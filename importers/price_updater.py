"""Fetch card prices from TCGdex (EUR/Cardmarket), PokéWallet (USD/TCGPlayer), and PokeTrace (USD/TCGPlayer)."""
import re
import time
import requests
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    POKEWALLET_API_BASE, POKEWALLET_API_KEY,
    TCGDEX_API_BASE,
    POKETRACE_API_BASE, POKETRACE_API_KEY,
)
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


def _get_poketrace_set_slug(set_id):
    """Look up or search for the PokeTrace set slug matching our set_id."""
    with get_db() as conn:
        # Check if we already have the mapping cached
        row = conn.execute(
            "SELECT external_id FROM card_id_map WHERE card_id = ? AND source = 'poketrace_set'",
            (set_id,),
        ).fetchone()
        if row:
            return row["external_id"]

        # Look up set name and era to search PokeTrace
        set_row = conn.execute("SELECT name, era FROM sets WHERE id = ?", (set_id,)).fetchone()
        if not set_row:
            return None

    headers = {"X-API-Key": POKETRACE_API_KEY}
    try:
        resp = requests.get(
            f"{POKETRACE_API_BASE}/sets",
            params={"search": set_row["name"], "limit": 10},
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"  PokeTrace sets search failed: HTTP {resp.status_code}")
            return None

        data = resp.json()
        sets_list = data.get("data", [])
        if not sets_list:
            return None

        name_lower = set_row["name"].lower()
        era = (set_row["era"] or "").lower()
        era_prefixes = {"sv": "sv", "swsh": "swsh", "sm": "sm", "xy": "xy", "bw": "bw"}
        era_tag = era_prefixes.get(era, "")
        name_words = set(re.findall(r'\w+', name_lower))

        # Score all candidates by word overlap and era match
        candidates = []
        for s in sets_list:
            s_name = (s.get("name") or "").lower()
            s_slug = s.get("slug", "")
            if name_lower not in s_name and s_name != name_lower:
                continue
            score = 0

            # Word overlap ratio — penalize names with lots of extra words
            s_words = set(re.findall(r'\w+', s_name))
            noise = {era_tag} if era_tag else set()
            noise |= {w for w in s_words if re.match(r'^[a-z]+\d+[a-z]?$', w)}
            s_content = s_words - noise
            n_content = name_words - noise
            if n_content:
                overlap = len(n_content & s_content) / max(len(n_content), len(s_content))
                score += int(overlap * 30)

            if era_tag and era_tag in s_slug:
                score += 10

            candidates.append((score, s_slug, s_name))

        candidates.sort(key=lambda x: -x[0])

        best_slug = None
        if len(candidates) == 1:
            best_slug = candidates[0][1]
        elif len(candidates) >= 2 and candidates[0][0] > candidates[1][0]:
            best_slug = candidates[0][1]
        elif candidates:
            # Ambiguous — validate which slug actually has cards
            for score, slug, sname in candidates[:3]:
                try:
                    vresp = requests.get(
                        f"{POKETRACE_API_BASE}/cards",
                        params={"set": slug, "limit": 1},
                        headers=headers,
                        timeout=10,
                    )
                    if vresp.json().get("data"):
                        best_slug = slug
                        break
                    time.sleep(1)
                except Exception:
                    pass
            if not best_slug and candidates:
                best_slug = candidates[0][1]

        if best_slug:
            print(f"  PokeTrace: matched set '{set_row['name']}' -> slug '{best_slug}'")
            with get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO card_id_map (card_id, source, external_id) VALUES (?, 'poketrace_set', ?)",
                    (set_id, best_slug),
                )
        return best_slug
    except Exception as e:
        print(f"  PokeTrace set lookup error: {e}")
        return None


def _get_poketrace_card_id(card_id, card_name, card_number, set_slug):
    """Look up or search for a card's PokeTrace UUID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT external_id FROM card_id_map WHERE card_id = ? AND source = 'poketrace'",
            (card_id,),
        ).fetchone()
        if row:
            return row["external_id"]

    headers = {"X-API-Key": POKETRACE_API_KEY}
    try:
        resp = requests.get(
            f"{POKETRACE_API_BASE}/cards",
            params={
                "search": card_name,
                "set": set_slug,
                "limit": 5,
            },
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        cards_list = data.get("data", [])
        if not cards_list:
            return None

        # Match by card number — PokeTrace uses "166/165" format, we store just "166"
        card_num_str = str(card_number).lstrip("0") or "0"
        uuid = None
        for c in cards_list:
            pt_num = str(c.get("cardNumber", "")).split("/")[0].lstrip("0") or "0"
            if pt_num == card_num_str:
                uuid = c["id"]
                break
        if not uuid:
            uuid = cards_list[0]["id"]

        # Cache the mapping
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO card_id_map (card_id, source, external_id) VALUES (?, 'poketrace', ?)",
                (card_id, uuid),
            )
        return uuid
    except Exception:
        return None


def update_prices_poketrace(set_id, delay=2.0):
    """
    Fetch TCGPlayer (USD) prices from PokeTrace for all cards in a set.
    Rate limit: 250/day free tier, 1 request per 2 seconds.
    Uses card_id_map table to cache PokeTrace UUIDs.
    """
    if not POKETRACE_API_KEY:
        print("  PokeTrace: skipped (no API key — set POKETRACE_API_KEY env var)")
        return {}

    # Find the PokeTrace set slug
    set_slug = _get_poketrace_set_slug(set_id)
    if not set_slug:
        print(f"  PokeTrace: could not find set slug for {set_id}")
        return {}

    results = {}
    headers = {"X-API-Key": POKETRACE_API_KEY}

    with get_db() as conn:
        cards = conn.execute(
            "SELECT id, name, number, rarity FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()

    # Prioritize expensive rarities first (most value from limited API calls)
    rarity_priority = {
        "Special Illustration Rare": 0, "Hyper Rare": 1, "Special Art Rare": 2,
        "Illustration Rare": 3, "Ultra Rare": 4, "ACE SPEC Rare": 5,
        "Double Rare": 6, "Art Rare": 7, "Rare Holo": 8, "Rare": 9,
    }
    sorted_cards = sorted(cards, key=lambda c: rarity_priority.get(c["rarity"] or "", 99))

    print(f"  PokeTrace: fetching prices for {len(sorted_cards)} cards (set slug: {set_slug})...")
    fetched = 0
    errors = 0
    api_calls = 0

    for card_row in sorted_cards:
        card_id = card_row["id"]
        card_name = card_row["name"]
        card_number = card_row["number"]

        # Get or look up PokeTrace UUID
        pt_uuid = _get_poketrace_card_id(card_id, card_name, card_number, set_slug)
        api_calls += 1
        if not pt_uuid:
            errors += 1
            time.sleep(delay)
            continue

        # Fetch card detail with pricing
        try:
            time.sleep(delay)
            resp = requests.get(
                f"{POKETRACE_API_BASE}/cards/{pt_uuid}",
                headers=headers,
                timeout=10,
            )
            api_calls += 1

            if resp.status_code == 429:
                print("  PokeTrace: rate limited, stopping")
                break
            if resp.status_code != 200:
                errors += 1
                continue

            data = resp.json().get("data", {})
            all_prices = data.get("prices", {})

            # Extract TCGPlayer pricing for EV calculation
            tcgp = all_prices.get("tcgplayer", {})
            if not tcgp:
                continue

            # NEAR_MINT is the primary price for EV; store full JSON for all data
            price_entry = {}
            for tier in ["NEAR_MINT", "LIGHTLY_PLAYED"]:
                tier_data = tcgp.get(tier)
                if tier_data and tier_data.get("avg"):
                    price_entry = {
                        "tcg_market": tier_data.get("avg"),
                        "tcg_low": tier_data.get("low"),
                        "tcg_mid": tier_data.get("avg"),
                        "tcg_high": tier_data.get("high"),
                        "_full": all_prices,
                    }
                    break

            if price_entry:
                results[card_id] = price_entry
                fetched += 1

        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  PokeTrace error for {card_id}: {e}")

    print(f"  PokeTrace: got prices for {fetched}/{len(sorted_cards)} cards ({api_calls} API calls, {errors} errors)")
    return results


def update_set_prices(set_id, use_pokewallet=True, source=None):
    """
    Full price update for a set. Merges sources based on priority.

    Source priority for USD (tcg_market): PokeTrace > PokéWallet > TCGdex TCGPlayer
    Cardmarket EUR always comes from TCGdex.

    Args:
        set_id: The set to update.
        use_pokewallet: Whether to try PokéWallet (legacy flag).
        source: Force a specific source: "poketrace", "tcgdex", "pokewallet", or None (auto).

    Returns number of cards with at least one price.
    """
    print(f"Updating prices for set {set_id}...")

    tcgdex_prices = {}
    pw_prices = {}
    pt_prices = {}

    if source == "tcgcsv":
        from importers.tcgcsv_importer import update_prices_tcgcsv
        tcgcsv_prices = update_prices_tcgcsv(set_id)
        # TCGCSV gives us TCGPlayer USD prices directly
        now = datetime.utcnow().isoformat()
        with get_db() as conn:
            for card_id, p in tcgcsv_prices.items():
                conn.execute("""
                    INSERT INTO prices (card_id, tcg_market, tcg_low, tcg_mid, tcg_high,
                                       tcg_direct_low, price_source, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, 'tcgcsv', ?)
                    ON CONFLICT(card_id) DO UPDATE SET
                        tcg_market=excluded.tcg_market, tcg_low=excluded.tcg_low,
                        tcg_mid=excluded.tcg_mid, tcg_high=excluded.tcg_high,
                        tcg_direct_low=excluded.tcg_direct_low,
                        price_source=CASE WHEN price_source LIKE '%poketrace%'
                            THEN price_source ELSE 'tcgcsv' END,
                        last_updated=excluded.last_updated
                """, (card_id, p["tcg_market"], p["tcg_low"], p["tcg_mid"],
                      p["tcg_high"], p["tcg_direct_low"], now))
        print(f"  Total: {len(tcgcsv_prices)} cards with prices in DB")
        return len(tcgcsv_prices)
    elif source == "poketrace":
        pt_prices = update_prices_poketrace(set_id)
        # Also get Cardmarket EUR from TCGdex as supplementary
        tcgdex_prices = update_prices_tcgdex(set_id)
    elif source == "tcgdex":
        tcgdex_prices = update_prices_tcgdex(set_id)
    elif source == "pokewallet":
        tcgdex_prices = update_prices_tcgdex(set_id)
        pw_prices = update_prices_pokewallet(set_id)
    else:
        # Auto: always fetch TCGdex, then best USD source
        tcgdex_prices = update_prices_tcgdex(set_id)
        if POKETRACE_API_KEY:
            pt_prices = update_prices_poketrace(set_id)
        elif use_pokewallet:
            pw_prices = update_prices_pokewallet(set_id)

    now = datetime.utcnow().isoformat()
    updated = 0

    with get_db() as conn:
        card_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()]

        for card_id in card_ids:
            td = tcgdex_prices.get(card_id, {})
            pw = pw_prices.get(card_id, {})
            pt = pt_prices.get(card_id, {})

            if not td and not pw and not pt:
                continue

            # USD priority: PokeTrace > PokéWallet > TCGdex TCGPlayer
            usd = pt or pw
            tcg_market = usd.get("tcg_market") or td.get("tcg_market")
            tcg_low = usd.get("tcg_low") or td.get("tcg_low")
            tcg_mid = usd.get("tcg_mid") or td.get("tcg_mid")
            tcg_high = usd.get("tcg_high") or td.get("tcg_high")
            tcg_direct_low = usd.get("tcg_direct_low") or td.get("tcg_direct_low")

            sources = []
            if pt: sources.append("poketrace")
            if pw: sources.append("pokewallet")
            if td: sources.append("tcgdex")
            source_label = "+".join(sources)

            # Store full PokeTrace JSON if available
            full_json = None
            if pt and "_full" in pt:
                import json as _json
                full_json = _json.dumps(pt.pop("_full"))

            conn.execute("""
                INSERT OR REPLACE INTO prices
                (card_id, tcg_market, tcg_low, tcg_mid, tcg_high, tcg_direct_low,
                 cm_avg, cm_low, cm_trend, price_source, last_updated, price_detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                card_id,
                tcg_market, tcg_low, tcg_mid, tcg_high, tcg_direct_low,
                td.get("cm_avg"),
                td.get("cm_low"),
                td.get("cm_trend"),
                source_label, now, full_json,
            ))
            updated += 1

    print(f"  Total: {updated} cards with prices in DB")
    return updated
