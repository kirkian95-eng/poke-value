# Decisions

Architecture decisions, tradeoffs, and rationale for poke-value.

---

## #22 Rip-or-Flip Reads Cache, Not Recalculate

**Date:** 2026-03-07

**Decision:** `get_rip_or_flip()` now reads EV from `ev_cache` instead of calling `calculate_set_ev()` on every invocation. Only recalculates if no cache exists.

**Why:** The rip-or-flip page loops over every set with sealed products. Calling `calculate_set_ev()` per set was doing full EV recalculation + DB write for each one — dozens of sets. This turned a simple read-heavy page into a write-heavy one that also clobbered cache timestamps.

**Tradeoff:** EV data shown may be slightly stale if cache was built from an earlier price update. This is acceptable since the cron job rebuilds EV cache during price updates.

---

## #21 Graded EV Model — Multiplier Approach

**Date:** 2026-03-07

**Decision:** Use era-based grade multipliers (PSA 10 = 2.5x raw for modern, 12x for vintage) combined with PSA pop-derived grade distributions, rather than requiring per-card graded prices. Falls back to actual graded prices from `graded_prices` table when available (currently 20 cards).

**Why:** We only have per-card graded prices for 20 cards, but 4,427 cards have PSA pop data. The multiplier approach gives useful estimates for all sets. The multipliers were calibrated from the 20-card sample (e.g., PSA 10 avg = 18x raw across our data, but capped at 12x for vintage and 2.5x for modern to be conservative).

**Tradeoff:** Multipliers are rough averages — actual grading premiums vary wildly by card. A Charizard PSA 10 is 39x raw, while a common holo might only be 2x. As we scrape more graded prices from PriceCharting, the model will improve by using more real data and fewer multiplier fallbacks.

---

## #20 Real Pack Prices vs Hardcoded MSRP

**Date:** 2026-03-07

**Decision:** EV cache now looks up the cheapest non-code, non-sleeved, non-case "Booster Pack" product from `sealed_products` for each set. Falls back to $4.49 MSRP only for current SV/Mega era sets (still in print). Sets without sealed data get `pack_price = NULL`.

**Why:** Hardcoded $4.49 was wildly misleading for vintage sets. A Base Set pack costs $652, so showing "$47 EV vs $4.49 MSRP = 1044% value ratio" was wrong — it should be "7.2% value ratio (you're paying for collectibility, not card value)." Real pack prices from TCGPlayer sealed data give accurate economics.

**Tradeoff:** ~30 vintage sets have no sealed pack data in our DB and get NULL pack price (no value ratio shown). This is better than showing a fake $4.49. Could be improved by scraping more sealed data.

---

## #19 Sealed Value Auto-Detection vs Manual Mapping

**Date:** 2026-03-07

**Decision:** Auto-detect booster boxes (36 packs), enhanced boxes (30), ETBs (8-9 by era), and UPCs (16) from product_type + name patterns. Only manually map promo card IDs in `PRODUCT_PROMOS` for the small subset of products with valuable promos.

**Why:** Manual `PRODUCT_CONTENTS` mapping required listing every product individually (7 entries covered 7 products). With 159+ qualifying sealed products across all eras, manual mapping doesn't scale. Pack counts are highly predictable from product type — booster boxes are always 36, ETBs are always 8 or 9 (era-dependent), UPCs are always 16.

**Tradeoff:** Some niche products (special collections, tins with unusual pack counts) may be missed or get wrong pack counts. We filter these out with `_SEALED_SKIP` and the minimum 4-pack threshold. Promo card data is incomplete — only mapped for 151 and a few SWSH UPCs — but the tool still works without it (promos just show as $0).

---

## TCGCSV Variant Selection Strategy

**Date:** 2026-03-03

**Decision:** When TCGCSV returns multiple product variants per card number (Normal, Reverse Holofoil, Poke Ball Pattern, Master Ball Pattern), prefer the standard pack-pull version: filter out special variants by name suffix, prefer "Normal" subtype, then pick the cheapest remaining option.

**Why:** TCGPlayer lists multiple products per card (standard, Poke Ball Pattern, Master Ball Pattern). They share the same extNumber but have wildly different prices (Umbreon: standard $0.27 vs Master Ball $57.44). Without filtering, the importer was storing whichever came last in the CSV, which was often the most expensive special variant. This inflated EV calculations by 10-100x.

**Tradeoff:** The heuristic (name suffix filtering + cheapest) could theoretically pick the wrong variant for unusual cards. But it's always better than the previous "last wins" approach. Special variants are excluded from EV calculations since you can't pull a Master Ball Pattern card from a regular booster pack.

---

## Pull Rate Normalization

**Date:** 2026-03-03

**Decision:** After loading pull rate templates, redistribute orphaned probability (from rarities not present in a set) to the base Rare slot, then normalize hit_slot total to 1.0.

**Why:** Era templates define pull rates for all possible rarities (e.g., ACE SPEC Rare), but not every set has every rarity. Without redistribution, probability leaked — sv8pt5 had only 88.4% of hit slots accounted for. In reality, every pack has exactly one hit card, so the total must be 1.0. The missing probability most accurately goes to Rare (the most common hit).

---

## 1. Data Source: GitHub JSON Repo vs Live API

**Date:** 2026-02-28

**Decision:** Import card data from `PokemonTCG/pokemon-tcg-data` GitHub repo as a one-time operation, stored in local SQLite.

**Why:** Card data is static — a Bulbasaur from 151 never changes. Importing once avoids rate limits, API dependencies, and latency. Only new set releases require re-importing. The pokemontcg.io API is dead/migrated to paid Scrydex ($29/month), so a live API isn't viable anyway.

**Tradeoff:** When new sets release, you must manually run `python3 cli.py import-cards --set <new_set_id>`. This is a 5-second operation.

---

## 2. Pricing: Multi-Source with Priority

**Date:** 2026-02-28 (initial: TCGdex only), 2026-03-02 (PokeTrace added)

**Decision:** Use multiple pricing APIs with priority: PokeTrace (USD, TCGPlayer + eBay) > TCGdex (EUR, Cardmarket). TCGdex is the free baseline; PokeTrace overlays higher-quality USD data.

**Why (TCGdex):** Free, no API key, unlimited requests. Cardmarket EUR prices converted to USD at 1.08x. Only free working pricing API as of Feb 2026.

**Why (PokeTrace):** TCGdex only has Cardmarket EUR data for SV-era sets — no TCGPlayer USD. PokeTrace provides real TCGPlayer market prices, which is what US buyers actually pay. Free tier gives 250 calls/day, which is enough to gradually build coverage.

**Tradeoff:** Cardmarket EUR and TCGPlayer USD can diverge 10-20% for the same card. When both are available, TCGPlayer USD (via PokeTrace) is used for EV since that's the relevant market for US buyers. Cardmarket data is still stored for reference.

**Alternatives rejected:**
- Scraping TCGPlayer directly — fragile and against ToS
- pokemontcg.io API — dead, migrated to paid Scrydex ($29/month)
- PokéWallet API — returns 404s as of Feb 2026

---

## 3. EV Math: Closed-Form, Not Simulation

**Date:** 2026-02-28

**Decision:** Compute EV using exact analytical math. No Monte Carlo simulation.

**Why:** A pack has a finite, enumerable set of outcomes. The hit slot can land on any card of each eligible rarity, and each outcome has a known probability. Summing `P(card) × price(card)` over all cards gives the mathematically exact EV. This is faster, deterministic, and provably correct — a 10,000-pack simulation would introduce sampling noise for no benefit.

**Model:**
- Guaranteed slots (commons, uncommons): `EV = Σ (guaranteed_count / N_rarity) × price`
- Hit slot (rare+): `EV = Σ (P_rarity / N_rarity) × price` for each card
- Reverse holo: uniform draw from common/uncommon/rare pool, 50% price multiplier
- God pack: `EV_final = (1 - P_god) × EV_normal + P_god × EV_god_pack`

**Tradeoff:** Reverse holo pricing uses a 50% approximation since no API distinguishes reverse holo variants. This slightly underestimates reverse holo EV for desirable commons/uncommons, but the error is small (reverse holos are typically $0.10-$0.50).

---

## 4. Pull Rates: Era-Based Templates + Per-Set Overrides

**Date:** 2026-02-28

**Decision:** Seed default pull rates by era (SV, SWSH, SM), allow per-set overrides in `pull_rate_overrides` table.

**Why:** The Pokemon Company doesn't publish official pull rates. Community data (PokeBeach, Reddit) shows rates vary by set but cluster around era averages. The template/override system means adding a new SV set requires zero configuration — defaults auto-apply. Only sets with unusual distributions (151, Prismatic Evolutions) need manual overrides.

**Tradeoff:** Default rates are estimates. SV-era hit slot probabilities sum to 0.974 (not exactly 1.0) — the remaining 0.026 is absorbed by the base Rare probability. For precise analysis, override the specific set's rates from PokeBeach data.

---

## 5. Database: SQLite, Not PostgreSQL

**Date:** 2026-02-28

**Decision:** Single SQLite file (`pokemon_tcg_ev.db`), WAL mode.

**Why:** Single-user tool. SQLite handles concurrent Flask reads with WAL. No separate DB process, no credentials, trivially portable (copy the .db file). The entire database with 20K cards + full PokeTrace price JSON is under 10MB.

---

## 6. Frontend: Flask + Jinja2, Set Logos Only

**Date:** 2026-02-28

**Decision:** Server-rendered HTML with Flask. Only display set logo images (~170), not individual card images (20K+).

**Why:** Card images aren't needed for the prototype — the focus is on EV calculations and data tables. Set logos provide enough visual identity. Avoids CDN/caching complexity.

**Tradeoff:** No card art in tables. Could be added later via `image_url_small` already in the database.

---

## 7. God Pack: Separate Table, JSON Composition

**Date:** 2026-02-28

**Decision:** God packs stored in a dedicated `god_packs` table with JSON `composition` field.

**Why:** God packs vary wildly — 151 has demi god packs (2 IR + 1 SIR), Prismatic Evolutions has three tiers (Full: 9 SIRs, Demi: 3 SIRs + 7 RH, Master Ball), Ascended Heroes has a different mix. A rigid schema can't capture this. JSON composition allows rarity-based rules:
```json
[{"rarity": "Illustration Rare", "count": 5}, {"rarity": "Special Art Rare", "count": 4}]
```

---

## 8. PokeTrace Set Slug Matching: Word Overlap + Validation

**Date:** 2026-03-02

**Decision:** Match our set names to PokeTrace slugs using word overlap scoring with era awareness, falling back to card-count validation for ambiguous matches.

**Why:** PokeTrace has multiple entries per TCG set — the same set appears as a generic name ("151"), a Japanese set code ("SV2a: Pokemon Card 151"), and an English marketing name ("SV: Scarlet & Violet 151"). Only the English entry has cards with prices. Simple substring matching picks the wrong one (e.g., our set "Scarlet & Violet" matches "SV: Scarlet & Violet 151" because the name is a substring).

**Algorithm:**
1. Search PokeTrace by our set name
2. Score each result by word overlap ratio (penalizes extra words) + era tag presence in slug
3. If top two candidates have the same score, validate by fetching 1 card from each — pick the one that actually returns data
4. Cache the winning slug in `card_id_map` so it's never looked up again

**Tradeoff:** The validation step costs 1-2 extra API calls per ambiguous set, but only happens once per set (cached afterward). Worth it vs. silently matching the wrong set and getting 0 prices.

---

## 9. PokeTrace Card Number Format: Split on "/"

**Date:** 2026-03-02

**Decision:** Match card numbers by stripping the "/total" suffix from PokeTrace format.

**Why:** Our database stores card numbers as "166" (from the GitHub data source). PokeTrace stores them as "166/165". Comparing `"166" == "166/165"` fails. Splitting on "/" and comparing the first part handles this without knowing the total.

---

## 10. Full Price Data Retention: JSON Blob Column

**Date:** 2026-03-02

**Decision:** Store the complete PokeTrace price response as JSON in a `price_detail` TEXT column, alongside the flat columns used for EV calculation.

**Why:** PokeTrace returns ~80 data points per card: 5 condition tiers (NM/LP/MP/HP/DMG) × 2 marketplaces (TCGPlayer + eBay) × 8 metrics (avg, low, high, saleCount, lastUpdated, avg1d, avg7d, avg30d). The EV calculator only needs NEAR_MINT TCGPlayer avg, but discarding the rest would be wasteful — condition-based pricing, eBay arbitrage analysis, and trend tracking all need the full data.

**Tradeoff:** Database grows by ~1KB per priced card (compressed JSON). For 20K cards that's ~20MB — trivial for SQLite. The alternative (80 columns, or a separate normalized table) would be far more complex for minimal benefit.

---

## 11. Zero-Token Cron Pricing: Standalone Script

**Date:** 2026-03-02

**Decision:** Daily price updates run as a standalone Python cron script, completely independent of OpenClaw/Stephen.

**Why:** Kirk specifically asked for automation that doesn't use AI inference tokens. The script is pure Python — reads/writes SQLite, calls the PokeTrace API, manages its own rate limit budget. Runs via system crontab at 1am UTC daily. No Node.js, no AI framework, no token cost.

**Design choices:**
- Budget of 240/day (saves 10 of 250 as buffer for manual queries)
- Prioritizes SV-era Special Illustration Rares first (highest-value cards get accurate prices first)
- Caches PokeTrace UUIDs in `card_id_map` — first pass costs 2 calls/card, repeat passes cost 1
- Recalculates EV for any set that got new prices
- Writes status JSON to `/tmp/pokemon-price-status.json` for monitoring
- Rate limit resets at midnight UTC; cron runs at 1am UTC to start with fresh budget

**Timeline:** ~13,800 cards across SV/SWSH/SM/XY/BW/DP eras. First pass at 240/day = ~58 days for full coverage. SV era (3,250 cards, highest priority) = ~26 days.

---

## 12. NEAR_MINT as Primary EV Price

**Date:** 2026-03-02

**Decision:** Use NEAR_MINT TCGPlayer price as the primary value for EV calculations, falling back to LIGHTLY_PLAYED.

**Why:** Cards pulled from sealed packs are pack-fresh, which is Near Mint condition. NM is the standard grading baseline for sealed product analysis. Using LIGHTLY_PLAYED or lower would understate the EV of what you're actually pulling.

**Tradeoff:** NM prices are the highest condition tier, so EV calculations are slightly optimistic — if you damage a card or can't sell at NM due to market conditions, realized value will be lower. This is standard practice in sealed product analysis.

---

## 13. TCGCSV as Primary Bulk Price Source

**Date:** 2026-03-02

**Decision:** Use TCGCSV (tcgcsv.com) as the primary bulk pricing source. It mirrors TCGPlayer's entire product catalog as free CSV files — no auth, no rate limit, unlimited requests.

**Why:** TCGCSV solves the biggest problem we had: getting TCGPlayer USD prices at scale without burning API calls. One HTTP request per set gives market/low/mid/high/directLow prices for every card AND every sealed product (booster boxes, ETBs, tins, etc.). We priced 16,896 cards across 132 sets in ~90 seconds with zero API keys.

**URL pattern:** `https://tcgcsv.com/tcgplayer/3/{groupId}/ProductsAndPrices.csv`
- Category 3 = Pokemon
- groupId mapped from our set names via `Groups.csv`
- CSV columns: productId, name, extNumber, marketPrice, lowPrice, midPrice, highPrice, directLowPrice

**How it fits with other sources:**
- **TCGCSV**: Bulk pricing backbone. TCGPlayer USD market/low/mid/high for all cards + sealed products. Updated frequently.
- **PokeTrace**: Overlay for premium data. Adds condition breakdowns (NM/LP/MP/HP/DMG), eBay prices, sale counts, 7d/30d trends. 250/day free tier, used for high-value cards.
- **TCGdex**: Cardmarket EUR data. Useful for EU market comparison.

**Tradeoff:** TCGCSV provides a single price point per card (presumably NM/market) — no condition breakdowns or trend data. PokeTrace is still needed for that deeper analysis. TCGCSV also doesn't distinguish between print variants (normal vs reverse holo vs holofoil) in the same way PokeTrace does — it reports the cheapest available printing. For EV calculations this is actually fine since we want the base card value.

**Sealed products:** TCGCSV is the only source that gives us sealed product pricing. We classify products by type (booster_box, etb, collection, tin, blister, etc.) and store them in a dedicated `sealed_products` table. This enables rip-or-flip analysis: compare sealed market price vs EV of contents.

---

## 14. Sealed Products Table: Separate from Cards

**Date:** 2026-03-02

**Decision:** Store sealed product prices in a dedicated `sealed_products` table, separate from the `cards`/`prices` tables.

**Why:** Sealed products are fundamentally different from cards — they don't have rarities, pull rates, or card numbers. They represent the *input* to EV calculations (what you pay), not the *output* (what you pull). Mixing them with cards would complicate every query.

**Schema:** `sealed_products(set_id, name, product_type, tcg_market, tcg_low, tcg_mid, tcg_high, tcg_direct_low, tcgplayer_product_id, last_updated)`. Product types are classified from the name: booster_box, etb, collection, tin, blister, booster_pack, booster_bundle, build_battle, league, deck, other.

**Tradeoff:** Requires a separate import path and table, but the data model is cleaner. Enables future features like rip-or-flip analysis, sealed product trend tracking, and arbitrage between sealed product types.

---

## 15. Frontend Strategy: Flask + Jinja2 + Chart.js, Not React

**Date:** 2026-03-02

**Decision:** Build all frontend features using Flask server-rendered templates with Jinja2, vanilla JavaScript, and Chart.js (CDN) for visualizations. No React, no build pipeline, no npm.

**Why:** The existing app already has 4 working templates with a consistent dark theme, filters, sorting, and a histogram — all in vanilla JS. Adding React would mean: a build step (webpack/vite), a Node.js dependency, a separate dev server, and rewriting all existing templates. The features on the roadmap (tables, charts, forms, comparison views) are well within what server-rendered HTML + Chart.js can handle.

**Chart.js:** Added via CDN for scatter plots, line charts (price history), bar charts (distributions), and pie charts (portfolio breakdown). Shared theme helper (`static/charts.js`) ensures consistent dark-theme styling across all charts.

**When to reconsider:** If we add real-time features (live price updates, WebSocket-driven dashboards) or highly interactive tools (drag-and-drop deck builder), a client-side framework would make sense. For now, every feature is request-response with optional JS enhancement.

**Tradeoff:** No client-side routing (each page is a full page load), no component reuse across pages (Jinja2 macros and includes handle this adequately), and interactive features require more manual DOM manipulation. But: zero build step, zero Node dependencies, instant deploys, and the entire frontend is readable by anyone who knows HTML.

---

## 16. Grade Distribution for Grading ROI Calculator

**Date:** 2026-03-07

**Decision:** Use fixed community-average grade distribution: 15% PSA 10, 40% PSA 9, 25% PSA 8, 10% PSA 7, 5% PSA 6, 3% PSA 5, 2% PSA 4. Normalize when not all grades have prices.

**Why:** PSA does not publish official grade distribution data. These percentages are community estimates from Pokemon card grading forums and YouTube sample sets. They assume pack-fresh cards submitted for grading (not already-damaged cards). The actual distribution varies by card age, set quality, and centering — modern cards tend to grade higher. But a fixed distribution gives a useful baseline ROI estimate.

**Tradeoff:** A card that consistently grades PSA 10 at 30% would show lower expected value than reality. Could add per-card or per-era grade distributions in the future. The fee selector (JS-based, $20/$50/$100/$150) lets users adjust the other major variable without a page reload.

---

## 17. Arbitrage Data Source Limitations

**Date:** 2026-03-07

**Decision:** Arbitrage finder compares TCGPlayer market price (TCGCSV) vs PriceCharting ungraded price (from graded_prices table). Currently limited to ~20 cards that have both data sources.

**Why:** TCGPlayer and PriceCharting/eBay can have meaningful price differences for the same card. TCGPlayer reflects listing prices; PriceCharting reflects eBay sold prices. The spread is actionable but must account for platform fees (13% eBay, 12% TCGPlayer) and shipping. Coverage will grow as more PriceCharting data is imported via `import-psa-pop --prices`.

---

## 18. Rarity Rank Mapping for Scatter Plots

**Date:** 2026-03-07

**Decision:** Map all 38 observed rarity types to 9 tiers (1=Common through 9=Hyper Rare) for the price-vs-rarity scatter plot Y-axis. Unmapped rarities default to tier 3 (Rare).

**Why:** Pokemon TCG has used inconsistent rarity names across eras (e.g., "Rare Ultra" vs "Ultra Rare", "Rare Shiny" vs "Shiny Rare"). A numeric tier system normalizes these for cross-era visualization. The mapping was built by reviewing all 38 rarity types in the database and grouping by approximate pull rate and value tier.
