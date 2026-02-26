import discord
from discord.ext import commands, tasks
import os
import zipfile
import datetime
import io
import asyncio
from dotenv import load_dotenv

load_dotenv()

class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.backup_channel_id = int(os.getenv("BACKUP_CHANNEL_ID", 0))
        self.files_to_backup = ["chat_history.json", "personas.json", ".env"]
        
        # Start the loop if ID is valid
        if self.backup_channel_id:
            self.daily_backup.start()
        else:
            print("WARNING: BACKUP_CHANNEL_ID not found in .env. Auto-backup disabled.")

    def cog_unload(self):
        self.daily_backup.cancel()

    async def create_backup_zip(self):
        """Creates a zip file in memory containing the ENTIRE bot directory."""
        buffer = io.BytesIO()
        base_dir = os.getcwd()
        
        # Folders to exclude
        exclude_dirs = {'.git', '__pycache__', 'venv', '.venv', 'node_modules', '.idea', '.vscode'}
        # Files to exclude
        exclude_files = {'.DS_Store'}

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, dirs, files in os.walk(base_dir):
                # Filter directories in-place to prevent walking them
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                
                for file in files:
                    if file in exclude_files:
                        continue
                        
                    file_path = os.path.join(root, file)
                    # Create relative path for zip structure
                    arcname = os.path.relpath(file_path, base_dir)
                    
                    try:
                        zip_file.write(file_path, arcname)
                    except Exception as e:
                        print(f"Skipped {file}: {e}")
        
        buffer.seek(0)
        return buffer

    @tasks.loop(hours=24)
    async def daily_backup(self):
        """Runs every 24 hours to backup files."""
        await self.bot.wait_until_ready()
        await self.perform_backup(reason="Daily Auto-Backup")

    async def perform_backup(self, ctx=None, reason="Manual Backup"):
        """Core logic to send the backup file to Discord."""
        try:
            channel = self.bot.get_channel(self.backup_channel_id)
            if not channel:
                # Try fetching if not in cache
                try:
                    channel = await self.bot.fetch_channel(self.backup_channel_id)
                except:
                    error_msg = f"ERROR: Could not find backup channel ID {self.backup_channel_id}."
                    print(error_msg)
                    if ctx: await ctx.send(error_msg)
                    return

            zip_buffer = await self.create_backup_zip()
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            filename = f"backup_bot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            
            file = discord.File(fp=zip_buffer, filename=filename)
            await channel.send(f"📦 **{reason}** - {timestamp}", file=file)
            
            if ctx:
                await ctx.send(f"✅ Backup sent to <#{self.backup_channel_id}>!")
            print(f"Backup successful: {filename}")
            
        except Exception as e:
            print(f"Backup failed: {e}")
            if ctx:
                await ctx.send(f"❌ Backup failed: {e}")

    @daily_backup.before_loop
    async def before_daily_backup(self):
        await self.bot.wait_until_ready()
        # Optional: Wait a bit on startup to ensure stability?
        # await asyncio.sleep(60) 



async def setup(bot):
    await bot.add_cog(Backup(bot))
