#!/usr/bin/env python3
"""
Scrape PSA/CGC population reports and graded prices from PriceCharting.com.

PriceCharting provides (no auth, no JS needed):
- Set-level pop tables: Grade 6-10 pop + total per card (one request per set)
- Per-card pop pages: Full Grade 1-10 breakdown + price per grade
- Per-card product pages: Ungraded, Grade 7-10, PSA 10 prices

Strategy:
1. Scrape set pop page for Grade 6-10 + total (bulk, one request per set)
2. For cards needing full detail, scrape individual pop pages for 1-10 + prices

Rate limit: 1 request per 2 seconds (be respectful).
"""
import re
import sys
import os
import time
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_db

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Map our set IDs to PriceCharting set slugs
_SET_SLUG_OVERRIDES = {
    "base1": "pokemon-base-set",
    "base2": "pokemon-jungle",
    "base3": "pokemon-fossil",
    "base4": "pokemon-base-set-2",
    "base5": "pokemon-team-rocket",
    "gym1": "pokemon-gym-heroes",
    "gym2": "pokemon-gym-challenge",
    "neo1": "pokemon-neo-genesis",
    "neo2": "pokemon-neo-discovery",
    "neo3": "pokemon-neo-revelation",
    "neo4": "pokemon-neo-destiny",
    "ecard1": "pokemon-expedition",
    "ecard2": "pokemon-aquapolis",
    "ecard3": "pokemon-skyridge",
    "ex1": "pokemon-ruby-sapphire",
    "ex2": "pokemon-sandstorm",
    "ex3": "pokemon-dragon",
    "ex4": "pokemon-team-magma-vs-team-aqua",
    "ex5": "pokemon-hidden-legends",
    "ex6": "pokemon-firered-leafgreen",
    "ex7": "pokemon-team-rocket-returns",
    "ex8": "pokemon-deoxys",
    "ex9": "pokemon-emerald",
    "ex10": "pokemon-unseen-forces",
    "ex11": "pokemon-delta-species",
    "ex12": "pokemon-legend-maker",
    "ex13": "pokemon-holon-phantoms",
    "ex14": "pokemon-crystal-guardians",
    "ex15": "pokemon-dragon-frontiers",
    "ex16": "pokemon-power-keepers",
    "dp1": "pokemon-diamond-pearl",
    "dp2": "pokemon-mysterious-treasures",
    "dp3": "pokemon-secret-wonders",
    "dp4": "pokemon-great-encounters",
    "dp5": "pokemon-majestic-dawn",
    "dp6": "pokemon-legends-awakened",
    "dp7": "pokemon-stormfront",
    "pl1": "pokemon-platinum",
    "pl2": "pokemon-rising-rivals",
    "pl3": "pokemon-supreme-victors",
    "pl4": "pokemon-arceus",
    "hgss1": "pokemon-heartgold-soulsilver",
    "hgss2": "pokemon-unleashed",
    "hgss3": "pokemon-undaunted",
    "hgss4": "pokemon-triumphant",
    "bw1": "pokemon-black-white",
    "bw2": "pokemon-emerging-powers",
    "bw3": "pokemon-noble-victories",
    "bw4": "pokemon-next-destinies",
    "bw5": "pokemon-dark-explorers",
    "bw6": "pokemon-dragons-exalted",
    "bw7": "pokemon-boundaries-crossed",
    "bw8": "pokemon-plasma-storm",
    "bw9": "pokemon-plasma-freeze",
    "bw10": "pokemon-plasma-blast",
    "bw11": "pokemon-legendary-treasures",
    "xy0": "pokemon-kalos-starter-set",
    "xy1": "pokemon-xy",
    "xy2": "pokemon-flashfire",
    "xy3": "pokemon-furious-fists",
    "xy4": "pokemon-phantom-forces",
    "xy5": "pokemon-primal-clash",
    "xy6": "pokemon-roaring-skies",
    "xy7": "pokemon-ancient-origins",
    "xy8": "pokemon-breakthrough",
    "xy9": "pokemon-breakpoint",
    "xy10": "pokemon-fates-collide",
    "xy11": "pokemon-steam-siege",
    "xy12": "pokemon-evolutions",
    "sm1": "pokemon-sun-moon",
    "sm2": "pokemon-guardians-rising",
    "sm3": "pokemon-burning-shadows",
    "sm35": "pokemon-shining-legends",
    "sm4": "pokemon-crimson-invasion",
    "sm5": "pokemon-ultra-prism",
    "sm6": "pokemon-forbidden-light",
    "sm7": "pokemon-celestial-storm",
    "sm75": "pokemon-dragon-majesty",
    "sm8": "pokemon-lost-thunder",
    "sm9": "pokemon-team-up",
    "sm10": "pokemon-unbroken-bonds",
    "sm11": "pokemon-unified-minds",
    "sm115": "pokemon-hidden-fates",
    "sm12": "pokemon-cosmic-eclipse",
    "swsh1": "pokemon-sword-shield",
    "swsh2": "pokemon-rebel-clash",
    "swsh3": "pokemon-darkness-ablaze",
    "swsh35": "pokemon-champions-path",
    "swsh4": "pokemon-vivid-voltage",
    "swsh45": "pokemon-shining-fates",
    "swsh5": "pokemon-battle-styles",
    "swsh6": "pokemon-chilling-reign",
    "swsh7": "pokemon-evolving-skies",
    "swsh8": "pokemon-fusion-strike",
    "swsh9": "pokemon-brilliant-stars",
    "swsh10": "pokemon-astral-radiance",
    "swsh11": "pokemon-lost-origin",
    "swsh12": "pokemon-silver-tempest",
    "swsh12pt5": "pokemon-crown-zenith",
    "sv1": "pokemon-scarlet-violet",
    "sv2": "pokemon-paldea-evolved",
    "sv3": "pokemon-obsidian-flames",
    "sv3pt5": "pokemon-scarlet-&-violet-151",
    "sv4": "pokemon-paradox-rift",
    "sv4pt5": "pokemon-paldean-fates",
    "sv5": "pokemon-temporal-forces",
    "sv6": "pokemon-twilight-masquerade",
    "sv6pt5": "pokemon-shrouded-fable",
    "sv7": "pokemon-stellar-crown",
    "sv8": "pokemon-surging-sparks",
    "sv8pt5": "pokemon-prismatic-evolutions",
    "sv9": "pokemon-journey-together",
    "sv9pt5": "pokemon-destined-rivals",
}


def _slugify_set_name(name):
    """Convert our set name to PriceCharting URL slug."""
    slug = name.lower().strip()
    slug = slug.replace("&", "&").replace("'", "").replace(":", "")
    slug = re.sub(r"[^a-z0-9\s&-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return f"pokemon-{slug}"


def _get_set_slug(set_id, set_name):
    """Get PriceCharting slug for a set."""
    if set_id in _SET_SLUG_OVERRIDES:
        return _SET_SLUG_OVERRIDES[set_id]
    return _slugify_set_name(set_name)


def _parse_int(s):
    """Parse integer from string, handling commas and dashes."""
    s = re.sub(r"<[^>]+>", "", s).strip().replace(",", "")
    if not s or s == "-":
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _parse_price(s):
    """Parse price from '$16,263.75' or '-'."""
    s = re.sub(r"<[^>]+>", "", s).strip().replace(",", "").replace("$", "")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_card_number(name):
    """Extract card number from 'Charizard #4'."""
    m = re.search(r"#(\d+)", name)
    return m.group(1) if m else None


def scrape_set_pop(set_id, set_name=None):
    """Scrape set-level pop report. One HTTP request per set.

    Returns list of dicts with card_name, card_number, grade 6-10 pops, total.
    """
    if set_name is None:
        with get_db() as conn:
            row = conn.execute("SELECT name FROM sets WHERE id = ?", (set_id,)).fetchone()
            if not row:
                return []
            set_name = row["name"]

    slug = _get_set_slug(set_id, set_name)
    url = f"https://www.pricecharting.com/pop/set/{slug}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"  PriceCharting: HTTP {resp.status_code} for {slug}")
            return []
    except Exception as e:
        print(f"  PriceCharting: error fetching {slug}: {e}")
        return []

    text = resp.text

    idx = text.find('id="games_table"')
    if idx < 0:
        print(f"  PriceCharting: no games_table for {slug}")
        return []

    end = text.find("</table>", idx)
    table = text[idx:end + 8]

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL)

    results = []
    for row in rows[1:]:  # skip header
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        if len(cells) < 8:
            continue

        card_name_raw = re.sub(r"<[^>]+>", "", cells[1]).strip()
        # Skip variant editions — we want the standard unlimited print
        if any(tag in card_name_raw for tag in
               ["[1st Edition]", "[Shadowless]", "[Reverse Holo]", "[Cosmos Holo]"]):
            continue

        card_number = _extract_card_number(card_name_raw)
        if not card_number:
            continue

        card_name = re.sub(r"\s*#\d+\s*$", "", card_name_raw).strip()

        # Also extract the card slug from the link for detail fetching
        link_match = re.search(r'href="/pop/item/[^/]+/([^"]+)"', cells[1])
        card_slug = link_match.group(1) if link_match else None

        results.append({
            "card_name": card_name,
            "card_number": card_number,
            "card_slug": card_slug,
            "psa_6": _parse_int(cells[2]),
            "psa_7": _parse_int(cells[3]),
            "psa_8": _parse_int(cells[4]),
            "psa_9": _parse_int(cells[5]),
            "psa_10": _parse_int(cells[6]),
            "total_graded": _parse_int(cells[7]),
        })

    return results


def scrape_card_pop_detail(set_slug, card_slug):
    """Scrape individual card pop page for full 1-10 breakdown + prices."""
    url = f"https://www.pricecharting.com/pop/item/{set_slug}/{card_slug}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return None
    except Exception:
        return None

    text = resp.text

    idx = text.find('id="population-table"')
    if idx < 0:
        return None

    end = text.find("</table>", idx)
    table = text[idx:end + 8]

    pop = {}
    prices = {}
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 5:
            continue

        grade_text = re.sub(r"<[^>]+>", "", cells[0]).strip()
        if grade_text == "Total":
            pop["total"] = _parse_int(cells[3])
            continue

        grade_num = _parse_int(cells[0])
        if grade_num < 1 or grade_num > 10:
            continue

        psa_count = _parse_int(cells[1])
        cgc_count = _parse_int(cells[2])
        price = _parse_price(cells[4])

        pop[f"psa_{grade_num}"] = psa_count + cgc_count
        if price is not None:
            prices[f"Grade {grade_num}"] = price

    # Also grab ungraded price from the product page
    prod_url = f"https://www.pricecharting.com/game/{set_slug}/{card_slug}"
    try:
        resp2 = requests.get(prod_url, headers=HEADERS, timeout=30)
        if resp2.status_code == 200:
            m = re.search(r'id="used_price"[^>]*>.*?class="price[^"]*">([^<]+)',
                          resp2.text, re.DOTALL)
            if m:
                raw_price = _parse_price(m.group(1))
                if raw_price:
                    prices["Ungraded"] = raw_price
    except Exception:
        pass

    return {"pop": pop, "prices": prices}


def import_set_pop(set_id, dry_run=False):
    """Import PSA pop data for a set. One HTTP request.

    Returns count of cards matched.
    """
    with get_db() as conn:
        set_row = conn.execute(
            "SELECT id, name FROM sets WHERE id = ?", (set_id,)
        ).fetchone()
        if not set_row:
            print(f"  Set {set_id} not found")
            return 0

    print(f"  Scraping pop report for {set_row['name']}...")
    pop_data = scrape_set_pop(set_id, set_row["name"])
    if not pop_data:
        print(f"  No pop data found")
        return 0

    with get_db() as conn:
        cards = conn.execute(
            "SELECT id, number FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()

    card_by_number = {}
    for c in cards:
        num = c["number"].lstrip("0") or "0"
        card_by_number[num] = c["id"]

    now = datetime.utcnow().isoformat()
    matched = 0

    if not dry_run:
        with get_db() as conn:
            for entry in pop_data:
                num = entry["card_number"].lstrip("0") or "0"
                card_id = card_by_number.get(num)
                if not card_id:
                    continue

                conn.execute("""
                    INSERT INTO psa_pop (card_id, psa_6, psa_7, psa_8, psa_9, psa_10,
                                         total_graded, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(card_id) DO UPDATE SET
                        psa_6=excluded.psa_6, psa_7=excluded.psa_7,
                        psa_8=excluded.psa_8, psa_9=excluded.psa_9,
                        psa_10=excluded.psa_10, total_graded=excluded.total_graded,
                        last_updated=excluded.last_updated
                """, (card_id, entry["psa_6"], entry["psa_7"], entry["psa_8"],
                      entry["psa_9"], entry["psa_10"], entry["total_graded"], now))
                matched += 1

    print(f"  Pop: {len(pop_data)} scraped, {matched} matched")
    return matched


def import_card_graded_prices(set_id, min_price=5.0, max_cards=50, dry_run=False):
    """Import full pop + graded prices for high-value cards.

    Scrapes individual card pages — one request per card with rate limiting.
    Only fetches cards worth >= min_price (raw).
    """
    with get_db() as conn:
        set_row = conn.execute(
            "SELECT id, name FROM sets WHERE id = ?", (set_id,)
        ).fetchone()
        if not set_row:
            return 0

        cards = conn.execute("""
            SELECT c.id, c.name, c.number, p.tcg_market
            FROM cards c
            JOIN prices p ON c.id = p.card_id
            WHERE c.set_id = ? AND p.tcg_market >= ?
            ORDER BY p.tcg_market DESC
            LIMIT ?
        """, (set_id, min_price, max_cards)).fetchall()

    if not cards:
        print(f"  No cards above ${min_price} in {set_row['name']}")
        return 0

    slug = _get_set_slug(set_id, set_row["name"])

    # Get card slugs from set pop page
    pop_data = scrape_set_pop(set_id, set_row["name"])
    slug_by_number = {}
    for entry in pop_data:
        num = entry["card_number"].lstrip("0") or "0"
        if entry.get("card_slug"):
            slug_by_number[num] = entry["card_slug"]

    now = datetime.utcnow().isoformat()
    imported = 0

    print(f"  Fetching graded prices for {len(cards)} cards in {set_row['name']}...")

    for card in cards:
        num = card["number"].lstrip("0") or "0"
        card_slug = slug_by_number.get(num)
        if not card_slug:
            # Build slug from card name
            card_slug = re.sub(r"[^a-z0-9\s]", "", card["name"].lower())
            card_slug = re.sub(r"\s+", "-", card_slug.strip())
            card_slug = f"{card_slug}-{card['number']}"

        time.sleep(2)
        detail = scrape_card_pop_detail(slug, card_slug)
        if not detail:
            continue

        if not dry_run:
            with get_db() as conn:
                pop = detail.get("pop", {})
                if pop:
                    conn.execute("""
                        INSERT INTO psa_pop (card_id, psa_1, psa_2, psa_3, psa_4, psa_5,
                                             psa_6, psa_7, psa_8, psa_9, psa_10,
                                             total_graded, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(card_id) DO UPDATE SET
                            psa_1=excluded.psa_1, psa_2=excluded.psa_2,
                            psa_3=excluded.psa_3, psa_4=excluded.psa_4,
                            psa_5=excluded.psa_5, psa_6=excluded.psa_6,
                            psa_7=excluded.psa_7, psa_8=excluded.psa_8,
                            psa_9=excluded.psa_9, psa_10=excluded.psa_10,
                            total_graded=excluded.total_graded,
                            last_updated=excluded.last_updated
                    """, (card["id"],
                          pop.get("psa_1", 0), pop.get("psa_2", 0),
                          pop.get("psa_3", 0), pop.get("psa_4", 0),
                          pop.get("psa_5", 0), pop.get("psa_6", 0),
                          pop.get("psa_7", 0), pop.get("psa_8", 0),
                          pop.get("psa_9", 0), pop.get("psa_10", 0),
                          pop.get("total", 0), now))

                for grade_label, price in detail.get("prices", {}).items():
                    conn.execute("""
                        INSERT INTO graded_prices (card_id, grade, market_price,
                                                   price_source, last_updated)
                        VALUES (?, ?, ?, 'pricecharting', ?)
                        ON CONFLICT(card_id, grade) DO UPDATE SET
                            market_price=excluded.market_price,
                            last_updated=excluded.last_updated
                    """, (card["id"], grade_label, price, now))

        imported += 1
        print(f"    {card['name']} #{card['number']}: "
              f"{len(detail.get('prices', {}))} grades, "
              f"pop={detail.get('pop', {}).get('total', '?')}")

    print(f"  Graded prices: {imported}/{len(cards)} cards")
    return imported


def import_all_set_pops(era_filter=None, dry_run=False):
    """Import set-level pop data for all sets. One request per set."""
    with get_db() as conn:
        query = "SELECT id, name, era FROM sets"
        params = []
        if era_filter:
            query += " WHERE era = ?"
            params.append(era_filter)
        query += " ORDER BY release_date"
        sets = conn.execute(query, params).fetchall()

    total = 0
    for s in sets:
        matched = import_set_pop(s["id"], dry_run=dry_run)
        total += matched
        if matched > 0:
            time.sleep(2)

    print(f"\nTotal: {total} cards with pop data across {len(sets)} sets")
    return total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape PSA pop + graded prices from PriceCharting")
    parser.add_argument("--set", help="Single set ID")
    parser.add_argument("--era", help="Filter by era")
    parser.add_argument("--all", action="store_true", help="All sets")
    parser.add_argument("--prices", action="store_true", help="Also fetch per-card graded prices (slow)")
    parser.add_argument("--min-price", type=float, default=5.0, help="Min raw price for graded price fetch")
    parser.add_argument("--max-cards", type=int, default=50, help="Max cards per set for graded prices")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if args.set:
        import_set_pop(args.set, dry_run=args.dry_run)
        if args.prices:
            import_card_graded_prices(args.set, min_price=args.min_price,
                                      max_cards=args.max_cards, dry_run=args.dry_run)
    elif args.all or args.era:
        import_all_set_pops(era_filter=args.era, dry_run=args.dry_run)
    else:
        parser.print_help()
