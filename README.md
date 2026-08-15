# TI 2026 — spoiler-free VOD tracker

A local, single-page site for watching The International 2026 (Shanghai, Aug 13–23)
from YouTube VODs without learning any result before you watch it.

Open `index.html` in a browser. That's it — no server, no build step, no network
access needed to browse. Everything you've watched is kept in `localStorage`.

## How it stays spoiler-free

The usual way a VOD list spoils a series is by counting: two links under a Bo3
means it ended 2–0. So every series here renders **all** of its slots — three for
a Bo3, five for a Bo5 — whether the game happened or not. Slots are visually
identical until you act on one, and the "play" control is a button rather than a
link so hovering can't reveal in the status bar whether a video exists behind it.
Open a slot for a game that was never played and the site tells you *then*, and
not before.

Rounds are collapsed by default for the same reason: in a Swiss group stage a
later matchup implies an earlier result, so nothing beyond the round you're
working through is on screen unless you open it.

### Reveal modes

| Mode | Behaviour |
| --- | --- |
| **Progressive** (default) | A slot opens up once you tick game *N−1*. You always know what you're about to watch, never what comes after. |
| **Strict** | Nothing until you press `?` on a specific game. The series rating is hidden too, so there's no indirect inference at all. |
| **Open** | Everything visible — for when you're caught up. |

The watched counter's denominator only counts slots you haven't yet revealed as
never-played, so it converges on the true number of games without ever getting
ahead of you.

## Ratings and length

Ratings are surfaced per **series** only — enough to tell you a good game is in
there, never which one it is. Game length is never shown at all; a revealed slot
is marked `⏱ short` if it ran under 35 minutes and carries no mark otherwise.

There is no public site that rates individual professional Dota games, so the
ratings here are computed from the replay data itself (via OpenDota), ranked
against every other game at this TI:

- **Comeback** (30%) — the largest gold deficit the eventual winner climbed out of
- **Lead swings** (25%) — how often the gold lead genuinely changed hands
- **Closeness** (25%) — how tight the gold margin stayed through the back half
- **Kill pace** (20%) — kills per minute

A series is flagged `★★ must-watch inside` if one of its games lands in the top
15% at this TI, or `★ worth watching` for the next 25%. A rating never encodes
who won.

A handful of games have no parsed replay yet; those are scored on kill pace alone
and are deliberately held back from the top tier. Re-running `update.py` asks
OpenDota to parse them and picks them up once it has.

## Updating during the tournament

```sh
python3 update.py          # pull in new games (uses the cache for old ones)
python3 update.py --full   # recompute every game's stats from scratch
```

Or double-click `refresh.command` on macOS, which updates the data and opens the
site.

New games appear as soon as Liquipedia posts their VOD links — usually within a
few hours of the games being played. The Main Event bracket is already listed
with the right shape (including the Bo5 grand final); the matchups fill in as
teams qualify.

Only `python3` is required — standard library plus `curl`, no packages to
install.

## Files

| Path | |
| --- | --- |
| `index.html`, `styles.css`, `app.js` | the site |
| `data/matches.js` | generated data (`window.TI_DATA`) |
| `data/.cache/` | raw API responses, so re-runs are cheap |
| `update.py` | fetch + join + score pipeline |

Schedule and VOD links come from [Liquipedia](https://liquipedia.net/dota2/The_International/2026),
durations and replay stats from [OpenDota](https://www.opendota.com/).

> Note: `data/matches.js` is plain JSON — it does contain the per-game durations
> and ratings that the interface is hiding from you. Don't go reading it.


