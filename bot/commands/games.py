"""Game commands."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import code_block, safe_reply
from bot.registry import register
from bot.services.dice import DiceError, roll
from bot.services.gamelogic import Blackjack, Hangman, ttt_best_move, ttt_winner

logger = logging.getLogger(__name__)


@register("dice")
async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Roll dice with notation."""
    expr = " ".join(context.args) if context.args else "d20"
    try:
        result = roll(expr)
        response = f"""🎲 **{result.expression}**

Total: **{result.total}**
Range: {result.min_possible} - {result.max_possible}

{code_block(result.detail)}"""
        await safe_reply(update, response)
    except DiceError as e:
        await safe_reply(update, f"❌ {e}")


@register("tictactoe")
async def cmd_tictactoe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Play tic-tac-toe."""
    # Placeholder - full implementation would need game state in context
    board = [""] * 9
    board[4] = "X"  # Player plays center

    ai_move = ttt_best_move(board, "O", "impossible")
    board[ai_move] = "O"

    display = "\n".join([
        f"{board[0] or '1'} | {board[1] or '2'} | {board[2] or '3'}",
        "---------",
        f"{board[3] or '4'} | {board[4] or '5'} | {board[5] or '6'}",
        "---------",
        f"{board[6] or '7'} | {board[7] or '8'} | {board[8] or '9'}",
    ])

    response = f"""🎮 **Tic-Tac-Toe**

{code_block(display)}

Your move: Reply with 1-9"""
    await safe_reply(update, response)


@register("hangman")
async def cmd_hangman(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Play hangman."""
    game = Hangman("python")

    response = f"""🎮 **Hangman**

Word: {game.masked}
Wrong: {", ".join(game.wrong) or "none"}

{code_block(game.render())}

Guess a letter: /guess [letter]"""
    await safe_reply(update, response)


@register("blackjack")
async def cmd_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Play blackjack."""
    game = Blackjack.new()

    player_val = sum(int(c[:-1]) if c[:-1] != "A" else 11 for c in game.player)
    dealer_val = sum(int(c[:-1]) if c[:-1] != "A" else 11 for c in game.dealer[:1])

    response = f"""🃏 **Blackjack**

Your hand: {", ".join(game.player)} (value: {player_val})
Dealer shows: {game.dealer[0]}

/hit - Take another card
/stand - End turn"""
    await safe_reply(update, response)
