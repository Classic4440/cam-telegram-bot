"""AI-powered translation and lightweight hosted image/weather commands."""
from __future__ import annotations

import asyncio
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.errors import AIUnavailable
from bot.formatting import markdown_to_html, reply_ai
from bot.registry import command, command_summary
from bot.state import get_state

logger = logging.getLogger(__name__)
_WEATHER_FORMAT = "%l:+%c+%t+(feels+like+%f),+humidity+%h,+wind+%w"


@command("image", description="Generate an image from a text prompt", category="AI", usage="/image <prompt>")
async def image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    prompt = " ".join(context.args).strip()
    if not prompt:
        await reply_ai(message, "Usage: /image <description of the image>")
        return
    if len(prompt) > 1000:
        await reply_ai(message, "Please keep image prompts under 1,000 characters.")
        return

    image_url = f"https://image.pollinations.ai/prompt/{quote(prompt, safe='')}?width=1024&height=1024&nologo=true"
    try:
        await message.reply_photo(
            photo=image_url,
            caption=markdown_to_html(f"Image prompt: {prompt[:900]}"),
            parse_mode="HTML",
        )
    except TelegramError:
        logger.exception("Telegram could not send the generated image")
        await reply_ai(message, "I couldn't send that image. Please try another prompt.")


def _fetch_weather(city: str) -> str:
    url = f"https://wttr.in/{quote(city, safe='')}?format={_WEATHER_FORMAT}"
    request = Request(url, headers={"User-Agent": "cam-telegram-bot/1.0"})
    with urlopen(request, timeout=10) as response:
        body = response.read(4000).decode("utf-8", errors="replace").strip()
    if not body or body.startswith("ERROR"):
        raise ValueError("Weather service returned no forecast for that location.")
    return body


@command("weather", description="Get current weather from wttr.in", category="Info", usage="/weather <city>")
async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    city = " ".join(context.args).strip()
    if not city:
        await reply_ai(message, "Usage: /weather <city>\nExample: /weather Kampala")
        return
    try:
        forecast = await asyncio.to_thread(_fetch_weather, city)
    except (HTTPError, URLError, TimeoutError, UnicodeError, ValueError) as exc:
        logger.warning("Weather lookup failed for requested location: %s", type(exc).__name__)
        await reply_ai(message, "I couldn't get the weather right now. Check the city name and try again.")
        return
    await reply_ai(message, forecast)


@command("translate", description="Translate text using AI", category="AI", usage="/translate <language> <text>")
async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if len(context.args) < 2:
        await reply_ai(message, "Usage: /translate <language> <text>\nExample: /translate French Good morning")
        return

    language = context.args[0].strip()
    text = " ".join(context.args[1:]).strip()
    if len(language) > 60 or not text:
        await reply_ai(message, "Usage: /translate <language> <text>")
        return
    state = get_state(context)
    try:
        result = await state.ai.task(
            f"Translate the user's text into {language}. Return only the translation.",
            text,
            user_id=user.id,
            commands=command_summary(),
        )
    except AIUnavailable:
        logger.warning("AI translation service is unavailable")
        await reply_ai(message, "Translation is unavailable right now. Please try again shortly.")
        return
    await reply_ai(message, result)
