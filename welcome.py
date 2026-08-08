import discord
from discord.ext import commands
from discord import app_commands, ui

from database import get_welcome_config, set_welcome_config

class WelcomeMessageModal(ui.Modal, title="Configurar mensaje de bienvenida"):
    message = ui.TextInput(
        label="Mensaje",
        style=discord.TextStyle.paragraph,
        placeholder="¡Bienvenido {user} a {server}!",
        max_length=1000,
        required=True
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await set_welcome_config(self.guild_id, message=self.message.value)
        await interaction.response.send_message("Mensaje de bienvenida actualizado.", ephemeral=True)

class WelcomeColorModal(ui.Modal, title="Color del embed"):
    color = ui.TextInput(
        label="Color hexadecimal",
        placeholder="#5865F2",
        max_length=7,
        required=True
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        value = self.color.value.lstrip("#")
        try:
            color_int = int(value, 16)
            await set_welcome_config(self.guild_id, color=color_int)
            await interaction.response.send_message(f"Color actualizado a `#{value.upper()}`.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Color inválido. Usa formato hexadecimal (ej: #5865F2).", ephemeral=True)

class WelcomeImageModal(ui.Modal, title="Imagen del embed"):
    url = ui.TextInput(
        label="URL de la imagen",
        placeholder="https://...",
        required=False,
        max_length=300
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await set_welcome_config(self.guild_id, image_url=self.url.value or None)
        await interaction.response.send_message("Imagen actualizada.", ephemeral=True)

class WelcomeFooterModal(ui.Modal, title="Footer del embed"):
    footer = ui.TextInput(
        label="Texto del footer",
        placeholder="Sistema de Bienvenida",
        max_length=100,
        required=False
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        await set_welcome_config(self.guild_id, footer=self.footer.value or None)
        await interaction.response.send_message("Footer actualizado.", ephemeral=True)

class WelcomeSetupView(ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id

    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Selecciona el canal de bienvenida",
        min_values=1,
        max_values=1
    )
    async def select_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        channel = select.values[0]
        await set_welcome_config(self.guild_id, channel_id=channel.id)
        await interaction.response.send_message(f"Canal de bienvenida establecido: {channel.mention}", ephemeral=True)

    @ui.button(label="Mensaje", style=discord.ButtonStyle.primary, emoji="💬", row=1)
    async def set_message(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeMessageModal(self.guild_id))

    @ui.button(label="Color", style=discord.ButtonStyle.secondary, emoji="🎨", row=1)
    async def set_color(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeColorModal(self.guild_id))

    @ui.button(label="Imagen", style=discord.ButtonStyle.secondary, emoji="🖼️", row=1)
    async def set_image(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeImageModal(self.guild_id))

    @ui.button(label="Footer", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
    async def set_footer(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(WelcomeFooterModal(self.guild_id))

    @ui.button(label="Activar / Desactivar", style=discord.ButtonStyle.danger, emoji="⚡", row=2)
    async def toggle(self, interaction: discord.Interaction, button: ui.Button):
        config = await get_welcome_config(self.guild_id) or {}
        new_state = 0 if config.get("enabled", 1) else 1
        await set_welcome_config(self.guild_id, enabled=new_state)
        state = "activado" if new_state else "desactivado"
        await interaction.response.send_message(f"Sistema de bienvenida **{state}**.", ephemeral=True)

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="welcome-setup", description="Configura el sistema de bienvenida del servidor")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_setup(self, interaction: discord.Interaction):
        config = await get_welcome_config(interaction.guild_id) or {}

        embed = discord.Embed(
            title="Panel de Configuración de Bienvenida",
            description=(
                "Usa el selector y los botones de abajo para configurar el sistema.\n\n"
                "**Variables disponibles en el mensaje:**\n"
                "`{user}` → mención del usuario\n"
                "`{username}` → nombre del usuario\n"
                "`{server}` → nombre del servidor"
            ),
            color=config.get("color", 0x5865F2)
        )
        embed.add_field(
            name="Canal actual",
            value=f"<#{config['channel_id']}>" if config.get("channel_id") else "No configurado",
            inline=True
        )
        embed.add_field(
            name="Estado",
            value="Activado" if config.get("enabled", 1) else "Desactivado",
            inline=True
        )
        embed.add_field(
            name="Mensaje actual",
            value=config.get("message", "¡Bienvenido {user} a {server}!")[:150],
            inline=False
        )

        view = WelcomeSetupView(self.bot, interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await get_welcome_config(member.guild.id)
        if not config or not config.get("enabled", 1) or not config.get("channel_id"):
            return

        channel = member.guild.get_channel(config["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        message = config.get("message", "¡Bienvenido {user} a {server}!")
        message = (
            message
            .replace("{user}", member.mention)
            .replace("{username}", str(member))
            .replace("{server}", member.guild.name)
        )

        embed = discord.Embed(description=message, color=config.get("color", 0x5865F2))
        if config.get("image_url"):
            embed.set_image(url=config["image_url"])
        if config.get("footer"):
            embed.set_footer(text=config["footer"])
        embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(content=member.mention, embed=embed)
        except discord.Forbidden:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
