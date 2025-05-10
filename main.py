import os
from typing import Optional

import discord
from dotenv import load_dotenv

load_dotenv()  # take environment variables


intents: discord.Intents = discord.Intents.default()
intents.message_content = True

client: discord.Client = discord.Client(intents=intents)


@client.event
async def on_ready() -> None:
    print(f"We have logged in as {client.user}")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user:
        return

    if message.content.startswith("$hello"):
        await message.channel.send("Hello!")


token: Optional[str] = os.getenv("BOT_TOKEN")
if token is not None:
    client.run(token)
else:
    print("Error: BOT_TOKEN not found in environment variables.")
