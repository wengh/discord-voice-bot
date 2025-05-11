import logging
import os
import queue
import re
import time
from typing import Optional

import discord
import edge_tts
import edge_tts.constants
import miniaudio
from dotenv import load_dotenv
from edge_tts.exceptions import NoAudioReceived

load_dotenv()

logger = logging.getLogger(__name__)


intents: discord.Intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = discord.Bot(intents=intents)


def _clean_emojis(text: str) -> str:
    """Turn Discord emojis into plain text."""
    text = re.sub(r"<a?:(\w+):\d+>", r"\1", text).strip()
    return text


class QueueSource(miniaudio.StreamableSource):
    """Producer-consumer queue for streaming audio data."""

    _eof = object()

    def __init__(self):
        self.q = queue.Queue[bytes]()
        self.buffer = bytearray()
        self.finished = False

    def write(self, data: bytes) -> int:
        self.q.put(data)
        return len(data)

    def read(self, size: int) -> bytes:
        if self.finished:
            return b""
        data = self.q.get()
        if data is self._eof:
            self.finished = True
            return b""
        return data

    def done(self):
        self.q.put(self._eof)


class MP3AudioSource(discord.AudioSource):
    """Reads MP3 data and decodes it in-process to 48 kHz stereo 16-bit PCM."""

    FRAME_DURATION_S = 0.020
    SAMPLE_RATE = 48000
    NCHANNELS = 2
    SAMPLES_PER_FRAME = int(SAMPLE_RATE * FRAME_DURATION_S)
    BYTES_PER_SAMPLE = 2  # 16-bit
    FRAME_SIZE_BYTES = SAMPLES_PER_FRAME * NCHANNELS * BYTES_PER_SAMPLE  # 3840

    def __init__(self, q: QueueSource):
        self.q = q
        self.started = False

    def start(self) -> None:
        self.started = True
        # prime decoder: 48 kHz, stereo, signed16, no dither, frame = SAMPLES_PER_FRAME
        self._pcm_gen = miniaudio.stream_any(
            source=self.q,
            source_format=miniaudio.FileFormat.MP3,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=self.NCHANNELS,
            sample_rate=self.SAMPLE_RATE,
            frames_to_read=self.SAMPLES_PER_FRAME,
            dither=miniaudio.DitherMode.NONE,
        )
        # skip initial dummy
        next(self._pcm_gen, None)

    def read(self) -> bytes:
        """Return exactly 20ms of PCM (3840 bytes), or b'' at end."""
        if not self.started:
            self.start()
        try:
            pcm_arr = next(self._pcm_gen)
        except StopIteration:
            return b""
        if not pcm_arr:
            return b""
        data = pcm_arr.tobytes()
        if len(data) < self.FRAME_SIZE_BYTES:
            return b""
        return data

    def cleanup(self) -> None:
        self._pcm_gen = None
        self._buffer = None

    def is_opus(self) -> bool:
        return False


@bot.event
async def on_ready() -> None:
    logger.info(f"We have logged in as {bot.user}")


@bot.slash_command()
async def join(ctx: discord.ApplicationContext) -> None:
    """Join the user's voice channel for TTS messages."""
    guild: discord.Guild = ctx.guild
    if not ctx.author.voice or not ctx.guild:
        await ctx.respond("Join a voice channel first!")
        return

    voice_channel = ctx.author.voice.channel

    logger.info(
        f"Invited to join #{voice_channel.name} in {guild.name} by {ctx.author.name}."
    )

    # Check if the bot is already in a voice channel
    if guild.voice_client is not None:
        await guild.voice_client.move_to(voice_channel)
    else:
        await voice_channel.connect()

    # Self-deaf the bot to let users know that it doesn't hear anything
    await guild.change_voice_state(
        channel=voice_channel, self_mute=False, self_deaf=True
    )

    await ctx.respond(f"Joined {voice_channel.name}! I will read messages out loud.")


@bot.slash_command()
async def leave(ctx: discord.ApplicationContext) -> None:
    """Leave the voice channel."""
    if not ctx.voice_client:
        await ctx.respond("I am not connected to a voice channel.")
        return
    await ctx.voice_client.disconnect()
    await ctx.respond("Disconnected from the voice channel.")


@bot.event
async def on_voice_state_update(
    member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
) -> None:
    """Monitor voice state changes and leave if bot is alone in the voice channel."""
    # Skip if it's the bot's own state change
    voice_client = member.guild.voice_client
    if not voice_client:
        return

    if member.id == bot.user.id:
        # Disconnect if the bot left the channel
        if before.channel != after.channel and voice_client.is_playing():
            logger.info(f"Interrupting voice playback for {member.name}.")
            voice_client.stop()
        return

    if voice_client.is_connected() and voice_client.channel:
        # Get all members in the voice channel except the bot
        members = [m for m in voice_client.channel.members if not m.bot]

        # If there are no non-bot members left, disconnect
        if len(members) == 0:
            await voice_client.disconnect()
            logger.info(
                f"Left voice channel {voice_client.channel.name} because it's empty."
            )


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        return

    # Check if the message is not a command, the bot is in a voice channel, and the message is from the voice channel's text chat
    if (
        message.guild
        and message.guild.voice_client
        and message.guild.voice_client.is_connected()
        and message.channel.id == message.guild.voice_client.channel.id
    ):
        content = message.clean_content
        content = _clean_emojis(content)
        if not content:
            logger.info("Skipping empty message.")
            return
        try:
            logger.info(f"Converting message to speech: {content}")
            voice = os.getenv("EDGE_TTS_VOICE", edge_tts.constants.DEFAULT_VOICE)
            communicate = edge_tts.Communicate(content, voice)
            file = QueueSource()

            voice_client = message.guild.voice_client

            # Check if voice client is already playing
            if voice_client.is_playing():
                voice_client.stop()

            # Play the audio
            future = voice_client.play(
                MP3AudioSource(file),
                wait_finish=True,
            )

            start = time.time()
            first = None
            try:
                async for chunk in communicate.stream():
                    # Start playing only when the first audio chunk is received
                    # to avoid unnecessarily starting ffmpeg process
                    if first is None:
                        first = time.time()
                    if future.done():
                        logger.info("Voice interrupted before stream finished.")
                        break
                    if chunk["type"] == "audio":
                        file.write(chunk["data"])
                done = time.time()
                if first is not None:
                    logger.info(
                        f"First chunk latency: {first - start:.2f}s, "
                        f"Total latency: {done - start:.2f}s"
                    )
            finally:
                file.done()
        except NoAudioReceived:
            # Silently ignore when no audio is received
            logger.info(f"No audio received for message: {message.content}")


if __name__ == "__main__":
    # Set up logging to show more info like timestamps
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load libopus.so from path specified in Dockerfile
    # Otherwise ctypes.util.find_library fails to find it in the container
    libopus_path = os.getenv("LIBOPUS_PATH")
    if libopus_path:
        discord.opus.load_opus(libopus_path)

    token: Optional[str] = os.getenv("BOT_TOKEN")
    if token is None:
        logger.error("BOT_TOKEN not found in environment variables.")

    bot.run(token)
