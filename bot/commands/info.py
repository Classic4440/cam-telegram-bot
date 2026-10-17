"""Info commands: /start, /help."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import safe_reply
from bot.registry import register

logger = logging.getLogger(__name__)


@register("start")
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command."""
    response = """👋 **Welcome to Telegram Bot!**

This is the largest, most capable Telegram bot ever built with:
• 🎮 **Games**: dice, tic-tac-toe, hangman, blackjack
• 🔢 **Math**: safe calc, primes, factorization, equation solver
• 🎵 **Music**: scales, chords, transposition, tempo
• 🔤 **Text**: codecs, morse, ROT13, base64, ciphers
• 📸 **Media**: image OCR, audio transcription, voice notes
• 🤖 **AI**: 12 personas, intent routing, smart responses
• ⏰ **Utilities**: reminders, time parsing, unit conversion

Type /help for full command list.
"""
    await safe_reply(update, response)


@register("help")
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command."""
    response = """**Command List**

**Games:**
/dice [expr] - Roll dice (2d6+3, d20, etc)
/tictactoe - Play tic-tac-toe vs AI
/hangman - Start hangman; guess with /guess [letter] or send a letter
/guess [letter] - Guess a letter in your hangman game
/blackjack - Play blackjack

**Math & Logic:**
/math [expr] - Safe calculator (sqrt, sin, log, etc)
/prime [n] - Check if prime or factorize
/logic [expr] - Truth tables (a & b | !c, etc)
/solve [eq] - Solve linear/quadratic equations

**Utilities:**
/units [conv] - Convert units (10 km to mi, 72 f to c)
/music [mode] - Music theory (scales, chords)
/time [when] - Parse time (in 2h, tomorrow 9am, etc)
/remind [when] [msg] - Set reminder
/convert [base] - Base converter (2 to 16, etc)
/translate [text] - Translate text

**Media:**
Send photo - OCR text extraction
Send audio - Audio transcription
Send voice - Voice message transcription + TTS reply

**Info:**
/start - This message
/help - Commands (this message)
/version - Bot version and release notes
/stats - Bot statistics
/admin - Admin panel

**Examples:**
/dice 2d6+3
/math sqrt(16) + 2*pi
/units 10 km to miles
/remind 30m drink water
"""
    await safe_reply(update, response)
