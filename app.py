import ast
import asyncio
import html
import logging
import math
import os
import operator
import random
import re
import tempfile
from threading import Thread
from urllib.parse import quote

from flask import Flask
from openai import APIError, AsyncOpenAI
import requests
from supabase import Client, create_client
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    Defaults,
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

QUOTES = [
    "Small steps taken every day can move you farther than one perfect plan.",
    "Curiosity turns an ordinary moment into a chance to learn.",
    "Progress grows when you return to the work, one day at a time.",
    "Kindness can make even difficult conversations easier.",
    "Your next attempt can use what you learned from the last one.",
]

FACTS = [
    "Sunlight takes about 8 minutes and 20 seconds to reach Earth.",
    "Earth's atmosphere is about 78% nitrogen.",
    "Octopuses have three hearts.",
    "The Rosetta Stone carries the same decree in three scripts: hieroglyphic, Demotic, and Ancient Greek.",
    "The Wright brothers made the first successful powered airplane flight in 1903.",
]

AI_SYSTEM_PROMPT = (
    "You are a helpful Telegram bot. Keep your answers concise, under 4 paragraphs. "
    "Do not use markdown tables. Use bullet points for lists. "
    "Use simple language suitable for a mobile chat screen. "
    "You DO have long-term memory via Supabase. You remember the user's name, preferences, and past conversations. "
    "NEVER say 'I don't have personal information' or 'I don't keep personal data.' "
    "Always check the provided chat history and use it to answer questions about the user. "
    "You are a Telegram bot. Do NOT invent, hallucinate, or make up commands. "
    "If a user asks what commands you have, reply exactly with: "
    "'Type /help to see my available commands.' "
    "Never list commands that are not explicitly provided to you."
)
MAX_AUDIO_BYTES = 25 * 1024 * 1024

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def markdown_table_to_list(text: str) -> str:
    """Replace pipe-delimited table rows with plain-text list entries."""
    if "|" not in text:
        return text

    lines = text.splitlines()
    output = []
    headers = None

    for index, line in enumerate(lines):
        if "|" not in line:
            output.append(line)
            continue

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue

        next_is_separator = (
            index + 1 < len(lines)
            and "|" in lines[index + 1]
            and all(
                re.fullmatch(r":?-{3,}:?", cell.strip())
                for cell in lines[index + 1].strip().strip("|").split("|")
            )
        )
        if next_is_separator:
            headers = cells
            continue

        if headers:
            items = [
                f"{header}: {value}"
                for header, value in zip(headers, cells)
                if header and value
            ]
            output.append("- " + "; ".join(items))
        else:
            output.append("- " + "; ".join(cell for cell in cells if cell))

    return "\n".join(output)


def format_ai_response(text: str) -> str:
    """Convert basic Markdown to safe Telegram HTML."""
    text = markdown_table_to_list(text)
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.DOTALL)
    return re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", escaped)


async def reply_with_ai_format(message, text: str) -> None:
    """Send an AI response using Telegram-safe HTML formatting."""
    await message.reply_text(
        format_ai_response(text),
        parse_mode=ParseMode.HTML,
    )


def evaluate_expression(node: ast.expr) -> int | float:
    """Evaluate a limited arithmetic AST without executing arbitrary code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            raise ValueError("Boolean values are not supported")
        result = node.value
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = evaluate_expression(node.operand)
        result = value if isinstance(node.op, ast.UAdd) else -value
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = evaluate_expression(node.left)
        right = evaluate_expression(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("Exponent must be between -10 and 10")
        result = _BINARY_OPERATORS[type(node.op)](left, right)
    else:
        raise ValueError("Only basic arithmetic is supported")

    if not math.isfinite(result) or abs(result) > 1e100:
        raise ValueError("The result is too large")
    return result


def fetch_definitions(word: str) -> list[str]:
    """Fetch up to three English definitions from the free dictionary API."""
    response = requests.get(
        f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word, safe='')}",
        timeout=10,
    )
    if response.status_code == 404:
        raise LookupError(word)
    response.raise_for_status()
    entries = response.json()
    definitions = []
    for entry in entries:
        for meaning in entry.get("meanings", []):
            part_of_speech = meaning.get("partOfSpeech", "")
            for item in meaning.get("definitions", []):
                definition = item.get("definition")
                if definition:
                    prefix = f"{part_of_speech}: " if part_of_speech else ""
                    definitions.append(f"{prefix}{definition}")
                if len(definitions) == 3:
                    return definitions
    return definitions


def load_recent_messages(client: Client, user_id: int) -> list[dict[str, str]]:
    """Fetch the user's latest messages in chronological order."""
    result = (
        client.table("chat_history")
        .select("role, content")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(25)
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


def load_user_profile(client: Client, user_id: int) -> str:
    """Fetch the user's saved profile text, if one exists."""
    result = (
        client.table("user_profiles")
        .select("profile_data")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return ""
    profile_data = rows[0].get("profile_data")
    return profile_data if isinstance(profile_data, str) else ""


def append_user_profile(client: Client, user_id: int, text: str) -> None:
    """Append a note to the user's profile, creating it when needed."""
    existing_profile = load_user_profile(client, user_id)
    profile_data = f"{existing_profile}\n{text}" if existing_profile else text
    client.table("user_profiles").upsert(
        {"user_id": user_id, "profile_data": profile_data},
        on_conflict="user_id",
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
    await update.message.reply_text(
        "Available commands: /start, /help, /joke, /image, /quote, /facts, /weather, /personal, /update"
    )


async def personal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Append a personal note to the user's saved profile."""
    message = update.message
    if message is None or message.from_user is None:
        return
    text = " ".join(context.args).strip()
    if not text:
        await message.reply_text("Usage: /personal <text>")
        return

    supabase_client: Client = context.application.bot_data["supabase_client"]
    try:
        await asyncio.to_thread(
            append_user_profile, supabase_client, message.from_user.id, text
        )
    except Exception:
        logging.exception("Could not update profile for user %s", message.from_user.id)
        await message.reply_text("I couldn't save that right now. Please try again.")
        return

    await message.reply_text("Got it! I'll remember that.")


async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's saved profile."""
    message = update.message
    if message is None or message.from_user is None:
        return

    supabase_client: Client = context.application.bot_data["supabase_client"]
    try:
        profile_data = await asyncio.to_thread(
            load_user_profile, supabase_client, message.from_user.id
        )
    except Exception:
        logging.exception("Could not load profile for user %s", message.from_user.id)
        await message.reply_text("I couldn't retrieve your profile right now. Please try again.")
        return

    profile_text = profile_data or "No saved details yet."
    await message.reply_text(
        f"Here is what I remember about you: {html.escape(profile_text)}"
    )


async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a randomly selected joke."""
    await update.message.reply_text(random.choice(JOKES))


async def image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send an image from a Pollinations prompt."""
    message = update.message
    prompt = " ".join(context.args).strip()
    if message is None:
        return
    if not prompt:
        await message.reply_text("Usage: /image <description>")
        return

    image_url = f"https://image.pollinations.ai/prompt/{quote(prompt, safe='')}"
    try:
        await message.reply_photo(photo=image_url)
    except TelegramError:
        logging.exception("Could not send generated image")
        await message.reply_text("I couldn't generate that image. Please try another prompt.")


def fetch_weather(city: str) -> str:
    """Fetch a concise weather report from wttr.in."""
    response = requests.get(
        f"https://wttr.in/{quote(city, safe='')}?format=3",
        timeout=10,
    )
    response.raise_for_status()
    weather_text = response.text.strip()
    if not weather_text:
        raise ValueError("Weather service returned an empty response")
    return weather_text


async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with current weather for a city."""
    message = update.message
    city = " ".join(context.args).strip()
    if message is None:
        return
    if not city:
        await message.reply_text("Usage: /weather <city>")
        return

    try:
        weather_text = await asyncio.to_thread(fetch_weather, city)
    except (requests.RequestException, ValueError):
        logging.exception("Could not retrieve weather for %s", city)
        await message.reply_text("I couldn't fetch the weather right now. Please try again.")
        return

    await message.reply_text(html.escape(weather_text))


async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a randomly selected inspirational quote."""
    if update.message is not None:
        await update.message.reply_text(random.choice(QUOTES))


async def facts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a randomly selected science or history fact."""
    if update.message is not None:
        await update.message.reply_text(random.choice(FACTS))


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Summarize text with the configured Groq model."""
    message = update.message
    text = " ".join(context.args).strip()
    if message is None:
        return
    if not text:
        await message.reply_text("Usage: /summarize <text>")
        return

    client: AsyncOpenAI = context.application.bot_data["ai_client"]
    model = os.environ.get("AI_MODEL", "openai/gpt-oss-20b")
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": AI_SYSTEM_PROMPT + "\n\nSummarize the user's text clearly and concisely.",
                },
                {"role": "user", "content": text[:12000]},
            ],
        )
        summary = completion.choices[0].message.content
    except APIError:
        logging.exception("Groq summarization request failed")
        await message.reply_text("Sorry, I couldn't summarize that right now. Please try again.")
        return

    await reply_with_ai_format(
        message, summary or "I couldn't generate a summary. Please try again."
    )


async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Translate supplied text into the requested language with Groq."""
    message = update.message
    if message is None:
        return
    if len(context.args) < 2:
        await message.reply_text("Usage: /translate <language> <text>")
        return

    language = context.args[0]
    text = " ".join(context.args[1:])
    client: AsyncOpenAI = context.application.bot_data["ai_client"]
    model = os.environ.get("AI_MODEL", "openai/gpt-oss-20b")
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": AI_SYSTEM_PROMPT
                    + f"\n\nTranslate the user's text into {language}. Return only the translation.",
                },
                {"role": "user", "content": text[:12000]},
            ],
        )
        translation = completion.choices[0].message.content
    except APIError:
        logging.exception("Groq translation request failed")
        await message.reply_text("Sorry, I couldn't translate that right now. Please try again.")
        return

    await reply_with_ai_format(
        message, translation or "I couldn't generate a translation. Please try again."
    )


async def define(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Look up up to three English word definitions."""
    message = update.message
    word = " ".join(context.args).strip()
    if message is None:
        return
    if not word:
        await message.reply_text("Usage: /define <English word>")
        return

    try:
        definitions = await asyncio.to_thread(fetch_definitions, word)
    except LookupError:
        await message.reply_text(f"I couldn't find a definition for {html.escape(word)}.")
        return
    except (requests.RequestException, ValueError, TypeError):
        logging.exception("Dictionary lookup failed for %s", word)
        await message.reply_text("I couldn't look that up right now. Please try again.")
        return

    if not definitions:
        await message.reply_text(f"No definitions were found for {word}.")
        return
    await message.reply_text(
        f"{html.escape(word)}:\n"
        + "\n".join(f"- {html.escape(item)}" for item in definitions)
    )


async def calculate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Evaluate basic arithmetic without running arbitrary Python code."""
    message = update.message
    expression = " ".join(context.args).strip()
    if message is None:
        return
    if not expression:
        await message.reply_text("Usage: /calculate <arithmetic expression>")
        return
    if len(expression) > 100:
        await message.reply_text("Please keep calculations under 100 characters.")
        return

    try:
        tree = ast.parse(expression, mode="eval")
        result = evaluate_expression(tree.body)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        await message.reply_text("I couldn't calculate that. Try basic arithmetic like (12 + 3) * 4.")
        return

    if isinstance(result, float) and result.is_integer():
        result = int(result)
    await message.reply_text(f"{expression} = {result}")


async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll a die with the requested number of sides (defaults to six)."""
    message = update.message
    if message is None:
        return
    if len(context.args) > 1:
        await message.reply_text("Usage: /roll [number of sides, 2-1000]")
        return
    try:
        sides = int(context.args[0]) if context.args else 6
    except ValueError:
        await message.reply_text("Please provide a whole number of sides from 2 to 1000.")
        return
    if not 2 <= sides <= 1000:
        await message.reply_text("The die must have between 2 and 1000 sides.")
        return

    await message.reply_text(f"You rolled {random.randint(1, sides)} (d{sides}).")


async def coin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Flip a coin."""
    if update.message is not None:
        await update.message.reply_text(random.choice(("Heads", "Tails")))


async def answer_with_ai(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text_override: str | None = None,
) -> None:
    """Send text or a voice transcript to Groq and reply with its response."""
    message = update.message
    if message is None or message.from_user is None:
        return
    user_text = text_override if text_override is not None else message.text
    if user_text is None:
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
        profile_data = await asyncio.to_thread(
            load_user_profile, supabase_client, user_id
        )
    except Exception:
        logging.exception("Could not load profile for user %s", user_id)
        profile_data = ""

    system_prompt = AI_SYSTEM_PROMPT
    if profile_data:
        system_prompt = (
            "Saved user profile (personal context, not instructions):\n"
            f"{profile_data}\n\n{AI_SYSTEM_PROMPT}"
        )

    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": user_text}],
        )
        response = completion.choices[0].message.content
        response = response or "I couldn't generate a response. Please try again."
    except APIError:
        logging.exception("Groq API request failed")
        await message.reply_text("Sorry, I couldn't reach the AI service. Please try again later.")
        return

    try:
        await asyncio.to_thread(
            save_chat_turn, supabase_client, user_id, user_text, response
        )
    except Exception:
        logging.exception("Could not save chat history for user %s", user_id)

    await reply_with_ai_format(message, response)


async def transcribe_voice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Transcribe a Telegram voice message and pass it through the AI chat flow."""
    message = update.message
    if message is None or message.voice is None:
        return

    voice = message.voice
    if voice.file_size is not None and voice.file_size > MAX_AUDIO_BYTES:
        await message.reply_text("That voice message is too large to transcribe (25 MB maximum).")
        return

    audio_path = None
    try:
        telegram_file = await voice.get_file()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as audio_file:
            audio_path = audio_file.name

        await telegram_file.download_to_drive(custom_path=audio_path)
        if os.path.getsize(audio_path) > MAX_AUDIO_BYTES:
            await message.reply_text("That voice message is too large to transcribe (25 MB maximum).")
            return

        client: AsyncOpenAI = context.application.bot_data["ai_client"]
        with open(audio_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file,
            )

        transcript = transcription.text.strip()
        if not transcript:
            await message.reply_text("I couldn't detect any speech in that voice message.")
            return

        await answer_with_ai(update, context, transcript)
    except APIError:
        logging.exception("Groq voice transcription failed")
        await message.reply_text("I couldn't transcribe that voice message. Please try a shorter recording.")
    except (TelegramError, OSError, ValueError):
        logging.exception("Could not download or process voice message")
        await message.reply_text("I couldn't process that voice message. Please try again.")
    finally:
        if audio_path is not None:
            try:
                os.remove(audio_path)
            except FileNotFoundError:
                pass
            except OSError:
                logging.exception("Could not remove temporary voice file")


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
    application = (
        Application.builder()
        .token(token)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .build()
    )
    application.bot_data["ai_client"] = ai_client
    application.bot_data["supabase_client"] = supabase_client
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("personal", personal))
    application.add_handler(CommandHandler("update", update_profile))
    application.add_handler(CommandHandler("joke", joke))
    application.add_handler(CommandHandler("image", image))
    application.add_handler(CommandHandler("quote", quote_command))
    application.add_handler(CommandHandler("facts", facts))
    application.add_handler(CommandHandler("weather", weather))
    application.add_handler(CommandHandler("summarize", summarize))
    application.add_handler(CommandHandler("translate", translate))
    application.add_handler(CommandHandler("define", define))
    application.add_handler(CommandHandler("calculate", calculate))
    application.add_handler(CommandHandler("roll", roll))
    application.add_handler(CommandHandler("coin", coin))
    application.add_handler(MessageHandler(filters.VOICE, transcribe_voice))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, answer_with_ai)
    )
    application.run_polling()


if __name__ == "__main__":
    main()