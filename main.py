import os, config
import discord
import logging
import time

import asyncio
from discord.ext import commands
from keep_alive import keep_alive
from tortoise import Tortoise
from shapesinc import (
  shape,
  AsyncShape,
  ShapeUser as User,
  ShapeChannel as Channel
)

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
SHAPES_API_KEY = os.environ.get("SHAPES_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
MODEL = "otahun"
# BASE_URL = os.environ.get("SHAPES_API_URL")
SHAPES_APP_ID = os.environ.get("SHAPES_APP_ID")

if not SHAPES_API_KEY:
    raise ValueError("SHAPES_API_KEY environment variable is not set.")
if not SHAPES_APP_ID:
    raise ValueError("SHAPES_APP_ID environment variable is not set.")

# print("shapes api key:", SHAPES_API_KEY)
# print("shapes app id:", SHAPES_APP_ID)
# print("discord token:", DISCORD_TOKEN)
# Initialize Shapes API client for testing
shapes = shape(SHAPES_API_KEY, MODEL, SHAPES_APP_ID, synchronous=False)

user = User("0")
# channel = Channel("0")
# ─── BOT SETUP ─────────────────────────────────────────────────────────────────
class AIChatBot(commands.Bot):
    shape: AsyncShape
    def __init__(self):
        intents = discord.Intents.all()
        
        super().__init__(
          command_prefix='$',  # You can change this prefix as needed
          intents=intents,
          # help_command=None  # Disable default help command if you want
        )

    async def setup_hook(self):
        """Called when the bot is starting up"""
        try:
          # Load the AI chatbot cog
            await self.load_extension("ai_chatbot_cog")
            await self.load_extension("jishaku")
            logging.info("✅ AI Chatbot cog loaded successfully")
            await Tortoise.init(config=config.tortoise)
            # await Tortoise.generate_schemas(safe=True)
            logging.info("✅ DB loaded!")
      
        
            await self.tree.sync()
            logging.info("✅ Slash commands synced")
        except Exception as e:
            # logging.error(f"❌ Failed to load cog: {e}")
            raise e

  
    @property
    def pool(self):
        try:
            return Tortoise.get_connection("default")._pool
        except:
            return None
          
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

  try:
    async def test():
      await shapes.prompt(
        "test"
        # user=user
        # channel=channel
      )
      logging.info("✅ Shapes API connection successful")
    asyncio.run(test())
  except Exception as e:
    logging.error(f"❌ Shapes API connection failed: {e}")
    print(SHAPES_APP_ID)
    # print(e.data)
    raise e
    return

  # Start the bot with retry logic
  retry, max_retries = 0, 3
  while retry < max_retries:
    try:
      logging.info(f"🚀 Starting bot (attempt {retry+1}/{max_retries})")
      bot = AIChatBot()
      bot.owner_ids=[730454267533459568, 768493364181336104]
      bot.shape=shapes
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
