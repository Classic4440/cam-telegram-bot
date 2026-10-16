"""Game engines: unbeatable tic-tac-toe (minimax + alpha-beta), hangman, wordle scoring, blackjack."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# ======================================================================================
# tic-tac-toe
# ======================================================================================
_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def ttt_winner(board: list[str]) -> str | None:
    """Return 'X' / 'O' for a win, 'draw' for a full board, else ``None``."""
    for a, b, c in _LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return "draw" if all(board) else None


def _minimax(board: list[str], player: str, ai: str, alpha: int, beta: int, depth: int) -> int:
    result = ttt_winner(board)
    if result == ai:
        return 10 - depth
    if result == "draw":
        return 0
    if result is not None:
        return depth - 10
    maximizing = player == ai
    best = -100 if maximizing else 100
    other = "X" if player == "O" else "O"
    for i in range(9):
        if board[i]:
            continue
        board[i] = player
        score = _minimax(board, other, ai, alpha, beta, depth + 1)
        board[i] = ""
        if maximizing:
            best = max(best, score)
            alpha = max(alpha, best)
        else:
            best = min(best, score)
            beta = min(beta, best)
        if beta <= alpha:
            break
    return best


def ttt_best_move(board: list[str], ai: str = "O", difficulty: str = "impossible", rng: random.Random | None = None) -> int:
    """Pick the AI's move. ``easy`` plays randomly, ``medium`` plays randomly 40% of the time."""
    rng = rng or random.Random()
    free = [i for i, v in enumerate(board) if not v]
    if not free:
        raise ValueError("board is full")
    if difficulty == "easy" or (difficulty == "medium" and rng.random() < 0.4):
        return rng.choice(free)
    human = "X" if ai == "O" else "O"
    best_score, best_moves = -1000, []
    for i in free:
        board[i] = ai
        score = _minimax(board, human, ai, -100, 100, 1)
        board[i] = ""
        if score > best_score:
            best_score, best_moves = score, [i]
        elif score == best_score:
            best_moves.append(i)
    return rng.choice(best_moves)


# ======================================================================================
# hangman
# ======================================================================================
HANGMAN_STAGES = [
    "  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n=========",
]
MAX_WRONG = len(HANGMAN_STAGES) - 1


@dataclass
class Hangman:
    word: str
    guessed: set[str] = field(default_factory=set)
    hint: str = ""

    @property
    def wrong(self) -> list[str]:
        return sorted(c for c in self.guessed if c not in self.word)

    @property
    def masked(self) -> str:
        return " ".join(c if c in self.guessed or not c.isalpha() else "_" for c in self.word)

    @property
    def won(self) -> bool:
        return all(c in self.guessed for c in self.word if c.isalpha())

    @property
    def lost(self) -> bool:
        return len(self.wrong) >= MAX_WRONG

    @property
    def over(self) -> bool:
        return self.won or self.lost

    def guess(self, letter: str) -> str:
        letter = letter.lower()
        if len(letter) != 1 or not letter.isalpha():
            return "invalid"
        if letter in self.guessed:
            return "repeat"
        self.guessed.add(letter)
        return "hit" if letter in self.word else "miss"

    def render(self) -> str:
        return HANGMAN_STAGES[min(len(self.wrong), MAX_WRONG)]


# ======================================================================================
# wordle
# ======================================================================================
def wordle_score(secret: str, guess: str) -> str:
    """Return a 🟩🟨⬛ string using standard duplicate-letter rules."""
    if len(secret) != len(guess):
        raise ValueError("length mismatch")
    result = ["⬛"] * len(secret)
    remaining: dict[str, int] = {}
    for i, (s, g) in enumerate(zip(secret, guess)):
        if s == g:
            result[i] = "🟩"
        else:
            remaining[s] = remaining.get(s, 0) + 1
    for i, g in enumerate(guess):
        if result[i] == "⬛" and remaining.get(g, 0) > 0:
            result[i] = "🟨"
            remaining[g] -= 1
    return "".join(result)


# ======================================================================================
# blackjack
# ======================================================================================
SUITS = "♠♥♦♣"
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def hand_value(cards: list[str]) -> int:
    total, aces = 0, 0
    for card in cards:
        rank = card[:-1]
        if rank == "A":
            aces += 1
            total += 11
        elif rank in {"J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


@dataclass
class Blackjack:
    deck: list[str]
    player: list[str] = field(default_factory=list)
    dealer: list[str] = field(default_factory=list)
    finished: bool = False
    outcome: str = ""

    @classmethod
    def new(cls, rng: random.Random | None = None) -> "Blackjack":
        rng = rng or random.Random()
        deck = [f"{r}{s}" for r in RANKS for s in SUITS]
        rng.shuffle(deck)
        game = cls(deck)
        game.player = [game.deck.pop(), game.deck.pop()]
        game.dealer = [game.deck.pop(), game.deck.pop()]
        if hand_value(game.player) == 21:
            game.stand()
        return game

    def hit(self) -> None:
        if self.finished:
            return
        self.player.append(self.deck.pop())
        if hand_value(self.player) > 21:
            self.finished, self.outcome = True, "bust"
        elif hand_value(self.player) == 21:
            self.stand()

    def stand(self) -> None:
        if self.finished:
            return
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        p, d = hand_value(self.player), hand_value(self.dealer)
        self.finished = True
        if len(self.player) == 2 and p == 21 and not (len(self.dealer) == 2 and d == 21):
            self.outcome = "blackjack"
        elif d > 21 or p > d:
            self.outcome = "win"
        elif p == d:
            self.outcome = "push"
        else:
            self.outcome = "lose"
