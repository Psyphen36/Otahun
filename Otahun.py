import os
import discord
import asyncio
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any
from dataclasses import dataclass
from openai import OpenAI as RawOpenAI
from keep_alive import keep_alive

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
SHAPES_API_KEY = os.environ.get("SHAPES_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
BASE_URL = "https://api.shapes.inc/v1/"
MAX_CHARS = 2000
MAX_CONTEXT_MESSAGES = 10  # Number of recent messages to include for context
RATE_LIMIT_REQUESTS = 10    # Max requests per user per minute
TYPING_DELAY = 0.5         # Seconds to show typing indicator

# Initialize Shapes API client
shapes = RawOpenAI(api_key=SHAPES_API_KEY, base_url=BASE_URL)

@dataclass
class UserSession:
    user_id: int
    username: str
    display_name: str
    last_activity: datetime
    request_count: int
    request_reset_time: datetime

@dataclass
class ChannelContext:
    channel_id: int
    recent_messages: List[Dict[str, Any]]
    last_cleanup: datetime


def chunk_text(text: str, max_size: int = MAX_CHARS) -> List[str]:
    if len(text) <= max_size:
        return [text]
    chunks, current = [], ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) > max_size:
            chunks.append(current.strip())
            current = ""
        if len(paragraph) > max_size:
            for sentence in paragraph.split('. '):
                if len(current) + len(sentence) > max_size:
                    chunks.append(current.strip())
                    current = ""
                current += sentence + ". "
        else:
            current += paragraph + "\n\n"
    if current:
        chunks.append(current.strip())
    return chunks

class AdvancedChatBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.user_sessions: Dict[int, UserSession] = {}
        self.channel_contexts: Dict[int, ChannelContext] = {}
        self.rate_limits: Dict[int, List[datetime]] = {}

    async def on_ready(self):
        logging.info(f"Bot logged in as {self.user}.")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="@mentions"))

    async def on_message(self, message: discord.Message):
        # 1) Ignore self messages
        if message.author.id == self.user.id:
            return

        # 2) Check trigger: mention or reply to bot
        mentioned = self.user in message.mentions
        is_reply_to = False
        if message.reference:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                if ref_msg.author.id == self.user.id:
                    is_reply_to = True
            except Exception:
                pass
        if not (mentioned or is_reply_to):
            return

        # 3) Rate limiting
        if not await self._check_rate_limit(message.author.id):
            await message.reply("⏰ Please slow down! You're sending messages too quickly.")
            return

        # 4) Build user session and context
        session = self.user_sessions.setdefault(
            message.author.id,
            UserSession(message.author.id, str(message.author), getattr(message.author, 'display_name', str(message.author)), datetime.now(), 0, datetime.now() + timedelta(hours=1))
        )
        context = self.channel_contexts.setdefault(
            message.channel.id,
            ChannelContext(message.channel.id, [], datetime.now())
        )

        # 5) Typing and process
        async with message.channel.typing():
            response = await self._process_message(message, context)
            await asyncio.sleep(TYPING_DELAY)

        # 6) Send in chunks
        for chunk in chunk_text(response):
            await message.channel.send(chunk)

        # 7) Update context history
        context.recent_messages.append({'author': message.author.display_name, 'content': message.content, 'timestamp': datetime.now()})
        if len(context.recent_messages) > MAX_CONTEXT_MESSAGES:
            context.recent_messages.pop(0)

    async def _check_rate_limit(self, user_id: int) -> bool:
        now = datetime.now()
        times = self.rate_limits.setdefault(user_id, [])
        times[:] = [t for t in times if now - t < timedelta(minutes=1)]
        if len(times) >= RATE_LIMIT_REQUESTS:
            return False
        times.append(now)
        return True

    async def _process_message(self, message: discord.Message, context: ChannelContext) -> str:
        msgs = []
        for m in context.recent_messages:
            msgs.append({"role": "user", "content": f"{m['author']}: {m['content']}"})
        content = message.content
        if message.author.bot:
            content = f"[BOT] {message.author.display_name}: {content}"
        msgs.append({"role": "user", "content": content})
        result = await asyncio.to_thread(
            shapes.chat.completions.create,
            model="shapesinc/otahun",
            messages=msgs,
            temperature=0.7,
            max_tokens=2000
        )
        return result.choices[0].message.content


def main():
    if not SHAPES_API_KEY or not DISCORD_TOKEN:
        logging.error("API keys not set; exiting.")
        return
    bot = AdvancedChatBot()
    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    keep_alive()
    main()
