import discord
import datetime
import random
import os
import json
import aiohttp
from google import genai

# Aesthetic Palette
PASTEL_COLORS = [
    0xffadad, 0xffd6a5, 0xfdffb6, 0xcaffbf, 0x9bf6ff, 0xa0c4ff, 0xbdb2ff, 0xffc6ff, 0xfffffc
]

JOCKIE_COLOR = 0x3498db # Default fallback
ERROR_COLOR = 0xe74c3c
SUCCESS_COLOR = 0x2ecc71

class GeminiKeyManager:
    def __init__(self):
        keys_str = os.getenv("GEMINI_API_KEYS", "")
        self.keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        self.clients = [genai.Client(api_key=k) for k in self.keys]
        self.current_index = 0
        self.failed_indices = set()

    def get_client(self):
        if not self.clients:
            return None
        return self.clients[self.current_index]

    def rotate(self):
        """Rotate to the next key. Returns True if a new key is available, False if all keys exhausted."""
        if not self.clients:
            return False
            
        self.failed_indices.add(self.current_index)
        
        # Check if all keys have failed in this attempt
        if len(self.failed_indices) >= len(self.clients):
            return False
            
        self.current_index = (self.current_index + 1) % len(self.clients)
        return True

    def reset_failure_checks(self):
        """Reset the failure tracking for a new set of requests."""
        self.failed_indices.clear()

    @property
    def has_keys(self):
        return len(self.clients) > 0

def get_random_color():
    """Returns a random pastel color."""
    return random.choice(PASTEL_COLORS)

def create_embed(title, description, color=None):
    """Creates a standardized, aesthetic embed."""
    if color is None:
        color = get_random_color()
        
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.datetime.now())
    return embed

def create_error_embed(description):
    """Creates a standardized error embed."""
    return discord.Embed(title="❌ Error", description=description, color=ERROR_COLOR)

def create_progress_bar(current, total, length=12):
    """Creates a text-based progress bar."""
    if total == 0:
        return "🔘" + "▬" * length
        
    progress = int((current / total) * length)
    progress = max(0, min(length, progress)) # Clamp
    bar = "▬" * progress + "🔘" + "▬" * (length - progress)
    return bar

def format_time(seconds):
    """Formats seconds into MM:SS or HH:MM:SS."""
    if not seconds:
        return "00:00"
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"

async def send_split_message(ctx_or_msg, text, **kwargs):
    """
    Splits a long message into multiple Discord messages (max 2000 chars each).
    Tries to split by double newlines, then single newlines, then spaces.
    """
    if not text:
        return []

    if len(text) <= 2000:
        try:
            return [await ctx_or_msg.reply(text, **kwargs)]
        except:
            return [await ctx_or_msg.channel.send(text, **kwargs)]

    parts = []
    while len(text) > 0:
        if len(text) <= 2000:
            parts.append(text)
            break
        
        # Find split point
        split_idx = text.rfind('\n\n', 0, 2000)
        if split_idx == -1:
            split_idx = text.rfind('\n', 0, 2000)
        if split_idx == -1:
            split_idx = text.rfind(' ', 0, 2000)
        if split_idx == -1:
            split_idx = 2000
        
        parts.append(text[:split_idx].strip())
        text = text[split_idx:].strip()
    
    responses = []
    import asyncio
    for i, part in enumerate(parts):
        if part:
            try:
                if i == 0:
                    responses.append(await ctx_or_msg.reply(part, **kwargs))
                else:
                    responses.append(await ctx_or_msg.channel.send(part, **kwargs))
            except:
                 responses.append(await ctx_or_msg.channel.send(part, **kwargs))
            
            # Small delay to avoid rate limits if many parts
            if len(parts) > 1:
                await asyncio.sleep(0.5)
                
    return responses

def is_owner(member):
    """Checks if a member is the bot owner or has an owner role."""
    OWNER_ID = 1145666047383437453
    # User provided Role IDs
    OWNER_ROLES = [1351534280173555725, 1302965880560287754, 1445080252148875404, 1410097235814776832]
    
    if member.id == OWNER_ID:
        return True
    
    if hasattr(member, 'roles'):
        for role in member.roles:
            if role.id in OWNER_ROLES:
                return True
    return False

def get_maintenance_state():
    """Reads the maintenance state from system_settings.json. Returns (enabled, reason)."""
    try:
        if os.path.exists("system_settings.json"):
            with open("system_settings.json", "r") as f:
                data = json.load(f)
                return data.get("maintenance", False), data.get("maintenance_reason", None)
    except Exception as e:
        print(f"Error reading maintenance state: {e}")
    return False, None

def set_maintenance_state(state: bool, reason: str = None):
    """Saves the maintenance state to system_settings.json."""
    data = {"maintenance": state, "maintenance_reason": reason}
    try:
        # Load existing settings if any to preserve other keys if we add them later
        if os.path.exists("system_settings.json"):
            with open("system_settings.json", "r") as f:
                data = json.load(f)
        
        data["maintenance"] = state
        data["maintenance_reason"] = reason
        
        with open("system_settings.json", "w") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving maintenance state: {e}")
        return False

async def send_error_log(bot, error, ctx=None, message=None, extra_info=None):
    """Sends a rich error log embed to the designated logging channel."""
    ERROR_LOG_CHANNEL_ID = 1476562513641476299
    
    channel = bot.get_channel(ERROR_LOG_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(ERROR_LOG_CHANNEL_ID)
        except:
            print(f"CRITICAL: Could not find error log channel {ERROR_LOG_CHANNEL_ID}")
            return

    import traceback
    tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    if len(tb) > 1000:
        tb = "..." + tb[-997:] # Keep the end of the traceback which is usually most relevant

    embed = discord.Embed(
        title="🚨 System Error Detected",
        description=f"An error occurred during bot operation.",
        color=0xe74c3c, # ERROR_COLOR
        timestamp=datetime.datetime.now()
    )

    embed.add_field(name="Error Type", value=f"`{type(error).__name__}`", inline=True)
    embed.add_field(name="Error Message", value=f"```\n{str(error)[:1000]}\n```", inline=False)
    
    if ctx:
        embed.add_field(name="Command", value=f"`{ctx.command}`" if ctx.command else "No Command", inline=True)
        embed.add_field(name="User", value=f"{ctx.author} ({ctx.author.id})", inline=True)
        embed.add_field(name="Location", value=f"{ctx.guild.name if ctx.guild else 'DM'} ({ctx.channel.name if not isinstance(ctx.channel, discord.DMChannel) else 'DM'})", inline=True)
    elif message:
        embed.add_field(name="User", value=f"{message.author} ({message.author.id})", inline=True)
        embed.add_field(name="Location", value=f"{message.guild.name if message.guild else 'DM'} ({message.channel.name if not isinstance(message.channel, discord.DMChannel) else 'DM'})", inline=True)
        embed.add_field(name="Message Content", value=f"```\n{message.content[:500]}\n```", inline=False)

    if extra_info:
        embed.add_field(name="Extra Info", value=str(extra_info), inline=False)

    embed.add_field(name="Traceback", value=f"```python\n{tb}\n```", inline=False)
    
    embed.set_footer(text="MeLagu Error Reporter")
    
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"FAILED TO SEND ERROR LOG TO DISCORD: {e}")

def clean_song_title(title: str) -> str:
    import re
    # Remove everything in [], (), 【】, 「」, 『』
    title = re.sub(r'[\(\[\【\「\『].*?[\)\]\】\」\』]', '', title)
    # Remove noise words
    for noise in ['official', 'lyrics', 'video', 'ver', 'version', 'mv', 'hd', '4k', 'hq', 'audio', 'lyric']:
        title = re.compile(r'\b' + re.escape(noise) + r'\b', re.IGNORECASE).sub('', title)
    return title.strip()

async def fetch_synced_lyrics(query: str):
    """
    Fetches synced lyrics from LRCLIB for a given query.
    Returns a list of dictionaries: [{'time': float_seconds, 'text': str}, ...]
    or None if no synced lyrics are found.
    """
    url = "https://lrclib.net/api/search"
    
    async def _search(q):
        params = {'q': q}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, list):
                            # Filter for ones with syncedLyrics
                            synced_tracks = [t for t in data if t.get('syncedLyrics')]
                            if synced_tracks:
                                best_match = synced_tracks[0]
                                return parse_lrc(best_match['syncedLyrics'])
        except Exception as e:
            print(f"Error fetching lyrics for '{q}': {e}")
        return None

    # First try exact
    result = await _search(query)
    if result:
        return result
        
    # If not found, try cleaned title
    cleaned_query = clean_song_title(query)
    if cleaned_query and cleaned_query != query:
        return await _search(cleaned_query)
        
    return None

def parse_lrc(lrc_text: str):
    """Parses LRC format into a list of dictionaries."""
    import re
    lines = lrc_text.strip().split('\n')
    parsed = []
    # Match [mm:ss.xx] text
    pattern = re.compile(r'\[(\d+):(\d+\.\d+)\](.*)')
    for line in lines:
        match = pattern.match(line)
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            text = match.group(3).strip()
            total_seconds = minutes * 60 + seconds
            parsed.append({'time': total_seconds, 'text': text})
    return parsed

async def fetch_youtube_captions(source_data: dict):
    """
    Extracts JSON3 captions from yt-dlp extracted data.
    """
    if not source_data:
        return None
        
    subs_info = source_data.get('subtitles') or {}
    auto_subs_info = source_data.get('automatic_captions') or {}
    
    # Try getting Indonesian first, then English, then any available
    langs_to_try = ['id', 'en', 'en-US', 'en-GB']
    all_langs = list(subs_info.keys()) + list(auto_subs_info.keys())
    
    for lang in langs_to_try + all_langs:
        subs_list = subs_info.get(lang) or auto_subs_info.get(lang)
        if subs_list:
            json3_sub = next((s for s in subs_list if s.get('ext') == 'json3'), None)
            if json3_sub and 'url' in json3_sub:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(json3_sub['url']) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                return parse_json3_captions(data)
                except Exception as e:
                    print(f"Error fetching yt captions: {e}")
                    pass
    return None

def parse_json3_captions(data: dict):
    parsed = []
    events = data.get('events', [])
    for e in events:
        if 'segs' in e:
            text = "".join(seg.get('utf8', '') for seg in e['segs']).strip()
            if text and text != '\n':
                time_seconds = e.get('tStartMs', 0) / 1000.0
                parsed.append({'time': time_seconds, 'text': text})
    return parsed if parsed else None

