import discord
from discord.ext import commands
import time
import datetime
import asyncio
import speedtest
import psutil
from utils import create_embed

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    @commands.command(name='ping')
    async def ping(self, ctx):
        """Checks the bot's latency."""
        latency = round(self.bot.latency * 1000)
        embed = create_embed("Pong!", f"Latency: {latency}ms")
        await ctx.send(embed=embed)

    @commands.command(name='stats')
    async def stats(self, ctx):
        """Shows bot statistics."""
        current_time = time.time()
        uptime_seconds = int(current_time - self.start_time)
        uptime = str(datetime.timedelta(seconds=uptime_seconds))
        
        embed = create_embed("📊 Bot Statistics", "Here is the current status of the bot.")
        embed.add_field(name="⏳ Uptime", value=f"`{uptime}`", inline=True)
        embed.add_field(name="🌐 Servers", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="📶 Ping", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        
        # System Hardware Info (Blocking call executed directly since psutil is very fast, or via executor if needed)
        # Using a tiny delay for cpu_percent allows it to calculate over that interval without completely freezing
        cpu = psutil.cpu_percent(interval=None) # Start measurement
        await asyncio.sleep(0.1)
        cpu = psutil.cpu_percent(interval=None) # Get measurement
        
        ram = psutil.virtual_memory()
        ram_total = ram.total / (1024 ** 3)
        ram_used = ram.used / (1024 ** 3)
        
        embed.add_field(name="🧠 CPU Usage", value=f"`{cpu}%`", inline=True)
        embed.add_field(name="💾 Memory Usage", value=f"`{ram_used:.2f} GB / {ram_total:.2f} GB ({ram.percent}%)`", inline=True)
        
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        await ctx.send(embed=embed)

    @commands.command(name='source', aliases=['sc', 'script'])
    async def source(self, ctx):
        """Link to the bot's source code."""
        embed = create_embed("🔗 Source Code", "You can find my source code on GitHub!")
        embed.add_field(name="Repository", value="[Fadlay/discord-bot-music](https://github.com/Fadlay/discord-bot-music.git)")
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        await ctx.send(embed=embed)

    @commands.command(name='speedtest', aliases=['st'])
    async def speed(self, ctx):
        """Performs an internet speed test."""
        # Send initial embed
        embed = create_embed("🚀 Internet Speed Test", "Testing connection speed... Please wait.")
        initial_msg = await ctx.send(embed=embed)

        def run_speedtest():
            s = speedtest.Speedtest(secure=True)
            s.get_best_server()
            s.download()
            s.upload()
            return s.results.dict()

        try:
            # Run speedtest in an executor to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, run_speedtest)

            ping = results['ping']
            download = results['download'] / 1000000  # Convert to Mbps
            upload = results['upload'] / 1000000      # Convert to Mbps

            # Create results embed
            res_embed = create_embed("🚀 Internet Speed Test Results", "Speed test completed successfully.")
            res_embed.add_field(name="📶 Ping", value=f"`{ping:.2f} ms`", inline=True)
            res_embed.add_field(name="⬇️ Download", value=f"`{download:.2f} Mbps`", inline=True)
            res_embed.add_field(name="⬆️ Upload", value=f"`{upload:.2f} Mbps`", inline=True)
            res_embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

            await initial_msg.edit(embed=res_embed)
        except Exception as e:
            error_embed = create_embed("❌ Speed Test Error", f"An error occurred during the speed test:\n`{str(e)}`", color=0xe74c3c)
            await initial_msg.edit(embed=error_embed)

    @commands.command(name='help')
    async def help(self, ctx):
        """Shows this help message."""
        embed = create_embed("📜 Help Menu", "List of available commands by category:")
        
        # Emoji map for known cogs
        emoji_map = {
            "Music": "🎵",
            "Controls": "🎛️",
            "General": "⚙️",
            "Filters": "🎧",
            "Owner": "👑",
            "Owner Commands": "👑"
        }

        for cog_name, cog in self.bot.cogs.items():
            commands_list = []
            for command in cog.get_commands():
                if not command.hidden:
                    aliases = f" ({', '.join(command.aliases)})" if command.aliases else ""
                    commands_list.append(f"`{command.name}{aliases}`: {command.help or 'No description'}")
            
            if commands_list:
                emoji = emoji_map.get(cog_name, "📁")
                embed.add_field(name=f"{emoji} {cog_name}", value="\n".join(commands_list), inline=False)
        
        embed.set_footer(text=f"Type {ctx.prefix}help <command> for more info | Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))
