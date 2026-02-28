# Decisions

Architecture decisions, tradeoffs, and rationale for the Pokemon TCG EV Calculator.

---

## 1. Data Source: GitHub JSON Repo vs Live API

**Decision:** Import card data from `PokemonTCG/pokemon-tcg-data` GitHub repo as a one-time operation, stored in local SQLite.

**Why:** Card data is static — a Bulbasaur from 151 never changes. Importing once avoids rate limits, API dependencies, and latency. Only new set releases require re-importing. The pokemontcg.io API is dead/migrated to paid Scrydex ($29/month), so a live API isn't viable anyway.

**Tradeoff:** When new sets release, you must manually run `python3 cli.py import-cards --set <new_set_id>`. This is a 5-second operation.

---

## 2. Pricing: TCGdex API (Cardmarket EUR)

**Decision:** Use TCGdex API (`api.tcgdex.net/v2/en`) for pricing. Free, no API key, unlimited requests.

**Why:** pokemontcg.io is dead. PokéWallet API returns 404s. TCGdex is the only free, working API with pricing data as of Feb 2026. Prices come from Cardmarket (EUR) and are converted to USD at 1.08x.

**Tradeoff:** Cardmarket EUR prices may differ from TCGPlayer USD prices by 10-20%. TCGPlayer data appears in TCGdex responses for some sets (SWSH era) but not others (SV era). When a working USD API emerges, the price_updater.py already has the PokéWallet scaffolding ready to plug in.

**Alternative considered:** Scraping TCGPlayer directly — rejected as fragile and against ToS.

---

## 3. EV Math: 3-Slot Model

**Decision:** Model pack EV using three slot types: guaranteed (commons/uncommons), hit slot (rare+ with probability distribution), and reverse holo.

**Why:** This matches the actual physical pack composition. Modern packs have 4 commons, 3 uncommons, 2 reverse holos, and 1 "rare slot" that can upgrade based on pull rates. Modeling it this way makes the probabilities auditable.

**Math:**
- Guaranteed: P(specific card) = cards_per_slot / N_cards_of_rarity
- Hit slot: P(specific card) = P(rarity) / N_cards_of_rarity
- Reverse holo: P(specific card) = 2 / N_eligible × 0.5 price multiplier
- God pack: EV_total = (1 - P_god) × normal_EV + P_god × god_pack_EV

**Tradeoff:** Reverse holo pricing uses a 50% approximation since APIs don't distinguish reverse holo variants. This slightly underestimates reverse holo EV for desirable commons/uncommons.

---

## 4. Pull Rates: Era-Based Templates + Per-Set Overrides

**Decision:** Seed default pull rates by era (SV, SWSH, SM), allow per-set overrides in `pull_rate_overrides` table.

**Why:** The Pokemon Company doesn't publish official pull rates. Community data (PokeBeach, Reddit) shows rates vary by set but cluster around era averages. The template/override system means adding a new SV set requires zero configuration — defaults auto-apply. Only sets with unusual distributions (151, Prismatic Evolutions) need manual overrides.

**Tradeoff:** Default rates are estimates. The SV-era hit slot probabilities sum to 0.974 (not exactly 1.0) — the remaining 0.026 is absorbed by the base Rare probability in practice. For precise analysis, override the specific set's rates from PokeBeach data.

---

## 5. Database: SQLite, Not PostgreSQL

**Decision:** Single SQLite file (`pokemon_tcg_ev.db`), WAL mode.

**Why:** This is a personal tool, not a multi-user service. SQLite handles concurrent Flask reads fine with WAL. No separate DB process, no credentials, trivially portable (just copy the .db file). The entire database with 20K cards + prices is under 10MB.

---

## 6. Frontend: Flask + Jinja2, Set Logos Only

**Decision:** Server-rendered HTML with Flask. Only display set logo images (~170), not individual card images (20K+).

**Why:** Kirk explicitly said card images aren't needed for the prototype — the focus is on EV calculations and data tables. Set logos provide enough visual identity. This keeps the app lightweight and avoids CDN/caching complexity for thousands of card images.

**Tradeoff:** The card table doesn't show card art. Could be added later by linking to the `image_url_small` field already stored in the database.

---

## 7. God Pack: Separate Table, JSON Composition

**Decision:** God packs stored in a dedicated `god_packs` table with JSON `composition` field describing the pack contents.

**Why:** God packs vary wildly between sets — Pokemon 151 has one type, Prismatic Evolutions has three tiers (Full, Demi, Master Ball). A rigid schema can't capture this variety. JSON composition allows both card-ID-based and rarity-based rules:
```json
[{"rarity": "Illustration Rare", "count": 6}, {"rarity": "Special Illustration Rare", "count": 4}]
```

---

## 8. Stephen Integration: Zero-Token Query Script

**Decision:** Provide Stephen a shell script (`query-ev.sh`) that queries the SQLite database directly, plus a skill file (`SKILL.md`) teaching him how to interpret set name queries.

**Why:** Stephen runs on Gemini Flash and every token costs money. A shell script that reads SQLite and prints a one-line answer costs zero AI tokens for data retrieval — Stephen only spends tokens on interpreting Kirk's message and formatting the response.

**Tradeoff:** Stephen can't trigger price updates or EV recalculations without running Python. The query script is read-only by design — price updates should be run via cron or manually.
