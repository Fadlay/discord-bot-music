import discord
from discord.ext import commands
from utils import create_embed, create_error_embed
import random
import asyncio

class Controls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_player(self, ctx):
        return self.bot.get_cog('Music').get_player(ctx)

    @commands.command(name='skip', aliases=['s', 'next'])
    async def skip(self, ctx):
        """Skip the current song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send(embed=create_embed("Skipped", "Skipped the current song."))
        else:
             await ctx.send(embed=create_error_embed("Nothing is playing."))

    @commands.command(name='volume', aliases=['vol'])
    async def volume(self, ctx, vol: int):
        """Set volume (0-100)."""
        if not ctx.voice_client or not ctx.voice_client.is_playing():
             return await ctx.send(embed=create_error_embed("Nothing is playing."))
        
        if 0 <= vol <= 100:
            ctx.voice_client.source.volume = vol / 100
            player = self.get_player(ctx)
            player.volume = vol / 100
            await ctx.send(embed=create_embed("Volume", f"Set volume to {vol}%"))
        else:
            await ctx.send(embed=create_error_embed("Volume must be between 0 and 100."))

    @commands.command(name='shuffle')
    async def shuffle(self, ctx):
        """Shuffle the queue."""
        player = self.get_player(ctx)
        if player.queue.empty():
             return await ctx.send(embed=create_error_embed("Queue is empty."))
        
        items = []
        while not player.queue.empty():
            items.append(player.queue.get_nowait())
            
        random.shuffle(items)
        
        for item in items:
            await player.queue.put(item)
            
        await ctx.send(embed=create_embed("Shuffled", "Queue has been shuffled."))

    @commands.command(name='loop')
    async def loop(self, ctx, mode: str = None):
        """Toggle loop mode. Modes: track, queue, off."""
        player = self.get_player(ctx)
        
        if not mode:
            # Cycle modes: Off -> Track -> Queue -> Off
            player.loop_mode = (player.loop_mode + 1) % 3
        else:
            if mode.lower() in ['track', 'song', '1']:
                player.loop_mode = 1
            elif mode.lower() in ['queue', 'all', 'list', '2']:
                player.loop_mode = 2
            else:
                player.loop_mode = 0
        
        modes = ["Off", "Track", "Queue"]
        await ctx.send(embed=create_embed("Loop Mode", f"Set to **{modes[player.loop_mode]}**"))

async def setup(bot):
    await bot.add_cog(Controls(bot))
