#!/usr/bin/env python3
"""CLI for Pokemon TCG EV Calculator — database setup, imports, and calculations."""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(description="Pokemon TCG EV Calculator CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init-db", help="Initialize database and seed pull rate templates")
    sub.add_parser("import-sets", help="Import all sets from GitHub")

    p_cards = sub.add_parser("import-cards", help="Import cards from GitHub")
    p_cards.add_argument("--set", help="Single set ID, or 'all' (default)", default="all")

    p_prices = sub.add_parser("update-prices", help="Update card prices from APIs")
    p_prices.add_argument("--set", required=True, help="Set ID to update prices for")
    p_prices.add_argument("--no-pokewallet", action="store_true", help="Skip PokéWallet (USD)")
    p_prices.add_argument("--source", choices=["poketrace", "tcgdex", "pokewallet"],
                          help="Force a specific price source (default: auto-detect best)")

    p_ev = sub.add_parser("calc-ev", help="Calculate EV for a set")
    p_ev.add_argument("--set", required=True, help="Set ID")

    sub.add_parser("calc-ev-all", help="Calculate EV for all sets with prices")

    p_stats = sub.add_parser("stats", help="Show database statistics")

    args = parser.parse_args()

    if args.command == "init-db":
        from database.schema import init_db
        init_db()

    elif args.command == "import-sets":
        from importers.set_importer import import_all_sets
        count = import_all_sets()
        print(f"Imported {count} sets.")

    elif args.command == "import-cards":
        from importers.card_importer import import_set_cards, import_all_cards
        if args.set == "all":
            total = import_all_cards()
            print(f"Imported {total} total cards.")
        else:
            count = import_set_cards(args.set)
            print(f"Imported {count} cards for {args.set}.")

    elif args.command == "update-prices":
        from importers.price_updater import update_set_prices
        count = update_set_prices(args.set, use_pokewallet=not args.no_pokewallet,
                                  source=args.source)
        print(f"Done. {count} cards with prices for {args.set}.")

    elif args.command == "calc-ev":
        from engine.ev_calculator import calculate_set_ev
        result = calculate_set_ev(args.set)
        _print_ev_result(result)

    elif args.command == "calc-ev-all":
        from engine.ev_calculator import calculate_set_ev
        from database.connection import get_db
        with get_db() as conn:
            sets_with_prices = conn.execute("""
                SELECT DISTINCT c.set_id, s.name, s.release_date
                FROM cards c
                JOIN prices p ON c.id = p.card_id
                JOIN sets s ON c.set_id = s.id
                ORDER BY s.release_date DESC
            """).fetchall()
        print(f"\n{'Set Name':40s} | {'EV/Pack':>8s} | {'MSRP':>6s} | {'Ratio':>6s}")
        print("-" * 70)
        for row in sets_with_prices:
            try:
                result = calculate_set_ev(row["set_id"])
                ratio = result["ev_per_pack"] / 4.49 if result["ev_per_pack"] > 0 else 0
                print(f"{row['name']:40s} | ${result['ev_per_pack']:>6.2f} | $4.49 | {ratio:>5.1%}")
            except Exception as e:
                print(f"{row['name']:40s} | ERROR: {e}")

    elif args.command == "stats":
        _print_stats()

    else:
        parser.print_help()


def _print_ev_result(result):
    """Pretty-print an EV calculation result."""
    print(f"\n{'=' * 60}")
    print(f"  {result['set_name']} ({result['set_id']})")
    print(f"{'=' * 60}")
    print(f"  EV per pack:      ${result['ev_per_pack']:.2f}")
    print(f"  Pack MSRP:        $4.49")
    ratio = result['ev_per_pack'] / 4.49 if result['ev_per_pack'] > 0 else 0
    print(f"  Value ratio:      {ratio:.1%}")
    print(f"  Cards with prices: {result['cards_with_prices']}/{result['total_cards']}")
    if result['god_pack_adjustment'] != 0:
        print(f"  God pack adj:     ${result['god_pack_adjustment']:.4f}")
    print(f"\n  {'Rarity':30s} | {'Cards':>5s} | {'Avg $':>7s} | {'EV':>8s} | {'Type':>10s}")
    print(f"  {'-' * 75}")
    for b in result['ev_breakdown']:
        print(f"  {b['rarity']:30s} | {b['card_count']:>5d} | ${b['avg_price']:>5.2f} | "
              f"${b['ev_contribution']:>6.4f} | {b['slot_type']:>10s}")
    print()


def _print_stats():
    """Show database statistics."""
    from database.connection import get_db
    with get_db() as conn:
        sets_count = conn.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
        cards_count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        prices_count = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        ev_count = conn.execute("SELECT COUNT(*) FROM ev_cache").fetchone()[0]
        templates_count = conn.execute("SELECT COUNT(*) FROM pull_rate_templates").fetchone()[0]

        print(f"\nDatabase Statistics:")
        print(f"  Sets:            {sets_count}")
        print(f"  Cards:           {cards_count}")
        print(f"  Prices:          {prices_count}")
        print(f"  EV cached:       {ev_count}")
        print(f"  Pull templates:  {templates_count}")

        if prices_count > 0:
            priced_sets = conn.execute("""
                SELECT s.name, COUNT(*) as cnt
                FROM prices p
                JOIN cards c ON p.card_id = c.id
                JOIN sets s ON c.set_id = s.id
                GROUP BY s.id
                ORDER BY s.release_date DESC
                LIMIT 10
            """).fetchall()
            print(f"\n  Sets with prices (top 10):")
            for row in priced_sets:
                print(f"    {row['name']:40s} {row['cnt']:>5d} cards")
        print()


if __name__ == "__main__":
    main()
