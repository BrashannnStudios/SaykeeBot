import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from aiohttp import web

from database import init_db

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN no está definido en las variables de entorno.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("?"),
    intents=intents,
    case_insensitive=True,
    help_command=None,
    owner_id=OWNER_ID if OWNER_ID else None
)

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="?cmds | /welcome-setup")
    )
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Error al sincronizar slash commands: {e}")

@bot.command(name="cmds")
async def cmds(ctx: commands.Context):
    """Muestra la lista de comandos disponibles."""
    embed = discord.Embed(
        title="Comandos disponibles",
        color=0x5865F2,
        description="Prefijo: `?` (no distingue mayúsculas/minúsculas)"
    )
    embed.add_field(
        name="Moderación",
        value=(
            "`?lock` `?unlock` `?warn` `?warns` `?delwarn`\n"
            "`?ban` `?unban` `?tempban` `?kick`\n"
            "`?mute` `?unmute` `?clear` `?slowmode` `?nick`\n"
            "`?addrole` `?remove-role` `?setlogs`"
        ),
        inline=False
    )
    embed.add_field(
        name="Utilidad",
        value="`?snipe` `?user-info` `?server-info` `?cmds`",
        inline=False
    )
    embed.add_field(
        name="Bienvenida",
        value="`/welcome-setup`",
        inline=False
    )
    embed.set_footer(text="Bot de moderación global")
    await ctx.send(embed=embed)

async def health_handler(request):
    return web.Response(text="OK", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Health check escuchando en el puerto {port}")

async def main():
    await init_db()
    await bot.load_extension("moderation")
    await bot.load_extension("welcome")
    asyncio.create_task(start_health_server())
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
