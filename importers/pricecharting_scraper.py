#!/usr/bin/env python3
"""
Scrape card prices from PriceCharting.com via headless Chromium.

PriceCharting provides:
- Ungraded market prices (based on eBay sold listings)
- Graded prices: Grade 7, 8, 9, 9.5, PSA 10
- Sale volume per card
- Price trend deltas

This is a supplementary data source — no auth needed, no rate limit,
but uses browser automation so it's slower than API calls.

Requires: playwright, Chromium binary
"""
import asyncio
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHROMIUM_PATH = "/home/ubuntu/.cache/ms-playwright/chromium-1208/chrome-linux/chrome"

# Map our set IDs to PriceCharting console slugs
SET_SLUG_MAP = {
    "sv3pt5": "pokemon-scarlet-&-violet-151",
    "sv8pt5": "pokemon-scarlet-&-violet-prismatic-evolutions",
    "sv10": "pokemon-scarlet-&-violet-destined-rivals",
    "sv9": "pokemon-scarlet-&-violet-journey-together",
    "sv8": "pokemon-scarlet-&-violet-surging-sparks",
    "sv7": "pokemon-scarlet-&-violet-stellar-crown",
    "sv6pt5": "pokemon-scarlet-&-violet-shrouded-fable",
    "sv6": "pokemon-scarlet-&-violet-twilight-masquerade",
    "sv5": "pokemon-scarlet-&-violet-temporal-forces",
    "sv4pt5": "pokemon-scarlet-&-violet-paldean-fates",
    "sv4": "pokemon-scarlet-&-violet-paradox-rift",
    "sv3": "pokemon-scarlet-&-violet-obsidian-flames",
    "sv2": "pokemon-scarlet-&-violet-paldea-evolved",
    "sv1": "pokemon-scarlet-&-violet",
}


def _parse_price(text):
    """Parse a price string like '$299.87' or '$1,287.00' to float."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    m = re.search(r'\$(\d+\.?\d*)', text)
    return float(m.group(1)) if m else None


async def scrape_set_prices(set_id, max_pages=5):
    """
    Scrape all card prices from a PriceCharting set page.
    Returns list of dicts with card name, number, and price columns.
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
            url = f"https://www.pricecharting.com/console/{slug}?sort=name&page={page_num}"
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)

            rows = await page.query_selector_all("#games_table tbody tr")
            if not rows:
                break

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) < 4:
                    continue

                name_el = await cells[0].query_selector("a")
                name = ""
                href = ""
                if name_el:
                    href = await name_el.get_attribute("href") or ""
                    # Extract name from URL slug: .../charizard-ex-199 -> Charizard Ex 199
                    slug_part = href.rstrip("/").split("/")[-1] if href else ""
                    name = slug_part.replace("-", " ").title()

                # Extract card number from slug (last numeric part)
                num_match = re.search(r"(\d+)$", name)
                card_number = num_match.group(1) if num_match else ""

                # Price columns: Ungraded, Complete, Graded/New
                prices = []
                for cell in cells[1:]:
                    text = await cell.text_content()
                    prices.append(_parse_price(text))

                entry = {
                    "name": name,
                    "card_number": card_number,
                    "ungraded": prices[0] if len(prices) > 0 else None,
                    "complete": prices[1] if len(prices) > 1 else None,
                    "graded": prices[2] if len(prices) > 2 else None,
                }
                results.append(entry)

            print(f"  PriceCharting: page {page_num}, {len(rows)} cards")

            # If we got fewer than 50, we've reached the last page
            if len(rows) < 50:
                break

            await asyncio.sleep(1)  # be polite

        await browser.close()

    print(f"  PriceCharting: {len(results)} cards scraped for {set_id}")
    return results


async def scrape_card_detail(url):
    """
    Scrape detailed pricing for a single card from its PriceCharting page.
    Returns dict with ungraded + graded tier prices and metadata.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=CHROMIUM_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )

        await page.goto(url, wait_until="domcontentloaded", timeout=20000)

        result = {"url": url}

        # Get graded prices from the price data section
        price_cells = await page.query_selector_all(".price.js-price")
        grade_labels = ["ungraded", "grade_7", "grade_8", "grade_9", "grade_9_5", "psa_10"]
        for i, cell in enumerate(price_cells):
            if i < len(grade_labels):
                text = await cell.text_content()
                result[grade_labels[i]] = _parse_price(text)

        # Get metadata
        attr_rows = await page.query_selector_all("#attribute tr")
        for row in attr_rows:
            cells = await row.query_selector_all("td")
            if len(cells) >= 2:
                label = (await cells[0].text_content()).strip().rstrip(":")
                value = (await cells[1].text_content()).strip()
                if label == "Card Number":
                    result["card_number"] = value
                elif label == "TCGPlayer ID":
                    result["tcgplayer_id"] = value
                elif label == "ePID (eBay)":
                    result["ebay_epid"] = value

        await browser.close()

    return result


def scrape_set_sync(set_id, max_pages=5):
    """Synchronous wrapper for scrape_set_prices."""
    return asyncio.run(scrape_set_prices(set_id, max_pages))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape PriceCharting.com for Pokemon card prices")
    parser.add_argument("--set", required=True, help="Set ID (e.g., sv3pt5)")
    parser.add_argument("--detail", help="Scrape a specific card detail URL")
    args = parser.parse_args()

    if args.detail:
        result = asyncio.run(scrape_card_detail(args.detail))
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        cards = scrape_set_sync(args.set)
        print(f"\n{'Card':45s} | {'Ungraded':>10s} | {'Complete':>10s} | {'Graded':>10s}")
        print("-" * 85)
        for c in cards[:20]:
            ug = f"${c['ungraded']:.2f}" if c["ungraded"] else "N/A"
            cp = f"${c['complete']:.2f}" if c["complete"] else "N/A"
            gr = f"${c['graded']:.2f}" if c["graded"] else "N/A"
            print(f"  {c['name'][:43]:43s} | {ug:>10s} | {cp:>10s} | {gr:>10s}")
        if len(cards) > 20:
            print(f"  ... and {len(cards) - 20} more")
