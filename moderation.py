import discord
from discord.ext import commands, tasks
from typing import Optional, Union
import time

from database import (
    add_warn, get_warns, delete_warn,
    add_temp_ban, remove_temp_ban, get_expired_temp_bans,
    add_temp_lock, remove_temp_lock, get_expired_temp_locks
)
from time_parser import parse_time

def has_mod_permissions():
    async def predicate(ctx: commands.Context):
        if ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.administrator:
            return True
        raise commands.MissingPermissions(["manage_messages"])
    return commands.check(predicate)

def has_ban_permissions():
    async def predicate(ctx: commands.Context):
        if ctx.author.guild_permissions.ban_members or ctx.author.guild_permissions.administrator:
            return True
        raise commands.MissingPermissions(["ban_members"])
    return commands.check(predicate)

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_expired.start()

    def cog_unload(self):
        self.check_expired.cancel()

    @tasks.loop(minutes=1)
    async def check_expired(self):
        # Tempbans
        for entry in await get_expired_temp_bans():
            guild = self.bot.get_guild(entry["guild_id"])
            if not guild:
                continue
            try:
                user = await self.bot.fetch_user(entry["user_id"])
                await guild.unban(user, reason="Tempban expirado automáticamente")
            except Exception:
                pass
            await remove_temp_ban(entry["guild_id"], entry["user_id"])

        # Temp locks
        for entry in await get_expired_temp_locks():
            guild = self.bot.get_guild(entry["guild_id"])
            if not guild:
                continue
            channel = guild.get_channel(entry["channel_id"])
            if not channel or not isinstance(channel, discord.TextChannel):
                await remove_temp_lock(entry["guild_id"], entry["channel_id"])
                continue
            try:
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = None
                await channel.set_permissions(
                    guild.default_role,
                    overwrite=overwrite,
                    reason="Unlock automático por tiempo"
                )
            except Exception:
                pass
            await remove_temp_lock(entry["guild_id"], entry["channel_id"])

    @check_expired.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ───────────────────── LOCK / UNLOCK ─────────────────────
    @commands.command(name="lock")
    @has_mod_permissions()
    @commands.guild_only()
    async def lock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, *, time_str: Optional[str] = None):
        """Bloquea un canal. Uso: ?lock [#canal] [tiempo]"""
        channel = channel or ctx.channel

        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False

        await channel.set_permissions(
            ctx.guild.default_role,
            overwrite=overwrite,
            reason=f"Lock por {ctx.author} ({ctx.author.id})"
        )

        embed = discord.Embed(
            title="Canal bloqueado",
            description=f"{channel.mention} ha sido bloqueado.",
            color=0xED4245
        )

        if time_str:
            delta = parse_time(time_str)
            if not delta:
                return await ctx.send("Formato de tiempo inválido.\nEjemplos válidos: `1h`, `30m`, `2d`, `1h30m`, `1w`")

            unlock_at = time.time() + delta.total_seconds()
            await add_temp_lock(ctx.guild.id, channel.id, unlock_at)

            embed.description += f"\nSe desbloqueará automáticamente en **{time_str}**."
        
        await ctx.send(embed=embed)

    @commands.command(name="unlock")
    @has_mod_permissions()
    @commands.guild_only()
    async def unlock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Desbloquea un canal. Uso: ?unlock [#canal]"""
        channel = channel or ctx.channel

        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None

        await channel.set_permissions(
            ctx.guild.default_role,
            overwrite=overwrite,
            reason=f"Unlock por {ctx.author} ({ctx.author.id})"
        )
        await remove_temp_lock(ctx.guild.id, channel.id)

        embed = discord.Embed(
            title="Canal desbloqueado",
            description=f"{channel.mention} ha sido desbloqueado.",
            color=0x57F287
        )
        await ctx.send(embed=embed)

    # ───────────────────── WARNS ─────────────────────
    @commands.command(name="warn")
    @has_mod_permissions()
    @commands.guild_only()
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
        """Advierte a un usuario. Uso: ?warn @usuario [motivo]"""
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("No puedes advertir a alguien con un rol igual o superior al tuyo.")

        if member.bot:
            return await ctx.send("No puedes advertir a un bot.")

        warn_id = await add_warn(ctx.guild.id, member.id, ctx.author.id, reason)

        embed = discord.Embed(title="Usuario advertido", color=0xFEE75C, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Moderador", value=ctx.author.mention, inline=True)
        embed.add_field(name="ID de Warn", value=f"`#{warn_id}`", inline=True)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)

        try:
            await member.send(
                f"Has sido advertido en **{ctx.guild.name}**.\n"
                f"**Motivo:** {reason}\n**ID de la advertencia:** `#{warn_id}`"
            )
        except discord.Forbidden:
            pass

    @commands.command(name="warns")
    @has_mod_permissions()
    @commands.guild_only()
    async def warns(self, ctx: commands.Context, member: discord.Member):
        """Muestra las advertencias de un usuario. Uso: ?warns @usuario"""
        warns_list = await get_warns(ctx.guild.id, member.id)

        if not warns_list:
            return await ctx.send(f"{member.mention} no tiene advertencias registradas.")

        embed = discord.Embed(
            title=f"Advertencias de {member}",
            color=0xFEE75C,
            timestamp=discord.utils.utcnow()
        )

        for w in warns_list[:15]:
            mod = ctx.guild.get_member(w["moderator_id"])
            mod_str = mod.mention if mod else f"`{w['moderator_id']}`"
            embed.add_field(
                name=f"#{w['id']}",
                value=f"**Motivo:** {w['reason']}\n**Moderador:** {mod_str}",
                inline=False
            )

        embed.set_footer(text=f"Total: {len(warns_list)} advertencia(s)")
        await ctx.send(embed=embed)

    @commands.command(name="delwarn")
    @has_mod_permissions()
    @commands.guild_only()
    async def delwarn(self, ctx: commands.Context, member: discord.Member, warn_id: int):
        """Elimina una advertencia. Uso: ?delwarn @usuario <id>"""
        success = await delete_warn(ctx.guild.id, member.id, warn_id)

        if success:
            await ctx.send(f"Advertencia `#{warn_id}` de {member.mention} eliminada correctamente.")
        else:
            await ctx.send(f"No se encontró la advertencia `#{warn_id}` para {member.mention}.")

    # ───────────────────── BAN / UNBAN / TEMPBAN ─────────────────────
    @commands.command(name="ban")
    @has_ban_permissions()
    @commands.guild_only()
    async def ban(self, ctx: commands.Context, target: Union[discord.Member, discord.User, str], *, reason: str = "Sin motivo"):
        """Banea permanentemente. Uso: ?ban @usuario/ID [motivo]"""
        user = await self._resolve_user(ctx, target)
        if user is None:
            return

        if isinstance(user, discord.Member):
            if user.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
                return await ctx.send("No puedes banear a alguien con un rol igual o superior al tuyo.")
            if user.id == ctx.guild.owner_id:
                return await ctx.send("No puedes banear al dueño del servidor.")

        try:
            await ctx.guild.ban(user, reason=f"{ctx.author} ({ctx.author.id}) | {reason}", delete_message_days=0)
        except discord.Forbidden:
            return await ctx.send("No tengo permisos suficientes para banear a ese usuario.")
        except discord.HTTPException as e:
            return await ctx.send(f"Error al banear: {e}")

        embed = discord.Embed(title="Usuario baneado", color=0xED4245, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)")
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="unban")
    @has_ban_permissions()
    @commands.guild_only()
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str = "Sin motivo"):
        """Desbanea por ID. Uso: ?unban <user_id> [motivo]"""
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=f"{ctx.author} ({ctx.author.id}) | {reason}")
            await remove_temp_ban(ctx.guild.id, user_id)
        except discord.NotFound:
            return await ctx.send("Ese usuario no está baneado o el ID es inválido.")
        except discord.Forbidden:
            return await ctx.send("No tengo permisos para desbanear.")
        except Exception as e:
            return await ctx.send(f"Error: {e}")

        embed = discord.Embed(title="Usuario desbaneado", color=0x57F287, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)")
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="tempban")
    @has_ban_permissions()
    @commands.guild_only()
    async def tempban(self, ctx: commands.Context, target: Union[discord.Member, discord.User, str], time_str: str, *, reason: str = "Sin motivo"):
        """Baneo temporal. Uso: ?tempban @usuario/ID <tiempo> [motivo]"""
        user = await self._resolve_user(ctx, target)
        if user is None:
            return

        delta = parse_time(time_str)
        if not delta:
            return await ctx.send("Formato de tiempo inválido.\nEjemplos: `1h`, `30m`, `2d`, `1w`, `1h30m`")

        if isinstance(user, discord.Member):
            if user.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
                return await ctx.send("No puedes banear a alguien con un rol igual o superior al tuyo.")
            if user.id == ctx.guild.owner_id:
                return await ctx.send("No puedes banear al dueño del servidor.")

        try:
            await ctx.guild.ban(
                user,
                reason=f"{ctx.author} ({ctx.author.id}) | Tempban {time_str} | {reason}",
                delete_message_days=0
            )
        except discord.Forbidden:
            return await ctx.send("No tengo permisos suficientes para banear a ese usuario.")

        unban_at = time.time() + delta.total_seconds()
        await add_temp_ban(ctx.guild.id, user.id, unban_at, reason)

        embed = discord.Embed(title="Usuario baneado temporalmente", color=0xED4245, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)")
        embed.add_field(name="Duración", value=time_str)
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)

    async def _resolve_user(self, ctx: commands.Context, target) -> Optional[Union[discord.Member, discord.User]]:
        if isinstance(target, (discord.Member, discord.User)):
            return target
        try:
            uid = int(str(target).strip())
            return await self.bot.fetch_user(uid)
        except (ValueError, discord.NotFound, discord.HTTPException):
            await ctx.send("Usuario no encontrado. Usa una mención válida o un ID numérico.")
            return None

    # ───────────────────── ERROR HANDLER (estilo Dyno) ─────────────────────
    @lock.error
    @unlock.error
    @warn.error
    @warns.error
    @delwarn.error
    @ban.error
    @unban.error
    @tempban.error
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingRequiredArgument):
            cmd = ctx.command
            await ctx.send(
                f"**Faltan argumentos.**\n"
                f"Uso correcto: `?{cmd.name} {cmd.signature}`\n"
                f"Ejemplo: `?{cmd.name} @usuario motivo aquí`"
            )
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Argumento inválido. Revisa el formato del comando.")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("No tienes los permisos necesarios para ejecutar este comando.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("No tengo los permisos necesarios en este servidor.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("Usuario no encontrado.")
        elif isinstance(error, commands.ChannelNotFound):
            await ctx.send("Canal no encontrado.")
        else:
            print(f"[ERROR] {ctx.command}: {type(error).__name__}: {error}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
