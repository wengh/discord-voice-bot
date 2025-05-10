import os
import tempfile
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
from gtts import gTTS  # Google Text-to-Speech

load_dotenv()  # take environment variables


intents: discord.Intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

# Using commands.Bot instead of discord.Client for command handling
bot = commands.Bot(command_prefix="$", intents=intents)


@bot.event
async def on_ready() -> None:
    print(f"We have logged in as {bot.user}")


@bot.command(name="join")
async def join(ctx: commands.Context) -> None:
    """Join the user's voice channel for TTS messages."""
    if not ctx.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return

    voice_channel = ctx.author.voice.channel

    # Check if the bot is already in a voice channel
    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(voice_channel)
    else:
        await voice_channel.connect()

    await ctx.send(f"Joined {voice_channel.name}! I will read messages out loud.")


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        return

    if message.content.startswith("$hello"):
        await message.channel.send("Hello!")

    # Check if the message is not a command and the bot is in a voice channel
    if (
        not message.content.startswith(bot.command_prefix)
        and message.guild
        and message.guild.voice_client
    ):
        # Convert text to speech
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
            tts = gTTS(text=message.content, lang="en", slow=False)
            tts.save(tmp_file.name)

            voice_client = message.guild.voice_client

            # Check if voice client is already playing
            if voice_client.is_playing():
                voice_client.stop()

            # Play the audio
            voice_client.play(
                discord.FFmpegPCMAudio(tmp_file.name),
                after=lambda e: os.remove(tmp_file.name),
            )

    # Process commands
    await bot.process_commands(message)


token: Optional[str] = os.getenv("BOT_TOKEN")
if token is not None:
    bot.run(token)
else:
    print("Error: BOT_TOKEN not found in environment variables.")
