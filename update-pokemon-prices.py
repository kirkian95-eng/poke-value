#!/usr/bin/env python3
"""
Daily PokeTrace price updater — zero AI tokens.
Runs via system cron, uses 250 API calls/day (free tier limit).
Prioritizes SV-era high-value rarities first, then works through the rest.
Caches PokeTrace UUIDs in card_id_map so repeat runs only need 1 call/card.

Usage: update-pokemon-prices.py [--budget N] [--era ERA] [--dry-run]
"""
import argparse
import json
import os
import re
import requests
import sqlite3
import sys
import time
from datetime import datetime

PROJECT_DIR = os.environ.get("POKE_VALUE_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_DIR, "pokemon_tcg_ev.db")
LOG_PATH = "/tmp/pokemon-price-update.log"
STATUS_PATH = "/tmp/pokemon-price-status.json"

API_BASE = "https://api.poketrace.com/v1"
API_KEY = os.environ.get("POKETRACE_API_KEY", "")

# Rarity priority: lower = more valuable = price first
RARITY_PRIORITY = {
    "Special Illustration Rare": 0, "Hyper Rare": 1, "Special Art Rare": 2,
    "Illustration Rare": 3, "Ultra Rare": 4, "ACE SPEC Rare": 5,
    "Shiny Ultra Rare": 6, "Double Rare": 7, "Shiny Rare": 8,
    "Art Rare": 9, "Rare Holo": 10, "Rare": 11,
    "Promo": 12, "Uncommon": 13, "Common": 14,
}

# Era priority: SV first (current), then backward
ERA_PRIORITY = {"sv": 0, "swsh": 1, "sm": 2, "xy": 3, "bw": 4, "dp": 5}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def get_set_slug(conn, set_id, headers, budget):
    """Look up or fetch the PokeTrace set slug. Returns (slug, calls_used)."""
    row = conn.execute(
        "SELECT external_id FROM card_id_map WHERE card_id = ? AND source = 'poketrace_set'",
        (set_id,),
    ).fetchone()
    if row:
        return row["external_id"], 0

    set_row = conn.execute("SELECT name, era FROM sets WHERE id = ?", (set_id,)).fetchone()
    if not set_row or budget < 1:
        return None, 0

    try:
        resp = requests.get(
            f"{API_BASE}/sets",
            params={"search": set_row["name"], "limit": 10},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 429:
            return "rate_limited", 1
        if resp.status_code != 200:
            return None, 1

        sets_list = resp.json().get("data", [])
        if not sets_list:
            return None, 1

        name_lower = set_row["name"].lower()
        era = (set_row["era"] or "").lower()
        era_prefixes = {"sv": "sv", "swsh": "swsh", "sm": "sm", "xy": "xy", "bw": "bw"}
        era_tag = era_prefixes.get(era, "")

        # Normalize words for comparison
        name_words = set(re.findall(r'\w+', name_lower))

        # Score all candidates
        candidates = []
        for s in sets_list:
            s_name = (s.get("name") or "").lower()
            s_slug = s.get("slug", "")
            if name_lower not in s_name and s_name != name_lower:
                continue
            score = 0

            # Word overlap ratio — penalize names with lots of extra words
            s_words = set(re.findall(r'\w+', s_name))
            # Strip era codes from comparison (sv, sv01, swsh, etc.)
            noise = {era_tag} if era_tag else set()
            noise |= {w for w in s_words if re.match(r'^[a-z]+\d+[a-z]?$', w)}  # sv01, sv2a, etc.
            s_content = s_words - noise
            n_content = name_words - noise
            if n_content:
                overlap = len(n_content & s_content) / max(len(n_content), len(s_content))
                score += int(overlap * 30)  # 0-30 based on word match quality

            # Era match in slug
            if era_tag and era_tag in s_slug:
                score += 10

            candidates.append((score, s_slug, s_name))

        # Sort by score descending
        candidates.sort(key=lambda x: -x[0])

        # Pick best candidate — if top 2 have same score, validate with a card fetch
        best_slug = None
        if len(candidates) == 1:
            best_slug = candidates[0][1]
        elif len(candidates) >= 2 and candidates[0][0] > candidates[1][0]:
            best_slug = candidates[0][1]
        elif candidates:
            # Ambiguous — validate by checking which slug has cards
            for score, slug, sname in candidates[:3]:
                try:
                    vresp = requests.get(
                        f"{API_BASE}/cards",
                        params={"set": slug, "limit": 1},
                        headers=headers,
                        timeout=10,
                    )
                    if vresp.json().get("data"):
                        best_slug = slug
                        log(f"  Set slug validated via card check: '{slug}'")
                        break
                    time.sleep(1)
                except Exception:
                    pass
            if not best_slug:
                best_slug = candidates[0][1]

        if best_slug:
            conn.execute(
                "INSERT OR REPLACE INTO card_id_map (card_id, source, external_id) VALUES (?, 'poketrace_set', ?)",
                (set_id, best_slug),
            )
            conn.commit()
            log(f"  Set {set_id} -> slug '{best_slug}'")
        return best_slug, 1
    except Exception as e:
        log(f"  Set slug error for {set_id}: {e}")
        return None, 1


def get_card_uuid(conn, card_id, card_name, card_number, set_slug, headers, budget):
    """Look up or fetch a card's PokeTrace UUID. Returns (uuid, calls_used)."""
    row = conn.execute(
        "SELECT external_id FROM card_id_map WHERE card_id = ? AND source = 'poketrace'",
        (card_id,),
    ).fetchone()
    if row:
        return row["external_id"], 0

    if budget < 1:
        return None, 0

    try:
        resp = requests.get(
            f"{API_BASE}/cards",
            params={"search": card_name, "set": set_slug, "limit": 5},
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return None, 1

        cards_list = resp.json().get("data", [])
        if not cards_list:
            return None, 1

        card_num_str = str(card_number).lstrip("0") or "0"
        uuid = None
        for c in cards_list:
            pt_num = str(c.get("cardNumber", "")).split("/")[0].lstrip("0") or "0"
            if pt_num == card_num_str:
                uuid = c["id"]
                break
        if not uuid:
            uuid = cards_list[0]["id"]

        conn.execute(
            "INSERT OR REPLACE INTO card_id_map (card_id, source, external_id) VALUES (?, 'poketrace', ?)",
            (card_id, uuid),
        )
        conn.commit()
        return uuid, 1
    except Exception:
        return None, 1


def fetch_price(uuid, headers):
    """Fetch all prices for a card UUID. Returns full price dict or status string, and 1 call."""
    try:
        resp = requests.get(f"{API_BASE}/cards/{uuid}", headers=headers, timeout=10)
        if resp.status_code == 429:
            return "rate_limited", 1
        if resp.status_code != 200:
            return None, 1

        all_prices = resp.json().get("data", {}).get("prices", {})
        if not all_prices:
            return None, 1

        # Extract NEAR_MINT TCGPlayer as the "primary" price for EV calculations
        tcgp = all_prices.get("tcgplayer", {})
        primary = {}
        for tier in ["NEAR_MINT", "LIGHTLY_PLAYED"]:
            t = tcgp.get(tier)
            if t and t.get("avg"):
                primary = {
                    "tcg_market": t.get("avg"),
                    "tcg_low": t.get("low"),
                    "tcg_mid": t.get("avg"),
                    "tcg_high": t.get("high"),
                }
                break

        if not primary:
            return None, 1

        # Return primary prices + full JSON for storage
        primary["_full"] = all_prices
        return primary, 1
    except Exception:
        return None, 1


def save_price(conn, card_id, price_data):
    """Upsert PokeTrace price into prices table with full JSON detail."""
    now = datetime.utcnow().isoformat()
    full_json = json.dumps(price_data.pop("_full", {}))
    existing = conn.execute("SELECT * FROM prices WHERE card_id = ?", (card_id,)).fetchone()

    if existing:
        conn.execute("""
            UPDATE prices SET tcg_market=?, tcg_low=?, tcg_mid=?, tcg_high=?,
            price_detail=?,
            price_source=CASE WHEN price_source LIKE '%poketrace%' THEN price_source
                              ELSE 'poketrace+' || COALESCE(price_source,'') END,
            last_updated=? WHERE card_id=?
        """, (
            price_data["tcg_market"], price_data["tcg_low"],
            price_data["tcg_mid"], price_data["tcg_high"],
            full_json, now, card_id,
        ))
    else:
        conn.execute("""
            INSERT INTO prices (card_id, tcg_market, tcg_low, tcg_mid, tcg_high,
                               price_detail, price_source, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, 'poketrace', ?)
        """, (
            card_id, price_data["tcg_market"], price_data["tcg_low"],
            price_data["tcg_mid"], price_data["tcg_high"],
            full_json, now,
        ))


def recalc_ev(set_ids):
    """Recalculate EV for sets that got new prices."""
    if not set_ids:
        return
    sys.path.insert(0, PROJECT_DIR)
    from engine.ev_calculator import calculate_set_ev
    conn = get_db()
    for set_id in set_ids:
        try:
            result = calculate_set_ev(set_id)
            if result and result.get("ev_per_pack"):
                conn.execute("""
                    INSERT OR REPLACE INTO ev_cache (set_id, ev_per_pack, ev_breakdown, pack_price, calculated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    set_id, result["ev_per_pack"],
                    json.dumps(result.get("breakdown", {})),
                    result.get("pack_price", 4.49),
                    datetime.utcnow().isoformat(),
                ))
                log(f"  EV recalc {set_id}: ${result['ev_per_pack']:.2f}/pack")
        except Exception as e:
            log(f"  EV recalc error {set_id}: {e}")
    conn.commit()
    conn.close()


def get_work_queue(conn, era_filter=None):
    """
    Build prioritized list of (set_id, card_id, card_name, card_number, rarity).
    Cards without PokeTrace prices come first, sorted by era priority then rarity priority.
    """
    era_clause = ""
    params = []
    if era_filter:
        era_clause = "AND s.era = ?"
        params.append(era_filter)

    # Cards that don't have PokeTrace-sourced prices yet, or have never been priced
    rows = conn.execute(f"""
        SELECT c.id, c.set_id, c.name, c.number, c.rarity, s.era,
               p.price_source
        FROM cards c
        JOIN sets s ON c.set_id = s.id
        LEFT JOIN prices p ON c.id = p.card_id
        WHERE s.era IN ('sv','swsh','sm','xy','bw','dp')
        {era_clause}
        AND (p.card_id IS NULL OR p.price_source NOT LIKE '%poketrace%')
        ORDER BY c.set_id, c.rarity
    """, params).fetchall()

    # Sort by era priority, then rarity priority
    def sort_key(r):
        era_p = ERA_PRIORITY.get(r["era"], 99)
        rar_p = RARITY_PRIORITY.get(r["rarity"] or "", 99)
        return (era_p, rar_p)

    rows = sorted(rows, key=sort_key)
    return [(r["set_id"], r["id"], r["name"], r["number"], r["rarity"]) for r in rows]


def main():
    parser = argparse.ArgumentParser(description="Daily PokeTrace price updater")
    parser.add_argument("--budget", type=int, default=240, help="Max API calls (default 240, saves 10 buffer)")
    parser.add_argument("--era", help="Limit to specific era (sv, swsh, sm, etc.)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without calling API")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between API calls (default 2.0)")
    args = parser.parse_args()

    if not API_KEY:
        log("ERROR: POKETRACE_API_KEY not set")
        sys.exit(1)

    # Clear today's log
    with open(LOG_PATH, "w") as f:
        f.write(f"=== Pokemon price update {datetime.now().isoformat()} ===\n")

    conn = get_db()
    headers = {"X-API-Key": API_KEY}
    budget = args.budget
    calls_used = 0
    cards_priced = 0
    sets_touched = set()
    errors = 0

    queue = get_work_queue(conn, args.era)
    log(f"Work queue: {len(queue)} cards need PokeTrace prices")

    if args.dry_run:
        # Show top 20 cards that would be priced
        for set_id, card_id, name, number, rarity in queue[:20]:
            print(f"  {set_id:12s} {name:30s} #{number:5s} {rarity}")
        print(f"  ... and {max(0, len(queue)-20)} more")
        conn.close()
        return

    if not queue:
        log("Nothing to do — all cards have PokeTrace prices")
        conn.close()
        return

    # Track set slugs needed
    current_set = None
    current_slug = None

    for set_id, card_id, card_name, card_number, rarity in queue:
        if budget <= 0:
            log(f"Budget exhausted after {calls_used} calls")
            break

        # Get set slug (cached after first lookup)
        if set_id != current_set:
            current_set = set_id
            slug, used = get_set_slug(conn, set_id, headers, budget)
            budget -= used
            calls_used += used
            current_slug = slug
            if used > 0:
                time.sleep(args.delay)
            if slug == "rate_limited":
                log(f"Rate limited during set lookup — stopping")
                break
            if not slug:
                log(f"  Skipping set {set_id} — no PokeTrace slug found")
                continue

        if not current_slug:
            continue

        # Get card UUID
        uuid, used = get_card_uuid(conn, card_id, card_name, card_number, current_slug, headers, budget)
        budget -= used
        calls_used += used
        if used > 0:
            time.sleep(args.delay)

        if not uuid:
            errors += 1
            continue

        if budget <= 0:
            break

        # Fetch price
        price, used = fetch_price(uuid, headers)
        budget -= used
        calls_used += used
        time.sleep(args.delay)

        if price == "rate_limited":
            log(f"Rate limited after {calls_used} calls — stopping")
            break

        if price and isinstance(price, dict):
            save_price(conn, card_id, price)
            cards_priced += 1
            sets_touched.add(set_id)

            if cards_priced % 10 == 0:
                conn.commit()
                log(f"  Progress: {cards_priced} priced, {calls_used} calls, {budget} remaining")
        else:
            errors += 1

    conn.commit()
    conn.close()

    # Recalculate EV for updated sets
    if sets_touched:
        log(f"Recalculating EV for {len(sets_touched)} sets: {', '.join(sorted(sets_touched))}")
        recalc_ev(sorted(sets_touched))

    # Write status for monitoring
    status = {
        "last_run": datetime.now().isoformat(),
        "cards_priced": cards_priced,
        "calls_used": calls_used,
        "errors": errors,
        "sets_updated": sorted(sets_touched),
        "queue_remaining": max(0, len(queue) - cards_priced),
    }
    with open(STATUS_PATH, "w") as f:
        json.dump(status, f)

    log(f"Done: {cards_priced} cards priced, {calls_used} API calls, {errors} errors, {len(sets_touched)} sets updated")
    remaining = len(queue) - cards_priced
    if remaining > 0:
        log(f"Remaining: ~{remaining} cards, ~{remaining * 2 // 240} more days at 240/day (first pass)")


if __name__ == "__main__":
    main()
