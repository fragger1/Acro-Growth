"""Inputs: the in-area place dump (Supabase) and the PlusVibe workspace dump."""
import json
import math
import os
import re
import shutil
import sys

from . import config
from .util import log


def miles(lat, lng):
    la1, lo1, la2, lo2 = map(math.radians, (*config.HQ, lat, lng))
    a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


COLS = ("place_id,name,category,categories,address,city,state,postal_code,phone,website,domain,"
        "primary_email,emails,rating,review_count,maps_url,lat,lng,first_seen_at")


def _paged(q):
    out, o = [], 0
    while True:
        p = q().range(o, o + 999).execute().data
        out += p
        o += 1000
        if len(p) < 1000:
            return out


def dump_supabase():
    """Every scraped place within DUMP_RADIUS of Jeff (any client, not only searches queued for jeff),
    with category_match computed like `gmaps export` (search keywords + keyword_categories patterns).
    Needs the scraper venv's python (supabase client) and the scraper's .env."""
    sys.path.insert(0, config.SCRAPER)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(config.SCRAPER, ".env"))
        from gmaps.config import load_config
        from gmaps.db import Db
    except ImportError as e:
        raise SystemExit(f"dump needs the scraper venv: {config.SCRAPER_PYTHON} jeff.py dump ({e})")
    t = Db.connect(load_config()).c.table
    jeff = {r["place_id"] for r in _paged(lambda: t("place_clients").select("place_id").eq("client", "jeff").order("place_id"))}
    kws = {r["keyword"].lower() for r in _paged(lambda: t("search_queue").select("keyword").eq("client", "jeff").order("id"))}
    pats = [re.compile(".*" + re.escape(k) + ".*", re.I) for k in kws]
    pats += [re.compile("".join(".*" if c == "%" else re.escape(c) for c in r["pattern"]), re.I)
             for r in _paged(lambda: t("keyword_categories").select("keyword,pattern").order("pattern"))
             if r["keyword"].lower() in kws]
    places = _paged(lambda: t("places").select(COLS).gte("lat", config.BBOX["lat"][0]).lte("lat", config.BBOX["lat"][1])
                    .gte("lng", config.BBOX["lng"][0]).lte("lng", config.BBOX["lng"][1]).order("place_id"))
    out = []
    for p in places:
        if p["lat"] is None:
            continue
        d = miles(p["lat"], p["lng"])
        if d > config.DUMP_RADIUS:
            continue
        p["miles"] = round(d, 1)
        p["jeff"] = p["place_id"] in jeff
        p["category_match"] = bool(p["category"]) and any(x.fullmatch(p["category"]) for x in pats)
        out.append(p)
    return out


def dump(run, src=None):
    dest = run.path("places.json")
    if src:
        shutil.copyfile(src, dest)
        places = json.load(open(dest, encoding="utf-8"))
        source = os.path.abspath(src)
    else:
        places = dump_supabase()
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(places, fh)
        source = "supabase"
    newest = max((p.get("first_seen_at") or "" for p in places), default="")
    n_email = sum(1 for p in places if p.get("primary_email"))
    log(f"{len(places)} places within {config.DUMP_RADIUS} mi ({sum(bool(p.get('jeff')) for p in places)} linked to "
        f"jeff), {n_email} with email, {sum(bool(p.get('category_match')) for p in places)} on-target, newest {newest[:19]}")
    run.done("dump", source=source, places=len(places), with_email=n_email, newest_first_seen=newest)


def _leads_from(obj):
    """Find the list of lead dicts inside whatever shape the PlusVibe tool returned."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "email" in obj[0]:
            return obj
        if obj and isinstance(obj[0], dict) and obj[0].get("type") == "text":  # MCP content blocks
            leads = []
            for block in obj:
                leads += _leads_from(_parse(block.get("text") or ""))
            return leads or None
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            found = _leads_from(v)
            if found:
                return found
    return None


def _parse(text):
    try:
        return json.loads(text)
    except ValueError:
        pass
    # list_all_leads with limit 10000 overflows into a tool-results file: a header line, then the JSON.
    lines = text.split("\n", 1)
    if len(lines) == 2:
        try:
            return json.loads(lines[1])
        except ValueError:
            pass
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
    if start >= 0:
        return json.loads(text[start:])
    raise SystemExit("could not find JSON in the PlusVibe file")


def import_pv(run, src):
    text = open(src, encoding="utf-8").read()
    leads = _leads_from(_parse(text))
    if not leads:
        raise SystemExit(f"no leads found in {src}")
    ws = {lead.get("workspace_id") for lead in leads if lead.get("workspace_id")}
    if ws and ws != {config.PLUSVIBE_WORKSPACE}:
        log(f"warning: workspace ids in the dump: {ws}")
    with open(run.path("plusvibe_leads.json"), "w", encoding="utf-8") as fh:
        json.dump(leads, fh)
    log(f"{len(leads)} PlusVibe leads -> {run.path('plusvibe_leads.json')}")
    if len(leads) in (100, 1000, 10000):
        log("warning: exactly a page limit came back; check list_all_leads was not truncated")
    run.done("pv", source=os.path.abspath(src), leads=len(leads))
