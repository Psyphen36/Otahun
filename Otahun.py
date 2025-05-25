import os
import discord
import asyncio
import logging
import json
import time
from discord import app_commands
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
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

# ─── DATA STRUCTURES ───────────────────────────────────────────────────────────
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
    recent_messages: List[Dict[str, any]]
    last_cleanup: datetime

# ─── UTILITY FUNCTIONS ─────────────────────────────────────────────────────────
def chunk_text(text: str, max_size: int = MAX_CHARS) -> List[str]:
    if len(text) <= max_size:
        return [text]
    chunks, current_chunk = [], ""
    paragraphs = text.split('\n\n')
    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) + 2 > max_size and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = ""
        if len(paragraph) > max_size:
            for sentence in paragraph.split('. '):
                if len(current_chunk) + len(sentence) + 2 > max_size and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                current_chunk += sentence + ". "
        else:
            current_chunk += paragraph + "\n\n"
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    return chunks


def extract_code_blocks(text: str) -> List[str]:
    import re
    return re.findall(r'```[\s\S]*?```', text)


def format_for_discord(text: str) -> str:
    lines = text.split('\n')
    formatted_lines, in_code_block = [], False
    for line in lines:
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
        formatted_lines.append(line)
    return '\n'.join(formatted_lines)

# ─── ENHANCED DISCORD CLIENT ──────────────────────────────────────────────────
class AdvancedChatBot(discord.Client):
    def __init__(self, *args, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.reactions = True
        intents.typing = True
        super().__init__(intents=intents, **kwargs)
        self.active_channels: Set[int] = set()
        self.tree = app_commands.CommandTree(self)
        self.user_sessions: Dict[int, UserSession] = {}
        self.user_contexts: Dict[tuple[int,int], ChannelContext] = {}
        self.rate_limits: Dict[int, List[datetime]] = {}

    async def setup_hook(self):
        # Register the /active command when the bot is ready
        self.tree.add_command(self.active)
        await self.tree.sync()

    @app_commands.command(
        name="active",
        description="Toggle active listening in this channel"
        )
    
    async def active(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        if cid in self.active_channels:
            self.active_channels.remove(cid)
            await interaction.response.send_message(
                f"🔕 I will now ignore this channel.", ephemeral=True
            )
        else:
            self.active_channels.add(cid)
            await interaction.response.send_message(
                f"✅ I am now active in this channel!", ephemeral=True
            )

    async def on_ready(self):
        logging.info(f"🤖 {self.user} is now online!")
        logging.info(f"📊 Connected to {len(self.guilds)} servers")
        print(f"✅ Bot ready! Logged in as {self.user}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, 
                name='''Hey i'm Otahun ozz is my creator
                '''
            )
        )

    async def on_message(self, message: discord.Message):
        # never respond to yourself
        if message.author.id == self.user.id:
            return

        # ——— Prefix-based activation toggles ———
        raw = message.content.strip()
        for fmt in (f"<@!{self.user.id}>", f"<@{self.user.id}>"):
            if raw.startswith(fmt):
                raw = raw[len(fmt):].strip()
        if raw.startswith("$activate"):
            cid = message.channel.id
            if cid not in self.active_channels:
                self.active_channels.add(cid)
                await message.channel.send("✅ Activated: I'll now listen here without a mention.")
            else:
                await message.channel.send("⚠️ I'm already activated in this channel.")
            return
        if raw.startswith("$deactivate"):
            cid = message.channel.id
            if cid in self.active_channels:
                self.active_channels.remove(cid)
                await message.channel.send("🔕 Deactivated: back to mention-only mode.")
            else:
                await message.channel.send("⚠️ I'm not currently activated here.")
            return
        try:
            # check for explicit @mention
            is_mentioned = self.user in message.mentions

            # check if this is a reply to one of the bot’s messages
            is_reply_to_bot = False
            if message.reference and message.reference.message_id:
                try:
                    ref = await message.channel.fetch_message(message.reference.message_id)
                    if ref.author.id == self.user.id:
                        is_reply_to_bot = True
                except Exception:
                    pass

            is_active = message.channel.id in self.active_channels
            if not is_active:
                # in “mention” mode, bail unless we’re mentioned or replied‐to
                if not (is_mentioned or is_reply_to_bot):
                    return
            # in active mode we drop the “other-bot” check so we can chat with other bots

            # rate-limit, context updates, AI call, etc. continue here...
            if not await self._check_rate_limit(message.author.id):
                await message.reply("⏰ Please slow down! You're sending messages too quickly.")
                return
            await self._update_user_session(message.author)
            # pick (channel, user) as the context key:
            ctx_key = (message.channel.id, message.author.id)
            channel_context = await self._get_user_context(ctx_key)

            async with message.channel.typing():
                response = await self._process_message(message, channel_context)
                await asyncio.sleep(TYPING_DELAY)

            await self._send_response(message, response)
            await self._update_channel_context(message, response, channel_context, ctx_key)
            return

        except Exception as e:
            logging.exception(f"Critical error in on_message: {e}")
            try:
                await self._send_error_response(message.channel, e)
            except Exception as err:
                logging.error(f"Failed to send error response: {err}")

    async def _check_rate_limit(self, user_id: int) -> bool:
        now = datetime.now()
        self.rate_limits.setdefault(user_id, [])
        self.rate_limits[user_id] = [t for t in self.rate_limits[user_id] if now - t < timedelta(minutes=1)]
        if len(self.rate_limits[user_id]) >= RATE_LIMIT_REQUESTS:
            return False
        self.rate_limits[user_id].append(now)
        return True

    async def _update_user_session(self, author: discord.User):
        now = datetime.now()
        sess = self.user_sessions.get(author.id)
        if sess:
            sess.last_activity = now
        else:
            self.user_sessions[author.id] = UserSession(
                user_id=author.id,
                username=str(author),
                display_name=getattr(author, 'display_name', str(author)),
                last_activity=now,
                request_count=0,
                request_reset_time=now + timedelta(hours=1)
            )

    async def _get_user_context(self, ctx_key: tuple[int,int]) -> ChannelContext:
        """
        Returns the per-(channel, user) context,
        so each user’s history is kept separate.
        """
        if ctx_key not in self.user_contexts:
            ch_id, usr_id = ctx_key
            self.user_contexts[ctx_key] = ChannelContext(
                channel_id=ch_id,
                recent_messages=[],
                last_cleanup=datetime.now()
            )
        return self.user_contexts[ctx_key]

    async def _process_message(self, message: discord.Message, context: ChannelContext) -> str:
        # msgs = []
        try:
            content = message.content
            for mention in message.mentions:
                content = content.replace(f'<@!{mention.id}>', f'@{mention.display_name}')
                content = content.replace(f'<@{mention.id}>', f'@{mention.display_name}')
            content = content.strip()

            # Build messages without system prompt (offloaded to Shapes API)
            messages: List[Dict[str, str]] = []
            try:
                for m in context.recent_messages:
                    messages.append({"role": "user", "content": f"{m['author']}: {m['content']}"})
                recent_context = self._build_context_messages(context, message.channel)
                messages.extend(recent_context)
            except Exception:
                pass
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
                # always include the replied‐to text as context
                reply_text = ref.content or ""
                reply_context = f"[Replying to {ref.author.display_name}]: {reply_text[:500]}"
                messages.append({"role":"user","content": reply_context})

                # optional: also include any attachments or stickers
                for att in ref.attachments:
                    messages.append({"role":"user","content": f"[Attachment] {att.url}"})
                if hasattr(ref, 'stickers'):
                    for st in ref.stickers:
                        url = f"https://cdn.discordapp.com/stickers/{st.id}.png"
                        messages.append({"role":"user","content": f"[Sticker] {st.name} {url}"})
            except Exception:
                pass

            # include current message attachements
            if message.attachments:
                for att in message.attachments:
                    messages.append({"role": "user", "content": f"[Attachment] {att.url}"})
            # include current message stickers
            if hasattr(message, 'stickers') and message.stickers:
                for st in message.stickers:
                    url = f"https://cdn.discordapp.com/stickers/{st.id}.png"
                    messages.append({"role": "user", "content": f"[Sticker] {st.name} {url}"})

            user_msg = f"[BOT] {message.author.display_name}: {content}" if message.author.bot else f"{message.author.display_name}: {content}"
            messages.append({"role": "user", "content": user_msg})
        

            logging.info(f"🔄 Sending request to Shapes API for user {message.author} in channel {message.channel.id}")
            api_result = await asyncio.to_thread(
                shapes.chat.completions.create,
                model="shapesinc/otahun",
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                # pass the Discord user ID (or any string that uniquely identifies them)
                user=str(message.author.id),

            )
            logging.info(f"✅ Received response from Shapes API ({len(api_result.choices)} choice(s))")
            return api_result.choices[0].message.content

        except Exception as e:
            logging.error(f"AI processing error: {e}")
            return "I'm having trouble processing your message right now. Could you try again?"

    def _build_context_messages(self, context: ChannelContext, channel) -> List[Dict[str,str]]:
        return []

    async def _send_response(self, message: discord.Message, response: str):
        try:
            if not response.strip(): response = "I'm not sure how to respond to that."
            formatted = format_for_discord(response)
            for i, chunk in enumerate(chunk_text(formatted)):
                # small pause between multi-part replies
                if i > 0:
                    await asyncio.sleep(0.5)

                # for the first chunk reply to the user; subsequent chunks can also reply
                await message.reply(chunk, mention_author=True)
        except Exception as e:
            logging.error(f"Send response error: {e}")
            try: await channel.send("❌ I had trouble sending my response. Please try again.")
            except: pass

    async def _update_channel_context(self, message, response, context: ChannelContext, ctx_key: tuple[int,int]):
        context.recent_messages.append({
            'author': message.author.display_name,
            'content': message.content[:500],
            'timestamp': datetime.now(),
            'message_id': message.id
        })
        # trim old memories
        if len(context.recent_messages) > MAX_CONTEXT_MESSAGES:
            context.recent_messages = context.recent_messages[-MAX_CONTEXT_MESSAGES:]
        # no need to re-assign back, since context is a mutable object

    async def _send_error_response(self, channel, error: Exception):
        opts = [
            "🤔 I'm having trouble processing that right now. Could you try rephrasing?",
            "⚠️ Something went wrong on my end. Please try again in a moment.",
            "🔧 I encountered an issue. Let me know if this keeps happening!",
        ]
        import random; resp = random.choice(opts)
        logging.error(f"Error details: {error}")
        await channel.send(resp)

    async def on_message_edit(self, before, after): pass
    async def on_reaction_add(self, reaction, user):
        if user.id == self.user.id: return
        if reaction.emoji == "👍" and reaction.message.author == self.user:
            logging.info(f"Positive feedback from {user} on: {reaction.message.content[:50]}...")
    async def on_typing(self, channel, user, when): pass


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    if not SHAPES_API_KEY:
        logging.error("❌ SHAPES_API_KEY not set!"); return
    if not DISCORD_TOKEN:
        logging.error("❌ DISCORD_TOKEN not set!"); return
    try:
        test = shapes.chat.completions.create(model="shapesinc/otahun", messages=[{"role":"user","content":"test"}], max_tokens=5)
        logging.info("✅ Shapes API connection successful")
    except Exception as e:
        logging.error(f"❌ Shapes API connection failed: {e}"); return
    retry, max_r = 0,3
    while retry < max_r:
        try:
            logging.info(f"🚀 Starting bot (attempt {retry+1}/{max_r})")
            bot = AdvancedChatBot()
            bot.run(DISCORD_TOKEN)
            break
        except discord.LoginFailure:
            logging.error("❌ Failed to login. Check your token."); break
        except discord.HTTPException as e:
            logging.error(f"❌ Discord HTTP error: {e}"); retry+=1; time.sleep(5)
        except Exception as e:
            logging.exception(f"❌ Unexpected error: {e}"); retry+=1; time.sleep(5)
    if retry>=max_r:
        logging.error("❌ Max retries reached. Bot failed to start.")
    else:
        logging.info("👋 Bot shut down gracefully.")

if __name__ == "__main__":
    keep_alive()
    main()
