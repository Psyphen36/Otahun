import os
import discord
import asyncio
import logging
from openai import OpenAI as RawOpenAI
from keep_alive import keep_alive

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
SHAPES_API_KEY = os.environ["SHAPES_API_KEY"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
BASE_URL = "https://api.shapes.inc/v1/"
MAX_CHARS = 2000

# Initialize raw OpenAI client if needed elsewhere
shapes = RawOpenAI(api_key=SHAPES_API_KEY, base_url=BASE_URL)
keep_alive()
# ─── UTILITY ────────────────────────────────────────────────────────────────────
def chunk_text(text: str, max_size: int = MAX_CHARS) -> list[str]:
    """Split text into ≤ max_size chunks at newlines or spaces."""
    chunks = []
    while len(text) > max_size:
        pos = text.rfind("\n", 0, max_size) or text.rfind(" ", 0, max_size) or max_size
        chunks.append(text[:pos].strip())
        text = text[pos:].strip()
    if text:
        chunks.append(text)
    return chunks

# ─── DISCORD CLIENT ─────────────────────────────────────────────────────────────
class MyClient(discord.Client):
    def __init__(self, *args, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        super().__init__(intents=intents, **kwargs)
        # Maintain conversation history per user
        self.histories: dict[int, list[dict[str, str]]] = {}

    async def on_ready(self):
        logging.info(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Bot is online!")

    async def on_message(self, message: discord.Message):
        # ignore the bot itself or messages where it's not mentioned
        if message.author.id == self.user.id or self.user.id not in [u.id for u in message.mentions]:
            return

        user_id = message.author.id
        channel = message.channel

        # Initialize history if first interaction
        if user_id not in self.histories:
            system_prompt = (
                f"You are a helpful assistant chatting with {message.author.display_name}"
                f" (username: {message.author}). Remember their name and speak accordingly."
            )
            self.histories[user_id] = [{"role": "system", "content": system_prompt}]

        # Build the context messages list fresh for this call
        messages = list(self.histories[user_id])

        # If replying to someone else, include their message as user context
        if message.reference and message.reference.message_id:
            try:
                ref_msg = await channel.fetch_message(message.reference.message_id)
                context_content = f"{ref_msg.author.display_name} said: {ref_msg.content}"
                logging.info(f"Adding reply context for user {user_id}: {context_content}")
                messages.append({"role": "user", "content": context_content})
            except Exception as e:
                logging.warning(f"Could not fetch referenced message: {e}")

        # Extract the user's prompt (strip mention)
        prompt = message.content
        # remove all mention forms
        prompt = prompt.replace(f"<@!{self.user.id}>", "").replace(f"<@{self.user.id}>", "").strip()
        messages.append({"role": "user", "content": prompt})

        try:
            async with channel.typing():
                # call Shapes chat completion with constructed history
                response = shapes.chat.completions.create(
                    model="shapesinc/otahun",
                    messages=messages
                )
                reply = response.choices[0].message.content
                await asyncio.sleep(0.2)

            # update stored history with new messages
            self.histories[user_id].extend(messages[len(self.histories[user_id]):])
            self.histories[user_id].append({"role": "assistant", "content": reply})

            # send the reply in manageable chunks
            for part in chunk_text(reply):
                await channel.send(part)

        except Exception as e:
            logging.exception(f"Error generating response: {e}")
            await channel.send("⚠️ Something went wrong. Please try again later.")

# ─── MAIN ENTRYPOINT ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    MyClient().run(DISCORD_TOKEN)
