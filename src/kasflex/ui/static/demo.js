"use strict";

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const SHOWCASE_DATE = "2023-01-15";
const SHOWCASE_SEED = 0;
const PRIORITY_NAMES = {
  balanced:["Balanced","In balans"], cost:["Lowest cost","Laagste kosten"],
  crop:["Crop first","Gewas eerst"], grid:["Grid relief","Net ontlasten"],
};
// Chart colours follow the entity, the same in every chart on the page, from a
// validated categorical palette (see demo.css: --s-*). Price is not an entity
// with an identity; it is drawn in neutral ink with the dearest hours emphasised.
const SERIES = {
  buffer:"var(--s-buffer)", chp:"var(--s-chp)", boiler:"var(--s-boiler)", lamps:"var(--s-lamps)",
  battery:"var(--s-battery)", grid:"var(--s-grid)", heat_pump:"var(--s-heatpump)",
};

const state = {
  lang: readStore("kasflex.demo.lang") || "en",
  inputMode: readStore("kasflex.demo.inputMode") || "",
  strings: {},
  workshop: null,
  version: "collab",
  scenarioId: "",
  context: null,
  recommendation: null,
  run: null,
  goals: [],
  sessionId: crypto.randomUUID(),
  participantId: readStore("kasflex.demo.participant") || "",
  studyConsented: false,
  planShownAt: 0,
  detailExpansions: 0,
  whyClicks: 0,
  editsMade: 0,
  dimensions: {},
  openReason: "",
  chooseOwn: false,
  reuse: new Set(),
  providers: [],
  adminToken: readSession("kasflex.admin.token") || "",
  approved: false,
};

function readSession(key) { try { return sessionStorage.getItem(key); } catch { return null; } }
function writeSession(key, value) {
  try { value ? sessionStorage.setItem(key, value) : sessionStorage.removeItem(key); } catch {}
}
function readStore(key) { try { return localStorage.getItem(key); } catch { return null; } }
function writeStore(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch {}
}

async function api(path, body) {
  const headers = body === undefined ? {} : {"Content-Type": "application/json"};
  if (state.adminToken) headers["X-KasFlex-Admin"] = state.adminToken;
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch {}
  if (response.status === 401 && state.adminToken) {
    state.adminToken = "";
    writeSession("kasflex.admin.token", "");
  }
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

/** Smooth scrolling, unless the person asked their system for less motion. */
function motion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

function tr(key, fallback="") { return state.strings[key] || fallback || key; }
function T(en, nl) { return state.lang === "nl" ? nl : en; }
function el(tag, className="", text="") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}
function svg(tag, attrs={}, parent=null) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.append(node);
  return node;
}
function svgText(parent, x, y, text, attrs={}) {
  const node = svg("text", {x, y, ...attrs}, parent);
  node.textContent = text;
  return node;
}

async function loadLanguage(language) {
  state.lang = language === "nl" ? "nl" : "en";
  writeStore("kasflex.demo.lang", state.lang);
  const response = await fetch(`/demo.${state.lang}.json`);
  state.strings = await response.json();
  document.documentElement.lang = state.lang;
  $("language-select").value = state.lang;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const value = state.strings[node.dataset.i18n];
    if (value) node.textContent = value;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    const value = state.strings[node.dataset.i18nPlaceholder];
    if (value) node.placeholder = value;
  });
  applyVersion();
  if (state.context) renderContext(state.context);
  if (state.recommendation) renderRecommendation(state.recommendation);
  renderGoalList();
  if (state.run) renderDecision(state.run, {preserveDimensions:true});
  if (!$("position-view").hidden) renderPositionPage();
}

function euro(value, digits=0) {
  return Number(value || 0).toLocaleString(state.lang === "nl" ? "nl-NL" : "en-NL", {
    style:"currency", currency:"EUR", minimumFractionDigits:digits, maximumFractionDigits:digits,
  });
}
function cents(value) { return `${(Number(value || 0) * 100).toFixed(1)} ct/kWh`; }
function mw(kw) { return `${(Number(kw || 0) / 1000).toFixed(1)} MW`; }
function hh(hour) { return String(hour).padStart(2, "0") + ":00"; }
function hourList(values) { return (values || []).map(hh).join(", "); }
function hourRuns(hours) {
  const sorted = [...hours].map(Number).sort((a, b) => a - b);
  const runs = [];
  for (const hour of sorted) {
    const last = runs.at(-1);
    if (last && hour === last[1] + 1) last[1] = hour; else runs.push([hour, hour]);
  }
  return runs.map(([a, b]) => `${hh(a)}–${hh((b + 1) % 24)}`).join(", ");
}
function showError(error, action="") {
  const box = $("error");
  const reason = String(error?.message || error || "Unknown error");
  const prefix = state.lang === "nl"
    ? (action ? `${action} mislukt: ` : "Mislukt: ")
    : (action ? `${action} failed: ` : "Failed: ");
  box.textContent = prefix + reason;
  box.hidden = false;
}
function clearError() { $("error").hidden = true; }
function toast(text) {
  const node = $("toast");
  node.textContent = text;
  node.hidden = false;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.hidden = true, 3200);
}
function secondsSince(timestamp) { return Math.max(0, (performance.now() - timestamp) / 1000); }

// -- study version -----------------------------------------------------------
// manual: the grower sets everything; KasFlex calculates and checks, but does not
//         suggest, argue or explain.
// ai:     KasFlex suggests first; the grower agrees or disagrees with a reason.
// collab: as ai, plus a chat panel and the "why this plan" graph.

function isAdvised() { return state.version !== "manual"; }
function dimensionsFor(run=state.run) {
  if (!isAdvised()) return [];
  const list = ["money", "crop", "work"];
  if ((run?.goals || []).length || (run?.targets || []).length) list.push("goal");
  return list;
}

function applyVersion() {
  const advised = isAdvised();
  $("recommend-panel").hidden = !advised || (!state.recommendation && !state.recommending);
  $("choices-panel").hidden = advised && Boolean(state.recommendation) && !state.chooseOwn;
  $("open-factors").hidden = !advised;
  $("dimension-panel").hidden = !advised;
  $("chat-toggle").hidden = state.version !== "collab" || !state.run;
  if (state.version !== "collab") $("chat-panel").hidden = true;
}

async function loadWorkshop() {
  try {
    state.workshop = await api(`/api/workshop?lang=${state.lang}`);
  } catch {
    state.workshop = {version:"collab", scenarios:[], scenario_id:"", lock_scenario:false};
  }
  const ws = state.workshop;
  state.version = ws.version || "collab";
  const select = $("scenario-select");
  select.replaceChildren();
  for (const scenario of ws.scenarios || []) {
    const option = el("option", "", scenario.title_text || scenario.id);
    option.value = scenario.id;
    select.append(option);
  }
  const stored = readStore("kasflex.demo.scenario");
  const known = (id) => (ws.scenarios || []).some((s) => s.id === id);
  state.scenarioId = ws.lock_scenario ? ws.scenario_id
    : (known(stored) ? stored : (ws.scenario_id || ws.scenarios?.[0]?.id || ""));
  select.value = state.scenarioId;
  if (ws.lock_scenario || !state.inputMode) state.inputMode = state.scenarioId ? "scenario" : "showcase";
  if (state.inputMode === "scenario" && !state.scenarioId) state.inputMode = "showcase";
  $("input-mode").value = state.inputMode;
  // A locked workshop shows only the chosen scenario: no switching mid-session.
  $("input-mode").closest("label").hidden = Boolean(ws.lock_scenario);
  $("scenario-picker").hidden = Boolean(ws.lock_scenario);
  applyVersion();
}

// -- what the planner is told ----------------------------------------------------

function targets() {
  const number = (id) => {
    const raw = $(id).value.trim();
    return raw === "" ? null : Number(raw);
  };
  const importMw = number("target-import");
  return {
    max_import_kw: importMw === null ? null : importMw * 1000,
    light_mol_m2: number("target-light"),
    budget_eur: number("target-budget"),
    heat_day_c: number("target-heat-day"),
    heat_night_c: number("target-heat-night"),
  };
}

function selectedPolicy() {
  const policy = {
    priority: document.querySelector('input[name="priority"]:checked')?.value || "balanced",
    avoid_chp_night: $("avoid-chp-night").checked,
    prefer_stored_heat: $("prefer-buffer").checked,
    battery_reserve_pct: Number($("battery-reserve").value),
    brief: $("brief").value.trim(),
    targets: targets(),
    goals: state.goals,
  };
  const advice = state.recommendation?.policy;
  if (advice?.avoid_chp_hours?.length) policy.avoid_chp_hours = advice.avoid_chp_hours;
  if (state.reuse.size) policy.reuse_memory = [...state.reuse];
  return policy;
}

function overrides() {
  const scenario = state.inputMode === "scenario";
  const showcase = state.inputMode !== "real";
  const out = {
    data_source:showcase ? "synthetic" : "demo",
    planner:"collaborative",
    date:showcase ? SHOWCASE_DATE : (state.context?.date || undefined),
    seed:showcase ? SHOWCASE_SEED : undefined,
    language:state.lang,
    condition:state.version,
    participant_id:state.participantId || undefined,
    "checker.enabled":$("checker-enabled").checked,
  };
  if (scenario) {
    out.data_source = "scenario";
    out.scenario_id = state.scenarioId;
    delete out.date;
    delete out.seed;
  }
  return out;
}
function runRef(run=state.run) {
  return {run_id:run.run_id, revision:run.revision, plan_hash:run.plan_hash};
}

async function loadValidationStatus() {
  const pill = $("validation-pill");
  try {
    const status = await api("/api/validation-status");
    if (status.validated) {
      pill.className = "pill measured";
      pill.textContent = T(`Measured replay · not validated for operation (${status.days_compared} d)`,
                           `Meetreplay · niet gevalideerd voor de praktijk (${status.days_compared} d)`);
      pill.title = `${status.dataset} · ${status.model || "model"}`;
    } else {
      pill.className = "pill pending";
      pill.textContent = tr("validation.pending", "Model validation pending");
      pill.title = `${status.dataset} · DOI ${status.doi}`;
    }
  } catch (error) {
    pill.className = "pill pending";
    pill.textContent = tr("validation.pending", "Model validation pending");
    pill.title = String(error?.message || error);
  }
}

async function handleConsent() {
  let status;
  try { status = await api("/api/consent"); }
  catch { return; }
  if (!status.study_active) return;
  $("participant-id").value = state.participantId;
  $("consent-dialog").showModal();
}

// -- step 1: the day ------------------------------------------------------------

async function loadContext({ refresh = false } = {}) {
  clearError();
  const pill = $("data-pill");
  pill.className = "pill loading";
  pill.textContent = T("Loading…", "Laden…");
  $("refresh-data").disabled = true;
  $("build-plan").disabled = true;
  $("compare-checker").disabled = true;
  state.recommendation = null;
  state.chooseOwn = false;
  applyVersion();
  try {
    if (state.inputMode === "real") {
      const prepared = await api("/api/demo-prepare", {overrides:{data_source:"demo"}, refresh});
      state.context = await api("/api/day-context", {
        overrides:{...overrides(), date:prepared.date, data_source:"demo"}
      });
      pill.textContent = prepared.reused_cache ? T("Real data · cached", "Echte data · lokaal opgeslagen")
                                               : T("Real data · ready", "Echte data · klaar");
    } else {
      state.context = await api("/api/day-context", {overrides:overrides()});
      pill.textContent = state.inputMode === "scenario"
        ? T("Workshop scenario · offline", "Workshopscenario · offline")
        : T("Showcase data · offline", "Showcase-data · offline");
    }
    pill.className = "pill";
    renderContext(state.context);
    $("build-plan").disabled = false;
    $("compare-checker").disabled = false;
    if (isAdvised()) await loadRecommendation();
  } catch (error) {
    pill.className = "pill loading";
    pill.textContent = T("Data unavailable", "Data niet beschikbaar");
    showError(error, T("Preparing data", "Data voorbereiden"));
  } finally {
    $("refresh-data").disabled = false;
  }
}

function renderContext(ctx) {
  const locale = state.lang === "nl" ? "nl-NL" : "en-GB";
  $("planning-date").textContent = new Date(ctx.date + "T12:00:00").toLocaleDateString(locale, {
    weekday:"short", day:"numeric", month:"short", year:"numeric"
  });
  const scenario = ctx.scenario;
  $("scenario-card").hidden = !scenario;
  if (scenario) {
    $("scenario-title").textContent = scenario.title_text || scenario.id;
    $("scenario-framing").textContent = scenario.framing_text || "";
  }

  $("price-low").textContent = cents(ctx.price.min_eur_kwh);
  $("price-high").textContent = cents(ctx.price.max_eur_kwh);
  $("temp-range").textContent =
    `${ctx.weather.min_temp_c.toFixed(0)}${T(" to ", " tot ")}${ctx.weather.max_temp_c.toFixed(0)} °C`;
  const grid = ctx.grid || {};
  $("grid-limit").textContent = mw(grid.import_limit_kw);
  $("grid-window").textContent = grid.contract?.name || "";
  $("grid-window").title = grid.contract?.summary || "";
  renderContextChart(ctx);
}

/** A column with a 4px rounded data end and a square foot on the baseline. */
function columnPath(x, y, width, height, radius=4) {
  if (height <= 0) return "";
  const r = Math.min(radius, width / 2, height);
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}`
    + `Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
}

/** A collapsed table with the same numbers as a chart: the accessible twin. */
function tableView(headings, rows, label=T("Show as table", "Toon als tabel")) {
  const details = el("details", "table-view");
  details.append(el("summary", "", label));
  const table = el("table");
  const head = el("thead"), headRow = el("tr");
  headings.forEach((text) => headRow.append(el("th", "", text)));
  head.append(headRow);
  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    row.forEach((cell) => tr.append(el("td", "", cell)));
    body.append(tr);
  }
  table.append(head, body);
  details.append(table);
  return details;
}

/** Price and outside temperature as two small multiples on one hour axis (never
 *  two y-scales on one plot), with the hours the grid contract allows less shaded. */
function renderContextChart(ctx) {
  const root = $("price-chart");
  root.replaceChildren();
  const W = 640, L = 58, R = 16, step = (W - L - R) / 24;
  const prices = ctx.price.series.map((p) => p * 100);
  const temps = ctx.weather.temperature_series || [];
  const grid = ctx.grid || {};
  const limits = grid.hourly_import_kw || [];
  const panels = [
    {label:T("Power price", "Stroomprijs"), unit:"ct", values:prices, top:22, h:112,
     min:Math.min(0, ...prices), max:Math.max(...prices) * 1.12},
    {label:T("Outside", "Buiten"), unit:"°C", values:temps, top:170, h:70,
     min:Math.floor(Math.min(...temps, 0) - 1), max:Math.ceil(Math.max(...temps, 4) + 1)},
  ];
  const H = 268;
  const chart = svg("svg", {viewBox:`0 0 ${W} ${H}`, class:"svg-chart", role:"img",
                            "aria-label":T("Power price and outside temperature per hour", "Stroomprijs en buitentemperatuur per uur")}, root);
  const x = (h) => L + step * h + step / 2;
  const lowered = limits.map((kw, h) => kw < grid.import_limit_kw - 1e-6 ? h : -1).filter((h) => h >= 0);
  for (const hour of lowered) {
    svg("rect", {x:L + step * hour, y:panels[0].top, width:step, height:panels[1].top + panels[1].h - panels[0].top, class:"band-limit"}, chart);
  }
  if (lowered.length) {
    svgText(chart, L + step * lowered[0] + 2, 12, T("grid limit lowered", "netgrens lager"), {class:"tick"});
  }
  const crosshair = svg("line", {x1:0, x2:0, y1:panels[0].top, y2:panels[1].top + panels[1].h, class:"crosshair", visibility:"hidden"}, chart);
  for (const panel of panels) {
    if (!panel.values.length) continue;
    const y = (v) => panel.top + panel.h - (v - panel.min) / (panel.max - panel.min) * panel.h;
    panel.y = y;
    for (const value of [panel.min, (panel.min + panel.max) / 2, panel.max]) {
      svg("line", {x1:L, x2:W - R, y1:y(value), y2:y(value), class:"gridline"}, chart);
      svgText(chart, L - 6, y(value) + 4, value.toFixed(0), {class:"tick", "text-anchor":"end"});
    }
    svgText(chart, L, panel.top - 6, `${panel.label} (${panel.unit})`, {class:"panel-label"});
    const line = panel.values.map((v, h) => `${h ? "L" : "M"}${x(h)},${y(v)}`).join("");
    svg("path", {d:`${line}L${x(23)},${y(panel.min)}L${x(0)},${y(panel.min)}Z`, class:"area-series"}, chart);
    svg("path", {d:line, class:"line-series"}, chart);
    const peak = panel.values.indexOf(Math.max(...panel.values));
    svg("circle", {cx:x(peak), cy:y(panel.values[peak]), r:4, class:"dot-series"}, chart);
    svgText(chart, x(peak) + 8, y(panel.values[peak]) + 4,
            `${panel.values[peak].toFixed(0)} ${panel.unit}`, {class:"label"});
    panel.dot = svg("circle", {cx:0, cy:0, r:4, class:"dot-series", visibility:"hidden"}, chart);
  }
  svg("line", {x1:L, x2:W - R, y1:H - 22, y2:H - 22, class:"baseline"}, chart);
  for (const hour of [0, 6, 12, 18, 23]) svgText(chart, x(hour), H - 6, hh(hour), {class:"tick", "text-anchor":"middle"});

  const readout = $("price-hover");
  const describe = (h) => `${hh(h)} · ${prices[h].toFixed(1)} ct/kWh`
    + (temps.length ? ` · ${temps[h].toFixed(1)} °C` : "")
    + (limits.length ? ` · ${T("grid limit", "netgrens")} ${mw(limits[h])}` : "");
  readout.textContent = "";
  const pick = (event) => {
    const box = chart.getBoundingClientRect();
    const hour = Math.floor(((event.clientX - box.left) / box.width * W - L) / step);
    if (hour < 0 || hour > 23) return;
    crosshair.setAttribute("x1", x(hour)); crosshair.setAttribute("x2", x(hour));
    crosshair.setAttribute("visibility", "visible");
    for (const panel of panels) {
      if (!panel.dot) continue;
      panel.dot.setAttribute("cx", x(hour)); panel.dot.setAttribute("cy", panel.y(panel.values[hour]));
      panel.dot.setAttribute("visibility", "visible");
    }
    readout.textContent = describe(hour);
  };
  chart.addEventListener("pointermove", pick);
  chart.addEventListener("pointerdown", pick);
  root.append(tableView([T("Hour", "Uur"), T("Price", "Prijs"), T("Outside", "Buiten"), T("Grid limit", "Netgrens")],
    prices.map((p, h) => [hh(h), `${p.toFixed(1)} ct/kWh`, temps.length ? `${temps[h].toFixed(1)} °C` : "—",
                          limits.length ? mw(limits[h]) : "—"])));
}

// -- AI goes first ---------------------------------------------------------------

async function loadRecommendation() {
  // Loading has its own look, so a slow first plan never reads as an empty screen.
  const panel = $("recommend-panel");
  state.recommending = true;
  panel.classList.add("loading");
  panel.setAttribute("aria-busy", "true");
  if (!state.recommendation) {
    $("recommend-title").textContent = T("Comparing 4 plans…", "4 plannen vergelijken…");
    $("recommend-facts").replaceChildren();
    $("recommend-options").replaceChildren(el("div", "skeleton"), el("div", "skeleton"), el("div", "skeleton"));
  }
  $("accept-recommendation").disabled = true;
  applyVersion();
  try {
    state.recommendation = await api("/api/recommend", {overrides:overrides(), policy:selectedPolicy()});
    const advice = state.recommendation;
    const radio = document.querySelector(`input[name="priority"][value="${advice.priority}"]`);
    if (radio) radio.checked = true;
    if (advice.policy?.battery_reserve_pct !== undefined) {
      $("battery-reserve").value = advice.policy.battery_reserve_pct;
      $("reserve-value").textContent = `${advice.policy.battery_reserve_pct}%`;
    }
    $("avoid-chp-night").checked = Boolean(advice.policy?.avoid_chp_night);
    renderRecommendation(advice);
  } catch (error) {
    state.recommendation = null;
    showError(error, T("Making a suggestion", "Voorstel maken"));
  } finally {
    state.recommending = false;
    panel.classList.remove("loading");
    panel.removeAttribute("aria-busy");
    $("accept-recommendation").disabled = false;
  }
  applyVersion();
}

function fact(icon, value, label, cls="") {
  const chip = el("span", `fact ${cls}`.trim());
  const glyph = el("i", "", icon);
  glyph.setAttribute("aria-hidden", "true");
  chip.append(glyph, el("strong", "", value), el("span", "sr", ` (${label})`));
  chip.title = label;
  return chip;
}

function renderRecommendation(advice) {
  $("recommend-title").textContent = T(PRIORITY_NAMES[advice.priority][0], PRIORITY_NAMES[advice.priority][1]);
  $("recommend-reasons").replaceChildren(...(advice.reasons || []).map((reason) => el("li", "", reason)));

  // The reasons as numbers: one chip each, the sentence only in the tooltip.
  const facts = $("recommend-facts");
  facts.replaceChildren();
  for (const item of advice.facts || []) {
    if (item.kind === "light") facts.append(fact("☀", `${item.cheapest.toFixed(1)} / ${item.target.toFixed(0)} mol/m²`,
      T("Light in the cheapest plan against the crop's need", "Licht in het goedkoopste plan tegenover de behoefte van het gewas"), "warn"));
    else if (item.kind === "peak") facts.append(fact("⚡", `−${Math.round(item.drop_kw)} kW`,
      T(`Lower grid peak for ${euro(item.extra_eur)} more`, `Lagere netpiek voor ${euro(item.extra_eur)} extra`)));
    else if (item.kind === "swing") facts.append(fact("€", `${(item.low_eur_kwh * 100).toFixed(0)}→${(item.high_eur_kwh * 100).toFixed(0)} ct`,
      T("Cheapest and dearest hour", "Goedkoopste en duurste uur")));
    else if (item.kind === "saving") facts.append(fact(item.eur >= 0 ? "▼" : "▲", euro(Math.abs(item.eur)),
      T("Against normal control", "Tegenover de normale regeling"), item.eur >= 0 ? "good" : "warn"));
    else if (item.kind === "frost") facts.append(fact("❄", `${item.temp_c.toFixed(0)} °C → 🔋 ${item.reserve_pct.toFixed(0)}%`,
      T("Frost tonight: more reserve in battery and buffer", "Vorst vannacht: meer reserve in batterij en buffer")));
  }

  // Every option side by side: cost and light, the suggestion emphasised.
  const root = $("recommend-options");
  root.replaceChildren();
  const rows = [...(advice.options || []), {...advice.normal, priority:"normal"}];
  const target = (advice.facts || []).find((f) => f.kind === "light")?.target;
  const costMax = Math.max(...rows.map((o) => o.cost_eur), 1);
  const lightMax = Math.max(...rows.map((o) => o.light_mol_m2 || 0), target || 0, 1);
  const W = 520, L = 112, colW = 150, gap = 40, rowH = 26, top = 22;
  const H = top + rows.length * rowH + 4;
  const chart = svg("svg", {viewBox:`0 0 ${W} ${H}`, class:"svg-chart", role:"img",
                            "aria-label":T("Cost and light per option", "Kosten en licht per optie")}, root);
  const costX = L, lightX = L + colW + gap + 50;
  svgText(chart, costX, 12, "€", {class:"panel-label"});
  svgText(chart, lightX, 12, "☀ mol/m²", {class:"panel-label"});
  rows.forEach((option, i) => {
    const y = top + i * rowH;
    const chosen = option.priority === advice.priority;
    const name = option.priority === "normal" ? T("Normal", "Normaal")
      : T(PRIORITY_NAMES[option.priority][0], PRIORITY_NAMES[option.priority][1]);
    svgText(chart, L - 10, y + 13, name, {class:chosen ? "label" : "tick", "text-anchor":"end"});
    const cw = option.cost_eur / costMax * colW;
    svg("rect", {x:costX, y:y + 3, width:Math.max(2, cw), height:14, rx:3, class:chosen ? "col-plan" : "col-normal"}, chart);
    svgText(chart, costX + cw + 6, y + 14, euro(option.cost_eur), {class:chosen ? "label" : "tick"});
    const lw = (option.light_mol_m2 || 0) / lightMax * (colW - 40);
    svg("rect", {x:lightX, y:y + 3, width:Math.max(2, lw), height:14, rx:3, class:chosen ? "col-plan" : "col-normal"}, chart);
    svgText(chart, lightX + lw + 6, y + 14, (option.light_mol_m2 || 0).toFixed(1), {class:chosen ? "label" : "tick"});
  });
  if (target) {
    const tx = lightX + target / lightMax * (colW - 40);
    svg("line", {x1:tx, x2:tx, y1:top - 4, y2:H - 2, class:"line-target"}, chart);
    svgText(chart, tx, top - 7, T("need", "nodig"), {class:"tick", "text-anchor":"middle"});
  }

  // What the grower said before: standing rules are already in the plan (🧠);
  // one-off reasons can be applied again with one click, similar days first.
  const memory = $("recommend-memory");
  const items = advice.remembered || [];
  memory.hidden = !items.length;
  memory.replaceChildren();
  const why = {weekday:T("same weekday", "zelfde weekdag"), cold:T("cold night again", "weer een koude nacht"),
               grid:T("grid limit lowered again", "netgrens weer lager")};
  for (const item of items.slice(0, 6)) {
    if (item.applied && !state.reuse.has(item.pref_id)) {
      memory.append(fact("🧠", `“${item.said}”`, T("Taken from what you said before", "Meegenomen uit wat u eerder zei")));
      continue;
    }
    const on = state.reuse.has(item.pref_id);
    const chip = el("button", `fact reuse${on ? " on" : ""}${item.similar ? " similar" : ""}`);
    chip.type = "button";
    chip.setAttribute("aria-pressed", String(on));
    const label = item.similar ? `${T("Apply again", "Opnieuw toepassen")} (${why[item.similar]})`
                               : T("Apply again", "Opnieuw toepassen");
    chip.title = `${label}: ${item.summary}`;
    const glyph = el("i", "", on ? "✓" : "↻");
    glyph.setAttribute("aria-hidden", "true");
    chip.append(glyph, el("strong", "", `“${item.said}”`), el("span", "sr", ` (${label})`));
    if (item.similar) chip.append(el("small", "", why[item.similar]));
    chip.addEventListener("click", async () => {
      if (on) state.reuse.delete(item.pref_id); else state.reuse.add(item.pref_id);
      await loadRecommendation();
    });
    memory.append(chip);
  }
}

function chooseOwn() {
  state.chooseOwn = true;
  applyVersion();
  $("choices-panel").scrollIntoView({behavior:motion(), block:"start"});
}

// -- goals -----------------------------------------------------------------------

const GOAL_LABELS = {
  switches:["switches", "wisselingen"], chp_hours:["CHP hours", "WKK-uren"],
  cost_eur:["cost €", "kosten €"], peak_import_kw:["grid peak kW", "netpiek kW"],
  light_mol_m2:["light mol/m²", "licht mol/m²"],
};
function addGoal() {
  const name = $("goal-name").value.trim();
  const value = $("goal-value").value.trim();
  if (!name || value === "") {
    toast(T("Give the goal a name and a number.", "Geef het doel een naam en een getal."));
    return;
  }
  if (state.goals.length >= 5) {
    toast(T("Five goals at most.", "Maximaal vijf doelen."));
    return;
  }
  state.goals.push({name, metric:$("goal-metric").value, op:$("goal-op").value, value:Number(value)});
  $("goal-name").value = "";
  $("goal-value").value = "";
  renderGoalList();
}
function renderGoalList() {
  const root = $("goal-list");
  root.replaceChildren();
  state.goals.forEach((goal, index) => {
    const chip = el("span", "goal-chip", `${goal.name}: ${T(...GOAL_LABELS[goal.metric])} ${goal.op} ${goal.value}`);
    const remove = el("button", "chip-x", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", T("Remove goal", "Doel verwijderen"));
    remove.addEventListener("click", () => { state.goals.splice(index, 1); renderGoalList(); });
    chip.append(remove);
    root.append(chip);
  });
  const set = Object.values(targets()).filter((v) => v !== null).length + state.goals.length;
  $("goals-count").textContent = set ? T(` · ${set} set`, ` · ${set} ingesteld`) : "";
}

// -- the safety demonstration ------------------------------------------------------

async function compareChecker() {
  if (!state.context) return;
  const button = $("compare-checker"), old = button.textContent;
  button.disabled = true;
  button.textContent = T("Comparing…", "Vergelijken…");
  clearError();
  try {
    const result = await api("/api/checker-comparison", {
      overrides:{...overrides(), planner:"naive"}, policy:selectedPolicy(),
    });
    const root = $("checker-comparison");
    root.replaceChildren();
    for (const row of result.rows || []) {
      const card = el("article", row.checker_enabled ? "on" : "off");
      card.append(
        el("strong", "", row.checker_enabled ? T("Baseline + check", "Baseline + check")
                                             : T("Baseline without check", "Baseline zonder check")),
        el("span", "", `${row.hard_violations} ${T("hard breaches", "harde overschrijdingen")} · ${euro(row.cost_eur)}`),
      );
      root.append(card);
    }
    root.hidden = false;
  } catch (error) {
    showError(error, T("Comparing checker", "Checker vergelijken"));
  } finally {
    button.disabled = false; button.textContent = old;
  }
}

// -- step 2: the plan --------------------------------------------------------------

async function buildPlan() {
  if (!state.context) {
    showError(new Error(T("Day data is not ready yet.", "De dagdata is nog niet klaar.")));
    return;
  }
  const buttons = [$("build-plan"), $("accept-recommendation")];
  const labels = buttons.map((b) => b.textContent);
  buttons.forEach((b) => { b.disabled = true; b.textContent = T("Planning…", "Plannen…"); });
  clearError();
  try {
    state.run = await api("/api/run", {overrides:overrides(), policy:selectedPolicy()});
    state.planShownAt = performance.now();
    state.dimensions = {};
    state.openReason = "";
    state.approved = false;
    $("prepare-view").hidden = true;
    $("decision-view").hidden = false;
    $("debrief").hidden = true;
    renderDecision(state.run);
    applyVersion();
    window.scrollTo({top:0, behavior:motion()});
  } catch (error) {
    showError(error, T("Building plan", "Plan maken"));
  } finally {
    buttons.forEach((b, i) => { b.disabled = false; b.textContent = labels[i]; });
  }
}

function renderDecision(run, {preserveDimensions=false}={}) {
  const saving = Number(run.normal_settings?.saving_eur || 0);
  $("result-cost").textContent = euro(run.metrics?.net_cost_eur);
  $("result-saving").textContent = run.normal_settings
    ? `${saving >= 0 ? "▼" : "▲"} ${euro(Math.abs(saving))} ${T("vs normal", "t.o.v. normaal")}` : "—";
  $("result-crop").textContent = `${Number(run.metrics?.fruit_growth_kg_m2 || 0).toFixed(2)} kg/m²`;
  $("result-crop-note").textContent = `☀ ${Number(run.metrics?.supplemental_dli_mol_m2 || 0).toFixed(1)} mol/m²`;
  const grid = run.grid || {};
  $("result-peak").textContent = mw(grid.peak_import_kw);
  $("result-peak-note").textContent = `/ ${mw(grid.import_limit_kw)}`;
  const share = Math.min(1, (grid.peak_import_kw || 0) / Math.max(1, grid.import_limit_kw || 1));
  $("result-peak-meter").firstElementChild.style.width = `${share * 100}%`;
  const ratio = (grid.peak_import_kw || 0) / Math.max(1, grid.import_limit_kw || 1);
  $("result-peak-meter").className = "meter" + (ratio > 1.0001 ? " over" : ratio > 0.9 ? " near" : "");
  const work = run.work || {};
  $("result-work").textContent = `⇄ ${work.switches}`;
  $("result-work-note").textContent = `${T("CHP", "WKK")} ${work.chp_hours} ${T("h", "u")} · ☾ ${work.chp_night_hours}`;

  const badge = $("checker-badge");
  if (!run.checker_enabled) {
    const hard = Number(run.realised_hard || 0);
    badge.className = "checker off";
    badge.textContent = T(`Check OFF · ${hard} hard breach${hard === 1 ? "" : "es"}`,
                          `Check UIT · ${hard} harde overschrijding${hard === 1 ? "" : "en"}`);
  } else if (run.accepted) {
    badge.className = "checker good";
    badge.textContent = T("✓ Checked", "✓ Gecontroleerd");
  } else {
    badge.className = "checker bad";
    badge.textContent = T("Not safe to approve", "Niet veilig om goed te keuren");
  }
  // When the check refuses the plan, say why in the grower's words, or approval
  // just looks broken.
  const problems = $("check-problems");
  const refused = run.checker_enabled && !run.accepted;
  problems.hidden = !refused;
  problems.replaceChildren();
  if (refused) {
    problems.append(el("strong", "", T("The check does not approve this plan:", "De check keurt dit plan niet goed:")));
    const list = el("ul");
    for (const violation of (run.violations || []).slice(0, 4)) list.append(el("li", "", violation.plain || violation.message));
    problems.append(list);
  }
  // The grid contract is a hard rule, not something to agree or disagree with.
  const gridBadge = $("grid-badge");
  gridBadge.className = "checker " + (grid.within_contract ? "good" : "bad");
  gridBadge.textContent = grid.within_contract
    ? T("✓ Within grid contract", "✓ Binnen netcontract") : T("Over the grid limit", "Over de netgrens");

  renderPlanChart($("plan-chart"), run);
  renderDonut(run);
  renderGoalResults(run);
  renderMemory(run);
  if (!preserveDimensions) state.dimensions = {};
  renderDimensions();
  updateApproval();
}

function heatName(source) {
  return {boiler:T("boiler", "ketel"), chp:T("CHP", "WKK"), buffer:T("buffer", "buffer"),
          heat_pump:T("heat pump", "warmtepomp")}[source] || source;
}

function planRows(run) {
  return (run.plan || []).map((row) => [
    hh(row.hour), cents(row.power_price_eur_kwh), mw(row.grid_import_kw), mw(row.import_limit_kw),
    heatName(row.heat_source), `${Math.round((row.lighting_level || 0) * 100)}%`,
    row.battery === "idle" ? "—" : `${row.battery === "charge" ? "+" : "−"}${Math.round(row.battery_power_kw)} kW`,
    row.chp_running ? T("on", "aan") : "—",
  ]);
}
function planHeadings() {
  return [T("Hour", "Uur"), T("Price", "Prijs"), T("Grid", "Net"), T("Limit", "Grens"), T("Heat from", "Warmte uit"),
          T("Lamps", "Lampen"), T("Battery", "Batterij"), T("CHP", "WKK")];
}

/** The 24-hour plan as lanes on one hour axis, read across: price, grid import
 *  against the hourly limit, storage, heat source, lamps and CHP. Each entity keeps
 *  its colour in every lane and chart; one shared legend sits under the chart. */
function renderPlanChart(root, run, {tall=false}={}) {
  root.replaceChildren();
  const plan = run.plan || [];
  if (!plan.length) return;
  const W = 960, L = 118, R = 70, step = (W - L - R) / 24, barW = Math.min(24, step - 4);
  const lanes = [
    {key:"price", label:T("Power price", "Stroomprijs"), h:tall ? 100 : 72},
    {key:"grid", label:T("Grid import", "Netafname"), h:tall ? 96 : 66},
    {key:"store", label:T("Storage", "Opslag"), h:tall ? 80 : 56},
    {key:"heat", label:T("Heat from", "Warmte uit"), h:22},
    {key:"lamps", label:T("Lamps", "Lampen"), h:28},
    {key:"chp", label:T("CHP", "WKK"), h:22},
  ];
  const gap = 14, axis = 24;
  let cursor = 10;
  for (const lane of lanes) { lane.y = cursor; cursor += lane.h + gap; }
  const H = cursor + axis;
  const chart = svg("svg", {viewBox:`0 0 ${W} ${H}`, class:"svg-chart plan-svg", role:"img",
                            "aria-label":T("Plan for each hour", "Plan per uur")}, root);
  const x = (h) => L + step * h;
  const cx = (h) => x(h) + (step - barW) / 2;
  const highlight = svg("rect", {x:0, y:0, width:step, height:cursor - gap, class:"hover-col", visibility:"hidden"}, chart);
  for (const lane of lanes) {
    svgText(chart, L - 12, lane.y + lane.h / 2 + 5, lane.label, {class:"lane-label", "text-anchor":"end"});
  }

  // Price: neutral columns, the dearest third emphasised (no hue: price is not an entity).
  const price = lanes[0], prices = plan.map((r) => r.power_price_eur_kwh);
  const pMax = Math.max(...prices, 0.01), pMin = Math.min(...prices);
  svg("line", {x1:L, x2:x(24), y1:price.y + price.h, y2:price.y + price.h, class:"baseline"}, chart);
  plan.forEach((row, h) => {
    const height = Math.max(2, row.power_price_eur_kwh / pMax * price.h);
    svg("path", {d:columnPath(cx(h), price.y + price.h - height, barW, height),
                 class:row.power_price_eur_kwh > pMin + (pMax - pMin) * .66 ? "col-dear" : "col-price"}, chart);
  });
  svgText(chart, x(24) + 8, price.y + 10, `${(pMax * 100).toFixed(0)} ct`, {class:"tick"});

  // Grid import against the hourly limit (a threshold step line).
  const gl = lanes[1];
  const gMax = Math.max(...plan.map((r) => Math.max(r.grid_import_kw || 0, r.import_limit_kw || 0)), 1);
  const gy = (kw) => gl.y + gl.h - kw / gMax * gl.h;
  svg("line", {x1:L, x2:x(24), y1:gl.y + gl.h, y2:gl.y + gl.h, class:"baseline"}, chart);
  plan.forEach((row, h) => {
    const over = (row.grid_import_kw || 0) > (row.import_limit_kw || Infinity) + 1e-6;
    const height = (row.grid_import_kw || 0) / gMax * gl.h;
    if (height > 0.5) svg("path", {d:columnPath(cx(h), gl.y + gl.h - height, barW, height), class:over ? "col-over" : "col-grid"}, chart);
  });
  svg("path", {d:plan.map((row, h) => `${h ? "L" : "M"}${x(h)},${gy(row.import_limit_kw)}H${x(h + 1)}`).join(""),
               class:"line-limit"}, chart);
  svgText(chart, x(24) + 8, gy(plan[23].import_limit_kw) + 4, T("limit", "grens"), {class:"tick"});

  // Storage: battery and buffer as a share of capacity, direct-labelled at the end.
  const st = lanes[2], cap = run.storage || {};
  const sy = (share) => st.y + st.h - share * st.h;
  svg("line", {x1:L, x2:x(24), y1:st.y + st.h, y2:st.y + st.h, class:"baseline"}, chart);
  const stores = [
    ["buffer_level_kwh", cap.buffer_kwh, SERIES.buffer, T("buffer", "buffer")],
    ["battery_soc_kwh", cap.battery_kwh, SERIES.battery, T("battery", "batterij")],
  ].map(([field, capacity, colour, name]) => {
    const share = (row) => Math.min(1, (row[field] || 0) / Math.max(1, capacity || 1));
    svg("path", {d:plan.map((row, h) => `${h ? "L" : "M"}${x(h) + step / 2},${sy(share(row))}`).join(""),
                 class:"line-store", stroke:colour}, chart);
    const end = sy(share(plan[23]));
    svg("circle", {cx:x(23) + step / 2, cy:end, r:4, fill:colour, class:"end-dot"}, chart);
    return {end, name};
  });
  // End labels only where they stand apart; converging lines lean on the legend.
  if (Math.abs(stores[0].end - stores[1].end) >= 14) {
    for (const store of stores) svgText(chart, x(24) + 8, store.end + 4, store.name, {class:"tick"});
  }

  // Heat source, lamps and CHP: cells with a 2px surface gap.
  const heat = lanes[3], lamps = lanes[4], chp = lanes[5];
  svg("line", {x1:L, x2:x(24), y1:lamps.y + lamps.h, y2:lamps.y + lamps.h, class:"baseline"}, chart);
  plan.forEach((row, h) => {
    svg("rect", {x:x(h) + 1, y:heat.y, width:step - 2, height:heat.h, rx:3,
                 fill:SERIES[row.heat_source] || "var(--ink-muted)"}, chart);
    const lit = Math.max(0, Math.min(1, row.lighting_level || 0));
    if (lit > 0) svg("path", {d:columnPath(cx(h), lamps.y + lamps.h * (1 - lit), barW, lamps.h * lit), fill:SERIES.lamps}, chart);
    if (row.chp_running) svg("rect", {x:x(h) + 1, y:chp.y + 3, width:step - 2, height:chp.h - 6, rx:3, fill:SERIES.chp}, chart);
  });
  for (const hour of [0, 3, 6, 9, 12, 15, 18, 21]) {
    svgText(chart, x(hour) + step / 2, H - 6, hh(hour), {class:"tick", "text-anchor":"middle"});
  }

  // One legend for every entity the chart shows.
  const legend = el("div", "legend");
  const used = new Set(plan.map((r) => r.heat_source));
  const keys = [...["buffer", "chp", "boiler", "heat_pump"].filter((k) => used.has(k)).map((k) => [SERIES[k], heatName(k)]),
                [SERIES.lamps, T("lamps", "lampen")], [SERIES.battery, T("battery", "batterij")],
                [SERIES.grid, T("grid import", "netafname")]];
  for (const [colour, name] of keys) {
    const key = el("span", "key");
    key.style.background = colour;
    legend.append(key, el("span", "", name));
  }
  legend.append(el("span", "key limit-key"), el("span", "", T("grid limit", "netgrens")));
  root.append(legend);

  const readout = root.parentElement?.querySelector(".hover-readout") || $("plan-hover");
  const describe = (row) => {
    const battery = row.battery === "idle" ? T("battery idle", "batterij rust")
      : row.battery === "charge" ? T(`battery charges ${Math.round(row.battery_power_kw)} kW`, `batterij laadt ${Math.round(row.battery_power_kw)} kW`)
      : T(`battery delivers ${Math.round(row.battery_power_kw)} kW`, `batterij levert ${Math.round(row.battery_power_kw)} kW`);
    return `${hh(row.hour)} · ${cents(row.power_price_eur_kwh)} · ${T("heat from", "warmte uit")} ${heatName(row.heat_source)}`
      + ` · ${T("lamps", "lampen")} ${Math.round((row.lighting_level || 0) * 100)}% · ${battery}`
      + ` · ${T("grid", "net")} ${mw(row.grid_import_kw)} / ${mw(row.import_limit_kw)}`
      + (row.chp_running ? ` · ${T("CHP on", "WKK aan")}` : "");
  };
  if (readout) readout.textContent = "";
  const pick = (event) => {
    const box = chart.getBoundingClientRect();
    const hour = Math.floor(((event.clientX - box.left) / box.width * W - L) / step);
    if (hour < 0 || hour > 23) { highlight.setAttribute("visibility", "hidden"); return; }
    highlight.setAttribute("x", x(hour));
    highlight.setAttribute("visibility", "visible");
    if (readout) readout.textContent = describe(plan[hour]);
  };
  chart.addEventListener("pointermove", pick);
  chart.addEventListener("pointerdown", pick);
  root.append(tableView(planHeadings(), planRows(run)));
}

function renderDonut(run) {
  const root = $("cost-donut");
  root.replaceChildren();
  const totals = run.cost_forecast?.totals || {};
  // Part-to-whole with three parts: a donut. Fixed slot order 1-3.
  const parts = [
    // Electricity is what the grid import costs, so it wears the grid's colour.
    {label:T("Electricity", "Stroom"), value:totals.electricity_import_eur || 0, colour:"var(--s-grid)"},
    {label:T("Gas", "Gas"), value:totals.gas_eur || 0, colour:"var(--s-7)"},
    {label:T("CO₂", "CO₂"), value:totals.liquid_co2_eur || 0, colour:"var(--s-8)"},
  ].filter((p) => p.value > 0.5);
  const sum = parts.reduce((a, p) => a + p.value, 0) || 1;
  const r = 56, c = 2 * Math.PI * r;
  const chart = svg("svg", {viewBox:"0 0 160 160", class:"donut-svg", role:"img",
                            "aria-label":T("Cost by kind", "Kosten per soort")}, root);
  let offset = 0;
  for (const part of parts) {
    const length = part.value / sum * c;
    const arc = svg("circle", {cx:80, cy:80, r, fill:"none", stroke:part.colour, "stroke-width":20,
                               "stroke-dasharray":`${Math.max(0, length - 2)} ${c}`, "stroke-dashoffset":-offset,
                               transform:"rotate(-90 80 80)"}, chart);
    const title = svg("title", {}, arc);
    title.textContent = `${part.label}: ${euro(part.value)} (${Math.round(part.value / sum * 100)}%)`;
    offset += length;
  }
  svgText(chart, 80, 80, euro(totals.net_cost_eur), {class:"donut-total", "text-anchor":"middle"});
  svgText(chart, 80, 98, T("net", "netto"), {class:"tick", "text-anchor":"middle"});
  const list = el("ul", "donut-legend");
  for (const part of parts) {
    const item = el("li");
    const key = el("span", "key");
    key.style.background = part.colour;
    item.append(key, el("span", "", `${part.label} · ${Math.round(part.value / sum * 100)}%`), el("b", "", euro(part.value)));
    list.append(item);
  }
  if (totals.export_revenue_eur > 0.5) {
    const item = el("li", "income");
    item.append(el("span", "", T("Sold to the grid", "Verkocht aan het net")),
                el("b", "", `− ${euro(totals.export_revenue_eur)}`));
    list.append(item);
  }
  root.append(list);
}

function renderGoalResults(run) {
  const items = [...(run.targets || []).map((t) => ({
    name:{max_import_kw:T("Max. grid import", "Max. netafname"), light_mol_m2:T("Extra light", "Extra licht"),
          budget_eur:T("Day budget", "Dagbudget"), heat_day_c:T("Heating, day", "Verwarming, dag"),
          heat_night_c:T("Heating, night", "Verwarming, nacht")}[t.key] || t.key,
    text:t.key === "max_import_kw" ? `${mw(t.actual)} ${t.op} ${mw(t.value)}`
      : t.key === "budget_eur" ? `${euro(t.actual)} ${t.op} ${euro(t.value)}`
      : t.op === "=" ? (t.met ? T(`planned at ${t.value} °C`, `gepland op ${t.value} °C`)
                              : T("this greenhouse model cannot use it", "dit kasmodel kan dit niet gebruiken"))
      : `${t.actual} ${t.op} ${t.value}`,
    met:t.met,
  })), ...(run.goals || []).map((g) => ({name:g.name, text:`${g.actual} ${g.op} ${g.value}`, met:g.met}))];
  $("goal-results").hidden = !items.length;
  const list = $("goal-result-list");
  list.replaceChildren();
  for (const item of items) {
    const li = el("li", item.met ? "met" : "unmet");
    li.append(el("span", "mark", item.met ? "✓" : "✗"), el("span", "", item.name), el("small", "", item.text));
    list.append(li);
  }
}

function renderMemory(run) {
  const items = run.remembered_applied || [];
  $("memory-panel").hidden = !isAdvised() || !items.length;
  const list = $("memory-list");
  list.replaceChildren();
  for (const item of items) {
    const li = el("li");
    li.append(el("span", "", `“${item.said}”`), el("small", "", item.summary));
    list.append(li);
  }
}

// -- the grower's view on each part --------------------------------------------------

function dimensionTitle(dimension) {
  return {
    money:T("saves money", "bespaart geld"), crop:T("protects the crop", "beschermt het gewas"),
    work:T("fits how I work", "past bij mijn werkwijze"), goal:T("meets my goals", "haalt mijn doelen"),
  }[dimension] || dimension;
}

/** A labelled horizontal bar: the value as a share of a scale, the number at its end. */
function barRow(label, value, max, text, cls="") {
  const row = el("div", `bar-row ${cls}`.trim());
  const track = el("span", "bar-track");
  const fill = el("i");
  fill.style.width = `${Math.max(2, Math.min(1, value / Math.max(max, 1e-9)) * 100)}%`;
  track.append(fill);
  row.append(el("span", "bar-label", label), track, el("b", "", text));
  return row;
}

/** What each part of the plan amounts to, drawn rather than written. */
function dimensionVisual(dimension) {
  const run = state.run;
  const box = el("div", "evidence");
  const work = run.work || {};
  if (dimension === "money") {
    const plan = Number(run.metrics?.net_cost_eur || 0);
    const normal = Number(run.normal_settings?.net_cost_eur || plan);
    const max = Math.max(plan, normal);
    box.append(barRow(T("Normal", "Normaal"), normal, max, euro(normal), "muted-bar"),
               barRow("KasFlex", plan, max, euro(plan)));
  } else if (dimension === "crop") {
    const light = Number(run.metrics?.dli_mol_m2 || 0);
    const target = Number(run.crop_target_mol_m2 || 10);
    box.append(barRow(T("☀ Light", "☀ Licht"), light, Math.max(light, target), `${light.toFixed(1)} / ${target.toFixed(0)}`,
                      light + 0.05 >= target ? "" : "warn"));
    // One tick per hour inside the crop's temperature band.
    const hours = Math.round(Number(run.metrics?.temperature_band_hours || 0));
    const strip = el("div", "hour-strip");
    strip.title = T(`${hours} of 24 h in the temperature band`, `${hours} van 24 u binnen de temperatuurband`);
    strip.setAttribute("role", "img");
    strip.setAttribute("aria-label", strip.title);
    for (let h = 0; h < 24; h++) strip.append(el("i", h < hours ? "on" : ""));
    const row = el("div", "bar-row");
    row.append(el("span", "bar-label", T("🌡 Temp.", "🌡 Temp.")), strip, el("b", "", `${hours}/24`));
    box.append(row);
  } else if (dimension === "work") {
    const stats = el("div", "stat-icons");
    for (const [icon, value, label] of [
      ["⇄", work.switches, T("switches", "wisselingen")],
      ["⚙", `${work.chp_hours} ${T("h", "u")}`, T("CHP running", "WKK aan")],
      ["☾", `${work.chp_night_hours} ${T("h", "u")}`, T("CHP at night", "WKK 's nachts")],
    ]) {
      const stat = el("span", "stat");
      stat.title = label;
      stat.append(el("i", "", icon), el("strong", "", String(value)), el("small", "", label));
      stats.append(stat);
    }
    // Which hours the plan does something else than normal control.
    const normal = run.normal_settings?.plan || [];
    const strip = el("div", "hour-strip changed");
    strip.title = T(`${work.hours_changed_vs_normal} of 24 h differ from normal`, `${work.hours_changed_vs_normal} van 24 u anders dan normaal`);
    strip.setAttribute("role", "img");
    strip.setAttribute("aria-label", strip.title);
    (run.plan || []).forEach((row, h) => {
      const other = normal[h] || {};
      const differs = ["heat_source", "lighting_level", "battery", "chp_mode"].some((f) => row[f] !== other[f]);
      strip.append(el("i", differs ? "on" : ""));
    });
    const row = el("div", "bar-row");
    row.append(el("span", "bar-label", T("≠ Normal", "≠ Normaal")), strip, el("b", "", `${work.hours_changed_vs_normal}/24`));
    box.append(stats, row);
  } else {
    const chips = el("div", "goal-chips");
    for (const item of [...(run.targets || []), ...(run.goals || [])]) {
      const name = item.name || {max_import_kw:"⚡ MW", light_mol_m2:"☀", budget_eur:"€",
                                 heat_day_c:"🌡 ☀", heat_night_c:"🌡 ☾"}[item.key] || item.key;
      chips.append(el("span", `goal-chip ${item.met ? "met" : "unmet"}`, `${item.met ? "✓" : "✗"} ${name}`));
    }
    box.append(chips);
  }
  return box;
}

/** Current plan against the alternative, metric by metric. */
function compareVisual(current, alternative) {
  const table = el("div", "compare");
  const rows = [
    ["€", current.metrics?.net_cost_eur, alternative.metrics?.net_cost_eur, euro, false],
    ["⚡", current.grid?.peak_import_kw, alternative.grid?.peak_import_kw, mw, false],
    ["⇄", current.work?.switches, alternative.work?.switches, String, false],
    ["☀", current.metrics?.dli_mol_m2, alternative.metrics?.dli_mol_m2, (v) => Number(v || 0).toFixed(1), true],
  ];
  for (const [icon, before, after, format, upIsGood] of rows) {
    const delta = Number(after || 0) - Number(before || 0);
    const same = Math.abs(delta) < 1e-6;
    const better = upIsGood ? delta > 0 : delta < 0;
    table.append(el("span", "c-icon", icon), el("span", "c-before", format(before)),
                 el("span", "c-arrow", "→"), el("strong", `c-after ${same ? "" : better ? "good" : "worse"}`.trim(), format(after)));
  }
  return table;
}

function renderDimensions() {
  const root = $("dimensions");
  root.replaceChildren();
  if (!state.run) return;
  for (const dimension of dimensionsFor()) {
    const saved = state.dimensions[dimension] || {};
    const card = el("article", "dimension-card" + (saved.final ? " resolved" : ""));
    card.dataset.dimension = dimension;

    const top = el("div", "dimension-card-top");
    top.append(el("strong", "", dimensionTitle(dimension)));
    if (saved.final) top.append(el("span", "done", {agree:"✓", unsure:"?", disagree:"✗"}[saved.final] || "✓"));
    card.append(top, dimensionVisual(dimension));

    const choices = el("div", "response-choices");
    for (const response of ["agree", "unsure", "disagree"]) {
      const shown = saved.final || saved.initial || (state.openReason === dimension ? "disagree" : "");
      const button = el("button", "choice" + (shown === response ? " picked" : ""),
                        tr(`response.${response}`, response));
      button.type = "button";
      button.setAttribute("aria-pressed", String(shown === response));
      button.disabled = Boolean(saved.final) || Boolean(saved.busy);
      button.addEventListener("click", () => {
        if (response === "disagree") { state.openReason = dimension; renderDimensions(); card.querySelector("textarea")?.focus(); }
        else respondDimension(dimension, response);
      });
      choices.append(button);
    }
    card.append(choices);

    if (state.openReason === dimension && !saved.final && !saved.counter) {
      const box = el("div", "reason-box");
      const label = el("label");
      label.append(el("span", "", T("Why?", "Waarom?")));
      const input = el("textarea");
      input.rows = 2;
      input.maxLength = 300;
      input.value = saved.reason || "";
      input.placeholder = {
        money:T("e.g. gas will be dearer than this", "bijv. gas wordt duurder dan dit"),
        crop:T("e.g. frost tonight, keep it warmer", "bijv. vannacht vorst, houd het warmer"),
        work:T("e.g. CHP maintenance 8–14h", "bijv. WKK onderhoud van 8 tot 14 uur"),
        goal:T("e.g. stay under 2 MW from 16 to 20h", "bijv. tussen 16 en 20 uur onder 2 MW blijven"),
      }[dimension];
      input.addEventListener("input", () => {
        state.dimensions[dimension] = {...(state.dimensions[dimension] || {}), reason:input.value};
      });
      label.append(input);
      const send = el("button", "small-primary", T("Send", "Versturen"));
      send.type = "button";
      send.disabled = Boolean(saved.busy);
      send.addEventListener("click", () => {
        if (input.value.trim().length < 3) {
          input.focus();
          toast(T("Say in a few words why.", "Zeg in een paar woorden waarom."));
          return;
        }
        respondDimension(dimension, "disagree");
      });
      box.append(label, send);
      card.append(box);
    }

    if (saved.counter) {
      const counter = el("div", "counter");
      if (saved.reason) counter.append(el("p", "said", `“${saved.reason}” ${saved.remembered ? "🧠" : ""}`.trim()));
      if (saved.summary) counter.append(el("p", "applied", saved.summary));
      if (saved.alternative && saved.before) {
        counter.append(compareVisual(saved.before, saved.alternative));
        counter.append(el("span", `checker ${saved.alternative.accepted ? "good" : "bad"}`,
          saved.alternative.accepted ? T("✓ Checked", "✓ Gecontroleerd") : T("Not safe", "Niet veilig")));
      }
      const words = el("details", "why-text");
      words.append(el("summary", "", T("In words", "In woorden")), el("p", "", saved.counter));
      counter.append(words);
      if (saved.alternative && !saved.final) {
        const actions = el("div", "counter-actions");
        const use = el("button", "small-primary", tr("counter.use", "Use this alternative"));
        use.type = "button";
        use.addEventListener("click", () => useAlternative(dimension));
        const keep = el("button", "small-ghost", tr("counter.keep", "Keep current plan"));
        keep.type = "button";
        keep.addEventListener("click", () => keepCurrent(dimension));
        actions.append(use, keep);
        counter.append(actions);
      }
      card.append(counter);
    }
    root.append(card);
  }
}

async function respondDimension(dimension, response) {
  const previous = state.dimensions[dimension] || {};
  state.dimensions[dimension] = {...previous, busy:true};
  renderDimensions();
  const payload = {
    ...runRef(),
    overrides:overrides(),
    session_id:state.sessionId,
    participant_id:state.participantId,
    dimension,
    response,
    time_to_first_response_s:secondsSince(state.planShownAt),
    detail_expansions:state.detailExpansions,
    why_clicks:state.whyClicks,
    edits_made:state.editsMade,
    reason:response === "disagree" ? (previous.reason || "") : "",
  };
  try {
    const reply = await api("/api/deliberate", payload);
    state.dimensions[dimension] = {
      ...previous, busy:false,
      initial:response,
      counter:response === "disagree" ? reply.counter_response : "",
      summary:reply.reason_summary || "",
      remembered:Boolean(reply.remembered_id),
      before:response === "disagree" ? state.run : null,
      counterModel:reply.counter_model || "",
      alternative:reply.alternative,
      final:response === "disagree" ? "" : response,
    };
    if (state.openReason === dimension) state.openReason = "";
    if (response !== "disagree") await finaliseDimension(dimension, response);
    else if (reply.remembered_id) toast(T("KasFlex will remember this.", "KasFlex onthoudt dit."));
  } catch (error) {
    state.dimensions[dimension] = {...previous, busy:false};
    showError(error, T("Recording your view", "Uw oordeel verwerken"));
  }
  renderDimensions();
  updateApproval();
}

async function finaliseDimension(dimension, finalResponse, acceptedFinally=null, outcomeShown=false, outcomeResult="") {
  const item = state.dimensions[dimension] || {};
  try {
    await api("/api/deliberate/final", {
      ...runRef(),
      overrides:overrides(),
      session_id:state.sessionId,
      participant_id:state.participantId,
      dimension,
      initial_response:item.initial || finalResponse,
      ai_counter_response:item.counter || "",
      counter_model:item.counterModel || "",
      final_response:finalResponse,
      time_to_first_response_s:secondsSince(state.planShownAt),
      time_to_final_decision_s:secondsSince(state.planShownAt),
      detail_expansions:state.detailExpansions,
      why_clicks:state.whyClicks,
      edits_made:state.editsMade,
      free_text_reason:item.reason || "",
      plan_accepted_finally:acceptedFinally,
      outcome_shown:outcomeShown,
      outcome_better_or_worse_than_expected:outcomeResult,
    });
  } catch (error) {
    showError(error, T("Saving research record", "Onderzoeksrecord opslaan"));
  }
}

async function useAlternative(dimension) {
  const item = state.dimensions[dimension];
  if (!item?.alternative) return;
  state.editsMade += 1;
  state.run = item.alternative;
  state.planShownAt = performance.now();
  state.dimensions = {[dimension]: {...item, final:"agree", alternative:null}};
  await finaliseDimension(dimension, "agree");
  renderDecision(state.run, {preserveDimensions:true});
  toast(T("New plan in place. Look at the other parts again.", "Nieuw plan staat klaar. Bekijk de andere onderdelen opnieuw."));
}

async function keepCurrent(dimension) {
  const item = state.dimensions[dimension];
  state.dimensions[dimension] = {...item, final:"disagree", alternative:null};
  await finaliseDimension(dimension, "disagree");
  renderDimensions();
  updateApproval();
}

function updateApproval() {
  const dims = dimensionsFor();
  const done = dims.filter((dimension) => state.dimensions[dimension]?.final).length;
  // Progress as dots, one per part: filled once the grower has given a view.
  const dots = $("review-progress");
  dots.replaceChildren(...dims.map((dimension) => {
    const dot = el("span", state.dimensions[dimension]?.final ? "dot done" : "dot");
    dot.title = dimensionTitle(dimension);
    return dot;
  }));
  dots.setAttribute("role", "img");
  dots.setAttribute("aria-label", T(`${done} of ${dims.length} parts reviewed`, `${done} van ${dims.length} onderdelen beoordeeld`));
  $("approve-plan").disabled = state.approved
    || !(done === dims.length && state.run?.checker_enabled && state.run?.accepted);
}

// -- detail views ---------------------------------------------------------------------

function openDialog(title, subtitle="") {
  state.detailExpansions += 1;
  $("dialog-title").textContent = title;
  $("dialog-eyebrow").textContent = subtitle;
  $("dialog-eyebrow").title = "";
  const body = $("dialog-body");
  body.replaceChildren();
  $("detail-dialog").showModal();
  return body;
}

function openDetail(kind) {
  if (kind === "risk") renderRiskDetail(openDialog(T("Risk and uncertainty", "Risico en onzekerheid")));
  else if (kind === "plan") renderPlanDetail(openDialog(T("Tomorrow, hour by hour", "Morgen, uur voor uur")));
  else renderDataDetail(openDialog(T("Data and provenance", "Data en herkomst")));
}

function renderPlanDetail(root) {
  const holder = el("div", "chart");
  const readout = el("p", "hover-readout");
  root.append(holder, readout);
  renderPlanChart(holder, state.run, {tall:true});
  // The same numbers as text, for anyone who prefers to read them.
  const details = el("details", "plan-text");
  details.append(el("summary", "", T("Why each hour", "Waarom per uur")));
  const list = el("ol");
  for (const row of state.run?.plan || []) list.append(el("li", "", `${hh(row.hour)} — ${row.reasoning || ""}`));
  details.append(list);
  root.append(details);
}

async function openFactors() {
  if (!state.run) return;
  state.whyClicks += 1;
  const root = openDialog(T("Why this plan?", "Waarom dit plan?"),
                          T("Hours that change without each factor ⓘ", "Uren die veranderen zonder elke factor ⓘ"));
  root.append(el("p", "muted", T("Working it out…", "Even rekenen…")));
  try {
    const result = await api("/api/explain-factors", {...runRef(), overrides:overrides()});
    root.replaceChildren();
    const chart = el("div", "factor-chart");
    for (const bar of result.bars || []) {
      const row = el("div", "factor-row");
      const track = el("span", "factor-track");
      const fill = el("i");
      fill.style.width = `${Math.max(2, bar.share * 100)}%`;
      track.append(fill);
      const effect = bar.cost_effect_eur;
      row.append(el("span", "factor-label", bar.label), track,
                 el("b", "", T(`${bar.changed_hours.length} of 24 h`, `${bar.changed_hours.length} van 24 u`)),
                 el("small", "", Math.abs(effect) < 1 ? "—"
                   : T(`${effect > 0 ? "+" : "−"}${euro(Math.abs(effect))} without it`, `${effect > 0 ? "+" : "−"}${euro(Math.abs(effect))} zonder`)));
      row.title = bar.sentence;
      chart.append(row);
    }
    root.append(chart);
    $("dialog-eyebrow").title = result.method || "";
  } catch (error) {
    root.replaceChildren(el("p", "error", String(error.message || error)));
  }
}

async function openWeek() {
  if (!state.run) return;
  const root = openDialog(T("A week like this", "Een week als deze"), T("Estimate ⓘ", "Schatting ⓘ"));
  root.append(el("p", "muted", T("Planning seven days…", "Zeven dagen plannen…")));
  try {
    const result = await api("/api/week-outlook", {overrides:overrides(), policy:state.run.policy || selectedPolicy()});
    root.replaceChildren();
    const W = 640, H = 220, L = 50, B = 26, top = 12;
    const max = Math.max(...result.days.flatMap((d) => [d.cost_eur, d.normal_cost_eur]), 1) * 1.08;
    const chart = svg("svg", {viewBox:`0 0 ${W} ${H}`, class:"svg-chart", role:"img"});
    const band = (W - L - 10) / 7;
    const y = (v) => top + (H - top - B) * (1 - v / max);
    for (let i = 0; i <= 2; i++) {
      const value = max * i / 2;
      svg("line", {x1:L, x2:W - 10, y1:y(value), y2:y(value), class:"gridline"}, chart);
      svgText(chart, L - 6, y(value) + 4, value < 1 ? "€0" : `€${(value / 1000).toFixed(0)}k`, {class:"tick", "text-anchor":"end"});
    }
    const w = Math.min(24, band * .3);
    svg("line", {x1:L, x2:W - 10, y1:y(0), y2:y(0), class:"baseline"}, chart);
    result.days.forEach((day, i) => {
      const mid = L + band * i + band / 2;
      for (const [value, cls, name, left] of [
        [day.normal_cost_eur, "col-normal", T("Normal control", "Normale regeling"), mid - w - 1],
        [day.cost_eur, "col-plan", "KasFlex", mid + 1],
      ]) {
        const mark = svg("path", {d:columnPath(left, y(value), w, y(0) - y(value)), class:cls}, chart);
        svg("title", {}, mark).textContent = `${T("Day", "Dag")} ${day.day} · ${name}: ${euro(value)}`;
      }
      svgText(chart, mid, H - 8, T(`day ${day.day}`, `dag ${day.day}`), {class:"tick", "text-anchor":"middle"});
    });
    const legend = el("div", "legend");
    legend.append(el("span", "key normal"), el("span", "", T("Normal control", "Normale regeling")),
                  el("span", "key plan"), el("span", "", T("KasFlex", "KasFlex")));
    const summary = el("div", "detail-grid");
    for (const [label, value] of [
      [T("Week cost", "Weekkosten"), euro(result.cost_eur)],
      [T("Saved vs normal", "Bespaard t.o.v. normaal"), euro(result.saving_eur)],
      [T("Tomato growth", "Tomatengroei"), `${Number(result.growth_kg_m2).toFixed(2)} kg/m²`],
    ]) {
      const card = el("article");
      card.append(el("span", "", label), el("strong", "", value));
      summary.append(card);
    }
    const table = tableView([T("Day", "Dag"), T("Normal control", "Normale regeling"), "KasFlex", T("Growth", "Groei")],
      result.days.map((d) => [String(d.day), euro(d.normal_cost_eur), euro(d.cost_eur), `${d.growth_kg_m2.toFixed(3)} kg/m²`]));
    root.append(summary, chart, legend, table);
    // Why there is no week plan, for whoever wonders: on hover, not on the screen.
    $("dialog-eyebrow").title = T(
      "The day-ahead market sets prices one day at a time, and weather forecasts lose most of their skill after two or three days. So KasFlex plans tomorrow; this outlook only estimates a week of such days.",
      "De day-aheadmarkt zet prijzen per dag vast, en weersverwachtingen worden na twee à drie dagen veel onzekerder. KasFlex plant dus morgen; dit overzicht schat alleen een week van zulke dagen.");
  } catch (error) {
    root.replaceChildren(el("p", "error", String(error.message || error)));
  }
}

function renderPositionDetail(root) {
  const summary = state.run?.position?.summary || {};
  const grid = el("div", "detail-grid");
  for (const [label, value] of [
    [T("Contracted", "Gecontracteerd"), `${(Number(summary.contracted_energy_kwh || 0) / 1000).toFixed(1)} MWh`],
    [T("Planned net use", "Geplande netto-afname"), `${(Number(summary.planned_net_energy_kwh || 0) / 1000).toFixed(1)} MWh`],
    [T("Absolute deviation", "Absolute afwijking"), `${(Number(summary.absolute_deviation_kwh || 0) / 1000).toFixed(1)} MWh`],
    [T("Spot settlement", "Spotafrekening"), euro(summary.settlement_eur || 0)],
    [T("Export", "Export"), `${(Number(summary.export_energy_kwh || 0) / 1000).toFixed(1)} MWh`],
    [T("Export revenue", "Exportopbrengst"), euro(summary.export_revenue_eur || 0)],
  ]) {
    const card = el("article");
    card.append(el("span", "", label), el("strong", "", value));
    grid.append(card);
  }
  const contract = state.context?.grid?.contract;
  root.append(grid);
  if (contract) root.append(el("p", "detail-note", `${contract.name}: ${contract.summary}`));
  root.append(el("p", "detail-note", T(
    "Volume risk is the difference between the contracted position and what the plan needs from the grid. Positive deviation is short; negative is long.",
    "Positierisico is het verschil tussen vooraf ingekocht volume en wat het plan van het net vraagt. Positief is tekort; negatief is over.")));
  const bars = el("div", "position-bars");
  for (const row of state.run?.position?.hours || []) {
    const line = el("div", `position-line ${row.direction}`);
    const direction = row.direction === "short" ? T("short", "tekort")
      : row.direction === "long" ? T("long", "overschot") : String(row.direction || "");
    line.append(el("span", "", hh(row.hour)), el("b", "", mw(row.planned_net_kw)),
                el("small", "", `${direction} · ${euro(row.settlement_eur, 0)}`));
    bars.append(line);
  }
  root.append(bars);
}

function renderPositionPage() {
  $("position-page-title").textContent = T("Position, deviation and grid", "Positie, afwijking en net");
  $("back-from-position").textContent = T("← Back to the plan", "← Terug naar het plan");
  const body = $("position-page-body");
  body.replaceChildren();
  renderPositionDetail(body);
}

function openPositionPage() {
  if (!state.run) return;
  state.detailExpansions += 1;
  $("decision-view").hidden = true;
  $("position-view").hidden = false;
  renderPositionPage();
  window.scrollTo({top:0, behavior:motion()});
}

function closePositionPage() {
  $("position-view").hidden = true;
  $("decision-view").hidden = false;
  window.scrollTo({top:0, behavior:motion()});
}

function renderRiskDetail(root) {
  const u = state.run?.uncertainty || {};
  const band = u.cost;
  const basis = state.lang === "nl"
    ? ({measured:"gemeten", assumed:"aangenomen"}[u.forecast_error?.basis] || u.forecast_error?.basis)
    : u.forecast_error?.basis;
  const novelty = state.lang === "nl"
    ? ({typical:"gebruikelijk", unusual:"ongebruikelijk", "unlike anything seen":"niet eerder gezien", unknown:"onbekend"}[u.novelty?.band] || u.novelty?.band)
    : u.novelty?.band;
  const grid = el("div", "detail-grid");
  for (const [label, value] of [
    [T("Expected", "Verwacht"), euro(state.run?.metrics?.net_cost_eur)],
    [T("Bad case (90th percentile)", "Ongunstig (90e percentiel)"), band && u.is_defensible ? euro(band.high_eur) : "—"],
    [T("Weather uncertainty", "Weeronzekerheid"), basis || "—"],
    [T("Model familiarity", "Modelbekendheid"), novelty || "—"],
  ]) {
    const card = el("article");
    card.append(el("span", "", label), el("strong", "", value));
    grid.append(card);
  }
  root.append(grid, el("p", "detail-note", u.words?.detail || ""));
  if (state.run?.actuals_available && state.run?.data_source === "demo") {
    root.append(el("p", "detail-note", T(
      `Replay realised cost: ${euro(state.run.metrics?.net_cost_eur)} versus ${euro(state.run.cost_forecast?.totals?.net_cost_eur || state.run.metrics?.net_cost_eur)} predicted.`,
      `Werkelijke replay-kosten: ${euro(state.run.metrics?.net_cost_eur)} tegenover ${euro(state.run.cost_forecast?.totals?.net_cost_eur || state.run.metrics?.net_cost_eur)} voorspeld.`)));
  }
  root.append(el("p", "warning", T(
    "A measured AGC replay has been completed, but calibration errors remain too high for operational use.",
    "Een gemeten AGC-replay is uitgevoerd, maar de kalibratiefouten zijn nog te groot voor operationeel gebruik.")));
}

function renderDataDetail(root) {
  const items = Object.entries(state.context?.provenance || {});
  if (!items.length) {
    root.append(el("p", "muted", state.context?.data_source === "scenario"
      ? T("This day comes from a workshop scenario: prices and temperatures were set by the researcher.",
          "Deze dag komt uit een workshopscenario: prijzen en temperaturen zijn door de onderzoeker ingesteld.")
      : T("No provenance metadata available.", "Geen bronmetadata beschikbaar.")));
    return;
  }
  const roles = {prices:T("Electricity prices", "Stroomprijzen"), forecast_weather:T("Weather forecast", "Weersverwachting"),
                 actual_weather:T("Realised weather", "Gerealiseerd weer")};
  for (const [role, info] of items) {
    const card = el("article", "source-card");
    card.append(el("strong", "", roles[role] || role), el("span", "", info.dataset_key || ""),
                el("small", "", info.source || ""), el("small", "", `SHA256 ${String(info.sha256 || "").slice(0, 16)}…`));
    root.append(card);
  }
}

// -- chat (collaboration version) ---------------------------------------------------

function toggleChat(open) {
  const panel = $("chat-panel");
  panel.hidden = open === undefined ? !panel.hidden : !open;
  if (!panel.hidden) {
    renderChatSuggestions();
    $("chat-input").focus();
  }
}
function renderChatSuggestions() {
  const root = $("chat-suggestions");
  root.replaceChildren();
  const dear = state.context?.price?.dearest_hours?.[0] ?? 18;
  for (const question of [
    T(`Why this at ${hh(dear)}?`, `Waarom dit om ${dear} uur?`),
    T("What does the battery do?", "Wat doet de batterij?"),
    T("When does the CHP run?", "Wanneer draait de WKK?"),
    T("What do you remember from me?", "Wat onthoud je van mij?"),
  ]) {
    const chip = el("button", "chip", question);
    chip.type = "button";
    chip.addEventListener("click", () => { $("chat-input").value = question; sendChat(); });
    root.append(chip);
  }
}
function chatMessage(who, text) {
  const node = el("div", `bubble ${who}`, text);
  $("chat-log").append(node);
  node.scrollIntoView({block:"end"});
  return node;
}
async function sendChat() {
  const input = $("chat-input");
  const question = input.value.trim();
  if (!question) return;
  if (!state.run) { toast(T("Build a plan first.", "Maak eerst een plan.")); return; }
  input.value = "";
  chatMessage("me", question);
  const pending = chatMessage("ai pending", "…");
  $("chat-send").disabled = true;
  try {
    const reply = await api("/api/chat", {
      ...runRef(), overrides:overrides(), question,
      session_id:state.sessionId, participant_id:state.participantId,
    });
    pending.className = "bubble ai";
    pending.textContent = reply.answer;
    if (reply.sources?.length) {
      pending.append(el("small", "source", T("Source: ", "Bron: ")
        + [...new Set(reply.sources.map((source) => source.title))].join(", ")));
    }
    $("chat-model").textContent = reply.model === "kasflex-offline-assistant"
      ? T("offline answers", "offline antwoorden") : reply.model;
  } catch (error) {
    pending.className = "bubble ai error";
    pending.textContent = String(error.message || error);
  } finally {
    $("chat-send").disabled = false;
  }
}

// -- approval and debrief ----------------------------------------------------------------

async function approvePlan() {
  if (!state.run) return;
  const button = $("approve-plan");
  button.disabled = true;
  try {
    await api("/api/decision", {
      ...runRef(),
      decision:"approve",
      comment:isAdvised() ? "Approved after dimension-level deliberation" : "Approved (no-advisor version)",
      research_consent:state.studyConsented,
      seconds_to_decide:secondsSince(state.planShownAt),
    });
    const predicted = Number(state.run.cost_forecast?.totals?.net_cost_eur || state.run.metrics?.net_cost_eur || 0);
    const actual = Number(state.run.metrics?.net_cost_eur || 0);
    const outcomeResult = !state.run.actuals_available ? ""
      : actual <= predicted ? "better_than_expected" : "worse_than_expected";
    for (const dimension of dimensionsFor()) {
      await finaliseDimension(dimension, state.dimensions[dimension]?.final || "unsure", true,
                              Boolean(state.run.actuals_available), outcomeResult);
    }
    if (state.run.actuals_available && state.run.data_source === "demo") {
      try {
        await api("/api/outcomes", {
          overrides:overrides(),
          run_id:state.run.run_id,
          predicted_cost_eur:predicted,
          actual_cost_eur:actual,
          ai_plan_cost_eur:predicted,
          final_plan_cost_eur:actual,
          within_predicted_band:Boolean(state.run.uncertainty?.cost
            && actual >= state.run.uncertainty.cost.low_eur && actual <= state.run.uncertainty.cost.high_eur),
          note:"Historical demo replay",
        });
      } catch {}
    }
    state.approved = true;
    button.textContent = T("✓ Approved", "✓ Goedgekeurd");
    showDebrief(state.run);
    toast(T("Final plan recorded.", "Definitief plan vastgelegd."));
  } catch (error) {
    showError(error, T("Approving plan", "Plan goedkeuren"));
    updateApproval();
  }
}

/** After approval, the scenario says how tomorrow really went: the moment a
 *  workshop participant learns whether there was a trap and whether they caught it. */
function showDebrief(run) {
  const check = run.scenario?.check;
  if (!check) return;
  $("debrief").hidden = false;
  $("debrief").className = "panel debrief " + (check.ok ? "good" : "bad");
  $("debrief-message").textContent = check.message || "";
  $("debrief-text").textContent = check.debrief || "";
  $("debrief").scrollIntoView({behavior:motion(), block:"center"});
}

function backToChoices() {
  $("decision-view").hidden = true;
  $("prepare-view").hidden = false;
  if (isAdvised()) { state.chooseOwn = true; applyVersion(); }
}

async function consentStudy() {
  const participant = $("participant-id").value.trim();
  if (!participant) { $("participant-id").focus(); return; }
  const button = $("consent-study"); button.disabled = true;
  try {
    const status = await api("/api/consent");
    const keyName = `kasflex.consent.key.${participant}`;
    const granted = await api("/api/consent", {
      participant_id:participant,
      version:status.version,
      scopes:{research:true, quotes:true, outcomes:true},
      overrides:{participant_id:participant},
      withdraw_key:readStore(keyName) || "",
    });
    // The key lets this browser withdraw or change this participant's consent later.
    if (granted.withdraw_key) writeStore(keyName, granted.withdraw_key);
    state.participantId = participant;
    state.studyConsented = true;
    writeStore("kasflex.demo.participant", participant);
    $("consent-dialog").close();
  } catch (error) {
    showError(error, T("Saving consent", "Toestemming opslaan"));
  } finally { button.disabled = false; }
}

function consentAnonymous() {
  state.participantId = "";
  state.studyConsented = false;
  writeStore("kasflex.demo.participant", null);
  $("consent-dialog").close();
}

function resetToPrepare() {
  $("checker-comparison").hidden = true;
  state.run = null;
  state.dimensions = {};
  $("decision-view").hidden = true;
  $("position-view").hidden = true;
  $("prepare-view").hidden = false;
  $("chat-log").replaceChildren();
  applyVersion();
}

// -- settings (behind the admin password) ------------------------------------------

function openSettings() {
  $("settings-dialog").showModal();
  if (state.adminToken) loadSettings();
  else showSettingsLogin();
}
function showSettingsLogin(message="") {
  $("settings-login").hidden = false;
  $("settings-body").hidden = true;
  $("settings-login-error").hidden = !message;
  $("settings-login-error").textContent = message;
  $("settings-password").value = "";
  $("settings-password").focus();
}
async function unlockSettings(event) {
  event?.preventDefault();
  try {
    const result = await api("/api/admin/login", {password:$("settings-password").value});
    state.adminToken = result.token;
    writeSession("kasflex.admin.token", result.token);
    await loadSettings();
  } catch (error) {
    showSettingsLogin(error.status === 401 ? T("Wrong password.", "Verkeerd wachtwoord.") : String(error.message || error));
  }
}
async function lockSettings() {
  try { await api("/api/admin/logout", {}); } catch {}
  state.adminToken = "";
  writeSession("kasflex.admin.token", "");
  showSettingsLogin();
}

function selectedProviderInfo() {
  return (state.settings?.models?.providers || []).find((p) => p.id === $("set-llm_provider").value) || {};
}
function renderProviderFields() {
  const provider = selectedProviderInfo();
  const list = $("model-options");
  list.replaceChildren(...(provider.models || []).map((model) => { const o = el("option"); o.value = model; return o; }));
  $("base-url-field").hidden = !(provider.local || provider.base_url_env);
  $("api-key-field").hidden = !provider.requires_key;
  $("key-status").className = "status-dot " + (provider.configured ? "on" : "off");
  $("key-status").title = provider.configured ? T("Key saved", "Sleutel opgeslagen") : T("No key yet", "Nog geen sleutel");
  $("test-ai-result").textContent = "";
}

async function loadSettings() {
  try {
    state.settings = await api("/api/site-settings");
  } catch (error) {
    if (error.status === 401) { showSettingsLogin(); return; }
    showSettingsLogin(String(error.message || error));
    return;
  }
  $("settings-login").hidden = true;
  $("settings-body").hidden = false;
  const fields = Object.fromEntries(state.settings.fields.map((f) => [f.path, f]));
  const providerSelect = $("set-llm_provider");
  providerSelect.replaceChildren(...(state.settings.models?.providers || []).map((provider) => {
    const option = el("option", "", provider.name);
    option.value = provider.id;
    return option;
  }));
  providerSelect.value = fields.llm_provider?.value || "";
  $("set-llm_model").value = fields.llm_model?.value || "";
  $("set-llm_base_url").value = fields.llm_base_url?.value || "";
  $("set-api-key").value = "";
  $("set-entsoe-key").value = "";
  renderProviderFields();
  const entsoe = (state.settings.connections?.connections || []).find((c) => c.id === "entsoe");
  $("entsoe-status").className = "status-dot " + (entsoe?.configured ? "on" : "off");

  // The site's own numbers: one input per field, unit beside it, no explanations.
  const root = $("site-fields");
  root.replaceChildren();
  for (const field of state.settings.fields) {
    if (field.path.startsWith("llm_")) continue;
    const label = el("label");
    label.title = field.help || "";
    let input;
    if (field.kind === "choice") {
      input = el("select");
      for (const choice of field.choices || []) {
        const option = el("option", "", state.settings.contract_names?.[choice] || choice);
        option.value = choice;
        input.append(option);
      }
    } else {
      input = el("input");
      input.type = "number";
      if (field.min !== undefined) input.min = field.min;
      if (field.max !== undefined) input.max = field.max;
      input.step = field.step || "any";
    }
    input.value = field.value ?? "";
    input.dataset.path = field.path;
    const name = el("span", "", field.label + (field.unit ? ` (${field.unit})` : ""));
    label.append(name, input);
    root.append(label);
  }
}

async function saveSettings() {
  const values = {
    llm_provider:$("set-llm_provider").value,
    llm_model:$("set-llm_model").value.trim(),
    llm_base_url:$("set-llm_base_url").value.trim(),
  };
  document.querySelectorAll("#site-fields [data-path]").forEach((input) => {
    values[input.dataset.path] = input.tagName === "SELECT" ? input.value
      : (input.value === "" ? "" : Number(input.value));
  });
  const button = $("save-settings");
  button.disabled = true;
  try {
    const key = $("set-api-key").value.trim();
    if (key) await api("/api/connections", {provider:$("set-llm_provider").value, api_key:key});
    const entsoe = $("set-entsoe-key").value.trim();
    if (entsoe) await api("/api/connections", {provider:"entsoe", api_key:entsoe});
    await api("/api/site-settings", {values});
    await loadSettings();
    toast(T("Saved.", "Opgeslagen."));
    if (state.context) { resetToPrepare(); await loadContext(); }
  } catch (error) {
    if (error.status === 401) showSettingsLogin(T("Locked again: enter the password.", "Weer vergrendeld: voer het wachtwoord in."));
    else toast(String(error.message || error));
  } finally {
    button.disabled = false;
  }
}

async function testAi() {
  const out = $("test-ai-result");
  out.textContent = "…";
  try {
    const result = await api("/api/models/test", {provider:$("set-llm_provider").value,
      model:$("set-llm_model").value.trim(), base_url:$("set-llm_base_url").value.trim()});
    out.textContent = result.ok ? "✓" : `✗ ${result.message || ""}`;
    out.className = result.ok ? "ok" : "bad";
  } catch (error) {
    out.textContent = `✗ ${error.message || error}`;
    out.className = "bad";
  }
}

$("battery-reserve").addEventListener("input", () => $("reserve-value").textContent = $("battery-reserve").value + "%");
$("checker-enabled").addEventListener("change", () => {
  const on = $("checker-enabled").checked;
  toast(on ? T("Safety check on.", "Veiligheidscheck aan.")
           : T("Check off: this plan cannot be finally approved.", "Check uit: dit plan kan niet definitief worden goedgekeurd."));
});
for (const id of ["target-import", "target-light", "target-budget", "target-heat-day", "target-heat-night"]) $(id).addEventListener("input", renderGoalList);
$("refresh-data").addEventListener("click", () => loadContext({ refresh: true }));
$("compare-checker").addEventListener("click", compareChecker);
$("build-plan").addEventListener("click", buildPlan);
$("accept-recommendation").addEventListener("click", buildPlan);
$("choose-own").addEventListener("click", chooseOwn);
$("add-goal").addEventListener("click", addGoal);
$("open-position").addEventListener("click", openPositionPage);
$("back-from-position").addEventListener("click", closePositionPage);
$("open-risk").addEventListener("click", () => openDetail("risk"));
$("open-plan").addEventListener("click", () => openDetail("plan"));
$("open-data").addEventListener("click", () => openDetail("data"));
$("open-factors").addEventListener("click", openFactors);
$("open-week").addEventListener("click", openWeek);
$("approve-plan").addEventListener("click", approvePlan);
$("back-to-choices").addEventListener("click", backToChoices);
$("close-dialog").addEventListener("click", () => $("detail-dialog").close());
$("consent-anonymous").addEventListener("click", consentAnonymous);
$("consent-study").addEventListener("click", consentStudy);
$("chat-toggle").addEventListener("click", () => toggleChat());
$("open-settings").addEventListener("click", openSettings);
$("close-settings").addEventListener("click", () => $("settings-dialog").close());
$("unlock-settings").addEventListener("click", unlockSettings);
$("settings-login").addEventListener("submit", unlockSettings);
$("lock-settings").addEventListener("click", lockSettings);
$("save-settings").addEventListener("click", saveSettings);
$("test-ai").addEventListener("click", testAi);
$("open-admin").addEventListener("click", () => { window.location.href = "/admin"; });
$("set-llm_provider").addEventListener("change", renderProviderFields);
$("chat-close").addEventListener("click", () => toggleChat(false));
$("chat-send").addEventListener("click", (event) => { event.preventDefault(); sendChat(); });
$("chat-form").addEventListener("submit", (event) => { event.preventDefault(); sendChat(); });
$("input-mode").addEventListener("change", async (event) => {
  state.inputMode = ["real", "scenario"].includes(event.target.value) ? event.target.value : "showcase";
  writeStore("kasflex.demo.inputMode", state.inputMode);
  resetToPrepare();
  await loadContext();
});
$("scenario-select").addEventListener("change", async (event) => {
  state.scenarioId = event.target.value;
  writeStore("kasflex.demo.scenario", state.scenarioId);
  state.inputMode = "scenario";
  $("input-mode").value = "scenario";
  resetToPrepare();
  await loadContext();
});
$("language-select").addEventListener("change", async (event) => {
  await loadLanguage(event.target.value);
  $("checker-comparison").hidden = true;
  await loadWorkshop();
  await loadValidationStatus();
  if (state.context) await loadContext();
});

async function boot() {
  try {
    await loadLanguage(state.lang);
    await loadWorkshop();
    await loadValidationStatus();
    await handleConsent();
    await loadContext();
  } catch (error) {
    showError(error, T("Starting", "Starten"));
  }
}
boot();
