# Investment Research Tools — Plan

Three new tools focused on Pokemon card investing analysis.

---

## Prerequisite: Backfill All-Era Pricing

**Current state:** Only SV-era sets (16 sets, 2023-2025) have card prices and sealed products in the DB. The other 155 sets have cards imported but zero prices.

**Fix:** Run `python3 cli.py bulk-prices --all`. TCGCSV has data for all eras back to Base Set (1999). This single command will:
- Price cards across all 171 sets (currently only 16 are priced)
- Import sealed products (including loose booster packs) for all eras
- Takes ~90 seconds, free, no auth

**Verified:** TCGCSV has booster pack prices going back to 1999:
| Set | Year | Booster Pack Price |
|-----|------|--------------------|
| Base Set (Unlimited) | 1999 | $652.72 |
| Jungle (Unlimited) | 1999 | $284.29 |
| Fossil (Unlimited) | 1999 | $251.64 |
| Neo Genesis (Unlimited) | 2000 | $598.50 |
| Diamond & Pearl | 2007 | $214.84 |
| Sun & Moon | 2017 | $17.36 |
| Sword & Shield | 2020 | $7.94 |

This prerequisite unlocks Tools A and B with no new code needed beyond the existing `bulk-prices` command.

---

## Tool A: Sealed Pack Investment ROI Tracker

**Question it answers:** "If I bought a loose booster pack at release for $4 MSRP, what's my annualized return today?"

### Data available (after backfill)
- `sealed_products` table: booster pack market prices from TCGCSV
- `sets` table: release dates going back to 1999
- Assume flat $4 MSRP cost basis for all packs (per Kirk)

### Filtering logic
TCGCSV lists many variants per set (sleeved, bundles, code cards, 1st edition). Need to identify the **single loose unlimited booster pack** per set:
- Exclude: code cards, art bundles, sleeved packs, 1st edition, bundle sets
- Prefer: the plain "[Set Name] Booster Pack" or "[Set Name] Booster Pack [Unlimited Edition]"
- Fallback: cheapest non-code booster_pack product

### Math
```
years_held = (today - release_date) / 365.25
total_return = (current_price / 4.00) - 1
annualized_roi = (current_price / 4.00) ^ (1 / years_held) - 1
```

### Tasks

#### A1: Backend — pack investment calculator
- New function `get_pack_investment_data()` in `engine/set_analysis.py`
- Query: join `sealed_products` (type=booster_pack) with `sets` (release_date)
- Filter to one loose pack per set (name heuristics above)
- Calculate: current value, total return %, annualized ROI %, years held
- Return list sorted by release_date
- Files: `engine/set_analysis.py`

#### A2: API endpoint
- `GET /api/investment/packs` — returns all pack investment data as JSON
- Optional query params: `?era=sv&min_year=2000`
- Files: `app.py`

#### A3: Frontend — pack investment page
- New `/investment/packs` route and template
- **Chart 1:** Scatter/line — X=release year, Y=current pack value (log scale). Each dot is a set. Hover shows set name + price + ROI.
- **Chart 2:** Bar chart — annualized ROI % by release year, color-coded (green = beat S&P, red = underperformed)
- **Table:** Sortable by set name, year, current price, total return %, annualized ROI %
- Reference line: S&P 500 historical ~10% annualized for comparison
- Files: `app.py`, `templates/pack_investment.html` (new), `static/style.css`

---

## Tool B: Chase Card Appreciation Tracker

**Question it answers:** "How do the most valuable cards in each set trend over time? Are recent chase cards more or less valuable than vintage ones?"

### Data available (after backfill)
- `prices.tcg_market` for all cards
- `sets.release_date` for timeline
- Already have MAX(tcg_market) working — sv8pt5 Umbreon ex at $1,104, Base Set Charizard at $525

### Analysis
- Most valuable card per set (raw, ungraded market price)
- Average of top 3 and top 10 cards per set (reduces single-card outlier noise)
- Group by release year for trend visualization
- Compare: are modern chase cards (SIRs, $500-1100) more or less valuable than vintage chase cards (holos, $150-525)?

### Tasks

#### B1: Backend — chase card analysis
- New function `get_chase_card_trends()` in `engine/set_analysis.py`
- Query: for each set, get top 1 / top 3 / top 10 most expensive cards
- Join with sets for release_date, era
- Return: set name, year, era, top_1_price, top_1_card_name, top_3_avg, top_10_avg
- Files: `engine/set_analysis.py`

#### B2: API endpoint
- `GET /api/investment/chase-cards` — returns chase card trend data
- Optional: `?era=sv&top_n=3`
- Files: `app.py`

#### B3: Frontend — chase card trends page
- New `/investment/chase-cards` route and template
- **Chart:** Scatter plot — X=release year, Y=price (log scale). Three series: top 1, top 3 avg, top 10 avg. Connect dots chronologically for trend line.
- **Table:** Every set with its #1 card name + price, top 3 avg, top 10 avg, sortable
- Insights box: "Average #1 chase card across all sets: $X. Modern SV-era: $Y. Vintage: $Z."
- Files: `app.py`, `templates/chase_cards.html` (new), `static/style.css`

---

## Tool C: PSA Pop Report Pricing Tool

**Question it answers:** "Which PSA 10 cards are undervalued relative to their population? What's the ROI of grading a raw card to each PSA tier?"

### Data challenge — this is the hard one

**What we need but don't have:**
1. **PSA population data** (how many PSA 7/8/9/10 exist for each card)
2. **PSA grade-specific prices** (what does a PSA 7 vs PSA 10 sell for)

**What we have:**
- 0 cards with graded_prices data currently
- The `graded_prices` TEXT column exists in the prices table but is empty
- The `price_detail` JSON from PokeTrace has condition tiers (NM/LP/MP) but NOT PSA grades

### Data source options

#### Option 1: PriceCharting (recommended for prices)
- PriceCharting.com has PSA-graded prices for thousands of Pokemon cards
- Has PSA 10, PSA 9, PSA 8, ungraded prices
- No official API, but structured URLs: `https://www.pricecharting.com/game/pokemon-<set>/<card-name>`
- Could scrape or use their CSV export (they sell bulk data access)
- **Verdict:** Best free source for graded PRICES. Scraping is feasible at our scale.

#### Option 2: PSA Pop Reports (required for population)
- PSA publishes pop reports at `https://www.psacard.com/pop/tcg-cards/pokemon/`
- Each set has an HTML table with PSA 1-10 population counts per card
- No API. Must scrape.
- Set pages are structured: `/pop/tcg-cards/pokemon/<set-slug>/<set-id>`
- **Verdict:** The ONLY source for official PSA population data. Must scrape.

#### Option 3: eBay sold listings (supplement for prices)
- eBay API has completed item search
- Could get recent sold prices for "Pokemon [card] PSA 10"
- Good for validation but noisy data
- **Verdict:** Supplementary, not primary.

#### Option 4: Manual CSV import (fallback)
- PSA allows exporting pop report data
- User uploads CSV, we parse and store
- **Verdict:** Viable fallback if scraping is too fragile.

### Recommended approach
1. **Scrape PSA pop reports** for population data (one request per set, ~170 requests total)
2. **Scrape PriceCharting** for graded prices (PSA 10, PSA 9, ungraded per card)
3. Store in new tables, map to our existing card IDs by set + card number
4. If scraping proves unreliable, add manual CSV import as fallback

### New schema

```sql
CREATE TABLE IF NOT EXISTS psa_pop (
    card_id TEXT NOT NULL,
    psa_1 INTEGER DEFAULT 0,
    psa_2 INTEGER DEFAULT 0,
    psa_3 INTEGER DEFAULT 0,
    psa_4 INTEGER DEFAULT 0,
    psa_5 INTEGER DEFAULT 0,
    psa_6 INTEGER DEFAULT 0,
    psa_7 INTEGER DEFAULT 0,
    psa_8 INTEGER DEFAULT 0,
    psa_9 INTEGER DEFAULT 0,
    psa_10 INTEGER DEFAULT 0,
    total_graded INTEGER DEFAULT 0,
    last_updated TEXT,
    PRIMARY KEY (card_id),
    FOREIGN KEY (card_id) REFERENCES cards(id)
);

CREATE TABLE IF NOT EXISTS graded_prices (
    card_id TEXT NOT NULL,
    grade TEXT NOT NULL,          -- 'PSA 10', 'PSA 9', 'PSA 8', 'PSA 7', 'RAW'
    market_price REAL,
    last_sale REAL,
    price_source TEXT,            -- 'pricecharting', 'ebay', 'manual'
    last_updated TEXT,
    PRIMARY KEY (card_id, grade),
    FOREIGN KEY (card_id) REFERENCES cards(id)
);
```

### Tasks

#### C1: Schema — psa_pop and graded_prices tables
- Add tables to `database/schema.py`
- Migration script for live DB
- Files: `database/schema.py`

#### C2: PSA pop report scraper
- New `importers/psa_scraper.py`
- Scrape `psacard.com/pop/tcg-cards/pokemon/<set>/<id>` per set
- Parse HTML table: card name, card number, PSA 1-10 counts
- Match to our card IDs by set_id + number
- Rate limit: 1 req/3 sec (be respectful)
- CLI: `python3 cli.py import-psa-pop --set <id|all>`
- Files: `importers/psa_scraper.py` (new), `cli.py`

#### C3: Graded price scraper
- New `importers/graded_price_scraper.py`
- Source: PriceCharting or eBay sold listings
- Get PSA 7, 8, 9, 10 and raw/ungraded prices per card
- CLI: `python3 cli.py import-graded-prices --set <id|all>`
- Files: `importers/graded_price_scraper.py` (new), `cli.py`

#### C4: Backend — PSA analysis engine
- New function `get_psa_analysis(set_id=None)` in `engine/set_analysis.py`
- Metrics per card:
  - Pop count per grade (PSA 7/8/9/10)
  - Price per grade
  - Grade premium = (PSA 10 price / raw price) — measures grading upside
  - Pop-adjusted value score = price / log(pop + 1) — finds undervalued low-pop cards
  - Grading ROI per tier = (graded_price - raw_price - grading_fee) / (raw_price + grading_fee)
- Cross-set sorting: find the lowest-pop PSA 10s, highest grade premiums, best grading ROI
- Files: `engine/set_analysis.py`, `config.py` (grading fee constants)

#### C5: API endpoints
- `GET /api/psa/cards` — sortable PSA card data (pop, prices, scores)
  - Query params: `?sort=pop_score&grade=10&set_id=sv8pt5&min_price=10`
- `GET /api/psa/set/<id>` — PSA data for one set
- `GET /api/psa/undervalued` — top undervalued cards by pop-adjusted score
- Files: `app.py`

#### C6: Frontend — PSA pop report page
- New `/psa` route and template
- **Main table:** All PSA-graded cards, sortable by:
  - PSA 10 pop (ascending = rarest)
  - PSA 10 price
  - Pop-adjusted value score (ascending = most undervalued)
  - Grade premium (PSA 10 / raw)
  - Grading ROI %
- **Filters:** Set, era, min price, grade level (7/8/9/10)
- **Columns:** Card name, set, PSA 10 pop, PSA 9 pop, PSA 10 price, PSA 9 price, raw price, grade premium, pop score
- **Highlight:** Cards with low pop + low price relative to similar-pop cards (the "undervalued" thesis)
- **Chart:** Scatter — X=PSA 10 population (log), Y=PSA 10 price (log). Outliers below the trend line are undervalued.
- Files: `app.py`, `templates/psa.html` (new), `static/style.css`

---

## Build Order

### Chunk 1: Data backfill + Tools A & B (easiest, no new data sources)
1. Run `bulk-prices --all` to populate all eras
2. A1 + A2 + A3: Pack Investment ROI Tracker
3. B1 + B2 + B3: Chase Card Appreciation Tracker

### Chunk 2: PSA schema + scrapers (hardest, new data sources)
4. C1: Schema migration
5. C2: PSA pop report scraper (test with 1-2 sets first)
6. C3: Graded price scraper (test with 1-2 sets first)

### Chunk 3: PSA analysis + frontend
7. C4: PSA analysis engine
8. C5 + C6: API + frontend

### Estimated effort
- **Chunk 1:** Small-medium. Data already exists in TCGCSV. Just queries + charts.
- **Chunk 2:** Medium-large. Web scraping is inherently fragile. PSA and PriceCharting may change HTML structure. Need fallback strategies.
- **Chunk 3:** Medium. Analysis math is straightforward once data is in the DB.

---

## Open Questions

1. **PSA scraping legality/ToS:** PSA's ToS may prohibit automated scraping. If so, manual CSV import is the fallback. Worth checking before building C2.
2. **PriceCharting access:** They sell bulk data. Might be worth $20-30 for a clean CSV dump instead of scraping. Check pricing.
3. **Which eras matter for PSA?** Vintage (Base-Neo) and modern hype sets (Prismatic Evolutions, 151) are where PSA grading is most active. Could start with just those ~30 sets instead of all 171.
4. **Grading fee tiers:** PSA economy ($20), regular ($50), express ($100), walkthrough ($300). Should be configurable in config.py. Default to $20 economy.
5. **Pack MSRP history:** $4 flat is a simplification. Actual MSRP was $3.29 for WOTC era, $3.99 for most of ex/DP/BW/XY, $4.49 for SM/SWSH/SV. Could refine later.
