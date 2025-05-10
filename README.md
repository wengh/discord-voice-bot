# discord-voice-bot

## Installation

### Initial setup

1. Clone this repository:
   ```bash
   git clone https://github.com/wengh/discord-voice-bot.git
   cd discord-voice-bot
   ```

2. Create a `.env` file with your Discord bot token:
   ```
   BOT_TOKEN=your_token_here
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
