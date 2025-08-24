# -*- coding: utf-8 -*-
import logging
import sqlite3
import os
from pathlib import Path
from typing import Optional, Iterable, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# ===== Load .env variables =====
from dotenv import load_dotenv
load_dotenv()  # loads BOT_TOKEN and CHANNEL_ID if present

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)  # convert to int if provided

REQUIRED_HASHTAG = "#Lesson_of_the_day"
DB_PATH = "lessons.db"
MAX_KEEP = None
APP_TZ = ZoneInfo("Africa/Addis_Ababa")
MAX_MSG_LEN = 4096

# ===== Logging =====
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("lessonbot")

# ===== Database setup =====
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    channel_id INTEGER,
    message_id INTEGER,
    text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, channel_id, message_id) ON CONFLICT IGNORE
)
""")
cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_text ON lessons(text)")
cur.execute("""
CREATE TABLE IF NOT EXISTS bookmarks (
    user_id INTEGER,
    lesson_id INTEGER,
    PRIMARY KEY (user_id, lesson_id)
)
""")
conn.commit()

# ===== Helper Functions =====
def save_lesson(*, text: str, source: str, channel_id: Optional[int] = None,
                message_id: Optional[int] = None, created_at: Optional[str] = None):
    cur.execute(
        "INSERT OR IGNORE INTO lessons (source, channel_id, message_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
        (source, channel_id, message_id, text.strip(), created_at or datetime.now(APP_TZ).isoformat())
    )
    conn.commit()
    if MAX_KEEP:
        cur.execute("SELECT COUNT(*) FROM lessons")
        total = cur.fetchone()[0]
        if total > MAX_KEEP:
            to_delete = total - MAX_KEEP
            cur.execute(
                "DELETE FROM lessons WHERE id IN (SELECT id FROM lessons ORDER BY id ASC LIMIT ?)",
                (to_delete,)
            )
            conn.commit()

def _rows_to_today(rows: Iterable[Tuple[int, str, str]]) -> list[Tuple[int, str, str]]:
    today = datetime.now(APP_TZ).date()
    out = []
    for _id, text, created_at in rows:
        try:
            dt = datetime.fromisoformat(created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=APP_TZ)
            if dt.astimezone(APP_TZ).date() == today:
                out.append((_id, text, created_at))
        except:
            continue
    return out

def has_today_lesson() -> bool:
    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC LIMIT 200")
    rows = cur.fetchall()
    return len(_rows_to_today(rows)) > 0

def format_lesson(lesson_id: int, text: str, created_at: str) -> str:
    try:
        date_str = datetime.fromisoformat(created_at)
        if date_str.tzinfo is None:
            date_str = date_str.replace(tzinfo=APP_TZ)
        date_str = date_str.astimezone(APP_TZ).strftime("%d/%m/%Y")
    except Exception:
        date_str = created_at
    return f"📅 {date_str}\n\n📘 Lesson #{lesson_id}:\n\n{text}"

def build_nav_keyboard(user_id: Optional[int], lesson_id: int, max_id: int) -> InlineKeyboardMarkup:
    prev_id = max(lesson_id - 1, 1)
    next_id = min(lesson_id + 1, max_id)
    buttons = [
        InlineKeyboardButton("⬅ Previous", callback_data=f"lesson:{prev_id}"),
        InlineKeyboardButton("Next ➡", callback_data=f"lesson:{next_id}"),
        InlineKeyboardButton("🔖 Bookmark", callback_data=f"bookmark:{lesson_id}"),
        InlineKeyboardButton("❌ Unbookmark", callback_data=f"unbookmark:{lesson_id}"),
    ]
    return InlineKeyboardMarkup([buttons])

def build_reply_keyboard() -> ReplyKeyboardMarkup:
    today_label = "📌 Today ✅" if has_today_lesson() else "📌 Today"
    return ReplyKeyboardMarkup(
        [[today_label, "🆕 Latest"], ["⏪ Previous", "🔍 Search by Date"], ["🔖 My Bookmarks"]],
        resize_keyboard=True,
    )

async def send_long_message(chat_id, text, context: ContextTypes.DEFAULT_TYPE, reply_markup=None):
    chunks = [text[i:i+MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]
    for i, chunk in enumerate(chunks):
        await context.bot.send_message(chat_id, chunk, reply_markup=reply_markup if i == 0 else None)

async def send_formatted_lesson(chat_id: int, lesson_id: int, user_id: Optional[int], context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, text, created_at FROM lessons WHERE id=?", (lesson_id,))
    row = cur.fetchone()
    if not row:
        await context.bot.send_message(chat_id, "⚠️ Lesson not found.")
        return
    _, text, created_at = row
    cur.execute("SELECT MAX(id) FROM lessons")
    max_id = cur.fetchone()[0] or lesson_id
    await send_long_message(chat_id, format_lesson(lesson_id, text, created_at), context,
                            reply_markup=build_nav_keyboard(user_id, lesson_id, max_id))

# ===== Commands =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome = (
        f"👋 Hello, <b>{user.first_name}</b>!\n\n"
        "🌟 <i>Every day holds a lesson to teach us.</i> 🌟\n\n"
        f"Welcome to <b>Lesson of the Day Bot</b>! 🎓\n\n"
        "📚 Learn something new every day — explore today’s lesson, revisit previous ones, "
        "search by date, and bookmark your favorites. 🚀\n\n"
        "✨ <b>Features you’ll love:</b>\n"
        "• Get <b>today’s lesson</b> instantly\n"
        "• Explore <b>latest & previous</b> lessons\n"
        "• <b>Search by date</b> easily\n"
        "• Save & manage your <b>bookmarks</b>\n\n"
        "🔽 <i>Choose an option below to get started:</i>")
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=build_reply_keyboard())

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC LIMIT 200")
    rows = cur.fetchall()
    today_lessons = _rows_to_today(rows)
    if not today_lessons:
        await update.message.reply_text("📭 No lesson available for today yet.", reply_markup=build_reply_keyboard())
        return
    lesson_id, text, created_at = today_lessons[0]
    await send_formatted_lesson(update.effective_chat.id, lesson_id, update.effective_user.id, context)

async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("📭 No lessons available yet.", reply_markup=build_reply_keyboard())
        return
    lesson_id, text, created_at = row
    await send_formatted_lesson(update.effective_chat.id, lesson_id, update.effective_user.id, context)

async def previous(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("📭 No lessons available.", reply_markup=build_reply_keyboard())
        return
    for lesson_id, text, created_at in reversed(rows):
        await send_formatted_lesson(update.effective_chat.id, lesson_id, update.effective_user.id, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text
    user_id = update.effective_user.id

    if msg.forward_from_chat:
        await handle_forwarded_message(update, context)
        return

    if text in ["📌 Today ✅", "📌 Today"]:
        await today(update, context)
    elif text == "🆕 Latest":
        await latest(update, context)
    elif text == "⏪ Previous":
        await previous(update, context)
    elif text == "🔍 Search by Date":
        await update.message.reply_text("📅 Enter date YYYY-MM-DD:", reply_markup=build_reply_keyboard())
    elif text == "🔖 My Bookmarks":
        cur.execute("SELECT l.id, l.text, l.created_at FROM lessons l JOIN bookmarks b ON l.id=b.lesson_id WHERE b.user_id=? ORDER BY l.id DESC", (user_id,))
        rows = cur.fetchall()
        for lesson_id, text, created_at in rows[:5]:
            await send_formatted_lesson(update.effective_chat.id, lesson_id, user_id, context)
    else:
        # Check if date
        import re
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'
        if re.match(date_pattern, text):
            try:
                search_date_obj = datetime.strptime(text, "%Y-%m-%d").date()
                cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC")
                all_rows = cur.fetchall()
                found_lessons = []
                for lesson_id, lesson_text, created_at in all_rows:
                    try:
                        dt = datetime.fromisoformat(created_at)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=APP_TZ)
                        if dt.astimezone(APP_TZ).date() == search_date_obj:
                            found_lessons.append((lesson_id, lesson_text, created_at))
                    except:
                        continue
                if found_lessons:
                    lesson_id, lesson_text, created_at = found_lessons[0]
                    await send_formatted_lesson(update.effective_chat.id, lesson_id, user_id, context)
                else:
                    await update.message.reply_text(f"📭 No lesson found for {text}.", reply_markup=build_reply_keyboard())
            except ValueError:
                await update.message.reply_text("❌ Invalid date format. Use YYYY-MM-DD.", reply_markup=build_reply_keyboard())
        else:
            await update.message.reply_text("❓ I didn't understand that. Use the buttons below.", reply_markup=build_reply_keyboard())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    if data.startswith("lesson:"):
        lesson_id = int(data.split(":")[1])
        await send_formatted_lesson(query.message.chat.id, lesson_id, user_id, context)
    elif data.startswith("bookmark:"):
        lesson_id = int(data.split(":")[1])
        cur.execute("INSERT OR IGNORE INTO bookmarks (user_id, lesson_id) VALUES (?, ?)", (user_id, lesson_id))
        conn.commit()
        await query.edit_message_text("🔖 Lesson bookmarked!")
    elif data.startswith("unbookmark:"):
        lesson_id = int(data.split(":")[1])
        cur.execute("DELETE FROM bookmarks WHERE user_id=? AND lesson_id=?", (user_id, lesson_id))
        conn.commit()
        await query.edit_message_text("❌ Bookmark removed!")

async def handle_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.forward_from_chat and msg.forward_from_chat.type == "channel":
        text = (msg.text or msg.caption or "").strip()
        if text and REQUIRED_HASHTAG in text:
            save_lesson(text=text, source="forwarded", channel_id=msg.forward_from_chat.id,
                        message_id=msg.forward_from_message_id,
                        created_at=msg.forward_date.isoformat() if msg.forward_date else datetime.now(APP_TZ).isoformat())
            await msg.reply_text("✅ Lesson saved successfully!", reply_markup=build_reply_keyboard())
            log.info(f"Saved forwarded lesson from user {update.effective_user.id}")
        else:
            await msg.reply_text("❌ Message must contain #Lesson_of_the_day hashtag", reply_markup=build_reply_keyboard())
    else:
        await msg.reply_text("❓ I didn't understand that. Use the buttons below.", reply_markup=build_reply_keyboard())

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return
    if CHANNEL_ID and msg.chat.id != CHANNEL_ID:
        return
    text = (msg.text or msg.caption or "").strip()
    if text and REQUIRED_HASHTAG in text:
        save_lesson(text=text, source="channel", channel_id=msg.chat.id,
                    message_id=msg.message_id, created_at=msg.date.isoformat())
        log.info("Saved lesson from channel")

# ===== Main =====
def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not found in environment variables. Add it to your .env or PythonAnywhere environment.")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, on_channel_post))
    log.info("🚀 Lesson of the Day Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
