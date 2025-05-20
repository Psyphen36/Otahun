import os
import discord
import asyncio
import logging
from openai import OpenAI as RawOpenAI
from keep_alive import keep_alive

# LangGraph / Runnable imports
from pydantic import BaseModel, Field  # data model
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage  # message types
from langchain_core.chat_history import BaseChatMessageHistory  # history interface
from langchain_core.runnables.history import RunnableWithMessageHistory  # manages history
from langchain_openai.chat_models import ChatOpenAI  # chat LLM

# ─── KEEP THE BOT ALIVE ─────────────────────────────────────────────────────────
keep_alive()

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
SHAPES_API_KEY = os.environ["SHAPES_API_KEY"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
BASE_URL = os.environ[
    "BASE_URL"]  # e.g. https://generativelanguage.googleapis.com/v1beta/openai/
MAX_CHARS = 2000

# Initialize raw OpenAI client if needed elsewhere
shapes = RawOpenAI(api_key=SHAPES_API_KEY, base_url=BASE_URL)


# ─── IN-MEMORY SESSION HISTORY ───────────────────────────────────────────────────
class InMemoryHistory(BaseChatMessageHistory, BaseModel):
    """Simple in-memory chat history (for testing / ephemeral use)."""
    messages: list[BaseMessage] = Field(default_factory=list)

    def add_messages(self, messages: list[BaseMessage]) -> None:
        self.messages.extend(messages)

    def clear(self) -> None:
        self.messages = []


# Create a dictionary to store chat histories
chat_histories = {}


# Function to get or create a chat history for a session
def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in chat_histories:
        chat_histories[session_id] = InMemoryHistory()
    return chat_histories[session_id]


# Create the chat model
chat_model = ChatOpenAI(api_key=SHAPES_API_KEY,
                        base_url=BASE_URL,
                        model="shapesinc/otahun")

# Wrap the chat model in a Runnable that auto-loads/saves history per session_id
runnable = RunnableWithMessageHistory(
    runnable=chat_model,  # This was missing in your original code
    get_session_history=get_session_history,
)


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

    async def on_message(self, message: discord.Message):
        # ignore the bot itself
        if message.author.id == self.user.id:
            return

        # only respond when mentioned
        if self.user in message.mentions:
            prompt = message.content.replace(f"<@!{self.user.id}>", "").strip()
            # Also handle non-nickname mentions
            prompt = prompt.replace(f"<@{self.user.id}>", "").strip()
            channel = message.channel
            session_id = str(channel.id)

            try:
                async with channel.typing():
                    # Invoke with automatic history: pass new user turn + session config
                    ai_msg = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: runnable.invoke(HumanMessage(content=prompt), {
                            "configurable": {
                                "session_id": session_id
                            }
                        }))
                    reply = ai_msg.content  # AIMessage → text
                    await asyncio.sleep(0.2)

                for part in chunk_text(reply):
                    await channel.send(part)

            except Exception as e:
                logging.exception(f"Error in RunnableWithMessageHistory: {e}")
                await channel.send(
                    "⚠️ Something went wrong. Please try again later.")


# ─── MAIN ENTRYPOINT ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    intents = discord.Intents.default()
    intents.message_content = True  # required intent
    MyClient(intents=intents).run(DISCORD_TOKEN)
