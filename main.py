import logging
import os
import queue
import re
from typing import Optional

import discord
import edge_tts
import edge_tts.constants
from dotenv import load_dotenv
from edge_tts.exceptions import NoAudioReceived

load_dotenv()

logger = logging.getLogger(__name__)


intents: discord.Intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = discord.Bot(intents=intents)


def _clean_emojis(text: str) -> str:
    """Remove Discord emojis from the text."""
    text = re.sub(r"<a?:(\w+):\d+>", r"\1", text).strip()
    return text


class QueueIO:
    """Producer-consumer queue for streaming audio data."""

    _eof = object()

    def __init__(self):
        self.q = queue.Queue()

    def write(self, data: bytes) -> int:
        self.q.put(data)
        return len(data)

    def read(self, size: Optional[int] = -1) -> bytes:
        data = self.q.get()
        if data is self._eof:
            return b""
        return data

    def done(self):
        self.q.put(self._eof)

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


@bot.event
async def on_ready() -> None:
    logger.info(f"We have logged in as {bot.user}")


@bot.slash_command()
async def join(ctx: discord.ApplicationContext) -> None:
    """Join the user's voice channel for TTS messages."""
    if not ctx.author.voice:
        await ctx.respond("Join a voice channel first!")
        return

    voice_channel = ctx.author.voice.channel

    # Check if the bot is already in a voice channel
    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(voice_channel)
    else:
        await voice_channel.connect()

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
        # Convert text to speech using Microsoft Edge TTS
        try:
            # Since we're already in an async function, we can await directly
            content = message.clean_content
            content = _clean_emojis(content)
            logger.info(f"Converting message to speech: {content}")
            voice = os.getenv("EDGE_TTS_VOICE", edge_tts.constants.DEFAULT_VOICE)
            communicate = edge_tts.Communicate(content, voice)
            file = QueueIO()

            voice_client = message.guild.voice_client

            # Check if voice client is already playing
            if voice_client.is_playing():
                voice_client.stop()

            # Play the audio
            future = voice_client.play(
                discord.FFmpegPCMAudio(file, pipe=True),
                wait_finish=True,
            )

            try:
                async for chunk in communicate.stream():
                    if future.done():
                        logger.info("Voice interrupted before stream finished.")
                        break
                    if chunk["type"] == "audio":
                        file.write(chunk["data"])
            finally:
                file.done()

            await future
        except NoAudioReceived:
            # Silently ignore when no audio is received
            logger.error(f"No audio received for message: {message.content}")


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
