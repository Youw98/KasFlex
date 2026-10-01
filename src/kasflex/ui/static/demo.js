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
  providers: [],
  selectedProvider: "",
  selectedModel: "",
  approved: false,
};

function readStore(key) { try { return localStorage.getItem(key); } catch { return null; } }
function writeStore(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch {}
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : {"Content-Type": "application/json"},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch {}
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
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
  $("model-field").hidden = !advised;
  $("intro-copy").textContent = advised
    ? T("KasFlex looks at prices, weather and your grid contract first and makes a suggestion. You decide.",
        "KasFlex kijkt eerst naar prijzen, weer en uw netcontract en doet een voorstel. U beslist.")
    : T("Choose what matters and set your targets. KasFlex calculates the plan and checks it.",
        "Kies wat telt en stel uw doelen in. KasFlex rekent het plan uit en controleert het.");
  $("recommend-panel").hidden = !advised || !state.recommendation;
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
    llm_provider:state.selectedProvider || undefined,
    llm_model:state.selectedModel || undefined,
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

async function loadModels() {
  const previousProvider = state.selectedProvider;
  const previousModel = state.selectedModel;
  const select = $("model-select");
  let payload;
  try { payload = await api("/api/models"); }
  catch {
    state.providers = [];
    select.replaceChildren();
    const option = el("option", "", T("Built-in planner", "Ingebouwde planner"));
    option.value = JSON.stringify({provider:previousProvider, model:previousModel});
    select.append(option);
    return;
  }
  state.providers = payload.providers || [];
  const selected = payload.selected || {};
  state.selectedProvider = previousProvider || selected.provider || "";
  state.selectedModel = previousModel || selected.model || "";
  select.replaceChildren();
  for (const provider of state.providers) {
    const models = provider.models?.length ? provider.models : [state.selectedModel || "default"];
    for (const model of models) {
      const status = provider.configured === false ? T(" · setup needed", " · installatie nodig") : "";
      const option = el("option", "", `${provider.name} — ${model}${status}`);
      option.value = JSON.stringify({provider:provider.id, model});
      if (provider.id === state.selectedProvider && model === state.selectedModel) option.selected = true;
      select.append(option);
    }
  }
  if (!select.options.length) {
    const option = el("option", "", T("Built-in planner", "Ingebouwde planner"));
    option.value = JSON.stringify({provider:"", model:""});
    select.append(option);
  }
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
  if (ctx.data_source === "synthetic") {
    $("source-summary").textContent = T("Fixed showcase prices · simulated weather",
                                        "Vaste showcaseprijzen · gesimuleerd weer");
  } else if (ctx.data_source === "scenario") {
    $("source-summary").textContent = T("Workshop scenario", "Workshopscenario");
  } else {
    const provenance = ctx.provenance || {};
    const market = provenance.prices?.dataset_key === "entsoe_da"
      ? T("ENTSO-E-derived NL prices", "ENTSO-E-afgeleide NL-prijzen") : T("electricity prices", "stroomprijzen");
    const weather = provenance.forecast_weather?.dataset_key === "openmeteo_hist_forecast"
      ? "Open-Meteo" : T("weather forecast", "weersverwachting");
    $("source-summary").textContent = `${market} · ${weather}`;
  }

  const scenario = ctx.scenario;
  $("scenario-card").hidden = !scenario;
  if (scenario) {
    $("scenario-title").textContent = scenario.title_text || scenario.id;
    $("scenario-framing").textContent = scenario.framing_text || "";
  }

  $("price-low").textContent = cents(ctx.price.min_eur_kwh);
  $("price-high").textContent = cents(ctx.price.max_eur_kwh);
  $("price-low-hours").textContent = hourList(ctx.price.cheapest_hours);
  $("price-high-hours").textContent = hourList(ctx.price.dearest_hours);
  $("temp-range").textContent =
    `${ctx.weather.min_temp_c.toFixed(0)}${T(" to ", " tot ")}${ctx.weather.max_temp_c.toFixed(0)} °C`;
  $("sun-hours").textContent = T(`${ctx.weather.sun_hours} h daylight`, `${ctx.weather.sun_hours} uur daglicht`);
  const grid = ctx.grid || {};
  $("grid-limit").textContent = mw(grid.import_limit_kw);
  const lowered = (grid.hourly_import_kw || []).map((kw, hour) => [kw, hour])
    .filter(([kw]) => kw < grid.import_limit_kw - 1e-6).map(([, hour]) => hour);
  const name = grid.contract?.name || "";
  $("grid-window").textContent = lowered.length
    ? `${name} · ${T("lower", "lager")} ${hourRuns(lowered)}` : name;
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
  readout.textContent = T("Point at an hour for its numbers.", "Wijs een uur aan voor de getallen.");
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
  }
  applyVersion();
}

function renderRecommendation(advice) {
  $("recommend-title").textContent = T(PRIORITY_NAMES[advice.priority][0], PRIORITY_NAMES[advice.priority][1]);
  const list = $("recommend-reasons");
  list.replaceChildren(...(advice.reasons || []).map((reason) => el("li", "", reason)));

  const root = $("recommend-options");
  root.replaceChildren();
  const options = advice.options || [];
  const max = Math.max(...options.map((o) => o.cost_eur), advice.normal?.cost_eur || 0, 1);
  const rows = [...options, {...advice.normal, priority:"normal"}];
  for (const option of rows) {
    const row = el("div", "option-row" + (option.priority === advice.priority ? " chosen" : ""));
    const name = option.priority === "normal" ? T("Normal control", "Normale regeling")
      : T(PRIORITY_NAMES[option.priority][0], PRIORITY_NAMES[option.priority][1]);
    const bar = el("span", "option-bar");
    const fill = el("i");
    fill.style.width = `${Math.max(4, option.cost_eur / max * 100)}%`;
    bar.append(fill);
    row.append(el("span", "option-name", name), bar, el("b", "", euro(option.cost_eur)),
               el("small", "", `${Number(option.light_mol_m2 || 0).toFixed(1)} mol/m²`));
    root.append(row);
  }

  const memory = $("recommend-memory");
  const remembered = (advice.remembered || []).filter((item) => item.applied);
  memory.hidden = !remembered.length;
  memory.replaceChildren();
  if (remembered.length) {
    memory.append(el("strong", "", T("Taken from what you said before:", "Meegenomen uit wat u eerder zei:")));
    for (const item of remembered) memory.append(el("span", "", `“${item.said}”`));
  }
}

function chooseOwn() {
  state.chooseOwn = true;
  applyVersion();
  $("choices-panel").scrollIntoView({behavior:"smooth", block:"start"});
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
    window.scrollTo({top:0, behavior:"smooth"});
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
    ? T(`${euro(Math.abs(saving))} ${saving >= 0 ? "below" : "above"} normal`,
        `${euro(Math.abs(saving))} ${saving >= 0 ? "lager" : "hoger"} dan normaal`) : "—";
  $("result-crop").textContent = `${Number(run.metrics?.fruit_growth_kg_m2 || 0).toFixed(2)} kg/m²`;
  $("result-crop-note").textContent = T(
    `${Number(run.metrics?.supplemental_dli_mol_m2 || 0).toFixed(1)} mol/m² extra light`,
    `${Number(run.metrics?.supplemental_dli_mol_m2 || 0).toFixed(1)} mol/m² extra licht`);
  const grid = run.grid || {};
  $("result-peak").textContent = mw(grid.peak_import_kw);
  $("result-peak-note").textContent = T(`limit ${mw(grid.import_limit_kw)}`, `grens ${mw(grid.import_limit_kw)}`);
  const work = run.work || {};
  $("result-work").textContent = T(`${work.switches} switches`, `${work.switches} wisselingen`);
  $("result-work-note").textContent = T(`CHP ${work.chp_hours} h · ${work.chp_night_hours} at night`,
                                        `WKK ${work.chp_hours} u · ${work.chp_night_hours} 's nachts`);

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
    for (const violation of (run.violations || []).slice(0, 4)) list.append(el("li", "", violation.message));
    problems.append(list, el("p", "", isAdvised()
      ? T("Disagree with a reason, or change your choices or targets and rebuild.",
          "Geef bij 'Oneens' een reden, of pas uw keuzes of doelen aan en plan opnieuw.")
      : T("Change your choices or targets and rebuild.", "Pas uw keuzes of doelen aan en plan opnieuw.")));
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
  if (readout) readout.textContent = T("Point at an hour to see what happens then.", "Wijs een uur aan om te zien wat er dan gebeurt.");
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
    {label:T("Electricity", "Stroom"), value:totals.electricity_import_eur || 0, colour:"var(--s-1)"},
    {label:T("Gas", "Gas"), value:totals.gas_eur || 0, colour:"var(--s-2)"},
    {label:T("CO₂", "CO₂"), value:totals.liquid_co2_eur || 0, colour:"var(--s-3)"},
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

function dimensionEvidence(dimension) {
  const run = state.run;
  const work = run.work || {};
  if (dimension === "money") {
    const saving = Number(run.normal_settings?.saving_eur || 0);
    return T(`${euro(run.metrics?.net_cost_eur)} expected · ${euro(Math.abs(saving))} ${saving >= 0 ? "less" : "more"} than normal control.`,
             `${euro(run.metrics?.net_cost_eur)} verwacht · ${euro(Math.abs(saving))} ${saving >= 0 ? "minder" : "meer"} dan de normale regeling.`);
  }
  if (dimension === "crop") {
    const dli = Number(run.metrics?.supplemental_dli_mol_m2 || 0);
    const hours = Number(run.metrics?.temperature_band_hours || 0);
    return T(`${dli.toFixed(1)} mol/m² extra light · ${hours.toFixed(0)} of 24 h in the temperature band (simulated).`,
             `${dli.toFixed(1)} mol/m² extra licht · ${hours.toFixed(0)} van 24 uur binnen de temperatuurband (gesimuleerd).`);
  }
  if (dimension === "work") {
    return T(`${work.switches} switches of equipment · CHP ${work.chp_hours} h (${work.chp_night_hours} at night, ${work.chp_starts} starts) · ${work.hours_changed_vs_normal} of 24 h differ from normal.`,
             `${work.switches} keer wisselen van installatie · WKK ${work.chp_hours} u (${work.chp_night_hours} 's nachts, ${work.chp_starts} starts) · ${work.hours_changed_vs_normal} van 24 uur anders dan normaal.`);
  }
  const all = [...(run.targets || []), ...(run.goals || [])];
  const met = all.filter((g) => g.met).length;
  return T(`${met} of ${all.length} of your targets met.`, `${met} van ${all.length} van uw doelen gehaald.`);
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
    card.append(top, el("p", "evidence", dimensionEvidence(dimension)));

    const choices = el("div", "response-choices");
    for (const response of ["agree", "unsure", "disagree"]) {
      const shown = saved.final || saved.initial || (state.openReason === dimension ? "disagree" : "");
      const button = el("button", "choice" + (shown === response ? " picked" : ""),
                        tr(`response.${response}`, response));
      button.type = "button";
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
      label.append(el("span", "", T("Why do you disagree? KasFlex adjusts the plan and remembers it.",
                                     "Waarom bent u het oneens? KasFlex past het plan aan en onthoudt het.")));
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
      if (saved.reason) counter.append(el("p", "said", `“${saved.reason}”`));
      counter.append(el("p", "", saved.counter));
      if (saved.alternative && !saved.final) {
        const alt = saved.alternative;
        const diff = el("p", "alt-numbers", T(
          `New plan: ${euro(alt.metrics?.net_cost_eur)} · ${mw(alt.grid?.peak_import_kw)} peak · ${alt.work?.switches} switches`,
          `Nieuw plan: ${euro(alt.metrics?.net_cost_eur)} · piek ${mw(alt.grid?.peak_import_kw)} · ${alt.work?.switches} wisselingen`));
        counter.append(diff);
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
  $("review-progress").textContent = dims.length ? `${done}/${dims.length}` : "";
  $("final-title").textContent = dims.length
    ? T("Give your view on every part", "Geef uw oordeel over elk onderdeel")
    : T("Happy with this plan?", "Tevreden met dit plan?");
  if (!state.approved) {
    $("decision-copy").textContent = dims.length
      ? T("Approve once every part has your view and the check accepts the plan.",
          "Goedkeuren kan zodra elk onderdeel is beoordeeld en de check het plan accepteert.")
      : T("Not happy? Change your choices and rebuild.", "Niet tevreden? Pas uw keuzes aan en plan opnieuw.");
  }
  $("approve-plan").disabled = state.approved
    || !(done === dims.length && state.run?.checker_enabled && state.run?.accepted);
}

// -- detail views ---------------------------------------------------------------------

function openDialog(title, subtitle="") {
  state.detailExpansions += 1;
  $("dialog-title").textContent = title;
  $("dialog-eyebrow").textContent = subtitle;
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
                          T("What the plan leans on most", "Waar het plan het meest op leunt"));
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
    root.append(chart, el("p", "hint", result.method || ""));
  } catch (error) {
    root.replaceChildren(el("p", "error", String(error.message || error)));
  }
}

async function openWeek() {
  if (!state.run) return;
  const root = openDialog(T("A week like this", "Een week als deze"),
                          T("Estimate: KasFlex plans one day at a time", "Schatting: KasFlex plant één dag tegelijk"));
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
    root.append(summary, chart, legend, table, el("p", "hint", T(
      "Why not a week plan? The day-ahead market sets prices one day at a time, and weather forecasts lose most of their skill after two or three days. So KasFlex plans tomorrow, and this outlook only estimates what a week of such days adds up to.",
      "Waarom geen weekplan? De day-aheadmarkt zet prijzen per dag vast, en weersverwachtingen worden na twee à drie dagen veel onzekerder. KasFlex plant dus morgen; dit overzicht schat alleen wat een week van zulke dagen oplevert.")));
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
  $("position-page-copy").textContent = T(
    "What was bought ahead, what the plan needs, and which hours are short or long.",
    "Wat vooraf is ingekocht, wat het plan nodig heeft en welke uren tekort of over zijn.");
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
  window.scrollTo({top:0, behavior:"smooth"});
}

function closePositionPage() {
  $("position-view").hidden = true;
  $("decision-view").hidden = false;
  window.scrollTo({top:0, behavior:"smooth"});
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
    $("decision-copy").textContent = T("Approved. This checked plan is recorded as the final day plan.",
                                       "Goedgekeurd. Dit gecontroleerde plan is vastgelegd als het definitieve dagplan.");
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
  $("debrief").scrollIntoView({behavior:"smooth", block:"center"});
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
    await api("/api/consent", {
      participant_id:participant,
      version:status.version,
      scopes:{research:true, quotes:true, outcomes:true},
      overrides:{participant_id:participant},
    });
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
  await Promise.all([loadModels(), loadValidationStatus()]);
  if (state.context) await loadContext();
});
$("model-select").addEventListener("change", (event) => {
  try {
    const selected = JSON.parse(event.target.value);
    state.selectedProvider = selected.provider || "";
    state.selectedModel = selected.model || "";
  } catch {}
});

async function boot() {
  try {
    await loadLanguage(state.lang);
    await loadWorkshop();
    await loadModels();
    await loadValidationStatus();
    await handleConsent();
    await loadContext();
  } catch (error) {
    showError(error, T("Starting", "Starten"));
  }
}
boot();
