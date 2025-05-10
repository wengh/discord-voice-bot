import os
import re
import tempfile
from typing import Optional

import discord
import edge_tts
from dotenv import load_dotenv
from edge_tts.exceptions import NoAudioReceived

load_dotenv()


intents: discord.Intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = discord.Bot(command_prefix="$", intents=intents)


def _clean_emojis(text: str) -> str:
    """Remove Discord emojis from the text."""
    text = re.sub(r"<a?:(\w+):\d+>", r"\1", text).strip()
    return text


@bot.event
async def on_ready() -> None:
    print(f"We have logged in as {bot.user}")


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
    if member.id == bot.user.id:
        return

    # Loop through all voice clients the bot has
    for voice_client in bot.voice_clients:
        # Check if the voice client is connected and has a channel
        if voice_client.is_connected() and voice_client.channel:
            # Get all members in the voice channel except the bot
            members = [m for m in voice_client.channel.members if not m.bot]

            # If there are no non-bot members left, disconnect
            if len(members) == 0:
                await voice_client.disconnect()
                print(
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
        and message.channel.id == message.guild.voice_client.channel.id
    ):
        # Convert text to speech using Microsoft Edge TTS
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
                # Since we're already in an async function, we can await directly
                content = message.clean_content
                content = _clean_emojis(content)
                communicate = edge_tts.Communicate(content, "zh-CN-XiaoyiNeural")
                await communicate.save(tmp_file.name)

                voice_client = message.guild.voice_client

                # Check if voice client is already playing
                if voice_client.is_playing():
                    voice_client.stop()

                # Play the audio
                voice_client.play(
                    discord.FFmpegPCMAudio(tmp_file.name),
                    after=lambda e: os.remove(tmp_file.name),
                )
        except NoAudioReceived:
            # Silently ignore when no audio is received
            print(f"No audio received for message: {message.content}")


token: Optional[str] = os.getenv("BOT_TOKEN")
if token is not None:
    bot.run(token)
else:
    print("Error: BOT_TOKEN not found in environment variables.")
