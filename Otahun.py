import os
import discord
import logging
import time
from discord.ext import commands
from openai import OpenAI as RawOpenAI
from keep_alive import keep_alive

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
SHAPES_API_KEY = os.environ.get("SHAPES_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
MODEL = os.environ.get("MODEL")
BASE_URL = "https://api.shapes.inc/v1/"

# Initialize Shapes API client for testing
shapes = RawOpenAI(api_key=SHAPES_API_KEY, base_url=BASE_URL)

# ─── BOT SETUP ─────────────────────────────────────────────────────────────────
class AIChatBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.reactions = True
        intents.typing = True
        
        super().__init__(
            command_prefix='!',  # You can change this prefix as needed
            intents=intents,
            help_command=None  # Disable default help command if you want
        )

    async def setup_hook(self):
        """Called when the bot is starting up"""
        try:
            # Load the AI chatbot cog
            await self.load_extension('ai_chatbot_cog')
            logging.info("✅ AI Chatbot cog loaded successfully")
            
            # Load the image caption cog
            # await self.load_extension('image_caption_cog')
            # logging.info("✅ Image Caption cog loaded successfully")
            
            # Sync slash commands
            await self.tree.sync()
            logging.info("✅ Slash commands synced")
        except Exception as e:
            logging.error(f"❌ Failed to load cog: {e}")

    async def on_ready(self):
        logging.info(f"🤖 {self.user} is now online!")
        logging.info(f"📊 Connected to {len(self.guilds)} servers")
        print(f"✅ Bot ready! Logged in as {self.user}")

def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    # Validate environment variables
    if not SHAPES_API_KEY:
        logging.error("❌ SHAPES_API_KEY not set!")
        return
    if not DISCORD_TOKEN:
        logging.error("❌ DISCORD_TOKEN not set!")
        return

    # Test Shapes API connection
    try:
        test = shapes.chat.completions.create(
            model=f"{MODEL}",
            messages=[{"role":"user","content":"test"}], 
            max_tokens=5
        )
        logging.info("✅ Shapes API connection successful")
    except Exception as e:
        logging.error(f"❌ Shapes API connection failed: {e}")
        return

    # Start the bot with retry logic
    retry, max_retries = 0, 3
    while retry < max_retries:
        try:
            logging.info(f"🚀 Starting bot (attempt {retry+1}/{max_retries})")
            bot = AIChatBot()
            bot.run(DISCORD_TOKEN)
            break
        except discord.LoginFailure:
            logging.error("❌ Failed to login. Check your token.")
            break
        except discord.HTTPException as e:
            logging.error(f"❌ Discord HTTP error: {e}")
            retry += 1
            time.sleep(5)
        except Exception as e:
            logging.exception(f"❌ Unexpected error: {e}")
            retry += 1
            time.sleep(5)

    if retry >= max_retries:
        logging.error("❌ Max retries reached. Bot failed to start.")
    else:
        logging.info("👋 Bot shut down gracefully.")

if __name__ == "__main__":
    keep_alive()
    main()
