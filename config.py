import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pokemon_tcg_ev.db")

# GitHub raw base URL for card/set JSON
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/refs/heads/master"
GITHUB_CARDS_URL = f"{GITHUB_RAW_BASE}/cards/en"
GITHUB_SETS_URL = f"{GITHUB_RAW_BASE}/sets/en.json"

# Pricing APIs
POKEWALLET_API_BASE = "https://api.pokewallet.io/api/v1"
POKEWALLET_API_KEY = os.environ.get("POKEWALLET_API_KEY", "")

TCGDEX_API_BASE = "https://api.tcgdex.net/v2/en"

POKETRACE_API_BASE = "https://api.poketrace.com/v1"
POKETRACE_API_KEY = os.environ.get("POKETRACE_API_KEY", "")

# Pack MSRP for EV comparison
DEFAULT_PACK_MSRP = 4.49

# EUR to USD conversion factor
EUR_TO_USD = 1.08

# Era detection from set ID prefix
ERA_PREFIXES = {
    "sv": "sv",
    "swsh": "swsh",
    "sm": "sm",
    "xy": "xy",
    "bw": "bw",
    "dp": "dp",
    "pl": "pl",
    "hgss": "hgss",
    "ex": "ex",
    "neo": "neo",
    "base": "classic",
    "gym": "classic",
    "ecard": "classic",
}
