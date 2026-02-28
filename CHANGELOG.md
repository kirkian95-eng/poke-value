# Changelog

All notable changes to the Pokemon TCG EV Calculator.

---

## 2026-02-28 — Initial Build

Session: Claude Code (Opus 4.6) at Kirk's direction.

### Added

**Core Application**
- SQLite database with schema for sets, cards, prices, pull rates, god packs, and EV cache
- Card importer: fetches all English card data from `PokemonTCG/pokemon-tcg-data` GitHub repo
- Set importer: fetches 171 sets with metadata, logos, era detection
- Price updater: fetches pricing from TCGdex API (Cardmarket EUR + TCGPlayer USD where available)
- EV calculation engine: 3-slot model (guaranteed, hit slot, reverse holo) with god pack adjustment
- Pull rate templates: SV, SWSH, and SM eras seeded with community-derived defaults
- Per-set pull rate overrides table for sets with unusual distributions

**CLI** (`cli.py`)
- `init-db` — create schema and seed templates
- `import-sets` — download all 171 sets
- `import-cards --set <id|all>` — download card data
- `update-prices --set <id>` — fetch current prices from TCGdex
- `calc-ev --set <id>` — calculate and display EV breakdown
- `calc-ev-all` — EV summary for all priced sets
- `stats` — database statistics

**Flask Web App** (`app.py`)
- Index page: set grid with logos, EV values, value ratio color coding, filters by era/search
- Set detail page: EV summary box, rarity breakdown table, pull rates, full card list with sorting
- About page: methodology explanation with formulas

**Tests** (`test_ev_calculator.py`)
- 28 tests covering: price resolution, pull rate templates, hand-calculated EV verification, god pack adjustment, edge cases
- Uses synthetic data (not real cards) for deterministic testing

**Stephen Integration**
- `query-ev.sh` — zero-token shell script for Stephen to query EV data from SQLite
- `skills/pokemon-ev/SKILL.md` — OpenClaw skill teaching Stephen how to handle set name queries

### Data Imported
- 171 sets, 20,078 cards
- Pokemon 151 (sv3pt5): 207 cards priced, EV = $5.53/pack (123% of $4.49 MSRP)

### Key Technical Decisions
- TCGdex API for pricing (pokemontcg.io is dead, PokéWallet returns 404s)
- Cardmarket EUR prices converted to USD at 1.08x
- Pull rates are era-based defaults, not per-card — avoids entering thousands of values
- See DECISIONS.md for full rationale
