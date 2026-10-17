"""Tool commands: math, logic, units, music, etc."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import code_block, safe_reply
from bot.registry import register
from bot.services.logic import LogicError
from bot.services.mathx import CalcError, evaluate, solve
from bot.services.music import MusicError, parse_chord, scale_notes
from bot.services.numbers import NumberError, factorize, is_prime
from bot.services.textcodec import CodecError, rot13
from bot.services.units import UnitError, parse_and_convert

logger = logging.getLogger(__name__)


async def cmd_math(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Safe calculator."""
    expr = " ".join(context.args) if context.args else None
    if not expr:
        await safe_reply(update, "Usage: /math [expression]\nExample: /math sqrt(16) + 2*pi")
        return

    try:
        result = evaluate(expr)
        await safe_reply(update, f"🔢 **{expr}** = **{result}**")
    except CalcError as e:
        await safe_reply(update, f"❌ {e}")


async def cmd_prime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prime checker and factorizer."""
    if not context.args:
        await safe_reply(update, "Usage: /prime [number]\nExample: /prime 100")
        return

    try:
        n = int(context.args[0])
        if is_prime(n):
            await safe_reply(update, f"✅ **{n}** is prime!")
        else:
            factors = factorize(n)
            response = f"🔢 **{n}** = " + " × ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in factors.items())
            await safe_reply(update, response)
    except (NumberError, ValueError) as e:
        await safe_reply(update, f"❌ {e}")


@register("logic")
async def cmd_logic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Propositional logic solver."""
    expr = " ".join(context.args) if context.args else None
    if not expr:
        await safe_reply(update, "Usage: /logic [expression]\nExample: /logic (a & b) | !c")
        return

    try:
        from bot.services.logic import truth_table, render
        table = truth_table(expr)
        response = f"**{expr}**\n\n{code_block(render(table))}\nClassification: **{table.classification}**"
        await safe_reply(update, response)
    except LogicError as e:
        await safe_reply(update, f"❌ {e}")


@register("units")
async def cmd_units(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unit converter."""
    text = " ".join(context.args) if context.args else None
    if not text:
        await safe_reply(update, "Usage: /units 10 km to mi\nExample: /units 72 f to c")
        return

    try:
        conv = parse_and_convert(text)
        response = f"📏 **{conv.value} {conv.src}** = **{conv.result:.4f} {conv.dst}**"
        await safe_reply(update, response)
    except UnitError as e:
        await safe_reply(update, f"❌ {e}")


async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Music theory helper."""
    if not context.args:
        await safe_reply(update, "Usage: /music [chord] or /music [note] [scale]\nExample: /music Cmaj7 or /music C major")
        return

    try:
        # Try as chord first
        try:
            chord = parse_chord(context.args[0])
            response = f"🎵 **{chord.name}**: {', '.join(chord.notes)}"
        except:
            # Try as scale
            root = context.args[0]
            scale = context.args[1] if len(context.args) > 1 else "major"
            notes = scale_notes(root, scale)
            response = f"🎵 **{root} {scale}**: {' - '.join(notes)}"

        await safe_reply(update, response)
    except Exception as e:
        await safe_reply(update, f"❌ {e}")


async def cmd_translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Translate text (placeholder)."""
    text = " ".join(context.args) if context.args else None
    if not text:
        await safe_reply(update, "Usage: /translate [text]\nExample: /translate hello world")
        return

    # Placeholder - implement with translation API
    await safe_reply(update, f"🌐 Translation coming soon for: {text}")


@register("convert")
async def cmd_convert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Number base converter."""
    if len(context.args) < 3:
        await safe_reply(update, "Usage: /convert [value] from [base] to [base]\nExample: /convert 255 from 10 to 16")
        return

    try:
        from bot.services.numbers import convert_base
        value, from_base, to_base = context.args[0], int(context.args[1]), int(context.args[2])
        result = convert_base(value, from_base, to_base)
        response = f"🔢 **{value}** (base {from_base}) = **{result}** (base {to_base})"
        await safe_reply(update, response)
    except (NumberError, ValueError) as e:
        await safe_reply(update, f"❌ {e}")
