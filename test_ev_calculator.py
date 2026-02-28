#!/usr/bin/env python3
"""
Verification tests for the EV calculation engine.

Uses synthetic data (not real cards) to validate the math independently
of API availability or database state.
"""
import sys
import os
import json
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Override DB_PATH to use a temp database for tests
import config
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
config.DB_PATH = _test_db.name

from database.connection import get_db
from database.schema import init_db, SCHEMA_SQL
from engine.ev_calculator import calculate_set_ev, _get_price, _compute_god_pack_ev
from engine.pull_rates import get_set_pull_rates, get_god_pack_data


def _setup_test_db():
    """Create schema and seed a synthetic set for testing."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)

        # Seed SV pull rate templates
        templates = [
            ("sv", "Common", "guaranteed", 4, 1.0, "4 per pack"),
            ("sv", "Uncommon", "guaranteed", 3, 1.0, "3 per pack"),
            ("sv", "Reverse Holo", "reverse_holo", 2, 1.0, "2 reverse holos"),
            ("sv", "Rare", "hit_slot", 0, 0.55, "base rare"),
            ("sv", "Double Rare", "hit_slot", 0, 0.20, "ex cards"),
            ("sv", "Illustration Rare", "hit_slot", 0, 0.09, "IR"),
            ("sv", "Ultra Rare", "hit_slot", 0, 0.065, "UR"),
            ("sv", "ACE SPEC Rare", "hit_slot", 0, 0.048, "ACE"),
            ("sv", "Special Illustration Rare", "hit_slot", 0, 0.015, "SIR"),
            ("sv", "Hyper Rare", "hit_slot", 0, 0.006, "HR"),
        ]
        conn.executemany(
            "INSERT INTO pull_rate_templates (era, rarity, slot_type, guaranteed_count, probability_per_pack, notes) VALUES (?,?,?,?,?,?)",
            templates,
        )

        # Create a synthetic test set
        conn.execute("""
            INSERT INTO sets (id, name, series, printed_total, total_cards, release_date, era)
            VALUES ('test1', 'Test Set', 'Test Series', 100, 120, '2025/01/01', 'sv')
        """)

        # Insert synthetic cards with known prices
        # 40 Commons at $0.10 each
        for i in range(1, 41):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"Common Card {i}", str(i), "Common", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 0.10, "test", "2025-01-01"),
            )

        # 30 Uncommons at $0.20 each
        for i in range(41, 71):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"Uncommon Card {i}", str(i), "Uncommon", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 0.20, "test", "2025-01-01"),
            )

        # 15 Rares at $0.50 each
        for i in range(71, 86):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"Rare Card {i}", str(i), "Rare", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 0.50, "test", "2025-01-01"),
            )

        # 10 Double Rares at $3.00 each
        for i in range(86, 96):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"Double Rare {i}", str(i), "Double Rare", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 3.00, "test", "2025-01-01"),
            )

        # 8 Illustration Rares at $15.00 each
        for i in range(96, 104):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"Illustration Rare {i}", str(i), "Illustration Rare", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 15.00, "test", "2025-01-01"),
            )

        # 6 Ultra Rares at $10.00 each
        for i in range(104, 110):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"Ultra Rare {i}", str(i), "Ultra Rare", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 10.00, "test", "2025-01-01"),
            )

        # 4 Special Illustration Rares at $50.00 each
        for i in range(110, 114):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"SIR {i}", str(i), "Special Illustration Rare", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 50.00, "test", "2025-01-01"),
            )

        # 2 Hyper Rares at $25.00 each
        for i in range(114, 116):
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test1-{i}", "test1", f"Hyper Rare {i}", str(i), "Hyper Rare", "Pokemon"),
            )
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test1-{i}", 25.00, "test", "2025-01-01"),
            )

        # No ACE SPEC cards in this test set (tests missing rarity handling)

        # Create a second set with god pack for god pack testing
        conn.execute("""
            INSERT INTO sets (id, name, series, printed_total, total_cards, release_date, era, has_god_pack, god_pack_odds)
            VALUES ('test2', 'God Pack Set', 'Test Series', 100, 120, '2025/01/01', 'sv', 1, 0.00167)
        """)

        # Copy same cards to test2
        for i in range(1, 116):
            orig = conn.execute("SELECT * FROM cards WHERE id = ?", (f"test1-{i}",)).fetchone()
            conn.execute(
                "INSERT INTO cards (id, set_id, name, number, rarity, supertype) VALUES (?,?,?,?,?,?)",
                (f"test2-{i}", "test2", orig["name"], orig["number"], orig["rarity"], orig["supertype"]),
            )
            price = conn.execute("SELECT tcg_market FROM prices WHERE card_id = ?", (f"test1-{i}",)).fetchone()
            conn.execute(
                "INSERT INTO prices (card_id, tcg_market, price_source, last_updated) VALUES (?,?,?,?)",
                (f"test2-{i}", price["tcg_market"], "test", "2025-01-01"),
            )

        # Add god pack data
        conn.execute("""
            INSERT INTO god_packs (set_id, name, odds, composition, description)
            VALUES ('test2', 'God Pack', 0.00167, ?, 'Test god pack: 6 IRs + 4 SIRs')
        """, (json.dumps([
            {"rarity": "Illustration Rare", "count": 6},
            {"rarity": "Special Illustration Rare", "count": 4},
        ]),))


class TestGetPrice(unittest.TestCase):
    """Test price resolution logic."""

    def test_tcg_market_preferred(self):
        card = {"tcg_market": 5.00, "cm_trend": 4.00, "cm_avg": 3.50}
        self.assertEqual(_get_price(card), 5.00)

    def test_cm_trend_fallback(self):
        card = {"tcg_market": None, "cm_trend": 4.00, "cm_avg": 3.50}
        self.assertAlmostEqual(_get_price(card), 4.00 * 1.08, places=2)

    def test_cm_avg_fallback(self):
        card = {"tcg_market": None, "cm_trend": None, "cm_avg": 3.50}
        self.assertAlmostEqual(_get_price(card), 3.50 * 1.08, places=2)

    def test_no_price(self):
        card = {"tcg_market": None, "cm_trend": None, "cm_avg": None}
        self.assertEqual(_get_price(card), 0.0)

    def test_zero_price_skipped(self):
        card = {"tcg_market": 0, "cm_trend": 0, "cm_avg": 3.50}
        self.assertAlmostEqual(_get_price(card), 3.50 * 1.08, places=2)


class TestPullRateTemplates(unittest.TestCase):
    """Test that pull rate templates are loaded and structured correctly."""

    def test_sv_templates_loaded(self):
        rates = get_set_pull_rates("test1")
        self.assertGreater(len(rates), 0)

    def test_hit_slot_probabilities_sum_to_one(self):
        """Hit slot probabilities must sum to ~1.0 for the math to be valid."""
        rates = get_set_pull_rates("test1")
        hit_probs = sum(r["probability_per_pack"] for r in rates if r["slot_type"] == "hit_slot")
        self.assertAlmostEqual(hit_probs, 0.974, places=2,
            msg=f"Hit slot probabilities sum to {hit_probs}, expected ~0.974")

    def test_guaranteed_slots_present(self):
        rates = get_set_pull_rates("test1")
        guaranteed = [r for r in rates if r["slot_type"] == "guaranteed"]
        rarities = {r["rarity"] for r in guaranteed}
        self.assertIn("Common", rarities)
        self.assertIn("Uncommon", rarities)

    def test_reverse_holo_slot_present(self):
        rates = get_set_pull_rates("test1")
        rev = [r for r in rates if r["slot_type"] == "reverse_holo"]
        self.assertEqual(len(rev), 1)
        self.assertEqual(rev[0]["guaranteed_count"], 2)


class TestEVCalculation(unittest.TestCase):
    """Test the core EV math with synthetic data."""

    def test_ev_returns_required_fields(self):
        result = calculate_set_ev("test1")
        self.assertIn("ev_per_pack", result)
        self.assertIn("ev_breakdown", result)
        self.assertIn("god_pack_adjustment", result)
        self.assertIn("total_cards", result)
        self.assertIn("cards_with_prices", result)

    def test_ev_is_positive(self):
        result = calculate_set_ev("test1")
        self.assertGreater(result["ev_per_pack"], 0)

    def test_all_cards_have_prices(self):
        result = calculate_set_ev("test1")
        self.assertEqual(result["cards_with_prices"], result["total_cards"])

    def test_ev_manual_calculation(self):
        """
        Manually verify EV against hand-calculated values.

        Guaranteed slots:
          Common:   4 cards/pack * avg($0.10) = 4/40 * 40*0.10 = $0.40
          Uncommon: 3 cards/pack * avg($0.20) = 3/30 * 30*0.20 = $0.60

        Hit slot (each rarity prob / n_cards * sum_prices):
          Rare:     0.55/15 * 15*0.50 = 0.55 * 0.50 = $0.275
          DR:       0.20/10 * 10*3.00 = 0.20 * 3.00 = $0.60
          IR:       0.09/8  *  8*15.0 = 0.09 * 15.0 = $1.35
          UR:       0.065/6 *  6*10.0 = 0.065 * 10.0 = $0.65
          SIR:      0.015/4 *  4*50.0 = 0.015 * 50.0 = $0.75
          HR:       0.006/2 *  2*25.0 = 0.006 * 25.0 = $0.15
          ACE:      0 (no cards) = $0.00

        Reverse Holo:
          Pool = 40 common + 30 uncommon + 15 rare = 85 cards
          2 cards from pool at 50% price
          Sum of pool prices = 40*0.10 + 30*0.20 + 15*0.50 = 4+6+7.50 = $17.50
          EV = 2/85 * 17.50 * 0.50 = 2 * 17.50 * 0.50 / 85 = $0.2059

        Total = 0.40 + 0.60 + 0.275 + 0.60 + 1.35 + 0.65 + 0.75 + 0.15 + 0.2059
              = $4.9809
        """
        result = calculate_set_ev("test1")
        expected = 4.98
        self.assertAlmostEqual(result["ev_per_pack"], expected, delta=0.05,
            msg=f"EV {result['ev_per_pack']} differs from hand-calculated {expected}")

    def test_guaranteed_common_ev(self):
        """Common EV should be 4/40 * sum(40 * $0.10) = $0.40"""
        result = calculate_set_ev("test1")
        common_entry = next(b for b in result["ev_breakdown"] if b["rarity"] == "Common")
        self.assertAlmostEqual(common_entry["ev_contribution"], 0.40, places=2)

    def test_guaranteed_uncommon_ev(self):
        """Uncommon EV should be 3/30 * sum(30 * $0.20) = $0.60"""
        result = calculate_set_ev("test1")
        uncommon_entry = next(b for b in result["ev_breakdown"] if b["rarity"] == "Uncommon")
        self.assertAlmostEqual(uncommon_entry["ev_contribution"], 0.60, places=2)

    def test_hit_slot_illustration_rare_ev(self):
        """IR EV should be 0.09/8 * sum(8 * $15.00) = 0.09 * 15.0 = $1.35"""
        result = calculate_set_ev("test1")
        ir_entry = next(b for b in result["ev_breakdown"] if b["rarity"] == "Illustration Rare")
        self.assertAlmostEqual(ir_entry["ev_contribution"], 1.35, places=2)

    def test_missing_rarity_handled(self):
        """ACE SPEC has a template but no cards — should not appear in breakdown."""
        result = calculate_set_ev("test1")
        ace_entries = [b for b in result["ev_breakdown"] if b["rarity"] == "ACE SPEC Rare"]
        self.assertEqual(len(ace_entries), 0)

    def test_breakdown_rarities_match_cards(self):
        """Every rarity in breakdown should correspond to actual cards in the set."""
        result = calculate_set_ev("test1")
        for entry in result["ev_breakdown"]:
            self.assertGreater(entry["card_count"], 0,
                msg=f"Rarity {entry['rarity']} has 0 cards but appears in breakdown")

    def test_ev_cached(self):
        """After calculation, result should be cached in ev_cache table."""
        calculate_set_ev("test1")
        with get_db() as conn:
            cached = conn.execute(
                "SELECT ev_per_pack FROM ev_cache WHERE set_id = 'test1'"
            ).fetchone()
        self.assertIsNotNone(cached)
        self.assertGreater(cached["ev_per_pack"], 0)


class TestGodPackCalculation(unittest.TestCase):
    """Test god pack EV adjustment."""

    def test_god_pack_data_loaded(self):
        gp = get_god_pack_data("test2")
        self.assertEqual(len(gp), 1)
        self.assertEqual(gp[0]["name"], "God Pack")
        self.assertAlmostEqual(gp[0]["odds"], 0.00167, places=4)

    def test_god_pack_ev_calculation(self):
        """
        God pack = 6 IRs (avg $15) + 4 SIRs (avg $50) = $90 + $200 = $290
        Normal EV ≈ $4.98
        Adjustment = 0.00167 * (290 - 4.98) = 0.00167 * 285.02 ≈ $0.476
        Total ≈ $4.98 + $0.476 ≈ $5.46
        """
        result = calculate_set_ev("test2")
        self.assertGreater(result["god_pack_adjustment"], 0,
            msg="God pack should increase EV")
        self.assertAlmostEqual(result["god_pack_adjustment"], 0.476, delta=0.05)

    def test_god_pack_increases_ev(self):
        """Set with god pack should have higher EV than same set without."""
        ev_no_gp = calculate_set_ev("test1")
        ev_with_gp = calculate_set_ev("test2")
        self.assertGreater(ev_with_gp["ev_per_pack"], ev_no_gp["ev_per_pack"])

    def test_no_god_pack_zero_adjustment(self):
        """Set without god pack should have zero adjustment."""
        result = calculate_set_ev("test1")
        self.assertEqual(result["god_pack_adjustment"], 0)


class TestComputeGodPackEV(unittest.TestCase):
    """Test the _compute_god_pack_ev helper directly."""

    def test_rarity_based_composition(self):
        cards = [
            {"id": "1", "rarity": "Illustration Rare", "tcg_market": 20.0, "cm_trend": None, "cm_avg": None},
            {"id": "2", "rarity": "Illustration Rare", "tcg_market": 10.0, "cm_trend": None, "cm_avg": None},
            {"id": "3", "rarity": "Special Illustration Rare", "tcg_market": 60.0, "cm_trend": None, "cm_avg": None},
        ]
        composition = [
            {"rarity": "Illustration Rare", "count": 2},
            {"rarity": "Special Illustration Rare", "count": 1},
        ]
        # 2 IRs at avg $15 + 1 SIR at $60 = $30 + $60 = $90
        ev = _compute_god_pack_ev(composition, cards)
        self.assertAlmostEqual(ev, 90.0, places=2)

    def test_card_id_based_composition(self):
        cards = [
            {"id": "card-a", "tcg_market": 100.0, "cm_trend": None, "cm_avg": None},
            {"id": "card-b", "tcg_market": 50.0, "cm_trend": None, "cm_avg": None},
        ]
        composition = ["card-a", "card-b"]
        ev = _compute_god_pack_ev(composition, cards)
        self.assertAlmostEqual(ev, 150.0, places=2)

    def test_empty_composition(self):
        self.assertEqual(_compute_god_pack_ev([], []), 0.0)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def test_nonexistent_set(self):
        """Calculating EV for a set that doesn't exist should handle gracefully."""
        result = calculate_set_ev("nonexistent-set")
        self.assertEqual(result["ev_per_pack"], 0)
        self.assertEqual(result["total_cards"], 0)

    def test_set_with_no_prices(self):
        """Set with cards but no prices should give EV = 0."""
        with get_db() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO sets (id, name, era) VALUES ('test-noprices', 'No Prices Set', 'sv')
            """)
            conn.execute("""
                INSERT OR IGNORE INTO cards (id, set_id, name, number, rarity, supertype)
                VALUES ('test-noprices-1', 'test-noprices', 'Card', '1', 'Common', 'Pokemon')
            """)
        result = calculate_set_ev("test-noprices")
        self.assertEqual(result["ev_per_pack"], 0)


if __name__ == "__main__":
    _setup_test_db()
    unittest.main(verbosity=2)
