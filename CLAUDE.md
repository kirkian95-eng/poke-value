# Project: poke-value (Pokemon TCG Toolkit)

## Mandatory practices

- **Always update DECISIONS.md** when making architecture decisions, choosing between approaches, or making tradeoffs. Every non-trivial "why" should be captured there. Do this as you work, not at the end.
- **Always update CHANGELOG.md** when adding features, fixing bugs, or making config changes.
- **Never hardcode API keys or secrets.** Use environment variables.
- **Never commit the .db file or log files.**

## Project conventions

- Python 3, Flask, SQLite (WAL mode)
- CLI via argparse in cli.py
- Price sources: TCGdex (free, EUR), PokeTrace (API key, USD, full condition data)
- EV engine uses closed-form probability math, not simulation
- Pull rates are community estimates stored as era-based templates with per-set overrides
- Full PokeTrace JSON stored in `price_detail` column — never discard pricing data
- The cron script (`update-pokemon-prices.py`) is standalone — no AI, no OpenClaw dependency
- Tests use synthetic data, not real card data

## Key files

- `engine/ev_calculator.py` — core math engine
- `engine/pull_rates.py` — pull rate resolver
- `importers/price_updater.py` — multi-source price fetcher
- `database/schema.py` — schema + seed data
- `update-pokemon-prices.py` — standalone daily cron script
- `query_ev.py` — zero-dependency JSON query script

## PokeTrace API notes

- Free tier: 250 calls/day, resets midnight UTC
- Burst rate limit: ~1 request per 2 seconds
- Set slugs: prefer English marketing names (slug starts with era prefix + hyphen, e.g. `sv-`) over Japanese set codes (e.g. `sv2a-`)
- Card numbers: PokeTrace uses "166/165" format, our DB stores just "166"
- Condition tiers: NEAR_MINT, LIGHTLY_PLAYED, MODERATELY_PLAYED, HEAVILY_PLAYED, DAMAGED
- Two marketplaces per card: tcgplayer + ebay
