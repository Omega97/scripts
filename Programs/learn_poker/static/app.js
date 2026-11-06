const state = {
  view: "home",
  mode: null,
  hand: null,
  points: {},
  result: null,
  streak: 0,
  xp: 0,
  hands: 0,
  dashboard: null,
  error: "",
  busy: false,
};

const SUITS = { s: "♠", h: "♥", d: "♦", c: "♣" };

function esc(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function cardHtml(code) {
  const suit = code.slice(-1);
  const rank = code.slice(0, -1).replace("T", "10");
  const red = suit === "h" || suit === "d" ? " red" : "";
  return `<div class="card${red}"><b>${esc(rank)}</b><i>${SUITS[suit] || ""}</i></div>`;
}

function cardsHtml(codes) {
  if (!codes.length) return "";
  return `<div class="cards">${codes.map(cardHtml).join("")}</div>`;
}

function boardHtml(codes) {
  if (!codes.length) return "";
  const streets = [
    ["flop", codes.slice(0, 3)],
    ["turn", codes.slice(3, 4)],
    ["river", codes.slice(4, 5)],
  ].filter(([, cards]) => cards.length);
  const groups = streets.map(([name, cards]) =>
    `<div class="street ${name}">${cards.map(cardHtml).join("")}</div>`
  ).join("");
  return `<div class="cards board">${groups}</div>`;
}

function situationRows(hand) {
  if (hand.rows && hand.rows.length) return hand.rows;
  const parts = String(hand.text || "").split(". ").filter(Boolean);
  return parts.map((line, index) => ({
    text: index < parts.length - 1 ? `${line}.` : line,
    actor: "",
    bet: "",
    pot: "",
  }));
}

function situationHtml(hand) {
  const rows = situationRows(hand);
  const showMoney = rows.some((row) => row.actor || row.bet || row.pot);
  const head = showMoney
    ? `<div class="line head"><span></span><span>Actor</span><span>Bet</span><span>Pot</span></div>`
    : "";
  const body = rows.map((row) => `
    <div class="line">
      <p>${esc(row.text)}</p>
      <span class="who">${esc(row.actor || "")}</span>
      <span class="money bet">${esc(row.bet || "")}</span>
      <span class="money pot">${esc(row.pot || "")}</span>
    </div>
  `).join("");
  return `<div class="situation">${head}${body}</div>`;
}

function handHtml(hand) {
  const board = hand.board.length
    ? `<div class="pile"><span class="pile-label">Board</span>${boardHtml(hand.board)}</div>`
    : "";
  return `<div class="hand">${board}<div class="pile"><span class="pile-label">Hero</span>${cardsHtml(hand.hero)}</div></div>`;
}

function pct(points, total) {
  if (!total) return "0.0%";
  const value = Math.round((points / total) * 1000) / 10;
  return `${value.toFixed(1)}%`;
}

function scoreText(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(2);
}

async function api(path, body) {
  const response = await fetch(path, body ? {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  } : undefined);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function totalPoints() {
  return Object.values(state.points).reduce((sum, value) => sum + value, 0);
}

function homeHtml() {
  const board = state.dashboard;
  const modes = (board.modes || []).map((mode) => `
    <button class="mode${mode.id === "grind" ? " grind" : ""}" data-act="mode" data-mode="${esc(mode.id)}">
      <small>${esc(mode.detail)}</small>
      <strong>${esc(mode.label)}</strong>
    </button>
  `).join("");
  const stats = board.phases.map((phase) => `
    <div class="stat"><span>${esc(phase.label)}</span><b>${scoreText(phase.avg_score)}</b><span>${phase.total_hands} hands</span></div>
  `).join("");
  const recent = board.recent.length
    ? board.recent.map((row) => `
      <li><span>${esc(row.phase_label)}</span><b>${scoreText(row.norm_score)}</b><span>${esc(row.title)}</span></li>
    `).join("")
    : `<li><span>No hands yet.</span></li>`;
  return `
    <header class="top">
      <div>
        <p class="eyebrow">${esc(board.kicker || "Heads-up")}</p>
        <h1>Frequency trainer</h1>
        <p class="lede">Guess how often each action should happen. The mix is the share of the points on each action.</p>
        <p class="dataset-now">${esc(board.dataset ? board.dataset.name : "")}</p>
      </div>
      <div class="home-side">
        <button class="ghost" data-act="settings">Settings</button>
        <div class="pill"><span>Overall</span><b>${scoreText(board.overall.avg_score)}</b><span>${board.overall.total_hands} hands</span></div>
      </div>
    </header>
    <p class="section-label">Play</p>
    <section class="modes">${modes}</section>
    <p class="error">${esc(state.error)}</p>
    <p class="section-label">Stats</p>
    <section class="stats">${stats}</section>
    <section class="recent"><ul>${recent}</ul></section>
    <p class="note">${esc(board.note)}</p>
  `;
}

function playHtml() {
  const hand = state.hand;
  const total = totalPoints();
  const ready = total >= 1 && !state.busy;
  const segments = hand.actions.map((action) => {
    const width = total ? (state.points[action.key] / total) * 100 : 0;
    return `<span style="width:${width}%"></span>`;
  }).join("");
  const actions = hand.actions.map((action) => {
    const points = state.points[action.key] || 0;
    return `
      <article class="action">
        <h2>${esc(action.label)}</h2>
        <div class="controls">
          <button class="step minus" data-act="dec" data-key="${esc(action.key)}" ${points === 0 ? "disabled" : ""} aria-label="Remove a point from ${esc(action.label)}">−</button>
          <div class="freq">
            <span class="pct">
              <span class="pct-sizer" aria-hidden="true">100.0%</span>
              <span class="pct-value">${pct(points, total)}</span>
            </span>
            <span class="points">${points} pts</span>
          </div>
          <button class="step" data-act="inc" data-key="${esc(action.key)}" aria-label="Add a point to ${esc(action.label)}">+</button>
        </div>
      </article>
    `;
  }).join("");
  return `
    <header class="top">
      <div>
        <p class="eyebrow">${esc(hand.phase_label)}</p>
        <h1>${esc(state.mode === "grind" ? "The Grind" : hand.phase_label)}</h1>
      </div>
      <div class="session">
        <div class="pill"><span>Streak</span><b>${state.streak}</b></div>
        <div class="pill"><span>Session</span><b>${state.xp} XP</b></div>
      </div>
    </header>
    <section class="table">
      <div class="spot">
        ${situationHtml(hand)}
        ${handHtml(hand)}
      </div>
    </section>
    <div class="mix" aria-hidden="true">${segments}</div>
    <section class="actions">${actions}</section>
    <footer class="footer">
      <p class="hint">${total === 0 ? "Add a point to lock in" : `${total} point${total === 1 ? "" : "s"}`}</p>
      <button class="lock" data-act="lock" ${ready ? "" : "disabled"}>LOCK IN</button>
    </footer>
    <p class="error">${esc(state.error)}</p>
  `;
}

function resultHtml() {
  const result = state.result;
  const band = result.norm_score >= 0.75 ? "great" : result.norm_score >= 0.55 ? "ok" : "bad";
  const rows = result.actions.map((action) => `
    <div>
      <strong>${esc(action.label)}</strong>
      <div class="pair">
        <div class="bar-row"><span>You ${result.user[action.key]}%</span><div class="track you"><i style="--w:${result.user[action.key]}%"></i></div></div>
        <div class="bar-row"><span>GTO ${result.gto[action.key]}%</span><div class="track gto"><i style="--w:${result.gto[action.key]}%"></i></div></div>
      </div>
    </div>
  `).join("");
  return `
    <header class="top">
      <div>
        <p class="eyebrow">${esc(result.phase_label)}</p>
        <h1>${esc(result.label)}</h1>
      </div>
      <div class="session">
        <div class="pill"><span>Streak</span><b>${state.streak}</b></div>
        <div class="pill"><span>Session</span><b>${state.xp} XP</b></div>
      </div>
    </header>
    <section class="result">
      <div class="score-line">
        <p class="score ${band}">${result.norm_score.toFixed(2)}</p>
        <p class="xp">+${result.xp} XP</p>
      </div>
      <div class="bars">${rows}</div>
    </section>
    <section class="table review">
      <div class="spot">
        ${situationHtml(state.hand)}
        ${handHtml(state.hand)}
      </div>
    </section>
    <footer class="footer">
      <button class="ghost" data-act="home">Return Home</button>
      <button class="lock" data-act="next" ${state.busy ? "disabled" : ""}>Next Hand</button>
    </footer>
  `;
}

function settingsHtml() {
  const datasets = state.dashboard.datasets || [];
  const cards = datasets.map((item) => {
    const count = item.available ? `${Number(item.spots).toLocaleString()} spots` : "Unavailable";
    const mark = item.active ? "Selected" : count;
    return `
      <button class="mode dataset${item.active ? " on" : ""}" data-act="dataset" data-id="${esc(item.id)}" ${item.available ? "" : "disabled"} aria-pressed="${item.active ? "true" : "false"}">
        <small>${esc(mark)}</small>
        <strong>${esc(item.name)}</strong>
        <span class="dataset-detail">${esc(item.detail)}</span>
      </button>
    `;
  }).join("");
  return `
    <header class="top">
      <div>
        <p class="eyebrow">Trainer</p>
        <h1>Settings</h1>
        <p class="lede">Choose which set of poker problems to deal.</p>
      </div>
    </header>
    <p class="section-label">Dataset</p>
    <section class="datasets">${cards}</section>
    <p class="error">${esc(state.error)}</p>
    <footer class="footer">
      <button class="ghost" data-act="home">Back</button>
    </footer>
  `;
}

function render() {
  const root = document.querySelector("#app");
  if (!state.dashboard && state.view === "home") {
    root.innerHTML = `<p class="lede">Loading…</p>`;
    return;
  }
  const page = state.view === "home"
    ? homeHtml()
    : state.view === "settings"
      ? settingsHtml()
      : state.view === "result"
        ? resultHtml()
        : playHtml();
  root.innerHTML = page;
}

async function chooseDataset(id) {
  const current = state.dashboard && state.dashboard.dataset;
  if (state.busy || (current && current.id === id)) return;
  state.busy = true;
  state.error = "";
  render();
  try {
    state.dashboard = await api("/api/settings", { dataset: id });
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function start(mode, exclude) {
  if (state.busy) return;
  state.busy = true;
  state.error = "";
  render();
  try {
    const query = new URLSearchParams({ mode });
    if (exclude) query.set("exclude", exclude);
    state.hand = await api(`/api/hand?${query.toString()}`);
    state.points = Object.fromEntries(state.hand.actions.map((action) => [action.key, 0]));
    state.mode = mode;
    state.view = "play";
    state.result = null;
  } catch (error) {
    state.error = error.message;
    state.view = "home";
  } finally {
    state.busy = false;
    render();
  }
}

async function lockIn() {
  if (state.busy || totalPoints() < 1) return;
  state.busy = true;
  state.error = "";
  render();
  try {
    const result = await api("/api/submit", { id: state.hand.id, points: state.points });
    state.streak = result.norm_score >= 0.75 ? state.streak + 1 : 0;
    state.xp += result.xp;
    state.hands += 1;
    state.result = result;
    state.view = "result";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function goHome() {
  state.view = "home";
  state.streak = 0;
  state.xp = 0;
  state.hands = 0;
  state.hand = null;
  state.result = null;
  state.error = "";
  try {
    state.dashboard = await api("/api/dashboard");
  } catch (error) {
    state.error = error.message;
  }
  render();
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.repeat || event.metaKey || event.ctrlKey || event.altKey) return;
  const button = document.querySelector("[data-act='next']:not(:disabled)");
  if (!button) return;
  event.preventDefault();
  start(state.mode, state.hand && state.hand.id);
});

document.querySelector("#app").addEventListener("click", (event) => {
  const target = event.target.closest("[data-act]");
  if (!target || target.disabled) return;
  const act = target.dataset.act;
  if (act === "mode") start(target.dataset.mode);
  if (act === "inc" || act === "dec") {
    const key = target.dataset.key;
    const next = (state.points[key] || 0) + (act === "inc" ? 1 : -1);
    state.points[key] = Math.max(0, next);
    render();
  }
  if (act === "lock") lockIn();
  if (act === "next") start(state.mode, state.hand && state.hand.id);
  if (act === "home") goHome();
  if (act === "settings") {
    state.view = "settings";
    state.error = "";
    render();
  }
  if (act === "dataset") chooseDataset(target.dataset.id);
});

api("/api/dashboard").then((dashboard) => {
  state.dashboard = dashboard;
  render();
}).catch((error) => {
  state.error = error.message;
  state.dashboard = { phases: [], modes: [], recent: [], overall: { total_hands: 0, avg_score: null }, note: "" };
  render();
});
