"""Fetch card prices from TCGdex (EUR/Cardmarket) and PokéWallet (USD/TCGPlayer)."""
import re
import time
import requests
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import POKEWALLET_API_BASE, POKEWALLET_API_KEY, TCGDEX_API_BASE
from database.connection import get_db


def _to_tcgdex_set_id(set_id):
    """
    Convert pokemontcg-data set ID to TCGdex set ID.
    sv3pt5 -> sv03.5, sv1 -> sv01, swsh1 -> swsh01, etc.
    """
    result = set_id.replace("pt5", ".5")

    # Zero-pad SV set numbers: sv1 -> sv01
    m = re.match(r'^(sv|swsh|sm)(\d+)(\.5)?$', result)
    if m:
        prefix, num, half = m.groups()
        result = f"{prefix}{int(num):02d}{half or ''}"

    return result


def _to_tcgdex_card_id(card_id):
    """
    Convert pokemontcg-data card ID to TCGdex card ID.
    sv3pt5-1 -> sv03.5-001 (TCGdex zero-pads card numbers to 3 digits)
    """
    parts = card_id.split("-", 1)
    if len(parts) != 2:
        return card_id
    set_part = _to_tcgdex_set_id(parts[0])
    card_num = parts[1]
    # Zero-pad numeric card numbers to 3 digits
    if card_num.isdigit():
        card_num = card_num.zfill(3)
    return f"{set_part}-{card_num}"


def update_prices_tcgdex(set_id, delay=0.05):
    """
    Fetch pricing from TCGdex for all cards in a set.
    TCGdex pricing is under data["pricing"]["cardmarket"] and data["pricing"]["tcgplayer"].
    Returns {card_id: {"cm_avg": float, "cm_low": float, "cm_trend": float, ...}}.
    """
    results = {}
    with get_db() as conn:
        cards = conn.execute(
            "SELECT id FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()

    print(f"  TCGdex: fetching prices for {len(cards)} cards...")
    fetched = 0
    errors = 0
    for card_row in cards:
        card_id = card_row["id"]
        tcgdex_id = _to_tcgdex_card_id(card_id)
        try:
            resp = requests.get(
                f"{TCGDEX_API_BASE}/cards/{tcgdex_id}",
                timeout=10,
            )
            if resp.status_code != 200:
                errors += 1
                continue

            data = resp.json()
            pricing = data.get("pricing")
            if not pricing:
                continue

            price_entry = {}

            # Cardmarket prices (EUR) — under pricing.cardmarket
            cm = pricing.get("cardmarket")
            if cm:
                price_entry["cm_avg"] = cm.get("avg")
                price_entry["cm_low"] = cm.get("low")
                price_entry["cm_trend"] = cm.get("trend")

            # TCGPlayer prices (USD) — under pricing.tcgplayer
            tcgp = pricing.get("tcgplayer")
            if tcgp:
                # Pick best variant: normal, reverse-holofoil, holofoil
                for variant in ["holofoil", "normal", "reverse-holofoil"]:
                    v = tcgp.get(variant)
                    if v and v.get("marketPrice"):
                        price_entry["tcg_market"] = v.get("marketPrice")
                        price_entry["tcg_low"] = v.get("lowPrice")
                        price_entry["tcg_mid"] = v.get("midPrice")
                        price_entry["tcg_high"] = v.get("highPrice")
                        price_entry["tcg_direct_low"] = v.get("directLowPrice")
                        break

            if price_entry:
                results[card_id] = price_entry
                fetched += 1

            time.sleep(delay)
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  TCGdex error for {card_id}: {e}")

    print(f"  TCGdex: got prices for {fetched}/{len(cards)} cards ({errors} errors)")
    return results


def update_prices_pokewallet(set_id):
    """
    Fetch TCGPlayer (USD) prices from PokéWallet for all cards in a set.
    Rate limit: 100/hour, 1000/day.
    """
    if not POKEWALLET_API_KEY:
        print("  PokéWallet: skipped (no API key set)")
        return {}

    results = {}
    headers = {"X-API-Key": POKEWALLET_API_KEY}

    with get_db() as conn:
        cards = conn.execute(
            "SELECT id, name FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()

    fetched = 0
    for card_row in cards:
        card_id = card_row["id"]
        try:
            resp = requests.get(
                f"{POKEWALLET_API_BASE}/cards/{card_id}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 429:
                print("  PokéWallet: rate limited, stopping")
                break
            if resp.status_code != 200:
                continue

            data = resp.json()
            tcgp = data.get("tcgplayer", {})
            prices = tcgp.get("prices", {})

            for variant in ["holofoil", "normal", "reverseHolofoil"]:
                v = prices.get(variant)
                if v and v.get("market"):
                    results[card_id] = {
                        "tcg_market": v.get("market"),
                        "tcg_low": v.get("low"),
                        "tcg_mid": v.get("mid"),
                        "tcg_high": v.get("high"),
                        "tcg_direct_low": v.get("directLow"),
                    }
                    fetched += 1
                    break

            time.sleep(0.5)
        except Exception as e:
            print(f"  PokéWallet error for {card_id}: {e}")

    print(f"  PokéWallet: got prices for {fetched}/{len(cards)} cards")
    return results


def update_set_prices(set_id, use_pokewallet=True):
    """
    Full price update for a set. Merges both sources.
    Returns number of cards with at least one price.
    """
    print(f"Updating prices for set {set_id}...")
    tcgdex_prices = update_prices_tcgdex(set_id)
    pw_prices = update_prices_pokewallet(set_id) if use_pokewallet else {}

    now = datetime.utcnow().isoformat()
    updated = 0

    with get_db() as conn:
        card_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()]

        for card_id in card_ids:
            td = tcgdex_prices.get(card_id, {})
            pw = pw_prices.get(card_id, {})

            if not td and not pw:
                continue

            source = "both" if td and pw else ("pokewallet" if pw else "tcgdex")

            conn.execute("""
                INSERT OR REPLACE INTO prices
                (card_id, tcg_market, tcg_low, tcg_mid, tcg_high, tcg_direct_low,
                 cm_avg, cm_low, cm_trend, price_source, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                card_id,
                pw.get("tcg_market") or td.get("tcg_market"),
                pw.get("tcg_low") or td.get("tcg_low"),
                pw.get("tcg_mid") or td.get("tcg_mid"),
                pw.get("tcg_high") or td.get("tcg_high"),
                pw.get("tcg_direct_low") or td.get("tcg_direct_low"),
                td.get("cm_avg"),
                td.get("cm_low"),
                td.get("cm_trend"),
                source, now,
            ))
            updated += 1

    print(f"  Total: {updated} cards with prices in DB")
    return updated
