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
    
    # 1. Handle the classic single daily total total
    if period == "daily":
        since_str = now.strftime('%Y-%m-%d 00:00:00')
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM msgs WHERE chat_id=? AND time >= ?", 
                                   (message.chat.id, since_str)) as cursor:
                row = await cursor.fetchone()
                return await message.answer(f"📊 {hbold(period.capitalize())} Summary: {row[0]} messages.", parse_mode="HTML")

    # 2. Set up ranges for daily breakdowns
    if period == "weekly":
        since_str = (now - timedelta(days=6)).strftime('%Y-%m-%d 00:00:00') # Last 7 days including today
        report_header = f"📊 {hbold('របាយការណ៍ប្រចាំសប្តាហ៍')} (Last 7 Days):\n"
    elif period == "monthly":
        since_str = (now - timedelta(days=29)).strftime('%Y-%m-%d 00:00:00') # Last 30 days including today
        report_header = f"📊 {hbold('របាយការណ៍ប្រចាំខែ')} (Last 30 Days):\n"
    else:
        return await message.reply("Options: daily, weekly, monthly")

    # 3. Query database grouping by day
    async with aiosqlite.connect(DB_PATH) as db:
        # SUBSTR(time, 1, 10) extracts 'YYYY-MM-DD' from 'YYYY-MM-DD HH:MM:SS'
        async with db.execute(
            """SELECT SUBSTR(time, 1, 10) as log_date, COUNT(*) 
               FROM msgs 
               WHERE chat_id=? AND time >= ? 
               GROUP BY log_date 
               ORDER BY log_date ASC""", 
            (message.chat.id, since_str)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return await message.answer(f"📊 No log history found for this period.")

    # 4. Build output string in your exact formatting scheme
    response_lines = [report_header]
    for row in rows:
        db_date, total_log = row
        # Convert YYYY-MM-DD to dd-mm-yyyy
        date_obj = datetime.strptime(db_date, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%d-%m-%Y")
        
        response_lines.append(f"• {formatted_date} : {total_log}")

    await message.answer("\n".join(response_lines), parse_mode="HTML")

@dp.message()
async def logger_handler(message: types.Message):
    mg_id = message.media_group_id 
    chat_id = message.chat.id
    msg_time_str = message.date.strftime('%Y-%m-%d %H:%M:%S')
    today_start = message.date.strftime('%Y-%m-%d 00:00:00')

    # --- MULTI-PHOTO FIX ---
    if mg_id:
        if mg_id in processed_media_groups:
            return
        processed_media_groups.add(mg_id)
        asyncio.get_event_loop().call_later(60, lambda: processed_media_groups.discard(mg_id))

    async with aiosqlite.connect(DB_PATH) as db:
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

    await message.reply(f"📈 ចំនួនកម្មងសរុបថ្ងៃនេះ: {hbold(current_total)}", parse_mode="HTML", disable_notification=True)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
