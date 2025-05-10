import os
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio

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
    """Join the user's voice channel and play an audio file."""
    if not ctx.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return

    voice_channel = ctx.author.voice.channel

    # Check if the bot is already in a voice channel
    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(voice_channel)
    else:
        voice_client = await voice_channel.connect()

    # Get voice client if we didn't just connect
    voice_client = ctx.voice_client or voice_client

    # Path to the audio file
    audio_file = os.path.join(r"/mnt/c/repos/MeowyPlayer/music/Pluie sur la ville.mp3")

    # Check if the file exists
    if not os.path.exists(audio_file):
        await ctx.send(
            f"Joined {voice_channel.name}! (Audio file not found: {audio_file})"
        )
        return

    # Play the audio file
    voice_client.play(discord.FFmpegPCMAudio(audio_file))

    await ctx.send(f"Joined {voice_channel.name} and playing welcome audio!")


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        return

    if message.content.startswith("$hello"):
        await message.channel.send("Hello!")

    # Process commands
    await bot.process_commands(message)


token: Optional[str] = os.getenv("BOT_TOKEN")
if token is not None:
    bot.run(token)
else:
    print("Error: BOT_TOKEN not found in environment variables.")
