import discord
from discord.ext import commands
from utils import create_embed, create_error_embed

class Filters(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_player(self, ctx):
        return self.bot.get_cog('Music').get_player(ctx)

    async def apply_filter(self, ctx, options):
        """Helper to apply ffmpeg options to current track."""
        player = self.get_player(ctx)
        
        if not ctx.voice_client or not ctx.voice_client.is_playing():
             return await ctx.send(embed=create_error_embed("Nothing is playing."))

        # Update player options
        # We need to include '-vn' as well since we are replacing the 'options' key
        player.ffmpeg_opts = {'options': f'-vn {options}'}
        
        # Restart current track
        if player.current:
            data = player.current.data
            # Prepend to queue
            # Accessing internal deque
            player.queue._queue.appendleft(data)
            
            ctx.voice_client.stop()
            
            await ctx.send(embed=create_embed("Filter Applied", "Restarting track with new settings..."))

    @commands.command(name='bassboost', aliases=['bb'])
    async def bassboost(self, ctx, level: int = 10):
        """Applies bassboost (default 10)."""
        await self.apply_filter(ctx, f'-af "bass=g={level}"')

    @commands.command(name='nightcore', aliases=['nc'])
    async def nightcore(self, ctx):
        """Applies nightcore effect (speed 1.25x, pitch up)."""
        await self.apply_filter(ctx, '-af "asetrate=44100*1.25,aresample=44100"')

    @commands.command(name='vaporwave')
    async def vaporwave(self, ctx):
        """Applies vaporwave effect (speed 0.8x, pitch down)."""
        await self.apply_filter(ctx, '-af "asetrate=44100*0.8,aresample=44100"')

    @commands.command(name='speed')
    async def speed(self, ctx, speed: float):
        """Changes playback speed (0.5 - 2.0)."""
        if not 0.5 <= speed <= 2.0:
            return await ctx.send(embed=create_error_embed("Speed must be between 0.5 and 2.0"))
            
        await self.apply_filter(ctx, f'-af "atempo={speed}"')

    @commands.command(name='reset')
    async def reset(self, ctx):
        """Resets all filters."""
        player = self.get_player(ctx)
        player.ffmpeg_opts = {}
        
        if player.current:
            data = player.current.data
            player.queue._queue.appendleft(data)
            ctx.voice_client.stop()
        
        await ctx.send(embed=create_embed("Filters Reset", "Audio settings restored to default."))

async def setup(bot):
    await bot.add_cog(Filters(bot))
