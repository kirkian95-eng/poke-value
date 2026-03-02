#!/usr/bin/env python3
"""
Fetch TCGPlayer prices via TCGCSV (free, no auth, no rate limit).

TCGCSV mirrors TCGPlayer's product and pricing data as CSV files.
This gives us market/low/mid/high prices for every card AND sealed product.

URL pattern: https://tcgcsv.com/tcgplayer/3/{groupId}/ProductsAndPrices.csv
- Category 3 = Pokemon
- groupId = TCGPlayer's set/group ID (mapped from our set IDs)
"""
import csv
import io
import re
import time
import requests
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_db

TCGCSV_BASE = "https://tcgcsv.com/tcgplayer/3"
HEADERS = {"User-Agent": "poke-value/1.0"}


def fetch_tcgcsv_groups():
    """Fetch all Pokemon set groups from TCGCSV. Returns list of dicts."""
    resp = requests.get(f"{TCGCSV_BASE}/Groups.csv", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return list(reader)


def _match_group_to_set(groups, set_id, set_name):
    """Find the TCGCSV group matching our set. Returns groupId or None."""
    name_lower = set_name.lower().strip()

    # Try exact name match first
    for g in groups:
        gname = g.get("name", "").lower().strip()
        # TCGCSV names often have "SV: " prefix
        clean = re.sub(r'^[a-z]+\d*:\s*', '', gname)
        if clean == name_lower or gname == name_lower:
            return g["groupId"]

    # Fuzzy: check if our name is contained in theirs
    best = None
    best_len = 999
    for g in groups:
        gname = g.get("name", "").lower()
        if name_lower in gname:
            # Prefer shortest match (most specific)
            if len(gname) < best_len:
                best = g["groupId"]
                best_len = len(gname)

    return best


def _classify_sealed_product(name):
    """Classify a sealed product by type based on its name."""
    name_lower = name.lower()
    if "booster box" in name_lower or "booster case" in name_lower:
        return "booster_box"
    elif "elite trainer box" in name_lower or "etb" in name_lower:
        return "etb"
    elif "booster pack" in name_lower or "sleeved booster" in name_lower:
        return "booster_pack"
    elif "booster bundle" in name_lower:
        return "booster_bundle"
    elif "collection box" in name_lower or "collection" in name_lower:
        return "collection"
    elif "tin" in name_lower:
        return "tin"
    elif "binder" in name_lower:
        return "binder"
    elif "blister" in name_lower:
        return "blister"
    elif "build" in name_lower and "battle" in name_lower:
        return "build_battle"
    elif "starter" in name_lower or "league" in name_lower:
        return "league"
    elif "deck" in name_lower:
        return "deck"
    else:
        return "other"


def _safe_float(val):
    """Convert a CSV value to float, or None if empty/invalid."""
    if not val or val.strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def update_prices_tcgcsv(set_id, groups=None):
    """
    Fetch TCGPlayer prices from TCGCSV for a set.
    Returns dict of {card_id: {tcg_market, tcg_low, tcg_mid, tcg_high, tcg_direct_low}}.
    Also stores sealed product prices in the sealed_products table.
    """
    with get_db() as conn:
        set_row = conn.execute("SELECT name FROM sets WHERE id = ?", (set_id,)).fetchone()
        if not set_row:
            print(f"  TCGCSV: set {set_id} not in database")
            return {}

    if groups is None:
        groups = fetch_tcgcsv_groups()

    group_id = _match_group_to_set(groups, set_id, set_row["name"])
    if not group_id:
        print(f"  TCGCSV: no matching group for '{set_row['name']}'")
        return {}

    try:
        resp = requests.get(
            f"{TCGCSV_BASE}/{group_id}/ProductsAndPrices.csv",
            headers=HEADERS,
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  TCGCSV: HTTP {resp.status_code} for group {group_id}")
            return {}

        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
    except Exception as e:
        print(f"  TCGCSV: error fetching group {group_id}: {e}")
        return {}

    # Match TCGCSV products to our cards by card number
    with get_db() as conn:
        cards = conn.execute(
            "SELECT id, name, number FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()

    card_by_number = {}
    for c in cards:
        num = c["number"].lstrip("0") or "0"
        card_by_number[num] = c["id"]

    results = {}
    sealed_products = []
    now = datetime.utcnow().isoformat()

    for row in rows:
        ext_number = row.get("extNumber", "").strip()
        market = _safe_float(row.get("marketPrice", ""))
        if market is None:
            continue

        if ext_number:
            # It's a card — match by number
            num = ext_number.split("/")[0].lstrip("0") or "0"
            card_id = card_by_number.get(num)
            if card_id:
                results[card_id] = {
                    "tcg_market": market,
                    "tcg_low": _safe_float(row.get("lowPrice")),
                    "tcg_mid": _safe_float(row.get("midPrice")),
                    "tcg_high": _safe_float(row.get("highPrice")),
                    "tcg_direct_low": _safe_float(row.get("directLowPrice")),
                }
        else:
            # It's a sealed product
            name = row.get("name", "")
            sealed_products.append({
                "name": name,
                "product_type": _classify_sealed_product(name),
                "tcg_market": market,
                "tcg_low": _safe_float(row.get("lowPrice")),
                "tcg_mid": _safe_float(row.get("midPrice")),
                "tcg_high": _safe_float(row.get("highPrice")),
                "tcg_direct_low": _safe_float(row.get("directLowPrice")),
                "product_id": row.get("productId", ""),
            })

    # Store sealed products
    if sealed_products:
        with get_db() as conn:
            for sp in sealed_products:
                conn.execute("""
                    INSERT INTO sealed_products
                    (set_id, name, product_type, tcg_market, tcg_low, tcg_mid, tcg_high,
                     tcg_direct_low, tcgplayer_product_id, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(set_id, tcgplayer_product_id) DO UPDATE SET
                        tcg_market=excluded.tcg_market, tcg_low=excluded.tcg_low,
                        tcg_mid=excluded.tcg_mid, tcg_high=excluded.tcg_high,
                        tcg_direct_low=excluded.tcg_direct_low,
                        last_updated=excluded.last_updated
                """, (set_id, sp["name"], sp["product_type"], sp["tcg_market"],
                      sp["tcg_low"], sp["tcg_mid"], sp["tcg_high"],
                      sp["tcg_direct_low"], sp["product_id"], now))

    print(f"  TCGCSV: {len(results)} cards priced, {len(sealed_products)} sealed products stored")
    return results


def update_all_prices_tcgcsv(era_filter=None):
    """
    Bulk update prices for all sets from TCGCSV.
    Free, no auth, no rate limit — but be polite with a small delay.
    """
    groups = fetch_tcgcsv_groups()
    print(f"TCGCSV: {len(groups)} Pokemon groups available")

    with get_db() as conn:
        era_clause = "WHERE era = ?" if era_filter else ""
        params = (era_filter,) if era_filter else ()
        sets = conn.execute(
            f"SELECT id, name, era FROM sets {era_clause} ORDER BY release_date DESC", params
        ).fetchall()

    now = datetime.utcnow().isoformat()
    total_priced = 0
    total_sealed = 0

    for s in sets:
        set_id = s["id"]
        print(f"\n{set_id} ({s['name']}):")

        prices = update_prices_tcgcsv(set_id, groups=groups)
        if not prices:
            continue

        with get_db() as conn:
            for card_id, p in prices.items():
                conn.execute("""
                    INSERT INTO prices (card_id, tcg_market, tcg_low, tcg_mid, tcg_high,
                                       tcg_direct_low, price_source, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, 'tcgcsv', ?)
                    ON CONFLICT(card_id) DO UPDATE SET
                        tcg_market=excluded.tcg_market,
                        tcg_low=excluded.tcg_low,
                        tcg_mid=excluded.tcg_mid,
                        tcg_high=excluded.tcg_high,
                        tcg_direct_low=excluded.tcg_direct_low,
                        price_source=CASE WHEN price_source LIKE '%poketrace%'
                            THEN price_source ELSE 'tcgcsv' END,
                        last_updated=excluded.last_updated
                """, (card_id, p["tcg_market"], p["tcg_low"], p["tcg_mid"],
                      p["tcg_high"], p["tcg_direct_low"], now))

        total_priced += len(prices)
        time.sleep(0.5)  # be polite

    # Count sealed products stored
    with get_db() as conn:
        total_sealed = conn.execute("SELECT COUNT(*) FROM sealed_products").fetchone()[0]

    print(f"\nTotal: {total_priced} cards priced across {len(sets)} sets")
    print(f"Sealed products in DB: {total_sealed}")
    return total_priced


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch TCGPlayer prices via TCGCSV")
    parser.add_argument("--set", help="Single set ID to update")
    parser.add_argument("--era", help="Filter by era (sv, swsh, sm, etc.)")
    parser.add_argument("--all", action="store_true", help="Update all sets")
    args = parser.parse_args()

    if args.set:
        groups = fetch_tcgcsv_groups()
        prices = update_prices_tcgcsv(args.set, groups=groups)
        print(f"Got {len(prices)} card prices")
    elif args.all or args.era:
        update_all_prices_tcgcsv(era_filter=args.era)
    else:
        parser.print_help()
