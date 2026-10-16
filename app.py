"""Flask health endpoint and Telegram bot entry point."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from flask import Flask
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from bot.ai import AIService
from bot.config import Settings
from bot.content import ContentLibrary
from bot.errors import AIUnavailable
from bot.formatting import reply_ai
from bot.registry import build_handlers, command_summary, discover
from bot.security import TokenBucketLimiter, sanitize_text
from bot.state import AppState
from bot.store import Store

logger = logging.getLogger(__name__)
web_app = Flask(__name__)


@web_app.get("/health")
def health_check() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


async def handle_ai_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.text:
        return

    state: AppState = context.application.bot_data["state"]
    text = sanitize_text(message.text, state.settings.max_input_chars)
    if not text:
        return

    state.stats.messages += 1
    state.stats.ai_chats += 1
    try:
        async with state.user_lock(user.id):
            result = await state.ai.chat(
                text,
                history=[],
                commands=command_summary(),
            )
        await reply_ai(message, result.text)
    except AIUnavailable:
        logger.exception("AI service is unavailable")
        await message.reply_text(
            "The AI service is unavailable right now. Please try again shortly."
        )
    except Exception:
        state.stats.errors += 1
        logger.exception("Could not handle an AI message")
        await message.reply_text("Something went wrong. Please try again.")


def create_application(settings: Settings) -> Application:
    application = (
        Application.builder()
        .token(settings.telegram_token)
        .concurrent_updates(settings.concurrent_updates)
        .build()
    )
    application.bot_data["state"] = AppState(
        settings=settings,
        store=Store(),
        ai=AIService(settings),
        content=ContentLibrary(),
        limiter=TokenBucketLimiter(
            settings.rate_capacity, settings.rate_refill_seconds
        ),
    )

    commands_dir = Path(__file__).resolve().parent / "bot" / "commands"
    command_modules = (
        [path for path in commands_dir.glob("*.py") if not path.name.startswith("_")]
        if commands_dir.is_dir()
        else []
    )
    if command_modules:
        try:
            loaded = discover()
        except ModuleNotFoundError as exc:
            if exc.name and (
                exc.name == "bot.commands" or exc.name.startswith("bot.services")
            ):
                logger.warning("Skipping unavailable optional bot module %s", exc.name)
            else:
                raise
        else:
            logger.info("Discovered command modules: %s", ", ".join(loaded))
    else:
        logger.info("No command modules found; starting without registered commands")

    application.add_handlers(build_handlers())
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message)
    )
    return application


def run_telegram_bot(application: Application) -> None:
    application.run_polling(stop_signals=None)


def main() -> None:
    settings = Settings.from_env()
    application = create_application(settings)
    telegram_thread = threading.Thread(
        target=run_telegram_bot,
        args=(application,),
        name="telegram-bot",
        daemon=True,
    )
    telegram_thread.start()

    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
