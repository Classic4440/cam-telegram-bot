"""Main Telegram bot application entry point."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
from contextlib import suppress
from pathlib import Path

from flask import Flask
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from bot.ai import AIService
from bot.config import Settings
from bot.content import ContentLibrary
from bot.errors import AIUnavailable
from bot.formatting import reply_ai
from bot.logging_setup import setup_logging
from bot.registry import build_handlers, command_summary, discover
from bot.security import TokenBucketLimiter, sanitize_text
from bot.state import AppState
from bot.store import build_store

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
            history = await state.store.load_history(
                user.id, state.settings.history_messages
            )
            result = await state.ai.chat(
                text,
                history=history,
                user_id=user.id,
                commands=command_summary(),
            )
            await state.store.save_turn(user.id, text, result.text)
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
    store = build_store(settings.supabase_url, settings.supabase_key)
    app_state = AppState(
        settings=settings,
        store=store,
        ai=AIService(settings, profile_loader=store.get_user_profile),
        content=ContentLibrary(),
        limiter=TokenBucketLimiter(
            settings.rate_capacity, settings.rate_refill_seconds
        ),
    )
    application = (
        Application.builder()
        .token(settings.telegram_token)
        .concurrent_updates(settings.concurrent_updates)
        .build()
    )
    application.bot_data["state"] = app_state
    application.bot_data["store"] = store
    application.bot_data["config"] = settings

    commands_dir = Path(__file__).resolve().parent / "bot" / "commands"
    command_modules = (
        [
            path
            for path in commands_dir.glob("*.py")
            if not path.name.startswith("_")
        ]
        if commands_dir.is_dir()
        else []
    )
    if command_modules:
        loaded = discover()
        logger.info("Discovered command modules: %s", ", ".join(loaded))
    else:
        logger.info("No command modules found")

    application.add_handlers(build_handlers())
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message)
    )
    return application


def run_health_server() -> None:
    port = int(os.environ.get("PORT", "10000"))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)


async def main() -> None:
    setup_logging()
    try:
        settings = Settings.from_env()
    except RuntimeError as exc:
        logger.critical("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    logger.info("=== Telegram Bot Starting ===")
    application = create_application(settings)
    threading.Thread(
        target=run_health_server,
        name="health-server",
        daemon=True,
    ).start()

    loop = asyncio.get_running_loop()
    shutdown_requested = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, shutdown_requested.set)

    async with application:
        await application.start()
        if application.updater is None:
            raise RuntimeError("Telegram Application has no updater")
        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES
        )
        logger.info("Bot is running")
        await shutdown_requested.wait()

        logger.info("Shutdown requested")
        if application.updater.running:
            await application.updater.stop()
        if application.running:
            await application.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception:
        logger.exception("Fatal application error")
        sys.exit(1)
