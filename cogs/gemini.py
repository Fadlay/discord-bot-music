import discord
import os
import json
import asyncio
import struct
import time
import numpy as np
import scipy.signal
from discord.ext import commands
from discord.ext.voice_recv import VoiceRecvClient, BasicSink
from google import genai
from google.genai import types, errors
from utils import GeminiKeyManager, send_error_log

# Audio Configuration
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS = 2
GEMINI_INPUT_SAMPLE_RATE = 16000
GEMINI_OUTPUT_SAMPLE_RATE = 24000
FRAME_SIZE = 20 # ms

class GeminiAudioSource(discord.AudioSource):
    """Reads PCM data from a queue, resamples it, and plays it to Discord."""
    def __init__(self):
        self.queue = asyncio.Queue()
        self.buffer = bytearray()
        self.sample_rate = DISCORD_SAMPLE_RATE
    
    def add_data(self, data):
        """Adds 24kHz mono data to queue."""
        self.queue.put_nowait(data)

    def read(self):
        # We need 20ms of 48kHz stereo = 960 samples * 4 bytes = 3840 bytes
        frame_size_bytes = 3840 
        
        # If not enough data, return silence or silence frame?
        # For simplicity, we try to fetch from queue and buffer
        # This is a blocking read called by Discord, so we can't await properly here
        # But we can try to get from queue non-blocking
        
        while len(self.buffer) < frame_size_bytes:
            try:
                # Get raw 24kHz mono chunk
                chunk = self.queue.get_nowait()
                
                # Resample 24k Mono -> 48k Stereo
                # Convert bytes to numpy array (int16)
                audio_data = np.frombuffer(chunk, dtype=np.int16)
                
                # Resample: 24000 -> 48000 (2x)
                # Simple repeat for speed? No, resample is better.
                # len(audio_data) * 2
                resampled = scipy.signal.resample(audio_data, len(audio_data) * 2).astype(np.int16)
                
                # Mono to Stereo: duplicate channels
                # shape (N,) -> (N, 2)
                stereo = np.stack((resampled, resampled), axis=-1).flatten()
                
                self.buffer.extend(stereo.tobytes())
            except asyncio.QueueEmpty:
                return b'\x00' * frame_size_bytes # Silence if empty

        data = self.buffer[:frame_size_bytes]
        del self.buffer[:frame_size_bytes]
        # print(f"DEBUG: Playing {len(data)} bytes")
        return bytes(data)

    def cleanup(self):
        pass

import threading

# ... existing imports ...

class GeminiSink(BasicSink):
    """Receives Discord audio, resamples it, and sends to Gemini."""
    def __init__(self, session, personas_instr):
        super().__init__(threading.Event()) # Initialize BasicSink properly
        self.session = session
        self.personas_instr = personas_instr
        self.packet_buffer = bytearray()
        self.is_speaking = False
        self.last_packet_time = time.time()
        
    def write(self, user, data):
        # Update heartbeat
        self.last_packet_time = time.time()
        # logging.info(f"DEBUG: Pkt from {user}") 
        
        if user is None: 
            return 
        
        # Log every 50 packets (~1 sec) to show it's working without spam
        # if not hasattr(self, 'pkt_count'): self.pkt_count = 0
        # self.pkt_count += 1
        # if self.pkt_count % 50 == 0:
        # print(f"DEBUG: Got packet from {user}, size: {len(data.pcm)}") 
        
        pcm = data.pcm 
        self.packet_buffer.extend(pcm)
        
        # Process every ~100ms or so to send reasonable chunks
        # 100ms of 48k stereo = 4800 * 4 = 19200 bytes
        CHUNK_SIZE = 19200
        
        if len(self.packet_buffer) >= CHUNK_SIZE:
                # Get the chunk to process
                chunk = self.packet_buffer[:CHUNK_SIZE]
                del self.packet_buffer[:CHUNK_SIZE]

                # Resample 48k -> 16k (1/3) using simple slicing (faster)
                # Resample 48k Stereo -> 16k Mono
                audio_data = np.frombuffer(chunk, dtype=np.int16)
                audio_data = audio_data.reshape(-1, 2)
                mono = audio_data.mean(axis=1).astype(np.int16)
                
                # Slicing: Take every 3rd sample
                resampled = mono[::3] 
                
                # DEBUG: Save to file to verify audio quality
                with open("debug_audio.pcm", "ab") as f:
                    f.write(resampled.tobytes())

                # Simple VAD (Voice Activity Detection)
                rms = np.sqrt(np.mean(resampled.astype(float)**2))
                THRESHOLD = 200 # Adjusted for 16k mono
                
                if rms > THRESHOLD:
                    if not self.is_speaking:
                        self.is_speaking = True
                        print(f"DEBUG: Speech STARTED (RMS: {int(rms)})")
                    
                    asyncio.create_task(self.send_to_gemini(resampled.tobytes(), end_of_turn=False))
                    
                else:
                    if self.is_speaking:
                         self.is_speaking = False
                         print(f"DEBUG: Speech STOPPED (RMS: {int(rms)}) -> Triggering Reply")
                         asyncio.create_task(self.send_to_gemini(b'', end_of_turn=True))

    async def check_silence_timeout(self):
        """Called periodically to check if Discord stopped sending packets (User stopped talking)."""
        if self.is_speaking and (time.time() - self.last_packet_time > 1.0):
             self.is_speaking = False
             print("DEBUG: Implicit Silence Detected (Discord VAD) -> Triggering Reply")
             asyncio.create_task(self.send_to_gemini(b'', end_of_turn=True))

    async def send_to_gemini(self, data, end_of_turn=False):
        try:
            payload = {"data": data, "mime_type": "audio/pcm"} if data else None
            
            if payload:
                await self.session.send(input=payload, end_of_turn=end_of_turn)
            elif end_of_turn:
                 await self.session.send(input={"data": b'', "mime_type": "audio/pcm"}, end_of_turn=True)
                 
        except Exception as e:
            print(f"Error sending to Gemini: {e}")
            await send_error_log(self.session.bot if hasattr(self.session, 'bot') else None, e, extra_info="GeminiSink.send_to_gemini")


class MeLaguLive(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.key_manager = GeminiKeyManager()
        if not self.key_manager.has_keys:
            print("Warning: No Gemini API keys found in .env")

        # Try to load Opus manually if needed
        if not discord.opus.is_loaded():
            try:
                discord.opus.load_opus("./libopus-0.x64.dll")
            except Exception:
                pass # Will be checked again in live command
        
        self.live_session = None # Initialize session state
        self.session_starters = {} # guild_id -> author_id
        self.session_votes = {} # guild_id -> set(author_ids)

    def get_system_instruction(self, user_id, guild=None):
        chat_cog = self.bot.get_cog("Chat")
        if chat_cog:
            return chat_cog.get_system_instruction(user_id, guild=guild)
        return "You are a helpful assistant."

    # Text chat features moved to cogs/chat.py

    async def send_text_input(self, text):
        """Sends text input to the active Live session."""
        if self.live_session:
            await self.live_session.send(input=text, end_of_turn=True)
            return True
        return False

    @commands.command()
    async def live(self, ctx):
        """
        Starts a MeLagu Live session.        
        Connects to your voice channel and allows you to talk to MeLagu in real-time.
        The bot will use your current Persona.
        """
        try:
            if not ctx.author.voice:
                return await ctx.send("Join a voice channel!")
                
            if not discord.opus.is_loaded():
                print("WARNING: Opus library not loaded! Audio receiving will fail.")
                await ctx.send("⚠️ Warning: Opus library not loaded. I might be deaf.")
            
            if ctx.voice_client:
                # MUTUAL EXCLUSION: Check if Music is playing
                music_cog = self.bot.get_cog("Music")
                if music_cog:
                    player = music_cog.players.get(ctx.guild.id)
                    if player and player.current:
                        return await ctx.send("⚠️ Cannot start MeLagu Live while music is playing. Stop the music first!")
                
                await ctx.voice_client.disconnect()
            
            status_msg = await ctx.send("⏳ Initiating MeLagu Live... (Connecting to Voice)")
            
            # Get Persona
            instr = self.get_system_instruction(ctx.author.id, guild=ctx.guild)
            
            # INJECT CHAT HISTORY (Memory Sync)
            # We fetch the recent text chat history to give the Live model context
            chat_cog = self.bot.get_cog("Chat")
            if chat_cog:
                 user_id = str(ctx.author.id)
                 if user_id in chat_cog.histories:
                     history = chat_cog.histories[user_id]
                     # Take last 10 turns to avoid token limits
                     recent_history = history[-10:] 
                     
                     context_str = "\n\n[CONTEXT FROM PREVIOUS TEXT CHAT]:\n"
                     for item in recent_history:
                         role = "User" if item.role == "user" else "Model"
                         # Filter out None values in case of function calls
                         text = " ".join([p.text for p in item.parts if p.text])
                         context_str += f"{role}: {text}\n"
                     
                     instr += context_str

            # Connect to Voice with VoiceRecvClient
            try:
                await ctx.send(f"📡 DEBUG: Connecting to `{ctx.author.voice.channel.name}`...")
                
                # Add a timeout to the connection attempt
                vc = await asyncio.wait_for(ctx.author.voice.channel.connect(cls=VoiceRecvClient), timeout=15.0)
                await status_msg.edit(content="✅ Connected to Voice! Starting Live Session...")
            except asyncio.TimeoutError:
                return await ctx.send("❌ Connection Timed Out. Discord is taking too long to respond. Try joining/leaving the channel manually.")
            except Exception as e:
                print(f"Connection Error: {e}")
                return await ctx.send(f"❌ Failed to connect to voice: `{e}`")

            # Record Starter and Reset Votes
            self.session_starters[ctx.guild.id] = ctx.author.id
            self.session_votes[ctx.guild.id] = set()

            # Start Session Task
            await ctx.send("🚀 Launching Live Session Task...")
            self.bot.loop.create_task(self.run_session(ctx, vc, instr))
            
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"CRITICAL ERROR in live command: {e}\n{tb}")
            await ctx.send(f"❌ A critical error occurred while starting Live: `{e}`\nCheck console for details.")

    async def run_session(self, ctx, vc, instr):
        # Connect to Gemini Live
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
                )
            ),
            system_instruction=types.Content(parts=[types.Part.from_text(text=instr)])
        )
        
        self.live_session = None # Track active session
        self.key_manager.reset_failure_checks()
        
        while True:
            client = self.key_manager.get_client()
            try:
                # print(f"DEBUG: Connecting to Gemini...")
                print(f"DEBUG: Connecting to Gemini with model 'gemini-2.5-flash-native-audio-preview-12-2025'")
                # Use async context manager for connection
                async with client.aio.live.connect(model="gemini-2.5-flash-native-audio-preview-12-2025", config=config) as session:
                    print("DEBUG: Connected to MeLagu Live API!")
                    self.live_session = session # Store it!
                    
                    # Notify User
                    persona_name = "default"
                    chat_cog = self.bot.get_cog("Chat")
                    if chat_cog:
                        settings = chat_cog.user_settings.get(str(ctx.author.id), {})
                        persona_name = settings.get("persona", "default")
                    
                    await ctx.send(f"Connected to Live! Persona: **{persona_name}**\nType in chat to speak! 🗣️")
                    
                    # Setup Audio Output (Gemini -> Discord)
                    audio_source = GeminiAudioSource()
                    vc.play(audio_source)
                    
                    # Setup Voice Receiving (Discord -> Gemini)
                    sink = GeminiSink(session, instr)
                    vc.listen(sink)
                    
                    try:
                        while ctx.voice_client == vc and ctx.voice_client.is_connected():
                            async for response in session.receive():
                                # Fallback exit check inside receive loop
                                if not ctx.voice_client or ctx.voice_client != vc:
                                    break

                                if response.server_content and response.server_content.model_turn:
                                    for part in response.server_content.model_turn.parts:
                                        if part.inline_data:
                                            audio_source.add_data(part.inline_data.data)

                            print("DEBUG: Gemini session.receive() ended. Reconnecting loop...")
                            await asyncio.sleep(1) 
                        
                    except Exception as e:
                        print(f"Receive Loop Error: {e}")
                    finally:
                        print("DEBUG: Receive Loop Exited")
                
                break # Exit the while True loop on successful connection completion
                    
            except errors.APIError as e:
                # Code 429 is Rate Limit
                if e.code == 429:
                    print(f"DEBUG: Key {self.key_manager.current_index} rate limited. Rotating for Live session...")
                    if self.key_manager.rotate():
                        continue
                    else:
                        await ctx.send("❌ Semua API Key MeLagu sudah mencapai batas (rate limit). Gagal memulai Live session. 🙏")
                        break
                else:
                    await ctx.send(f"⚠️ Kesalahan API Gemini: {e}")
                    break
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                print(f"ERROR: MeLagu Live Session Error: {e}")
                print(error_trace)
                await ctx.send(f"❌ MeLagu Session Error: `{e}`\nCheck console for more details.")
                break
        
        self.live_session = None
        if ctx.voice_client and ctx.voice_client.is_connected():
            await ctx.voice_client.disconnect()

    @commands.command()
    async def stoplive(self, ctx):
        """
        Stops the MeLagu Live session and disconnects (Requires voting or Starter).
        """
        if not ctx.voice_client:
            return await ctx.send("I'm not in a voice channel.")

        if not self.live_session:
            return await ctx.send("⚠️ No active MeLagu Live session found. Use `al!stop` if you want to stop music.")

        starter_id = self.session_starters.get(ctx.guild.id)
        
        # Priority Check: Starter can stop immediately
        if ctx.author.id == starter_id:
            self.live_session = None # Clear state immediately
            await ctx.voice_client.disconnect()
            return await ctx.send("Disconnected by the Starter.")

        # Voting Logic
        votes = self.session_votes.get(ctx.guild.id, set())
        votes.add(ctx.author.id)
        self.session_votes[ctx.guild.id] = votes
        
        votes_needed = 3
        current_votes = len(votes)

        if current_votes >= votes_needed:
            self.live_session = None # Clear state immediately
            await ctx.voice_client.disconnect()
            await ctx.send(f"Disconnected by voting ({current_votes}/{votes_needed}).")
        else:
            await ctx.send(f"**{ctx.author.name}** voted to stop the Live session. ({current_votes}/{votes_needed} votes needed)")

async def setup(bot):
    await bot.add_cog(MeLaguLive(bot))
