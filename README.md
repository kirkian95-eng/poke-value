# poke-value

A toolkit for analyzing the economics of Pokemon TCG products. Calculate the expected value of booster packs, track card prices across marketplaces, and figure out the true cost to complete a set.

## What it does

**Pack EV Calculator** — Answers "is this booster pack worth buying at retail?" by computing the exact expected dollar value of opening a pack based on current market prices and pull rate probabilities.

**Price Database** — Aggregates card prices from multiple sources (TCGPlayer via TCGCSV and PokeTrace, Cardmarket via TCGdex) across all conditions (Near Mint through Damaged) and marketplaces (TCGPlayer + eBay). Bulk pricing via TCGCSV is free and unlimited — covers 16,000+ cards and sealed products in under 2 minutes.

**Web Dashboard** — Browse all 171 sets with EV breakdowns, value ratios vs MSRP, pack value distributions, and sortable card price tables.

## How the math works

The EV engine uses closed-form probability math — not simulation. Every possible pack outcome is enumerated and weighted by its exact probability.

A booster pack has three types of card slots:

| Slot Type | How it works |
|---|---|
| **Guaranteed** (commons, uncommons) | Fixed distribution. `P(card) = slots / cards_of_rarity` |
| **Hit slot** (rare and above) | One slot with rarity probability tiers. `P(card) = P(rarity) / cards_of_rarity` |
| **Reverse holo** | Drawn from common/uncommon/rare pool at ~50% price |

```
EV = Σ P(card_in_pack) × price(card)   for all cards across all slot types
```

For sets with god packs (151, Prismatic Evolutions, etc.):
```
EV_final = (1 - P_god) × EV_normal + P_god × EV_god_pack
```

The distribution engine computes exact percentiles — probability of beating MSRP, hitting $10+, $20+, $50+ packs — by evaluating every discrete hit slot outcome.

## Quick start

```bash
# Clone and install
git clone https://github.com/kirkian95-eng/poke-value.git
cd poke-value
pip install -r requirements.txt

# Initialize database and import all sets + cards
python3 cli.py init-db
python3 cli.py import-sets
python3 cli.py import-cards --set all

# Fetch prices for a set (free, no API key needed)
python3 cli.py update-prices --set sv3pt5

# Calculate EV
python3 cli.py calc-ev --set sv3pt5
```

Output:
```
Set: 151 (sv3pt5)
  Cards with prices: 207
  EV per pack: $5.53
  Pack MSRP:   $4.49
  Value ratio:  123.2% ← worth buying
```

## Price sources

| Source | Data | Auth | Rate limit | Best for |
|---|---|---|---|---|
| **TCGCSV** | TCGPlayer market/low/mid/high + sealed products | None (free) | Unlimited | Bulk pricing, sealed products |
| **PokeTrace** | TCGPlayer + eBay USD, all conditions, trend data | API key (free tier) | 250/day | Condition breakdowns, trends |
| **TCGdex** | Cardmarket EUR prices | None (free) | Unlimited | EUR/Cardmarket data |

**TCGCSV** is the primary bulk price source — mirrors TCGPlayer's entire product catalog as CSV files. One HTTP request per set gives market/low/mid/high prices for every card AND sealed product (booster boxes, ETBs, tins, etc.). Covers 16,000+ cards across 130+ sets with zero authentication.

**PokeTrace** provides higher-quality per-card data: condition breakdowns (NM/LP/MP/HP/DMG), sale counts, and 7-day/30-day trends — stored as full JSON in the `price_detail` column so nothing is discarded.

### Automated daily pricing (optional)

The included cron script uses the PokeTrace free tier to gradually build up USD pricing data — 240 cards/day, prioritizing high-value SV-era rarities first.

```bash
# Set your PokeTrace API key
export POKETRACE_API_KEY="your_key_here"

# Run manually
python3 update-pokemon-prices.py --dry-run   # preview what would be priced
python3 update-pokemon-prices.py             # run with default 240-call budget

# Or add to crontab for daily runs (resets at midnight UTC)
# 0 1 * * * POKETRACE_API_KEY=your_key python3 /path/to/update-pokemon-prices.py
```

Check progress:
```bash
cat /tmp/pokemon-price-status.json
```

## Web dashboard

```bash
./run.sh              # starts Flask on port 5001
open http://localhost:5001
./stop.sh             # stop
```

**Index** — Set grid with logos, EV values, color-coded value ratios (green = good deal), filterable by era and search.

**Set detail** — EV summary, rarity breakdown table, pull rates, pack value distribution histogram with percentile stats, full card list with sorting.

## CLI reference

```
python3 cli.py init-db                         # Create schema, seed pull rate templates
python3 cli.py import-sets                     # Download all 171 sets from GitHub
python3 cli.py import-cards --set <id|all>     # Download card data
python3 cli.py update-prices --set <id>        # Fetch prices (TCGdex + PokeTrace if key set)
python3 cli.py update-prices --set <id> --source tcgcsv      # TCGPlayer prices via TCGCSV
python3 cli.py update-prices --set <id> --source poketrace   # Full condition/trend data
python3 cli.py bulk-prices --all               # Bulk update ALL sets via TCGCSV (free, fast)
python3 cli.py bulk-prices --era sv            # Bulk update one era
python3 cli.py calc-ev --set <id>              # Calculate and display EV breakdown
python3 cli.py calc-ev-all                     # EV for all priced sets
python3 cli.py sealed --set <id>               # Show sealed product prices
python3 cli.py stats                           # Database statistics
```

## Database schema

| Table | Purpose |
|---|---|
| `sets` | 171 sets with metadata, era, god pack flags |
| `cards` | 20K+ cards with rarity, images, regulation marks |
| `prices` | Per-card prices from TCGCSV/PokeTrace + full JSON detail |
| `sealed_products` | Sealed product prices (booster boxes, ETBs, tins, etc.) |
| `pull_rate_templates` | Default pull rates by era (SV, SWSH, SM) |
| `pull_rate_overrides` | Per-set adjustments for unusual distributions |
| `god_packs` | God pack definitions with JSON composition |
| `ev_cache` | Cached EV calculations |
| `card_id_map` | PokeTrace UUID cache (minimizes API calls) |

## Project structure

```
poke-value/
├── app.py                    # Flask web app
├── cli.py                    # CLI interface
├── config.py                 # API URLs, conversion rates, era config
├── database/
│   ├── schema.py             # SQLite schema + seed data
│   └── connection.py         # DB connection manager (WAL mode)
├── engine/
│   ├── ev_calculator.py      # EV math engine + distribution analysis
│   └── pull_rates.py         # Pull rate template/override resolver
├── importers/
│   ├── set_importer.py       # Set data from GitHub
│   ├── card_importer.py      # Card data from GitHub
│   ├── price_updater.py      # Multi-source price fetcher
│   └── tcgcsv_importer.py   # TCGCSV bulk price + sealed product importer
├── templates/                # Jinja2 HTML templates
├── static/                   # CSS
├── update-pokemon-prices.py  # Standalone daily cron script
├── query_ev.py               # Zero-dependency JSON query script
└── test_ev_calculator.py     # Unit tests
```

## Roadmap

### Ready to build (data already in DB)
- **Set completion cost** — Sum market price of every card in a set. "Completing Prismatic Evolutions costs $X at market / $Y at low." Data: 98% card price coverage.
- **Expected packs to complete** — Coupon collector problem with pull rate weights. How many packs to collect every card, with duplicate trading model.
- **Rip-or-flip analysis** — Compare sealed product price vs EV of contents. "Prismatic Evolutions ETB: $193 sealed, 9 packs × $30.41 EV = $274 expected — rip it." Data: 1,740 sealed products + pack EV.
- **Grading ROI calculator** — Raw vs PSA 10 price spread minus grading fees and expected grade distribution. Data: 596 cards with ungraded/Grade 9/PSA 10 prices.
- **Price-to-rarity scatter** — Plot price vs rarity tier across sets. Find outlier commons worth more than ultra rares, or underpriced SIRs.
- **Cross-set rarity comparison** — Which set has the cheapest SIRs? Most expensive? Helps decide which sealed product to buy.
- **Pack value distribution** — Already computed in EV engine. Surface as a tool: probability of $10+, $50+, $100+ packs.

### Medium effort (some new data/logic needed)
- **Portfolio tracker** — User inputs owned cards, system sums market value. Track over time with daily TCGCSV snapshots (needs price history table).
- **Price alerts** — Store target prices, compare against daily refresh, notify via Telegram when a card drops below threshold.
- **Arbitrage finder** — Compare TCGCSV (TCGPlayer) vs PriceCharting (eBay) prices for the same card. Flag meaningful spreads. Both sources already in DB.
- **Sealed product trend tracker** — Snapshot sealed_products daily, build price history. Track which ETBs/boxes are appreciating.

### Bigger builds
- **Pack opening simulator** — Monte Carlo with exact pull rates. "Simulate 100 packs of Prismatic Evolutions" → histogram, probability of profit, best/worst case.
- **Market intelligence dashboard** — Daily price deltas, biggest movers, set-level trend aggregates. Needs price history over time.
- **Rotation impact analyzer** — Track sets approaching Standard rotation, model expected price impact from historical rotation data.

## Tech stack

- Python 3, Flask, SQLite (WAL mode)
- Card data: [PokemonTCG/pokemon-tcg-data](https://github.com/PokemonTCG/pokemon-tcg-data)
- Pricing: [TCGCSV](https://tcgcsv.com) (bulk TCGPlayer), [PokeTrace API](https://poketrace.com) (condition/trend), [TCGdex API](https://tcgdex.dev) (Cardmarket EUR)
- No external dependencies beyond `flask` and `requests`

## License

MIT
