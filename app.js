/* TI 2026 spoiler-free VOD tracker.
 *
 * The one rule everything else follows: nothing on screen may let you count
 * how many games a series actually had. Every Bo3 renders three slots and
 * every Bo5 renders five, played or not, and they are indistinguishable until
 * you deliberately reveal one.
 */

const DATA = window.TI_DATA || { series: [] };
const LS = "ti2026.";

const store = {
  read(key, fallback) {
    try {
      const raw = localStorage.getItem(LS + key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  },
  write(key, value) {
    try {
      localStorage.setItem(LS + key, JSON.stringify(value));
    } catch (e) {
      /* private browsing, quota — the site still works, it just won't remember */
    }
  },
};

const state = {
  watched: store.read("watched", {}),
  peeked: store.read("peeked", {}),
  rounds: store.read("rounds", {}),
  prefs: Object.assign(
    { mode: "progressive", hideWatched: false, onlyGood: false },
    store.read("prefs", {})
  ),
  search: "",
};

const gameKey = (series, game) => series.id + ":" + game.n;

/* ------------------------------------------------------------ reveal rules */

function isRevealed(series, index) {
  const game = series.games[index];
  if (state.peeked[gameKey(series, game)]) return true;
  if (state.prefs.mode === "open") return true;
  if (state.prefs.mode === "strict") return false;
  // progressive: you may see what you are about to watch, never what follows
  if (index === 0) return true;
  return !!state.watched[gameKey(series, series.games[index - 1])];
}

// Series-level ratings are an indirect hint, so strict mode withholds them too.
const showSeriesBadges = () => state.prefs.mode !== "strict";

function seriesStarted(s) {
  return s.gamesPlayed > 0;
}

function seriesFinishedByMe(s) {
  if (!seriesStarted(s)) return false;
  return s.games.every((g, i) => {
    if (state.watched[gameKey(s, g)]) return true;
    return !g.played && isRevealed(s, i);
  });
}

/* ---------------------------------------------------------------- helpers */

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function dayLabel(ts) {
  if (!ts) return "TBD";
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function timeLabel(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function matchesSearch(s) {
  if (!state.search) return true;
  return s.teams.some((t) => t.toLowerCase().includes(state.search));
}

function visibleSeries(s) {
  if (!matchesSearch(s)) return false;
  if (state.prefs.onlyGood && !(s.bestTier > 0)) return false;
  if (state.prefs.hideWatched && seriesFinishedByMe(s)) return false;
  return true;
}

/* ------------------------------------------------------------- round model */

function buildRounds() {
  const map = new Map();
  DATA.series.forEach((s) => {
    const key = s.stage + "|" + s.round;
    if (!map.has(key)) map.set(key, { key, stage: s.stage, round: s.round, series: [] });
    map.get(key).series.push(s);
  });
  return [...map.values()];
}

const ROUNDS = buildRounds();

// Default: open the first round that still has something to watch, and only
// that one — an expanded later round is itself a spoiler about earlier ones.
const DEFAULT_OPEN = (() => {
  const r = ROUNDS.find((rd) => rd.series.some((s) => seriesStarted(s) && !seriesFinishedByMe(s)));
  return r ? r.key : ROUNDS.length ? ROUNDS[ROUNDS.length - 1].key : null;
})();

function isOpen(round) {
  if (state.search) return true; // a filtered list you can't see is useless
  if (round.key in state.rounds) return state.rounds[round.key];
  return round.key === DEFAULT_OPEN;
}

/* ---------------------------------------------------------------- rendering */

function renderGame(s, g, i) {
  const key = gameKey(s, g);
  const watched = !!state.watched[key];
  const revealed = isRevealed(s, i);
  const upcoming = !seriesStarted(s) && !g.played && (s.start || 0) * 1000 > Date.now();

  const classes = ["game"];
  if (watched) classes.push("watched");
  if (revealed && !g.played) classes.push("absent");
  if (upcoming) classes.push("upcoming");

  let label = "Game " + g.n;
  let info;

  if (upcoming) {
    info = '<span class="hidden-dots">—</span>';
  } else if (!revealed) {
    info = '<span class="hidden-dots">•••</span>';
  } else if (!g.played) {
    info = "not played";
  } else {
    // Length itself stays hidden -- only whether it's one of the short ones.
    // Ratings live at series level, so a slot never hints at what it holds.
    const bits = [];
    if (g.short) bits.push('<span class="is-short">⏱ short</span>');
    if (!g.url) bits.push("no VOD yet");
    // nothing to say about a normal-length game -- hold the line so revealed
    // slots keep the same height as their neighbours
    info = bits.join(" ") || "&nbsp;";
    if (g.url) label += ' <span class="yt">▶</span>';
  }

  // A real <a> would leak through the browser's hover status bar, so an
  // unrevealed slot is always a button that decides what to do on click.
  let play;
  if (revealed && g.played && g.url) {
    play = `<a class="play" href="${esc(g.url)}" target="_blank" rel="noreferrer">
        <span class="g-label">${label}</span><span class="g-info">${info}</span></a>`;
  } else if (revealed || upcoming) {
    play = `<div class="play"><span class="g-label">${label}</span><span class="g-info">${info}</span></div>`;
  } else {
    play = `<button class="play" data-act="open" data-key="${key}">
        <span class="g-label">${label}</span><span class="g-info">${info}</span></button>`;
  }

  let side = "";
  if (!upcoming) {
    const tick = revealed && !g.played
      ? ""
      : `<button class="tick ${watched ? "on" : ""}" data-act="tick" data-key="${key}"
           title="${watched ? "Watched" : "Mark as watched"}">${watched ? "✓" : "○"}</button>`;
    const peek = revealed
      ? ""
      : `<button class="peek" data-act="peek" data-key="${key}" title="Reveal length and rating">?</button>`;
    side = `<div class="g-side">${tick}${peek}</div>`;
  }

  return `<div class="${classes.join(" ")}">${play}${side}</div>`;
}

function renderSeries(s) {
  const done = seriesFinishedByMe(s);
  const tbd = s.teams.every((t) => /^tbd$/i.test(t));

  const meta = [];
  if (s.start) meta.push(esc(timeLabel(s.start)));
  meta.push(`<span class="badge bo">Bo${s.bo}</span>`);

  if (!seriesStarted(s)) {
    meta.push(
      (s.start || 0) * 1000 > Date.now()
        ? '<span class="badge soon">scheduled</span>'
        : '<span class="badge live">awaiting VODs</span>'
    );
  } else if (!s.complete) {
    meta.push('<span class="badge live">series in progress</span>');
  }

  if (showSeriesBadges() && seriesStarted(s)) {
    if (s.bestTier === 2) meta.push('<span class="badge tier2">★★ must-watch inside</span>');
    else if (s.bestTier === 1) meta.push('<span class="badge tier1">★ worth watching</span>');
    if (s.allShort) meta.push('<span class="badge short">⏱ all short</span>');
  }

  return `<div class="series ${done ? "done" : ""}">
    <div class="series-main">
      <div class="teams ${tbd ? "tbd" : ""}">${esc(s.teams[0])}<span class="vs">vs</span>${esc(s.teams[1])}</div>
      <div class="series-meta">${meta.join("")}</div>
    </div>
    <div class="games">${s.games.map((g, i) => renderGame(s, g, i)).join("")}</div>
  </div>`;
}

function renderRound(round) {
  const list = round.series.filter(visibleSeries);
  if (!list.length) return "";

  const open = isOpen(round);
  const slots = round.series.reduce((n, s) => n + (seriesStarted(s) ? s.bo : 0), 0);
  const ticked = round.series.reduce(
    (n, s) => n + s.games.filter((g) => state.watched[gameKey(s, g)]).length,
    0
  );
  const allDone = round.series.every((s) => !seriesStarted(s) || seriesFinishedByMe(s));
  const dot = ticked === 0 ? "" : allDone ? "done" : "partial";

  const dates = round.series.map((s) => s.start).filter(Boolean);
  const when = dates.length ? dayLabel(Math.min(...dates)) : "TBD";

  const body = open
    ? `<div class="round-body">${list.map(renderSeries).join("")}</div>`
    : "";

  return `<section class="round">
    <button class="round-head" data-act="round" data-key="${esc(round.key)}" aria-expanded="${open}">
      <span class="chevron">▶</span>
      <span>
        <span class="round-stage">${esc(round.stage)}</span><br>
        <span class="round-name">${esc(round.round)}</span>
      </span>
      <span class="round-meta">
        <span>${esc(when)}</span>
        <span>·</span>
        <span>${list.length} series</span>
        <span>·</span>
        <span>${ticked}/${slots} watched</span>
        <span class="round-dot ${dot}"></span>
      </span>
    </button>
    ${body}
  </section>`;
}

function render() {
  const html = ROUNDS.map(renderRound).join("");
  document.getElementById("app").innerHTML =
    html || '<p class="empty">Nothing matches those filters.</p>';

  // Slots you have personally revealed as never-played drop out of the total,
  // so the counter converges on the real number without ever getting ahead of you.
  let total = 0;
  let seen = 0;
  DATA.series.forEach((s) => {
    if (!seriesStarted(s)) return;
    s.games.forEach((g, i) => {
      if (!g.played && isRevealed(s, i)) return;
      total += 1;
      if (state.watched[gameKey(s, g)]) seen += 1;
    });
  });

  document.getElementById("watchedCount").textContent = seen;
  document.getElementById("totalCount").textContent = total;
  document.getElementById("progressFill").style.width = total ? (100 * seen) / total + "%" : "0%";
}

/* ------------------------------------------------------------------ events */

function findGame(key) {
  const [sid, n] = key.split(":");
  const s = DATA.series.find((x) => x.id === sid);
  return s ? { s, g: s.games[Number(n) - 1] } : null;
}

document.getElementById("app").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  const key = btn.dataset.key;

  if (act === "round") {
    state.rounds[key] = !isOpen(ROUNDS.find((r) => r.key === key));
    store.write("rounds", state.rounds);
    render();
    return;
  }

  const found = findGame(key);
  if (!found) return;

  if (act === "tick") {
    if (state.watched[key]) delete state.watched[key];
    else state.watched[key] = true;
    store.write("watched", state.watched);
  } else if (act === "peek") {
    state.peeked[key] = true;
    store.write("peeked", state.peeked);
  } else if (act === "open") {
    // Opening a slot tells you what it was either way, so reveal it too.
    state.peeked[key] = true;
    store.write("peeked", state.peeked);
    if (found.g.played && found.g.url) window.open(found.g.url, "_blank", "noreferrer");
  }
  render();
});

const bindCheck = (id, pref) => {
  const el = document.getElementById(id);
  el.checked = state.prefs[pref];
  el.addEventListener("change", () => {
    state.prefs[pref] = el.checked;
    store.write("prefs", state.prefs);
    render();
  });
};

bindCheck("hideWatched", "hideWatched");
bindCheck("onlyGood", "onlyGood");

const modeEl = document.getElementById("mode");
modeEl.value = state.prefs.mode;
modeEl.addEventListener("change", () => {
  state.prefs.mode = modeEl.value;
  store.write("prefs", state.prefs);
  render();
});

let searchTimer;
document.getElementById("search").addEventListener("input", (ev) => {
  clearTimeout(searchTimer);
  const value = ev.target.value.trim().toLowerCase();
  searchTimer = setTimeout(() => {
    state.search = value;
    render();
  }, 120);
});

const explain = document.getElementById("explain");
document.getElementById("howBtn").addEventListener("click", () => {
  explain.hidden = !explain.hidden;
});
document.getElementById("explainClose").addEventListener("click", () => {
  explain.hidden = true;
});

document.getElementById("reset").addEventListener("click", () => {
  if (!confirm("Forget which games you've watched and revealed?")) return;
  state.watched = {};
  state.peeked = {};
  state.rounds = {};
  store.write("watched", {});
  store.write("peeked", {});
  store.write("rounds", {});
  render();
});

/* -------------------------------------------------------------------- init */

if (DATA.tournament) {
  document.getElementById("sub").textContent =
    DATA.tournament.city + " · " + DATA.tournament.dates;
}
if (DATA.generated) {
  document.getElementById("stamp").textContent =
    "Data last updated " + new Date(DATA.generated * 1000).toLocaleString();
}

render();
