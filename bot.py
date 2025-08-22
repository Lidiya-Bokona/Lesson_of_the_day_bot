# -*- coding: utf-8 -*-
import logging
import sqlite3
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

# ========= CONFIG =========
BOT_TOKEN = "8024047392:AAHEHvURxq_unPZC5g92nfMCu3ZEYqaNTrA"
CHANNEL_ID = 1002428279370  # Fill after first post if you want to restrict source channel
REQUIRED_HASHTAG = "#Lesson_of_the_day"
DB_PATH = Path("lessons.db")
MAX_KEEP = None
APP_TZ = ZoneInfo("Africa/Addis_Ababa")
MAX_MSG_LEN = 4096
CHANNEL_USERNAME = "@tech_world_o1"
# =========================

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("lessonbot")

# --- DB setup ---
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

cur.execute(
    """
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    channel_id INTEGER,
    message_id INTEGER,
    text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, channel_id, message_id) ON CONFLICT IGNORE
)
"""
)
cur.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_text ON lessons(text)"
)
cur.execute(
    """
CREATE TABLE IF NOT EXISTS bookmarks (
    user_id INTEGER,
    lesson_id INTEGER,
    PRIMARY KEY (user_id, lesson_id)
)
"""
)
conn.commit()


# ===== Helper Functions =====
def save_lesson(
    *,
    text: str,
    source: str,
    channel_id: Optional[int] = None,
    message_id: Optional[int] = None,
    created_at: Optional[str] = None,
):
    """Persist a lesson and enforce MAX_KEEP."""
    cur.execute(
        """
        INSERT OR IGNORE INTO lessons (source, channel_id, message_id, text, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            source,
            channel_id,
            message_id,
            text.strip(),
            created_at or datetime.now(APP_TZ).isoformat(),
        ),
    )
    conn.commit()

    if MAX_KEEP:
        cur.execute("SELECT COUNT(*) FROM lessons")
        total = cur.fetchone()[0]
        if total > MAX_KEEP:
            to_delete = total - MAX_KEEP
            cur.execute(
                """
                DELETE FROM lessons
                WHERE id IN (SELECT id FROM lessons ORDER BY id ASC LIMIT ?)
                """,
                (to_delete,),
            )
            conn.commit()


def _rows_to_today(
    rows: Iterable[Tuple[int, str, str]]
) -> list[Tuple[int, str, str]]:
    """Filter rows to those created today in APP_TZ."""
    today = datetime.now(APP_TZ).date()
    out = []
    for _id, text, created_at in rows:
        try:
            dt = datetime.fromisoformat(created_at)
            # If created_at has timezone, convert; else assume naive in APP_TZ
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=APP_TZ)
            dt_local = dt.astimezone(APP_TZ)
            if dt_local.date() == today:
                out.append((_id, text, created_at))
        except Exception:
            # Fallback: skip malformed timestamps
            continue
    return out


def has_today_lesson() -> bool:
    """Efficiently detect if we have any lesson for 'today' by sampling recent entries."""
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
        date_str = created_at  # raw fallback
    return f"📅 {date_str}\n\n📘 Lesson #{lesson_id}:\n\n{text}"


def build_nav_keyboard(
    user_id: Optional[int], lesson_id: int, max_id: int
) -> InlineKeyboardMarkup:
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
    """Emoji-based, dynamic Today highlight."""
    today_label = "📌 Today ✅" if has_today_lesson() else "📌 Today"
    return ReplyKeyboardMarkup(
        [
            [today_label, "🆕 Latest"],
            ["⏪ Previous", "🔍 Search by Date"],
            ["🔖 My Bookmarks"],
        ],
        resize_keyboard=True,
    )


async def send_long_message(
    chat_id, text, context: ContextTypes.DEFAULT_TYPE, reply_markup=None
):
    chunks = [text[i : i + MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]
    for i, chunk in enumerate(chunks):
        await context.bot.send_message(
            chat_id, chunk, reply_markup=reply_markup if i == 0 else None
        )


async def send_formatted_lesson(
    chat_id: int, lesson_id: int, user_id: Optional[int], context: ContextTypes.DEFAULT_TYPE
):
    cur.execute("SELECT id, text, created_at FROM lessons WHERE id=?", (lesson_id,))
    row = cur.fetchone()
    if not row:
        await context.bot.send_message(chat_id, "⚠️ Lesson not found.")
        return
    _, text, created_at = row
    cur.execute("SELECT MAX(id) FROM lessons")
    max_id = cur.fetchone()[0] or lesson_id
    await send_long_message(
        chat_id,
        format_lesson(lesson_id, text, created_at),
        context,
        reply_markup=build_nav_keyboard(user_id, lesson_id, max_id),
    )


# ===== Commands =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome = (
        f"👋 Hello, <b>{user.first_name}</b>!\n\n"
        "🌟 <i>Every day holds a lesson to teach us.</i> 🌟\n\n"
        f"Welcome to <b>Lesson of the Day Bot</b>! 🎓\n\n"
        "📚 Every single day have its own lesson to teach. explore today’s lesson, revisit previous ones, "
        "search by date, and bookmark your favorites. 🚀\n\n"
        "✨ <b>Features you’ll love:</b>\n"
        "• Get <b>today’s lesson</b> instantly\n"
        "• Explore <b>latest & previous</b> lessons\n"
        "• <b>Search by date</b> easily\n"
        "• Save & manage your <b>bookmarks</b>\n\n"
        "🔽 <i>Choose an option below to get started:</i>"
    )
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=build_reply_keyboard())


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC")
    rows = cur.fetchall()
    todays = _rows_to_today(rows)
    if not todays:
        await update.message.reply_text("⚠️ Today's lesson is not posted yet.", reply_markup=build_reply_keyboard())
        return
    payload = "\n\n— — —\n\n".join(format_lesson(r[0], r[1], r[2]) for r in todays)
    await send_long_message(update.effective_chat.id, payload, context, reply_markup=build_reply_keyboard())


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    if row:
        lesson_id, text, created_at = row
        cur.execute("SELECT MAX(id) FROM lessons")
        max_id = cur.fetchone()[0] or lesson_id
        await send_long_message(
            update.effective_chat.id,
            format_lesson(lesson_id, text, created_at),
            context,
            reply_markup=build_nav_keyboard(update.effective_user.id, lesson_id, max_id),
        )
    else:
        await update.message.reply_text("⚠️ No lessons yet.", reply_markup=build_reply_keyboard())


async def previous(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # default to 5 previous (excluding current latest)
    n = 5
    if context.args:
        try:
            n = max(1, min(20, int(context.args[0])))
        except ValueError:
            pass
    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC LIMIT ? OFFSET 1", (n,))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("⚠️ No previous lessons yet.", reply_markup=build_reply_keyboard())
        return
    payload = "\n\n— — —\n\n".join(format_lesson(r[0], r[1], r[2]) for r in rows)
    await send_long_message(update.effective_chat.id, payload, context, reply_markup=build_reply_keyboard())


async def search_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /searchdate <dd/mm/yyyy>", reply_markup=build_reply_keyboard())
        return
    try:
        target_date = datetime.strptime(context.args[0], "%d/%m/%Y").date()
    except ValueError:
        await update.message.reply_text("⚠️ Date format: dd/mm/yyyy", reply_markup=build_reply_keyboard())
        return

    cur.execute("SELECT id, text, created_at FROM lessons ORDER BY id DESC")
    rows = cur.fetchall()

    matches = []
    for _id, text, created_at in rows:
        try:
            dt = datetime.fromisoformat(created_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=APP_TZ)
            if dt.astimezone(APP_TZ).date() == target_date:
                matches.append((_id, text, created_at))
        except Exception:
            continue

    if not matches:
        await update.message.reply_text(f"No lessons found on {context.args[0]}", reply_markup=build_reply_keyboard())
        return

    payload = "\n\n— — —\n\n".join(format_lesson(r[0], r[1], r[2]) for r in matches)
    await send_long_message(update.effective_chat.id, payload, context, reply_markup=build_reply_keyboard())


async def my_bookmarks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute(
        """
        SELECT lessons.id, lessons.text, lessons.created_at
        FROM lessons
        JOIN bookmarks ON lessons.id = bookmarks.lesson_id
        WHERE bookmarks.user_id=?
        ORDER BY lessons.id DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("📌 No bookmarks yet.", reply_markup=build_reply_keyboard())
        return

    payload = "\n\n— — —\n\n".join(format_lesson(r[0], r[1], r[2]) for r in rows[:10])
    await send_long_message(update.effective_chat.id, payload, context, reply_markup=build_reply_keyboard())


async def bookmark_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /bookmark <lesson_id>", reply_markup=build_reply_keyboard())
        return
    try:
        lesson_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Lesson ID must be a number.", reply_markup=build_reply_keyboard())
        return

    cur.execute("SELECT id FROM lessons WHERE id=?", (lesson_id,))
    if not cur.fetchone():
        await update.message.reply_text("Lesson not found.", reply_markup=build_reply_keyboard())
        return

    user_id = update.effective_user.id
    try:
        cur.execute("INSERT INTO bookmarks (user_id, lesson_id) VALUES (?, ?)", (user_id, lesson_id))
        conn.commit()
        await update.message.reply_text("✅ Lesson bookmarked.", reply_markup=build_reply_keyboard())
    except sqlite3.IntegrityError:
        await update.message.reply_text("🔖 Already bookmarked.", reply_markup=build_reply_keyboard())


async def unbookmark_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unbookmark <lesson_id>", reply_markup=build_reply_keyboard())
        return
    try:
        lesson_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Lesson ID must be a number.", reply_markup=build_reply_keyboard())
        return

    user_id = update.effective_user.id
    cur.execute("DELETE FROM bookmarks WHERE user_id=? AND lesson_id=?", (user_id, lesson_id))
    conn.commit()
    await update.message.reply_text("❌ Lesson unbookmarked.", reply_markup=build_reply_keyboard())


# ===== Reply Keyboard Button Mapping =====
async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text.startswith("📌 Today"):
        await today(update, context)
    elif text == "🆕 Latest":
        await latest(update, context)
    elif text == "⏪ Previous":
        await previous(update, context)
    elif text == "🔍 Search by Date":
        await update.message.reply_text("📅 Use: /searchdate <dd/mm/yyyy>", reply_markup=build_reply_keyboard())
    elif text == "🔖 My Bookmarks":
        await my_bookmarks(update, context)
    else:
        await update.message.reply_text("⚠️ Unknown option. Please use the buttons below.", reply_markup=build_reply_keyboard())


# ===== Inline Callback Handler =====
async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    if data.startswith("lesson:"):
        lesson_id = int(data.split(":")[1])
        await send_formatted_lesson(query.message.chat.id, lesson_id, query.from_user.id, context)
    elif data.startswith("bookmark:"):
        lesson_id = int(data.split(":")[1])
        user_id = query.from_user.id
        try:
            cur.execute("INSERT INTO bookmarks (user_id, lesson_id) VALUES (?, ?)", (user_id, lesson_id))
            conn.commit()
            await query.message.reply_text("✅ Lesson bookmarked.")
        except sqlite3.IntegrityError:
            await query.message.reply_text("🔖 Already bookmarked.")
    elif data.startswith("unbookmark:"):
        lesson_id = int(data.split(":")[1])
        user_id = query.from_user.id
        cur.execute("DELETE FROM bookmarks WHERE user_id=? AND lesson_id=?", (user_id, lesson_id))
        conn.commit()
        await query.message.reply_text("❌ Lesson unbookmarked.")


# ===== Channel Post Handler =====
async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return
    if CHANNEL_ID and msg.chat.id != CHANNEL_ID:
        return

    text = (msg.text or msg.caption or "").strip()
    if text and REQUIRED_HASHTAG in text:
        # Telegram channel message date is typically UTC; store ISO (with tz) and convert when reading.
        save_lesson(
            text=text,
            source="channel",
            channel_id=msg.chat.id,
            message_id=msg.message_id,
            created_at=msg.date.isoformat(),
        )
        log.info("Saved lesson from channel")


# ===== Main =====
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("latest", latest))
    app.add_handler(CommandHandler("previous", previous))
    app.add_handler(CommandHandler("searchdate", search_date))
    app.add_handler(CommandHandler("mybookmarks", my_bookmarks))
    app.add_handler(CommandHandler("bookmark", bookmark_cmd))
    app.add_handler(CommandHandler("unbookmark", unbookmark_cmd))

    # Reply-keyboard button presses (non-commands)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_menu_buttons))

    # Channel posts (ingest lessons)
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, on_channel_post))

    # Inline callbacks (prev/next/bookmark)
    app.add_handler(CallbackQueryHandler(on_callback_query))

    log.info("🚀 Lesson of the Day Bot running...")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
