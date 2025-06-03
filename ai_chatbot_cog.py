import os
import discord
import asyncio
import logging
import json
import time
import re
import random
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from shapesinc import (
  Message,
  ShapeUser,
  ShapeChannel,
  ContentType
)
# ─── CONFIGURATION ─────────────────────────────────────────────────────────────

MAX_CHARS = 2000
MAX_CONTEXT_MESSAGES = 10  # Number of recent messages to include for context
RATE_LIMIT_REQUESTS = 10  # Max requests per user per minute
TYPING_DELAY = 0.4     # Seconds to show typing indicator
RESET_RE = re.compile(r'(?:^|\s)!reset(?=\s|$|[!.,?])', re.IGNORECASE)

# ─── NEW: Delay (in seconds) whenever we see another bot message ────────────────
BOT_DELAY_MIN = 40.0
BOT_DELAY_MAX = 200.0


# ─── KEYWORD TRIGGERS ─────────────────────────────────────────────────────────
# Keys are regex patterns; values are either static replies or callables
KEYWORD_TRIGGERS = [
  re.compile(r'\bserver down\b', re.IGNORECASE),
  re.compile(r'\bserver dead\b', re.IGNORECASE),
  re.compile(r'\bbug bounty\b', re.IGNORECASE),
  re.compile(r'\bhacking\b', re.IGNORECASE),
  re.compile(r'\bdiscord\b', re.IGNORECASE),
  re.compile(r'\botahun\b', re.IGNORECASE),
  re.compile(r'\bcoding\b', re.IGNORECASE),
  re.compile(r'\banime\b', re.IGNORECASE),
  re.compile(r'\bwaifu\b', re.IGNORECASE),
  re.compile(r'\bgeek\b', re.IGNORECASE),
  re.compile(r'\bnerd\b', re.IGNORECASE),
  re.compile(r'\bhelp\b', re.IGNORECASE),
  re.compile(r'\broast\b', re.IGNORECASE),
  re.compile(r'\bnarcissist\b', re.IGNORECASE),
  re.compile(r'\beveryone\b', re.IGNORECASE),
  re.compile(r'\banyone\b', re.IGNORECASE),
  re.compile(r'\bteach\b', re.IGNORECASE),
  re.compile(r'\bskill\b', re.IGNORECASE),
  re.compile(r'\bhack\b', re.IGNORECASE),
  re.compile(r'\bsolve this\b', re.IGNORECASE),
  re.compile(r'\bsolve\b', re.IGNORECASE),
  re.compile(r'\bmf\b', re.IGNORECASE)
]


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

# ─── AI CHATBOT COG ────────────────────────────────────────────────────────────
class AIChatbotCog(commands.Cog):
  def __init__(self, bot: commands.Bot):
    self.bot = bot
    self.shape = bot.shape
    self.active_channels: Set[int] = set()
    self.rate_limits: Dict[int, List[datetime]] = {}
    self.user_map = {}

  def user(self, id: int) -> ShapeUser:
    u=self.user_map.get(id)
    if u: return u
    self.user_map[id]=ShapeUser(str(id)[5:])
    return self.user(id)

  @app_commands.command(
    name="authorise",
    description="Authorise yourself!"
  )
  async def authorise(self, ctx, code: str = ""):
    user = self.user(ctx.user.id)
    url, auth = user.auth(self.shape)
    if not code:
      return await ctx.response.send_message(
        f"[Click Here]({url}) to get a code. Submit the code using `/authorise code:YOUR_CODE` to authorise yourself", ephemeral=True
      )
      
    try:
      await auth(code)
    except Exception as e:
      await ctx.response.send_message(
        f"Couldn't authorise you!", ephemeral=True
      )
      raise e
      
    return await ctx.response.send_message(
        f"Successfully authorises you!", ephemeral=True
      )
      
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

  @commands.command()
  async def deactivate(self, ctx, channel: discord.TextChannel = None):
    """Deactivates auto-chatbot in a channel!"""
    channel = channel or ctx.channel
    cid = channel.id
    if cid in self.active_channels:
      self.active_channels.remove(cid)
      return await ctx.reply("🔕 Deactivated: back to mention-only mode.")
      
    await ctx.reply("⚠️ I'm not currently activated here.")

  @commands.command()
  async def activate(self, ctx, channel: discord.TextChannel = None):
    """Activates auto-chatbot in a channel!"""
    channel = channel or ctx.channel
    cid = channel.id
    if cid not in self.active_channels:
      self.active_channels.add(cid)
      return await ctx.reply("✅ Activated: I'll now listen here without a mention.")

    await ctx.reply("⚠️ I'm already activated in this channel.")

  @commands.Cog.listener()
  async def on_ready(self):
    logging.info(f"🤖 AI Chatbot Cog loaded!")
    # Set bot presence
    await self.bot.change_presence(
      activity=discord.Activity(
        type=discord.ActivityType.listening, 
        name='''@ me 👂 | created by ozz'''
      )
    )

  @commands.Cog.listener()
  async def on_message(self, message: discord.Message):
    # ——— Prefix-based activation toggles ———
    raw = message.content
    if raw.startswith("$"): return

    # ─── NEVER RESPOND TO YOURSELF ───────────────────────────
    if message.author.id == self.bot.user.id:
      return

    # ─── KEYWORD TRIGGER DETECTION ────────────────────────────
    forced_active = False
    for regex in KEYWORD_TRIGGERS:
      if regex.search(message.content):
        forced_active = True
        break
    
    # ─── BLOCK RESET ────────────────────────────────────────────────────────
    if RESET_RE.search(raw):
      return await message.channel.send(
        "LoL you thought you have permission to reset my memory! "
        "In your dreams! <:smug:1358014214148591768>."
      )
    
    # ─────────────────────────────────────────────────────────────────────────

    try:
      # check for explicit @mention
      is_mentioned = self.bot.user in message.mentions

      # check if this is a reply to one of the bot's messages
      is_reply_to_bot = False
      if message.reference and message.reference.message_id:
        try:
          ref = await message.channel.fetch_message(message.reference.message_id)
          if ref.author.id == self.bot.user.id:
            is_reply_to_bot = True
        except Exception:
          pass

      is_active = message.channel.id in self.active_channels
      # If the channel is active, or we're mentioned/replied‐to, or
      # a keyword triggered, proceed; otherwise bail out.
      if not (is_active or is_mentioned or is_reply_to_bot or forced_active):
        return
      
      # ─── NEW: If the author is another bot, wait a bit before continuing ─────
      if message.author.bot:
        delay_seconds = random.uniform(BOT_DELAY_MIN, BOT_DELAY_MAX)
        logging.info(
          f"ℹ️ Detected bot→bot interaction; sleeping for {delay_seconds:.1f}s before responding."
        )
        await asyncio.sleep(delay_seconds)

      # rate-limit, context updates, AI call, etc. continue here...
      if not await self._check_rate_limit(message.author.id):
        await message.reply("⏰ Please slow down! You're sending messages too quickly.")
        return

      async with message.channel.typing():
        return await self._process(message)

    except Exception as e:
      logging.exception(f"Critical error in on_message: {e}")
      try:
        await self._send_error_response(message.channel, e)
      except Exception as err:
        logging.error(f"Failed to send error response: {err}")



  async def _process(self, message):
    try:
      content = message.content.strip()
      for st in message.stickers:
        content += " "+st.url

      files = []
      for att in message.attachments:
        c=att.content_type.split("/")[0]
        if c not in ["image", "audio"]: continue
        files.append(dict(
          type=getattr(ContentType, c),
          url=att.url
        ))
      logging.info(
        f"🔄 Sending request to Shapes API for user {message.author.id} "
        f"in channel {message.channel.id}"
      )
      res = await self.shape.prompt(
        Message.new(content, files),
        user = self.user(message.author.id),
        channel = ShapeChannel(str(message.channel.id)[5:])
      )
      for choice in res.choices:
        await self._send_response(message, str(choice.message))
        
      logging.info(
        f"✅ Received response from Shapes API ({len(res.choices)} choice(s))"
      )
    except Exception as e:
      logging.error(f"AI processing error: {e}")
      return await message.reply("I'm having trouble processing your message right now. Could you try again?",mention_author=True)

  async def _check_rate_limit(self, user_id: int) -> bool:
    now = datetime.now()
    self.rate_limits.setdefault(user_id, [])
    self.rate_limits[user_id] = [
      t for t in self.rate_limits[user_id] 
      if now - t < timedelta(minutes=1)
    ]
    if len(self.rate_limits[user_id]) >= RATE_LIMIT_REQUESTS:
      return False
    self.rate_limits[user_id].append(now)
    return True


  async def _send_response(self, message: discord.Message, response: str):
    try:
      if not response.strip(): 
        response = "I'm not sure how to respond to that."
      formatted = format_for_discord(response)
      for i, chunk in enumerate(chunk_text(formatted)):
        # small pause between multi-part replies
        if i > 0:
          await asyncio.sleep(0.5)

        # for the first chunk reply to the user; subsequent chunks can also reply
        await message.reply(chunk, mention_author=True)
    except Exception as e:
      logging.error(f"Send response error: {e}")
      try: 
        await message.channel.send("❌ I had trouble sending my response. Please try again.")
      except: 
        pass

  async def _send_error_response(self, channel, error: Exception):
    opts = [
      "🤔 I'm having trouble processing that right now. Could you try rephrasing?",
      "⚠️ Something went wrong on my end. Please try again in a moment.",
      "🔧 I encountered an issue. Let me know if this keeps happening!",
    ]
    import random
    resp = random.choice(opts)
    logging.error(f"Error details: {error}")
    await channel.send(resp)

  @commands.Cog.listener()
  async def on_message_edit(self, before, after): 
    pass

  @commands.Cog.listener()
  async def on_reaction_add(self, reaction, user):
    if user.id == self.bot.user.id: 
      return
    if reaction.emoji == "👍" and reaction.message.author == self.bot.user:
      logging.info(f"Positive feedback from {user} on: {reaction.message.content[:50]}...")

  @commands.Cog.listener()
  async def on_typing(self, channel, user, when): 
    pass

# ─── COG SETUP FUNCTION ────────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
  """Function to load the cog"""
  await bot.add_cog(AIChatbotCog(bot))
