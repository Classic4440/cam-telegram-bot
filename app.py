import logging
import os
from threading import Thread

from flask import Flask
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


@web_app.get("/health")
def health_check():
    """Simple health endpoint for services like UptimeRobot."""
    return "Bot is running", 200


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to the /start command."""
    await update.message.reply_text("Hello! I am your bot. I am working!")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo any text message sent by the user."""
    text = update.message.text or ""
    await update.message.reply_text(f"You said: {text}")


def run_web_server() -> None:
    """Run Flask in a separate thread so Render can keep the service alive."""
    port = int(os.environ.get("PORT", "10000"))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)


def main() -> None:
    """Load the Telegram token, start keepalive web server, and begin polling."""
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Set the TELEGRAM_TOKEN environment variable.")

    # Render assigns a port dynamically; Flask should listen on it.
    Thread(target=run_web_server, daemon=True).start()

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.run_polling()


if __name__ == "__main__":
    main()