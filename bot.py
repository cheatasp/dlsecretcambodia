import asyncio
import logging
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.markdown import hbold

# --- CONFIGURATION ---
API_TOKEN = '8997667603:AAHVmlPvigDCKGAG9PZKH34ysExmBjiN1p4'
DB_PATH = 'stats.db'

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Local cache to prevent race conditions with multi-photo albums
processed_media_groups = set()

# --- DATABASE INITIALIZATION ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS msgs 
                            (id INTEGER, 
                             chat_id INTEGER, 
                             media_group_id TEXT, 
                             time TEXT,
                             PRIMARY KEY (id, chat_id))''')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_chat_time ON msgs (chat_id, time)')
        await db.commit()

# --- HANDLERS ---

@dp.message(Command("count"))
async def count_range(message: types.Message):
    try:
        args = message.text.split()
        start_id, end_id = int(args[1]), int(args[2])
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM msgs WHERE chat_id=? AND id BETWEEN ? AND ?", 
                                   (message.chat.id, start_id, end_id)) as cursor:
                row = await cursor.fetchone()
                await message.reply(f"🔢 Total unique messages: {hbold(row[0])}", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.reply("Usage: `/count [start_id] [end_id]`")

@dp.message(Command("summary"))
async def summary(message: types.Message):
    args = message.text.split()
    period = args[-1].lower() if len(args) > 1 else "daily"
    now = datetime.now()
    
    if period == "daily": since_str = now.strftime('%Y-%m-%d 00:00:00')
    elif period == "weekly": since_str = (now - timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')
    elif period == "monthly": since_str = (now - timedelta(days=30)).strftime('%Y-%m-%d 00:00:00')
    else: return await message.reply("Options: daily, weekly, monthly")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM msgs WHERE chat_id=? AND time >= ?", 
                               (message.chat.id, since_str)) as cursor:
            row = await cursor.fetchone()
            await message.answer(f"📊 {hbold(period.capitalize())} Summary: {row[0]} messages.", parse_mode="HTML")

@dp.message()
async def logger_handler(message: types.Message):
    mg_id = message.media_group_id 
    chat_id = message.chat.id
    msg_time_str = message.date.strftime('%Y-%m-%d %H:%M:%S')
    today_start = message.date.strftime('%Y-%m-%d 00:00:00')

    # --- MULTI-PHOTO FIX ---
    if mg_id:
        # Check if we are already processing this album in this session
        if mg_id in processed_media_groups:
            return
        processed_media_groups.add(mg_id)
        
        # Optional: Clear old IDs from memory after 1 minute to save RAM
        asyncio.get_event_loop().call_later(60, lambda: processed_media_groups.discard(mg_id))

    async with aiosqlite.connect(DB_PATH) as db:
        # Check database for the media group as a fallback
        if mg_id:
            async with db.execute("SELECT 1 FROM msgs WHERE chat_id=? AND media_group_id=?", (chat_id, mg_id)) as cursor:
                if await cursor.fetchone():
                    return

        # Insert message
        await db.execute("INSERT OR IGNORE INTO msgs (id, chat_id, media_group_id, time) VALUES (?, ?, ?, ?)", 
                         (message.message_id, chat_id, mg_id, msg_time_str))
        await db.commit()

        # Count total for today
        async with db.execute("SELECT COUNT(*) FROM msgs WHERE chat_id=? AND time >= ?", (chat_id, today_start)) as cursor:
            row = await cursor.fetchone()
            current_total = row[0]

    await message.reply(f"📈 ចំនួនសរុបថ្ងៃនេះ: {hbold(current_total)}", parse_mode="HTML", disable_notification=True)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
