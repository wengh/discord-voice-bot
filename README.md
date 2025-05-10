# discord-voice-bot

A very simple Discord bot that turns voice channel text chat messages into voice using edge-tts.

## Usage

1. Invite the bot to your server using by replacing `{APPLICATION_ID}` in the url with your bot's application ID.
   ```
   https://discord.com/oauth2/authorize?client_id={APPLICATION_ID}&permissions=0&integration_type=0&scope=bot
   ```

2. Join a voice channel in your server.

3. Use the `/join` slash command in the corresponding text channel to make the bot join the voice channel.

4. All text messages in the text channel will be converted to speech and played in the voice channel.

## Installation

### Initial setup

1. Clone this repository:
   ```bash
   git clone https://github.com/wengh/discord-voice-bot.git
   cd discord-voice-bot
   ```

2. Edit the `.env` file to set your bot token and edge-tts voice:
   ```bash
   cp .env.example .env
   nano .env
   ```

### Running the bot

#### Option 1: Using uv

1. Install uv if you haven't already:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Install ffmpeg if you haven't already:
   ```bash
   # For Ubuntu/Debian
   sudo apt update
   sudo apt install ffmpeg
   ```

3. Setup venv and run the bot:
   ```bash
   uv run main.py
   ```

#### Option 2: Using Docker

1. Install Docker and Docker Compose if you haven't already.

2. Build and start the Docker container:
   ```bash
   docker compose up -d
   ```
