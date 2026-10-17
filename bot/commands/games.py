"""Game commands."""
from __future__ import annotations

import logging
import random

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import code_block, safe_reply
from bot.registry import register
from bot.services.dice import DiceError, roll
from bot.services.gamelogic import Blackjack, Hangman, ttt_best_move, ttt_winner

logger = logging.getLogger(__name__)

_TTT_KEY = "tictactoe"
_HANGMAN_KEY = "hangman"


def _render_ttt(board: list[str]) -> str:
    return "\n".join(
        (
            f"{board[0] or '1'} | {board[1] or '2'} | {board[2] or '3'}",
            "---------",
            f"{board[3] or '4'} | {board[4] or '5'} | {board[5] or '6'}",
            "---------",
            f"{board[6] or '7'} | {board[7] or '8'} | {board[8] or '9'}",
        )
    )


async def _ttt_move(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_data = context.user_data
    if user_data is None:
        await safe_reply(update, "Game state is unavailable. Please start a new game with /tictactoe.")
        return

    board = user_data.get(_TTT_KEY)
    if not isinstance(board, list) or len(board) != 9 or any(mark not in {"", "X", "O"} for mark in board):
        user_data.pop(_TTT_KEY, None)
        await safe_reply(update, "That game state is invalid. Please start a new game with /tictactoe.")
        return
    try:
        position = int(text.strip()) - 1
    except ValueError:
        position = -1
    if position not in range(9):
        await safe_reply(update, "Choose an empty square by replying with a number from 1 to 9.")
        return
    if board[position]:
        await safe_reply(update, "That square is already taken. Choose an empty square from 1 to 9.")
        return

    board[position] = "X"
    result = ttt_winner(board)
    if result is None:
        board[ttt_best_move(board, "O", "impossible")] = "O"
        result = ttt_winner(board)

    response = f"🎮 **Tic-Tac-Toe**\n\n{code_block(_render_ttt(board))}"
    if result:
        user_data.pop(_TTT_KEY, None)
        outcome = "It's a draw!" if result == "draw" else ("You win!" if result == "X" else "I win!")
        response += f"\n\n{outcome} Start another round with /tictactoe."
    else:
        response += "\n\nYour move: reply with an empty square number."
    await safe_reply(update, response)


async def _hangman_guess(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    letter: str,
) -> None:
    user_data = context.user_data
    if user_data is None:
        await safe_reply(update, "Game state is unavailable. Please start a new game with /hangman.")
        return
    game = user_data.get(_HANGMAN_KEY)
    if game is None:
        await safe_reply(update, "Start a game first with /hangman.")
        return

    result = game.guess(letter.strip())
    if result == "invalid":
        await safe_reply(update, "Guess one letter at a time with /guess [letter].")
        return
    if result == "repeat":
        await safe_reply(update, f"You already guessed {letter.lower()}. Try another letter.")
        return

    response = (
        f"🎮 **Hangman**\n\nWord: {game.masked}\n"
        f"Wrong: {', '.join(game.wrong) or 'none'}\n\n{code_block(game.render())}"
    )
    if game.over:
        user_data.pop(_HANGMAN_KEY, None)
        response += f"\n\n{'You won!' if game.won else f'Game over — the word was {game.word}.'} Start again with /hangman."
    else:
        response += "\n\nGuess another letter with /guess [letter] or send a single letter."
    await safe_reply(update, response)


async def handle_game_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> bool:
    """Handle a free-text move for an active user game."""
    user_data = getattr(context, "user_data", None)
    if user_data is None:
        return False
    if _TTT_KEY in user_data:
        await _ttt_move(update, context, text)
        return True
    letter = text.strip()
    if _HANGMAN_KEY in user_data and len(letter) == 1 and letter.isalpha():
        await _hangman_guess(update, context, letter)
        return True
    return False


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
    """Start tic-tac-toe against the bot."""
    if context.user_data is None:
        await safe_reply(update, "Game state is unavailable right now. Please try again later.")
        return
    board = [""] * 9
    context.user_data[_TTT_KEY] = board
    response = f"""🎮 **Tic-Tac-Toe**

{code_block(_render_ttt(board))}

Your move: Reply with 1-9"""
    await safe_reply(update, response)


@register("hangman")
async def cmd_hangman(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Play hangman."""
    if context.user_data is None:
        await safe_reply(update, "Game state is unavailable right now. Please try again later.")
        return
    content_lib = context.bot_data.get("content_lib")
    words = content_lib.get_all("words") if content_lib else []
    words = [word.lower() for word in words if isinstance(word, str) and word.isalpha()]
    game = Hangman(random.choice(words or ["python", "memory", "planet"]))
    context.user_data[_HANGMAN_KEY] = game

    response = f"""🎮 **Hangman**

Word: {game.masked}
Wrong: {", ".join(game.wrong) or "none"}

{code_block(game.render())}

Guess a letter: /guess [letter]"""
    await safe_reply(update, response)


@register("guess")
async def cmd_guess(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guess a letter in the current hangman game."""
    letter = context.args[0] if context.args else ""
    await _hangman_guess(update, context, letter)


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
