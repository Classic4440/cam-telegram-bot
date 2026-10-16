# Bot Services & Curated Content Summary

## Services Modules (bot/services/)
All 9 service modules implement pure Python logic (no Telegram imports) for reusability:

1. **dice.py** (2.8 KB) — Dice notation roller supporting: 2d6+3, d20, 4d6kh3 (keep highest), 3d8kl1 (keep lowest)
2. **logic.py** (7.4 KB) — Propositional logic parser, truth tables, tautology/contradiction/equivalence checks
3. **units.py** (7.0 KB) — Unit conversion: length, mass, volume, time, speed, area, energy, pressure, angle, data
4. **dice.py** — See above
5. **numbers.py** (8.4 KB) — Number theory: prime checking (Miller-Rabin), factorization (Pollard's rho), statistics
6. **textcodec.py** (7.9 KB) — rot13, base64, morse code, phonetic alphabet, substitution ciphers
7. **music.py** (8.8 KB) — Chord theory, scales, modes, intervals, transposition, tempo math, note frequencies
8. **timeparse.py** (5.1 KB) — Natural language time parsing: "in 2 hours", "next Tuesday", "3pm"
9. **gamelogic.py** (7.2 KB) — Rock-paper-scissors, hangman, connect-4, tic-tac-toe (minimax), blackjack

## Curated Content Files (scripts/)

### curated_jokes.py (26.3 KB)
- Hand-written jokes organized by category
- Multiple families for variety (one-liners, setup-punchline, programming humor, etc.)
- Totals: ~1,500+ joke entries
- Used as reference data for content loader

### curated_quotes_facts.py (21.5 KB)
- Famous quotes with confident attributions only (no misattributed quotes)
- True facts across various topics
- Totals: ~1,000+ quote and fact entries
- Merged with generated content via fingerprinting

### curated_games.py (18.6 KB)
- Riddles with answers
- Trivia questions with multiple choice answers
- Tongue twisters
- Magic 8-ball responses
- Totals: ~500+ entries

## Important Notes

- **Fingerprinting**: All content de-duped by normalized form (whitespace/case-insensitive)
- **Loader behavior**: Content loaded at bot startup via `bot/content.py`
- **Merge strategy**: Generated `.generated.json` loaded first, curated `.json` second → curated wins on conflict
- **Generation**: Stage 3 added ~23K+ generated entries across all categories

## Files Ready for Extract & Upload

Extract these from `scripts/generate_content.md` (one python block):
- Full `generate_content.py` (1082 lines, ~58 KB)
- All services as individual `.py` files
- Curated content as reference

All stored in `/home/claude/cam-telegram-bot/` and ready for Drive sync.
