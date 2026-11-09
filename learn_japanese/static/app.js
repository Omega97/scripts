const state = {
  boot: null,
  settings: null,
  screen: "home",
  session: null,
  question: null,
  feedback: null,
  selectedKey: null,
  summary: null,
  dashboard: null,
  zen: null,
  zenIndex: 0,
  zenFace: "front",
  revealed: false,
  questionAt: 0,
  busy: false,
  setup: null,
};

const app = document.getElementById("app");
const topbar = document.getElementById("top");
const modal = document.getElementById("modal");
const toast = document.getElementById("toast");
let audioCtx = null;

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  const props = attrs || {};
  Object.keys(props).forEach((key) => {
    const value = props[key];
    if (value == null) return;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  });
  (children || []).forEach((child) => {
    if (child == null) return;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  });
  return node;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function adopt(boot) {
  state.boot = boot;
  state.settings = boot.settings;
  document.body.className = `theme-${boot.theme}` + (boot.settings.reduced_motion ? " reduce-motion" : "");
  renderParticles(boot);
  renderHeader();
}

function renderParticles(boot) {
  const root = document.getElementById("particles");
  root.replaceChildren();
  const seasonal = ["spring", "summer", "autumn", "winter"].includes(boot.theme);
  const reduce = boot.settings.reduced_motion || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!seasonal || reduce) return;
  const kind = boot.season.particle;
  for (let i = 0; i < 14; i += 1) {
    const bit = el("span", { class: `particle ${kind}` });
    bit.style.left = `${Math.random() * 100}%`;
    bit.style.animationDelay = `${Math.random() * 8}s`;
    bit.style.animationDuration = `${9 + Math.random() * 8}s`;
    root.append(bit);
  }
}

function renderHeader() {
  const focus = state.screen === "quiz" && state.session && state.session.focus;
  const streak = focus ? null : el("span", { class: "muted", text: `Streak ${state.boot.streak}  ·  freeze ${state.boot.freezes}` });
  topbar.replaceChildren(
    el("button", { class: "brand", type: "button", onclick: () => goHome() }, [
      el("span", { text: "学び", lang: "ja" }),
      el("small", { text: "Learn Japanese" }),
    ]),
    el("div", { class: "controls" }, [
      streak,
      el("button", {
        class: "chip",
        type: "button",
        "aria-pressed": String(!!state.settings.furigana),
        text: "ふりがな",
        onclick: () => patch({ furigana: !state.settings.furigana }),
      }),
      el("button", {
        class: "chip",
        type: "button",
        "aria-pressed": String(!!state.settings.sound),
        text: state.settings.sound ? "Sound on" : "Sound off",
        onclick: () => patch({ sound: !state.settings.sound }),
      }),
      themeSelect(),
      el("button", {
        class: "chip",
        type: "button",
        "aria-pressed": String(!!state.settings.reduced_motion),
        text: "Motion",
        onclick: () => patch({ reduced_motion: !state.settings.reduced_motion }),
      }),
    ]),
  );
}

function themeSelect() {
  const select = el("select", { class: "chip", "aria-label": "Theme", onchange: (event) => patch({ theme: event.target.value }) });
  [["seasonal", "Seasonal"], ["light", "Light"], ["dark", "Dark"], ["contrast", "Contrast"]].forEach(([value, label]) => {
    const option = el("option", { value, text: label });
    if (state.boot.season_setting === value) option.selected = true;
    select.append(option);
  });
  return select;
}

async function patch(partial) {
  try {
    adopt(await api("/api/settings", partial));
    paint();
  } catch (error) {
    showError(error);
  }
}

function paint() {
  if (state.screen === "home") showHome();
  else if (state.screen === "setup") showSetup(state.setup);
  else if (state.screen === "quiz") showQuiz();
  else if (state.screen === "summary") showSummary();
  else if (state.screen === "dashboard") showDashboard();
  else if (state.screen === "zen") showZen();
}

async function goHome() {
  stopSpeech();
  if (state.screen === "quiz" && state.session) {
    const answered = state.feedback
      ? state.feedback.progress.answered
      : (state.question ? state.question.answered : 0);
    if (answered > 0 && !window.confirm("End this session?")) return;
    try {
      const summary = await api("/api/end", { session_id: state.session.id });
      state.session = null;
      state.question = null;
      state.feedback = null;
      if (summary.answered > 0) {
        state.summary = summary;
        adopt(await api("/api/bootstrap"));
        showSummary();
        return;
      }
    } catch (error) {
      state.session = null;
    }
  }
  state.screen = "home";
  try {
    adopt(await api("/api/bootstrap"));
  } catch (error) {
    showError(error);
  }
  showHome();
}

function showHome() {
  state.screen = "home";
  renderHeader();
  const boot = state.boot;
  const daily = boot.daily;
  app.replaceChildren(
    el("section", { class: "hero" }, [
      el("p", { class: "jp", lang: "ja", text: boot.season.jp }),
      el("p", { class: "romaji", text: boot.season.romaji }),
      el("p", { class: "lede", text: boot.season.en }),
      el("p", { class: "muted", text: `${boot.motto.jp} — ${boot.motto.en}` }),
    ]),
    el("div", { class: "daily" }, [
      ring(daily.done, daily.goal),
      el("div", {}, [
        el("strong", { text: `${daily.done} / ${daily.goal}` }),
        el("div", { class: "muted", text: "problems toward today's goal" }),
      ]),
    ]),
    el("div", { class: "home-grid" }, boot.categories.map((category) => el("button", {
      class: "menu-card",
      type: "button",
      onclick: () => showSetup(category),
    }, [
      el("strong", { text: category.label }),
      el("span", { text: `${category.count} items` }),
    ]))),
    el("div", { class: "home-grid", style: "margin-top:14px" }, [
      el("button", { class: "menu-card", type: "button", onclick: () => openDashboard() }, [
        el("strong", { text: "Dashboard" }),
        el("span", { text: "Streaks, accuracy, and reviews" }),
      ]),
    ]),
    el("h2", { text: "Dictionary" }),
    el("input", {
      class: "search",
      type: "search",
      placeholder: "Kanji, kana, romaji, or English",
      "aria-label": "Search the dictionary",
      onkeydown: (event) => {
        if (event.key === "Enter") searchDictionary(event.target.value);
      },
    }),
    el("div", { id: "results", class: "results" }),
    ...(boot.source ? [el("p", { class: "muted", text: boot.source })] : []),
  );
}

function ring(done, goal) {
  const pct = goal ? Math.max(0, Math.min(1, done / goal)) : 0;
  const length = 2 * Math.PI * 15.5;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 36 36");
  svg.setAttribute("class", "ring");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${done} of ${goal} problems today`);
  const track = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  track.setAttribute("cx", "18");
  track.setAttribute("cy", "18");
  track.setAttribute("r", "15.5");
  track.setAttribute("class", "track");
  const value = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  value.setAttribute("cx", "18");
  value.setAttribute("cy", "18");
  value.setAttribute("r", "15.5");
  value.setAttribute("class", "value");
  value.setAttribute("stroke-dasharray", `${pct * length} ${length}`);
  svg.append(track, value);
  return svg;
}

function showSetup(category) {
  state.screen = "setup";
  renderHeader();
  state.setup = category;
  let mode = category.modes[0].id;
  let length = 10;
  let focus = false;
  const modeRow = el("div", { class: "choices" });
  category.modes.forEach((item, index) => {
    const button = el("button", {
      class: "chip",
      type: "button",
      "aria-pressed": index === 0 ? "true" : "false",
      text: item.label,
      onclick: () => {
        mode = item.id;
        [...modeRow.children].forEach((child) => child.setAttribute("aria-pressed", "false"));
        button.setAttribute("aria-pressed", "true");
      },
    });
    modeRow.append(button);
  });
  const lengthRow = el("div", { class: "choices" });
  [[5, "5"], [10, "10"], [20, "20"], [0, "Endless"]].forEach(([value, label]) => {
    const button = el("button", {
      class: "chip",
      type: "button",
      "aria-pressed": value === 10 ? "true" : "false",
      text: label,
      onclick: () => {
        length = value;
        [...lengthRow.children].forEach((child) => child.setAttribute("aria-pressed", "false"));
        button.setAttribute("aria-pressed", "true");
      },
    });
    lengthRow.append(button);
  });
  const focusButton = el("button", {
    class: "chip",
    type: "button",
    "aria-pressed": "false",
    text: "Focus mode",
    onclick: () => {
      focus = !focus;
      focusButton.setAttribute("aria-pressed", String(focus));
    },
  });
  app.replaceChildren(
    el("h2", { text: category.label }),
    el("p", { class: "muted", text: "習うより慣れよ — learn by doing." }),
    el("p", { class: "sub", text: "Mode" }),
    modeRow,
    el("p", { class: "sub", text: "Session length" }),
    lengthRow,
    el("div", { class: "choices" }, [
      focusButton,
      el("button", { class: "chip", type: "button", text: "Zen mode", onclick: () => openZen(category.id) }),
    ]),
    el("div", { class: "choices" }, [
      el("button", { class: "play", type: "button", text: "Start", onclick: () => startSession(category.id, mode, length, focus) }),
      el("button", { class: "chip", type: "button", text: "Back", onclick: () => showHome() }),
    ]),
  );
  state.launch = { category: category.id, mode, length, focus };
  const remember = () => {
    state.launch = { category: category.id, mode, length, focus };
  };
  modeRow.querySelectorAll("button").forEach((button) => button.addEventListener("click", remember));
  lengthRow.querySelectorAll("button").forEach((button) => button.addEventListener("click", remember));
  focusButton.addEventListener("click", remember);
}

async function startSession(category, mode, length, focus) {
  try {
    const data = await api("/api/session", { category, mode, length, focus });
    state.session = { id: data.session_id, focus: data.focus, endless: data.endless, category, mode };
    state.feedback = null;
    state.selectedKey = null;
    state.revealed = false;
    receiveQuestion(data.question);
    showQuiz();
  } catch (error) {
    showError(error);
  }
}

function receiveQuestion(question) {
  state.question = question;
  state.feedback = null;
  state.selectedKey = null;
  state.revealed = false;
  state.questionAt = performance.now();
  if (question && question.audio && state.settings.sound) speak(question.audio);
}

function showQuiz() {
  state.screen = "quiz";
  renderHeader();
  const question = state.question;
  if (!question) {
    app.replaceChildren(el("p", { text: "This session is finished." }));
    return;
  }
  const focus = question.focus;
  const prompt = el("div", { class: "prompt-wrap" });
  if (question.ruby) {
    prompt.append(el("p", { class: "sentence", lang: "ja" }, renderRuby(question.ruby)));
  } else {
    const size = question.prompt && question.prompt.length > 12 ? "prompt small" : "prompt";
    prompt.append(el("p", { class: size, lang: "ja", text: question.prompt, "aria-label": question.aria || question.prompt }));
  }
  prompt.append(el("p", { class: "sub", text: question.sub || "" }));
  const tools = [];
  if (question.audio) {
    tools.push(el("button", { class: "play", type: "button", text: "Play", onclick: () => speak(question.audio) }));
  }
  if (question.allow_reveal) {
    tools.push(el("button", {
      class: "chip",
      type: "button",
      text: state.revealed ? "Hide text" : "Show text",
      onclick: () => {
        state.revealed = !state.revealed;
        showQuiz();
      },
    }));
  }
  if (state.revealed && question.audio) {
    prompt.append(el("p", { lang: "ja", text: question.audio }));
  }
  const body = [el("p", { class: "muted", text: question.label }), prompt, el("div", { class: "choices" }, tools)];
  if (question.input === "choice") {
    const grid = el("div", { class: "option-grid" });
    question.options.forEach((option, index) => {
      grid.append(el("button", {
        class: "option",
        type: "button",
        lang: "ja",
        "data-key": option.key,
        onclick: () => submitChoice(option.key),
      }, [el("span", { class: "muted", text: `${index + 1}` }), ` ${option.text}`]));
    });
    body.push(grid);
  } else if (!state.feedback) {
    const input = el("input", {
      class: "writing",
      type: "text",
      lang: "ja",
      autocomplete: "off",
      autocapitalize: "off",
      spellcheck: "false",
      "aria-label": question.mode === "HARD" && question.category === "KANJI" ? "Type the kanji" : "Type the romaji",
      onkeydown: (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          submitText(event.target.value);
        }
      },
    });
    body.push(input, el("div", { class: "choices" }, [
      el("button", { class: "chip", type: "button", text: "Check", onclick: () => submitText(input.value) }),
    ]));
    setTimeout(() => input.focus(), 0);
  }
  if (state.feedback) body.push(feedbackCard());
  const progress = state.feedback ? state.feedback.progress : null;
  const answered = progress ? progress.answered : question.answered;
  const totalNow = progress ? progress.total : question.total;
  const shownTotal = (totalNow == null ? "∞" : String(totalNow));
  const combo = state.feedback ? state.feedback.combo : question.combo;
  const dots = focus ? `${question.index} / ${shownTotal}` : dotString(answered, totalNow);
  body.push(el("div", { class: "footer-bar" }, [
    el("span", { class: "dots", text: dots }),
    focus ? null : el("span", { text: `Streak ${combo}` }),
    el("button", { class: "chip", type: "button", text: "End", onclick: () => goHome() }),
  ]));
  app.replaceChildren(el("section", {}, body));
  if (state.feedback) markOptions();
}

function dotString(answered, total) {
  if (total == null) return `${answered} answered`;
  const done = Math.min(answered, total);
  return `${"●".repeat(done)}${"○".repeat(Math.max(0, total - done))}  ${done}/${total}`;
}

function renderRuby(parts) {
  return (parts || []).map((part) => {
    if (part.blank) {
      const gap = el("span", { class: "blank", "aria-label": "blank" });
      gap.style.minWidth = `${part.width || 1}em`;
      return gap;
    }
    if (part.kanji) {
      const ruby = el("ruby", { lang: "ja" }, [part.kanji]);
      const reading = part.reading && !/^#\d+$/.test(part.reading) ? part.reading : "";
      if (state.settings.furigana && reading) ruby.append(el("rt", { text: reading }));
      return ruby;
    }
    return document.createTextNode(part.text || "");
  });
}

async function submitChoice(key) {
  if (state.busy || state.feedback) return;
  state.selectedKey = key;
  await sendAnswer({ option_key: key, text: "" });
}

async function submitText(value) {
  if (state.busy || state.feedback) return;
  if (!String(value || "").trim()) return;
  await sendAnswer({ option_key: null, text: value });
}

async function sendAnswer(payload) {
  state.busy = true;
  const responseMs = Math.max(0, Math.round(performance.now() - state.questionAt));
  try {
    const result = await api("/api/answer", {
      session_id: state.session.id,
      qid: state.question.qid,
      response_ms: responseMs,
      ...payload,
    });
    state.feedback = result;
    state.boot.daily = result.daily;
    state.boot.streak = state.boot.streak;
    if (result.unlocks && result.unlocks.length) showToast(result.unlocks.map((item) => `${item.seal} ${item.name}`).join("  ·  "));
    chime(result.correct ? "ok" : "bad");
    if (result.unlocks && result.unlocks.length) chime("bell");
    if (result.summary) state.summary = result.summary;
    state.pendingNext = result.next;
    showQuiz();
  } catch (error) {
    showError(error);
  } finally {
    state.busy = false;
  }
}

function feedbackCard() {
  const result = state.feedback;
  const bits = [
    el("p", { class: "answer", lang: "ja", text: result.correct_text }),
  ];
  if (result.reading) bits.push(el("p", { lang: "ja", text: result.reading }));
  if (result.meaning && result.meaning !== result.correct_text) bits.push(el("p", { text: result.meaning }));
  if (result.note) bits.push(el("p", { class: "muted", text: result.note }));
  if (result.mnemonic) bits.push(el("p", { text: result.mnemonic }));
  if (result.radicals && result.radicals.length) bits.push(el("p", { class: "muted", text: `Radicals ${result.radicals.join(" · ")}` }));
  if (result.strokes) bits.push(el("p", { class: "muted", text: `${result.strokes} strokes` }));
  if (result.sentence) bits.push(el("p", { class: "sentence", lang: "ja" }, renderRuby(result.sentence)));
  if (result.example) {
    bits.push(el("p", { lang: "ja", text: result.example.jp }));
    if (state.settings.furigana && result.example.kana) bits.push(el("p", { class: "muted", lang: "ja", text: result.example.kana }));
    if (result.example.en) bits.push(el("p", { text: result.example.en }));
  }
  if (result.insight) {
    bits.push(el("p", { lang: "ja", text: result.insight.jp }));
    bits.push(el("p", { class: "muted", text: `${result.insight.romaji} — ${result.insight.en}` }));
  }
  const label = result.summary ? "Summary" : "Next";
  bits.push(el("button", { class: "chip", type: "button", text: label, onclick: advance }));
  return el("article", { class: "card feedback" }, bits);
}

function markOptions() {
  const result = state.feedback;
  document.querySelectorAll(".option").forEach((button) => {
    const key = button.getAttribute("data-key");
    const accepted = new Set(result.accepted_keys || []);
    if (result.correct_key) accepted.add(result.correct_key);
    if (key && accepted.has(key)) button.classList.add("is-correct");
    else if (key && state.selectedKey && key === state.selectedKey && !result.correct) button.classList.add("is-wrong");
  });
}

function advance() {
  stopSpeech();
  if (state.feedback && state.feedback.summary) {
    state.summary = state.feedback.summary;
    state.session = null;
    state.question = null;
    showSummary();
    return;
  }
  if (state.pendingNext) {
    receiveQuestion(state.pendingNext);
    showQuiz();
    return;
  }
  showSummary();
}

function showSummary() {
  state.screen = "summary";
  renderHeader();
  const summary = state.summary || { answered: 0, correct: 0, accuracy: 0, duration_ms: 0, phrase: state.boot.motto, category_label: "", mode_label: "" };
  const pct = Math.round((summary.accuracy || 0) * 100);
  app.replaceChildren(
    el("article", { class: "card summary" }, [
      el("p", { class: "muted", text: `${summary.category_label || ""} · ${summary.mode_label || ""}` }),
      el("p", { class: "prompt", text: `${pct}%` }),
      el("p", { text: `${summary.correct} correct out of ${summary.answered}` }),
      el("p", { class: "muted", text: `Time ${formatDuration(summary.duration_ms || 0)}` }),
      summary.phrase ? el("p", { lang: "ja", text: summary.phrase.jp }) : null,
      summary.phrase ? el("p", { class: "muted", text: `${summary.phrase.romaji} — ${summary.phrase.en}` }) : null,
      el("div", { class: "choices" }, [
        el("button", { class: "chip", type: "button", text: "Home", onclick: () => goHome() }),
      ]),
    ]),
  );
}

async function openDashboard() {
  try {
    state.dashboard = await api("/api/dashboard");
    state.screen = "dashboard";
    showDashboard();
  } catch (error) {
    showError(error);
  }
}

function showDashboard() {
  state.screen = "dashboard";
  renderHeader();
  const data = state.dashboard;
  if (!data) return;
  const accuracy = data.accuracy == null ? "—" : `${Math.round(data.accuracy * 100)}%`;
  app.replaceChildren(
    el("div", { class: "stat-grid" }, [
      stat("Streak", `${data.streak} days`),
      stat("Solved", String(data.solved)),
      stat("Accuracy", accuracy),
      stat("Study time", formatStudy(data.study_ms)),
    ]),
    el("p", { class: "muted", text: `Streak freezes ready: ${data.freezes}. Daily goal ${data.daily.done}/${data.daily.goal}.` }),
    el("h2", { text: "Categories" }),
    el("div", { class: "cat-grid" }, data.categories.map(categoryCard)),
    el("h2", { text: "This week" }),
    el("p", { text: data.weekly }),
    el("h2", { text: "Kanji discovered" }),
    data.discovery.length ? el("div", { class: "discovery" }, data.discovery.map(discoveryCard)) : el("p", { class: "muted", text: "New kanji show up here after you meet them." }),
    el("h2", { text: "Activity" }),
    heatmap(data.heatmap),
    el("h2", { text: "Accuracy, last 30 days" }),
    trendChart(data.trend),
    el("h2", { text: "Review piles" }),
    pie(data.srs),
    el("h2", { text: "Response time" }),
    histogram(data.times),
    el("h2", { text: "Seals" }),
    el("div", { class: "badge-grid" }, data.achievements.map(badge)),
    goalEditor(data.daily.goal),
  );
}

function stat(label, value) {
  return el("article", { class: "card stat" }, [el("span", { class: "muted", text: label }), el("b", { text: value })]);
}

function accuracyClass(value) {
  if (value == null) return "";
  if (value >= 0.8) return "good";
  if (value >= 0.6) return "warn";
  return "bad";
}

function categoryCard(category) {
  const pct = category.total ? Math.round((category.learned / category.total) * 100) : 0;
  const acc = category.accuracy == null ? "—" : `${Math.round(category.accuracy * 100)}%`;
  return el("article", { class: "card stat" }, [
    el("strong", { text: category.label }),
    el("b", { class: accuracyClass(category.accuracy), text: acc }),
    el("div", { class: "bar" }, [el("span", { style: `width:${pct}%` })]),
    el("p", { class: "muted", text: `${category.learned} / ${category.total} learned · ${category.mastered} mastered · ${category.new_this_week} new this week` }),
  ]);
}

function discoveryCard(item) {
  return el("article", { class: "card" }, [
    el("button", {
      class: "glyph",
      type: "button",
      lang: "ja",
      text: item.kanji,
      onclick: () => openItem(item.id),
    }),
    el("div", {}, [
      el("div", { text: item.meaning }),
      el("div", { class: "muted", text: item.date }),
      el("div", { text: item.mnemonic }),
    ]),
  ]);
}

function heatmap(data) {
  const wrap = el("div", { class: "heat", role: "img", "aria-label": "Problems solved per day" });
  data.counts.forEach((count, index) => {
    const level = count === 0 ? 0 : count < 3 ? 1 : count < 6 ? 2 : count < 10 ? 3 : 4;
    wrap.append(el("i", { class: level ? `l${level}` : "", title: `${data.dates[index]}: ${count}` }));
  });
  return wrap;
}

function trendChart(trend) {
  const colors = { HIRAGANA: "#264b73", KATAKANA: "#c9a961", KANJI: "#b5313a", PHRASE: "#6b8e4e" };
  const width = 640;
  const height = 180;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Accuracy trend for the last 30 days");
  Object.keys(trend.series).forEach((category) => {
    const points = [];
    trend.series[category].forEach((value, index) => {
      if (value == null) return;
      const x = (index / Math.max(1, trend.dates.length - 1)) * (width - 8) + 4;
      const y = height - 8 - value * (height - 16);
      points.push(`${x},${y}`);
    });
    if (!points.length) return;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", colors[category] || "#333");
    line.setAttribute("stroke-width", "2");
    line.setAttribute("points", points.join(" "));
    svg.append(line);
  });
  const legend = el("div", { class: "legend" }, Object.keys(colors).map((category) => el("span", {}, [
    el("i", { class: "swatch", style: `background:${colors[category]}` }),
    category === "PHRASE" ? "Phrases" : category[0] + category.slice(1).toLowerCase(),
  ])));
  return el("div", {}, [svg, legend]);
}

function pie(srs) {
  const parts = [
    ["New", srs.new, "#d9d0c1"],
    ["Learning", srs.learning, "#b5313a"],
    ["Review", srs.review, "#264b73"],
    ["Mastered", srs.mastered, "#6b8e4e"],
  ];
  const total = parts.reduce((sum, part) => sum + part[1], 0) || 1;
  let cursor = 0;
  const stops = parts.map((part) => {
    const start = cursor;
    cursor += (part[1] / total) * 100;
    return `${part[2]} ${start}% ${cursor}%`;
  }).join(", ");
  const disk = el("div", { style: `width:140px;height:140px;border-radius:50%;background:conic-gradient(${stops})` });
  const list = el("ul", {}, parts.map((part) => el("li", { text: `${part[0]}: ${part[1]}` })));
  return el("div", { class: "row" }, [disk, list]);
}

function histogram(rows) {
  const max = Math.max(1, ...rows.map((row) => row.count));
  return el("div", { class: "bars" }, rows.map((row) => el("div", { class: "line" }, [
    el("span", { text: row.label }),
    el("span", { class: "fill", style: `width:${Math.round((row.count / max) * 100)}%` }),
    el("span", { text: String(row.count) }),
  ])));
}

function badge(item) {
  return el("article", { class: "card badge" }, [
    el("div", { class: item.unlocked ? "seal on" : "seal", lang: "ja", text: item.seal }),
    el("strong", { text: item.name }),
    el("div", { class: "muted", text: item.detail }),
    el("div", { text: `${item.current} / ${item.target}` }),
  ]);
}

function goalEditor(goal) {
  const input = el("input", { type: "number", min: "1", max: "500", value: String(goal), "aria-label": "Daily goal" });
  return el("div", { class: "choices" }, [
    el("span", { text: "Daily goal" }),
    input,
    el("button", {
      class: "chip",
      type: "button",
      text: "Save",
      onclick: async () => {
        await patch({ daily_goal: Number(input.value) });
        await openDashboard();
      },
    }),
  ]);
}

async function openZen(category) {
  try {
    state.zen = await api(`/api/zen?category=${encodeURIComponent(category)}`);
    state.zenIndex = 0;
    state.zenFace = "front";
    state.screen = "zen";
    showZen();
  } catch (error) {
    showError(error);
  }
}

function showZen() {
  state.screen = "zen";
  renderHeader();
  const cards = state.zen.cards;
  const card = cards[state.zenIndex];
  const face = el("div", { class: "zen-card card", onclick: () => { state.zenFace = state.zenFace === "front" ? "back" : "front"; showZen(); } });
  if (state.zenFace === "front") {
    if (card.front_ruby) face.append(el("div", { class: "sentence", lang: "ja" }, renderRuby(card.front_ruby)));
    else face.append(el("div", { class: "glyph", lang: "ja", text: card.front }));
    face.append(el("p", { class: "muted", text: "Tap to reveal" }));
  } else {
    face.append(el("div", { class: "glyph", lang: "ja", text: card.title }));
    face.append(el("p", { lang: "ja", text: card.reading }));
    face.append(el("p", { text: card.meaning }));
    if (card.mnemonic) face.append(el("p", { text: card.mnemonic }));
    if (card.example_jp) face.append(el("p", { lang: "ja", text: card.example_jp }));
    if (state.settings.furigana && card.example_kana) face.append(el("p", { class: "muted", lang: "ja", text: card.example_kana }));
    if (card.example_en) face.append(el("p", { text: card.example_en }));
  }
  app.replaceChildren(
    el("p", { class: "muted", text: `${state.zen.label} · Zen · ${state.zenIndex + 1} / ${cards.length}` }),
    face,
    el("div", { class: "choices" }, [
      el("button", { class: "chip", type: "button", text: "Previous", onclick: () => stepZen(-1) }),
      el("button", { class: "chip", type: "button", text: "Next", onclick: () => stepZen(1) }),
      el("button", { class: "chip", type: "button", text: "Done", onclick: () => showHome() }),
    ]),
  );
}

function stepZen(delta) {
  const count = state.zen.cards.length;
  state.zenIndex = (state.zenIndex + delta + count) % count;
  state.zenFace = "front";
  showZen();
}

async function searchDictionary(query) {
  const host = document.getElementById("results");
  if (!host) return;
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(query)}`);
    host.replaceChildren(...data.results.map((item) => el("button", {
      class: "menu-card",
      type: "button",
      onclick: () => openCard(item),
    }, [
      el("strong", { lang: "ja", text: item.title }),
      el("span", { text: item.meaning }),
    ])));
    if (!data.results.length) host.append(el("p", { class: "muted", text: "Nothing matched." }));
  } catch (error) {
    showError(error);
  }
}

async function openItem(itemId) {
  try {
    openCard(await api(`/api/item?id=${encodeURIComponent(itemId)}`));
  } catch (error) {
    showError(error);
  }
}

function openCard(card) {
  const bits = [
    el("p", { class: "glyph", lang: "ja", text: card.title }),
    el("p", { lang: "ja", text: card.reading }),
    el("p", { text: card.meaning }),
  ];
  if (card.mnemonic) bits.push(el("p", { text: card.mnemonic }));
  if (card.note) bits.push(el("p", { class: "muted", text: card.note }));
  if (card.strokes) bits.push(el("p", { class: "muted", text: `${card.strokes} strokes` }));
  if (card.radicals && card.radicals.length) bits.push(el("p", { text: `Radicals ${card.radicals.join(" · ")}` }));
  if (card.ruby) bits.push(el("p", { class: "sentence", lang: "ja" }, renderRuby(card.ruby)));
  if (card.example_jp) bits.push(el("p", { lang: "ja", text: card.example_jp }));
  if (state.settings.furigana && card.example_kana) bits.push(el("p", { class: "muted", lang: "ja", text: card.example_kana }));
  if (card.example_en) bits.push(el("p", { text: card.example_en }));
  bits.push(el("button", { class: "chip", type: "button", text: "Close", onclick: closeModal }));
  modal.replaceChildren(el("article", { class: "card dialog", role: "dialog", "aria-modal": "true" }, bits));
  modal.hidden = false;
}

function closeModal() {
  modal.hidden = true;
  modal.replaceChildren();
}

function showToast(text) {
  toast.hidden = false;
  toast.textContent = text;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 4200);
}

function showError(error) {
  showToast(error.message || "Something went wrong.");
}

function formatDuration(ms) {
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatStudy(ms) {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

function speak(text) {
  if (!text || !window.speechSynthesis) {
    showToast("This browser has no speech synthesis. Use Show text.");
    return;
  }
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "ja-JP";
  utter.rate = 0.88;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utter);
}

function stopSpeech() {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

function chime(kind) {
  if (!state.settings || !state.settings.sound) return;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const context = audioCtx;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.connect(gain);
    gain.connect(context.destination);
    const now = context.currentTime;
    if (kind === "ok") {
      oscillator.frequency.setValueAtTime(520, now);
      oscillator.frequency.exponentialRampToValueAtTime(780, now + 0.12);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.07, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.32);
      oscillator.start(now);
      oscillator.stop(now + 0.34);
    } else if (kind === "bad") {
      oscillator.type = "triangle";
      oscillator.frequency.setValueAtTime(180, now);
      gain.gain.setValueAtTime(0.04, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.25);
      oscillator.start(now);
      oscillator.stop(now + 0.26);
    } else {
      oscillator.frequency.setValueAtTime(880, now);
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.06, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.7);
      oscillator.start(now);
      oscillator.stop(now + 0.72);
    }
  } catch (error) {
    /* Audio is optional. */
  }
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeModal();
    return;
  }
  if (event.key === "Enter" && state.screen === "setup" && state.launch && !state.busy) {
    const tag = event.target && event.target.tagName;
    if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
      event.preventDefault();
      const launch = state.launch;
      startSession(launch.category, launch.mode, launch.length, launch.focus);
    }
    return;
  }
  if (state.screen !== "quiz" || state.busy || !state.question) return;
  if (state.feedback) {
    if (event.key === "Enter") {
      event.preventDefault();
      advance();
    }
    return;
  }
  if (state.question.input === "choice") {
    const map = { 1: "a", 2: "b", 3: "c", 4: "d" };
    if (map[event.key]) submitChoice(map[event.key]);
  }
});

api("/api/bootstrap").then((boot) => {
  adopt(boot);
  showHome();
}).catch((error) => {
  app.textContent = error.message || "Could not open the app.";
});
