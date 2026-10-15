"""Paths and fixed settings for Jeff's lead pipeline. Override the folders with environment variables."""
import os

# Where every Jeff run folder, delivered file and hand-review drop lives.
PROJECTS = os.environ.get("JEFF_PROJECTS", r"C:\Users\Hi\Documents\Claude\Projects\AcroGrowth")
# The Google Maps scraper checkout with the Supabase .env (the dump step imports gmaps from here).
SCRAPER = os.environ.get("JEFF_SCRAPER", r"C:\Users\Hi\AcroGrowth\scraper\gmaps-scraper")
SCRAPER_PYTHON = os.path.join(SCRAPER, ".venv", "Scripts", "python.exe")
# Shared Reoon cache: every Reoon answer ever paid for, one JSON object per line.
REOON_CACHE = os.environ.get("JEFF_REOON_CACHE", os.path.join(PROJECTS, "MidwestRoofing_EmailFinder", "reoon_cache.jsonl"))
RUN_PREFIX = "JeffRun_"

# PlusVibe (for the skill and the payload notes; nothing here uploads).
PLUSVIBE_WORKSPACE = "6a8708da7b065e030fbe57d7"
CAMPAIGNS = {"8/20": "6a8708ef8c214cfc9078c566", "church": "6aba4d3c6b77606edf92fa00"}

# Jeff's office (Shawnee, KS). The dump keeps places within DUMP_RADIUS, the pools within POOL_RADIUS.
HQ = (38.9116, -94.7103)
DUMP_RADIUS = 45
POOL_RADIUS = 40
# Bounding box that contains DUMP_RADIUS around HQ (cheap pre-filter in the Supabase query).
BBOX = {"lat": (38.2, 39.7), "lng": (-95.7, -93.7)}

# Reoon defaults (the 10/15 runs: Reoon answers "unknown" when hit with many checks at once).
VERIFY_BATCH, VERIFY_PAUSE = 10, 15
GUESS_BATCH, GUESS_PAUSE = 6, 15
WORKERS = 2
BALANCE_EVERY = 10   # check the balance once per this many paid checks
DAILY_FLOOR = 100    # stop when daily credits fall to this
