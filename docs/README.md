# Telegram Bot - Largest Bot Ever 🤖

A comprehensive, production-grade Telegram bot framework with extensive content generation, AI integration, and game logic.

## Project Structure

```
cam-telegram-bot/
├── bot/                          # Core bot framework
│   ├── __init__.py              # Package initialization
│   ├── config.py                # Typed environment configuration
│   ├── errors.py                # Custom exception types
│   ├── cache.py                 # Thread-safe TTL cache with LRU eviction
│   ├── logging_setup.py         # Logging with secret redaction
│   ├── security.py              # Rate limiting & input sanitization
│   ├── state.py                 # AppState dataclass & stats
│   ├── formatting.py            # Telegram-safe text formatting (MD→HTML)
│   ├── store.py                 # Persistence layer (Memory/Supabase)
│   ├── content.py               # Content library loader & selection
│   ├── ai.py                    # AI service (12 personas, intent routing)
│   ├── registry.py              # Decorator-based command registry
│   ├── commands/                # Auto-discovered Telegram commands
│   ├── handlers/                # Text and media update handlers
│   ├── utils/                   # Media processing helpers
│   └── services/                # Business logic modules
│       ├── __init__.py
│       ├── dice.py              # Dice notation roller (2d6+3, d20, etc)
│       ├── gamelogic.py         # Game engines (tic-tac-toe, hangman, etc)
│       ├── logic.py             # Propositional logic parser & truth tables
│       ├── mathx.py             # Safe math eval, symbolic diff, matrices
│       ├── music.py             # Chord theory, scales, intervals, transposition
│       ├── numbers.py           # Prime checking, factorization, statistics
│       ├── textcodec.py         # rot13, base64, morse, ciphers
│       ├── timeparse.py         # Natural language time parsing
│       └── units.py             # Unit conversion (length, mass, volume, etc)
├── app.py                        # Telegram polling application entry point
├── scripts/                      # Content generation & utilities
│   ├── curated_jokes.py         # Hand-written jokes (~1,500+ entries)
│   ├── curated_quotes_facts.py  # Quotes & facts (~1,000+ entries)
│   ├── curated_games.py         # Riddles, trivia, tongue twisters (~500+ entries)
│   ├── generate_content.md      # Content generator source
│   └── generate_content.py      # Executable content generator
├── tests/                        # 493 executable tests and readable Markdown sources
│   ├── test_memory.py           # Profile persistence and prompt injection
│   ├── test_generate_content.py
│   ├── test_generate_content_data.py
│   ├── test_generate_content_text.py
│   ├── test_generate_content.md
│   ├── test_generate_content_data.md
│   └── test_generate_content_text.md
├── docs/                         # Documentation
│   ├── README.md                # This file
│   ├── Project_Instructions.md
│   ├── Current_Status_and_Architecture.md
│   └── services_and_curated_full.md
└── supabase/                     # Supabase RLS policies & migrations
    └── user_profiles.sql        # Long-term memory profile table
```

## Key Features

### Architecture
- **Modular plugin-style command registry** with decorators and middleware
- **Circuit breaker pattern** for database failover
- **Token-bucket rate limiting** for bot protection
- **Thread-safe TTL cache** with LRU eviction
- **Dual persistence layer**: Memory (dev) + Supabase (prod)

### AI Integration
- **12 AI personas**: default, professor, engineer, coach, comedian, zen, pirate, shakespeare, hype, sage, producer, eli5
- **Intent routing** with confidence thresholds
- **Model fallback chain** with retry+jitter (Groq → OpenAI → Claude)
- **Voice transcription** support

### Content System
- **Deterministic seeded generation** with atomic writes
- **Fingerprinting & deduplication** (case/space-insensitive)
- **Deck-based shuffling** prevents repeats per-chat
- **Curated + generated packs** merged seamlessly
- **~23K+ generated entries** across all categories

### Services (Pure Python, Reusable)
- **Dice notation**: 2d6+3, d20, 4d6kh3, 3d8kl1
- **Game engines**: tic-tac-toe (minimax), hangman, connect-4, blackjack
- **Logic parser**: propositional logic, truth tables, tautology checks
- **Math**: safe AST-based eval, symbolic differentiation, matrix ops
- **Music theory**: chords, scales, modes, intervals, transposition
- **Number theory**: Miller-Rabin primality, Pollard's rho factorization
- **Text codecs**: rot13, base64, morse, phonetic alphabet, substitution ciphers
- **Time parsing**: "in 2 hours", "next Tuesday" → ISO 8601
- **Units**: Length, mass, volume, time, speed, area, energy, pressure, angle, data

## Configuration

Set environment variables:
```bash
TELEGRAM_TOKEN=your_bot_token
AI_API_KEY=your_groq_key
SUPABASE_URL=optional
SUPABASE_KEY=optional
```

The bot reads credentials directly from the process environment; do not commit a `.env` file. Configure
the profile table by applying `supabase/user_profiles.sql` in Supabase. For durable server-side access,
`SUPABASE_KEY` must be a server key permitted to bypass row-level security.

`/personal <information>` saves a user's profile and `/update` displays it. The profile is also included
in the system prompt for AI chat and AI tasks.

## Testing

Run `python -m pytest tests/` for all 493 tests. The three Markdown test files are the readable source
copies for the generated Python test suites.

## Development Notes

- **Python 3.10+** required
- **No eval()** anywhere — all math/logic uses AST whitelist
- **RLS policies** required for Supabase production
- **All services** are pure Python with zero Telegram imports
- **Deterministic generation** enables reproducible content

## Next Steps

1. Run `python -m pytest tests/`.
2. Set the required environment variables (`TELEGRAM_TOKEN`, `AI_API_KEY`) and optional Supabase settings.
3. Run `python app.py` to start Telegram polling and the `/health` endpoint on `PORT` (default `10000`).

---

Built with python-telegram-bot 22.8, Supabase PostgreSQL, and Groq AI.
