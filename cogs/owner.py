import discord
import os
import sys
from discord.ext import commands
from utils import create_embed, create_error_embed, is_owner, get_maintenance_state, set_maintenance_state, send_split_message

class Owner(commands.Cog, name="Owner Commands"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='autoleave')
    async def autoleave(self, ctx):
        """Toggle the auto-leave timer (Owner only)."""
        # User ID check: 1145666047383437453
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        music_cog = self.bot.get_cog('Music')
        if not music_cog:
            return await ctx.send(embed=create_error_embed("Music system is not active."))

        player = music_cog.get_player(ctx)
        player.timer_enabled = not player.timer_enabled
        status = "Enabled" if player.timer_enabled else "Disabled"
        await ctx.send(embed=create_embed("Auto-Leave", f"Auto-leave timer has been **{status}**."))


    @commands.command(name='backup')
    async def backup(self, ctx):
        """Manually triggers a full backup (Owner only)."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        backup_cog = self.bot.get_cog('Backup')
        if not backup_cog:
            return await ctx.send(embed=create_error_embed("Backup system is not active."))

        await ctx.send("⏳ Creating manual backup...")
        await backup_cog.perform_backup(ctx, reason="Manual Backup requested by Owner")

    @commands.command(name='restart')
    async def restart(self, ctx):
        """Restart the bot program (Owner only)."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        await ctx.send(embed=create_embed("System", "🔄 Restarting bot..."))
        
        # Shutdown the bot briefly
        await self.bot.close()
        
        # This will restart the current script
        os.execv(sys.executable, ['python'] + sys.argv)

    @commands.command(name='forgetshared', aliases=['fs'])
    async def reset_shared_memory(self, ctx):
        """Resets the shared (global) chat memory (Owner only)."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        chat_cog = self.bot.get_cog('Chat')
        if not chat_cog:
            return await ctx.send(embed=create_error_embed("Chat system is not active."))

        target_id = f"shared_{ctx.guild.id}" if ctx.guild else "shared_dm"
        location_name = "Global"
        
        # Maintenance Isolation Check - GLOBAL across servers
        is_maintenance, _ = get_maintenance_state()
        if is_maintenance:
            target_id = f"test_{ctx.author.id}"
            location_name = "Maintenance Test"
        # SMART LOGIC: If in the special private channel, target its specific history
        elif ctx.channel.id == 1429779152919068733:
            target_id = f"channel_{ctx.channel.id}"
            location_name = "Private Channel"

        if target_id in chat_cog.histories:
            del chat_cog.histories[target_id]
            chat_cog.save_history()
            await ctx.send(f"🧠 **{location_name} Memory Wiped!** Context has been reset for this server.")
        else:
            await ctx.send(f"✨ The {location_name.lower()} memory for this server was already empty.")

    @commands.command(name='maintenance', aliases=['mt'])
    async def maintenance(self, ctx, status: str = None, *, reason: str = None):
        """Toggle maintenance mode (Owner only)."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        if status is None:
            current, current_reason = get_maintenance_state()
            status_str = "ON" if current else "OFF"
            reason_str = f" (Reason: {current_reason})" if current and current_reason else ""
            return await ctx.send(embed=create_embed("System", f"Maintenance Mode is currently **{status_str}**{reason_str}. Use `al!mt on [reason]` or `al!mt off` to change it."))

        if status.lower() == 'on':
            set_maintenance_state(True, reason)
            reason_msg = f"\nReason: {reason}" if reason else ""
            await ctx.send(embed=create_embed("System", f"🚧 **Maintenance Mode ENABLED.** All commands are restricted to Owners only.{reason_msg}", color=0xf1c40f))
        elif status.lower() == 'off':
            set_maintenance_state(False)
            
            # AUTOMATIC CLEANUP: Delete all test histories when Maintenance ends
            chat_cog = self.bot.get_cog('Chat')
            if chat_cog:
                test_keys = [k for k in chat_cog.histories.keys() if k.startswith("test_")]
                if test_keys:
                    for k in test_keys:
                        del chat_cog.histories[k]
                    chat_cog.save_history()
                    print(f"DEBUG: Cleared {len(test_keys)} test session histories.")

            await ctx.send(embed=create_embed("System", "✅ **Maintenance Mode DISABLED.** Bot is back to normal.", color=0x2ecc71))
        else:
            await ctx.send(embed=create_error_embed("Invalid status. Use `al!mt on` or `al!mt off`."))

    @commands.group(name='globalpersona', aliases=['gp'], invoke_without_command=True)
    async def global_persona(self, ctx):
        """Manage the global (server-wide) persona (Owner only)."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        chat_cog = self.bot.get_cog('Chat')
        if not chat_cog:
            return await ctx.send(embed=create_error_embed("Chat system is not active."))

        guild_id = str(ctx.guild.id) if ctx.guild else None
        if not guild_id:
            return await ctx.send("This command can only be used in a server.")

        settings = chat_cog.global_settings.get(guild_id, {})
        current = settings.get("persona", "default")
        await ctx.send(f"Current Global Persona for this server: **{current}**\nCommands: `al!gp list`, `al!gp set <name>`, `al!gp reset`")

    @global_persona.command(name="list")
    async def gp_list(self, ctx):
        """List all available personas for global settings."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        chat_cog = self.bot.get_cog('Chat')
        if not chat_cog:
            return await ctx.send(embed=create_error_embed("Chat system is not active."))

        available = [f"`{name}`" for name in chat_cog.personas.keys()]
        keys = ", ".join(available)
        await ctx.send(f"Available Personas: {keys}")

    @global_persona.command(name="set")
    async def gp_set(self, ctx, name: str):
        """Set the global persona for this server."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        chat_cog = self.bot.get_cog('Chat')
        if not chat_cog:
            return await ctx.send(embed=create_error_embed("Chat system is not active."))

        if name not in chat_cog.personas:
             return await ctx.send(f"❌ Persona `{name}` not found.")
        
        guild_id = str(ctx.guild.id) if ctx.guild else None
        if not guild_id:
            return await ctx.send("This command can only be used in a server.")

        if guild_id not in chat_cog.global_settings:
            chat_cog.global_settings[guild_id] = {}
            
        chat_cog.global_settings[guild_id]["persona"] = name
        chat_cog.save_global_settings()
        await ctx.send(f"Global Persona for this server set to: **{name}**")

    @global_persona.command(name="reset")
    async def gp_reset(self, ctx):
        """Reset the global persona for this server to default."""
        if not is_owner(ctx.author):
             return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        chat_cog = self.bot.get_cog('Chat')
        if not chat_cog:
            return await ctx.send(embed=create_error_embed("Chat system is not active."))

        guild_id = str(ctx.guild.id) if ctx.guild else None
        if not guild_id:
            return await ctx.send("This command can only be used in a server.")

        if guild_id in chat_cog.global_settings:
            chat_cog.global_settings[guild_id]["persona"] = "default"
            chat_cog.save_global_settings()
            await ctx.send("Global Persona for this server has been reset to **default**.")
        else:
            await ctx.send("Global Persona was already set to **default**.")

    @commands.command(name='log', aliases=['logs', 'terminal'])
    async def log_command(self, ctx, lines: int = 30):
        """View recent terminal logs (Owner only)."""
        if not is_owner(ctx.author):
            return await ctx.send(embed=create_error_embed("Only owner can use this command."))

        if not hasattr(self.bot, 'stdout_wrapper'):
            return await ctx.send(embed=create_error_embed("Log system is not initialized."))

        # Get logs from stdout and stderr
        out_logs = self.bot.stdout_wrapper.get_logs(lines)
        err_logs = self.bot.stderr_wrapper.get_logs(lines)
        
        log_parts = []
        
        # ANSI Escape Codes for coloring
        BLUE_BOLD = "\u001b[1;34m"
        RED_BOLD = "\u001b[1;31m"
        WHITE_BOLD = "\u001b[1;37m"
        RESET = "\u001b[0m"
        GRAY = "\u001b[0;30m"

        if out_logs:
            header = f"{BLUE_BOLD}┏━━━━━━━━━ STDOUT ━━━━━━━━━┓{RESET}"
            footer = f"{BLUE_BOLD}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━┛{RESET}"
            log_parts.append(header)
            log_parts.extend(out_logs)
            log_parts.append(footer)
        
        if err_logs:
            if log_parts: log_parts.append("") # Spacer
            header = f"{RED_BOLD}┏━━━━━━━━━ STDERR ━━━━━━━━━┓{RESET}"
            footer = f"{RED_BOLD}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━┛{RESET}"
            log_parts.append(header)
            log_parts.extend(err_logs)
            log_parts.append(footer)

        if not log_parts:
            return await ctx.send(embed=create_embed("Terminal Logs", "No activity recorded yet."))

        # Join with newlines
        log_text = "\n".join(log_parts)
        
        # Format the log text for aesthetic display
        formatted_logs = f"```ansi\n{log_text}\n```"
        
        embed = discord.Embed(
            title="📂 System Terminal Activity",
            description=f"Recalling the last `{lines}` lines of activity from the session.",
            color=0x2f3136, # Dark mode aesthetic
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name="MeLagu Console", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

        await ctx.send(embed=embed)
        await send_split_message(ctx, formatted_logs)



async def setup(bot):
    await bot.add_cog(Owner(bot))
