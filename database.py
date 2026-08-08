import aiosqlite
import os
import time
from typing import Optional, List, Dict, Any

DB_PATH = os.getenv("DATABASE_PATH", "bot.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS temp_bans (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                unban_at REAL NOT NULL,
                reason TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS temp_locks (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                unlock_at REAL NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS welcome_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                message TEXT DEFAULT '¡Bienvenido {user} a {server}!',
                color INTEGER DEFAULT 5814783,
                image_url TEXT,
                footer TEXT DEFAULT 'Sistema de Bienvenida',
                recommended_channels TEXT,
                enabled INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mod_config (
                guild_id INTEGER PRIMARY KEY,
                log_channel_id INTEGER
            )
        """)
        # Migraciones seguras
        try:
            await db.execute("ALTER TABLE welcome_config ADD COLUMN recommended_channels TEXT")
        except Exception:
            pass
        await db.commit()

async def add_warn(guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO warns (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason, time.time())
        )
        await db.commit()
        return cursor.lastrowid

async def get_warns(guild_id: int, user_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, reason, moderator_id, timestamp FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC",
            (guild_id, user_id)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def delete_warn(guild_id: int, user_id: int, warn_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM warns WHERE id = ? AND guild_id = ? AND user_id = ?",
            (warn_id, guild_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0

async def add_temp_ban(guild_id: int, user_id: int, unban_at: float, reason: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_bans (guild_id, user_id, unban_at, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, unban_at, reason)
        )
        await db.commit()

async def remove_temp_ban(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM temp_bans WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        await db.commit()

async def get_expired_temp_bans() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT guild_id, user_id FROM temp_bans WHERE unban_at <= ?",
            (time.time(),)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def add_temp_lock(guild_id: int, channel_id: int, unlock_at: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO temp_locks (guild_id, channel_id, unlock_at) VALUES (?, ?, ?)",
            (guild_id, channel_id, unlock_at)
        )
        await db.commit()

async def remove_temp_lock(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM temp_locks WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id)
        )
        await db.commit()

async def get_expired_temp_locks() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT guild_id, channel_id FROM temp_locks WHERE unlock_at <= ?",
            (time.time(),)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_welcome_config(guild_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM welcome_config WHERE guild_id = ?", (guild_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def set_welcome_config(guild_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        current = await get_welcome_config(guild_id)
        if current is None:
            await db.execute(
                "INSERT INTO welcome_config (guild_id) VALUES (?)", (guild_id,)
            )

        allowed = {
            "channel_id", "message", "color", "image_url",
            "footer", "recommended_channels", "enabled"
        }
        fields = []
        values = []
        for key, value in kwargs.items():
            if key in allowed:
                fields.append(f"{key} = ?")
                values.append(value)

        if fields:
            values.append(guild_id)
            await db.execute(
                f"UPDATE welcome_config SET {', '.join(fields)} WHERE guild_id = ?",
                values
            )
        await db.commit()

# ── Logs de moderación ──
async def set_log_channel(guild_id: int, channel_id: Optional[int]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO mod_config (guild_id, log_channel_id) VALUES (?, ?)",
            (guild_id, channel_id)
        )
        await db.commit()

async def get_log_channel(guild_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT log_channel_id FROM mod_config WHERE guild_id = ?", (guild_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None
