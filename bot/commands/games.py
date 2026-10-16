"""Small chat games and curated quiz commands."""
from __future__ import annotations

import random
import re

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import reply_ai
from bot.registry import command
from bot.services.gamelogic import Blackjack, Hangman, hand_value, ttt_best_move, ttt_winner
from scripts.curated_games import FIVE_LETTER_WORDS, HANGMAN_WORDS, RIDDLES, TRIVIA

_RPS = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}


def _board_text(board: list[str]) -> str:
    cells = [value if value else str(index + 1) for index, value in enumerate(board)]
    return f"{cells[0]} | {cells[1]} | {cells[2]}\n---------\n{cells[3]} | {cells[4]} | {cells[5]}\n---------\n{cells[6]} | {cells[7]} | {cells[8]}"


def _blackjack_text(game: Blackjack, reveal_dealer: bool = False) -> str:
    dealer = " ".join(game.dealer) if reveal_dealer else f"{game.dealer[0]} ??"
    text = f"Dealer: {dealer}\nYour hand: {' '.join(game.player)} ({hand_value(game.player)})"
    if game.finished:
        text += f"\nResult: {game.outcome}."
    else:
        text += "\nUse /game blackjack hit or /game blackjack stand."
    return text


@command(
    "game",
    description="Play rock-paper-scissors, hangman, tic-tac-toe or blackjack",
    category="Games",
    usage="/game <rps|hangman|tictactoe|blackjack> [move]",
)
async def game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    args = list(context.args)
    if not args:
        await reply_ai(message, "Usage: /game <rps|hangman|tictactoe|blackjack> [move]")
        return

    mode = args[0].lower()
    rest = args[1:]
    user_data = context.user_data

    if mode == "rps":
        if not rest or rest[0].lower() not in _RPS:
            await reply_ai(message, "Usage: /game rps <rock|paper|scissors>")
            return
        player = rest[0].lower()
        computer = random.choice(tuple(_RPS))
        outcome = (
            "It's a draw!"
            if player == computer
            else "You win!"
            if (player, computer) in {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}
            else "I win this round!"
        )
        await reply_ai(
            message,
            f"You: {_RPS[player]}  Me: {_RPS[computer]}\n{outcome}",
        )
        return

    if mode == "hangman":
        key = "game_hangman"
        current: Hangman | None = user_data.get(key)
        if not rest or rest[0].lower() in {"new", "start"} or current is None or current.over:
            words = [word for entries in HANGMAN_WORDS.values() for word in entries]
            if not words:
                words = FIVE_LETTER_WORDS
            if not words:
                await reply_ai(message, "No words are available for hangman right now.")
                return
            word = random.choice(words).lower()
            current = Hangman(word=word)
            user_data[key] = current
            await reply_ai(message, f"Hangman started!\n{current.render()}\n{current.masked}\nGuess with /game hangman <letter>.")
            return
        guess = rest[0].lower()
        if len(guess) != 1 or not guess.isalpha():
            await reply_ai(message, "Usage: /game hangman <one letter>, or /game hangman new")
            return
        result = current.guess(guess)
        if result == "repeat":
            await reply_ai(message, f"You already guessed that letter.\n{current.render()}\n{current.masked}")
            return
        if result == "invalid":
            await reply_ai(message, "Guess one letter from A to Z.")
            return
        status = "Correct guess!" if result == "hit" else "Not in the word."
        if current.won:
            status += f" You won! The word was **{current.word}**."
        elif current.lost:
            status += f" Game over; the word was **{current.word}**."
        else:
            status += f"\nWrong guesses: {', '.join(current.wrong) or 'none'}"
        await reply_ai(message, f"{status}\n{current.render()}\n{current.masked}")
        return

    if mode in {"tictactoe", "tic-tac-toe", "ttt"}:
        key = "game_tictactoe"
        board: list[str] = user_data.get(key)
        if not rest or rest[0].lower() in {"new", "start"} or board is None or ttt_winner(board):
            board = [""] * 9
            user_data[key] = board
            await reply_ai(message, f"New tic-tac-toe game. You are X; I am O.\n{_board_text(board)}\nChoose a square with /game tictactoe <1-9>.")
            return
        if not re.fullmatch(r"[1-9]", rest[0]):
            await reply_ai(message, "Usage: /game tictactoe <square 1-9>, or /game tictactoe new")
            return
        position = int(rest[0]) - 1
        if board[position]:
            await reply_ai(message, "That square is occupied. Choose an empty square from 1 to 9.")
            return
        board[position] = "X"
        winner = ttt_winner(board)
        if winner is None:
            board[ttt_best_move(board, ai="O")] = "O"
            winner = ttt_winner(board)
        result = {"X": "You win!", "O": "I win!", "draw": "It's a draw!"}.get(winner, "Your move.")
        await reply_ai(message, f"{_board_text(board)}\n{result}")
        return

    if mode == "blackjack":
        key = "game_blackjack"
        current: Blackjack | None = user_data.get(key)
        action = rest[0].lower() if rest else "new"
        if action in {"new", "start"} or current is None or current.finished:
            current = Blackjack.new()
            user_data[key] = current
            await reply_ai(message, _blackjack_text(current, reveal_dealer=current.finished))
            return
        if action == "hit":
            current.hit()
        elif action in {"stand", "stay"}:
            current.stand()
        else:
            await reply_ai(message, "Usage: /game blackjack [new|hit|stand]")
            return
        await reply_ai(message, _blackjack_text(current, reveal_dealer=current.finished))
        return

    await reply_ai(message, "Choose a game: rps, hangman, tictactoe or blackjack.")


@command("riddle", description="Ask a curated riddle", category="Games", usage="/riddle [answer]")
async def riddle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    key = "current_riddle"
    answer = " ".join(context.args).strip()
    current = context.user_data.get(key)
    if answer and current:
        expected = re.sub(r"\W+", " ", current["a"].lower()).strip()
        guess = re.sub(r"\W+", " ", answer.lower()).strip()
        if guess and (guess in expected or expected in guess):
            await reply_ai(message, f"Correct! {current['a']}")
        else:
            await reply_ai(message, "Not quite. Try again, or send /riddle to reveal a new one.")
        return
    current = random.choice(RIDDLES)
    context.user_data[key] = current
    await reply_ai(message, f"**Riddle:** {current['q']}\nReply with /riddle <answer> to guess.")


@command("trivia", description="Answer a curated trivia question", category="Games", usage="/trivia [1-4]")
async def trivia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    key = "current_trivia"
    guess = " ".join(context.args).strip()
    current = context.user_data.get(key)
    if guess and current:
        if guess == current["correct_option"]:
            await reply_ai(message, f"Correct! The answer is {current['a']}.")
        else:
            await reply_ai(message, f"Not quite. The correct answer is {current['a']}.")
        context.user_data.pop(key, None)
        return
    entries = [entry for items in TRIVIA.values() for entry in items]
    if not entries:
        await reply_ai(message, "No trivia questions are available right now.")
        return
    question = random.choice(entries)
    options = list(question["w"]) + [question["a"]]
    random.shuffle(options)
    correct_option = str(options.index(question["a"]) + 1)
    context.user_data[key] = {**question, "correct_option": correct_option}
    choices = "\n".join(f"{index}. {option}" for index, option in enumerate(options, 1))
    await reply_ai(message, f"**Trivia:** {question['q']}\n{choices}\nAnswer with /trivia <1-4>.")
