import discord
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional, List

from database import get_welcome_config, set_welcome_config

def apply_placeholders(text: str, member: discord.Member, guild: discord.Guild) -> str:
    """Reemplaza todos los placeholders disponibles."""
    if not text:
        return text
    return (
        text
        .replace("{user}", member.mention)
        .replace("{username}", str(member))
        .replace("{server}", guild.name)
        .replace("{member-count}", str(guild.member_count))
        .replace("{member_count}", str(guild.member_count))
    )

def build_panel_embed(config: dict, guild: discord.Guild) -> discord.Embed:
    """Construye el embed del panel de configuración (se actualiza en vivo)."""
    embed = discord.Embed(
        title="Panel de Configuración de Bienvenida",
        description=(
            "Usa los selectores y botones para configurar el sistema.\n"
            "El panel se actualiza automáticamente al cambiar cualquier opción.\n\n"
            "**Placeholders disponibles** (funcionan en mensaje y footer):\n"
            "`{user}` → mención\n"
            "`{username}` → nombre\n"
            "`{server}` → nombre del servidor\n"
            "`{member-count}` → cantidad de miembros"
        ),
        color=config.get("color", 0x5865F2)
    )

    channel_text = f"<#{config['channel_id']}>" if config.get("channel_id") else "No configurado"
    embed.add_field(name="Canal de bienvenida", value=channel_text, inline=True)
    embed.add_field(
        name="Estado",
        value="Activado" if config.get("enabled", 1) else "Desactivado",
        inline=True
    )

    # Canales recomendados
    rec_ids = config.get("recommended_channels") or ""
    if rec_ids:
        mentions = " ".join(f"<#{cid.strip()}>" for cid in rec_ids.split(",") if cid.strip().isdigit())
        embed.add_field(name="Canales recomendados", value=mentions or "Ninguno", inline=False)
    else:
        embed.add_field(name="Canales recomendados", value="Ninguno", inline=False)

    msg = config.get("message", "¡Bienvenido {user} a {server}!")
    embed.add_field(name="Mensaje", value=msg[:200] + ("..." if len(msg) > 200 else ""), inline=False)

    footer_text = config.get("footer") or "Sin footer"
    embed.add_field(name="Footer", value=footer_text[:100], inline=False)

    if config.get("image_url"):
        embed.set_image(url=config["image_url"])

    embed.set_footer(text="Cambia cualquier opción y el panel se actualizará solo")
    return embed

class WelcomeMessageModal(ui.Modal, title="Configurar mensaje de bienvenida"):
    message = ui.TextInput(
        label="Mensaje",
        style=discord.TextStyle.paragraph,
        placeholder="¡Bienvenido {user} a {server}! Eres el miembro #{member-count}",
        max_length=1000,
        required=True
    )

    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        await set_welcome_config(self.view_ref.guild_id, message=self.message.value)
        await self.view_ref.refresh_panel(interaction)
        await interaction.followup.send("Mensaje actualizado.", ephemeral=True)

class WelcomeColorModal(ui.Modal, title="Color del embed"):
    color = ui.TextInput(
        label="Color hexadecimal",
        placeholder="#5865F2",
        max_length=7,
        required=True
    )

    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        value = self.color.value.lstrip("#")
        try:
            color_int = int(value, 16)
            await set_welcome_config(self.view_ref.guild_id, color=color_int)
            await self.view_ref.refresh_panel(interaction)
            await interaction.followup.send(f"Color actualizado a `#{value.upper()}`.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Color inválido. Usa formato #RRGGBB.", ephemeral=True)

class WelcomeImageModal(ui.Modal, title="Imagen del embed"):
    url = ui.TextInput(
        label="URL de la imagen",
        placeholder="https://...",
        required=False,
        max_length=300
    )

    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        await set_welcome_config(self.view_ref.guild_id, image_url=self.url.value or None)
        await self.view_ref.refresh_panel(interaction)
        await interaction.followup.send("Imagen actualizada.", ephemeral=True)

class WelcomeFooterModal(ui.Modal, title="Footer del embed"):
    footer = ui.TextInput(
        label="Texto del footer (soporta placeholders)",
        placeholder="Eres el miembro #{member-count} de {server}",
        max_length=150,
        required=False
    )

    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        await set_welcome_config(self.view_ref.guild_id, footer=self.footer.value or None)
        await self.view_ref.refresh_panel(interaction)
        await interaction.followup.send("Footer actualizado.", ephemeral=True)

class WelcomeSetupView(ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.message: Optional[discord.Message] = None

    async def refresh_panel(self, interaction: discord.Interaction):
        """Actualiza el embed del panel en tiempo real."""
        config = await get_welcome_config(self.guild_id) or {}
        embed = build_panel_embed(config, interaction.guild)

        try:
            if interaction.message:
                await interaction.message.edit(embed=embed, view=self)
            elif self.message:
                await self.message.edit(embed=embed, view=self)
        except Exception:
            pass

    # ── Canal de bienvenida ──
    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Selecciona el canal de bienvenida",
        min_values=1,
        max_values=1,
        row=0
    )
    async def select_welcome_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        channel = select.values[0]
        await set_welcome_config(self.guild_id, channel_id=channel.id)
        await interaction.response.defer()
        await self.refresh_panel(interaction)
        await interaction.followup.send(f"Canal de bienvenida: {channel.mention}", ephemeral=True)

    # ── Canales recomendados (múltiples) ──
    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Canales recomendados (puedes elegir varios)",
        min_values=0,
        max_values=10,
        row=1
    )
    async def select_recommended(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        channels = select.values
        ids = ",".join(str(c.id) for c in channels) if channels else None
        await set_welcome_config(self.guild_id, recommended_channels=ids)
        await interaction.response.defer()
        await self.refresh_panel(interaction)

        if channels:
            mentions = " ".join(c.mention for c in channels)
            await interaction.followup.send(f"Canales recomendados: {mentions}", ephemeral=True)
        else:
            await interaction.followup.send("Canales recomendados eliminados.", ephemeral=True)

    # ── Botones de configuración ──
    @ui.button(label="Mensaje", style=discord.ButtonStyle.primary, emoji="💬", row=2)
    async def btn_message(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeMessageModal(self))

    @ui.button(label="Color", style=discord.ButtonStyle.secondary, emoji="🎨", row=2)
    async def btn_color(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeColorModal(self))

    @ui.button(label="Imagen", style=discord.ButtonStyle.secondary, emoji="🖼️", row=2)
    async def btn_image(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeImageModal(self))

    @ui.button(label="Footer", style=discord.ButtonStyle.secondary, emoji="📝", row=2)
    async def btn_footer(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeFooterModal(self))

    @ui.button(label="Preview", style=discord.ButtonStyle.success, emoji="👁️", row=3)
    async def btn_preview(self, interaction: discord.Interaction, button: ui.Button):
        """Muestra una vista previa real del mensaje de bienvenida."""
        config = await get_welcome_config(self.guild_id) or {}
        member = interaction.user
        guild = interaction.guild

        message = apply_placeholders(
            config.get("message", "¡Bienvenido {user} a {server}!"),
            member, guild
        )
        footer = apply_placeholders(config.get("footer") or "", member, guild)

        embed = discord.Embed(
            description=message,
            color=config.get("color", 0x5865F2)
        )
        if config.get("image_url"):
            embed.set_image(url=config["image_url"])
        if footer:
            embed.set_footer(text=footer)
        embed.set_thumbnail(url=member.display_avatar.url)

        # Canales recomendados en el preview
        rec_ids = config.get("recommended_channels") or ""
        if rec_ids:
            mentions = " ".join(f"<#{cid.strip()}>" for cid in rec_ids.split(",") if cid.strip().isdigit())
            if mentions:
                embed.add_field(name="Canales recomendados", value=mentions, inline=False)

        await interaction.response.send_message(
            content=f"**Vista previa** (usando a {member.mention}):",
            embed=embed,
            ephemeral=True
        )

    @ui.button(label="Activar / Desactivar", style=discord.ButtonStyle.danger, emoji="⚡", row=3)
    async def btn_toggle(self, interaction: discord.Interaction, button: ui.Button):
        config = await get_welcome_config(self.guild_id) or {}
        new_state = 0 if config.get("enabled", 1) else 1
        await set_welcome_config(self.guild_id, enabled=new_state)
        await interaction.response.defer()
        await self.refresh_panel(interaction)
        state = "activado" if new_state else "desactivado"
        await interaction.followup.send(f"Sistema de bienvenida **{state}**.", ephemeral=True)

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="welcome-setup", description="Configura el sistema de bienvenida del servidor")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_setup(self, interaction: discord.Interaction):
        config = await get_welcome_config(interaction.guild_id) or {}
        embed = build_panel_embed(config, interaction.guild)

        view = WelcomeSetupView(self.bot, interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # Guardamos la referencia del mensaje para poder editarlo después
        view.message = await interaction.original_response()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await get_welcome_config(member.guild.id)
        if not config or not config.get("enabled", 1) or not config.get("channel_id"):
            return

        channel = member.guild.get_channel(config["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        message = apply_placeholders(
            config.get("message", "¡Bienvenido {user} a {server}!"),
            member, member.guild
        )
        footer = apply_placeholders(config.get("footer") or "", member, member.guild)

        embed = discord.Embed(
            description=message,
            color=config.get("color", 0x5865F2)
        )
        if config.get("image_url"):
            embed.set_image(url=config["image_url"])
        if footer:
            embed.set_footer(text=footer)
        embed.set_thumbnail(url=member.display_avatar.url)

        # Canales recomendados
        rec_ids = config.get("recommended_channels") or ""
        if rec_ids:
            mentions = " ".join(f"<#{cid.strip()}>" for cid in rec_ids.split(",") if cid.strip().isdigit())
            if mentions:
                embed.add_field(name="Canales recomendados", value=mentions, inline=False)

        try:
            await channel.send(content=member.mention, embed=embed)
        except discord.Forbidden:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
