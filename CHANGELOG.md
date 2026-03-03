# Changelog

All notable changes to poke-value.

---

## 2026-03-03 — Replace reverse holo price assumption with real data

### Fixed

**Reverse Holo Pricing**
- Old assumption: reverse holos = 50% of normal card price
- Reality: reverse holos average 1.81x normal price (TCGCSV has real "Reverse Holofoil" market prices)
- Added `tcg_reverse_holo` column to prices table
- TCGCSV importer now captures reverse holo prices as a separate field
- EV calculator uses real reverse holo prices with fallback to normal price
- Impact: all set EVs increased by $0.25–$1.09 (the old assumption was undervaluing packs)

---

## 2026-03-03 — Critical EV Math Audit: Three Bug Fixes

### Fixed

**Bug 1: sv1 mapped to wrong TCGPlayer group**
- Fuzzy matcher matched "Scarlet & Violet" to "SV: Scarlet & Violet 151" (group 23237) instead of "SV01: Scarlet & Violet Base Set" (group 22873)
- Every sv1 card was getting the wrong price (Crushing Hammer priced at $92.29 instead of $0.12)
- Added explicit override `sv1 -> 22873` in `_GROUP_OVERRIDES`

**Bug 2: TCGCSV variant overwrite inflating prices**
- TCGCSV has multiple product variants per card number: Normal, Reverse Holofoil, Poke Ball Pattern, Master Ball Pattern
- Importer was overwriting and keeping whichever came last (often the most expensive variant)
- Umbreon (Rare) was stored at $57.44 (Master Ball Pattern) instead of $0.27 (standard Holofoil)
- Fixed variant selection: prefer standard prints over special variants, prefer Normal subtype, pick cheapest among same tier

**Bug 3: Pull rate probabilities didn't sum to 1.0**
- Template hit_slot probabilities summed to 0.974, leaving a 2.6% gap
- When a set lacked a template rarity (e.g., sv8pt5 has no Illustration Rare), that probability was wasted (up to 11.6% leak)
- Added redistribution: orphaned rarity probability goes to base Rare slot, then normalize to 1.0

### Impact
- sv1 EV: $55.97 → $2.77
- sv8pt5 EV: $30.41 → $4.34
- All SV-era sets now in the $2.50–$8.50 range (was $0–$56)

---

## 2026-03-03 — Phase 1 Complete: Foundation + Quick Wins

### Added

**Set Completion Cost Calculator** (feature: `set-completion-cost`)
- `engine/set_analysis.py` — shared set analysis module
- `get_set_completion_cost(set_id)` — total market/low/mid cost with rarity breakdown
- `/completion` route + template — sortable cross-set completion cost comparison
- `/api/set/<id>/completion` JSON endpoint
- Set detail page: completion cost section with rarity breakdown bars
- CLI: `completion-cost --set <id>` command

**Rip-or-Flip Analysis** (feature: `rip-or-flip`)
- `get_rip_or_flip(set_id)` — sealed product EV vs sealed price, rip/flip/even verdicts
- Pack count heuristics (product_type mapping + name regex fallback)
- `/rip-or-flip` route + template — cross-set sealed product rankings by margin
- `/api/set/<id>/rip-or-flip` JSON endpoint
- Set detail page: sealed products rip-or-flip table with verdict badges

**Navigation & Dashboard** (feature: `nav-overhaul`)
- Dashboard landing page at `/` with quick stats, top EV sets, tool links
- Set grid moved to `/sets`
- Responsive nav with Tools dropdown menu and mobile hamburger
- Brand name links to dashboard

**Chart.js Integration** (feature: `chartjs-setup`)
- Chart.js v4 CDN in base template
- `static/charts.js` — `createChart()` helper with dark theme defaults, consistent color palette

**Pack Value Distribution Tool** (feature: `pack-value-tool`)
- `/api/set/<id>/distribution` JSON endpoint
- Chart.js bar chart replaces HTML-bar histogram on set detail page
- `/distributions` route + template — multi-set distribution comparison (select 2-4 sets, overlaid charts, stats table)

**Set Analysis Engine Module** (feature: `set-analysis-module`)
- `engine/set_analysis.py` created with shared functions for multiple features

### Tests
- 20 new tests (57 total, all passing): completion cost (8), pack count (5), rip-or-flip (7)

### Task Progress — Phase 1 Complete
- `set-completion-cost`: done (5/5 subtasks)
- `rip-or-flip`: done (4/4 subtasks)
- `nav-overhaul`: done (2/2 subtasks)
- `chartjs-setup`: done (1/1 subtasks)
- `pack-value-tool`: done (3/3 subtasks)
- `set-analysis-module`: done (1/1 subtasks)

---

## 2026-03-02 — Task Roadmap & Frontend-First Planning

Session: Claude Code (Opus 4.6) at Kirk's direction.

### Added

**Task Roadmap (`tasks.yaml`)**
- Comprehensive YAML task file breaking all 16 features into 50+ subtasks
- Each feature has both backend (engine, API, CLI) and frontend (template, JS, CSS) tasks
- Dependencies, priorities (1-3), tiers (ready/medium/bigger), and file lists per task
- 4-phase build order: Foundation → Analysis Tools → Tracking/History → Intelligence
- Frontend stack: Flask + Jinja2 + vanilla JS + Chart.js (CDN) — no React, consistent with existing dark theme

### Technical Decisions
- See DECISIONS.md #15 for frontend-alongside-backend development approach

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
