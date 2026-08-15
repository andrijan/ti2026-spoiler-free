#!/usr/bin/env python3
"""
Rebuild data/matches.js for the spoiler-free TI 2026 site.

Sources
-------
Liquipedia  : match schedule, rounds, best-of format, per-game YouTube VOD links
OpenDota    : per-game duration + replay-derived stats used for the "good game" score

Usage
-----
    python3 update.py            # incremental (uses cached per-game stats)
    python3 update.py --full     # ignore the stats cache and refetch everything

Run it every day or two while the tournament is live; new games appear
automatically as Liquipedia adds the VOD links.
"""

import argparse
import collections
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CACHE_DIR = os.path.join(DATA_DIR, ".cache")

LEAGUE_ID = 19719  # The International 2026 on OpenDota
LP_PAGES = [
    ("The International/2026/Group Stage", "Group Stage"),
    ("The International/2026/Main Event", "Main Event"),
]
UA = "TI2026SpoilerFreeSite/1.0 (personal use)"

SHORT_GAME_SECONDS = 35 * 60


# --------------------------------------------------------------------------
# tiny http helper (curl -- both APIs reject python-urllib's default UA)
# --------------------------------------------------------------------------
def get(url, tries=3, method="GET"):
    for attempt in range(tries):
        cmd = ["curl", "-s", "--compressed", "--max-time", "45", "-A", UA]
        if method == "POST":
            cmd += ["-X", "POST"]
        cmd.append(url)
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        try:
            return json.loads(out)
        except Exception:
            if attempt == tries - 1:
                print(f"  ! failed: {url}\n    {out[:200]}", file=sys.stderr)
                return None
            time.sleep(2 + attempt * 3)
    return None


# --------------------------------------------------------------------------
# Liquipedia: schedule + VOD links
# --------------------------------------------------------------------------
def fetch_liquipedia(page):
    url = (
        "https://liquipedia.net/dota2/api.php?action=parse&format=json&prop=text&page="
        + urllib.parse.quote(page.replace(" ", "_"))
    )
    doc = get(url)
    if not doc or "parse" not in doc:
        print(f"  ! could not load Liquipedia page: {page}", file=sys.stderr)
        return None
    return doc["parse"]["text"]["*"]


def strip_tags(s):
    return html.unescape(re.sub("<[^>]+>", "", s)).strip()


def bracket_round_names(markup):
    """Map bracket match index (document order) -> round name ("Grand Final", ...).

    Liquipedia draws a bracket as nested <div class="brkts-round-body">, so a
    match's round is its nesting depth: deepest = earliest round. Column titles
    live in a preceding brkts-round-header block, listed earliest round first.
    """
    header_groups, stack, depth, group = [], [], 0, -1
    matches = []
    try:
        for m in re.finditer(r"<div\b([^>]*)>|</div>", markup):
            if m.group(0) == "</div>":
                if stack and stack.pop() == "body":
                    depth -= 1
                continue
            cls = re.search(r'class="([^"]*)"', m.group(1))
            cls = cls.group(1) if cls else ""
            if "brkts-round-body" in cls:
                stack.append("body")
                depth += 1
            else:
                stack.append("")
            if "brkts-round-header" in cls:
                stop = markup.find("brkts-round-body", m.start())
                seg = markup[m.start(): stop if stop > 0 else len(markup)]
                names = []
                for hm in re.finditer(r'class="brkts-header[^"]*"[^>]*>(.*?)</div>', seg, re.S):
                    text = strip_tags(hm.group(1))
                    half = len(text) // 2
                    # rendered three times (full/medium/short); the full variant
                    # comes first and reads as its own text doubled
                    if text and len(text) % 2 == 0 and text[:half] == text[half:]:
                        names.append(text[:half])
                header_groups.append(names)
                group += 1
            if "brkts-match-info-popup" in cls:
                matches.append([len(matches), group, depth])
    except Exception:
        return {}

    # within a header group, header i sits at (deepest depth - i)
    deepest = {}
    for _, g, d in matches:
        deepest[g] = max(deepest.get(g, 0), d)
    by_depth = {}
    for g, names in enumerate(header_groups):
        for i, name in enumerate(names):
            by_depth.setdefault((g, deepest.get(g, len(names)) - i), name)

    out = {}
    for index, g, d in matches:
        name = by_depth.get((g, d))
        if name is None:  # e.g. the grand final, titled in the upper bracket's header row
            for other in range(g - 1, -1, -1):
                name = by_depth.get((other, d))
                if name:
                    break
        if name:
            out[index] = name
    return out


def parse_liquipedia(markup, stage_name):
    """Pull one record per series out of the rendered bracket/matchlist HTML."""
    headings = sorted(
        (m.start(), strip_tags(m.group(2)))
        for m in re.finditer(r"<h([2-4])[^>]*>(.*?)</h\1>", markup, re.S)
    )
    skip = {"Matches", "Standings", "Contents", "Results"}
    bracket_rounds = bracket_round_names(markup)

    def round_for(pos):
        label = stage_name
        for off, name in headings:
            if off < pos and name and name not in skip:
                label = name
        return label

    starts = [
        m.start()
        for m in re.finditer(r"brkts-popup brkts-popup-container brkts-match-info-popup", markup)
    ]
    series = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(markup)
        blk = markup[start:end]

        teams = [
            strip_tags(t)
            for t in re.findall(
                r'match-info-header-opponent[^>]*>.*?<span class="name"[^>]*>(.*?)</span>',
                blk,
                re.S,
            )
        ]
        if len(teams) != 2 or not all(teams):
            continue

        ts = re.search(r'data-timestamp="(\d+)"', blk)
        bo = re.search(r"scoreholder-lower\">\(Bo(\d)\)", blk)

        vods = {}
        for m in re.finditer(r'title="Watch Game (\d+)"><a href="([^"]+)"', blk):
            vods[int(m.group(1))] = html.unescape(m.group(2))

        series.append(
            {
                "stage": stage_name,
                "round": bracket_rounds.get(i) or round_for(start),
                "start": int(ts.group(1)) if ts else None,
                "teams": teams,
                # default Bo3; grand finals etc. are picked up from the header
                "bo": int(bo.group(1)) if bo else 3,
                "vods": vods,
                # a winner is highlighted only once the series is over
                "complete": "match-info-header-winner" in blk,
            }
        )
    return series


# --------------------------------------------------------------------------
# OpenDota: durations + replay stats
# --------------------------------------------------------------------------
def load_cache(name, default):
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return default


def save_cache(name, obj):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, name), "w") as fh:
        json.dump(obj, fh)


def fetch_team_names(team_ids):
    names = load_cache("teams.json", {})
    missing = [t for t in team_ids if str(t) not in names]
    for tid in missing:
        doc = get(f"https://api.opendota.com/api/teams/{tid}")
        names[str(tid)] = (doc or {}).get("name") or f"Team {tid}"
        time.sleep(0.35)
    if missing:
        save_cache("teams.json", names)
    return {int(k): v.strip() for k, v in names.items()}


def fetch_game_stats(match_ids, full=False):
    """Per-game stats. Cached: a finished game's numbers never change."""
    stats = {} if full else load_cache("games.json", {})
    todo = [m for m in match_ids if str(m) not in stats or not stats[str(m)].get("parsed")]
    if todo:
        print(f"  fetching stats for {len(todo)} game(s) from OpenDota...")
    for i, mid in enumerate(todo, 1):
        doc = get(f"https://api.opendota.com/api/matches/{mid}")
        if not doc:
            time.sleep(2)
            continue
        gold = doc.get("radiant_gold_adv") or []
        fights = doc.get("teamfights") or []
        stats[str(mid)] = {
            "duration": doc.get("duration"),
            "radiant_win": doc.get("radiant_win"),
            "kills": (doc.get("radiant_score") or 0) + (doc.get("dire_score") or 0),
            "gold_adv": gold,
            "teamfights": len(fights),
            "parsed": bool(gold),
        }
        if i % 10 == 0:
            save_cache("games.json", stats)
            print(f"    {i}/{len(todo)}")
        time.sleep(1.1)
    if todo:
        save_cache("games.json", stats)
    return stats


def request_parses(stats):
    """Ask OpenDota to parse the replays we are missing, for next run."""
    unparsed = [mid for mid, s in stats.items() if not s.get("parsed")]
    for mid in unparsed:
        get(f"https://api.opendota.com/api/request/{mid}", tries=1, method="POST")
        time.sleep(1.2)
    if unparsed:
        print(f"  queued {len(unparsed)} replay parse(s); re-run later to pick them up")


# --------------------------------------------------------------------------
# "is this a good game?" scoring
# --------------------------------------------------------------------------
def raw_metrics(s):
    """Four independent signals of an entertaining game."""
    dur_min = max(1, (s.get("duration") or 0) / 60)
    kills = s.get("kills") or 0
    gold = s.get("gold_adv") or []

    m = {
        "kpm": kills / dur_min,
        "comeback": 0.0,
        "swings": 0.0,
        "closeness": 0.0,
    }
    if not gold:
        return m, False

    # Whoever won, how far behind were they at their worst? (after min 10)
    sign = 1 if s.get("radiant_win") else -1
    winner = [g * sign for g in gold]
    late = winner[10:] or winner
    m["comeback"] = max(0.0, -min(late))

    # Meaningful lead changes: crossings of a +/-1500g deadband after min 8.
    side, swings = 0, 0
    for g in winner[8:]:
        if g > 1500 and side <= 0:
            side, swings = 1, swings + (1 if side else 0)
        elif g < -1500 and side >= 0:
            side, swings = -1, swings + (1 if side else 0)
    m["swings"] = float(swings)

    # How close was it through the second half of the game?
    half = gold[len(gold) // 2:] or gold
    m["closeness"] = sum(1 - min(1.0, abs(g) / 15000) for g in half) / len(half)
    return m, True


def percentile_ranks(values):
    """Map each value to its 0..1 rank within the field."""
    order = sorted(values)
    n = len(order)
    if n < 2:
        return {v: 0.5 for v in values}
    import bisect

    return {v: bisect.bisect_left(order, v) / (n - 1) for v in set(values)}


def score_games(stats):
    """Blend the signals into a 0-100 hype score, ranked across the tournament."""
    metrics, parsed_flag = {}, {}
    for mid, s in stats.items():
        metrics[mid], parsed_flag[mid] = raw_metrics(s)

    parsed = [m for m in metrics if parsed_flag[m]]
    weights = {"comeback": 0.30, "swings": 0.25, "closeness": 0.25, "kpm": 0.20}

    ranks = {}
    for key in weights:
        pool = parsed if key != "kpm" else list(metrics)
        table = percentile_ranks([metrics[m][key] for m in pool])
        ranks[key] = {m: table[metrics[m][key]] for m in pool}

    scored = {}
    for mid in metrics:
        if parsed_flag[mid]:
            value = sum(w * ranks[k][mid] for k, w in weights.items())
        else:
            # No replay data: fall back to kill pace alone, and never let an
            # unparsed game outrank a properly measured one.
            value = 0.55 * ranks["kpm"][mid] + 0.15
        scored[mid] = {
            "score": round(100 * value),
            "estimated": not parsed_flag[mid],
            "comeback": round(metrics[mid]["comeback"]),
            "swings": int(metrics[mid]["swings"]),
            "kpm": round(metrics[mid]["kpm"], 2),
        }

    # Tier by rank within this tournament, so the stars stay meaningful
    # however the field as a whole plays out.
    ordered = sorted(scored, key=lambda m: -scored[m]["score"])
    for i, mid in enumerate(ordered):
        pct = i / max(1, len(ordered) - 1)
        scored[mid]["tier"] = 2 if pct < 0.15 else (1 if pct < 0.40 else 0)
    return scored


# --------------------------------------------------------------------------
# join + emit
# --------------------------------------------------------------------------
def build():
    print("Liquipedia: schedule + VOD links")
    lp_series = []
    for page, stage in LP_PAGES:
        markup = fetch_liquipedia(page)
        if not markup:
            continue
        found = parse_liquipedia(markup, stage)
        print(f"  {stage}: {len(found)} series, {sum(len(s['vods']) for s in found)} VODs")
        lp_series += found
        time.sleep(1)

    print("OpenDota: durations + replay stats")
    od_matches = get(f"https://api.opendota.com/api/leagues/{LEAGUE_ID}/matches")
    if not isinstance(od_matches, list) or not od_matches:
        # OpenDota rate-limits; fall back to the last good response rather than
        # regenerating the site with every duration and rating missing.
        od_matches = load_cache("league_matches.json", [])
        if not od_matches:
            sys.exit("OpenDota returned no games and no cache is available -- try again shortly.")
        print(f"  ! OpenDota unavailable, using cached game list ({len(od_matches)} games)")
    else:
        save_cache("league_matches.json", od_matches)
        print(f"  {len(od_matches)} games")

    team_ids = {m["radiant_team_id"] for m in od_matches} | {m["dire_team_id"] for m in od_matches}
    names = fetch_team_names(sorted(t for t in team_ids if t))

    od_series = collections.defaultdict(list)
    for m in od_matches:
        od_series[m["series_id"]].append(m)
    for games in od_series.values():
        games.sort(key=lambda g: g["start_time"])

    stats = fetch_game_stats([m["match_id"] for m in od_matches])
    scores = score_games(stats)

    # index OpenDota series by the pair of teams that played it
    by_pair = collections.defaultdict(list)
    for sid, games in od_series.items():
        pair = frozenset(
            {names.get(games[0]["radiant_team_id"], ""), names.get(games[0]["dire_team_id"], "")}
        )
        by_pair[pair].append(games)

    def norm(name):
        return re.sub(r"\s+", " ", name).strip().lower()

    lookup = {frozenset(norm(t) for t in pair): v for pair, v in by_pair.items()}

    # chronological; anything still unscheduled (empty bracket slots) goes last
    lp_series.sort(key=lambda s: s["start"] or 2**62)
    out_series, used = [], set()

    for idx, s in enumerate(lp_series):
        key = frozenset(norm(t) for t in s["teams"])
        candidates = [g for g in lookup.get(key, []) if id(g) not in used]
        od_games = None
        if candidates and s["start"]:
            od_games = min(candidates, key=lambda g: abs(g[0]["start_time"] - s["start"]))
            used.add(id(od_games))
        elif candidates:
            od_games = candidates[0]
            used.add(id(od_games))

        games = []
        played = max(len(s["vods"]), len(od_games or []))
        for n in range(1, s["bo"] + 1):
            url = s["vods"].get(n)
            od = od_games[n - 1] if od_games and n <= len(od_games) else None
            if url is None and od is None:
                games.append({"n": n, "played": False})
                continue
            mid = str(od["match_id"]) if od else None
            sc = scores.get(mid, {}) if mid else {}
            duration = (stats.get(mid) or {}).get("duration") if mid else None
            games.append(
                {
                    "n": n,
                    "played": True,
                    "url": url,
                    "matchId": int(mid) if mid else None,
                    "duration": duration,
                    "short": bool(duration and duration < SHORT_GAME_SECONDS),
                    "score": sc.get("score"),
                    "tier": sc.get("tier", 0),
                    "estimated": sc.get("estimated", True),
                    "comeback": sc.get("comeback"),
                    "swings": sc.get("swings"),
                }
            )

        rated = [g for g in games if g.get("played") and g.get("score") is not None]
        out_series.append(
            {
                "id": f"s{idx:03d}",
                "stage": s["stage"],
                "round": s["round"],
                "start": s["start"],
                "teams": s["teams"],
                "bo": s["bo"],
                "complete": s["complete"],
                "gamesPlayed": played,
                "bestTier": max([g["tier"] for g in rated], default=0),
                "bestScore": max([g["score"] for g in rated], default=None),
                "allShort": bool(rated) and all(g["short"] for g in rated),
                "games": games,
            }
        )

    payload = {
        "tournament": {
            "name": "The International 2026",
            "short": "TI 15",
            "city": "Shanghai, China",
            "dates": "August 13-23, 2026",
        },
        "generated": int(time.time()),
        "series": out_series,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "matches.js"), "w") as fh:
        fh.write("// Generated by update.py -- do not edit by hand.\n")
        fh.write("window.TI_DATA = ")
        json.dump(payload, fh, indent=1)
        fh.write(";\n")

    total_games = sum(1 for s in out_series for g in s["games"] if g.get("played"))
    missing = sum(1 for s in out_series for g in s["games"] if g.get("played") and not g.get("url"))
    print(
        f"\nWrote data/matches.js: {len(out_series)} series, {total_games} games"
        + (f" ({missing} without a VOD link yet)" if missing else "")
    )
    request_parses(stats)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="ignore the per-game stats cache")
    args = ap.parse_args()
    if args.full and os.path.exists(os.path.join(CACHE_DIR, "games.json")):
        os.remove(os.path.join(CACHE_DIR, "games.json"))
    build()
