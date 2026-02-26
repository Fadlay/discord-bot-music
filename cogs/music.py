import discord
import asyncio
import yt_dlp
import requests
import json
import difflib
import time
import os
import shutil
from bs4 import BeautifulSoup
from discord.ext import commands
from async_timeout import timeout
from utils import create_embed, create_error_embed, format_time, JOCKIE_COLOR, create_progress_bar, is_owner, send_error_log

# Suppress noise about console usage from errors
yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
    'cookiesfrombrowser': ('firefox',),  # Read cookies from Firefox (no App-Bound Encryption!)
    'extractor_args': {'youtubetab': {'skip': ['authcheck']}},
}

# Dynamically find the path to Node.js for YouTube n-challenge solving (SABR issue)
_node_path = shutil.which('node')
if _node_path:
    ytdl_format_options['js_runtimes'] = {'node': {'exe': _node_path}}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'  # Critical for streaming
}


def get_ytdl(extra_opts=None):
    """Create a fresh YoutubeDL instance that re-reads cookies from Firefox."""
    opts = dict(ytdl_format_options)
    if extra_opts:
        opts.update(extra_opts)
    return yt_dlp.YoutubeDL(opts)


# Default global instance (for backward compatibility)
ytdl = get_ytdl()


def _extract_info(url, **kwargs):
    """Extract info using a fresh ytdl instance for each call (fresh cookies)."""
    ydl = get_ytdl()
    return ydl.extract_info(url, **kwargs)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')
        self.is_live = data.get('is_live', False)

    @classmethod
    async def create(cls, data, loop=None):
         loop = loop or asyncio.get_event_loop()
         # Ensure we have the stream url
         filename = data['url']
         return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True, ffmpeg_opts=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: _extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        
        # Merge default options with provided options
        opts = ffmpeg_options.copy()
        if ffmpeg_opts:
            opts.update(ffmpeg_opts)
            
        return cls(discord.FFmpegPCMAudio(filename, **opts), data=data)

class MusicPlayer:
    """A class which is assigned to each guild using the bot for Music."""

    __slots__ = ('bot', '_guild', '_channel', '_cog', 'queue', 'next', 'current', 'np', 'volume', 'loop_mode', 'ffmpeg_opts', 'timer_enabled', 'autoplay', 'history', 'last_track', 'autoplay_candidate', 'start_time', 'sticky_task', 'prefetched_data', 'starter_id', 'stop_votes', 'last_voice_channel', 'reconnect_attempts', 'player_task', '_intentional_disconnect', 'last_error')

    def __init__(self, ctx, cog=None):
        self.bot = ctx.bot
        self._guild = ctx.guild
        self._channel = ctx.channel
        self._cog = cog or ctx.cog

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()

        self.np = None  # Now playing message
        self.volume = .5
        self.current = None
        self.start_time = 0
        self.sticky_task = None
        self.last_track = None # Track data for autoplay
        self.autoplay_candidate = None # Pre-fetched track
        self.loop_mode = 0 # 0: Off, 1: Track, 2: Queue
        self.ffmpeg_opts = {} # Current filters
        self.timer_enabled = True # Default On
        self.autoplay = False
        self.history = [] # List of titles to avoid repeats
        self.prefetched_data = None # Store pre-fetched info/source data
        self.starter_id = ctx.author.id
        self.stop_votes = set()
        self.last_voice_channel = ctx.author.voice.channel if ctx.author.voice else None
        self.reconnect_attempts = 0
        self.player_task = None
        self._intentional_disconnect = False
        self.last_error = None

        self.player_task = ctx.bot.loop.create_task(self.player_loop())

    async def reconnect(self):
        """Attempts to reconnect the voice client to the last known channel."""
        if self._intentional_disconnect:
            print(f"DEBUG: Skipping reconnect for guild {self._guild.id} (intentional disconnect)")
            return False

        if self.reconnect_attempts >= 3:
            print(f"DEBUG: Reconnect failed after 3 attempts for guild {self._guild.id}")
            if self._channel:
                 await self._channel.send(embed=create_error_embed("Failed to reconnect to voice channel after multiple attempts. Stopping playback."))
            return self.destroy(self._guild)

        self.reconnect_attempts += 1
        print(f"DEBUG: Reconnection attempt {self.reconnect_attempts} for guild {self._guild.id}")

        try:
            if self.last_voice_channel:
                if self._guild.voice_client:
                    try:
                        await self._guild.voice_client.disconnect(force=True)
                    except:
                        pass
                
                await self.last_voice_channel.connect(timeout=20.0, reconnect=True)
                print(f"DEBUG: Successfully reconnected to {self.last_voice_channel.name}")
                self.reconnect_attempts = 0 # Reset on success
                return True
            else:
                print(f"DEBUG: No last_voice_channel recorded for guild {self._guild.id}")
                return False
        except Exception as e:
            print(f"DEBUG: Reconnect error: {e}")
            await asyncio.sleep(5) # Wait before next attempt
            return await self.reconnect()

    async def prepare_next_song(self, current_track=None):
        """Pre-fetch the next song (Autoplay OR Queue) in the background."""
        await asyncio.sleep(10) # Wait for current song to stabilize
        
        self.autoplay_candidate = None
        self.prefetched_data = None
        
        # Use explicit track or fallback to last_track
        seed_track = current_track or self.last_track
        
        try:
            # 1. Check Autoplay if queue empty
            if self.queue.empty() and self.autoplay and seed_track:
                 # print(f"DEBUG: Fetching Autoplay based on: {seed_track.title}")
                 recommendation = await self.get_recommendation(seed_track.data)
                 if recommendation:
                     print(f"DEBUG: Queued related track ({recommendation.get('title')}) [Seed: {seed_track.title}]")

                     # Double check queue is empty to avoid race with user play command
                     if self.queue.empty():
                         recommendation['is_autoplay'] = True
                         await self.queue.put(recommendation)
                     # Now queue is not empty, proceed to pre-fetch it
            
            # 2. Peek Queue
            if not self.queue.empty():
                # Peek the first item (object reference)
                next_item = self.queue._queue[0]
                
                # Resolve if needed (lazy query)
                data = next_item
                if isinstance(data, dict):
                     # If it's a query, resolve it now
                     if data.get('query'):
                         try:
                             query = data['query']
                             search_result = await self.bot.loop.run_in_executor(None, lambda: _extract_info(f"ytsearch:{query}", download=False))
                             if 'entries' in search_result and search_result['entries']:
                                 data = search_result['entries'][0]
                             else:
                                 return # Failed resolve
                         except:
                             return
                
                # 3. Extract Stream Info (The slow part)
                # We need the full data with 'url' pointing to the stream
                # YTDLSource.from_url does this via extract_info(download=not stream)
                # We want stream=True, so download=False
                
                url = data.get('webpage_url') or data.get('url')
                if url:
                     loop = self.bot.loop or asyncio.get_event_loop()
                     stream_data = await loop.run_in_executor(None, lambda: _extract_info(url, download=False))
                     
                     if 'entries' in stream_data:
                         stream_data = stream_data['entries'][0]
                         
                     # Save it linked to the queue item
                     self.prefetched_data = {'info': stream_data, 'ref_item': next_item}
                     # print(f"DEBUG: Pre-fetched {stream_data.get('title')}")
                     
        except Exception as e:
            print(f"Pre-fetch error: {e}")

    async def update_sticky_message(self):
        """Loop to update the Now Playing message (Progress only, no longer sticky to avoid rate limits)."""
        while self.current and self._guild.voice_client and self._guild.voice_client.is_playing():
            try:
                # Calculate Progress
                elapsed = time.time() - self.start_time
                duration = self.current.duration
                
                # Build Embed
                display_url = self.current.webpage_url if hasattr(self.current, 'webpage_url') and self.current.webpage_url else self.current.url
                embed = create_embed("🎶 Now Playing", f"[{self.current.title}]({display_url})")
                embed.set_image(url=self.current.thumbnail)
                
                if duration:
                    prog_bar = create_progress_bar(elapsed, duration)
                    embed.add_field(name="Progress", value=f"`{format_time(elapsed)}` {prog_bar} `{format_time(duration)}`", inline=False)
                
                embed.add_field(name="Looping", value=["❌ Off", "🔂 Track", "🔁 Queue"][self.loop_mode], inline=True)
                embed.add_field(name="Volume", value=f"🔊 {int(self.volume * 100)}%", inline=True)
                embed.set_footer(text=f"Playing in {self._guild.name}", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
                
                # Update existing message
                if self.np:
                    try:
                        await self.np.edit(embed=embed)
                    except discord.NotFound:
                        # Message was deleted by a user, stop trying to update it
                        self.np = None
                    except Exception as e:
                        pass
                
            except Exception as e:
                print(f"NP loop update error: {e}")
                
            await asyncio.sleep(5) # Update every 5 seconds

    async def player_loop(self):
        """Our main player loop."""
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            # GHOST PLAYER CHECK: Exit if this loop belongs to a player that was replaced or cleaned up
            if self._cog.players.get(self._guild.id) is not self:
                print(f"DEBUG: Ghost player loop detected for guild {self._guild.id}. Exiting loop.")
                return

            self.next.clear()

            try:
                if self.loop_mode == 1 and self.current:
                    # Loop Track: Replay current
                    data = self.current.data
                    source = await YTDLSource.from_url(data['webpage_url'], loop=self.bot.loop, stream=True, ffmpeg_opts=self.ffmpeg_opts)
                else:
                    # Inactivity Timer logic: Disable if Live Mode is active in this guild
                    live_cog = self.bot.get_cog("MeLaguLive")
                    is_live_active = live_cog and live_cog.live_session and self._guild.voice_client
                    
                    # Determine timeout duration
                    timeout_duration = 180 if self.timer_enabled and not self.autoplay and not is_live_active else None
                    
                    try:
                        async with timeout(timeout_duration):
                            # Autoplay Logic
                            if self.queue.empty() and self.autoplay:
                                recommendation = None
                                
                                # Check if we have a pre-fetched candidate
                                if self.autoplay_candidate:
                                    recommendation = self.autoplay_candidate
                                    self.autoplay_candidate = None # Consume it
                                elif self.last_track:
                                    # Fallback: Fetch now (slow)
                                    recommendation = await self.get_recommendation(self.last_track.data)
                                
                                if recommendation:
                                    await self.queue.put(recommendation)
                                    embed = create_embed("🤖 Autoplay", f"Queued related track: **{recommendation.get('title')}**")
                                    if self._channel:
                                        await self._channel.send(embed=embed)

                            # Check if queue is empty to send a warning (only if autoplay didn't fill it)
                            # Only warn if we've actually played something (history not empty) to avoid startup warning
                            # AND if there are users in the channel (if alone, let the auto-leave handler warn)
                            channel_members = self._guild.voice_client.channel.members if self._guild.voice_client else []
                            if self.queue.empty() and self.timer_enabled and self.history and len(channel_members) > 1:
                                try:
                                    if self._channel:
                                        await self._channel.send(embed=create_embed("Info", "No more tracks in queue. Disconnecting in 3 minutes if no song is added."))
                                except:
                                    pass

                            item = await self.queue.get()
                    except asyncio.TimeoutError:
                        if self.timer_enabled and self.queue.empty(): # double check empty
                            # If we are alone, let on_voice_state_update handle the disconnect to avoid double messages
                            channel_members = self._guild.voice_client.channel.members if self._guild.voice_client else []
                            if len(channel_members) <= 1:
                                # We are alone (or disconnected), just return/wait? 
                                # If we return, we stop the player loop. The auto-leave listener should handle the rest.
                                # But strictly, if we stop the loop, we are technically "idle".
                                # Let's just return.
                                return self.destroy(self._guild) # Actually destroy is fine, but maybe suppress message?
                            
                            try:
                                if self._channel:
                                    await self._channel.send(embed=create_embed("Timeout", "No songs played for 3 minutes. Disconnecting..."))
                            except:
                                pass
                            return self.destroy(self._guild)
                        else:
                            # Should not happen given logic above effectively, but safe fallback
                            item = await self.queue.get()
                        
                    # Check Pre-fetch match
                    source = None
                    if self.prefetched_data and self.prefetched_data['ref_item'] is item:
                        # Use pre-fetched data directly!
                        try:
                            # print(f"DEBUG: Using pre-fetched source for {self.prefetched_data['info'].get('title')}")
                            data = self.prefetched_data['info']
                            source = await YTDLSource.create(data, loop=self.bot.loop)
                            self.prefetched_data = None # Consume
                        except Exception as e:
                            print(f"Pre-fetch usage error: {e}")
                            source = None
                    
                    if not source:
                        if isinstance(item, dict):
                             # 1. LAZY PLAYLIST EXTRACTION
                             if item.get('playlist_url'):
                                 try:
                                     url = item['playlist_url']
                                     data = await self.bot.loop.run_in_executor(None, lambda: _extract_info(url, download=False, process=False))
                                     
                                     if 'entries' in data:
                                         new_entries = [entry for entry in data['entries'] if entry]
                                         if new_entries:
                                             item = new_entries.pop(0)
                                             # Put back at FRONT
                                             old_queue = list(self.queue._queue)
                                             self.queue = asyncio.Queue()
                                             for entry in (new_entries + old_queue):
                                                 await self.queue.put(entry)
                                         else:
                                             continue
                                     else:
                                         continue
                                 except Exception as e:
                                     print(f"Lazy playlist error: {e}")
                                     continue

                             # Re-sync data after extraction
                             data = item if isinstance(item, dict) else item
                             
                             # 2. Lazy Search (Spotify or Text Query)
                             if data.get('query'):
                                 try:
                                     query = data['query']
                                     search_result = await self.bot.loop.run_in_executor(None, lambda: _extract_info(f"ytsearch:{query}", download=False))
                                     
                                     if 'entries' in search_result and search_result['entries']:
                                         data = search_result['entries'][0]
                                     else:
                                         print(f"Could not find: {query}")
                                         continue
                                 except Exception as e:
                                      print(f"Lazy resolve error: {e}")
                                      continue

                             # 3. Stream Info Extraction
                             url = data.get('webpage_url') or data.get('url')
                             
                             if not url and data.get('id'):
                                 url = f"https://www.youtube.com/watch?v={data['id']}"
                                 
                             if not url:
                                 print(f"Skipping item with no URL: {data}")
                                 continue
                                 
                             source = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True, ffmpeg_opts=self.ffmpeg_opts)
                        else:
                             # It's already a full data object
                             url = item.url if hasattr(item, 'url') else None
                             if url:
                                 source = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True, ffmpeg_opts=self.ffmpeg_opts)
                             else:
                                 continue

            except Exception as e:
                err_msg = str(e).split('\n')[0] # Keep it short
                print(f"Player error: {e}")
                await send_error_log(self.bot, e, extra_info=f"Guild: {self._guild.name} ({self._guild.id}) - Player Loop")
                if self._channel:
                    await self._channel.send(embed=create_error_embed(f"Skipping track: {err_msg}"))
                continue

            source.volume = self.volume
            self.current = source
            
            # Record Start Time
            self.start_time = time.time()

            # Add to history
            track_id = getattr(source, 'data', {}).get('id')
            display_url = source.webpage_url if hasattr(source, 'webpage_url') and source.webpage_url else source.url
            # If it's a stream URL, try to construct a standard YouTube URL if ID is available
            if 'googlevideo.com' in display_url and track_id:
                display_url = f"https://www.youtube.com/watch?v={track_id}"

            if not any(h.get('id') == track_id or h['title'] == source.title for h in self.history):
                self.history.append({
                    'title': source.title, 
                    'url': display_url,
                    'id': track_id
                })
                # Keep history size manageable (e.g. 50 items)
                if len(self.history) > 50:
                    self.history.pop(0)

            if not self._guild.voice_client:
                if self._intentional_disconnect:
                    print(f"DEBUG: Intentional disconnect detected in player_loop for guild {self._guild.id}. Exiting.")
                    return

                print(f"DEBUG: Voice client missing in player_loop for guild {self._guild.id}. Attempting reconnect.")
                success = await self.reconnect()
                if not success:
                     return # Reconnect method handles destruction/messages

            try:
                def after_playing(error):
                    if error:
                        self.last_error = error
                    self.bot.loop.call_soon_threadsafe(self.next.set)

                self._guild.voice_client.play(source, after=after_playing)
            except Exception as e:
                print(f"Playback error: {e}")
                
                # Check if it was a "Not connected to voice" error
                if "Not connected to voice" in str(e):
                    if self._intentional_disconnect: return

                    print(f"DEBUG: Detected voice connection loss during play() for guild {self._guild.id}")
                    success = await self.reconnect()
                    if success:
                        # Retry playback once
                        try:
                            self._guild.voice_client.play(source, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
                        except Exception as retry_e:
                             print(f"Retry playback error: {retry_e}")
                             return self.destroy(self._guild)
                    else:
                        return
                else:
                    return self.destroy(self._guild)
            
            # Send 'Start Playing' Log (Requested by user to be unified for all tracks)
            # This is separate from the Sticky 'Now Playing' message
            if self._channel:
                 await self._channel.send(embed=create_embed("▶️ Start Playing", f"**{source.title}**"))
            
            # Send 'Now Playing' embed - Handled by Sticky Task mostly, but send initial
            # Actually, let's just let the sticky task handle it. 
            # Waiting 5s might be too long for first feedback.
            # So send initial immediately, then start task.
            display_url = source.webpage_url if hasattr(source, 'webpage_url') and source.webpage_url else source.url
            embed = create_embed("🎶 Now Playing", f"[{source.title}]({display_url})")
            embed.set_image(url=source.thumbnail)
            if source.duration:
                 prog_bar = create_progress_bar(0, source.duration)
                 embed.add_field(name="Progress", value=f"`{format_time(0)}` {prog_bar} `{format_time(source.duration)}`", inline=False)
            embed.add_field(name="Looping", value=["❌ Off", "🔂 Track", "🔁 Queue"][self.loop_mode], inline=True)
            embed.add_field(name="Volume", value=f"🔊 {int(self.volume * 100)}%", inline=True)
            embed.set_footer(text=f"Playing in {self._guild.name}", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
            
            self.np = await self._channel.send(embed=embed)
            
            # START STICKY TASK
            self.sticky_task = self.bot.loop.create_task(self.update_sticky_message())
            
            # TRIGGER PRE-FETCH (Autoplay or Queue)
            self.bot.loop.create_task(self.prepare_next_song(source))
            
            await self.next.wait()
            
            # STOP STICKY TASK
            if self.sticky_task:
                self.sticky_task.cancel()
                self.sticky_task = None

            # Detect if it was an unexpected end for a live stream
            unexpected_end = False
            if self.last_error:
                unexpected_end = True
                print(f"DEBUG: Playback error in guild {self._guild.id}: {self.last_error}")
                self.last_error = None # Reset
            
            if source and source.is_live:
                # If a live stream ends, check if it was "short" or had an error
                # Usually live streams should run indefinitely until stopped or next track
                # If it ended and next.is_set() was triggered by 'after', we check if loop should continue
                elapsed = time.time() - self.start_time
                if not self.next.is_set() or elapsed < 10: # Sample heuristic
                     unexpected_end = True
                
                # We can also check if the voice client is still connected but stopped playing
                if self._guild.voice_client and not self._guild.voice_client.is_playing() and not self.next.is_set():
                     unexpected_end = True

            # If it's a live stream that ended unexpectedly, retry it
            if unexpected_end and source and source.is_live:
                print(f"DEBUG: Live stream {source.title} ended unexpectedly. Refreshing...")
                if self._channel:
                    await self._channel.send(embed=create_embed("🔄 Stream Refresh", f"Live stream interrupted. Refreshing **{source.title}**..."), delete_after=10)
                
                # Put the SAME item back at the front of the queue to "retry"
                # We need to use the original data to re-extract the URL
                # If source.data exists, we use its webpage_url
                retry_data = source.data.get('webpage_url') or source.data.get('url')
                if retry_data:
                    # Clear current so it doesn't loop track 1
                    self.current = None 
                    # Insert at front of queue
                    self.queue._queue.appendleft(source.data)
                    # Don't cleanup source yet? Actually cleanup is fine if we recreate from URL
            else:
                # Logic for Loop Queue
                if self.loop_mode == 2:
                    # Put the data back into the queue
                    await self.queue.put(source.data)

            # Cleanup
            if source:
                source.cleanup()
            self.last_track = self.current # Save for autoplay
            self.current = None
            
            try:
                if self.np:
                    await self.np.delete()
            except:
                pass
            finally:
                self.np = None

    def is_similar(self, title1, title2):
        """Check if two titles are too similar (clean version, years, etc)."""
        def normalize(t):
            import re
            t = t.lower()
            # Remove bracketed/parenthesized text (e.g. [Cover], (Official Video))
            t = re.sub(r'[\(\[].*?[\)\]]', '', t)
            # Remove common years (2020-2029)
            t = re.sub(r'202\d', '', t)
            # Remove noise words
            for noise in ['official', 'lyrics', 'video', 'ver', 'version', 'mv', 'hd', '4k', 'hq', 'audio']:
                t = t.replace(noise, '')
            # Remove extra space/punctuation
            t = re.sub(r'[^\w\s]', '', t)
            return t.strip()
        
        t1 = normalize(title1)
        t2 = normalize(title2)
        
        # If one is empty after normalization, fallback to basic
        if not t1 or not t2:
            return title1.lower() == title2.lower()

        ratio = difflib.SequenceMatcher(None, t1, t2).ratio()
        return ratio > 0.8 # Higher threshold for cleaned titles

    async def get_recommendation(self, track_data):
        """Fetch a related song from YouTube Mix."""
        if not track_data or not track_data.get('id'):
            return None
            
        video_id = track_data.get('id')
        mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        
        loop = self.bot.loop or asyncio.get_event_loop()
        
        # Options for fast scraping
        # Options for fast scraping
        opts = dict(ytdl_format_options) # Copy global sub-options if needed, or just new dict
        opts.update({
            'extract_flat': True,
            'dump_single_json': True,
            'noplaylist': False, # Allow playlist for Mix
            'playlistend': 10 # Correct key for limits
        })
        # Explicit override
        opts['noplaylist'] = False
        
        def retrieve_mix():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(mix_url, download=False)
                
        try:
            # Extract flat info (fast)
            info = await loop.run_in_executor(None, retrieve_mix)
            
            if 'entries' in info:
                # verify it's a list or convert
                entries = list(info['entries'])
                
                for entry in entries:
                    # entries is a generator/islice in flat extraction if process=False?
                    # wait, if process=False, keys are generators? 
                    # extract_flat=True usually returns dict with 'entries' as list or generator.
                    # let's play safe and check.
                    if not entry: continue
                    
                    title = entry.get('title')
                    vid = entry.get('id')
                    
                    if not title or not vid: continue
                    
                    # 1. Skip if same ID exists in THIS candidate list or seed
                    if vid == video_id: continue
                    
                    # 2. Skip if ID exists in History (Exact match)
                    # This fulfills the user's request: "tidak memutar lagu dari link yang sama"
                    if any(h.get('id') == vid for h in self.history): continue
                    
                    # 3. Skip ONLY if the title is an EXACT match (Case insensitive)
                    # This prevents the exact same song if re-uploaded, but allows Remix/2024 Ver.
                    if any(h['title'].lower() == title.lower() for h in self.history): continue
                    
                    return entry
            else:
                pass
                    
        except Exception as e:
            print(f"Autoplay fetch error: {e}")
            import traceback
            traceback.print_exc()
            
        return None

    def destroy(self, guild):
        """Disconnect and cleanup the player."""
        return self.bot.loop.create_task(self._cog.cleanup(guild))

class PaginationView(discord.ui.View):
    def __init__(self, ctx, data_list, title="List"):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.data_list = data_list
        self.title = title
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = len(data_list) // self.items_per_page + (1 if len(data_list) % self.items_per_page > 0 else 0)

    async def update_message(self, interaction):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        items = self.data_list[start:end]
        
        fmt = ''
        for i, item in enumerate(items):
            # Handle both object (queue) and dict (history) items
            if isinstance(item, dict):
                 title = item.get('title')
                 url = item.get('url')
            else:
                 title = item.title
                 url = item.url

            if url and len(url) < 500:
                fmt += f'**{start + i + 1}.** [{title}]({url})\n'
            else:
                fmt += f'**{start + i + 1}.** {title}\n'
            
        embed = create_embed(f"{self.title} ({self.current_page + 1}/{self.total_pages})", fmt)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.grey)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)
        else:
             await interaction.response.defer()

    @discord.ui.button(label="Next", style=discord.ButtonStyle.grey)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_message(interaction)
        else:
             await interaction.response.defer()

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        self._cookie_refresh_task = bot.loop.create_task(self._cookie_refresh_loop())

    async def _cookie_refresh_loop(self):
        """Periodically recreate ytdl to re-read saved cookies from disk."""
        global ytdl
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(1800)  # Every 30 minutes
            try:
                ytdl = get_ytdl()
                print('[CookieRefresh] Refreshed ytdl instance')
            except Exception as e:
                print(f'[CookieRefresh] Error: {e}')

    async def get_spotify_tracks(self, url):
        """Scrape Spotify tracks from URL using __NEXT_DATA__ via Embed URL"""
        def scrape():
            try:
                # Convert to Embed URL for better scraping reliability (SSR)
                embed_url = url.replace('open.spotify.com/playlist/', 'open.spotify.com/embed/playlist/') \
                               .replace('open.spotify.com/album/', 'open.spotify.com/embed/album/') \
                               .replace('open.spotify.com/track/', 'open.spotify.com/embed/track/')
                
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(embed_url, headers=headers)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Check for __NEXT_DATA__
                script = soup.find('script', id='__NEXT_DATA__')
                if script:
                    data = json.loads(script.string)
                    # Try to find entity data
                    # Path: props -> pageProps -> state -> data -> entity
                    try:
                        entity = data['props']['pageProps']['state']['data']['entity']
                        
                        # Handle Playlist
                        if 'trackList' in entity:
                            tracks = []
                            for item in entity['trackList']:
                                title = item.get('title')
                                subtitle = item.get('subtitle')
                                # Clean subtitle (remove non-breaking spaces)
                                if subtitle:
                                    subtitle = subtitle.replace('\xa0', ' ')
                                
                                if title:
                                    query = f"{subtitle} - {title}" if subtitle else title
                                    tracks.append(query)
                            return {'type': 'playlist', 'tracks': tracks, 'title': entity.get('title', 'Spotify Playlist')}
                        
                        # Handle Single Track (Entity type might be 'track')
                        if entity.get('type') == 'track':
                             title = entity.get('title')
                             subtitle = entity.get('subtitle')
                             if subtitle:
                                 subtitle = subtitle.replace('\xa0', ' ')
                             query = f"{subtitle} - {title}" if subtitle else title
                             return {'type': 'track', 'query': query}
                             
                    except KeyError:
                        pass
                
                # Fallback: Scrape title from the ORIGINAL url if embed fails (Embed might behave differently on error)
                title_tag = soup.find('title')
                if title_tag:
                    text = title_tag.get_text()
                    # Embed title logic might be different?
                    clean_text = text.replace(' | Spotify', '').replace('- song by ', '').replace('- Song by ', '')
                    return {'type': 'track', 'query': clean_text}
            
            except Exception as e:
                print(f"Scrape error: {e}")
            return None

        loop = self.bot.loop or asyncio.get_event_loop()
        return await loop.run_in_executor(None, scrape)

    async def cleanup(self, guild):
        player = self.players.get(guild.id)
        if player:
            player._intentional_disconnect = True
            if player.player_task:
                player.player_task.cancel()
            if player.sticky_task:
                player.sticky_task.cancel()
            
            # Clean up message if exists
            if player.np:
                try:
                    await player.np.delete()
                except:
                    pass
                player.np = None

        try:
            if guild.voice_client:
                await guild.voice_client.disconnect()
        except:
            pass

        try:
            del self.players[guild.id]
        except KeyError:
            pass

    def get_player(self, ctx):
        try:
            player = self.players[ctx.guild.id]
        except KeyError:
            player = MusicPlayer(ctx, self)
            self.players[ctx.guild.id] = player
        
        return player

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Handle voice channel updates for auto-leave and kick detection."""
        # Track bot's own voice state to remember last channel OR detect kicks
        if member == self.bot.user:
            player = self.players.get(member.guild.id)
            if player:
                if after.channel:
                    player.last_voice_channel = after.channel
                    print(f"DEBUG: Updated last_voice_channel for guild {member.guild.id} to {after.channel.name}")
                elif before.channel and not after.channel:
                    # Bot was disconnected from a channel
                    if not player._intentional_disconnect:
                        print(f"DEBUG: Bot was externally disconnected/kicked from {before.channel.name}. Cleaning up.")
                        await self.cleanup(member.guild)
            return

        if member.bot: return
        
        # Check if bot is connected
        if not member.guild.voice_client: return

        # Check if the channel is the one bot is connected to
        # If the member LEFT the channel (before.channel == bot_channel)
        bot_channel = member.guild.voice_client.channel
        if before.channel != bot_channel: return
        
        # If bot is the only one left
        if len(bot_channel.members) == 1 and bot_channel.members[0] == self.bot.user:
            player = self.players.get(member.guild.id)
            if player and player.timer_enabled:
                 # Wait 3 minutes then check again
                 await asyncio.sleep(180)
                 # Re-check
                 if member.guild.voice_client and member.guild.voice_client.channel == bot_channel:
                     if len(bot_channel.members) == 1 and bot_channel.members[0] == self.bot.user:
                         await member.guild.voice_client.disconnect()
                         if player._channel:
                             await player._channel.send(embed=create_embed("Timeout", "Left voice channel due to inactivity."))
                         await self.cleanup(member.guild)



    @commands.command(name='join')
    async def join(self, ctx):
        """Joins the user's voice channel."""
        if not ctx.message.author.voice:
            await ctx.send(embed=create_error_embed("You are not connected to a voice channel."))
            return

        channel = ctx.message.author.voice.channel
        if ctx.voice_client is not None:
            return await ctx.voice_client.move_to(channel)

        await channel.connect()

    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx, *, search: str):
        """Request a song and add it to the queue."""
        
        async with ctx.typing():
            if not ctx.voice_client:
                 await ctx.invoke(self.join)
            
            if not ctx.voice_client:
                return

            # MUTUAL EXCLUSION: Check if MeLagu Live is active
            live_cog = self.bot.get_cog("MeLaguLive")
            if live_cog and live_cog.live_session:
                 return await ctx.send(embed=create_error_embed("Cannot play music while MeLagu Live is active. Stop Live first with `al!stoplive`!"))

            player = self.get_player(ctx)
            
            # Flush pending autoplay tracks to prioritize user request
            if not player.queue.empty():
                # We need to act on the internal deque safe-ish
                # Create a new deque without autoplay items
                new_queue = list()
                removed_items = []
                
                for item in player.queue._queue:
                    is_auto = False
                    if isinstance(item, dict) and item.get('is_autoplay'):
                        is_auto = True
                        
                    if not is_auto:
                        new_queue.append(item)
                    else:
                        removed_items.append(item)
                
                # Replace queue if items were removed
                if len(new_queue) != len(player.queue._queue):
                    # Clear and rebuild (thread-safety caveat: we are in async event loop, so it's serial)
                    player.queue._queue.clear()
                    player.queue._queue.extend(new_queue)
                    
                    # Consolidate prefetched data
                    if player.prefetched_data:
                         ref = player.prefetched_data.get('ref_item')
                         if ref in removed_items:
                             player.prefetched_data = None
                             print("DEBUG: Cleared prefetched autoplay data due to user priority.")
                    
                    print(f"DEBUG: Flushed {len(removed_items)} pending autoplay tracks to prioritize user request.")

            # Spotify Handling
            if 'open.spotify.com' in search:
                tracks = await self.get_spotify_tracks(search)
                if tracks:
                    if tracks.get('type') == 'playlist':
                        await ctx.send(embed=create_embed("Spotify Bridge", f"Queuing **{len(tracks['tracks'])}** tracks from **{tracks.get('title')}**..."))
                        for query in tracks['tracks']:
                            await player.queue.put({'query': query, 'title': query, 'webpage_url': None})
                        return
                    else:
                        # Single track
                        search = tracks['query']
                        await ctx.send(embed=create_embed("Spotify Bridge", f"Searching: **{search}**"))

            try:
                # Prepare the data
                loop = self.bot.loop or asyncio.get_event_loop()
                
                # Check if it's a playlist URL
                if 'list=' in search:
                    # ... (keep playlist logic as is for now, or lazy load it? playlists are complex)
                    # Let's keep playlists synchronous for now to show track count.
                    data = await loop.run_in_executor(None, lambda: _extract_info(search, download=False, process=False))
                    
                    if 'entries' in data:
                        # LAZY QUEUEING: Just put the playlist URL in the queue
                        # The player_loop will handle extracting items one by one
                        await player.queue.put({'playlist_url': search, 'requester': ctx.author})
                        await ctx.send(embed=create_embed("Added Playlist", f"Queued playlist: **{search}**\n(Tracks will be loaded as they play to prevent server lag)"))
                        return
                        
                # Check for URL (http/https)
                if search.startswith('http'):
                     # Normal URL processing (synchronous for now to get metadata)
                     data = await loop.run_in_executor(None, lambda: _extract_info(search, download=False))
                     if 'entries' in data:
                         data = data['entries'][0]
                     await player.queue.put(data)
                     embed = create_embed("Added to Queue", f"[{data['title']}]({data['webpage_url']})")
                     if 'thumbnail' in data:
                         embed.set_thumbnail(url=data['thumbnail'])
                     embed.add_field(name="Position", value=str(player.queue.qsize()))
                     await ctx.send(embed=embed)
                     return

                # LAZY LOADING -> SEMI-RESOLVED for Title
                # Run a quick flat search to get the Title
                # We use extract_flat=True for speed
                def resolve_title():
                    opts = dict(ytdl_format_options)
                    opts.update({'extract_flat': True, 'noplaylist': True})
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        try:
                            info = ydl.extract_info(f"ytsearch1:{search}", download=False)
                            if 'entries' in info and info['entries']:
                                return info['entries'][0]
                        except:
                            return None
                    return None

                data = await loop.run_in_executor(None, resolve_title)
                
                if data:
                    title = data.get('title')
                    url = data.get('url') # Might be ID or URL
                    if not url and data.get('id'):
                         url = f"https://www.youtube.com/watch?v={data['id']}"
                    
                    # Queue with resolved data
                    await player.queue.put({'title': title, 'url': url, 'id': data.get('id'), 'requester': ctx.author})
                    
                    embed = create_embed("🔎 Added to Queue", f"**[{title}]({url})**")
                    embed.add_field(name="Position", value=str(player.queue.qsize()))
                    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
                    await ctx.send(embed=embed)
                else:
                    # Fallback to query if failed
                    await player.queue.put({'query': search, 'title': search, 'requester': ctx.author})
                    embed = create_embed("🔎 Added to Queue", f"**{search}**")
                    embed.add_field(name="Position", value=str(player.queue.qsize()))
                    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
                    await ctx.send(embed=embed)
                
            except Exception as e:
                 await ctx.send(embed=create_error_embed(f"An error occurred: {e}"))

    @commands.command(name='pause')
    async def pause(self, ctx):
        """Pause the currently playing song."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send(embed=create_embed("Paused", "Music paused."))

    @commands.command(name='resume')
    async def resume(self, ctx):
        """Resume the currently paused song."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send(embed=create_embed("Resumed", "Music resumed."))

    @commands.command(name='stop')
    async def stop(self, ctx):
        """Stops playing and clears the queue (Requires voting or Starter)."""
        if ctx.guild.id not in self.players:
            return await ctx.send(embed=create_error_embed("No active player."))

        player = self.players[ctx.guild.id]
        
        # Priority Check: Starter or Owner can stop immediately
        if ctx.author.id == player.starter_id or is_owner(ctx.author):
            await self.cleanup(ctx.guild)
            reason = "the Starter" if ctx.author.id == player.starter_id else "the Owner"
            return await ctx.send(embed=create_embed("Stopped", f"Music stopped and queue cleared by {reason}."))
        
        # Voting Logic
        player.stop_votes.add(ctx.author.id)
        votes_needed = 3
        current_votes = len(player.stop_votes)
        
        if current_votes >= votes_needed:
            await self.cleanup(ctx.guild)
            await ctx.send(embed=create_embed("Stopped (Voted)", f"Music stopped and queue cleared by voting ({current_votes}/{votes_needed})."))
        else:
            await ctx.send(embed=create_embed("Vote to Stop", f"**{ctx.author.name}** voted to stop the music. ({current_votes}/{votes_needed} votes needed)"))
    
    @commands.command(name='queue', aliases=['q'])
    async def queue_info(self, ctx):
        """Retrieve a basic queue of upcoming songs."""
        if ctx.guild.id not in self.players:
            return await ctx.send(embed=create_embed("📂 Queue", "Queue is empty."))

        player = self.players[ctx.guild.id]
        if player.queue.empty():
            return await ctx.send(embed=create_embed("📂 Queue", "Queue is empty."))

        upcoming = list(player.queue._queue)
        view = PaginationView(ctx, upcoming, title=f"📂 Queue for {ctx.guild.name}")
        
        # Initial Embed (Page 1)
        start = 0
        end = view.items_per_page
        fmt = ''
        for i, item in enumerate(upcoming[start:end]):
            if isinstance(item, dict):
                 title = item.get('title')
                 url = item.get('url')
            else:
                 title = item.title
                 url = item.url
            
            if url:
                fmt += f'**{i + 1}.** [{title}]({url})\n'
            else:
                fmt += f'**{i + 1}.** {title}\n'
            
        embed = create_embed(f"📂 Queue ({len(upcoming)} songs) (1/{view.total_pages})", fmt)
        await ctx.send(embed=embed, view=view)
            
    @commands.command(name='autoplay')
    async def autoplay(self, ctx):
        """Toggle autoplay mode."""
        if ctx.guild.id not in self.players:
              return await ctx.send(embed=create_error_embed("No active player."))
              
        player = self.players[ctx.guild.id]
        player.autoplay = not player.autoplay
        status = "Enabled" if player.autoplay else "Disabled"
        
        if player.autoplay:
             description = "Autoplay will automatically queue related songs after the queue ends.\n"
             
             # Trigger immediate fetch if idle
             if player.queue.empty() and not ctx.voice_client.is_playing() and player.last_track:
                 description += "Fetching related track now..."
                 await ctx.send(embed=create_embed("🤖 Autoplay", f"Autoplay has been **{status}**.\n{description}"))
                 
                 # Fetch logic
                 try:
                     recommendation = await player.get_recommendation(player.last_track.data)
                     if recommendation:
                         await player.queue.put(recommendation)
                         await ctx.send(embed=create_embed("🤖 Autoplay", f"Queued related track: **{recommendation.get('title')}**"))
                     else:
                         await ctx.send(embed=create_error_embed("Could not find a related track to play."))
                 except Exception as e:
                     print(f"Manual autoplay trigger error: {e}")
                 return

        else:
             description = "Autoplay disabled."
        await ctx.send(embed=create_embed("🤖 Autoplay", f"Autoplay has been **{status}**.\n{description}"))

    @commands.command(name='list', aliases=['history', 'recent'])
    async def list_history(self, ctx):
        """Show the list of recently played songs."""
        if ctx.guild.id not in self.players:
              return await ctx.send(embed=create_error_embed("No history available."))
              
        player = self.players[ctx.guild.id]
        if not player.history:
             return await ctx.send(embed=create_embed("📜 History", "No songs played in this session yet."))
             
        # Show all history (reversed)
        recent = list(player.history)
        recent.reverse() # Show newest first
        
        view = PaginationView(ctx, recent, title=f"📜 History for {ctx.guild.name}")
        
        # Initial Embed (Page 1)
        start = 0
        end = view.items_per_page
        fmt = ""
        for i, track in enumerate(recent[start:end]):
            track_url = track['url']
            if track_url and len(track_url) < 500:
                 fmt += f"**{i+1}.** [{track['title']}]({track_url})\n"
            else:
                 fmt += f"**{i+1}.** {track['title']}\n"
            
        embed = create_embed(f"📜 Session History ({len(player.history)} Total) (1/{view.total_pages})", fmt)
        await ctx.send(embed=embed, view=view)
    @commands.command(name='remove', aliases=['rm', 'delete'])
    async def remove(self, ctx, *, query: str = None):
        """Remove a song from the queue by Index, Title, or 'last'."""
        if ctx.guild.id not in self.players:
            return await ctx.send(embed=create_error_embed("No active player."))
            
        player = self.players[ctx.guild.id]
        if player.queue.empty():
            return await ctx.send(embed=create_error_embed("Queue is already empty."))
            
        if not query:
             return await ctx.send(embed=create_error_embed("Please specify what to remove (Index, Title, or 'last')."))

        # Access internal queue safely-ish
        queue_list = list(player.queue._queue)
        removed_item = None
        
        target = query.lower().strip()
        
        if target == 'last':
            removed_item = queue_list.pop()
            
        elif target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(queue_list):
                removed_item = queue_list.pop(idx)
            else:
                return await ctx.send(embed=create_error_embed(f"Invalid index. Range: 1-{len(queue_list)}"))
                
        else:
            # Search by title
            for i, item in enumerate(queue_list):
                title = item.get('title') if isinstance(item, dict) else item.title
                if target in title.lower():
                    removed_item = queue_list.pop(i)
                    break
            
            if not removed_item:
                 return await ctx.send(embed=create_error_embed(f"Could not find song with title: {query}"))

        # Rebuild Queue
        player.queue = asyncio.Queue()
        for item in queue_list:
            await player.queue.put(item)
            
        title = removed_item.get('title') if isinstance(removed_item, dict) else removed_item.title
        await ctx.send(embed=create_embed("🗑️ Removed", f"Removed **{title}** from the queue."))

async def setup(bot):
    await bot.add_cog(Music(bot))
