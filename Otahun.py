import os
import discord
import asyncio
import logging
from openai import OpenAI as RawOpenAI

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
SHAPES_API_KEY = os.environ["SHAPES_API_KEY"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
BASE_URL = "https://your.shapes.api.host/v1"
MAX_CHARS = 2000

# Initialize raw OpenAI client if needed elsewhere
shapes = RawOpenAI(api_key=SHAPES_API_KEY, base_url=BASE_URL)

# ─── UTILITY ────────────────────────────────────────────────────────────────────
def chunk_text(text: str, max_size: int = MAX_CHARS) -> list[str]:
    """Split text into ≤ max_size chunks at newlines or spaces."""
    chunks = []
    while len(text) > max_size:
        pos = text.rfind("\n", 0, max_size) or text.rfind(" ", 0,
                                                          max_size) or max_size
        chunks.append(text[:pos].strip())
        text = text[pos:].strip()
    if text:
        chunks.append(text)
    return chunks

# ─── DISCORD CLIENT ─────────────────────────────────────────────────────────────
class MyClient(discord.Client):

    async def on_ready(self):
        logging.info(f"Logged in as {self.user} (ID: {self.user.id})")
        print("i'm in")
        print(self.user)

    async def on_message(self, message: discord.Message):
        # ignore the bot itself
        if message.author.id == self.user.id:
            return

        # only respond when mentioned
        if self.user in message.mentions:
            prompt = message.content.replace(f"<@!{self.user.id}>", "").strip()
            prompt = prompt.replace(f"<@{self.user.id}>", "").strip()
            channel = message.channel

            try:
                async with channel.typing():
                    # Replace this block with direct OpenAI calls via shapes
                    response = shapes.chat.completions.create(
                        model="shapesinc/otahun",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    reply = response.choices[0].message.content
                    await asyncio.sleep(0.2)

                for part in chunk_text(reply):
                    await channel.send(part)

            except Exception as e:
                logging.exception(f"Error generating response: {e}")
                await channel.send(
                    "⚠️ Something went wrong. Please try again later.")

# ─── MAIN ENTRYPOINT ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    intents = discord.Intents.default()
    intents.message_content = True  # required intent
    MyClient(intents=intents).run(DISCORD_TOKEN)
