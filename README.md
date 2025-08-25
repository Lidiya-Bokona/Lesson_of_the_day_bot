# Lesson of the Day Bot 🤖

A Telegram bot that delivers daily lessons, lets users browse past lessons, bookmark favorites, and search lessons by date. Deployed on PythonAnywhere for 24/7 access.

## 🔎 Features

- 📘 **Show today’s lesson instantly** – Get the lesson for today at a click.  
- 🕰 **Browse past lessons** – Explore previous lessons easily.  
- 🔖 **Bookmark lessons** – Save lessons you like and revisit them anytime.  
- 📅 **Search by date** – Look up lessons from any specific date.  

---

## 👉 Use the Bot

Start using the bot on Telegram: [@lesson_of_day_bot](https://t.me/lesson_of_day_bot)

---

## 💻 Deployment

- Built with **Python 3.13** and **python-telegram-bot v20+**  
- Hosted on **PythonAnywhere** for 24/7 uptime  
- Uses **SQLite** database for storing lessons and bookmarks  
- Environment variables: `BOT_TOKEN` and `CHANNEL_ID`  

---

## ⚙️ Installation (Development)

1. Clone the repo:  
git clone https://github.com/lidiya-bokona/lesson-of-the-day-bot.git
cd lesson-of-the-day-bot

2. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```
3. Install dependencies
```bash
pip install -r requirements.txt
```
4. Add your environment variables in a .env file:
```bash
BOT_TOKEN=your_telegram_bot_token
CHANNEL_ID=your_channel_id
```
6. Run the bot
```bash
python bot.py

