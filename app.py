"""Main Telegram bot application entry point."""
from __future__ import annotations

import asyncio
import logging
import signal
from threading import Thread

from flask import Flask
from telegram.ext import Application, JobQueue, MessageHandler, filters
from werkzeug.serving import BaseWSGIServer, make_server

from bot.ai import AIService
from bot.config import Settings
from bot.content import ContentLibrary
from bot.handlers import handle_audio, handle_image, handle_message, handle_voice
from bot.logging_setup import setup_logging
from bot.registry import REGISTRY, build_handlers, discover
from bot.security import TokenBucketLimiter
from bot.state import AppState
from bot.store import build_store

logger = logging.getLogger(__name__)
health_app = Flask(__name__)


@health_app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


async def main() -> None:
    """Load configuration and run the Telegram bot until shutdown."""
    setup_logging()
    settings = Settings.from_env()

    store = build_store(settings.supabase_url, settings.supabase_key)
    ai_service = AIService(settings, store=store)
    content_library = ContentLibrary()
    state = AppState(
        settings=settings,
        store=store,
        ai=ai_service,
        content=content_library,
        limiter=TokenBucketLimiter(settings.rate_capacity, settings.rate_refill_seconds),
    )

    discover()
    application = (
        Application.builder()
        .token(settings.telegram_token)
        .job_queue(JobQueue())
        .concurrent_updates(settings.concurrent_updates)
        .build()
    )
    if application.job_queue is None:
        raise RuntimeError("Telegram JobQueue is unavailable; install python-telegram-bot[job-queue].")
    application.bot_data.update(
        state=state,
        store=store,
        config=settings,
        ai_service=ai_service,
        content_lib=content_library,
    )

    for handler in build_handlers():
        application.add_handler(handler)
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    updater = application.updater
    if updater is None:
        raise RuntimeError("Telegram application has no updater configured")

    web_server: BaseWSGIServer = make_server("0.0.0.0", settings.port, health_app)
    web_thread = Thread(target=web_server.serve_forever, name="health-server", daemon=True)
    web_thread.start()

    logger.info("Telegram bot starting; registered %d commands", len(REGISTRY))
    try:
        async with application:
            await application.start()
            try:
                await updater.start_polling(
                    allowed_updates=["message", "edited_message", "channel_post"]
                )
                await stop_event.wait()
            finally:
                try:
                    if updater.running:
                        await updater.stop()
                finally:
                    if application.running:
                        await application.stop()
                    await store.flush_xp()
    finally:
        web_server.shutdown()
        web_thread.join(timeout=5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
