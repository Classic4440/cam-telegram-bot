import asyncio
import logging
import os
import random
from threading import Thread

from flask import Flask
from openai import APIError, AsyncOpenAI
from supabase import Client, create_client
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Basic logging setup for debugging and monitoring in a hosted environment.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Create a lightweight Flask app for health checks and keepalive pings.
web_app = Flask(__name__)

JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs!",
    "Why was the computer cold? It left its Windows open!",
    "Why did the developer go broke? Because they used up all their cache!",
]


def load_recent_messages(client: Client, user_id: int) -> list[dict[str, str]]:
    """Fetch the user's latest messages in chronological order."""
    result = (
        client.table("chat_history")
        .select("role, content")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    rows = result.data or []
    return [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
        if row.get("role") in {"user", "assistant"}
        and isinstance(row.get("content"), str)
    ]


def save_chat_turn(client: Client, user_id: int, user_text: str, reply: str) -> None:
    """Persist both sides of a completed conversation turn."""
    client.table("chat_history").insert(
        [
            {"user_id": user_id, "role": "user", "content": user_text},
            {"user_id": user_id, "role": "assistant", "content": reply},
        ]
    ).execute()


@web_app.get("/health")
def health_check():
    """Simple health endpoint for services like UptimeRobot."""
    return "Bot is running", 200


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to the /start command."""
    await update.message.reply_text("Hello! I am your bot. I am working!")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List the bot's available commands."""
    await update.message.reply_text("Here is what I can do: /start, /help, /joke")


async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a randomly selected joke."""
    await update.message.reply_text(random.choice(JOKES))


async def answer_with_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the user's text to Groq and reply with the model's response."""
    message = update.message
    if message is None or message.text is None:
        return

    client: AsyncOpenAI = context.application.bot_data["ai_client"]
    supabase_client: Client = context.application.bot_data["supabase_client"]
    model = os.environ.get("AI_MODEL", "openai/gpt-oss-20b")
    user_id = message.from_user.id

    try:
        history = await asyncio.to_thread(load_recent_messages, supabase_client, user_id)
    except Exception:
        logging.exception("Could not load chat history for user %s", user_id)
        history = []

    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=history + [{"role": "user", "content": message.text}],
        )
        response = completion.choices[0].message.content
        response = response or "I couldn't generate a response. Please try again."
    except APIError:
        logging.exception("Groq API request failed")
        await message.reply_text("Sorry, I couldn't reach the AI service. Please try again later.")
        return

    try:
        await asyncio.to_thread(
            save_chat_turn, supabase_client, user_id, message.text, response
        )
    except Exception:
        logging.exception("Could not save chat history for user %s", user_id)

    await message.reply_text(response)


def run_web_server() -> None:
    """Run Flask in a separate thread so Render can keep the service alive."""
    port = int(os.environ.get("PORT", "10000"))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)


def main() -> None:
    """Load the Telegram token, start keepalive web server, and begin polling."""
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Set the TELEGRAM_TOKEN environment variable.")

    ai_api_key = os.environ.get("AI_API_KEY")
    if not ai_api_key:
        raise RuntimeError("Set the AI_API_KEY environment variable.")

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Set the SUPABASE_URL and SUPABASE_KEY environment variables.")

    # Render assigns a port dynamically; Flask should listen on it.
    Thread(target=run_web_server, daemon=True).start()

    ai_client = AsyncOpenAI(
        api_key=ai_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    supabase_client = create_client(supabase_url, supabase_key)
    application = Application.builder().token(token).build()
    application.bot_data["ai_client"] = ai_client
    application.bot_data["supabase_client"] = supabase_client
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("joke", joke))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, answer_with_ai)
    )
    application.run_polling()


if __name__ == "__main__":
    main()