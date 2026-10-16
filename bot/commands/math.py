"""Math and number-theory commands."""
from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import format_number, reply_ai
from bot.registry import command
from bot.services import mathx, numbers


@command("math", description="Safely evaluate a math expression", category="Logic", usage="/math <expression>")
async def math_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    expression = " ".join(context.args).strip()
    if not expression:
        await reply_ai(message, "Usage: /math <expression>\nExample: /math sqrt(81) + 20% of 50")
        return
    try:
        result = mathx.evaluate(expression)
    except (mathx.CalcError, ArithmeticError, ValueError) as exc:
        await reply_ai(message, f"Could not calculate that: {exc}")
        return
    await reply_ai(message, f"{expression} = **{format_number(result)}**")


@command("prime", description="Check whether an integer is prime", category="Logic", usage="/prime <integer>")
async def prime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    value = " ".join(context.args).strip()
    if not re.fullmatch(r"[+-]?\d+", value):
        await reply_ai(message, "Usage: /prime <whole number>")
        return
    number = int(value)
    if abs(number) > numbers.MAX_PRIME_INPUT:
        await reply_ai(message, f"Please use an integer no larger than {numbers.MAX_PRIME_INPUT}.")
        return
    await reply_ai(message, f"{number} is {'prime' if numbers.is_prime(number) else 'not prime'}.")


@command("factor", description="Show the prime factorization of an integer", category="Logic", usage="/factor <integer>")
async def factor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    value = " ".join(context.args).strip()
    if not re.fullmatch(r"\+?\d+", value):
        await reply_ai(message, "Usage: /factor <integer greater than 1>")
        return
    try:
        factors = numbers.factorize(int(value))
    except numbers.NumberError as exc:
        await reply_ai(message, str(exc))
        return
    await reply_ai(message, f"Prime factors: **{numbers.format_factors(factors)}**")
