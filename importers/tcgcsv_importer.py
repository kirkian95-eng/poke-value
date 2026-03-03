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


# Manual overrides for sets where fuzzy matching fails.
# Our set_id -> TCGCSV groupId (verified against Groups.csv)
_GROUP_OVERRIDES = {
    # SV era: fuzzy match fails because "Scarlet & Violet" matches many groups
    "sv1": "22873",     # Scarlet & Violet -> SV01: Scarlet & Violet Base Set
    # Base sets: TCGCSV uses "and" not "&", or drops prefix
    "sm1": "1863",      # Sun & Moon -> SM Base Set
    "dp1": "1430",      # Diamond & Pearl -> Diamond and Pearl
    "bw1": "1400",      # Black & White -> Black and White
    "ex1": "1393",      # Ruby & Sapphire -> Ruby and Sapphire
    "hgss1": "1402",    # HeartGold & SoulSilver -> HeartGold SoulSilver
    "ecard1": "1375",   # Expedition Base Set -> Expedition
    # HGSS: our names have "HS—" prefix with em-dash
    "hgss4": "1381",    # HS—Triumphant -> Triumphant
    "hgss2": "1399",    # HS—Unleashed -> Unleashed
    "hgss3": "1403",    # HS—Undaunted -> Undaunted
    # Sub-sets / vaults
    "swsh45sv": "2781", # Shining Fates Shiny Vault
    "sma": "2594",      # Hidden Fates Shiny Vault
    "swsh12pt5gg": "17689",  # Crown Zenith Galarian Gallery
    # Special characters / names
    "pgo": "3064",      # Pokémon GO -> Pokemon GO
    "ru1": "1433",      # Pokémon Rumble -> Rumble
    # Promo sets
    "svp": "22872",     # SV Black Star Promos -> SV: Scarlet & Violet Promo Cards
    "swshp": "2545",    # SWSH Black Star Promos -> SWSH: Sword & Shield Promo Cards
    "smp": "1861",      # SM Black Star Promos -> SM Promos
    "xyp": "1451",      # XY Black Star Promos -> XY Promos
    "bwp": "1407",      # BW Black Star Promos -> Black and White Promos
    "dpp": "1421",      # DP Black Star Promos -> Diamond and Pearl Promos
    "hsp": "1453",      # HGSS Black Star Promos -> HGSS Promos
    "basep": "1418",    # Wizards Black Star Promos -> WoTC Promo
    "np": "1423",       # Nintendo Black Star Promos -> Nintendo Promos
    "bp": "1455",       # Best of Game -> Best of Promos
    # McDonald's
    "mcd22": "3150",    # McDonald's Collection 2022
    "mcd19": "2555",    # McDonald's Collection 2019
    "mcd21": "2782",    # McDonald's Collection 2021 -> 25th Anniversary Promos
    "mcd18": "2364",    # McDonald's Collection 2018
    "mcd17": "2148",    # McDonald's Collection 2017
    "mcd16": "3087",    # McDonald's Collection 2016
    "mcd15": "1694",    # McDonald's Collection 2015
    "mcd14": "1692",    # McDonald's Collection 2014
    "mcd12": "1427",    # McDonald's Collection 2012
    "mcd11": "1401",    # McDonald's Collection 2011
}


def _match_group_to_set(groups, set_id, set_name):
    """Find the TCGCSV group matching our set. Returns groupId or None."""
    # Check manual overrides first
    if set_id in _GROUP_OVERRIDES:
        return _GROUP_OVERRIDES[set_id]

    name_lower = set_name.lower().strip()
    # Normalize: replace & with "and", strip special chars
    name_normalized = name_lower.replace("&", "and").replace("\u2014", " ").replace("\u2013", " ")

    # Try exact name match first
    for g in groups:
        gname = g.get("name", "").lower().strip()
        # TCGCSV names often have "SV: " prefix
        clean = re.sub(r'^[a-z]+\d*:\s*', '', gname)
        gname_normalized = gname.replace("&", "and")
        if clean == name_lower or gname == name_lower:
            return g["groupId"]
        if clean == name_normalized or gname_normalized == name_normalized:
            return g["groupId"]

    # Fuzzy: check if our name is contained in theirs
    best = None
    best_len = 999
    for g in groups:
        gname = g.get("name", "").lower()
        if name_lower in gname or name_normalized in gname.replace("&", "and"):
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
    reverse_holo_prices = {}  # card_id -> cheapest standard reverse holo market price
    sealed_products = []
    now = datetime.utcnow().isoformat()

    # Separate standard prints from special variants (Poke Ball Pattern, Master Ball Pattern, etc.)
    # Special variants share the same extNumber but have inflated prices.
    # We want the standard print price for EV calculations.
    _VARIANT_SUFFIXES = ("poke ball pattern", "master ball pattern", "cosmos holo",
                         "stamped", "promo", "prerelease")

    for row in rows:
        ext_number = row.get("extNumber", "").strip()
        market = _safe_float(row.get("marketPrice", ""))
        if market is None:
            continue

        if ext_number:
            # It's a card — match by number
            num = ext_number.split("/")[0].lstrip("0") or "0"
            card_id = card_by_number.get(num)
            if not card_id:
                continue

            # Skip special variant products (different productIds, same card number)
            clean_name = row.get("cleanName", "").lower()
            raw_name = row.get("name", "").lower()
            is_special = any(suffix in clean_name or suffix in raw_name
                            for suffix in _VARIANT_SUFFIXES)

            subtype = row.get("subTypeName", "").lower()

            # Track reverse holo prices separately (standard variants only)
            if subtype == "reverse holofoil" and not is_special:
                if card_id not in reverse_holo_prices or market < reverse_holo_prices[card_id]:
                    reverse_holo_prices[card_id] = market
                continue  # Don't use reverse holo as the main price

            price_data = {
                "tcg_market": market,
                "tcg_low": _safe_float(row.get("lowPrice")),
                "tcg_mid": _safe_float(row.get("midPrice")),
                "tcg_high": _safe_float(row.get("highPrice")),
                "tcg_direct_low": _safe_float(row.get("directLowPrice")),
            }

            if card_id not in results:
                # First entry for this card
                results[card_id] = price_data
                results[card_id]["_is_special"] = is_special
                results[card_id]["_subtype"] = subtype
            else:
                prev = results[card_id]
                prev_special = prev.get("_is_special", False)
                # Prefer standard over special; among same tier prefer Normal > cheapest
                if prev_special and not is_special:
                    # Replace special with standard
                    results[card_id] = price_data
                    results[card_id]["_is_special"] = is_special
                    results[card_id]["_subtype"] = subtype
                elif not prev_special and is_special:
                    # Keep existing standard, skip this special
                    pass
                elif subtype == "normal" and prev.get("_subtype") != "normal":
                    # Prefer Normal subtype
                    results[card_id] = price_data
                    results[card_id]["_is_special"] = is_special
                    results[card_id]["_subtype"] = subtype
                elif market < prev["tcg_market"] and prev.get("_subtype") != "normal":
                    # Among same tier (both standard or both special), pick cheapest
                    results[card_id] = price_data
                    results[card_id]["_is_special"] = is_special
                    results[card_id]["_subtype"] = subtype
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

    # Strip internal tracking keys and attach reverse holo prices
    for card_id in results:
        results[card_id].pop("_is_special", None)
        results[card_id].pop("_subtype", None)
        results[card_id]["tcg_reverse_holo"] = reverse_holo_prices.get(card_id)

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
                                       tcg_direct_low, tcg_reverse_holo, price_source, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'tcgcsv', ?)
                    ON CONFLICT(card_id) DO UPDATE SET
                        tcg_market=excluded.tcg_market,
                        tcg_low=excluded.tcg_low,
                        tcg_mid=excluded.tcg_mid,
                        tcg_high=excluded.tcg_high,
                        tcg_direct_low=excluded.tcg_direct_low,
                        tcg_reverse_holo=excluded.tcg_reverse_holo,
                        price_source=CASE WHEN price_source LIKE '%poketrace%'
                            THEN price_source ELSE 'tcgcsv' END,
                        last_updated=excluded.last_updated
                """, (card_id, p["tcg_market"], p["tcg_low"], p["tcg_mid"],
                      p["tcg_high"], p["tcg_direct_low"], p.get("tcg_reverse_holo"), now))

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
