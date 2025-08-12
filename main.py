import logging
import os
import queue
import re
import time
from collections import Counter
from typing import Optional

import discord
import edge_tts
import edge_tts.constants
import miniaudio
import requests
from discord import Option, OptionChoice
from dotenv import load_dotenv
from edge_tts.exceptions import NoAudioReceived
from edge_tts.typing import Voice
from urllib.parse import urljoin

load_dotenv()

logger = logging.getLogger(__name__)


intents: discord.Intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = discord.Bot(intents=intents)

CLOUDFLARE_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL")


DEFAULT_VOICE = os.getenv("EDGE_TTS_VOICE", edge_tts.constants.DEFAULT_VOICE)


def get_from_kv_store(key: str) -> str:
    try:
        response = requests.get(urljoin(CLOUDFLARE_WORKER_URL, f"kv/{key}"))

        if response.status_code == 404:
            logger.debug(f"Key '{key}' not found in KV store. Using default voice.")
            return DEFAULT_VOICE
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching key '{key}' from KV store: {e}")
        return DEFAULT_VOICE


def set_in_kv_store(key: str, value: str) -> bool:
    try:
        response = requests.put(
            urljoin(CLOUDFLARE_WORKER_URL, f"kv/{key}"),
            data=value,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()  # Raise an exception for HTTP errors
    except requests.exceptions.RequestException as e:
        logger.error(f"Error setting key '{key}' in KV store: {e}")
        raise


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
        await ctx.send_response("Join a voice channel first!", ephemeral=True)
        return

    voice_channel = ctx.author.voice.channel

    # Check permissions
    permissions = voice_channel.permissions_for(guild.me)

    perms_status = {
        "view channel": permissions.view_channel,
        "connect": permissions.connect,
        "speak": permissions.speak,
    }
    missing = [p for p, v in perms_status.items() if not v]

    if missing:
        await ctx.send_response(
            f"Missing permissions in <#{voice_channel.id}>: {', '.join(missing)}",
            ephemeral=True,
        )
        return

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

    await ctx.respond(
        f"Joined <#{voice_channel.id}>! I will read messages out loud.", ephemeral=True
    )


@bot.slash_command()
async def leave(ctx: discord.ApplicationContext) -> None:
    """Leave the voice channel."""
    if not ctx.voice_client:
        await ctx.respond("I am not connected to a voice channel.", ephemeral=True)
        return
    channel_id = ctx.voice_client.channel.id
    await ctx.voice_client.disconnect()
    await ctx.respond(f"Disconnected from <#{channel_id}>.", ephemeral=True)


_voices_cache: list[Voice] | None = None


async def list_voices() -> list[Voice]:
    global _voices_cache
    if _voices_cache is None:
        _voices_cache = await edge_tts.list_voices()
        logger.info(f"Cached {len(_voices_cache)} voices from Edge TTS.")
    return _voices_cache


async def list_languages(ctx: discord.AutocompleteContext) -> list[str]:
    keyword = ctx.options["language"]
    languages = Counter()
    for voice in await list_voices():
        if keyword in voice["Locale"]:
            languages[voice["Locale"]] += 1
    # Sort by number of voices
    return [k for k, v in languages.most_common(25)]


async def list_voices_for_language(
    ctx: discord.AutocompleteContext,
) -> list[discord.OptionChoice]:
    language = ctx.options["language"]
    is_valid = language in await list_languages(ctx)
    choices: list[discord.OptionChoice] = []
    for voice in await list_voices():
        if not is_valid or voice["Locale"] == language:
            short_name = (
                voice["ShortName"]
                .removeprefix(voice["Locale"] + "-")
                .removesuffix("Neural")
            )
            gender = voice["Gender"]
            personalities = voice["VoiceTag"]["VoicePersonalities"]
            categories = voice["VoiceTag"]["ContentCategories"]
            description = f"{gender}: {short_name} ({', '.join(personalities)}) ({', '.join(categories)})"
            choices.append(
                OptionChoice(
                    name=description,
                    value=voice["ShortName"],
                )
            )
    choices.sort(key=lambda x: x.name)
    return choices


@bot.slash_command()
async def set_language(
    ctx: discord.ApplicationContext,
    language: str = Option(
        str,
        "Select a language",
        required=True,
        autocomplete=list_languages,
    ),
    voice: str = Option(
        str,
        "Select a voice",
        required=True,
        autocomplete=list_voices_for_language,
    ),
):
    """Set the language and voice for your current voice channel."""
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.respond(
            "You must be in a voice channel to set your language and voice.",
            ephemeral=True,
        )
        return

    channel_id = ctx.author.voice.channel.id
    key = str(channel_id)
    if voice not in [v["ShortName"] for v in await list_voices()]:
        await ctx.respond(
            f"Voice `{voice}` is not available. Please select a valid voice.",
            ephemeral=True,
        )
        return

    try:
        set_in_kv_store(key, voice)
        await ctx.respond(
            f"Set voice for <#{channel_id}> to `{voice}`.",
            ephemeral=False,
        )
    except requests.exceptions.RequestException as e:
        await ctx.respond(
            f"Failed to set voice for <#{channel_id}>. Error: {e}",
            ephemeral=True,
        )


@bot.slash_command()
async def language_samples(ctx: discord.ApplicationContext):
    """Listen to audio samples of available voices."""
    ctx.respond(
        "https://geeksta.net/tools/tts-samples/",
        ephemeral=True,
    )


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
        voice_client = message.guild.voice_client
        content = message.clean_content
        content = _clean_emojis(content)
        if not content:
            logger.info("Skipping empty message.")
            return
        try:
            logger.info(f"Converting message to speech: {content}")
            voice = get_from_kv_store(str(voice_client.channel.id))
            communicate = edge_tts.Communicate(content, voice)
            file = QueueSource()

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
