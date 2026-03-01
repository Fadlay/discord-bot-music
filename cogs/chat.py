import discord
import os
import json
import asyncio
from discord.ext import commands
from google import genai
from google.genai import types, errors
from utils import GeminiKeyManager, send_split_message, is_owner, get_maintenance_state, create_error_embed, send_error_log

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = None
        self.personas = {}
        self.user_settings = {}
        self.global_settings = {}
        self.histories = {} # Store per-user or shared chat history
        self.locks = {} # Per-history locks for concurrency control
        self.history_file = "chat_history.json"
        self.settings_file = "user_settings.json"
        self.global_file = "global_settings.json"
        
        self.load_personas()
        self.load_history()
        self.load_user_settings()
        self.load_global_settings()
        
        self.key_manager = GeminiKeyManager()
        if not self.key_manager.has_keys:
            print("Warning: No Gemini API keys found in .env")

    def load_personas(self):
        try:
            with open("personas.json", "r") as f:
                data = json.load(f)
                # Migration: Convert old string format to new dict format
                self.personas = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        self.personas[k] = {"instruction": v, "author_id": None}
                    else:
                        self.personas[k] = v
        except FileNotFoundError:
            self.personas = {"default": {"instruction": "You are a helpful assistant.", "author_id": None}}
            self.save_personas()

    def save_personas(self):
        with open("personas.json", "w") as f:
            json.dump(self.personas, f, indent=4)

    def load_user_settings(self):
        try:
            with open(self.settings_file, "r") as f:
                data = json.load(f)
                self.user_settings = {}
                for user_id, settings in data.items():
                    if isinstance(settings, str):
                        # Migration from legacy persona string to dict
                        self.user_settings[user_id] = {"persona": settings, "chat_mode": "public"}
                    else:
                        self.user_settings[user_id] = settings
        except FileNotFoundError:
            self.user_settings = {}

    def save_user_settings(self):
        with open(self.settings_file, "w") as f:
            json.dump(self.user_settings, f, indent=4)

    def load_global_settings(self):
        try:
            with open(self.global_file, "r") as f:
                self.global_settings = json.load(f)
        except FileNotFoundError:
            self.global_settings = {}

    def save_global_settings(self):
        with open(self.global_file, "w") as f:
            json.dump(self.global_settings, f, indent=4)

    def load_history(self):
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
                self.histories = {}
                for user_id, history_list in data.items():
                    self.histories[user_id] = []
                    for item in history_list:
                        # Reconstruct parts
                        parts = []
                        for p_data in item["parts"]:
                            if "text" in p_data and p_data["text"] is not None:
                                parts.append(types.Part.from_text(text=p_data["text"]))
                            elif "function_call" in p_data:
                                fc = p_data["function_call"]
                                parts.append(types.Part.from_function_call(name=fc["name"], args=fc["args"]))
                            elif "function_response" in p_data:
                                fr = p_data["function_response"]
                                parts.append(types.Part.from_function_response(name=fr["name"], response=fr["response"]))
                        
                        self.histories[user_id].append(types.Content(role=item["role"], parts=parts))
        except FileNotFoundError:
            self.histories = {}
        except Exception as e:
            print(f"Error loading history: {e}")
            self.histories = {}

    def save_history(self):
        data = {}
        for user_id, history_list in self.histories.items():
            data[user_id] = []
            for item in history_list:
                parts_data = []
                for p in item.parts:
                    if p.text:
                        parts_data.append({"text": p.text})
                    elif p.function_call:
                        parts_data.append({
                            "function_call": {
                                "name": p.function_call.name,
                                "args": dict(p.function_call.args)
                            }
                        })
                    elif p.function_response:
                        parts_data.append({
                            "function_response": {
                                "name": p.function_response.name, # name field for FunctionResponse might not be directly accessible as attribute in some SDK versions, check types. Assuming it is.
                                "response": dict(p.function_response.response)
                            }
                        })
                
                data[user_id].append({
                    "role": item.role,
                    "parts": parts_data
                })
        
        with open(self.history_file, "w") as f:
            json.dump(data, f, indent=4)

    def get_system_instruction(self, user_id, guild=None, chat_mode="private"):
        # Select persona based on chat mode
        if chat_mode == "public" and guild:
            # Use global persona for this guild
            guild_id = str(guild.id)
            settings = self.global_settings.get(guild_id, {})
            persona_key = settings.get("persona", "default")
        else:
            # Use individual persona
            settings = self.user_settings.get(str(user_id), {})
            persona_key = settings.get("persona", "default")

        persona_data = self.personas.get(persona_key, self.personas.get("default"))
        # Handle case where persona might have been deleted but user/guild still has it selected
        if not persona_data:
             persona_data = self.personas.get("default")
        
        instruction = persona_data["instruction"]

        # --- EMOJI & STICKER AWARENESS ---
        instruction += "\n\n[EMOJI & STICKER GUIDELINES]:\n"
        instruction += "- Kamu bisa melihat emoji kustom user dalam format :nama_emoji: dan stiker dalam format [Sticker: nama_stiker].\n"
        instruction += "- Kamu memiliki kemampuan 'Nitro'. Kamu bisa menggunakan emoji kustom dari seluruh server yang bot masuki dengan menulis :nama_emoji:. Bot akan otomatis mengubahnya menjadi emoji asli.\n"
        instruction += "- PENTING: Jangan mengarang nama emoji kustom yang tidak ada (misal :shocked:). Gunakan HANYA nama emoji yang ada di daftar [AVAILABLE EMOJIS] di bawah ini, atau emoji standar bawaan.\n"
        instruction += "- Untuk stiker, kamu hanya bisa mengirim stiker yang berasal dari server ini. Jika kamu mencoba mengirim stiker luar, bot mungkin hanya mengirimkan teksnya saja.\n"
        instruction += "- Kamu bisa memanggil (mention) orang dengan format @username (gunakan username unik yang ada di tanda kurung dari [SERVER MEMBERS]). Contoh: jika ada member 'Aiden (@aidennn)', panggil dengan @aidennn. Bot akan otomatis mengubahnya menjadi mention biru."

        # --- AVAILABLE EMOJIS CONTEXT ---
        try:
            if self.bot.emojis:
                import random
                # Provide up to 150 global emojis to give the AI a good vocabulary without bloating the prompt
                sample_emojis = self.bot.emojis
                if len(sample_emojis) > 150:
                    sample_emojis = random.sample(sample_emojis, 150)
                
                emoji_names = sorted([f":{e.name}:" for e in sample_emojis])
                instruction += f"\n\n[AVAILABLE EMOJIS (Showing {len(emoji_names)}/{len(self.bot.emojis)})]:\n"
                instruction += ", ".join(emoji_names)
        except Exception as e:
            print(f"DEBUG: Failed to fetch emoji list: {e}")

        # --- SERVER MEMBER CONTEXT ---
        if guild:
            try:
                # Prioritize online/active members
                all_members = list(guild.members)
                # Filter out bots and sort: Online -> Idle -> DND -> Offline
                all_members.sort(key=lambda m: (m.status == discord.Status.offline, m.status == discord.Status.invisible, m.bot))
                
                member_list = []
                for m in all_members:
                    if m.bot: continue
                    if len(member_list) >= 100: break # Keep prompt size safe
                    
                    status_icon = "🟢" if m.status == discord.Status.online else "🟡" if m.status == discord.Status.idle else "🔴" if m.status == discord.Status.dnd else "⚪"
                    roles = [r.name for r in m.roles if r.name != "@everyone"][:3] # Max 3 roles for brevity
                    role_str = f" ({', '.join(roles)})" if roles else ""
                    member_list.append(f"- {status_icon} {m.display_name} (@{m.name}){role_str}")
                
                total_members = guild.member_count
                if member_list:
                    instruction += f"\n\n[SERVER MEMBERS (Showing 100/{total_members})]:\n" + "\n".join(member_list)
                    if total_members > 100:
                        instruction += "\n... (Daftar di atas diprioritaskan untuk member yang sedang online)"
            except Exception as e:
                print(f"DEBUG: Failed to fetch member list: {e}")

        # Inject Song Context if available
        if guild:
            music_cog = self.bot.get_cog("Music")
            if music_cog:
                player = music_cog.players.get(guild.id)
                if player and player.current:
                    song_info = f"\n\n[NOW PLAYING CONTEXT]:\nYou are currently playing: '{player.current.title}'"
                    if hasattr(player.current, 'uploader') and player.current.uploader:
                        song_info += f" by {player.current.uploader}"
                    instruction += song_info

        return instruction

    @commands.group(invoke_without_command=True)
    async def persona(self, ctx):
        """
        Manage chat personas.
        
        View your current persona or use subcommands to list/set/add/delete personas.
        """
        settings = self.user_settings.get(str(ctx.author.id), {})
        current = settings.get("persona", "default")
        await ctx.send(f"Current Persona: **{current}**\nCommands: `al!persona list`, `al!persona set <name>`")

    @persona.command(name="list")
    async def persona_list(self, ctx):
        """
        List all available personas (Public + Your Private ones).
        """
        available = []
        for name, data in self.personas.items():
            # Show if public (no author_id) or if owned by user
            if data["author_id"] is None or data["author_id"] == ctx.author.id:
                available.append(f"`{name}`")
            
        keys = ", ".join(available)
        await ctx.send(f"Available Personas: {keys}")

    @persona.command(name="set")
    async def persona_set(self, ctx, name: str):
        """
        Set your personal persona.
        
        Usage: `al!persona set <name>`
        Example: `al!persona set tsundere`
        """
        if name not in self.personas:
             return await ctx.send(f"❌ Persona `{name}` not found.")
        
        # Prevent setting a private persona that isn't yours
        data = self.personas[name]
        if data["author_id"] is not None and data["author_id"] != ctx.author.id:
             return await ctx.send(f"❌ Persona `{name}` is private.")

        if str(ctx.author.id) not in self.user_settings:
            self.user_settings[str(ctx.author.id)] = {"persona": "default", "chat_mode": "public"}
            
        self.user_settings[str(ctx.author.id)]["persona"] = name
        self.save_user_settings()
        await ctx.send(f"Persona set to: **{name}**")

    @persona.command(name="add")
    async def persona_add(self, ctx, name: str, *, instruction: str):
        """
        Add a new private persona.
        
        Usage: `al!persona add <name> <instruction>`
        Example: `al!persona add yoda You are Yoda. Speak like Yoda you must.`
        """
        if name in self.personas:
            return await ctx.send("Persona already exists.")
        
        self.personas[name] = {
            "instruction": instruction,
            "author_id": ctx.author.id
        }
        self.save_personas()
        await ctx.send(f"Persona **{name}** added! (Visible only to you)")

    @persona.command(name="delete")
    async def persona_delete(self, ctx, name: str):
        """
        Delete a custom persona.
        
        Usage: `al!persona delete <name>`
        Cannot delete the 'default' persona.
        """
        if name == "default":
            return await ctx.send("❌ You cannot delete the default persona.")
        
        if name not in self.personas:
            return await ctx.send(f"❌ Persona `{name}` not found.")
            
        data = self.personas[name]
        if data["author_id"] is not None and data["author_id"] != ctx.author.id:
            return await ctx.send("❌ You can only delete personas you created.")

        del self.personas[name]
        self.save_personas()
        await ctx.send(f"✅ Persona **{name}** deleted!")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # Check if mentioned or in a 'gemini' channel
        is_mentioned = self.bot.user in message.mentions
        is_chat_channel = isinstance(message.channel, discord.TextChannel) and "gemini" in (message.channel.topic or "").lower()
        
        if is_mentioned or is_chat_channel:
            # Check for Maintenance Mode
            is_maintenance, maintenance_reason = get_maintenance_state()
            if not is_owner(message.author) and is_maintenance:
                if is_mentioned:
                    reason_str = f"**Reason:** {maintenance_reason}\n\n" if maintenance_reason else ""
                    await message.reply(embed=create_error_embed(f"🚧 **Bot is currently under maintenance.**\n\n{reason_str}AI interactions are restricted to Owners only."))
                return

            # Ignore if it's a command
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return

            if not self.key_manager.has_keys:
                if is_mentioned:
                    await message.reply("❌ Gemini API Key missing!")
                return

            async with message.channel.typing():
                try:
                    # 1. Determine History Context (Shared or Private) with Server Isolation
                    user_id = str(message.author.id)
                    user_settings = self.user_settings.get(user_id, {"persona": "default", "chat_mode": "public"})
                    chat_mode = user_settings.get("chat_mode", "public")
                    
                    guild_id = str(message.guild.id) if message.guild else "dm"
                    
                    # PRIORITY 1: Maintenance Isolation (Test Mode) - GLOBAL across servers
                    is_maintenance, _ = get_maintenance_state()
                    if is_maintenance:
                        history_id = f"test_{user_id}"
                    # PRIORITY 2: Isolated Private Channel ID
                    elif message.channel.id == 1429779152919068733:
                        history_id = f"channel_{message.channel.id}"
                    else:
                        # Isolated by Guild ID
                        if chat_mode == "private":
                            history_id = f"{guild_id}_{user_id}"
                        else:
                            history_id = f"shared_{guild_id}"
                    
                    # Ensure lock exists for this history
                    if history_id not in self.locks:
                        self.locks[history_id] = asyncio.Lock()
                    
                    # SERIALIZE PROCESS PER HISTORY
                    async with self.locks[history_id]:
                        print(f"DEBUG: Processing message from {message.author}: {message.content} (History: {history_id})")
                        
                        # --- MESSAGE PRE-PROCESSING ---
                        clean_text = message.clean_content
                        # Remove the bot's own mention
                        bot_mention_nick = f"@{message.guild.me.display_name}" if message.guild else f"@{self.bot.user.name}"
                        bot_mention_user = f"@{self.bot.user.name}"
                        
                        raw_user_input = clean_text.replace(bot_mention_nick, "").replace(bot_mention_user, "").strip()
                        
                        # 1. Process Stickers
                        if message.stickers:
                            sticker_info = " ".join([f"[Sticker: {s.name}]" for s in message.stickers])
                            raw_user_input = (raw_user_input + f"\n{sticker_info}").strip()

                        # 2. Simplify Custom Emojis for AI (from <:name:id> to :name:)
                        import re
                        raw_user_input = re.sub(r'<(a?):(\w+):(\d+)>', r':\2:', raw_user_input)

                        # Final Fallback
                        if not raw_user_input: 
                            raw_user_input = "Hello"
                        
                        prompt_text = raw_user_input
                        
                        # 3. Check for Reply Context (Add prefix to prompt_text)
                        replied_msg = None
                        if message.reference and message.reference.message_id:
                            try:
                                replied_msg = message.reference.cached_message
                                if not replied_msg:
                                    replied_msg = await message.channel.fetch_message(message.reference.message_id)
                                
                                author_name = replied_msg.author.display_name
                                replied_content = replied_msg.clean_content
                                
                                if len(replied_content) > 500:
                                    replied_content = replied_content[:497] + "..."
                                    
                                context_prefix = f"[Replying to {author_name}: \"{replied_content}\"]\n\n"
                                prompt_text = context_prefix + raw_user_input
                                print(f"DEBUG: Added reply context from {author_name}")
                            except Exception as e:
                                print(f"DEBUG: Failed to fetch reply context: {e}")
                        # --- END PRE-PROCESSING ---

                        # CHECK FOR LIVE SESSION (Text-to-Speech Mode)
                        live_cog = self.bot.get_cog("MeLaguLive")
                        if live_cog and live_cog.live_session:
                            # Check if user is in the same voice channel
                            if message.author.voice and message.guild.voice_client and \
                               message.author.voice.channel == message.guild.voice_client.channel:
                                   print(f"DEBUG: Sending text input to Live Session: {raw_user_input}")
                                   success = await live_cog.send_text_input(raw_user_input)
                                   if success:
                                       await message.add_reaction("🗣️") # Indicate audio response
                                       return # Stop processing text response
                    
                    if history_id not in self.histories:
                        self.histories[history_id] = []
                    
                    # 2. Add User Message to History (Multimodal support)
                    # For shared history, add the user's name to the prompt
                    final_prompt = prompt_text
                    if history_id.startswith("shared"):
                        final_prompt = f"(User: {message.author.display_name}) {prompt_text}"
                    
                    parts = [types.Part.from_text(text=final_prompt)]
                    
                    # Collect all attachments (Original + Replied)
                    all_attachments = list(message.attachments)
                    if replied_msg and replied_msg.attachments:
                        all_attachments.extend(replied_msg.attachments)

                    if all_attachments:
                        # Supported MIME types for Gemini: Images, Video, Audio, Documents
                        supported_prefixes = ("image/", "video/", "audio/")
                        supported_types = ("application/pdf", "text/plain")
                        
                        for attachment in all_attachments:
                            # 15MB size limit per file
                            if attachment.size > 15 * 1024 * 1024:
                                print(f"DEBUG: Skipping {attachment.filename} - too large ({attachment.size} bytes)")
                                continue
                                
                            if attachment.content_type and (attachment.content_type.startswith(supported_prefixes) or attachment.content_type in supported_types):
                                try:
                                    print(f"DEBUG: Processing multimodal attachment: {attachment.filename} ({attachment.content_type})")
                                    media_bytes = await attachment.read()
                                    parts.append(types.Part.from_bytes(data=media_bytes, mime_type=attachment.content_type))
                                except Exception as e:
                                    print(f"DEBUG: Failed to read attachment {attachment.filename}: {e}")
                            else:
                                print(f"DEBUG: Skipping unsupported attachment type: {attachment.content_type}")

                    self.histories[history_id].append(types.Content(role="user", parts=parts))
                    print(f"DEBUG: Added prompt to {history_id} history with {len(parts)-1} media parts.")
                    
                    # 3. Limit History (Sliding Window - e.g., last 20 items, must start with user)
                    if len(self.histories[history_id]) > 1000: # High safety cap, pruning will handle tokens
                        start_idx = len(self.histories[history_id]) - 1000
                        # Ensure we start with a user message
                        while start_idx < len(self.histories[history_id]) and self.histories[history_id][start_idx].role != "user":
                            start_idx += 1
                        self.histories[history_id] = self.histories[history_id][start_idx:]
                    
                    system_instr = self.get_system_instruction(message.author.id, guild=message.guild, chat_mode=chat_mode)
                    
                    print("DEBUG: Sending request to Gemini API (Text)...")
                    # 4. Generate Content with History
                    # === INTENT DETECTION ===
                    # We check only the actual message content (without prefix/context) for music keywords
                    music_keywords = ["putar", "play", "skip", "volume", "lagu", "musik", "pause", "resume", "berhenti", "stop", "antrean", "queue", "shuffle", "loop", "bassboost", "nightcore", "vaporwave", "speed", "reset", "playlist", "rekomendasi", "rekomen", "recommend", "vibe", "genre", "mood", "suasana", "dengerin", "denger", "saran", "saranin", "buatin", "buatkan"]
                    
                    # Use raw_user_input for intent detection to avoid matching keywords in reply context
                    # We use a leading \b word boundary but no trailing boundary to support
                    # Indonesian suffixes like -nya, -kan, -in (e.g. "playlistnya", "putarin")
                    import re
                    is_music_request = False
                    for kw in music_keywords:
                        if re.search(rf'\b{re.escape(kw)}', raw_user_input.lower()):
                            is_music_request = True
                            break
                    music_tool = types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(
                                name="play_music",
                                description="Plays a song in the voice channel. Use this when the user asks to play music.",
                                parameters=types.Schema(
                                    type="OBJECT",
                                    properties={
                                        "query": types.Schema(
                                            type="STRING",
                                            description="The song title or artist to play."
                                        )
                                    },
                                    required=["query"]
                                )
                            ),
                            types.FunctionDeclaration(
                                name="control_music",
                                description="Control music playback (skip, stop, pause, resume, etc).",
                                parameters=types.Schema(
                                    type="OBJECT",
                                    properties={
                                        "action": types.Schema(
                                            type="STRING",
                                            description="The action to perform: skip, stop, pause, resume, queue, list_history, toggle_autoplay.",
                                            enum=["skip", "stop", "pause", "resume", "queue", "list_history", "toggle_autoplay"]
                                        )
                                    },
                                    required=["action"]
                                )
                            ),
                            types.FunctionDeclaration(
                                name="set_volume",
                                description="Set the music volume (0-100).",
                                parameters=types.Schema(
                                    type="OBJECT",
                                    properties={
                                        "level": types.Schema(
                                            type="INTEGER",
                                            description="Volume level from 0 to 100."
                                        )
                                    },
                                    required=["level"]
                                )
                            ),
                            types.FunctionDeclaration(
                                name="manage_queue",
                                description="Manage the music queue (shuffle, loop, remove).",
                                parameters=types.Schema(
                                    type="OBJECT",
                                    properties={
                                        "action": types.Schema(
                                            type="STRING",
                                            description="Action: shuffle, loop, remove.",
                                            enum=["shuffle", "loop", "remove"]
                                        ),
                                        "mode": types.Schema(
                                            type="STRING",
                                            description="For loop: 'track', 'queue', 'off'.",
                                            nullable=True
                                        ),
                                        "query": types.Schema(
                                            type="STRING",
                                            description="For remove: Index, Title, or 'last'.",
                                            nullable=True
                                        )
                                    },
                                    required=["action"]
                                )
                            ),
                            types.FunctionDeclaration(
                                name="audio_filter",
                                description="Apply audio filters.",
                                parameters=types.Schema(
                                    type="OBJECT",
                                    properties={
                                        "filter_name": types.Schema(
                                            type="STRING",
                                            description="Filter: bassboost, nightcore, vaporwave, speed, reset.",
                                            enum=["bassboost", "nightcore", "vaporwave", "speed", "reset"]
                                        ),
                                        "value": types.Schema(
                                            type="STRING", 
                                            description="Optional value (e.g. speed 1.5, bassboost 10).",
                                            nullable=True
                                        )
                                    },
                                    required=["filter_name"]
                                )
                            ),
                            types.FunctionDeclaration(
                                name="generate_playlist",
                                description="Generate an AI-powered playlist based on a vibe, genre, or mood. Use this when the user wants multiple song recommendations or a playlist for a specific vibe/genre/mood.",
                                parameters=types.Schema(
                                    type="OBJECT",
                                    properties={
                                        "vibe": types.Schema(
                                            type="STRING",
                                            description="The vibe, genre, or mood for the playlist (e.g. lofi, rock, galau, semangat, jazz, chill, sad, workout)."
                                        ),
                                        "count": types.Schema(
                                            type="INTEGER",
                                            description="Number of songs to generate (1-25). Default 5 if not specified."
                                        )
                                    },
                                    required=["vibe"]
                                )
                            )
                        ]
                    )

                    grounding_tool = types.Tool(
                        google_search=types.GoogleSearch()
                    )

                    if is_music_request:
                        print(f"DEBUG: Music intent detected for: '{prompt_text}'. Using music tools.")
                        tools_list = [music_tool]
                    else:
                        print(f"DEBUG: No music intent detected. Using grounding tool.")
                        tools_list = [grounding_tool]

                    self.key_manager.reset_failure_checks()
                    response = None
                    
                    while True:
                        client = self.key_manager.get_client()
                        try:
                            # TOKEN MANAGEMENT: Check and prune if necessary (900k limit)
                            try:
                                token_count_resp = client.models.count_tokens(
                                    model="gemini-2.5-flash", 
                                    contents=self.histories[history_id]
                                )
                                total_tokens = token_count_resp.total_tokens
                                if total_tokens >= 900000:
                                    print(f"DEBUG: Token threshold reached ({total_tokens}). Pruning 5% of history...")
                                    prune_count = max(1, int(len(self.histories[history_id]) * 0.05))
                                    self.histories[history_id] = self.histories[history_id][prune_count:]
                                    # Ensure it starts with user
                                    while self.histories[history_id] and self.histories[history_id][0].role != 'user':
                                        self.histories[history_id].pop(0)
                                    print(f"DEBUG: Pruning complete. New items: {len(self.histories[history_id])}")
                            except Exception as te:
                                print(f"DEBUG: Token count/pruning failed (skipping): {te}")

                            response = client.models.generate_content(
                                model="gemini-2.5-flash", 
                                contents=self.histories[history_id],
                                config=types.GenerateContentConfig(
                                    system_instruction=system_instr,
                                    temperature=0.7,
                                    tools=tools_list
                                )
                            )
                            break # Success!
                        except errors.APIError as e:
                            # 429 is Rate Limit Reached
                            if e.code == 429:
                                print(f"DEBUG: Key {self.key_manager.current_index} rate limited. Rotating...")
                                if self.key_manager.rotate():
                                    continue # Try again with next key
                                else:
                                    return await message.reply("❌ Semua API Key MeLagu sudah mencapai batas (rate limit). Coba lagi nanti ya! 🙏")
                            else:
                                raise e # Re-raise other API errors
                    # 5. Handle Response Loop (Text or Function Call)
                    while True:
                        if not response.candidates or not response.candidates[0].content.parts:
                            break
                        
                        function_called = False
                        
                        # Store ORIGINAL parts for history
                        original_parts = list(response.candidates[0].content.parts)
                        
                        # Execute functions and collect responses
                        function_responses = []
                        
                        for part in original_parts:
                            if part.text:
                                # Resolve :name: emojis in response text
                                response_text = part.text
                                if message.guild:
                                    import re
                                    def replace_emoji(match):
                                        emoji_name = match.group(1)
                                        # Search GLOBAL bot cache instead of just the current guild
                                        found = discord.utils.get(self.bot.emojis, name=emoji_name)
                                        if found:
                                            return str(found)
                                        return match.group(0) # Keep as is if not found
                                    
                                    response_text = re.sub(r':(\w+):', replace_emoji, response_text)

                                # Resolve @Mentions in response text
                                if message.guild:
                                    def replace_mention(match):
                                        identifier = match.group(1)
                                        # get_member_named handles "Name#Discrim", "Name", or "ID"
                                        # But for handles, we specifically want to search our member list
                                        found = message.guild.get_member_named(identifier)
                                        
                                        if not found:
                                            # Fallback: manual search in case get_member_named misses something
                                            target = identifier.lower()
                                            found = discord.utils.find(lambda m: m.name.lower() == target or m.display_name.lower() == target, message.guild.members)
                                        
                                        if found:
                                            return found.mention
                                        return match.group(0)
                                    
                                    # This regex matches @ followed by letters, numbers, dots, underscores, or hyphens
                                    response_text = re.sub(r'@([\w\.\-]+)', replace_mention, response_text)
                                
                                await send_split_message(message, response_text)
                            
                            if part.function_call:
                                function_called = True
                                func_name = part.function_call.name
                                args = part.function_call.args
                                print(f"DEBUG: Function Call Triggered: {func_name} with {args}")
                                
                                result_data = {"status": "error", "message": "Unknown error"}
                                
                                try:
                                    # Check Voice State (Common check)
                                    if func_name in ["play_music", "control_music", "set_volume", "manage_queue", "audio_filter", "generate_playlist"]:
                                        if not message.author.voice:
                                            result_data = {"status": "error", "message": "User not in voice channel."}
                                        else:
                                            ctx = await self.bot.get_context(message)
                                            music_cog = self.bot.get_cog("Music")
                                            controls_cog = self.bot.get_cog("Controls")
                                            filters_cog = self.bot.get_cog("Filters")
                                            
                                            if not music_cog:
                                                result_data = {"status": "error", "message": "Music module not loaded."}
                                            else:
                                                # === EXECUTE FUNCTION ===
                                                if func_name == "play_music":
                                                    query = args["query"]
                                                    await music_cog.play(ctx, search=query)
                                                    result_data = {"status": "success", "message": f"Queued/Played: {query}"}

                                                elif func_name == "control_music":
                                                    action = args["action"]
                                                    if action == "skip":
                                                        await controls_cog.skip(ctx)
                                                        result_data = {"status": "success", "message": "Skipped track."}
                                                    elif action == "stop":
                                                        await music_cog.cleanup(ctx.guild)
                                                        result_data = {"status": "success", "message": "Stopped playback and disconnected."}
                                                    elif action == "pause":
                                                        await music_cog.pause(ctx)
                                                        result_data = {"status": "success", "message": "Paused."}
                                                    elif action == "resume":
                                                        if hasattr(music_cog, 'resume'):
                                                            await music_cog.resume(ctx)
                                                        elif ctx.voice_client and ctx.voice_client.is_paused():
                                                            ctx.voice_client.resume()
                                                        result_data = {"status": "success", "message": "Resumed."}
                                                    elif action == "queue":
                                                        await music_cog.queue_info(ctx)
                                                        result_data = {"status": "success", "message": "Displayed queue."}
                                                    elif action == "list_history":
                                                        await music_cog.list_history(ctx)
                                                        result_data = {"status": "success", "message": "Displayed history."}
                                                    elif action == "toggle_autoplay":
                                                        await music_cog.autoplay(ctx)
                                                        result_data = {"status": "success", "message": "Toggled autoplay."}

                                                elif func_name == "set_volume":
                                                    level = int(args["level"])
                                                    await controls_cog.volume(ctx, vol=level)
                                                    result_data = {"status": "success", "message": f"Volume set to {level}%."}

                                                elif func_name == "manage_queue":
                                                    action = args["action"]
                                                    if action == "shuffle":
                                                        await controls_cog.shuffle(ctx)
                                                        result_data = {"status": "success", "message": "Shuffled queue."}
                                                    elif action == "loop":
                                                        mode = args.get("mode")
                                                        await controls_cog.loop(ctx, mode=mode)
                                                        result_data = {"status": "success", "message": f"Loop mode set to {mode}."}
                                                    elif action == "remove":
                                                        query = args.get("query")
                                                        await music_cog.remove(ctx, query=query)
                                                        result_data = {"status": "success", "message": f"Removed {query} from queue."}

                                                elif func_name == "audio_filter":
                                                    filter_name = args["filter_name"]
                                                    val = args.get("value")
                                                    if filters_cog:
                                                        if filter_name == "bassboost": await filters_cog.bassboost(ctx, value=val)
                                                        elif filter_name == "nightcore": await filters_cog.nightcore(ctx)
                                                        elif filter_name == "vaporwave": await filters_cog.vaporwave(ctx)
                                                        elif filter_name == "speed": await filters_cog.speed(ctx, speed=val)
                                                        elif filter_name == "reset": await filters_cog.reset(ctx)
                                                        result_data = {"status": "success", "message": f"Applied filter: {filter_name}"}
                                                    else:
                                                        result_data = {"status": "error", "message": "Filters module missing."}

                                                elif func_name == "generate_playlist":
                                                    vibe = args["vibe"]
                                                    count = int(args.get("count", 5))
                                                    await music_cog.playlist(ctx, vibe=vibe, count=count)
                                                    result_data = {"status": "success", "message": f"Generated AI playlist with vibe '{vibe}' ({count} songs)."}

                                except Exception as e:
                                    print(f"Error executing tool {func_name}: {e}")
                                    result_data = {"status": "error", "message": str(e)}

                                # Create response part
                                response_part = types.Part.from_function_response(
                                    name=func_name,
                                    response=result_data
                                )
                                function_responses.append(response_part)

                        # Append terms to history
                        self.histories[history_id].append(types.Content(role="model", parts=original_parts))

                        if function_called:
                            # Append responses
                            self.histories[history_id].append(types.Content(role="function", parts=function_responses))
                            
                            print("DEBUG: Sending function results back to Gemini...")
                            while True:
                                client = self.key_manager.get_client()
                                try:
                                    response = client.models.generate_content(
                                        model="gemini-2.5-flash",
                                        contents=self.histories[history_id],
                                        config=types.GenerateContentConfig(
                                            system_instruction=system_instr,
                                            temperature=0.7,
                                            tools=tools_list
                                        )
                                    )
                                    break
                                except errors.APIError as e:
                                    if e.code == 429:
                                        print(f"DEBUG: Key {self.key_manager.current_index} rate limited during tool use. Rotating...")
                                        if self.key_manager.rotate():
                                            continue
                                        else:
                                            return await message.reply("❌ Semua API Key MeLagu sudah mencapai batas (rate limit) saat memproses perintah. 🙏")
                                    else:
                                        raise e
                        else:
                            break

                    # Save history after interactions
                    self.save_history()
                        
                except Exception as e:
                    import traceback
                    print(f"ERROR: Gemini Chat Error: {e}")
                    traceback.print_exc()
                    await send_error_log(self.bot, e, message=message)
                    await message.reply("🤯 Wait, I'm having trouble thinking right now. Someone please call <@1145666047383437453>")


    @commands.command(name="forget")
    async def reset_memory(self, ctx):
        """Resets your private chat memory for this server."""
        user_id = str(ctx.author.id)
        guild_id = str(ctx.guild.id) if ctx.guild else "dm"
        
        # Maintenance Isolation Check - GLOBAL across servers
        is_maintenance, _ = get_maintenance_state()
        if is_maintenance:
            history_id = f"test_{user_id}"
            location_name = "Maintenance Test"
        else:
            history_id = f"{guild_id}_{user_id}"
            location_name = "Private"

        if history_id in self.histories:
            del self.histories[history_id]
            self.save_history()
            await ctx.send(f"🧠 **{location_name} Memory Wiped!** I've forgotten our conversation in this server.")
        else:
            await ctx.send(f"✨ My {location_name.lower()} memory of you in this server was already empty.")


    @commands.command(name="private")
    async def set_private(self, ctx):
        """Switches to private history mode."""
        user_id = str(ctx.author.id)
        if user_id not in self.user_settings:
            self.user_settings[user_id] = {"persona": "default", "chat_mode": "private"}
        else:
            self.user_settings[user_id]["chat_mode"] = "private"
        
        self.save_user_settings()
        await ctx.send("🔒 **Private Mode Activated**. Your chat history is now personal and hidden from others.")

    @commands.command(name="public")
    async def set_public(self, ctx):
        """Switches to shared (public) history mode."""
        user_id = str(ctx.author.id)
        if user_id not in self.user_settings:
            self.user_settings[user_id] = {"persona": "default", "chat_mode": "public"}
        else:
            self.user_settings[user_id]["chat_mode"] = "public"
        
        self.save_user_settings()
        await ctx.send("🌐 **Public Mode Activated**. Your messages will contribute to the shared chat history.")

async def setup(bot):
    await bot.add_cog(Chat(bot))
