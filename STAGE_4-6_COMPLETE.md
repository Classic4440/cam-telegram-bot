# Stages 4-6 Content Pipeline

The content generator keeps its import-safe builder API. Run the built-in stages from the repository root:

```bash
python scripts/generate_content.py --all --out bot/data --seed 20261015
```

Use `--dry-run` to generate and validate without writing files. Builder seeds are independent and reproducible.

## Generated packs

The checked-in packs contain 317 entries across eight kinds:

| Kind | Entries |
|---|---:|
| compliments | 5 |
| facts | 21 |
| fortunes | 4 |
| jokes | 94 |
| quotes | 7 |
| trivia | 25 |
| words | 151 |
| would_you_rather | 10 |

Stage 4 generates geography, chemistry, and math trivia; facts based on reference data; and five-letter words. Stage 5 reads curated `*.json` packs, validates them, and removes their duplicate entries from generated packs. Stage 6 validates all output before atomic writes.

The runtime loader combines curated and generated files with fingerprint-based de-duplication. Curated files take precedence if entries overlap. `ContentLibrary.get_all(kind)` returns entries across all categories for that content kind.
