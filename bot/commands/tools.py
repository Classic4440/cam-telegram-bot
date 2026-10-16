"""Unit, propositional-logic, time and text-encoding utilities."""
from __future__ import annotations

from datetime import timezone

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import format_number, reply_ai
from bot.registry import command
from bot.services import logic, textcodec, timeparse, units
from bot.state import get_state


@command("units", description="Convert between units", category="Tools", usage="/units <value> <unit> to <unit>")
async def units_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    text = " ".join(context.args).strip()
    if not text:
        await reply_ai(message, "Usage: /units <value> <unit> to <unit>\nExample: /units 10 km to mi")
        return
    try:
        result = units.parse_and_convert(text)
    except (units.UnitError, ValueError) as exc:
        await reply_ai(message, str(exc))
        return
    await reply_ai(
        message,
        f"{format_number(result.value)} {result.src} = **{format_number(result.result)} {result.dst}**",
    )


@command("logic", description="Evaluate a propositional logic expression", category="Logic", usage="/logic <expression>")
async def logic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    expression = " ".join(context.args).strip()
    if not expression:
        await reply_ai(message, "Usage: /logic <expression>\nExample: /logic (p and q) -> p")
        return
    try:
        table = logic.truth_table(expression)
    except logic.LogicError as exc:
        await reply_ai(message, f"Could not evaluate that: {exc}")
        return
    rendered = logic.render(table)
    await reply_ai(
        message,
        f"**{table.classification.title()}** — {table.true_count} of {len(table.rows)} rows are true.\n```text\n{rendered}\n```",
    )


@command("time", description="Parse a duration or natural-language time", category="Tools", usage="/time <duration or time phrase>")
async def time_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    phrase = " ".join(context.args).strip()
    if not phrase:
        await reply_ai(message, "Usage: /time <duration or time phrase>\nExamples: /time 2h30m, /time tomorrow 9am")
        return

    try:
        seconds = timeparse.parse_duration(phrase)
    except timeparse.TimeParseError:
        try:
            state = get_state(context)
            due, _ = timeparse.parse_reminder(
                f"{phrase} event", state.settings.default_timezone
            )
        except timeparse.TimeParseError:
            try:
                parsed = timeparse.parse_date(phrase)
            except timeparse.TimeParseError as exc:
                await reply_ai(message, str(exc))
                return
            rendered = parsed.replace(tzinfo=timezone.utc).isoformat()
            await reply_ai(message, f"Parsed date: **{rendered}** (UTC assumed).")
            return
        await reply_ai(message, f"That time is **{due.isoformat()}** (UTC).")
        return

    await reply_ai(message, f"That duration is **{timeparse.format_delta(seconds)}** ({format_number(seconds)} seconds).")


@command("encode", description="Encode text as ROT13, Base64 or Morse code", category="Tools", usage="/encode <rot13|base64|morse> <text>")
async def encode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    if len(context.args) < 2:
        await reply_ai(message, "Usage: /encode <rot13|base64|morse> <text>")
        return
    method = context.args[0].lower()
    text = " ".join(context.args[1:])
    encoders = {
        "rot13": textcodec.rot13,
        "base64": textcodec.b64_encode,
        "morse": textcodec.morse_encode,
    }
    encoder = encoders.get(method)
    if encoder is None:
        await reply_ai(message, "Choose an encoding: rot13, base64 or morse.")
        return
    try:
        result = encoder(text)
    except textcodec.CodecError as exc:
        await reply_ai(message, str(exc))
        return
    await reply_ai(message, f"**{method.upper()}**\n`{result}`")
