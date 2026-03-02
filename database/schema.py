from database.connection import get_db

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    series TEXT,
    printed_total INTEGER,
    total_cards INTEGER,
    release_date TEXT,
    logo_url TEXT,
    symbol_url TEXT,
    has_god_pack BOOLEAN DEFAULT 0,
    god_pack_odds REAL,
    god_pack_description TEXT,
    ptcgo_code TEXT,
    era TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL,
    name TEXT NOT NULL,
    number TEXT NOT NULL,
    rarity TEXT,
    supertype TEXT,
    subtypes TEXT,
    hp TEXT,
    types TEXT,
    artist TEXT,
    image_url_small TEXT,
    image_url_large TEXT,
    regulation_mark TEXT,
    FOREIGN KEY (set_id) REFERENCES sets(id)
);

CREATE TABLE IF NOT EXISTS prices (
    card_id TEXT PRIMARY KEY,
    tcg_market REAL,
    tcg_low REAL,
    tcg_mid REAL,
    tcg_high REAL,
    tcg_direct_low REAL,
    cm_avg REAL,
    cm_low REAL,
    cm_trend REAL,
    price_source TEXT,
    last_updated TEXT,
    price_detail TEXT,
    FOREIGN KEY (card_id) REFERENCES cards(id)
);

CREATE TABLE IF NOT EXISTS pull_rate_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    era TEXT NOT NULL,
    rarity TEXT NOT NULL,
    slot_type TEXT NOT NULL,
    guaranteed_count INTEGER DEFAULT 0,
    probability_per_pack REAL,
    notes TEXT,
    UNIQUE(era, rarity, slot_type)
);

CREATE TABLE IF NOT EXISTS pull_rate_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id TEXT NOT NULL,
    rarity TEXT NOT NULL,
    slot_type TEXT NOT NULL,
    guaranteed_count INTEGER,
    probability_per_pack REAL,
    notes TEXT,
    UNIQUE(set_id, rarity, slot_type),
    FOREIGN KEY (set_id) REFERENCES sets(id)
);

CREATE TABLE IF NOT EXISTS god_packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id TEXT NOT NULL,
    name TEXT DEFAULT 'God Pack',
    odds REAL NOT NULL,
    composition TEXT,
    description TEXT,
    FOREIGN KEY (set_id) REFERENCES sets(id)
);

CREATE TABLE IF NOT EXISTS ev_cache (
    set_id TEXT PRIMARY KEY,
    ev_per_pack REAL,
    ev_breakdown TEXT,
    pack_price REAL,
    calculated_at TEXT,
    FOREIGN KEY (set_id) REFERENCES sets(id)
);

CREATE TABLE IF NOT EXISTS card_id_map (
    card_id TEXT NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    PRIMARY KEY (card_id, source)
);

CREATE TABLE IF NOT EXISTS sealed_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id TEXT NOT NULL,
    name TEXT NOT NULL,
    product_type TEXT,
    tcg_market REAL,
    tcg_low REAL,
    tcg_mid REAL,
    tcg_high REAL,
    tcg_direct_low REAL,
    tcgplayer_product_id TEXT,
    last_updated TEXT,
    UNIQUE(set_id, tcgplayer_product_id),
    FOREIGN KEY (set_id) REFERENCES sets(id)
);

CREATE INDEX IF NOT EXISTS idx_cards_set_id ON cards(set_id);
CREATE INDEX IF NOT EXISTS idx_cards_rarity ON cards(rarity);
CREATE INDEX IF NOT EXISTS idx_prices_updated ON prices(last_updated);
CREATE INDEX IF NOT EXISTS idx_sealed_set_id ON sealed_products(set_id);
"""


def seed_pull_rate_templates(conn):
    """Insert default pull rate templates if not present."""
    count = conn.execute("SELECT COUNT(*) FROM pull_rate_templates").fetchone()[0]
    if count > 0:
        return

    # SV era (Scarlet & Violet) - modern sets
    sv_templates = [
        ("sv", "Common", "guaranteed", 4, 1.0, "4 commons per pack"),
        ("sv", "Uncommon", "guaranteed", 3, 1.0, "3 uncommons per pack"),
        ("sv", "Reverse Holo", "reverse_holo", 2, 1.0, "2 reverse holos, any common-rare"),
        ("sv", "Rare", "hit_slot", 0, 0.55, "~1 in 1.8 packs, base rare holo"),
        ("sv", "Double Rare", "hit_slot", 0, 0.20, "~1 in 5 packs, ex cards"),
        ("sv", "Illustration Rare", "hit_slot", 0, 0.09, "~1 in 11 packs"),
        ("sv", "Ultra Rare", "hit_slot", 0, 0.065, "~1 in 15 packs"),
        ("sv", "ACE SPEC Rare", "hit_slot", 0, 0.048, "~1 in 21 packs"),
        ("sv", "Special Illustration Rare", "hit_slot", 0, 0.015, "~1 in 67 packs avg"),
        ("sv", "Hyper Rare", "hit_slot", 0, 0.006, "~1 in 167 packs"),
    ]

    # SWSH era (Sword & Shield)
    swsh_templates = [
        ("swsh", "Common", "guaranteed", 4, 1.0, "4 commons per pack"),
        ("swsh", "Uncommon", "guaranteed", 3, 1.0, "3 uncommons per pack"),
        ("swsh", "Reverse Holo", "reverse_holo", 1, 1.0, "1 reverse holo per pack"),
        ("swsh", "Rare", "hit_slot", 0, 0.50, "Base rare"),
        ("swsh", "Rare Holo", "hit_slot", 0, 0.20, "Holo rare"),
        ("swsh", "Rare Holo V", "hit_slot", 0, 0.12, "V cards"),
        ("swsh", "Rare Holo VMAX", "hit_slot", 0, 0.04, "VMAX cards"),
        ("swsh", "Rare Holo VSTAR", "hit_slot", 0, 0.04, "VSTAR cards"),
        ("swsh", "Rare Ultra", "hit_slot", 0, 0.03, "Full art cards"),
        ("swsh", "Rare Secret", "hit_slot", 0, 0.02, "Secret/gold cards"),
        ("swsh", "Rare Rainbow", "hit_slot", 0, 0.01, "Rainbow rares"),
        ("swsh", "Radiant Rare", "hit_slot", 0, 0.02, "Radiant cards"),
    ]

    # SM era (Sun & Moon)
    sm_templates = [
        ("sm", "Common", "guaranteed", 4, 1.0, "4 commons per pack"),
        ("sm", "Uncommon", "guaranteed", 3, 1.0, "3 uncommons per pack"),
        ("sm", "Reverse Holo", "reverse_holo", 1, 1.0, "1 reverse holo per pack"),
        ("sm", "Rare", "hit_slot", 0, 0.50, "Base rare"),
        ("sm", "Rare Holo", "hit_slot", 0, 0.20, "Holo rare"),
        ("sm", "Rare Holo GX", "hit_slot", 0, 0.12, "GX cards"),
        ("sm", "Rare Ultra", "hit_slot", 0, 0.06, "Full art GX/Supporters"),
        ("sm", "Rare Secret", "hit_slot", 0, 0.03, "Secret/gold cards"),
        ("sm", "Rare Rainbow", "hit_slot", 0, 0.02, "Rainbow rares"),
        ("sm", "Rare Prism Star", "hit_slot", 0, 0.03, "Prism Star cards"),
        ("sm", "Amazing Rare", "hit_slot", 0, 0.02, "Amazing rares"),
    ]

    all_templates = sv_templates + swsh_templates + sm_templates
    conn.executemany(
        "INSERT INTO pull_rate_templates "
        "(era, rarity, slot_type, guaranteed_count, probability_per_pack, notes) "
        "VALUES (?,?,?,?,?,?)",
        all_templates,
    )


def seed_god_packs(conn):
    """Populate god pack data for all known sets that have god packs."""
    import json

    god_pack_sets = [
        {
            "set_id": "sv3pt5",
            "god_pack_odds": 1 / 1300,
            "packs": [
                {
                    "name": "Demi God Pack (Venusaur line)",
                    "odds": 1 / 1300,
                    "composition": json.dumps([
                        {"rarity": "Illustration Rare", "count": 2},
                        {"rarity": "Special Illustration Rare", "count": 1},
                    ]),
                    "description": "2 IR + 1 SIR from a Kanto starter evo line. 3 variants (Venusaur/Charizard/Blastoise).",
                },
            ],
        },
        {
            "set_id": "sv8pt5",
            "god_pack_odds": 1 / 500,  # combined odds (full + demi)
            "packs": [
                {
                    "name": "Full God Pack",
                    "odds": 1 / 2000,
                    "composition": json.dumps([
                        {"rarity": "Special Illustration Rare", "count": 9},
                    ]),
                    "description": "All 9 Eeveelution SIRs in one pack.",
                },
                {
                    "name": "Demi God Pack",
                    "odds": 1 / 500,
                    "composition": json.dumps([
                        {"rarity": "Special Illustration Rare", "count": 3},
                        {"rarity": "Reverse Holo", "count": 7},
                    ]),
                    "description": "3 random Eeveelution SIRs + 7 Pokeball Reverse Holos.",
                },
            ],
        },
        {
            "set_id": "me2pt5",
            "god_pack_odds": 1 / 1000,
            "packs": [
                {
                    "name": "Full God Pack",
                    "odds": 1 / 1000,
                    "composition": json.dumps([
                        {"rarity": "Reverse Holo", "count": 1},
                        {"rarity": "Art Rare", "count": 1},
                        {"rarity": "Illustration Rare", "count": 5},
                        {"rarity": "Special Art Rare", "count": 4},
                    ]),
                    "description": "1 RH + 1 AR + 5 MAR/IR + 4 SAR.",
                },
            ],
        },
    ]

    for gps in god_pack_sets:
        set_id = gps["set_id"]

        # Check if set exists in DB
        exists = conn.execute("SELECT id FROM sets WHERE id = ?", (set_id,)).fetchone()
        if not exists:
            continue

        # Update set flags
        conn.execute(
            "UPDATE sets SET has_god_pack = 1, god_pack_odds = ? WHERE id = ?",
            (gps["god_pack_odds"], set_id),
        )

        # Insert god pack entries (skip if already seeded)
        for pack in gps["packs"]:
            existing = conn.execute(
                "SELECT id FROM god_packs WHERE set_id = ? AND name = ?",
                (set_id, pack["name"]),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO god_packs (set_id, name, odds, composition, description) VALUES (?,?,?,?,?)",
                (set_id, pack["name"], pack["odds"], pack["composition"], pack["description"]),
            )


def init_db():
    """Create all tables and seed pull rate templates."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        seed_pull_rate_templates(conn)
        seed_god_packs(conn)
    print("Database initialized with schema and pull rate templates.")
