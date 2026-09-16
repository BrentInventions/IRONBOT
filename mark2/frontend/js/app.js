const STATES = [
  "IDLE", "WATCHING", "EVENT_DETECTED", "MOMENTUM_BUILDING", "TRADE_ARMED",
  "EXECUTE", "TRADE_INITIAL", "TRADE_PROFITABLE", "RUNNER_MANAGEMENT", "EXIT", "COOLDOWN",
];

function $(id) { return document.getElementById(id); }

const HUD_DESIGN_W = 1600;
const HUD_DESIGN_H = 900;
const HUD_SCALE_MIN = 0.55;
const HUD_SCALE_MAX = 1;

function autoHudScale() {
  const w = window.innerWidth || HUD_DESIGN_W;
  const h = window.innerHeight || HUD_DESIGN_H;
  return Math.max(HUD_SCALE_MIN, Math.min(HUD_SCALE_MAX, w / HUD_DESIGN_W, h / HUD_DESIGN_H));
}

function fitIronHud() {
  const scale = autoHudScale();
  document.documentElement.style.zoom = scale >= 0.995 ? "" : String(scale);
  document.documentElement.dataset.uiScale = scale.toFixed(2);
  return scale;
}
window.fitIronHud = fitIronHud;

function setBar(el, pct) {
  if (!el) return;
  el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
}

function cls(el, name, on) {
  if (!el) return;
  el.classList.toggle(name, !!on);
}

function fmt(n, d = 1) {
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return x.toFixed(d);
}

/** Countdown for goal hunt clock — H:MM or Mm. */
function fmtRemain(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}`;
  return `${m}m`;
}

function money(n) {
  const v = Number(n) || 0;
  const sign = v >= 0 ? "+" : "−";
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function moneySigned(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "+$0.00";
  const sign = v >= 0 ? "+" : "−";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function moneyBalance(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "WAITING";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function tradeKey(t) {
  if (t?.key) return String(t.key);
  return [t?.ts, t?.side, t?.entry, t?.exit, t?.pnl, t?.open ? "open" : "closed"].join("|");
}

/** Parse STOP, TRAIL, FAILED_EVENT:vel_fade, HUD_FLAT, etc. for HUD display. */
function formatExitReason(raw) {
  const text = String(raw || "").trim();
  if (!text) return { label: "—", detail: "", cls: "", full: "" };
  const colon = text.indexOf(":");
  let head = text;
  let detail = "";
  if (colon >= 0) {
    head = text.slice(0, colon).trim();
    detail = text.slice(colon + 1).trim().replaceAll("_", " ");
  }
  const upper = head.toUpperCase();
  let cls = "reason-other";
  if (upper === "STOP" || upper === "BREAKEVEN" || upper === "CATASTROPHIC_STOP" || upper === "ATR_STOP" || upper === "HARD_STOP") cls = "reason-stop";
  else if (upper === "TRAIL" || upper === "FLOOR" || upper === "MFE_GIVEBACK" || upper === "PROTECT" || upper === "TIP_TRAIL" || upper === "GROW_BANK" || upper === "ADVERSE_STACK" || upper === "RUNNER_TRAIL") cls = "reason-trail";
  else if (upper === "STRUCTURE_FAILURE" || upper === "COMPRESSION" || upper === "TREND_REVERSAL" || upper === "RSI_CANDLE_DEATH" || upper.startsWith("FAILED_EVENT")) cls = "reason-failed";
  else if (upper.startsWith("HUD_")) cls = "reason-manual";
  const pretty = {
    MFE_GIVEBACK: "MFE GIVEBACK",
    STRUCTURE_FAILURE: "STRUCTURE",
    COMPRESSION: "COMPRESSION",
    PROTECT: "PROTECT",
    CATASTROPHIC_STOP: "HARD STOP",
    ATR_STOP: "HARD STOP",
    HARD_STOP: "HARD STOP",
    TIP_TRAIL: "TIP TRAIL",
    GROW_BANK: "GROW BANK",
    ADVERSE_STACK: "ADVERSE STACK",
    TREND_REVERSAL: "TREND REVERSAL",
    RSI_CANDLE_DEATH: "RSI / CANDLE DEATH",
    FLOOR: "GREEN FLOOR",
    RUNNER_TRAIL: "PURPLE TRAIL",
  };
  const label = upper.startsWith("FAILED_EVENT") ? "FAILED" : (pretty[upper] || head.replace(/^HUD_/, ""));
  const display = detail ? `${label} · ${detail}` : label;
  return { label, detail, cls, full: text, display };
}

function plogRow(t, isNew) {
  const pnl = Number(t.pnl) || 0;
  const pts = Number(t.pts ?? t.points);
  const pnlCls = t.open
    ? (pnl > 0 ? "pos" : pnl < 0 ? "neg" : "")
    : (pnl > 0 ? "pos" : pnl < 0 ? "neg" : "flat");
  const side = String(t.side || "?").toUpperCase();
  const qty = Number(t.qty) || 1;
  const sideCls = side === "LONG" ? "long" : side === "SHORT" ? "short" : "";
  const sideLabel = qty > 1 ? `${side}×${qty}` : side;
  const exitInfo = formatExitReason(t.reason);
  const reasonHtml = t.open
    ? `<span class="plog-reason-tag reason-open">OPEN</span>`
    : `<span class="plog-reason-tag ${exitInfo.cls}" title="${escapeHtml(exitInfo.full)}">${escapeHtml(exitInfo.display)}</span>`;
  const entryExit = t.open
    ? `${fmt(t.entry, 2)} → LIVE`
    : `${fmt(t.entry, 2)} → ${fmt(t.exit, 2)}`;
  const pnlText = t.open
    ? (Number.isFinite(pnl) ? money(pnl) : "+$0.00")
    : money(pnl);
  const ptsText = Number.isFinite(pts) ? `${pts >= 0 ? "+" : ""}${fmt(pts, 1)}` : "—";
  const openCls = t.open ? "is-open" : "";
  const newCls = isNew ? "is-new" : "";
  return `<div class="plog-row ${openCls} ${newCls}" data-key="${escapeHtml(tradeKey(t))}" role="listitem">
    <div class="plog-time">${escapeHtml(t.clock || "—")}${t.day ? `<span class="plog-day">${escapeHtml(t.day)}</span>` : ""}</div>
    <div class="plog-side ${sideCls}">${escapeHtml(sideLabel)}</div>
    <div class="plog-px">${escapeHtml(entryExit)}</div>
    <div class="plog-pts">${escapeHtml(ptsText)}</div>
    <div class="plog-pnl ${pnlCls}">${escapeHtml(pnlText)}</div>
    <div class="plog-reason">${reasonHtml}</div>
  </div>`;
}

let tuningSyncing = false;
let strategySyncing = false;
let strategyHoldUntil = 0;
let tuneDebounce = null;

const INT_GATES = new Set(["build_ticks", "chop_build_ticks"]);

function chopSnapshotKey(gate) {
  return gate.replace(/^chop_/, "");
}

function formatGateValue(gate, val) {
  if (INT_GATES.has(gate)) return String(Math.round(Number(val)));
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  if (gate.includes("velocity") || gate.includes("vel")) return n.toFixed(2);
  return n.toFixed(0);
}

function gateLimit(tuning, gate) {
  const lim = tuning?.limits?.[gate];
  if (!lim) return { min: 0, max: 100, step: 1 };
  return lim;
}

function gateSnapshotValue(tuning, gate, scope) {
  if (!tuning) return 0;
  if (scope === "chop") return tuning.chop?.[chopSnapshotKey(gate)] ?? 0;
  return tuning.trend?.[gate] ?? 0;
}

function renderTuning(tuning) {
  if (!tuning || tuningSyncing) return;
  tuningSyncing = true;
  const strict = $("tune-strictness");
  const strictOut = $("tune-strictness-val");
  const badge = $("tune-mode-badge");
  if (strict) strict.value = String(Math.round(Number(tuning.strictness) || 50));
  if (strictOut) strictOut.textContent = formatGateValue("confidence", tuning.strictness);
  if (badge) {
    badge.textContent = tuning.custom ? "CUSTOM" : "PRESET";
    badge.classList.toggle("custom", !!tuning.custom);
  }
  document.querySelectorAll(".tune-knob").forEach((knob) => {
    const gate = knob.dataset.gate;
    const scope = knob.dataset.scope || "trend";
    const slider = knob.querySelector('input[type="range"]');
    const out = knob.querySelector("output");
    if (!slider || !gate) return;
    const lim = gateLimit(tuning, gate);
    slider.min = String(lim.min);
    slider.max = String(lim.max);
    slider.step = String(lim.step ?? (INT_GATES.has(gate) ? 1 : 0.01));
    const val = gateSnapshotValue(tuning, gate, scope);
    slider.value = String(val);
    if (out) out.textContent = formatGateValue(gate, val);
  });
  const tg = tuning.toggles || {};
  const bookOn = !!tg.book_patterns;
  const emaOn = !!tg.ema_strategy;
  if ($("toggle-trending")) $("toggle-trending").checked = !!tg.require_trending;
  if ($("toggle-chaotic")) $("toggle-chaotic").checked = !!tg.chaotic_bank;
  if ($("toggle-grow-mode")) $("toggle-grow-mode").checked = !!tg.grow_mode;
  if ($("toggle-experimental")) $("toggle-experimental").checked = !!tg.experimental_profile;
  if ($("toggle-candles")) $("toggle-candles").checked = !!tg.candle_align;
  if ($("toggle-book-patterns")) $("toggle-book-patterns").checked = bookOn;
  if ($("toggle-exhaustion")) $("toggle-exhaustion").checked = !!tg.exhaustion_filter;
  if ($("toggle-choppy-bias")) $("toggle-choppy-bias").checked = !!tg.choppy_bias;
  // Book / EMA modes lock conflicting gates; RSI/exhaustion stays the override.
  const locked = [
    "toggle-trending",
    "toggle-chaotic",
    "toggle-experimental",
    "toggle-candles",
    "toggle-choppy-bias",
  ];
  const lockOn = bookOn || emaOn;
  for (const id of locked) {
    const el = $(id);
    if (!el) continue;
    el.disabled = lockOn;
    const lab = el.closest("label");
    if (lab) lab.classList.toggle("is-book-locked", lockOn);
  }
  const exh = $("toggle-exhaustion");
  if (exh) {
    exh.disabled = bookOn; // forced ON in book mode
    const lab = exh.closest("label");
    if (lab) lab.classList.toggle("is-book-locked", bookOn);
  }
  const bookEl = $("toggle-book-patterns");
  if (bookEl) {
    bookEl.disabled = emaOn;
    const lab = bookEl.closest("label");
    if (lab) lab.classList.toggle("is-book-locked", emaOn);
  }
  tuningSyncing = false;
}

function formatStrategyValue(key, val) {
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  if (key === "contracts" || key === "daily_goal" || key === "reentry_cooldown" || key === "mfe_keep_pct" || key === "tip_trail_arm_usd" || key === "breakout_413_max_stop" || key === "tcm8_ema_period" || key === "tcm8_trend_slope_lookback" || key === "tcm8_consolidation_lookback" || key === "tcm8_swing_strength") {
    return String(Math.round(n));
  }
  return n.toFixed(2);
}

function applyStrategyDom(st) {
  if (!st) return;
  document.querySelectorAll("[data-strategy]").forEach((el) => {
    const key = el.dataset.strategy;
    if (key && key in st) el.checked = !!st[key];
  });
  document.querySelectorAll("[data-strategy-num]").forEach((knob) => {
    const key = knob.dataset.strategyNum;
    const slider = knob.querySelector('input[type="range"]');
    const out = knob.querySelector("output");
    if (!slider || !key) return;
    slider.min = knob.dataset.min || slider.min;
    slider.max = knob.dataset.max || slider.max;
    slider.step = knob.dataset.step || slider.step;
    if (key in st) slider.value = String(st[key]);
    if (out) out.textContent = formatStrategyValue(key, slider.value);
  });
  const risk = $("strategy-risk");
  if (risk && st.account_risk) risk.value = String(st.account_risk);
  const mode413 = $("strategy-413-mode");
  if (mode413 && st.breakout_413_mode) mode413.value = String(st.breakout_413_mode);
}

function renderStrategy(st) {
  if (!st || strategySyncing) return;
  if (Date.now() < strategyHoldUntil) return;
  strategySyncing = true;
  try {
    applyStrategyDom(st);
  } finally {
    strategySyncing = false;
  }
}

function scheduleTune(fn) {
  clearTimeout(tuneDebounce);
  tuneDebounce = setTimeout(fn, 100);
}

function startMotes(canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d", { alpha: true });
  let w = 0, h = 0;
  const motes = [];
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const r = canvas.parentElement.getBoundingClientRect();
    w = Math.max(1, r.width); h = Math.max(1, r.height);
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function spawn(m) {
    m.x = Math.random() * w; m.y = Math.random() * h;
    m.r = 0.6 + Math.random() * 1.6;
    m.vx = (Math.random() - 0.5) * 0.18;
    m.vy = -0.08 - Math.random() * 0.22;
    m.a = 0.15 + Math.random() * 0.45;
    m.pulse = Math.random() * Math.PI * 2;
    if (!m.hue) m.hue = Math.random() > 0.45 ? "gold" : "ember";
  }
  for (let i = 0; i < 42; i++) { const m = { hue: Math.random() > 0.45 ? "gold" : "ember" }; spawn(m); motes.push(m); }
  window.addEventListener("resize", resize);
  resize();
  function frame() {
    ctx.clearRect(0, 0, w, h);
    for (const m of motes) {
      m.x += m.vx; m.y += m.vy; m.pulse += 0.02;
      if (m.y < -4 || m.x < -4 || m.x > w + 4) spawn(m);
      const a = m.a * (0.55 + 0.45 * Math.sin(m.pulse));
      const isGold = m.hue !== "ember";
      ctx.beginPath();
      ctx.fillStyle = isGold ? `rgba(255, 193, 74, ${a})` : `rgba(255, 92, 26, ${a})`;
      ctx.shadowColor = isGold ? "rgba(255, 193, 74, 0.7)" : "rgba(255, 92, 26, 0.6)";
      ctx.shadowBlur = 6;
      ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

let _lastStatePaint = "";
function renderStates(current) {
  const track = $("state-track");
  if (!track) return;
  if (current === _lastStatePaint && track.childElementCount) return;
  _lastStatePaint = current;
  track.innerHTML = STATES.map((s) => {
    const now = s === current ? " now" : "";
    const label = s.replaceAll("_", " ");
    return `<span class="state-pill${now}">${label}</span>`;
  }).join("");
}

function renderSide(prefix, side) {
  $(`${prefix}-conf`).textContent = fmt(side.confidence, 0);
  $(`${prefix}-badge`).textContent = fmt(side.confidence, 0);
  $(`${prefix}-vel`).textContent = fmt(side.velocity, 1);
  $(`${prefix}-opp`).textContent = fmt(side.opportunity, 0);
  $(`${prefix}-ext`).textContent = fmt(side.extension, 0);
  setBar($(`${prefix}-conf-bar`), side.confidence);
  setBar($(`${prefix}-opp-bar`), side.opportunity);
  setBar($(`${prefix}-ext-bar`), side.extension);
  const velPct = Math.min(100, Math.abs(side.velocity) * 12);
  setBar($(`${prefix}-vel-bar`), velPct);
  const wrap = $(`${prefix}-vel-bar-wrap`);
  cls(wrap, "up", side.velocity > 0);
  cls(wrap, "down", side.velocity < 0);
}

let _lastLogHtml = null;
let _lastEmaLog = null;
let _lastTcm8Log = null;

function isTcm8Row(r) {
  const blob = [r.sys, r.event, r.note, r.trigger, r.reject].map((x) => String(x || "")).join(" ");
  return r.sys === "tcm8" || /8TCM|TCM8/i.test(blob);
}

function splitDecisionLogs(s) {
  const ema = [];
  const tcm8 = [];
  const srcEma = Array.isArray(s.logEma) ? s.logEma : [];
  const srcT8 = Array.isArray(s.logTcm8) ? s.logTcm8 : [];
  const mixed = Array.isArray(s.log) ? s.log : [];
  const pool = srcEma.length || srcT8.length ? srcEma.concat(srcT8) : mixed;
  for (const r of pool) {
    if (isTcm8Row(r)) tcm8.push(r);
    else ema.push(r);
  }
  return { ema, tcm8 };
}

function logLineHtml(r, sys) {
  let kind = "wait";
  if (r.decision === "OBSERVE_ONLY" || r.decision === "OBSERVE_EXECUTE") kind = "observe";
  else if (r.decision === "CLOSE") kind = "close";
  else if (String(r.decision).includes("EXECUTE") || r.decision === "MANAGE" || r.decision === "ACCEPT") kind = "enter";
  else if (r.decision === "REJECT" || r.decision === "NO_FIRE") kind = "reject";
  else if (r.decision === "EXIT") kind = "exit";
  const tag = sys === "tcm8" ? "8TCM" : "9/20/50";
  let body = "";
  if (r.note) {
    body = String(r.note).replace(/^\s*(8TCM|9\/20\/50)\s*[·:]\s*/i, "");
  } else {
    const exitRaw = r.exitReason || r.exit_reason || "";
    body = r.decision === "EXIT" && exitRaw
      ? `EXIT · ${formatExitReason(exitRaw).display}`
      : String(r.reject || r.decision || "");
    if (r.direction) body = `${r.direction} · ${body}`;
  }
  return `<div class="log-line ${kind}"><span class="log-sys">${tag}</span> ${escapeHtml(body)}</div>`;
}

function renderLog(rows) {
  const html = [...rows].reverse().map((r) => logLineHtml(r, isTcm8Row(r) ? "tcm8" : "ema")).join("");
  const fallback = `<div class="log-line wait">awaiting events…</div>`;
  const next = html || fallback;
  if (next === _lastLogHtml) return;
  _lastLogHtml = next;
  for (const id of ["log-tab", "log-stats"]) {
    const box = $(id);
    if (box) box.innerHTML = next;
  }
}

function renderSysLog(id, rows, sys) {
  const html = [...(rows || [])].reverse().map((r) => logLineHtml(r, sys)).join("");
  const next = html || `<div class="log-line wait">${sys === "tcm8" ? "8TCM quiet" : "9/20/50 quiet"}</div>`;
  if (sys === "ema") {
    if (next === _lastEmaLog) return;
    _lastEmaLog = next;
  } else {
    if (next === _lastTcm8Log) return;
    _lastTcm8Log = next;
  }
  const box = $(id);
  if (box) box.innerHTML = next;
}

function renderGateList(id, steps) {
  const box = $(id);
  if (!box) return;
  const rows = Array.isArray(steps) ? steps : [];
  box.innerHTML = rows.map((st) => {
    const status = String(st.status || "wait");
    const hot = !!st.hot;
    const mark = status === "pass" ? "✓" : status === "fail" ? "✗" : status === "hold" ? "●" : "·";
    const cls = [
      status === "pass" || status === "hold" ? "ok" : "",
      status === "fail" ? "fail" : "",
      status === "wait" ? "wait" : "",
      hot && status !== "fail" ? "hot" : "",
      hot && (status === "pass" || st.id === "fire") ? "go" : "",
    ].filter(Boolean).join(" ");
    const detail = st.detail ? ` · ${st.detail}` : "";
    return `<li class="${cls}"><b>${escapeHtml(mark)}</b> ${escapeHtml(String(st.label || ""))}${escapeHtml(detail)}</li>`;
  }).join("");
}

function renderSystemBoards(s) {
  const emaReady = Array.isArray(s.emaGates) && s.emaGates.some((g) => g.id === "fire" && (g.status === "pass" || g.hot) && g.status !== "fail");
  const t8 = s.tcm8 || {};
  const tcmReady = !!t8.accept || (Array.isArray(t8.checklist) && t8.checklist.some((g) => g.id === "fire" && g.hot && g.status !== "fail"));
  const emaCol = $("sys-ema");
  const tcmCol = $("sys-tcm8");
  if (emaCol) emaCol.classList.toggle("is-ready", !!(s.intersection && s.intersection.fire) || (emaReady && s.intersection && s.intersection.armed920));
  if (tcmCol) tcmCol.classList.toggle("is-ready", tcmReady);
  const emaBadge = $("ema-sys-badge");
  const tcmBadge = $("tcm8-sys-badge");
  if (emaBadge) emaBadge.textContent = (s.intersection && s.intersection.fire) ? "FIRE" : ((s.intersection && s.intersection.armed920) ? "ARMED" : "WATCH");
  if (tcmBadge) tcmBadge.textContent = t8.accept ? "FIRE" : (t8.badge || "WATCH");
  renderGateList("ema-gates", s.emaGates || []);
  renderGateList("tcm8-gates", t8.enabled ? (t8.checklist || []) : []);
  const split = splitDecisionLogs(s);
  renderSysLog("log-ema", split.ema, "ema");
  renderSysLog("log-tcm8", split.tcm8, "tcm8");
}

function moneyPlain(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2);
}

function renderAccountRisk(s) {
  const box = $("acct-risk");
  if (!box) return;
  const ar = s.accountRisk || {};
  const badge = $("acct-risk-badge");
  const state = String(ar.state || "ARMED");
  const emergency = !!ar.emergency || ["DAILY_LOCKOUT", "EQUITY_KILL", "CONNECTION_FAILSAFE"].includes(state);
  if (box) box.classList.toggle("emergency", emergency);
  if (badge) {
    badge.textContent = state;
    badge.classList.toggle("hot", emergency);
  }
  if ($("acct-profile")) $("acct-profile").textContent = ar.profile || "—";
  if ($("acct-equity")) $("acct-equity").textContent = moneyPlain(ar.equity);
  if ($("acct-daily")) $("acct-daily").textContent = moneyPlain(ar.dailyPnl);
  if ($("acct-daily-lim")) $("acct-daily-lim").textContent = moneyPlain(ar.dailyLossLimit);
  if ($("acct-trade-risk")) $("acct-trade-risk").textContent = moneyPlain(ar.tradeRisk);
  if ($("acct-allowed")) $("acct-allowed").textContent = moneyPlain(ar.allowedRisk);
  if ($("acct-qty")) $("acct-qty").textContent = `${ar.contracts || 1} / ${ar.maxContracts || 1}`;
  if ($("acct-risk-state")) $("acct-risk-state").textContent = `Risk State: ${state}`;
}

let _lastBookFlashKey = "";
function renderBookFlash(s) {
  const box = $("book-flash");
  if (!box) return;
  const flash = s.bookFlash;
  if (!flash || !flash.name) {
    box.classList.add("hidden");
    return;
  }
  const key = `${flash.name}|${flash.side}|${flash.ts || ""}`;
  $("book-flash-name").textContent = flash.name;
  $("book-flash-side").textContent = `${flash.side || ""}${flash.detail ? " · " + flash.detail : ""}`;
  box.classList.remove("hidden", "long", "short");
  box.classList.add(String(flash.side || "").toUpperCase() === "SHORT" ? "short" : "long");
  if (key !== _lastBookFlashKey) {
    _lastBookFlashKey = key;
    box.classList.remove("pop");
    void box.offsetWidth;
    box.classList.add("pop");
  }
}

async function api(name, ...args) {
  const bridge = window.pywebview?.api;
  if (!bridge || typeof bridge[name] !== "function") return null;
  return bridge[name](...args);
}

let _armBusy = false;
window.reconArm = async function reconArm(e) {
  if (e) {
    try { e.preventDefault(); e.stopPropagation(); } catch (_) {}
  }
  if (_armBusy) return false;
  _armBusy = true;
  try {
    const s = await api("snapshot");
    if (s && s.enabled) await api("disarm");
    else {
      const out = await api("arm");
      if (out == null) await api("set_enabled", true);
    }
    tick();
  } catch (err) {
    console.error(err);
  } finally {
    setTimeout(() => { _armBusy = false; }, 400);
  }
  return false;
};

const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

const MILESTONES = [
  { id: "live", label: "LIVE", title: "IN TRADE", sub: "PROBATION · HARD STOP ONLY TO +1R", kind: "live", always: true },
  { id: "confirmed", label: "+1R", title: "PROTECTED", sub: "STOP CUT TO ENTRY − 0.25 ATR", kind: "confirmed" },
  { id: "runner", label: "+2R", title: "RUNNER", sub: "70% OF MFE FLOOR · RATCHET UP ONLY", kind: "runner" },
  { id: "lock100", label: "70%", title: "MFE RATCHET", sub: "30% GIVEBACK FROM PEAK", kind: "lock100", sniper: true },
  { id: "lock150", label: "9/20", title: "STRUCTURE WATCH", sub: "9 LOSS WARNS · 9/20 FLIP EXITS", kind: "lock150", sniper: true },
  { id: "lock250", label: "SPR", title: "COMPRESSION", sub: "EXPANSION → CONTRACT = EXIT", kind: "lock250", sniper: true },
];

const BURST = {
  live: { colors: ["#e10600", "#ffb000", "#7ad7ff"], count: 46, speed: 4.2 },
  confirmed: { colors: ["#ffb000", "#fff4e4", "#e10600"], count: 70, speed: 5.4 },
  runner: { colors: ["#e10600", "#ffb000", "#7ad7ff"], count: 90, speed: 6.2 },
  lock100: { colors: ["#ffb000", "#ffe27a", "#fff4e4"], count: 88, speed: 5.8 },
  lock150: { colors: ["#e10600", "#ffb000", "#7ad7ff"], count: 100, speed: 6.4 },
  lock250: { colors: ["#7ad7ff", "#ffb000", "#e10600", "#fff4e4"], count: 140, speed: 7.4 },
  bull: { colors: ["#ffb000", "#e10600", "#7ad7ff"], count: 64, speed: 4.8 },
  climb: { colors: ["#ffb000", "#e10600", "#7ad7ff"], count: 22, speed: 3.4 },
  "exit-bank": { colors: ["#ffb000", "#ffe27a", "#fff4e4"], count: 120, speed: 7.2 },
  "exit-struct": { colors: ["#e10600", "#ffb000", "#ff7828"], count: 110, speed: 6.8 },
  "exit-compress": { colors: ["#7ad7ff", "#e10600", "#ffb000"], count: 130, speed: 7.4 },
  "exit-protect": { colors: ["#ffb000", "#7ad7ff", "#ffffff"], count: 100, speed: 6.4 },
  "exit-stop": { colors: ["#ff2a55", "#e10600", "#ffe600"], count: 90, speed: 6.0 },
};

const EXIT_LEDS = [
  { id: "p0", label: "P0" },
  { id: "r1", label: "+1R" },
  { id: "r2", label: "+2R" },
  { id: "mfe", label: "70%" },
  { id: "e9", label: "9" },
  { id: "e20", label: "20" },
  { id: "spr", label: "SPR" },
  { id: "hot", label: "HOT" },
];

const EXIT_CINEMA = {
  MFE_GIVEBACK: { title: "MFE FLOOR HIT", sub: "30% GIVEBACK — RUNNER BANKED", kind: "exit-bank" },
  STRUCTURE_FAILURE: { title: "STRUCTURE BROKE", sub: "9/20 FLIP CONFIRMED — OUT", kind: "exit-struct" },
  COMPRESSION: { title: "EXPANSION DIED", sub: "EMA SPREAD COMPRESSED — OUT", kind: "exit-compress" },
  PROTECT: { title: "PROTECT STOP", sub: "DOLLAR FLOOR / +1R LOCK — OUT", kind: "exit-protect" },
  CATASTROPHIC_STOP: { title: "HARD STOP", sub: "PROBATION STOP HIT", kind: "exit-stop" },
  ATR_STOP: { title: "HARD STOP", sub: "CATASTROPHIC ATR STOP", kind: "exit-stop" },
  HARD_STOP: { title: "HARD STOP", sub: "CATASTROPHIC STOP HIT — OUT", kind: "exit-stop" },
  TIP_TRAIL: { title: "TIP TRAIL", sub: "TRAIL OFF THE HIGH — BANKED", kind: "exit-bank" },
  GROW_BANK: { title: "GROW BANK", sub: "$50+ STALL — KEPT THE BULK", kind: "exit-bank" },
  ADVERSE_STACK: { title: "ADVERSE STACK", sub: "REDS AFTER THE HIGH — BANKED", kind: "exit-bank" },
  TREND_REVERSAL: { title: "TREND REVERSAL", sub: "9/20 FLIPPED — OUT", kind: "exit-struct" },
  RSI_CANDLE_DEATH: { title: "MOMENTUM DIED", sub: "RSI AND CANDLE FADED — OUT", kind: "exit-compress" },
  FLOOR: { title: "GREEN FLOOR", sub: "GAVE BACK THROUGH THE TARGET", kind: "exit-bank" },
  RUNNER_TRAIL: { title: "PURPLE TRAIL", sub: "TRAIL OFF THE HIGH — BANKED", kind: "exit-bank" },
};

const fx = {
  screen: null,
  dock: null,
  parts: [],
  lastPnl: null,
  lastPrice: null,
  tradeKey: "",
  seen: new Set(),
  queue: [],
  toastOn: false,
  toastTimer: 0,
  hadTrade: false,
  lastExitKey: "",
  exitOn: false,
};

function fxCanvas(el) {
  if (!el) return null;
  el.style.pointerEvents = "none";
  const ctx = el.getContext("2d", { alpha: true });
  const box = { el, ctx, w: 0, h: 0, dpr: 1, fit: null };
  const fit = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = el.getBoundingClientRect();
    box.w = Math.max(1, r.width);
    box.h = Math.max(1, r.height);
    box.dpr = dpr;
    el.width = box.w * dpr;
    el.height = box.h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  box.fit = fit;
  window.addEventListener("resize", fit);
  fit();
  return box;
}

function spawnBurst(target, x, y, kind, extra = 0) {
  if (reduceMotion || !target) return;
  const spec = BURST[kind] || BURST.climb;
  const n = spec.count + extra;
  for (let i = 0; i < n; i++) {
    const ang = (Math.PI * 2 * i) / n + Math.random() * 0.4;
    const spd = spec.speed * (0.35 + Math.random());
    fx.parts.push({
      t: target,
      x,
      y,
      vx: Math.cos(ang) * spd,
      vy: Math.sin(ang) * spd - 1.1,
      life: 0.55 + Math.random() * 0.55,
      age: 0,
      r: 1.1 + Math.random() * 2.4,
      color: spec.colors[i % spec.colors.length],
      g: 0.35 + Math.random() * 0.5,
    });
  }
}

function spawnFountain(target, x, y, strength = 1) {
  if (reduceMotion || !target) return;
  const n = Math.round(10 * strength);
  for (let i = 0; i < n; i++) {
    fx.parts.push({
      t: target,
      x: x + (Math.random() - 0.5) * 36,
      y,
      vx: (Math.random() - 0.5) * 2.2,
      vy: -2.2 - Math.random() * 3.6 * strength,
      life: 0.45 + Math.random() * 0.4,
      age: 0,
      r: 1 + Math.random() * 1.8,
      color: BURST.climb.colors[i % BURST.climb.colors.length],
      g: 0.25 + Math.random() * 0.4,
    });
  }
}

function tickFx(ts) {
  if (!fx._last) fx._last = ts;
  const dt = Math.min(0.05, (ts - fx._last) / 1000);
  fx._last = ts;
  const groups = new Map();
  for (const p of fx.parts) {
    p.age += dt;
    p.x += p.vx;
    p.y += p.vy;
    p.vy += 6.4 * dt;
    p.vx *= 0.99;
    if (!groups.has(p.t)) groups.set(p.t, []);
    groups.get(p.t).push(p);
  }
  fx.parts = fx.parts.filter((p) => p.age < p.life);
  for (const box of [fx.screen, fx.dock]) {
    if (!box) continue;
    box.ctx.clearRect(0, 0, box.w, box.h);
    const list = groups.get(box) || [];
    for (const p of list) {
      const a = Math.max(0, 1 - p.age / p.life);
      box.ctx.beginPath();
      box.ctx.fillStyle = p.color;
      box.ctx.globalAlpha = a;
      box.ctx.shadowColor = p.color;
      box.ctx.shadowBlur = 10;
      box.ctx.arc(p.x, p.y, p.r + p.g, 0, Math.PI * 2);
      box.ctx.fill();
    }
    box.ctx.globalAlpha = 1;
    box.ctx.shadowBlur = 0;
  }
  requestAnimationFrame(tickFx);
}

function tradeFxKey(trade) {
  return `${trade.side}|${trade.entry}|${trade.qty || 1}|${trade.tag || ""}`;
}

function isBullTrade(trade) {
  return String(trade.tag || "") === "EMA_RSI_LONG";
}

function hitMilestones(trade) {
  const locks = trade.locks || {};
  const atr = Math.max(Number(trade.atrAtEntry) || 0, 1e-9);
  const mfe = Number(trade.mfe) || 0;
  const mfeAtr = mfe / atr;
  const peak = Number(trade.peakPnl);
  const peakUsd = Number.isFinite(peak) ? peak : mfe * 2 * (Number(trade.qty) || 1);
  const state = String(trade.state || "").toUpperCase();
  const bull = false;
  const confirmedAt = Number(locks.confirmedAtr) || 1;
  const runnerAt = Number(locks.runnerAtr) || 2;
  const hit = new Set(["live"]);
  if (state === "CONFIRMED" || state === "CONFIRMED_TREND" || state === "RUNNER" || mfeAtr + 1e-9 >= confirmedAt) {
    hit.add("confirmed");
  }
  if (state === "RUNNER" || mfeAtr + 1e-9 >= runnerAt) hit.add("runner");
  if (state === "RUNNER" || Number(locks.floorPts) > 0) hit.add("lock100");
  if (locks.lost20 || locks.warn9) hit.add("lock150");
  if (Number(locks.spread) > 0 && state !== "PROBATION") hit.add("lock250");
  return { hit, peakUsd, mfeAtr, bull };
}

function marksFor(trade) {
  const bull = isBullTrade(trade);
  return MILESTONES.filter((m) => {
    if (m.id === "live") return true;
    if (m.bull) return bull;
    return !bull;
  });
}

function showMilestone(ms) {
  const toast = $("milestone-toast");
  if (!toast) return;
  toast.className = `milestone-toast show ms-${ms.kind}`;
  $("ms-kicker").textContent = "MILESTONE";
  $("ms-title").textContent = ms.title;
  $("ms-sub").textContent = ms.sub;
  const pop = $("pnl-pop");
  if (pop && !pop.classList.contains("hidden")) {
    pop.classList.remove("ms-hit");
    void pop.offsetWidth;
    pop.classList.add("ms-hit");
  }
  if (fx.screen) {
    spawnBurst(fx.screen, fx.screen.w * 0.5, fx.screen.h * 0.38, ms.kind);
    if (ms.kind === "lock250" || ms.kind === "runner") {
      spawnBurst(fx.screen, fx.screen.w * 0.28, fx.screen.h * 0.32, ms.kind, -30);
      spawnBurst(fx.screen, fx.screen.w * 0.72, fx.screen.h * 0.32, ms.kind, -30);
    }
  }
  if (fx.dock) spawnBurst(fx.dock, fx.dock.w * 0.5, fx.dock.h * 0.42, ms.kind, -20);
  clearTimeout(fx.toastTimer);
  fx.toastOn = true;
  fx.toastTimer = setTimeout(() => {
    toast.className = "milestone-toast hidden";
    fx.toastOn = false;
    drainMilestones();
  }, 2600);
}

function drainMilestones() {
  if (fx.toastOn || !fx.queue.length) return;
  showMilestone(fx.queue.shift());
}

function queueMilestone(id) {
  const ms = MILESTONES.find((m) => m.id === id);
  if (!ms || fx.seen.has(id)) return;
  fx.seen.add(id);
  fx.queue.push(ms);
  drainMilestones();
}

function resetTradeFx() {
  fx.tradeKey = "";
  fx.seen = new Set();
  fx.queue = [];
  fx.lastPnl = null;
  fx.tradeColor = "";
  if (fx.exitOn) return;
  fx.toastOn = false;
  clearTimeout(fx.toastTimer);
  const toast = $("milestone-toast");
  if (toast) toast.className = "milestone-toast hidden";
  const pop = $("pnl-pop");
  if (pop) {
    pop.style.removeProperty("--pnl-ink");
    pop.style.removeProperty("--pnl-glow");
  }
  for (const id of ["pnl-dollars", "pnl-pts", "pnl-side"]) {
    const el = $(id);
    if (el) {
      el.style.color = "";
      el.style.textShadow = "";
    }
  }
}

function exitCinemaFor(reason) {
  const head = String(reason || "").toUpperCase().split(":")[0].trim();
  return EXIT_CINEMA[head] || {
    title: "EXIT",
    sub: formatExitReason(reason).display || "FLAT",
    kind: "exit-protect",
  };
}

function playExitCinema(lx) {
  const spec = exitCinemaFor(lx?.reason);
  const key = `${lx?.clock || ""}|${lx?.reason || ""}|${lx?.pnl ?? ""}`;
  if (fx.lastExitKey === key) return;
  fx.lastExitKey = key;
  fx.exitOn = true;
  const toast = $("milestone-toast");
  if (toast) {
    toast.className = `milestone-toast show ms-${spec.kind}`;
    if ($("ms-kicker")) $("ms-kicker").textContent = "EXIT";
    if ($("ms-title")) $("ms-title").textContent = spec.title;
    const pnl = Number(lx?.pnl);
    const extra = Number.isFinite(pnl) ? ` · ${money(pnl)}` : "";
    if ($("ms-sub")) $("ms-sub").textContent = `${spec.sub}${extra}`;
  }
  const flash = $("exit-flash");
  if (flash) {
    flash.className = `exit-flash show ${spec.kind}`;
    setTimeout(() => {
      flash.className = "exit-flash hidden";
    }, 1200);
  }
  const panel = $("exit-panel");
  if (panel) {
    panel.classList.remove("hold-exit");
    void panel.offsetWidth;
    panel.classList.add("hold-exit");
  }
  if (fx.screen) {
    spawnBurst(fx.screen, fx.screen.w * 0.5, fx.screen.h * 0.4, spec.kind, 20);
    spawnBurst(fx.screen, fx.screen.w * 0.22, fx.screen.h * 0.36, spec.kind, -20);
    spawnBurst(fx.screen, fx.screen.w * 0.78, fx.screen.h * 0.36, spec.kind, -20);
  }
  if (fx.dock) spawnBurst(fx.dock, fx.dock.w * 0.5, fx.dock.h * 0.45, spec.kind);
  clearTimeout(fx.toastTimer);
  fx.toastOn = true;
  fx.toastTimer = setTimeout(() => {
    if (toast) toast.className = "milestone-toast hidden";
    fx.toastOn = false;
    fx.exitOn = false;
    drainMilestones();
  }, 3200);
}

function ensureExitLeds() {
  const row = $("exit-leds");
  if (!row || row.childElementCount) return;
  row.innerHTML = EXIT_LEDS.map(
    (l) => `<span class="exit-led" data-led="${l.id}" title="${l.label}"><i></i><em>${l.label}</em></span>`
  ).join("");
}

function setExitLed(id, on, mode) {
  const el = document.querySelector(`#exit-leds [data-led="${id}"]`);
  if (!el) return;
  el.classList.toggle("on", !!on);
  el.classList.toggle("warn", mode === "warn");
  el.classList.toggle("hot", mode === "hot");
}

function renderExitHold(s) {
  ensureExitLeds();
  const panel = $("exit-panel");
  const badge = $("exit-badge");
  const bullets = $("exit-bullets");
  if (!panel || !bullets) return;
  const trade = s.trade;
  if (fx.hadTrade && !trade && s.lastExit) playExitCinema(s.lastExit);
  fx.hadTrade = !!trade;
  if (!trade) {
    const enabled = !!s.enabled;
    panel.classList.toggle("hold-live", enabled);
    panel.classList.toggle("hold-hot", false);
    panel.classList.toggle("hold-armed", enabled);
    if (badge) badge.textContent = enabled ? "ARMED" : "DISARMED";
    for (const l of EXIT_LEDS) setExitLed(l.id, false, "");
    setExitLed("p0", enabled, enabled ? "warn" : "");
    setBar($("exit-r-bar"), 0);
    setBar($("exit-give-bar"), 0);
    setBar($("exit-spr-bar"), 0);
    if ($("exit-r-val")) $("exit-r-val").textContent = "0.00R";
    if ($("exit-give-val")) $("exit-give-val").textContent = "0%";
    if ($("exit-spr-val")) $("exit-spr-val").textContent = "—";
    const lx = s.lastExit;
    const t8 = s.tcm8 || {};
    if (t8.enabled) {
      const armLine = enabled
        ? "BOT ARMED · WAITING FOR 8TCM ENTRY"
        : "DISARMED · CLICK ARM ON CONTROL TO TAKE TRADES";
      if (lx && lx.reason) {
        const info = formatExitReason(lx.reason);
        bullets.innerHTML = `
          <li class="${enabled ? "ok" : "hot"}">${armLine}</li>
          <li class="ok">LAST EXIT · ${escapeHtml(info.display)} ${money(Number(lx.pnl) || 0)}</li>
          <li>${escapeHtml(String(lx.side || "—"))} · ${escapeHtml(lx.clock || "—")}</li>
          <li>CLASSIC TP AT NEXT KEY LEVEL · STOP NEVER WIDENS</li>`;
      } else {
        bullets.innerHTML = `
          <li class="${enabled ? "ok" : "hot"}">${armLine}</li>
          <li>STRUCTURE TREND · RETRACE TO EMA8 · TEST · CLOSE REJECT</li>
          <li>STOP PROTECTS THE EMA8 REJECTION · NEVER WIDENS</li>
          <li>PRIMARY TARGET AT THE NEXT KEY LEVEL · OPTIONAL RUNNER AFTER</li>`;
      }
      return;
    }
    const growOn = !!s.growMode;
    const armLine = enabled
      ? "BOT ARMED · WAITING FOR EMA ENTRY"
      : "DISARMED · CLICK ARM ON CONTROL TO TAKE TRADES";
    const idleTrail = growOn
      ? "$250 GROW · $50+ STALL BANK · THEN $100/$80 RUNNER FLOOR"
      : "$100 ARMS 7.5-PT TIP TRAIL · $80 FLOOR · SCALES TO $550 AT $600";
    const idleGrab = growOn
      ? "$250 START · $50+ GRABS WHEN THE HIGH STALLS"
      : "$100+ ARMS THE 7.5-PT TIP TRAIL AND $80 DOLLAR FLOOR";
    if (lx && lx.reason) {
      const info = formatExitReason(lx.reason);
      bullets.innerHTML = `
        <li class="${enabled ? "ok" : "hot"}">${armLine}</li>
        <li class="ok">LAST EXIT · ${escapeHtml(info.display)} ${money(Number(lx.pnl) || 0)}</li>
        <li>${escapeHtml(String(lx.side || "—"))} · ${escapeHtml(lx.clock || "—")}</li>
        <li>${idleTrail}</li>`;
    } else {
      bullets.innerHTML = `
        <li class="${enabled ? "ok" : "hot"}">${armLine}</li>
        <li>${idleGrab}</li>
        <li>3 REDS AFTER THE HIGH · BANK BEFORE THE HARD STOP</li>
        <li>STILL RUNNING? LEAVE ROOM · $100 → $80 · $600 → $550</li>`;
    }
    return;
  }
  const locks = trade.locks || {};
  const rawState = String(trade.state || "").toUpperCase();
  const state = !rawState || rawState === "WAITING" ? "PROBATION" : rawState;
  const oneR = Number(locks.oneR) || Math.max(Number(trade.atrAtEntry) || 0, 1e-9);
  const rMult = Number(locks.rMultiple);
  const r = Number.isFinite(rMult) ? rMult : (Number(trade.points) || 0) / Math.max(oneR, 1e-9);
  const give = Number(locks.giveback) || 0.3;
  const giveUsed = Number(locks.giveUsed) || 0;
  const compressUsed = Number(locks.compressUsed) || 0;
  const floorPts = Number(locks.floorPts) || 0;
  const openPts = Number(locks.openPts ?? trade.points) || 0;
  const mfe = Number(trade.mfe) || 0;
  const warn9 = !!locks.warn9;
  const lost20 = !!locks.lost20;
  const expanded = !!locks.spreadExpanded;
  const spreadNow = Number(locks.spreadNow) || 0;
  const spreadPeak = Number(locks.spread) || 0;
  const threat = String(locks.threat || "");
  const isRunner = state === "RUNNER";
  const isConf = state === "CONFIRMED" || state === "CONFIRMED_TREND" || isRunner;
  const giveHot = isRunner && giveUsed >= 0.7;
  const sprHot = isConf && expanded && compressUsed >= 0.7;
  const hot = lost20 || giveHot || sprHot;
  panel.classList.toggle("hold-live", true);
  panel.classList.toggle("hold-hot", hot);
  panel.classList.toggle("hold-armed", true);
  if (badge) badge.textContent = hot ? "EXIT HOT" : state;
  setExitLed("p0", true, "");
  setExitLed("r1", isConf || r + 1e-9 >= 1, !isConf && r >= 0.7 ? "warn" : "");
  setExitLed("r2", isRunner || r + 1e-9 >= 2, !isRunner && r >= 1.7 ? "warn" : "");
  setExitLed("mfe", isRunner && floorPts > 0, giveHot ? "hot" : "");
  setExitLed("e9", warn9, warn9 && !lost20 ? "warn" : "");
  setExitLed("e20", lost20, lost20 ? "hot" : "");
  setExitLed("spr", expanded || spreadPeak > 0, sprHot ? "hot" : "");
  setExitLed("hot", hot, hot ? "hot" : "");
  setBar($("exit-r-bar"), (r / 2) * 100);
  setBar($("exit-give-bar"), giveUsed * 100);
  setBar($("exit-spr-bar"), compressUsed * 100);
  $("exit-r-bar")?.closest(".exit-meter")?.classList.toggle("hot", r >= 2);
  $("exit-give-bar")?.closest(".exit-meter")?.classList.toggle("hot", giveHot);
  $("exit-spr-bar")?.closest(".exit-meter")?.classList.toggle("hot", sprHot);
  if ($("exit-r-val")) $("exit-r-val").textContent = `${fmt(r, 2)}R`;
  if ($("exit-give-val")) $("exit-give-val").textContent = `${Math.round(Math.min(giveUsed, 1) * give * 100)}%`;
  if ($("exit-spr-val")) $("exit-spr-val").textContent = spreadPeak > 0 ? `${fmt(spreadNow, 1)}/${fmt(spreadPeak, 1)}` : "—";
  const classic = !!locks.classic;
  const hardPts = Number(locks.hardStopPts) || 20;
  const armUsd = Number(locks.armUsd) || 15;
  const trailPts = Number(locks.trailPts) || 5.5;
  const phaseLine = classic
    ? (isRunner
      ? `PHASE · 10-5 · $${fmt(armUsd, 0)} ARMED · ${fmt(trailPts, 1)} OFF THE TIP`
      : `PHASE · 10-5 · ${fmt(hardPts, 0)} PT STOP · TRAIL ARMS AT $${fmt(armUsd, 0)}`)
    : state === "PROBATION"
      ? `PHASE · SMART EXIT · ${fmt(hardPts, 0)} PT HARD STOP · HOLD TO TARGET`
      : isRunner
        ? (Number(locks.keepUsd) > 0
          ? `PHASE · RUNNER · $${fmt(Number(locks.keepUsd), 0)} FLOOR · ${fmt(trailPts, 1)} PURPLE TRAIL`
          : `PHASE · RUNNER · ${fmt(trailPts, 1)} PURPLE TRAIL · RSI/CANDLE WATCH`)
        : `PHASE · SMART EXIT · ${fmt(hardPts, 0)} PT STOP · TRAIL ARMS AT TARGET`;
  const mfeLine = classic
    ? (isRunner
      ? `MFE ${fmt(mfe, 1)} · OPEN ${fmt(openPts, 1)} · TRAIL ${fmt(trailPts, 1)} OFF TIP`
      : `MFE ${fmt(mfe, 1)} · OPEN ${fmt(openPts, 1)} · TRAIL ARMS AT $${fmt(armUsd, 0)}`)
    : floorPts > 0
      ? `MFE ${fmt(mfe, 1)} · OPEN ${fmt(openPts, 1)} · FLOOR +${fmt(floorPts, 1)}`
      : `MFE ${fmt(mfe, 1)} · OPEN ${fmt(openPts, 1)} · $100 ARMS 7.5 TIP TRAIL`;
  const structLine = classic
    ? `${fmt(hardPts, 0)} PT HARD STOP FROM ENTRY · NO STRUCTURE YANK`
    : lost20
      ? "STRUCTURE · 9/20 AGAINST · NEXT BAR CONFIRMS EXIT"
      : warn9
        ? "STRUCTURE · EMA9 LOSS · WARNING ONLY"
        : "STRUCTURE · 9/20 STACK HOLDS";
  const sprLine = classic
    ? (isRunner ? "GIVEBACK OFF · TIP TRAIL IS THE EXIT" : "GIVEBACK OFF · HARD STOP ONLY UNTIL $15")
    : !isConf
      ? "SPREAD · TRACKING AFTER +1R"
      : expanded && compressUsed >= 1
        ? "SPREAD · COMPRESSION EXIT READY"
        : expanded
          ? `SPREAD · PEAK ${fmt(spreadPeak, 1)} · NOW ${fmt(spreadNow, 1)}`
          : "SPREAD · WAITING FOR EXPANSION";
  const growOn = !!locks.growMode;
  const stallBars = Number(locks.stallBars) || 0;
  if (s.tcm8 && s.tcm8.enabled) {
    const tcm8Fill = String(trade.tag || "").startsWith("8TCM") || !!trade.tcm8Hold;
    if (tcm8Fill) {
      bullets.innerHTML = `
        <li class="ok">8TCM HOLD · STOP ${fmt(trade.stop, 2)} · TP ${fmt(trade.target, 2)}</li>
        <li>HARD STOP NEVER WIDENS</li>
        <li>CLASSIC TP AT THE NEXT KEY LEVEL</li>
        <li>NO EMA TIP TRAIL · NO 9/20 STRUCTURE EXIT</li>`;
      return;
    }
  }
  const keepLine = classic
    ? ""
    : growOn
      ? (stallBars >= 1
        ? `GROW · $${fmt(Number(locks.growGrab) || 50, 0)}+ STALL BANK · ${stallBars} BARS SLOW`
        : "GROW · $50+ IS A BANK IF THE HIGH STALLS · ROOM WHILE IT RUNS")
      : isRunner && Number(locks.keepUsd) > 0
        ? `$100 → $80 FLOOR · SCALES TO $550 AT $600 · NOW $${fmt(Number(locks.keepUsd), 0)}`
        : Number(locks.peakUsd) + 1e-9 >= 100
        ? `7.5 TIP TRAIL ON · ${fmt(trailPts, 1)} OFF THE HIGH`
        : "7.5 TIP TRAIL ARMS AT $100 — NOT +2R";
  bullets.innerHTML = `
    <li class="ok">${escapeHtml(phaseLine)}</li>
    <li>${escapeHtml(mfeLine)}</li>
    <li class="${!classic && (lost20 || warn9) ? "hot" : "ok"}">${escapeHtml(structLine)}</li>
    <li class="${!classic && sprHot ? "hot" : ""}">${escapeHtml(sprLine)}</li>
    ${keepLine ? `<li>${escapeHtml(keepLine)}</li>` : ""}
    <li class="${hot ? "hot" : ""}">NEXT EXIT · ${escapeHtml(threat || "HOLD")}</li>
    <li>${classic ? "10-5 · STOP FIRST · THEN TRAIL THE TIP" : (growOn ? "GROW BANK + COMPRESSION + STRUCTURE" : "COMPRESSION + STRUCTURE + TIP TRAIL")}</li>`;
}

function fmtLvl(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? fmt(n, 2) : "—";
}

function renderBarrierScout(s, bar) {
  const card = $("scout-card");
  const badge = $("scout-badge");
  const call = $("scout-call");
  const list = $("scout-bullets");
  const ixList = $("ix-status");
  const tag = card.querySelector(".scout-tag");
  if (tag) tag.textContent = "MOMENTUM BARRIERS";
  const state = String(bar.state || "").toUpperCase();
  card.classList.toggle("is-take", state.includes("BREAKOUT"));
  card.classList.toggle("is-override", state.includes("TESTING") || state.includes("APPROACH"));
  card.classList.toggle("is-reject", state.includes("REJECTION") || bar.roomOk === false);
  card.classList.toggle("is-short", !!(bar.active && String(bar.active.kind || "").includes("LOW")));
  if (badge) badge.textContent = String(bar.badge || "MAP");
  if (call) call.textContent = String(bar.call || "FLAT · MAPPING SESSION LEVELS");
  const longZ = bar.long || {};
  const shortZ = bar.short || {};
  if (ixList) {
    const longTxt = longZ.found
      ? `${longZ.label || "LONG"} ${fmtLvl(longZ.price)} · ${fmt(Math.abs(Number(longZ.distancePoints) || 0), 1)} PTS`
      : "NONE";
    const shortTxt = shortZ.found
      ? `${shortZ.label || "SHORT"} ${fmtLvl(shortZ.price)} · ${fmt(Math.abs(Number(shortZ.distancePoints) || 0), 1)} PTS`
      : "NONE";
    ixList.innerHTML = `
      <li class="ok">PDH · ${escapeHtml(fmtLvl(bar.pdh))}</li>
      <li class="ok">PDL · ${escapeHtml(fmtLvl(bar.pdl))}</li>
      <li class="${longZ.roomOk === false ? "hot" : (longZ.found ? "ok" : "wait")}">NEXT LONG · ${escapeHtml(longTxt)}</li>
      <li class="${shortZ.roomOk === false ? "hot" : (shortZ.found ? "ok" : "wait")}">NEXT SHORT · ${escapeHtml(shortTxt)}</li>`;
  }
  const bullets = Array.isArray(bar.bullets) && bar.bullets.length
    ? bar.bullets
    : ["AI EXIT ON · TRAIL TIGHTENS AT THE NEXT LEVEL"];
  list.innerHTML = bullets.slice(0, 5).map((b) => `<li>${escapeHtml(String(b))}</li>`).join("");
}

function renderTcm8Scout(s, t8) {
  const card = $("scout-card");
  const badge = $("scout-badge");
  const call = $("scout-call");
  const list = $("scout-bullets");
  const ixList = $("ix-status");
  const tag = card.querySelector(".scout-tag");
  if (tag) tag.textContent = "8TCM";
  const reason = String(t8.reason || "").toUpperCase();
  card.classList.toggle("is-take", !!t8.accept);
      card.classList.toggle("is-override", /RETRACE|REJECTION|EMA8_TEST|TESTING/i.test(String(t8.state || "")));
  card.classList.toggle("is-reject", reason.startsWith("REJECT"));
  card.classList.toggle("is-short", String(t8.direction || "") === "SHORT");
  if (badge) badge.textContent = String(t8.badge || "8TCM");
  if (call) call.textContent = String(t8.call || t8.next || "8TCM · WAITING FOR TREND");
  const steps = Array.isArray(t8.checklist) ? t8.checklist : [];
  if (ixList && steps.length) {
    ixList.innerHTML = steps.map((st) => {
      const status = String(st.status || "wait");
      const cls = status === "pass" ? "ok" : (status === "fail" || status === "hold" ? (status === "hold" ? "ok" : "hot") : "wait");
      const mark = status === "pass" ? "PASS" : status === "fail" ? "FAIL" : status === "hold" ? "HOLD" : "WAIT";
      const detail = st.detail ? ` · ${st.detail}` : "";
      return `<li class="${cls}">${escapeHtml(String(st.label || ""))} · ${mark}${escapeHtml(detail)}</li>`;
    }).join("");
  } else if (ixList) {
    const nextBar = t8.barrier
      ? `${t8.barrier} ${fmtLvl(t8.barrierPrice)}`
      : "NONE";
    ixList.innerHTML = `
      <li class="${t8.htf1h === "BULLISH" ? "ok" : (t8.htf1h === "BEARISH" ? "hot" : "wait")}">1H · ${escapeHtml(String(t8.htf1h || "—"))}</li>
      <li class="${t8.range === "TRENDING" ? "ok" : "wait"}">CHOP · ${escapeHtml(String(t8.range || "—"))}</li>
      <li class="${t8.pullback ? "ok" : "wait"}">EMA8 · ${escapeHtml(t8.ema8 ? fmt(t8.ema8, 2) : "—")} ${t8.pullback ? "PULLBACK" : ""}</li>
      <li class="${t8.barrier ? "ok" : "wait"}">NEXT · ${escapeHtml(nextBar)}</li>`;
  }
  const bullets = Array.isArray(t8.bullets) && t8.bullets.length
    ? t8.bullets
    : ["FIRES ONLY ON A COMPLETED 1m CLOSE · ALL LINES MUST PASS"];
  list.innerHTML = bullets.slice(0, 5).map((b) => `<li>${escapeHtml(String(b))}</li>`).join("");
}

function renderScout(s) {
  const card = $("scout-card");
  const badge = $("scout-badge");
  const call = $("scout-call");
  const list = $("scout-bullets");
  if (!card || !call || !list) return;
  const view = $("view-trade");
  const stage = $("stage");
  const t8 = s.tcm8 || {};
  const tcmOn = !!t8.enabled;
  const bar = s.barriers || {};
  const on = !!bar.enabled;
  const tcmExclusive = !!t8.exclusive;
  if (view) {
    view.classList.toggle("is-tcm8", tcmOn && tcmExclusive);
    view.classList.toggle("is-barriers", on && !tcmOn);
  }
  if (stage) {
    stage.classList.toggle("is-tcm8", tcmOn && tcmExclusive);
    stage.classList.toggle("is-barriers", on && !tcmOn);
  }
  if (tcmOn && tcmExclusive) {
    renderTcm8Scout(s, t8);
    return;
  }
  if (on) {
    renderBarrierScout(s, bar);
    return;
  }
  card.classList.remove("is-reject");
  const tag = card.querySelector(".scout-tag");
  if (tag) tag.textContent = "INTERSECTION";
  const sc = s.scout || {};
  const action = String(sc.action || "HOLD").toUpperCase();
  const side = String(sc.side || "").toUpperCase();
  card.classList.toggle("is-take", action === "TAKE");
  card.classList.toggle("is-override", action === "OVERRIDE");
  card.classList.toggle("is-short", side === "SHORT");
  if (badge) {
    badge.textContent = action === "OVERRIDE" ? "OVERRIDE" : action === "TAKE" ? "TAKE" : "WATCH";
  }
  if (action === "OVERRIDE") {
    call.textContent = `OVERRIDE ${side || "FIRE"} · BOT MISSED THE CROSS`;
  } else if (action === "TAKE") {
    call.textContent = `TAKE ${side} · ${String(sc.why || "AI_SCOUT").replaceAll("_", " ")}`;
  } else if (sc.why === "IN_TRADE") {
    call.textContent = "IN TRADE · SCOUT STANDS DOWN";
  } else if (sc.why === "BOT_HELD") {
    call.textContent = "FILL HELD · SCOUT STANDS DOWN";
  } else if (sc.why === "COOLDOWN") {
    call.textContent = "PAUSE · 5S BETWEEN TRADES";
  } else if (sc.why === "WAIT_CROSS") {
    call.textContent = "HOLD · WAITING FOR 9/50 CONFIRM";
  } else if (sc.why) {
    call.textContent = `HOLD · ${String(sc.why).replaceAll("_", " ")}`;
  } else {
    call.textContent = "FLAT · SPREAD THEN 9/20 THEN 9/50";
  }
  const ix = s.intersection || {};
  const ixList = $("ix-status");
  if (ixList) {
    const sep = Number(ix.sepAtr);
    const sepTxt = Number.isFinite(sep) ? `${fmt(sep, 2)} ATR ${ix.sepMark || ""}`.trim() : "—";
    const tight = !!ix.tight;
    const fire = !!ix.fire;
    const armed = !!ix.armed920 || fire;
    ixList.innerHTML = `
      <li class="${ix.sepOk ? "ok" : "hot"}">EMA SEPARATION · ${escapeHtml(sepTxt)}</li>
      <li class="${armed ? "ok" : "wait"}">9/20 CROSS · ${escapeHtml(String(ix.cross920 || "WAITING"))}</li>
      <li class="${fire ? "ok" : "wait"}">9/50 CONFIRM · ${escapeHtml(String(ix.cross950 || "WAITING"))}</li>
      <li class="${tight ? "hot" : "ok"}">TIGHT STRUCTURE · ${tight ? "TRUE ✗" : "FALSE ✓"}</li>`;
  }
  const bullets = Array.isArray(sc.bullets) && sc.bullets.length
    ? sc.bullets
    : ["WAITING FOR SPREAD 9/20 THEN 9/50"];
  list.innerHTML = bullets.slice(0, 5).map((b) => `<li>${escapeHtml(String(b))}</li>`).join("");
}

function bumpClimb(pop, strength) {
  if (!pop) return;
  pop.classList.remove("climbing");
  void pop.offsetWidth;
  pop.classList.add("climbing");
  if (fx.dock) spawnFountain(fx.dock, fx.dock.w * 0.5, fx.dock.h * 0.58, strength);
  if (fx.screen) spawnBurst(fx.screen, fx.screen.w * 0.5, fx.screen.h * 0.86, "climb", -8);
}

function hexToRgb(hex) {
  const h = String(hex || "").replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function mixHex(a, b, t) {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  const k = Math.max(0, Math.min(1, t));
  const r = Math.round(x.r + (y.r - x.r) * k);
  const g = Math.round(x.g + (y.g - x.g) * k);
  const bl = Math.round(x.b + (y.b - x.b) * k);
  return `rgb(${r}, ${g}, ${bl})`;
}

function livePnlColor(pnl) {
  const v = Number(pnl) || 0;
  if (v < 0) return mixHex("#ffb3be", "#ff1238", Math.min(1, Math.abs(v) / 70));
  if (v < 20) return mixHex("#fff4e4", "#ffb000", v / 20);
  if (v < 80) return mixHex("#ffb000", "#e10600", (v - 20) / 60);
  if (v < 100) return mixHex("#e10600", "#7ad7ff", (v - 80) / 20);
  if (v < 150) return mixHex("#7ad7ff", "#ffe27a", (v - 100) / 50);
  if (v < 250) return mixHex("#ffe27a", "#ff9a3c", (v - 150) / 100);
  return mixHex("#ff9a3c", "#ff2d6a", Math.min(1, (v - 250) / 250));
}

function pnlTone(pnl, hit) {
  const v = Number(pnl) || 0;
  if (v <= -50) return "bleed";
  if (v < -0.01) return "down";
  if (v < 8) return "flat";
  if (hit.has("lock250") && v >= 160) return "fire";
  if (hit.has("lock150") && v >= 70) return "gold";
  if (hit.has("lock100") && v >= 65) return "bank";
  if (hit.has("runner")) return "hot";
  if (hit.has("confirmed")) return "ice";
  return "spark";
}

function paintPnlColor(el, color) {
  if (!el) return;
  el.style.color = color;
  el.style.textShadow = `0 0 8px ${color}, 0 0 22px ${color}`;
}

function applyPnlTone(pop, pnl, hit, slipping) {
  const tone = pnlTone(pnl, hit);
  const color = livePnlColor(pnl);
  const tones = ["bleed", "down", "flat", "spark", "ice", "hot", "bank", "gold", "fire"];
  for (const t of tones) pop.classList.toggle(`tone-${t}`, t === tone);
  pop.classList.toggle("slipping", !!slipping);
  pop.style.setProperty("--pnl-ink", color);
  pop.style.setProperty("--pnl-glow", color);
  paintPnlColor($("pnl-dollars"), color);
  paintPnlColor($("pnl-pts"), color);
  const head = $("pnl-side");
  if (head) head.style.color = color;
  return { tone, color };
}

function renderMarks(trade, hit, freshId) {
  const row = $("pnl-marks");
  if (!row) return;
  row.innerHTML = marksFor(trade).map((m) => {
    const on = hit.has(m.id);
    const fresh = m.id === freshId ? " fresh" : "";
    return `<span class="pnl-mark mk-${m.kind}${on ? " hit" : ""}${fresh}">${m.label}</span>`;
  }).join("");
}

function renderPnl(s) {
  const pop = $("pnl-pop");
  const trade = s.trade;
  if (!pop) return;
  if (!trade) {
    pop.className = "pnl-pop hidden";
    resetTradeFx();
    return;
  }
  const key = tradeFxKey(trade);
  if (key !== fx.tradeKey) {
    resetTradeFx();
    fx.tradeKey = key;
  }
  const pnl = Number(trade.pnl) || 0;
  const pts = Number(trade.points) || 0;
  const side = String(trade.side || "").toUpperCase();
  const state = String(trade.state || "PROBATION").toUpperCase() || "PROBATION";
  const { hit, peakUsd } = hitMilestones(trade);
  const fresh = [];
  for (const id of hit) {
    if (!fx.seen.has(id)) fresh.push(id);
  }
  pop.classList.remove("hidden");
  fx.dock?.fit?.();
  const slipping = fx.lastPnl != null && pnl < fx.lastPnl - 0.49;
  const rising = fx.lastPnl != null && pnl > fx.lastPnl + 0.49;
  const { color } = applyPnlTone(pop, pnl, hit, slipping);
  pop.classList.toggle("up", pnl > 0.01);
  pop.classList.toggle("down", pnl < -0.01);
  pop.classList.toggle("state-confirmed", state === "CONFIRMED" || state === "CONFIRMED_TREND");
  pop.classList.toggle("state-runner", state === "RUNNER" || !!trade.runner);
  $("pnl-side").textContent = `${side}${state === "RUNNER" || trade.runner ? " RUNNER" : ""} · ${trade.qty || 1}`;
  $("pnl-sim").textContent = s.enabled ? "NT LIVE" : "PAUSED";
  if (trade.banked) $("pnl-sim").textContent = `BANK $${fmt(trade.bankDollars || 25, 0)}`;
  if ($("pnl-state")) $("pnl-state").textContent = `${state} · PEAK ${money(peakUsd)}`;
  $("pnl-dollars").textContent = `${pnl >= 0 ? "+" : "-"}$${Math.abs(pnl).toFixed(2)}`;
  $("pnl-pts").textContent = `${pts >= 0 ? "+" : ""}${fmt(pts, 2)} pts`;
  const dollars = $("pnl-dollars");
  if (dollars) {
    dollars.classList.remove("num-up", "num-down");
    void dollars.offsetWidth;
    if (rising) dollars.classList.add("num-up");
    if (slipping) dollars.classList.add("num-down");
  }
  fx.tradeColor = color;
  $("pnl-entry").textContent = fmt(trade.entry, 2);
  $("pnl-stop").textContent = fmt(trade.stop, 2);
  const floorPx = Number(trade.locks?.floorPx);
  $("pnl-target").textContent = floorPx > 0 ? fmt(floorPx, 2) : "—";
  $("pnl-mfe").textContent = fmt(trade.mfe, 1);
  $("pnl-mae").textContent = fmt(trade.mae, 1);
  const hold = Number(trade.holdSec) || 0;
  $("pnl-hold").textContent = hold >= 60 ? `${Math.floor(hold / 60)}m ${Math.round(hold % 60)}s` : `${fmt(hold, 0)}s`;
  renderMarks(trade, hit, fresh[0] || "");
  if (fx.lastPnl != null && pnl > fx.lastPnl + 0.49) {
    bumpClimb(pop, Math.min(3.2, 0.8 + (pnl - fx.lastPnl) / 12));
  }
  fx.lastPnl = pnl;
  for (const id of fresh) queueMilestone(id);
}

function renderPnlLogTarget(s, suffix, state) {
  const list = $(`plog-list${suffix}`);
  const empty = $(`plog-empty${suffix}`);
  const badge = $(`plog-badge${suffix}`);
  if (!list) return;
  const trades = Array.isArray(s.trades) ? s.trades : [];
  const log = s.pnlLog || {};
  const st = s.stats || {};
  const wins = Number(log.wins ?? st.wins) || 0;
  const losses = Number(log.losses ?? st.losses) || 0;
  const count = Number(log.count ?? st.trades) || 0;
  if ($(`st-wl${suffix}`)) $(`st-wl${suffix}`).textContent = `${wins} / ${losses}`;
  if (badge) {
    if (s.trade || log.inTrade) {
      badge.textContent = "IN TRADE";
      badge.style.color = "var(--energy-cyan)";
    } else {
      badge.textContent = count ? `${count} CLOSED` : "FLAT";
      badge.style.color = "";
    }
  }
  const keys = trades.map(tradeKey);
  const sig = trades.map((t) => `${tradeKey(t)}:${t.open ? t.pnl : ""}`).join("¦");
  const prev = state.seen;
  const newKeys = new Set();
  if (prev) {
    for (const k of keys) {
      if (!prev.has(k)) newKeys.add(k);
    }
  }
  state.seen = new Set(keys);
  if (sig === state.sig) return;
  state.sig = sig;
  if (!trades.length) {
    list.innerHTML = "";
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;
  const stickTop = list.scrollTop < 8;
  list.innerHTML = trades.map((t) => plogRow(t, newKeys.has(tradeKey(t)))).join("");
  if (stickTop || newKeys.size) list.scrollTop = 0;
}

const plogStateMain = { sig: "", seen: null };
const plogStateTab = { sig: "", seen: null };

function renderPnlLog(s) {
  renderPnlLogTarget(s, "", plogStateMain);
  renderPnlLogTarget(s, "-tab", plogStateTab);
}

function renderMoney(s) {
  const pnlEl = $("hero-pnl");
  const balEl = $("hero-bal");
  if (!pnlEl || !balEl) return;
  const closed = Number(s.pnlLog?.net ?? s.stats?.net_pnl_after_fees) || 0;
  const open = s.trade ? (Number(s.trade.pnl) || 0) : (Number(s.pnlLog?.open) || 0);
  const botTotal = closed + open;
  const raw = Number(s.sessionPnl);
  let session = Number.isFinite(raw) ? raw : botTotal;
  // Paper / replay fills are not on the NT book. Don't paint NT $0 (or a
  // leftover sim unrealized) over the open trade sitting on the HUD.
  if (s.trade && s.pnlLog?.fromNt !== true) {
    session = botTotal;
  } else if (Math.abs(session) < 0.005 && Math.abs(botTotal) > 0.005) {
    session = botTotal;
  }
  const live = s.trade ? (Number(s.trade.pnl) || 0) : session;
  const ink = s.trade ? (fx.tradeColor || livePnlColor(live)) : "";
  pnlEl.textContent = moneySigned(session);
  pnlEl.className = "amt" + (session > 0.005 ? " pos" : session < -0.005 ? " neg" : "") + (s.trade ? " live-trade" : "");
  if (s.trade && ink) {
    pnlEl.style.color = ink;
    pnlEl.style.textShadow = `0 0 10px ${ink}, 0 0 24px ${ink}`;
  } else {
    pnlEl.style.color = "";
    pnlEl.style.textShadow = "";
  }
  const synced = !!s.accountSynced;
  const equity = Number(s.equity ?? s.net_liquidation);
  const cash = Number(s.cash);
  if (!synced) {
    balEl.textContent = "WAITING";
    balEl.className = "amt wait";
    return;
  }
  const bal = Number.isFinite(equity) && equity !== 0 ? equity : (Number.isFinite(cash) ? cash : 0);
  balEl.textContent = moneyBalance(bal);
  balEl.className = "amt";
}

function renderEmaLamps(s) {
  const lamps = s.emaLights || {};
  const px = Number(s.price) || 0;
  const atr = Number(s.atr) || 0;
  const nearRoom = 0.35 * Math.max(atr, 0.000001);
  const wrap = $("ema-lamps");
  if (wrap) {
    const watch = String(s.emaWatch || "").trim();
    wrap.title = watch
      ? `Watch: ${watch} (EMA lines — not choppy/regime)`
      : "Lights up when price passes red / white / blue";
  }
  const rows = [
    ["lamp-red", "red", "nearRed", Number(s.ema9) || 0],
    ["lamp-white", "white", "nearWhite", Number(s.ema20) || 0],
    ["lamp-blue", "blue", "nearBlue", Number(s.ema50) || 0],
  ];
  for (const [id, onKey, nearKey, level] of rows) {
    const el = $(id);
    if (!el) continue;
    let on = !!lamps[onKey];
    let near = !!lamps[nearKey];
    if (!s.emaLights && px > 0 && level > 0) {
      on = px >= level;
      near = !on && level - px <= nearRoom;
    }
    el.classList.toggle("on", on);
    el.classList.toggle("near", near && !on);
    const line = id === "lamp-red" ? "red 9" : id === "lamp-white" ? "white 20" : "blue 50";
    el.title = on ? `Price passed ${line}` : near ? `Approaching ${line}` : `Below ${line}`;
  }
}

let _lastProductName = "";
let _lastLicenseChip = "";
function paintBrand(s) {
  const iron = document.body.classList.contains("theme-ironman");
  const name = iron ? "IRONBOT" : String(s.product || "").trim();
  if (name && name !== _lastProductName) {
    _lastProductName = name;
    document.title = name;
    const wm = $("wordmark");
    if (wm) {
      if (iron) {
        wm.innerHTML = "IRON<span>BOT</span>";
      } else {
        const parts = name.split(/\s+/);
        if (parts.length >= 2) {
          wm.innerHTML = `${parts.slice(0, -1).join(" ")} <span>${parts[parts.length - 1]}</span>`;
        } else {
          wm.textContent = name;
        }
      }
    }
    const ticker = document.querySelector(".dev-ticker");
    if (ticker) ticker.setAttribute("aria-label", name);
    document.querySelectorAll(".dev-ticker-chunk").forEach((chunk) => {
      const tag = chunk.querySelector(".dev-tag");
      if (tag) tag.textContent = name;
    });
  }
  if (s.kickerLong && $("kicker-long")) $("kicker-long").textContent = s.kickerLong;
  if (s.kickerShort && $("kicker-short")) $("kicker-short").textContent = s.kickerShort;
  if (s.bridgeName && $("hint-bridge")) $("hint-bridge").textContent = s.bridgeName;
  const lic = s.license || {};
  const hint = $("hint-license");
  if (hint) {
    const st = String(lic.status || "").toUpperCase();
    const msg = String(lic.message || "").toUpperCase();
    let text = "LICENSE: REQUIRED";
    if (lic.valid) text = "LICENSE: AUTHORIZED";
    else if (st.includes("NO SERVER") || msg.includes("NO SERVER")) text = "LICENSE: NO SERVER";
    const chip = `${text}|${lic.valid ? "1" : "0"}`;
    if (chip !== _lastLicenseChip) {
      _lastLicenseChip = chip;
      hint.textContent = text;
      hint.classList.toggle("lic-bad", !lic.valid);
    }
  }
}

function renderRsi(s) {
  const gauge = $("rsi-gauge");
  const valEl = $("rsi-value");
  const zoneEl = $("rsi-zone");
  const needle = $("rsi-needle");
  const stochEl = $("rsi-stoch");
  const chaseEl = $("rsi-chase");
  const extEl = $("rsi-ext");
  const momEl = $("rsi-mom");
  const macdEl = $("rsi-macd");
  if (!gauge || !valEl) return;
  const exh = s.exhaustion || {};
  const rsi = exh.rsi;
  const has = rsi != null && Number.isFinite(Number(rsi));
  const v = has ? Number(rsi) : null;
  valEl.textContent = has ? fmt(v, 1) : "—";
  if (stochEl) {
    stochEl.textContent =
      exh.stochRsi != null && Number.isFinite(Number(exh.stochRsi))
        ? fmt(exh.stochRsi, 0)
        : "—";
  }
  if (extEl) {
    const eu = exh.extensionLong;
    const ed = exh.extensionShort;
    extEl.textContent =
      eu != null && ed != null ? `${fmt(eu, 0)}/${fmt(ed, 0)}` : "—";
  }
  if (momEl) {
    const mh = exh.momentumHealth;
    momEl.textContent =
      mh != null && Number.isFinite(Number(mh))
        ? `${Number(mh) >= 0 ? "+" : ""}${fmt(mh, 0)}`
        : "—";
    momEl.style.color =
      mh == null ? "" : Number(mh) > 20 ? "#00ff99" : Number(mh) < -20 ? "#ff5a8a" : "";
  }
  if (macdEl) {
    const d = exh.macdHistDelta;
    const cross = exh.macdCross ? ` ${exh.macdCross}` : "";
    const div = exh.macdDiv ? ` ${exh.macdDiv}-div` : "";
    macdEl.textContent =
      d != null && Number.isFinite(Number(d))
        ? `${Number(d) >= 0 ? "+" : ""}${fmt(d, 2)}${cross}${div}`
        : "—";
  }
  if (chaseEl) {
    const lc = exh.longChase;
    const sc = exh.shortChase;
    chaseEl.textContent =
      lc != null && sc != null ? `${fmt(lc, 0)}/${fmt(sc, 0)}` : "—";
  }
  if (needle) {
    const pct = has ? Math.max(0, Math.min(100, v)) : 50;
    needle.style.left = `${pct}%`;
  }
  gauge.classList.remove("is-ob", "is-os", "is-extreme-ob", "is-extreme-os");
  let zone = String(exh.zone || "mid");
  const ob = Number(exh.obLevel) || 75;
  const os = Number(exh.osLevel) || 25;
  if (has) {
    if (v >= Math.max(80, ob + 5)) zone = "extreme_ob";
    else if (v >= ob) zone = "ob";
    else if (v <= Math.min(20, os - 5)) zone = "extreme_os";
    else if (v <= os) zone = "os";
    else zone = "mid";
  }
  const labels = {
    mid: "NEUTRAL",
    ob: `OVERBOUGHT · ${ob}+`,
    os: `OVERSOLD · ${os}−`,
    extreme_ob: `EXTREME OB · ${Math.max(80, ob + 5)}+`,
    extreme_os: `EXTREME OS · ${Math.min(20, os - 5)}−`,
  };
  if (zoneEl) zoneEl.textContent = labels[zone] || "NEUTRAL";
  if (zone === "ob") gauge.classList.add("is-ob");
  else if (zone === "os") gauge.classList.add("is-os");
  else if (zone === "extreme_ob") gauge.classList.add("is-extreme-ob");
  else if (zone === "extreme_os") gauge.classList.add("is-extreme-os");
}

function paint(s) {
  if (!s) return;
  paintBrand(s);
  const armed = !!s.enabled;
  $("chip-mode").textContent = armed ? "NT LIVE" : "PAUSED";
  if (s.experimentalEnabled) {
    $("chip-mode").textContent += " · EXP";
  }
  if (s.tcm8 && s.tcm8.enabled) {
    $("chip-mode").textContent += " · 8TCM";
  } else if (s.barriers && s.barriers.enabled) {
    $("chip-mode").textContent += s.barriers.exclusive ? " · BARRIERS" : " · BARRIERS+";
  } else if (s.emaStrategyEnabled) {
    $("chip-mode").textContent += " · EMA";
  }
  if (s.growModeEnabled) {
    $("chip-mode").textContent += " · GROW";
  }
  $("chip-mode").className = "chip " + (armed ? "on" : "warn");
  $("chip-link").textContent = s.connected ? "LINK" : "OFFLINE";
  $("chip-link").className = "chip " + (s.connected ? "ok" : "bad");
  $("chip-state").textContent = s.state.replaceAll("_", " ");
  cls($("chip-state"), "on", s.state !== "IDLE");
  $("chip-session").textContent = s.session || "—";
  const trade = s.trade;
  const banner = $("trade-banner");
  const chipTrade = $("chip-trade");
  if (trade) {
    const side = String(trade.side || "").toUpperCase();
    const tcm8Fill = trade.tag && String(trade.tag).startsWith("8TCM");
    const tag = trade.chaoticBank
      ? "QUICK BANK"
      : (tcm8Fill
        ? "8TCM"
        : (trade.tag
          ? String(trade.tag).replaceAll("_", " ")
          : trade.runner
            ? "RUNNER"
            : "IN TRADE"));
    chipTrade.textContent = `${side} ${tag}`;
    chipTrade.className = "chip on " + (side === "SHORT" ? "bad" : "ok");
    banner.className = "trade-banner live " + (side === "SHORT" ? "short" : "long");
    banner.innerHTML = `<div class="type">IN ${side} ${tag} · ${money(trade.pnl)}</div>
      <div class="kv"><span>ENTRY <b>${fmt(trade.entry, 2)}</b></span><span>PNL <b>${money(trade.pnl)}</b></span>
      <span>MFE <b>${fmt(trade.mfe, 1)} pts</b></span><span>MAE <b>${fmt(trade.mae, 1)} pts</b></span>${
        s.barriers && s.barriers.enabled && s.barriers.active && s.barriers.active.found
          ? `<span>NEXT <b>${escapeHtml(String(s.barriers.active.label || "LEVEL"))} ${fmt(s.barriers.active.price, 2)}</b></span>`
          : (trade.tag && String(trade.tag).startsWith("8TCM") && trade.target
            ? `<span>8TCM TP <b>${fmt(trade.target, 2)}</b></span>`
            : "")
      }</div>`;
  } else {
    const ev = s.event || {};
    const why = s.lastReject || "";
    const regime = String(s.trendRegime || "").toUpperCase();
    const chaoticOn = !!s.chaoticBankEnabled;
    const sitOut =
      regime === "QUIET" ||
      regime === "CHOPPY" ||
      (regime === "CHAOTIC" && !chaoticOn) ||
      why === "REJECT_REGIME";
    const tcm8On = !!(s.tcm8 && s.tcm8.enabled && s.tcm8.exclusive);
    if (tcm8On && !trade) {
      const t8 = s.tcm8;
      chipTrade.textContent = t8.accept ? "8TCM READY" : (String(t8.badge || "8TCM"));
      chipTrade.className = "chip " + (t8.accept ? "on" : "warn");
      banner.className = "trade-banner watch";
      banner.innerHTML = `<div class="type">${escapeHtml(String(t8.call || t8.next || "8TCM · WAIT"))}</div>
        <div class="kv"><span>1H <b>${escapeHtml(String(t8.htf1h || "—"))}</b></span><span>${escapeHtml(String(t8.range || "—"))}</span></div>`;
    } else if (regime === "CHAOTIC" && chaoticOn && !trade) {
      chipTrade.textContent = "CHAOTIC BANK";
      chipTrade.className = "chip warn";
      banner.className = "trade-banner watch";
      banner.innerHTML = `<div class="type">CHAOTIC · QUICK BANK MODE</div>
        <div class="kv"><span>BIAS-ALIGNED <b>$25 BANK</b></span></div>`;
    } else if (sitOut && !trade) {
      chipTrade.textContent = "NO TRADE";
      chipTrade.className = "chip warn";
      banner.className = "trade-banner watch";
      banner.innerHTML = `<div class="type">${regime || "CHOP"} · NO ENTRIES</div>
        <div class="kv"><span>WAIT FOR <b>TRENDING</b></span></div>`;
    } else if (ev.type && why) {
      chipTrade.textContent = "WATCHING";
      chipTrade.className = "chip warn";
      banner.className = "trade-banner watch";
      banner.innerHTML = `<div class="type">WATCHING ${ev.direction || ""} RUNNER</div>
        <div class="kv"><span>REJECTED <b>${String(why).replace("REJECT_", "")}</b></span></div>`;
    } else if (s.lastExit && s.lastExit.reason) {
      const lx = s.lastExit;
      const exitInfo = formatExitReason(lx.reason);
      const lxPnl = Number(lx.pnl) || 0;
      chipTrade.textContent = "FLAT";
      chipTrade.className = "chip";
      banner.className = "trade-banner idle last-exit";
      banner.innerHTML = `<div class="type">LAST EXIT · ${escapeHtml(exitInfo.display)} ${money(lxPnl)}</div>
        <div class="kv"><span>${escapeHtml(String(lx.side || "—"))} <b>${escapeHtml(lx.clock || "—")}</b></span></div>`;
    } else if (s.barriers && s.barriers.enabled) {
      chipTrade.textContent = s.barriers.badge || "BARRIERS";
      chipTrade.className = "chip " + (s.barriers.roomOk ? "on" : "warn");
      banner.className = "trade-banner watch";
      banner.innerHTML = `<div class="type">MOMENTUM BARRIERS · ${escapeHtml(String(s.barriers.badge || "MAP"))}</div>
        <div class="kv"><span>${escapeHtml(String(s.barriers.call || "MAPPING LEVELS"))}</span></div>`;
    } else {
      chipTrade.textContent = "FLAT";
      chipTrade.className = "chip";
      banner.className = "trade-banner idle";
      banner.textContent = "FLAT · WATCHING";
    }
  }
  const priceEl = $("price");
  const pxNow = Number(s.price);
  if (priceEl) {
    priceEl.textContent = s.price ? fmt(s.price, 2) : "—";
    if (Number.isFinite(pxNow) && fx.lastPrice != null && Math.abs(pxNow - fx.lastPrice) > 0.01) {
      const up = pxNow > fx.lastPrice;
      priceEl.classList.remove("tick-up", "tick-down");
      void priceEl.offsetWidth;
      priceEl.classList.add(up ? "tick-up" : "tick-down");
    }
    if (Number.isFinite(pxNow)) fx.lastPrice = pxNow;
  }
  renderEmaLamps(s);
  renderExitHold(s);
  renderScout(s);
  renderPnl(s);
  renderMoney(s);
  $("core-badge").textContent = s.state.replaceAll("_", " ");
  $("hint-port").textContent = s.port || 5564;
  renderStates(s.state);
  renderSide("long", s.long || {});
  renderSide("short", s.short || {});
  $("kv-bias").textContent = s.trendBias || "—";
  $("kv-regime").textContent = s.trendRegime || "—";
  $("kv-struct").textContent = s.structure || "—";
  $("kv-vol").textContent = s.volatility || "—";
  $("kv-atr").textContent = fmt(s.atr, 1);
  $("kv-vwap").textContent = fmt(s.vwap, 1);
  $("kv-velocity").textContent = fmt(s.velocity, 2);
  $("kv-impulse").textContent = fmt(s.impulse, 0);
  renderRsi(s);
  renderBookFlash(s);
  const ev = s.event || {};
  $("event-card").innerHTML = ev.type
    ? `<div class="type">${ev.direction} · ${ev.type.replaceAll("_", " ")}</div>
       <div class="kv"><span>ID <b>#${ev.id}</b></span><span>PEAK <b>${fmt(ev.peakConfidence, 0)}</b></span></div>`
    : (s.tcm8 && s.tcm8.enabled && s.tcm8.exclusive
      ? `<div class="idle">8TCM · STRUCTURE TREND · EMA8 RETRACE · REJECTION</div>`
      : (s.barriers && s.barriers.enabled
      ? `<div class="idle">BARRIER TREND · 9/20 ALIGN + ROOM TO NEXT LEVEL</div>`
      : `<div class="idle">NO ACTIVE EVENT</div>`));
  const st = s.stats || {};
  const statIds = ["st-trades", "st-pnl", "st-exp", "st-pf", "st-dd", "st-mfe"];
  for (const id of statIds) {
    let val = "";
    let clsName = "val";
    if (id === "st-trades") val = String(st.trades || 0);
    else if (id === "st-pnl") {
      const net = st.net_pnl_after_fees || 0;
      val = money(net);
      clsName = "val " + (net > 0 ? "pos" : net < 0 ? "neg" : "");
    } else if (id === "st-exp") val = fmt(st.expectancy_per_trade, 2);
    else if (id === "st-pf") val = fmt(st.profit_factor, 2);
    else if (id === "st-dd") val = fmt(st.max_drawdown, 0);
    else if (id === "st-mfe") val = fmt(st.mfe_capture_pct, 0) + "%";
    for (const suf of ["", "-tab"]) {
      const el = $(id + suf);
      if (el) {
        el.textContent = val;
        el.className = clsName;
      }
    }
  }
  renderPnlLog(s);
  renderLog(s.log || []);
  renderSystemBoards(s);
  renderAccountRisk(s);
  const licOk = !s.license || !!s.license.valid;
  cls($("btn-enable"), "on", s.enabled);
  $("btn-enable").textContent = s.enabled ? "ARMED" : "ARM";
  $("btn-enable").title = !licOk
    ? "RECON LICENSE REQUIRED — TRADING DISABLED"
    : s.enabled
      ? "ARMED — click to disarm"
      : "Disarmed — click to arm. No trades until this flashes.";
  $("btn-enable").classList.toggle("lic-locked", !licOk);
  const emaBtn = $("btn-ema-strategy");
  if (emaBtn) {
    const emaOn = !!(s.strategy && s.strategy.ema_92050);
    cls(emaBtn, "on", emaOn);
    emaBtn.textContent = emaOn ? "9/20/50 ON" : "9/20/50";
  }
  const growBtn = $("btn-grow-mode");
  if (growBtn) {
    const growOn = !!(s.growModeEnabled || (s.entryTuning && s.entryTuning.toggles && s.entryTuning.toggles.grow_mode));
    cls(growBtn, "on", growOn);
    growBtn.textContent = growOn ? "GROW BANK ON" : "GROW BANK";
  }
  if ($("qty-val")) $("qty-val").textContent = String(s.contracts || 1);
  if ($("qty-bank")) {
    const g = s.dailyGoal || {};
    let huntTag = "";
    if (g.hunting) huntTag = g.pressurePush ? " PUSH" : " HUNT";
    $("qty-bank").textContent = `BANK $${fmt(s.bankDollars || 25, 0)}${huntTag}`;
  }
  if ($("goal-val")) {
    const g = s.dailyGoal || {};
    $("goal-val").textContent = fmt(g.goal || 0, 0);
    if ($("goal-remain")) {
      if (g.met) $("goal-remain").textContent = "HIT · LOCKED";
      else if (!g.enabled) $("goal-remain").textContent = "OFF";
      else $("goal-remain").textContent = `LEFT $${fmt(g.remaining || 0, 0)}`;
    }
  }
  if ($("clock-val")) {
    const g = s.dailyGoal || {};
    const wh = Number(g.windowHours || 0);
    $("clock-val").textContent = wh <= 0 ? "OFF" : `${fmt(wh, 1)}H`;
    if ($("clock-remain")) {
      if (wh <= 0) $("clock-remain").textContent = "NO LIMIT";
      else if (g.met) $("clock-remain").textContent = "DONE";
      else if (!g.enabled) $("clock-remain").textContent = "OFF";
      else if (g.expired) $("clock-remain").textContent = "TIME UP";
      else if (g.pressurePush) $("clock-remain").textContent = `${fmtRemain(g.remainSec)} PUSH`;
      else $("clock-remain").textContent = `${fmtRemain(g.remainSec)} LEFT`;
    }
  }
  if ($("stop-val")) $("stop-val").textContent = fmt(s.stopPoints || 20, 1);
  if ($("stop-dollars")) $("stop-dollars").textContent = `$${fmt(s.stopDollars || 40, 0)}`;
  const inTrade = !!s.trade;
  if ($("btn-buy")) $("btn-buy").disabled = inTrade;
  if ($("btn-sell")) $("btn-sell").disabled = inTrade;
  renderTuning(s.entryTuning);
  renderStrategy(s.strategy || {});
}

async function tick() {
  try {
    const s = await api("snapshot");
    if (s) paint(s);
  } catch (err) {
    console.error(err);
  }
}

function bindTabs() {
  const tabs = document.querySelectorAll(".hud-tab");
  const views = document.querySelectorAll(".hud-view");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.view;
      if (!name) return;
      tabs.forEach((t) => t.classList.toggle("is-active", t === tab));
      views.forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
    });
  });
}

function bind() {
  const armBtn = $("btn-enable");
  if (armBtn) {
    armBtn.addEventListener("pointerdown", (e) => { window.reconArm(e); }, true);
  }
  if ($("btn-ema-strategy")) {
    $("btn-ema-strategy").addEventListener("click", async () => {
      const s = await api("snapshot");
      const on = !!(s && s.strategy && s.strategy.ema_92050);
      await api("set_strategy", { ema_92050: !on });
      tick();
    });
  }
  if ($("btn-grow-mode")) {
    $("btn-grow-mode").addEventListener("click", async () => {
      const s = await api("snapshot");
      const on = !!(s && s.growModeEnabled);
      await api("set_entry_toggles", { grow_mode: !on });
      tick();
    });
  }
  async function resetSessionPnl() {
    await api("reset_pnl");
    tick();
  }
  if ($("btn-pnl-reset")) {
    $("btn-pnl-reset").addEventListener("click", () => { resetSessionPnl(); });
  }
  if ($("btn-pnl-reset-hero")) {
    $("btn-pnl-reset-hero").addEventListener("click", () => { resetSessionPnl(); });
  }
  $("btn-flat")?.addEventListener("click", async () => {
    await api("exit_trade");
    tick();
  });
  if ($("btn-buy")) {
    $("btn-buy").addEventListener("click", async () => {
      const r = await api("buy");
      if (r && r.ok === false) {
        const hint = $("hint-port")?.parentElement;
        if (hint) hint.textContent = `BUY blocked: ${r.error || "REJECT"}`;
      }
      tick();
    });
  }
  if ($("btn-sell")) {
    $("btn-sell").addEventListener("click", async () => {
      const r = await api("sell");
      if (r && r.ok === false) {
        const hint = $("hint-port")?.parentElement;
        if (hint) hint.textContent = `SHORT blocked: ${r.error || "REJECT"}`;
      }
      tick();
    });
  }
  $("btn-qty-down")?.addEventListener("click", async () => {
    const s = await api("snapshot");
    await api("set_contracts", Math.max(1, (s && s.contracts ? s.contracts : 1) - 1));
    tick();
  });
  $("btn-qty-up")?.addEventListener("click", async () => {
    const s = await api("snapshot");
    const cap = (s && s.maxContracts) || 10;
    await api("set_contracts", Math.min(cap, (s && s.contracts ? s.contracts : 1) + 1));
    tick();
  });
  if ($("btn-goal-down")) {
    $("btn-goal-down").addEventListener("click", async () => {
      const s = await api("snapshot");
      const g = (s && s.dailyGoal) || {};
      const cur = Number(g.goal || 0);
      await api("set_daily_goal", Math.max(0, cur - 25));
      tick();
    });
  }
  if ($("btn-goal-up")) {
    $("btn-goal-up").addEventListener("click", async () => {
      const s = await api("snapshot");
      const g = (s && s.dailyGoal) || {};
      const cur = Number(g.goal || 0);
      await api("set_daily_goal", Math.min(5000, cur + 25));
      tick();
    });
  }
  if ($("btn-clock-down")) {
    $("btn-clock-down").addEventListener("click", async () => {
      const s = await api("snapshot");
      const g = (s && s.dailyGoal) || {};
      const cur = Number(g.windowHours || 0);
      await api("set_goal_window_hours", Math.max(0, cur - 0.25));
      tick();
    });
  }
  if ($("btn-clock-up")) {
    $("btn-clock-up").addEventListener("click", async () => {
      const s = await api("snapshot");
      const g = (s && s.dailyGoal) || {};
      const cur = Number(g.windowHours || 0);
      await api("set_goal_window_hours", Math.min(12, cur + 0.25));
      tick();
    });
  }
  $("btn-stop-down")?.addEventListener("click", async () => {
    const s = await api("snapshot");
    await api("set_stop_points", Math.max(1, (s && s.stopPoints ? s.stopPoints : 20) - 1));
    tick();
  });
  $("btn-stop-up")?.addEventListener("click", async () => {
    const s = await api("snapshot");
    await api("set_stop_points", Math.min(80, (s && s.stopPoints ? s.stopPoints : 20) + 1));
    tick();
  });

  const strict = $("tune-strictness");
  if (strict) {
    strict.addEventListener("input", () => {
      if (tuningSyncing) return;
      const v = Number(strict.value);
      $("tune-strictness-val").textContent = String(Math.round(v));
      scheduleTune(async () => {
        await api("set_entry_strictness", v);
        tick();
      });
    });
  }

  document.querySelectorAll(".tune-knob").forEach((knob) => {
    const slider = knob.querySelector('input[type="range"]');
    const gate = knob.dataset.gate;
    const out = knob.querySelector("output");
    if (!slider || !gate) return;
    slider.addEventListener("input", () => {
      if (tuningSyncing) return;
      const v = Number(slider.value);
      if (out) out.textContent = formatGateValue(gate, v);
      scheduleTune(async () => {
        await api("set_entry_gate", gate, v);
        tick();
      });
    });
  });

  const tuneToggles = [
    ["toggle-trending", "require_trending"],
    ["toggle-chaotic", "chaotic_bank"],
    ["toggle-grow-mode", "grow_mode"],
    ["toggle-experimental", "experimental_profile"],
    ["toggle-candles", "candle_align"],
    ["toggle-book-patterns", "book_patterns"],
    ["toggle-exhaustion", "exhaustion_filter"],
    ["toggle-choppy-bias", "choppy_bias"],
  ];
  for (const [id, key] of tuneToggles) {
    const el = $(id);
    if (!el) continue;
    el.addEventListener("change", async () => {
      if (tuningSyncing) return;
      await api("set_entry_toggles", { [key]: el.checked });
      tick();
    });
  }

  $("btn-tune-reset")?.addEventListener("click", async () => {
    await api("reset_entry_tuning");
    tick();
  });

  document.querySelectorAll("[data-strategy]").forEach((el) => {
    el.addEventListener("change", async () => {
      const key = el.dataset.strategy;
      if (!key) return;
      const wanted = !!el.checked;
      strategySyncing = true;
      strategyHoldUntil = Date.now() + 2000;
      try {
        const out = await api("set_strategy", { [key]: wanted });
        if (out) applyStrategyDom(out);
        el.checked = wanted;
      } catch (err) {
        console.error(err);
        el.checked = !wanted;
      } finally {
        strategySyncing = false;
      }
    });
  });
  document.querySelectorAll("[data-strategy-num]").forEach((knob) => {
    const slider = knob.querySelector('input[type="range"]');
    const key = knob.dataset.strategyNum;
    const out = knob.querySelector("output");
    if (!slider || !key) return;
    slider.addEventListener("input", () => {
      if (strategySyncing) return;
      if (out) out.textContent = formatStrategyValue(key, slider.value);
      scheduleTune(async () => {
        await api("set_strategy", { [key]: Number(slider.value) });
        tick();
      });
    });
  });
  $("strategy-risk")?.addEventListener("change", async () => {
    if (strategySyncing) return;
    await api("set_strategy", { account_risk: $("strategy-risk").value });
    tick();
  });
  $("strategy-413-mode")?.addEventListener("change", async () => {
    if (strategySyncing) return;
    await api("set_strategy", { breakout_413_mode: $("strategy-413-mode").value });
    tick();
  });
}

for (const id of ["fx-canvas", "motes"]) {
  const el = $(id);
  if (!el) continue;
  el.style.pointerEvents = "none";
  el.style.display = "none";
  el.width = 1;
  el.height = 1;
}
fx.dock = null;
requestAnimationFrame(tickFx);
fitIronHud();
window.addEventListener("resize", fitIronHud);
bindTabs();
bind();
renderStates("IDLE");
const demoMode = new URLSearchParams(location.search).get("demo");
if (demoMode === "exit" && !window.pywebview) {
  runExitDemo();
} else if (demoMode === "milestones" && !window.pywebview) {
  runMilestoneDemo();
} else {
  setInterval(tick, 250);
  tick();
}
setTimeout(() => document.getElementById("stage").classList.remove("boot"), 900);

function runMilestoneDemo() {
  const base = {
    enabled: true,
    connected: true,
    state: "TRADE_PROFITABLE",
    session: "DEMO",
    price: 29000,
    atr: 20,
    trendBias: "LONG",
    trendRegime: "TRENDING",
    structure: "BULL",
    volatility: "NORMAL",
    vwap: 28980,
    velocity: 1.2,
    impulse: 40,
    long: { confidence: 72, velocity: 1.4, opportunity: 68, extension: 22 },
    short: { confidence: 18, velocity: 0.1, opportunity: 12, extension: 8 },
    stats: {},
    trades: [],
    pnlLog: { inTrade: true, net: 0, open: 0, wins: 0, losses: 0, count: 0 },
    event: { type: "EMA_CROSS", direction: "LONG", id: 1, peakConfidence: 70 },
    emaStrategyEnabled: true,
  };
  const steps = [
    { state: "PROBATION", mfe: 8, price: 29008, hold: 8 },
    { state: "PROBATION", mfe: 16, price: 29016, hold: 18 },
    { state: "CONFIRMED", mfe: 20, price: 29020, hold: 28 },
    { state: "CONFIRMED", mfe: 32, price: 29032, hold: 40 },
    { state: "RUNNER", mfe: 40, price: 29040, hold: 55 },
    { state: "RUNNER", mfe: 50, price: 29050, hold: 70 },
    { state: "RUNNER", mfe: 75, price: 29075, hold: 95 },
    { state: "RUNNER", mfe: 125, price: 29125, hold: 130 },
  ];
  let i = 0;
  const play = () => {
    const step = steps[Math.min(i, steps.length - 1)];
    const pnl = (step.price - 29000) * 2;
    paint({
      ...base,
      price: step.price,
      sessionPnl: pnl,
      trade: {
        side: "LONG",
        entry: 29000,
        stop: 28970,
        target: 29400,
        mfe: step.mfe,
        mae: 4,
        runner: step.state === "RUNNER",
        qty: 1,
        points: step.price - 29000,
        pnl,
        holdSec: step.hold,
        state: step.state,
        tag: "EMA_SNIPER_LONG",
        atrAtEntry: 20,
        peakPnl: step.mfe * 2,
        locks: {
          giveback: 0.30,
          compress: 0.35,
          floorPts: step.mfe > 0 ? Math.round(step.mfe * 0.7 * 10) / 10 : 0,
          floorPx: step.mfe > 0 ? 29000 + step.mfe * 0.7 : 0,
          spread: step.state === "RUNNER" ? 18 : 8,
          spreadNow: 12,
          entrySpread: 6,
          spreadExpanded: step.state === "RUNNER",
          warn9: false,
          lost20: false,
          confirmedAtr: 1,
          runnerAtr: 2,
          oneR: 20,
          rMultiple: (step.price - 29000) / 20,
          openPts: step.price - 29000,
          giveUsed: 0,
          compressUsed: 0,
          threat: step.mfe > 0 ? "70% MFE FLOOR" : step.state === "CONFIRMED" ? "PROTECT / STRUCTURE" : "HARD STOP ONLY",
        },
      },
    });
    i += 1;
    if (i < steps.length) setTimeout(play, 2800);
  };
  play();
}

function runExitDemo() {
  const base = {
    enabled: true,
    connected: true,
    state: "TRADE_PROFITABLE",
    session: "DEMO",
    price: 29000,
    atr: 20,
    trendBias: "LONG",
    trendRegime: "TRENDING",
    structure: "BULL",
    volatility: "NORMAL",
    vwap: 28980,
    velocity: 1.2,
    impulse: 40,
    long: { confidence: 72, velocity: 1.4, opportunity: 68, extension: 22 },
    short: { confidence: 18, velocity: 0.1, opportunity: 12, extension: 8 },
    stats: {},
    trades: [],
    pnlLog: { inTrade: true, net: 0, open: 0, wins: 0, losses: 0, count: 0 },
    event: { type: "EMA_CROSS", direction: "LONG", id: 1, peakConfidence: 70 },
    emaStrategyEnabled: true,
  };
  const hold = (price, state, extra = {}) => {
    const mfe = extra.mfe ?? price - 29000;
    const open = extra.open ?? price - 29000;
    const floor = mfe > 0 ? mfe * 0.7 : 0;
    return {
      price,
      sessionPnl: open * 2,
      trade: {
        side: "LONG",
        entry: 29000,
        stop: state === "PROBATION" ? 28970 : 28995,
        mfe,
        mae: 4,
        runner: state === "RUNNER",
        qty: 1,
        points: open,
        pnl: open * 2,
        holdSec: extra.hold || 40,
        state,
        tag: "EMA_SNIPER_LONG",
        atrAtEntry: 20,
        peakPnl: mfe * 2,
        locks: {
          giveback: 0.30,
          compress: 0.35,
          floorPts: floor,
          floorPx: floor ? 29000 + floor : 0,
          spread: extra.spread ?? 22,
          spreadNow: extra.spreadNow ?? 18,
          entrySpread: 8,
          spreadExpanded: extra.expanded ?? state !== "PROBATION",
          warn9: !!extra.warn9,
          lost20: !!extra.lost20,
          confirmedAtr: 1,
          runnerAtr: 2,
          oneR: 30,
          rMultiple: open / 30,
          openPts: open,
          giveUsed: extra.giveUsed ?? 0,
          compressUsed: extra.compressUsed ?? 0,
          threat: extra.threat || (floor > 0 ? "70% MFE FLOOR" : state === "CONFIRMED" ? "PROTECT / STRUCTURE" : "HARD STOP ONLY"),
        },
      },
    };
  };
  const flat = (reason, pnl, clock) => ({
    price: 29060,
    sessionPnl: pnl,
    state: "IDLE",
    trade: null,
    lastExit: { side: "LONG", pnl, pts: pnl / 2, reason, clock },
    pnlLog: { inTrade: false, net: pnl, open: 0, wins: pnl > 0 ? 1 : 0, losses: 0, count: 1 },
  });
  const frames = [
    hold(29012, "PROBATION", { hold: 8, expanded: false, spread: 8, spreadNow: 8, threat: "HARD STOP ONLY" }),
    hold(29032, "CONFIRMED", { hold: 22, threat: "PROTECT / STRUCTURE" }),
    hold(29070, "RUNNER", { hold: 40, mfe: 70, threat: "70% MFE FLOOR" }),
    hold(29085, "RUNNER", { hold: 55, mfe: 90, warn9: true, threat: "70% MFE FLOOR" }),
    hold(29078, "RUNNER", { hold: 70, mfe: 90, open: 78, warn9: true, lost20: true, giveUsed: 0.44, threat: "STRUCTURE CONFIRM" }),
    flat("STRUCTURE_FAILURE", 156, "09:12:01"),
    hold(29120, "RUNNER", { hold: 20, mfe: 120, open: 88, giveUsed: 0.89, threat: "MFE GIVEBACK" }),
    flat("MFE_GIVEBACK", 176, "09:14:22"),
    hold(29110, "RUNNER", { hold: 18, mfe: 110, compressUsed: 1.05, expanded: true, spread: 40, spreadNow: 24, threat: "COMPRESSION" }),
    flat("COMPRESSION", 168, "09:16:40"),
  ];
  let i = 0;
  const play = () => {
    paint({ ...base, ...frames[i] });
    i += 1;
    if (i < frames.length) setTimeout(play, i % 2 === 0 ? 3400 : 2200);
  };
  play();
}

