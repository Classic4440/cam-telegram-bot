"""Game commands."""
from __future__ import annotations

import logging
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.formatting import code_block, markdown_to_html, safe_reply
from bot.registry import callback, register
from bot.services.dice import DiceError, roll
from bot.services.gamelogic import Blackjack, Hangman, hand_value, ttt_best_move, ttt_winner

logger = logging.getLogger(__name__)

_TTT_KEY = "tictactoe"
_HANGMAN_KEY = "hangman"
_BLACKJACK_KEY = "blackjack"
_RPS_CHOICES = ("rock", "paper", "scissors")


def _game_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Rock Paper Scissors", callback_data=f"game:{user_id}:select:rps")],
            [InlineKeyboardButton("Hangman", callback_data=f"game:{user_id}:select:hangman")],
            [InlineKeyboardButton("Tic-Tac-Toe", callback_data=f"game:{user_id}:select:ttt")],
            [InlineKeyboardButton("Blackjack", callback_data=f"game:{user_id}:select:blackjack")],
        ]
    )


def _callback_data(user_id: int, game: str, action: str) -> str:
    return f"game:{user_id}:{game}:{action}"


def _ttt_keyboard(board: list[str], user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for start in (0, 3, 6):
        rows.append(
            [
                InlineKeyboardButton(
                    board[index] or str(index + 1),
                    callback_data=_callback_data(user_id, "ttt", str(index)),
                )
                for index in range(start, start + 3)
            ]
        )
    return InlineKeyboardMarkup(rows)


def _hangman_keyboard(game: Hangman, user_id: int) -> InlineKeyboardMarkup | None:
    letters = [letter for letter in "abcdefghijklmnopqrstuvwxyz" if letter not in game.guessed]
    if not letters:
        return None
    rows = [
        [
            InlineKeyboardButton(
                letter.upper(),
                callback_data=_callback_data(user_id, "hangman", letter),
            )
            for letter in letters[start : start + 7]
        ]
        for start in range(0, len(letters), 7)
    ]
    return InlineKeyboardMarkup(rows)


def _blackjack_text(game: Blackjack) -> str:
    dealer_cards = ", ".join(game.dealer if game.finished else game.dealer[:1])
    text = (
        f"🎮 **Blackjack**\n\n"
        f"Your hand: {', '.join(game.player)} (value: {hand_value(game.player)})\n"
        f"Dealer: {dealer_cards}"
    )
    if game.finished:
        outcomes = {
            "blackjack": "Blackjack! You win.",
            "win": "You win!",
            "push": "It's a push.",
            "lose": "Dealer wins.",
            "bust": "You busted. Dealer wins.",
        }
        return f"{text}\n\n{outcomes.get(game.outcome, 'Round over.')}"
    return text


def _blackjack_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Hit", callback_data=_callback_data(user_id, "blackjack", "hit")),
            InlineKeyboardButton("Stand", callback_data=_callback_data(user_id, "blackjack", "stand")),
        ]]
    )


async def _edit_game(query, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    await query.edit_message_text(
        markdown_to_html(text),
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def _start_game(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if name == "rps":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        choice.title(),
                        callback_data=_callback_data(user.id, "rps", choice),
                    )
                    for choice in _RPS_CHOICES
                ]
            ]
        )
        await safe_reply(update, "Choose Rock, Paper, or Scissors:", reply_markup=keyboard)
    elif name == "hangman":
        await cmd_hangman(update, context)
    elif name == "ttt":
        await cmd_tictactoe(update, context)
    elif name == "blackjack":
        if context.user_data is None:
            await safe_reply(update, "Game state is unavailable right now. Please try again later.")
            return
        game = Blackjack.new()
        if game.finished:
            context.user_data.pop(_BLACKJACK_KEY, None)
        else:
            context.user_data[_BLACKJACK_KEY] = game
        await safe_reply(
            update,
            _blackjack_text(game),
            reply_markup=_blackjack_keyboard(user.id) if not game.finished else None,
        )


@register("game")
async def cmd_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the game menu or start a game by name."""
    user = update.effective_user
    if user is None:
        return
    if not context.args:
        await safe_reply(update, "Choose a game:", reply_markup=_game_keyboard(user.id))
        return

    requested = context.args[0].strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "rps": "rps",
        "rockpaperscissors": "rps",
        "hangman": "hangman",
        "tictactoe": "ttt",
        "ttt": "ttt",
        "blackjack": "blackjack",
    }
    name = aliases.get(requested)
    if name is None:
        await safe_reply(update, "Choose /game to see the game menu, or use /game rps|hangman|tictactoe|blackjack.")
        return
    await _start_game(update, context, name)


@callback("game")
async def handle_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> None:
    query = update.callback_query
    user = update.effective_user

    parts = payload.split(":")
    try:
        owner_id = int(parts[0])
    except (ValueError, IndexError):
        await query.answer("This game button has expired.")
        await _edit_game(query, "This game button has expired. Start a new game with /game.")
        return
    if user is None or user.id != owner_id:
        await query.answer("This game menu belongs to another player.", show_alert=True)
        return
    if len(parts) < 2:
        await query.answer("This game button has expired.")
        await _edit_game(query, "This game button has expired. Start a new game with /game.")
        return

    await query.answer()
    action = parts[1]
    argument = parts[2] if len(parts) > 2 else ""
    if action == "select":
        if argument not in {"rps", "hangman", "ttt", "blackjack"}:
            await _edit_game(query, "That game button has expired. Start a new game with /game.")
        elif argument == "rps":
            await _edit_game(
                query,
                "Choose Rock, Paper, or Scissors:",
                InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            choice.title(),
                            callback_data=_callback_data(owner_id, "rps", choice),
                        )
                        for choice in _RPS_CHOICES
                    ]]
                ),
            )
        elif argument == "hangman":
            await _start_hangman_callback(update, context, owner_id)
        elif argument == "ttt":
            if context.user_data is None:
                await _edit_game(query, "Game state is unavailable. Start again with /game.")
                return
            board = [""] * 9
            context.user_data[_TTT_KEY] = board
            await _edit_game(
                query,
                f"🎮 **Tic-Tac-Toe**\n\n{code_block(_render_ttt(board))}\n\nChoose a square:",
                _ttt_keyboard(board, owner_id),
            )
        else:
            if context.user_data is None:
                await _edit_game(query, "Game state is unavailable. Start again with /game.")
                return
            game = Blackjack.new()
            if game.finished:
                context.user_data.pop(_BLACKJACK_KEY, None)
            else:
                context.user_data[_BLACKJACK_KEY] = game
            await _edit_game(
                query,
                _blackjack_text(game),
                _blackjack_keyboard(owner_id) if not game.finished else None,
            )
        return

    if context.user_data is None:
        await _edit_game(query, "This game has expired. Start another with /game.")
        return

    if action == "rps":
        if argument not in _RPS_CHOICES:
            await _edit_game(query, "That choice has expired. Start another round with /game rps.")
            return
        bot_choice = random.choice(_RPS_CHOICES)
        if argument == bot_choice:
            result = "It's a tie!"
        elif (argument, bot_choice) in {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}:
            result = "You win!"
        else:
            result = "I win!"
        await _edit_game(
            query,
            f"🎮 **Rock Paper Scissors**\n\nYou chose {argument.title()}; I chose {bot_choice.title()}.\n\n{result}",
        )
    elif action == "ttt":
        await _handle_ttt_callback(query, context, owner_id, argument)
    elif action == "hangman":
        await _handle_hangman_callback(query, context, owner_id, argument)
    elif action == "blackjack":
        await _handle_blackjack_callback(query, context, owner_id, argument)
    else:
        await _edit_game(query, "This game button has expired. Start a new game with /game.")


async def _start_hangman_callback(update, context, user_id: int) -> None:
    query = update.callback_query
    content_lib = context.bot_data.get("content_lib")
    words = content_lib.get_all("words") if content_lib else []
    words = [word.lower() for word in words if isinstance(word, str) and word.isalpha()]
    game = Hangman(random.choice(words or ["python", "memory", "planet"]))
    if context.user_data is None:
        await _edit_game(query, "Game state is unavailable. Start again with /game.")
        return
    context.user_data[_HANGMAN_KEY] = game
    text = f"🎮 **Hangman**\n\nWord: {game.masked}\nWrong: none\n\n{code_block(game.render())}\nGuess a letter:"
    await _edit_game(query, text, _hangman_keyboard(game, user_id))


async def _handle_ttt_callback(query, context, user_id: int, cell: str) -> None:
    board = context.user_data.get(_TTT_KEY)
    if not isinstance(board, list) or len(board) != 9 or any(mark not in {"", "X", "O"} for mark in board):
        context.user_data.pop(_TTT_KEY, None)
        await _edit_game(query, "This Tic-Tac-Toe game has expired. Start another with /game.")
        return
    try:
        position = int(cell)
    except ValueError:
        position = -1
    if position not in range(9) or board[position]:
        await _edit_game(
            query,
            f"🎮 **Tic-Tac-Toe**\n\n{code_block(_render_ttt(board))}\n\nChoose an empty square:",
            _ttt_keyboard(board, user_id),
        )
        return

    board[position] = "X"
    result = ttt_winner(board)
    if result is None:
        board[ttt_best_move(board, "O", "impossible")] = "O"
        result = ttt_winner(board)
    text = f"🎮 **Tic-Tac-Toe**\n\n{code_block(_render_ttt(board))}"
    if result:
        context.user_data.pop(_TTT_KEY, None)
        outcome = "It's a draw!" if result == "draw" else ("You win!" if result == "X" else "I win!")
        text += f"\n\n{outcome} Start another round with /game."
        keyboard = None
    else:
        text += "\n\nChoose a square:"
        keyboard = _ttt_keyboard(board, user_id)
    await _edit_game(query, text, keyboard)


async def _handle_hangman_callback(query, context, user_id: int, letter: str) -> None:
    game = context.user_data.get(_HANGMAN_KEY)
    if not isinstance(game, Hangman):
        await _edit_game(query, "This Hangman game has expired. Start another with /game.")
        return
    result = game.guess(letter)
    if result in {"invalid", "repeat"}:
        text = f"🎮 **Hangman**\n\nWord: {game.masked}\nWrong: {', '.join(game.wrong) or 'none'}\n\n{code_block(game.render())}\nChoose another letter:"
        await _edit_game(query, text, _hangman_keyboard(game, user_id))
        return

    text = f"🎮 **Hangman**\n\nWord: {game.masked}\nWrong: {', '.join(game.wrong) or 'none'}\n\n{code_block(game.render())}"
    if game.over:
        context.user_data.pop(_HANGMAN_KEY, None)
        text += f"\n\n{'You won!' if game.won else f'Game over — the word was {game.word}.'} Start another with /game."
        keyboard = None
    else:
        text += "\nChoose another letter:"
        keyboard = _hangman_keyboard(game, user_id)
    await _edit_game(query, text, keyboard)


async def _handle_blackjack_callback(query, context, user_id: int, action: str) -> None:
    game = context.user_data.get(_BLACKJACK_KEY)
    if not isinstance(game, Blackjack) or action not in {"hit", "stand"}:
        context.user_data.pop(_BLACKJACK_KEY, None)
        await _edit_game(query, "This Blackjack game has expired. Start another with /game.")
        return
    if action == "hit":
        game.hit()
    else:
        game.stand()
    if game.finished:
        context.user_data.pop(_BLACKJACK_KEY, None)
    await _edit_game(
        query,
        _blackjack_text(game),
        _blackjack_keyboard(user_id) if not game.finished else None,
    )


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
