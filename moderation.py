import discord
from discord.ext import commands, tasks
from typing import Optional, Union, Dict
import time
from datetime import datetime, timezone

from database import (
    add_warn, get_warns, delete_warn,
    add_temp_ban, remove_temp_ban, get_expired_temp_bans,
    add_temp_lock, remove_temp_lock, get_expired_temp_locks,
    set_log_channel, get_log_channel
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

def has_kick_permissions():
    async def predicate(ctx: commands.Context):
        if ctx.author.guild_permissions.kick_members or ctx.author.guild_permissions.administrator:
            return True
        raise commands.MissingPermissions(["kick_members"])
    return commands.check(predicate)

def has_moderate_members():
    async def predicate(ctx: commands.Context):
        if ctx.author.guild_permissions.moderate_members or ctx.author.guild_permissions.administrator:
            return True
        raise commands.MissingPermissions(["moderate_members"])
    return commands.check(predicate)

def has_manage_roles():
    async def predicate(ctx: commands.Context):
        if ctx.author.guild_permissions.manage_roles or ctx.author.guild_permissions.administrator:
            return True
        raise commands.MissingPermissions(["manage_roles"])
    return commands.check(predicate)

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.snipe_cache: Dict[int, Dict[int, discord.Message]] = {}  # guild_id -> {channel_id: message}
        self.check_expired.start()

    def cog_unload(self):
        self.check_expired.cancel()

    # ───────────────────── Helper de logs ─────────────────────
    async def send_mod_log(self, guild: discord.Guild, embed: discord.Embed):
        channel_id = await get_log_channel(guild.id)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    # ───────────────────── Task de expiración ─────────────────────
    @tasks.loop(minutes=1)
    async def check_expired(self):
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
                await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="Unlock automático")
            except Exception:
                pass
            await remove_temp_lock(entry["guild_id"], entry["channel_id"])

    @check_expired.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ───────────────────── SNIPE (listener) ─────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.guild.id not in self.snipe_cache:
            self.snipe_cache[message.guild.id] = {}
        self.snipe_cache[message.guild.id][message.channel.id] = message

    # ───────────────────── LOCK / UNLOCK ─────────────────────
    @commands.command(name="lock")
    @has_mod_permissions()
    @commands.guild_only()
    async def lock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, *, time_str: Optional[str] = None):
        """Bloquea un canal. Uso: ?lock [#canal] [tiempo]"""
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Lock por {ctx.author}")

        embed = discord.Embed(title="Canal bloqueado", description=f"{channel.mention} ha sido bloqueado.", color=0xED4245)
        if time_str:
            delta = parse_time(time_str)
            if not delta:
                return await ctx.send("Formato de tiempo inválido. Ejemplos: `1h`, `30m`, `2d`, `1h30m`")
            await add_temp_lock(ctx.guild.id, channel.id, time.time() + delta.total_seconds())
            embed.description += f"\nSe desbloqueará en **{time_str}**."
        await ctx.send(embed=embed)

    @commands.command(name="unlock")
    @has_mod_permissions()
    @commands.guild_only()
    async def unlock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Desbloquea un canal. Uso: ?unlock [#canal]"""
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Unlock por {ctx.author}")
        await remove_temp_lock(ctx.guild.id, channel.id)
        embed = discord.Embed(title="Canal desbloqueado", description=f"{channel.mention} ha sido desbloqueado.", color=0x57F287)
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

        log_embed = embed.copy()
        log_embed.title = "Warn"
        await self.send_mod_log(ctx.guild, log_embed)

        try:
            await member.send(f"Has sido advertido en **{ctx.guild.name}**.\n**Motivo:** {reason}\n**ID:** `#{warn_id}`")
        except discord.Forbidden:
            pass

    @commands.command(name="warns")
    @has_mod_permissions()
    @commands.guild_only()
    async def warns(self, ctx: commands.Context, member: discord.Member):
        """Muestra las advertencias. Uso: ?warns @usuario"""
        warns_list = await get_warns(ctx.guild.id, member.id)
        if not warns_list:
            return await ctx.send(f"{member.mention} no tiene advertencias.")

        embed = discord.Embed(title=f"Advertencias de {member}", color=0xFEE75C, timestamp=discord.utils.utcnow())
        for w in warns_list[:15]:
            mod = ctx.guild.get_member(w["moderator_id"])
            mod_str = mod.mention if mod else f"`{w['moderator_id']}`"
            embed.add_field(name=f"#{w['id']}", value=f"**Motivo:** {w['reason']}\n**Mod:** {mod_str}", inline=False)
        embed.set_footer(text=f"Total: {len(warns_list)}")
        await ctx.send(embed=embed)

    @commands.command(name="delwarn")
    @has_mod_permissions()
    @commands.guild_only()
    async def delwarn(self, ctx: commands.Context, member: discord.Member, warn_id: int):
        """Elimina una advertencia. Uso: ?delwarn @usuario <id>"""
        success = await delete_warn(ctx.guild.id, member.id, warn_id)
        if success:
            await ctx.send(f"Advertencia `#{warn_id}` de {member.mention} eliminada.")
        else:
            await ctx.send(f"No se encontró la advertencia `#{warn_id}`.")

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
                return await ctx.send("No puedes banear a alguien con un rol igual o superior.")
            if user.id == ctx.guild.owner_id:
                return await ctx.send("No puedes banear al dueño del servidor.")

        try:
            await ctx.guild.ban(user, reason=f"{ctx.author} | {reason}", delete_message_days=0)
        except discord.Forbidden:
            return await ctx.send("No tengo permisos para banear a ese usuario.")

        embed = discord.Embed(title="Usuario baneado", color=0xED4245, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)")
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(name="unban")
    @has_ban_permissions()
    @commands.guild_only()
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str = "Sin motivo"):
        """Desbanea por ID. Uso: ?unban <user_id> [motivo]"""
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=f"{ctx.author} | {reason}")
            await remove_temp_ban(ctx.guild.id, user_id)
        except discord.NotFound:
            return await ctx.send("Ese usuario no está baneado o el ID es inválido.")
        except discord.Forbidden:
            return await ctx.send("No tengo permisos para desbanear.")

        embed = discord.Embed(title="Usuario desbaneado", color=0x57F287, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)")
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

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
            return await ctx.send("Formato de tiempo inválido. Ejemplos: `1h`, `30m`, `2d`, `1w`")

        if isinstance(user, discord.Member):
            if user.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
                return await ctx.send("No puedes banear a alguien con un rol igual o superior.")
            if user.id == ctx.guild.owner_id:
                return await ctx.send("No puedes banear al dueño del servidor.")

        try:
            await ctx.guild.ban(user, reason=f"{ctx.author} | Tempban {time_str} | {reason}", delete_message_days=0)
        except discord.Forbidden:
            return await ctx.send("No tengo permisos para banear a ese usuario.")

        await add_temp_ban(ctx.guild.id, user.id, time.time() + delta.total_seconds(), reason)

        embed = discord.Embed(title="Usuario baneado temporalmente", color=0xED4245, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{user} (`{user.id}`)")
        embed.add_field(name="Duración", value=time_str)
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ───────────────────── KICK ─────────────────────
    @commands.command(name="kick")
    @has_kick_permissions()
    @commands.guild_only()
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
        """Expulsa a un usuario. Uso: ?kick @usuario [motivo]"""
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("No puedes expulsar a alguien con un rol igual o superior al tuyo.")
        if member.id == ctx.guild.owner_id:
            return await ctx.send("No puedes expulsar al dueño del servidor.")
        if member.bot:
            return await ctx.send("No puedes expulsar a un bot con este comando.")

        try:
            await member.kick(reason=f"{ctx.author} | {reason}")
        except discord.Forbidden:
            return await ctx.send("No tengo permisos para expulsar a ese usuario.")

        embed = discord.Embed(title="Usuario expulsado", color=0xED4245, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{member} (`{member.id}`)")
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ───────────────────── MUTE / UNMUTE (Timeout) ─────────────────────
    @commands.command(name="mute")
    @has_moderate_members()
    @commands.guild_only()
    async def mute(self, ctx: commands.Context, member: discord.Member, time_str: Optional[str] = None, *, reason: str = "Sin motivo"):
        """Silencia a un usuario (timeout). Uso: ?mute @usuario [tiempo] [motivo]"""
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("No puedes silenciar a alguien con un rol igual o superior.")
        if member.id == ctx.guild.owner_id:
            return await ctx.send("No puedes silenciar al dueño del servidor.")

        delta = None
        if time_str:
            delta = parse_time(time_str)
            if not delta:
                # Si el primer argumento no es tiempo, lo tratamos como parte del motivo
                reason = f"{time_str} {reason}".strip()
                time_str = None

        until = None
        if delta:
            until = discord.utils.utcnow() + delta
            # Discord limita timeout a 28 días
            max_timeout = discord.utils.utcnow() + discord.utils.timedelta(days=28)
            if until > max_timeout:
                until = max_timeout

        try:
            await member.timeout(until, reason=f"{ctx.author} | {reason}")
        except discord.Forbidden:
            return await ctx.send("No tengo permisos para silenciar a ese usuario (necesito Moderate Members).")

        embed = discord.Embed(title="Usuario silenciado", color=0xFEE75C, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{member.mention} (`{member.id}`)")
        embed.add_field(name="Moderador", value=ctx.author.mention)
        if time_str and delta:
            embed.add_field(name="Duración", value=time_str)
        else:
            embed.add_field(name="Duración", value="Indefinido (hasta que se quite)")
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    @commands.command(name="unmute")
    @has_moderate_members()
    @commands.guild_only()
    async def unmute(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
        """Quita el silencio a un usuario. Uso: ?unmute @usuario [motivo]"""
        try:
            await member.timeout(None, reason=f"{ctx.author} | {reason}")
        except discord.Forbidden:
            return await ctx.send("No tengo permisos para quitar el silencio.")

        embed = discord.Embed(title="Usuario desilenciado", color=0x57F287, timestamp=discord.utils.utcnow())
        embed.add_field(name="Usuario", value=f"{member.mention} (`{member.id}`)")
        embed.add_field(name="Moderador", value=ctx.author.mention)
        embed.add_field(name="Motivo", value=reason, inline=False)
        await ctx.send(embed=embed)
        await self.send_mod_log(ctx.guild, embed)

    # ───────────────────── CLEAR / PURGE ─────────────────────
    @commands.command(name="clear", aliases=["purge"])
    @has_mod_permissions()
    @commands.guild_only()
    async def clear(self, ctx: commands.Context, amount: int):
        """Borra mensajes. Uso: ?clear <cantidad> (1-100)"""
        if amount < 1 or amount > 100:
            return await ctx.send("La cantidad debe estar entre **1** y **100**.")

        try:
            deleted = await ctx.channel.purge(limit=amount + 1)  # +1 para incluir el comando
            count = len(deleted) - 1
            msg = await ctx.send(f"Se eliminaron **{count}** mensajes.", delete_after=5)
        except discord.Forbidden:
            await ctx.send("No tengo permisos para borrar mensajes.")
        except Exception as e:
            await ctx.send(f"Error al borrar mensajes: {e}")

    # ───────────────────── SLOWMODE ─────────────────────
    @commands.command(name="slowmode")
    @has_mod_permissions()
    @commands.guild_only()
    async def slowmode(self, ctx: commands.Context, seconds: int):
        """Activa/desactiva el modo lento. Uso: ?slowmode <segundos> (0 para desactivar)"""
        if seconds < 0 or seconds > 21600:
            return await ctx.send("Los segundos deben estar entre **0** y **21600** (6 horas).")

        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await ctx.send(f"Modo lento **desactivado** en {ctx.channel.mention}.")
            else:
                await ctx.send(f"Modo lento establecido a **{seconds} segundos** en {ctx.channel.mention}.")
        except discord.Forbidden:
            await ctx.send("No tengo permisos para cambiar el modo lento.")

    # ───────────────────── NICK ─────────────────────
    @commands.command(name="nick")
    @has_mod_permissions()
    @commands.guild_only()
    async def nick(self, ctx: commands.Context, member: discord.Member, *, nick: Optional[str] = None):
        """Cambia el apodo de un usuario. Uso: ?nick @usuario [nuevo apodo]"""
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("No puedes cambiar el apodo de alguien con un rol igual o superior.")

        try:
            old_nick = member.display_name
            await member.edit(nick=nick)
            if nick:
                await ctx.send(f"Apodo de {member.mention} cambiado de **{old_nick}** a **{nick}**.")
            else:
                await ctx.send(f"Apodo de {member.mention} restablecido.")
        except discord.Forbidden:
            await ctx.send("No tengo permisos para cambiar el apodo de ese usuario.")

    # ───────────────────── SNIPE ─────────────────────
    @commands.command(name="snipe")
    @commands.guild_only()
    async def snipe(self, ctx: commands.Context):
        """Muestra el último mensaje borrado del canal. Uso: ?snipe"""
        cache = self.snipe_cache.get(ctx.guild.id, {})
        message = cache.get(ctx.channel.id)

        if not message:
            return await ctx.send("No hay ningún mensaje borrado recientemente en este canal.")

        embed = discord.Embed(
            description=message.content or "*[Sin contenido de texto]*",
            color=0x5865F2,
            timestamp=message.created_at
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"Mensaje borrado en #{message.channel.name}")

        if message.attachments:
            embed.add_field(name="Archivos", value="\n".join(a.filename for a in message.attachments), inline=False)

        await ctx.send(embed=embed)

    # ───────────────────── SERVER-INFO ─────────────────────
    @commands.command(name="server-info", aliases=["serverinfo", "server"])
    @commands.guild_only()
    async def server_info(self, ctx: commands.Context):
        """Muestra información del servidor. Uso: ?server-info"""
        guild = ctx.guild
        embed = discord.Embed(title=f"Información de {guild.name}", color=0x5865F2, timestamp=discord.utils.utcnow())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(name="Dueño", value=guild.owner.mention if guild.owner else "Desconocido", inline=True)
        embed.add_field(name="Creado", value=discord.utils.format_dt(guild.created_at, "R"), inline=True)
        embed.add_field(name="Miembros", value=guild.member_count, inline=True)
        embed.add_field(name="Canales", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Nivel de verificación", value=str(guild.verification_level).title(), inline=True)
        embed.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True)
        embed.add_field(name="Nivel de boost", value=guild.premium_tier, inline=True)

        await ctx.send(embed=embed)

    # ───────────────────── USER-INFO ─────────────────────
    @commands.command(name="user-info", aliases=["userinfo", "whois", "ui"])
    @commands.guild_only()
    async def user_info(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Muestra información de un usuario. Uso: ?user-info [@usuario]"""
        member = member or ctx.author
        warns = await get_warns(ctx.guild.id, member.id)

        embed = discord.Embed(title=f"Información de {member}", color=member.color or 0x5865F2, timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Apodo", value=member.nick or "Ninguno", inline=True)
        embed.add_field(name="Bot", value="Sí" if member.bot else "No", inline=True)
        embed.add_field(name="Cuenta creada", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
        embed.add_field(name="Se unió", value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Desconocido", inline=True)
        embed.add_field(name="Advertencias", value=len(warns), inline=True)

        roles = [r.mention for r in member.roles if r != ctx.guild.default_role]
        roles_text = " ".join(roles[:15]) + ("..." if len(roles) > 15 else "") if roles else "Ninguno"
        embed.add_field(name=f"Roles [{len(roles)}]", value=roles_text, inline=False)

        if member.timed_out_until and member.timed_out_until > discord.utils.utcnow():
            embed.add_field(name="Silenciado hasta", value=discord.utils.format_dt(member.timed_out_until, "R"), inline=False)

        await ctx.send(embed=embed)

    # ───────────────────── SETLOGS ─────────────────────
    @commands.command(name="setlogs")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setlogs(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Establece el canal de logs de moderación. Uso: ?setlogs [#canal] (sin canal = desactivar)"""
        if channel is None:
            await set_log_channel(ctx.guild.id, None)
            await ctx.send("Canal de logs **desactivado**.")
        else:
            await set_log_channel(ctx.guild.id, channel.id)
            await ctx.send(f"Canal de logs establecido en {channel.mention}.")

    # ───────────────────── ADDROLE / REMOVE-ROLE ─────────────────────
    @commands.command(name="addrole")
    @has_manage_roles()
    @commands.guild_only()
    async def addrole(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        """Añade un rol a un usuario. Uso: ?addrole @usuario @rol"""
        if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("No puedes asignar un rol igual o superior al tuyo.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("No puedo asignar ese rol porque está por encima o al mismo nivel que el mío.")
        if role in member.roles:
            return await ctx.send(f"{member.mention} ya tiene el rol {role.mention}.")

        try:
            await member.add_roles(role, reason=f"Añadido por {ctx.author}")
            await ctx.send(f"Rol {role.mention} añadido a {member.mention}.")
        except discord.Forbidden:
            await ctx.send("No tengo permisos para asignar ese rol.")

    @commands.command(name="remove-role", aliases=["removerole", "delrole"])
    @has_manage_roles()
    @commands.guild_only()
    async def remove_role(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        """Quita un rol a un usuario. Uso: ?remove-role @usuario @rol"""
        if role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("No puedes quitar un rol igual o superior al tuyo.")
        if role >= ctx.guild.me.top_role:
            return await ctx.send("No puedo quitar ese rol porque está por encima o al mismo nivel que el mío.")
        if role not in member.roles:
            return await ctx.send(f"{member.mention} no tiene el rol {role.mention}.")

        try:
            await member.remove_roles(role, reason=f"Eliminado por {ctx.author}")
            await ctx.send(f"Rol {role.mention} eliminado de {member.mention}.")
        except discord.Forbidden:
            await ctx.send("No tengo permisos para quitar ese rol.")

    # ───────────────────── Helper ─────────────────────
    async def _resolve_user(self, ctx: commands.Context, target) -> Optional[Union[discord.Member, discord.User]]:
        if isinstance(target, (discord.Member, discord.User)):
            return target
        try:
            return await self.bot.fetch_user(int(str(target).strip()))
        except (ValueError, discord.NotFound, discord.HTTPException):
            await ctx.send("Usuario no encontrado. Usa una mención o un ID válido.")
            return None

    # ───────────────────── ERROR HANDLER ─────────────────────
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingRequiredArgument):
            cmd = ctx.command
            await ctx.send(
                f"**Faltan argumentos.**\n"
                f"Uso correcto: `?{cmd.name} {cmd.signature}`"
            )
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Argumento inválido. Revisa el formato del comando.")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("No tienes los permisos necesarios para usar este comando.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("No tengo los permisos necesarios en este servidor.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("Usuario no encontrado.")
        elif isinstance(error, commands.RoleNotFound):
            await ctx.send("Rol no encontrado.")
        elif isinstance(error, commands.ChannelNotFound):
            await ctx.send("Canal no encontrado.")
        else:
            print(f"[ERROR] {ctx.command}: {type(error).__name__}: {error}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
