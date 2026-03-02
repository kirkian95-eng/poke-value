#!/usr/bin/env python3
"""
Scrape card prices from PriceCharting.com via headless Chromium.

PriceCharting provides (per card, from the set page):
- Ungraded market price (based on eBay sold listings)
- Grade 9 price
- PSA 10 price

Card detail pages additionally provide: Grade 7, Grade 8, Grade 9.5

This is a supplementary data source — no auth needed, no rate limit,
but uses browser automation so it's slower than API calls.

Requires: playwright, Chromium binary
"""
import asyncio
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import get_db

CHROMIUM_PATH = "/home/ubuntu/.cache/ms-playwright/chromium-1208/chrome-linux/chrome"

# Map our set IDs to PriceCharting console slugs (verified)
SET_SLUG_MAP = {
    "sv3pt5": "pokemon-scarlet-&-violet-151",
    "sv8pt5": "pokemon-prismatic-evolutions",
    "sv10": "pokemon-destined-rivals",
    "sv9": "pokemon-journey-together",
    "sv8": "pokemon-surging-sparks",
    "sv7": "pokemon-stellar-crown",
    "sv6pt5": "pokemon-shrouded-fable",
    "sv6": "pokemon-twilight-masquerade",
    "sv5": "pokemon-temporal-forces",
    "sv4pt5": "pokemon-paldean-fates",
    "sv4": "pokemon-paradox-rift",
    "sv3": "pokemon-obsidian-flames",
    "sv2": "pokemon-paldea-evolved",
    "sv1": "pokemon-scarlet-&-violet",
}


def _parse_price(text):
    """Parse a price string like '$299.87' or '$1,287.00' to float."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    m = re.search(r'\$(\d+\.?\d*)', text)
    return float(m.group(1)) if m else None


async def scrape_set_prices(set_id, max_pages=10):
    """
    Scrape all card prices from a PriceCharting set page.
    Returns list of dicts with card name, number, ungraded/grade9/psa10 prices.
    """
    from playwright.async_api import async_playwright

    slug = SET_SLUG_MAP.get(set_id)
    if not slug:
        print(f"  PriceCharting: no slug mapping for {set_id}")
        return []

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=CHROMIUM_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )

        for page_num in range(1, max_pages + 1):
            url = f"https://www.pricecharting.com/console/{slug}?page={page_num}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                # Wait a moment for JS rendering
                await asyncio.sleep(1)
            except Exception as e:
                print(f"  PriceCharting: page {page_num} failed: {e}")
                break

            rows = await page.query_selector_all("#games_table tbody tr")
            if not rows:
                break

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 5:
                    continue

                # Column 1 is image, column 2 is card name with link
                name_cell = cells[1]
                name_el = await name_cell.query_selector("a")
                if not name_el:
                    continue

                name = (await name_el.text_content()).strip()
                href = await name_el.get_attribute("href") or ""

                # Extract card number from name (e.g., "Charizard ex #199")
                num_match = re.search(r"#(\d+)", name)
                card_number = num_match.group(1) if num_match else ""

                # Columns: [image, name, ungraded, grade_9, psa_10, actions]
                ungraded = _parse_price(await cells[2].text_content())
                grade_9 = _parse_price(await cells[3].text_content())
                psa_10 = _parse_price(await cells[4].text_content())

                entry = {
                    "name": name,
                    "card_number": card_number,
                    "url": href,
                    "ungraded": ungraded,
                    "grade_9": grade_9,
                    "psa_10": psa_10,
                }
                results.append(entry)

            print(f"  PriceCharting: page {page_num}, {len(rows)} items")

            if len(rows) < 50:
                break

            await asyncio.sleep(1)

        await browser.close()

    print(f"  PriceCharting: {len(results)} items scraped for {set_id}")
    return results


def save_graded_prices(set_id, scraped_cards):
    """Match scraped PriceCharting data to our cards and save graded prices."""
    with get_db() as conn:
        cards = conn.execute(
            "SELECT id, name, number FROM cards WHERE set_id = ?", (set_id,)
        ).fetchall()

    # Build lookup by card number
    card_by_number = {}
    for c in cards:
        num = c["number"].lstrip("0") or "0"
        card_by_number[num] = c["id"]

    matched = 0
    seen_ids = set()
    with get_db() as conn:
        for sc in scraped_cards:
            if not sc["card_number"]:
                continue

            num = sc["card_number"].lstrip("0") or "0"
            card_id = card_by_number.get(num)
            if not card_id or card_id in seen_ids:
                continue

            # Skip reverse holos and cosmos holos — they're variant entries
            # We want the base/regular card pricing
            name_lower = sc["name"].lower()
            if "reverse holo" in name_lower or "cosmos holo" in name_lower:
                continue

            graded_json = json.dumps({
                "ungraded": sc["ungraded"],
                "grade_9": sc["grade_9"],
                "psa_10": sc["psa_10"],
                "source": "pricecharting",
            })

            cursor = conn.execute("""
                UPDATE prices SET graded_prices = ?
                WHERE card_id = ?
            """, (graded_json, card_id))
            if cursor.rowcount > 0:
                matched += 1
                seen_ids.add(card_id)

    print(f"  Saved graded prices for {matched} cards")
    return matched


def scrape_and_save(set_id, max_pages=10):
    """Scrape a set from PriceCharting and save graded prices to DB."""
    cards = asyncio.run(scrape_set_prices(set_id, max_pages))
    if cards:
        return save_graded_prices(set_id, cards)
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape PriceCharting.com for Pokemon card prices")
    parser.add_argument("--set", help="Set ID (e.g., sv3pt5)")
    parser.add_argument("--all-sv", action="store_true", help="Scrape all SV-era sets")
    parser.add_argument("--detail", help="Scrape a specific card detail URL")
    parser.add_argument("--save", action="store_true", help="Save to database")
    args = parser.parse_args()

    if args.detail:
        # Detail page scrape not yet integrated with DB
        print(f"Fetching: {args.detail}")
        # Would need async runner here
    elif args.all_sv:
        total = 0
        for sid in SET_SLUG_MAP:
            print(f"\n{sid}:")
            total += scrape_and_save(sid)
        print(f"\nTotal: {total} cards with graded prices")
    elif args.set:
        if args.save:
            scrape_and_save(args.set)
        else:
            cards = asyncio.run(scrape_set_prices(args.set))
            print(f"\n{'Card':45s} | {'#':>4s} | {'Ungraded':>10s} | {'Grade 9':>10s} | {'PSA 10':>10s}")
            print("-" * 90)
            for c in cards[:25]:
                ug = f"${c['ungraded']:.2f}" if c["ungraded"] else "N/A"
                g9 = f"${c['grade_9']:.2f}" if c["grade_9"] else "N/A"
                p10 = f"${c['psa_10']:.2f}" if c["psa_10"] else "N/A"
                print(f"  {c['name'][:43]:43s} | {c['card_number']:>4s} | {ug:>10s} | {g9:>10s} | {p10:>10s}")
            if len(cards) > 25:
                print(f"  ... and {len(cards) - 25} more")
    else:
        parser.print_help()
