# Project: poke-value (Pokemon TCG Toolkit)

## Mandatory practices

- **Always update DECISIONS.md** when making architecture decisions, choosing between approaches, or making tradeoffs. Every non-trivial "why" should be captured there. Do this as you work, not at the end.
- **Always update CHANGELOG.md** when adding features, fixing bugs, or making config changes.
- **Never hardcode API keys or secrets.** Use environment variables.
- **Never commit the .db file or log files.**

## Project conventions

- Python 3, Flask, SQLite (WAL mode)
- CLI via argparse in cli.py
- Price sources: TCGCSV (free, unlimited, TCGPlayer USD + sealed), PokeTrace (API key, USD, conditions/trends), TCGdex (free, EUR)
- EV engine uses closed-form probability math, not simulation
- Pull rates are community estimates stored as era-based templates with per-set overrides
- Full PokeTrace JSON stored in `price_detail` column — never discard pricing data
- The cron script (`update-pokemon-prices.py`) is standalone — no AI, no OpenClaw dependency
- Tests use synthetic data, not real card data

## Key files

- `tasks.yaml` — roadmap tasks with subtasks, dependencies, priorities, and build order
- `engine/ev_calculator.py` — core math engine (EV, pack distribution)
- `engine/pull_rates.py` — pull rate resolver
- `engine/set_analysis.py` — set completion cost, rip-or-flip, cross-set analysis
- `importers/price_updater.py` — multi-source price fetcher
- `importers/tcgcsv_importer.py` — TCGCSV bulk price + sealed product importer
- `database/schema.py` — schema + seed data
- `update-pokemon-prices.py` — standalone daily cron script
- `query_ev.py` — zero-dependency JSON query script
- `static/charts.js` — Chart.js dark theme helper (`createChart()`, color palette)

## Development workflow

The project uses a task-driven development loop. All roadmap work lives in `tasks.yaml`.

**Slash commands:**
- `/task` — Pick up the next available task, build it (backend + frontend together), test, self-review, update docs, and mark done.
- `/review` — Self-review uncommitted changes for correctness, consistency, completeness, and performance.
- `/status` — Print roadmap progress across all features and phases.

**Rules for every task:**
1. Backend and frontend are built in the same pass — never leave a feature without its UI.
2. All new pages extend `templates/base.html` and use the dark theme.
3. Charts use Chart.js v4 (CDN in base.html) with the shared theme helper in `static/charts.js`.
4. Run existing tests after every change. Add new tests for new engine functions.
5. Update `tasks.yaml` status after completing each subtask.
6. Update CHANGELOG.md and DECISIONS.md as you work, not at the end.

**Frontend stack:** Flask + Jinja2 + vanilla JS + Chart.js CDN. No React, no npm, no build step.

## PokeTrace API notes

- Free tier: 250 calls/day, resets midnight UTC
- Burst rate limit: ~1 request per 2 seconds
- Set slugs: prefer English marketing names (slug starts with era prefix + hyphen, e.g. `sv-`) over Japanese set codes (e.g. `sv2a-`)
- Card numbers: PokeTrace uses "166/165" format, our DB stores just "166"
- Condition tiers: NEAR_MINT, LIGHTLY_PLAYED, MODERATELY_PLAYED, HEAVILY_PLAYED, DAMAGED
- Two marketplaces per card: tcgplayer + ebay
