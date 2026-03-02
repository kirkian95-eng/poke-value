# Changelog

All notable changes to poke-value.

---

## 2026-03-02 — TCGCSV Bulk Pricing, Sealed Products & Roadmap

Session: Claude Code (Opus 4.6) at Kirk's direction.

### Added

**TCGCSV Bulk Price Importer**
- `importers/tcgcsv_importer.py`: free, unlimited TCGPlayer price data via TCGCSV mirrors
- One HTTP request per set → market/low/mid/high/directLow for every card
- 16,896 cards priced across 132 sets in ~90 seconds, zero authentication
- Set name fuzzy matching with prefix stripping (handles "SV: Scarlet & Violet 151" → "151")
- CLI: `bulk-prices --all`, `bulk-prices --era sv`, `bulk-prices --set sv3pt5`
- `update-prices --source tcgcsv` for single-set updates

**Sealed Product Pricing**
- New `sealed_products` table stores booster box, ETB, tin, collection, blister prices
- Automatic product type classification from name
- TCGCSV provides sealed product prices that no other free API offers
- CLI: `sealed --set sv8pt5` shows all sealed products with prices and EV context
- Booster box EV ratio displayed (36-pack box EV vs market price)

**Expanded Roadmap**
- Near-term: set completion cost, expected packs to complete, sealed product analysis, price trends, portfolio tracker
- App ideas: arbitrage finder, grading ROI calculator, rip-or-flip analysis, pack simulator, price alerts, market intelligence, collection valuation

### Technical Decisions
- See DECISIONS.md #13-14 for TCGCSV as bulk source and sealed products table design

---

## 2026-03-02 — PokeTrace Integration & Public Repo

Session: Claude Code (Opus 4.6) at Kirk's direction.

### Added

**PokeTrace Pricing**
- Full PokeTrace API integration: set slug matching (era-aware with validation fallback), card UUID lookup with number format conversion ("166" vs "166/165")
- `price_detail` JSON column: stores ALL pricing data — 5 condition tiers (NM/LP/MP/HP/DMG) × 2 marketplaces (TCGPlayer + eBay) × 8 metrics (avg, low, high, saleCount, avg1d, avg7d, avg30d, lastUpdated)
- `card_id_map` table: caches PokeTrace set slugs and card UUIDs to minimize API calls on repeat runs
- CLI `--source` flag: `update-prices --set sv3pt5 --source poketrace`
- Source priority: PokeTrace USD > PokéWallet USD > TCGdex EUR

**Automated Daily Pricing**
- `update-pokemon-prices.py`: standalone cron script (zero AI tokens, zero OpenClaw dependency)
- Burns 240 of 250 daily free-tier API calls
- Prioritizes SV-era Special Illustration Rares first, works down by rarity and era
- Recalculates EV for any set that receives new prices
- Status file: `/tmp/pokemon-price-status.json`
- Crontab: 1am UTC daily

**God Pack Data**
- Seeded god pack definitions for 151 (demi god pack, 1/1300), Prismatic Evolutions (full 1/2000 + demi 1/500), Ascended Heroes (full 1/1000)

**Improved Set Search** (`query_ev.py`)
- Word-based fuzzy matching with normalization
- Strips common prefixes (pokemon, ptcg, tcg)
- Era prefix support
- ptcgo_code matching
- Returns top 10 cards instead of 5

**Public Repo**
- Moved to `kirkian95-eng/poke-value` (public)
- README with math explanation, quick start, CLI reference, roadmap
- MIT license
- CLAUDE.md with project conventions
- DECISIONS.md expanded with all architecture decisions

### Technical Decisions
- See DECISIONS.md #8-12 for full rationale on PokeTrace matching, full data retention, and cron automation

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
