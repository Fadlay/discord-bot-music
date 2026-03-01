import os
import discord
import asyncio
import sys
import io
import collections
from discord.ext import commands
from dotenv import load_dotenv
from utils import is_owner, get_maintenance_state, create_error_embed, send_error_log

class DualStream:
    def __init__(self, original_stream, maxlen=100):
        self.original_stream = original_stream
        self.log_deque = collections.deque(maxlen=maxlen)
        self._current_chunk = ""

    def write(self, data):
        self.original_stream.write(data)
        self._current_chunk += data
        if '\n' in self._current_chunk:
            lines = self._current_chunk.split('\n')
            # All elements except the last one are complete lines
            for line in lines[:-1]:
                self.log_deque.append(line)
            # The last element is the beginning of the next line
            self._current_chunk = lines[-1]

    def flush(self):
        self.original_stream.flush()

    def __getattr__(self, name):
        """Delegate missing methods (like fileno) to the original stream."""
        return getattr(self.original_stream, name)

    def get_logs(self, n=20):
        logs = list(self.log_deque)
        if self._current_chunk:
            logs.append(self._current_chunk)
        return logs[-n:]


# Global stream instances to be attached to bot
stdout_wrapper = DualStream(sys.stdout)
stderr_wrapper = DualStream(sys.stderr)
sys.stdout = stdout_wrapper
sys.stderr = stderr_wrapper


# Load environment variables
load_dotenv()
TOKEN = os.getenv('TOKEN')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True # Required for voice interactions (Music + AI)
intents.members = True # Required for member list and mentions
intents.presences = True # Required to see who is online

# Prefix: al! (Case insensitive)
bot = commands.Bot(
    command_prefix=['al!', 'Al!', 'AL!'], 
    intents=intents, 
    case_insensitive=True, 
    help_command=None,
    chunk_guilds_at_startup=True
)

# Attach log buffers
bot.stdout_wrapper = stdout_wrapper
bot.stderr_wrapper = stderr_wrapper


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')
    print(f'Connected to {len(bot.guilds)} guilds')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="al!help"))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(embed=create_error_embed(f"⏳ **Slow down!** You can use this command again in `{error.retry_after:.1f}s`."), delete_after=10)
    elif isinstance(error, commands.CheckFailure):
        pass # Handled by the check itself usually
    else:
        print(f"Command Error: {error}")
        await send_error_log(bot, error, ctx=ctx)

@bot.event
async def on_error(event, *args, **kwargs):
    import sys
    error = sys.exc_info()[1]
    print(f"Global Error in {event}: {error}")
    await send_error_log(bot, error, extra_info=f"Event: {event}\nArgs: {args}\nKwargs: {kwargs}")

@bot.check
async def global_maintenance_check(ctx):
    """Global check to block commands during maintenance mode, except for owners."""
    if is_owner(ctx.author):
        return True
    
    is_maintenance, maintenance_reason = get_maintenance_state()
    if is_maintenance:
        reason_str = f"**Reason:** {maintenance_reason}\n\n" if maintenance_reason else ""
        await ctx.send(embed=create_error_embed(f"🚧 **Bot is currently under maintenance.**\n\n{reason_str}Only owners can use commands at this time. Please try again later!"))
        return False
        
    return True

async def load_extensions():
    # Load cogs from ./cogs directory
    if os.path.exists('./cogs'):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py') and not filename.startswith('__'):
                try:
                    await bot.load_extension(f'cogs.{filename[:-3]}')
                    print(f"Loaded extension: {filename[:-3]}")
                except Exception as e:
                    print(f"Failed to load extension {filename}: {e}")

async def main():
    if not TOKEN:
        print("Error: TOKEN not found in .env file.")
        return
    
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
