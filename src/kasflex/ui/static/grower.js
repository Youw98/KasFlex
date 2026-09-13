/* KasFlex grower interface.
 *
 * Five screens, one question each: Tomorrow ("is tomorrow okay?"), Plan ("what
 * exactly changes?"), Goals ("what should it prioritise?"), Results ("did it
 * help?"), More ("technical detail").
 *
 * Habits held throughout, each for a reason:
 *
 * - Every visible string comes from the server catalogue via t(). Hard-coding
 *   English is how a Dutch screen ends up half translated.
 * - Text goes in with textContent, never innerHTML. Plan reasoning and model
 *   answers are model output, and model output is data.
 * - Nothing is irreversible. Decisions show as done immediately and send after a
 *   delay, with an undo bar.
 * - Measurement never blocks the grower. If recording fails, they still get their
 *   plan and their decision.
 */

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const kid of kids.flat()) if (kid != null) node.append(kid);
  return node;
};

const state = {
  lang: "en",
  strings: {},
  languages: [],
  settings: {},
  adjustable: new Set(),
  profile: null,
  run: null,
  editedPlan: null,
  selectedAction: null,
  decision: null,
  elicitation: null,
  consent: null,
  busy: false,
};

const t = (key, fields) => {
  let text = state.strings[key] || key;
  if (fields) for (const [k, v] of Object.entries(fields)) text = text.replaceAll(`{${k}}`, v);
  return text;
};

const LS = {
  get(key, fallback = null) {
    try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; }
    catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* private mode */ } },
};

/* ------------------------------------------------------------------- api */

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error(t("common.error")); }
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch { /* non-JSON body */ }
  if (!response.ok) throw new Error(payload.error || t("common.error"));
  return payload;
}

function showError(error) {
  const box = $("error");
  box.textContent = String(error && error.message ? error.message : error);
  box.hidden = false;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
const clearError = () => { $("error").hidden = true; };

/* -------------------------------------------------------------- language */

function applyStrings() {
  document.documentElement.lang = state.lang;
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  }
}

async function loadLanguage(code) {
  const payload = await api(`/api/i18n?lang=${encodeURIComponent(code || "")}`);
  state.lang = payload.language;
  state.strings = payload.strings;
  state.languages = payload.languages;
  const picker = $("language");
  if (!picker.options.length) {
    for (const language of state.languages) {
      picker.append(el("option", { value: language.code, textContent: language.endonym }));
    }
  }
  picker.value = state.lang;
  applyStrings();
}

$("language").addEventListener("change", async (event) => {
  await loadLanguage(event.target.value);
  state.settings.language = event.target.value;
  LS.set("kasflex.grower.settings", state.settings);
  // A language change re-renders from the server's own wording, so the plan has
  // to be rebuilt rather than translated in place.
  if (state.run) { await runPlan({ silent: true }); } else { renderCurrentView(); }
});

/* --------------------------------------------------------------- helpers */

/* Only what the server will accept.
 *
 * state.settings also holds interface-only preferences -- which priority the
 * grower picked, whether to ask before revealing, their written brief -- and the
 * server rejects any path it does not publish as adjustable. Sending those made
 * every run fail with a 400 while a stale plan stayed on screen, which looked
 * like the planner setting simply not working. */
function overrides() {
  const out = { language: state.lang };
  for (const [key, value] of Object.entries(state.settings)) {
    if (!state.adjustable.has(key)) continue;
    if (value !== null && value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

function money(value) {
  const whole = Math.round(Math.abs(Number(value) || 0))
    .toLocaleString(state.lang === "nl" ? "nl-NL" : "en-GB");
  return (Number(value) < 0 ? "-" : "") + (state.lang === "nl" ? `€ ${whole}` : `€${whole}`);
}

const hourLabel = (hour) => state.lang === "nl"
  ? `${String(hour).padStart(2, "0")}.00 uur`
  : `${String(hour).padStart(2, "0")}:00`;

/* ---------------------------------------------------------- 1. Tomorrow */

async function runPlan({ silent = false } = {}) {
  if (state.busy) return;
  state.busy = true;
  clearError();
  $("tomorrow-empty").hidden = true;
  $("tomorrow-result").hidden = true;
  $("tomorrow-loading").hidden = false;

  try {
    // The request goes out first and runs while the grower answers, so the wait
    // sits behind the question rather than in front of it.
    const pendingRun = api("/api/run", { overrides: overrides() });
    pendingRun.catch(() => {});

    let answer = null;
    if (!silent && state.settings.ask_first !== false) {
      $("tomorrow-loading").hidden = true;
      answer = await askBeforeReveal();
      $("tomorrow-loading").hidden = false;
    }

    const result = await pendingRun;
    state.run = result;
    state.editedPlan = (result.plan || []).map((row) => ({ ...row }));
    state.decision = null;
    state.selectedAction = null;
    LS.set("kasflex.grower.lastRun", result);

    state.elicitation = answer ? await recordElicitation(answer, result.run_id) : null;

    renderTomorrow(result);
    $("tomorrow-result").hidden = false;
    await revealToElicitation(result);
  } catch (error) {
    showError(error);
    $("tomorrow-empty").hidden = false;
  } finally {
    $("tomorrow-loading").hidden = true;
    state.busy = false;
  }
}

/* Crop first, energy second, per the information hierarchy. */
function renderTiles(result) {
  const root = $("tiles");
  root.replaceChildren();
  if (!result) {
    root.append(tile("tile.plan", t("tile.plan.notyet"), "", ""));
    return;
  }

  const band = Number((result.metrics || {}).temperature_band_hours);
  const cropLevel = !Number.isFinite(band) ? "warn" : band >= 22 ? "good" : band >= 18 ? "warn" : "bad";
  const cropKey = cropLevel === "good" ? "good" : cropLevel === "warn" ? "watch" : "risk";
  root.append(tile("tile.crop", t(`tile.crop.${cropKey}`), t(`tile.crop.${cropKey}.note`), cropLevel));

  const onTarget = Number.isFinite(band) && band >= 22;
  root.append(tile("tile.climate",
    t(onTarget ? "tile.climate.ontarget" : "tile.climate.off"),
    t(onTarget ? "tile.climate.ontarget.note" : "tile.climate.off.note"),
    onTarget ? "good" : "warn"));

  root.append(tile("tile.cost", money((result.metrics || {}).net_cost_eur),
    t("tile.cost.note"), "cost"));

  const count = (result.actions || []).length;
  root.append(tile("tile.plan", t(count ? "tile.plan.ready" : "tile.plan.none"),
    count ? t("actions.count", { n: count }).split(".")[0] : "", count ? "good" : ""));
}

function tile(labelKey, value, note, level) {
  return el("div", { className: `tile ${level}`.trim() },
    el("div", { className: "k", textContent: t(labelKey) }),
    el("div", { className: "v", textContent: value }),
    note ? el("div", { className: "n", textContent: note }) : null);
}

function renderTomorrow(result) {
  renderTiles(result);
  $("plan-date").textContent = result.date || "";
  $("actions-summary").textContent = result.actions_summary || "";

  const normal = result.normal_settings;
  const saving = normal ? Number(normal.saving_eur) : 0;
  const savingLine = $("saving-line");
  savingLine.hidden = !normal;
  if (normal) {
    savingLine.textContent = saving > 1
      ? t("today.saving", { amount: money(saving) })
      : t("today.nosaving");
  }

  renderUncertainty(result.uncertainty);
  renderActionList($("action-list"), result.actions || [], { selectable: false });
  renderPreview(result.plan || []);
  renderPlanScreen(result);

  $("approve").disabled = false;
  $("keep-normal").disabled = false;
  $("decision-note").textContent = "";
}

/* How certain the estimate is, directly under the figure it qualifies.
 *
 * The server decides whether a range is defensible; this honours that answer,
 * including when the answer is "I can't tell you". An invented interval looks
 * exactly like a real one on screen, which is why this never substitutes a
 * friendlier message of its own. */
function renderUncertainty(uncertainty) {
  const root = $("uncertainty");
  if (!uncertainty || !uncertainty.words) { root.hidden = true; return; }

  root.hidden = false;
  root.dataset.confidence = uncertainty.confidence || "unknown";
  $("uncertainty-headline").textContent = uncertainty.words.headline;
  $("uncertainty-detail").textContent = uncertainty.words.detail;
  $("uncertainty-why").textContent = uncertainty.words.why;

  const caveats = $("uncertainty-caveats");
  caveats.replaceChildren();
  for (const caveat of uncertainty.caveats || []) caveats.append(el("li", { textContent: caveat }));
}

function renderActionList(root, actions, { selectable }) {
  root.replaceChildren();
  if (!actions.length) {
    root.append(el("p", { className: "muted", textContent: t("actions.none") }));
    return;
  }
  for (const action of actions) {
    const card = el(selectable ? "button" : "div", { className: "action" });
    if (selectable) {
      card.type = "button";
      card.setAttribute("aria-current", String(state.selectedAction === action.action_id));
      card.addEventListener("click", () => selectAction(action));
    }

    const foot = el("div", { className: "foot" },
      el("span", { className: "pill", textContent: `✓ ${t(`status.${action.status}`)}` }));
    if (action.saving_eur) {
      foot.append(el("span", { className: "pill cost", textContent: money(action.saving_eur) }));
    }
    if (!selectable) {
      foot.append(el("button", {
        type: "button", className: "quiet", textContent: t("why.button"),
        onclick: (event) => { event.stopPropagation(); openWhy(action); },
      }));
    }

    card.append(
      el("div", {},
        el("div", { className: "title", textContent: action.title }),
        el("div", { className: "why", textContent: action.why }),
        foot),
      el("div", { className: "muted small", textContent: `${hourLabel(action.start)}–${hourLabel(action.end)}` }));
    root.append(card);
  }
}

/* Lighting, heating, CHP only. No axis values, no power figures. */
function renderPreview(plan) {
  const root = $("preview");
  root.replaceChildren();
  const byHour = new Map(plan.map((row) => [Number(row.hour), row]));

  const rows = [
    ["preview.lighting", (row) => (row && row.lighting_level > 0.6 ? "hi" : row && row.lighting_level > 0 ? "on" : "")],
    ["preview.heating", (row) => (row && row.heat_source && row.heat_source !== "none" ? "on" : "")],
    ["preview.chp", (row) => (row && row.chp_mode && row.chp_mode !== "off" ? "hi" : "")],
  ];
  for (const [key, classify] of rows) {
    const bar = el("div", { className: "preview-bar" });
    for (let hour = 0; hour < 24; hour += 1) {
      bar.append(el("i", { className: classify(byHour.get(hour)) }));
    }
    root.append(el("div", { className: "preview-row" },
      el("div", { className: "k", textContent: t(key) }), bar));
  }
  root.append(el("div", { className: "preview-scale" },
    ...["00:00", "06:00", "12:00", "18:00", "24:00"].map((label) =>
      el("span", { textContent: label }))));
}

$("make-plan").addEventListener("click", () => runPlan());
$("remake-plan").addEventListener("click", () => runPlan());

/* ------------------------------------------------------------------ why */

/* A short causal explanation, not a chat window. The model is optional here:
 * the templated reason is always shown, and a deeper answer is offered only if
 * a model is configured. */
function openWhy(action) {
  const sheet = $("sheet");
  const body = el("div", { style: "padding:26px" },
    el("h2", { textContent: t("why.title"), style: "margin-bottom:14px" }),
    el("p", { textContent: action.title, style: "font-weight:700;margin-bottom:8px" }),
    el("p", { className: "muted", textContent: action.why }));

  if (action.saving_eur) {
    body.append(el("p", { className: "saving", textContent: money(action.saving_eur) }));
  }

  const deeper = el("p", { className: "muted small", style: "margin-top:16px" });
  body.append(deeper,
    el("div", { className: "button-row end", style: "margin-top:20px" },
      el("button", { className: "primary", textContent: t("why.gotit"), onclick: () => sheet.close() })));
  sheet.replaceChildren(body);
  sheet.showModal();

  if (!state.run) return;
  deeper.textContent = t("chat.thinking");
  api("/api/explain", {
    run_id: state.run.run_id, date: state.run.date, plan: state.run.plan,
    metrics: state.run.metrics, cost_forecast: state.run.cost_forecast,
    data_source: state.run.data_source, overrides: overrides(),
    hour: action.start,
    question: `${t("why.title")} ${action.title}`,
  }).then((reply) => { deeper.textContent = reply.answer; })
    .catch(() => { deeper.textContent = ""; });   // the templated reason stands alone
}

/* --------------------------------------------------------------- 2. Plan */

function renderPlanScreen(result) {
  const has = Boolean(result && (result.actions || []).length);
  $("plan-empty").hidden = Boolean(result);
  $("plan-content").hidden = !result;
  if (!result) return;
  renderActionList($("plan-actions"), result.actions || [], { selectable: true });
  if (!has) $("plan-actions").append(el("p", { className: "muted", textContent: t("actions.none") }));
}

function selectAction(action) {
  state.selectedAction = action.action_id;
  renderActionList($("plan-actions"), state.run.actions || [], { selectable: true });
  renderEditPanel(action);
}

function renderEditPanel(action) {
  const root = $("edit-panel");
  root.replaceChildren(
    el("h2", { textContent: t("edit.heading"), style: "margin-bottom:10px" }),
    el("p", { textContent: action.title, style: "font-weight:700" }),
    el("p", { className: "muted", textContent: action.why, style: "margin-bottom:18px" }));

  const hours = action.hours.slice();
  const impact = el("div", { className: "impact" },
    el("div", { className: "k", textContent: t("edit.impact") }),
    el("div", { className: "v", textContent: action.saving_eur ? money(action.saving_eur) : "—" }));

  if (action.field_name === "lighting_level") {
    let percent = Math.round(Number(action.planned_value) * 100);
    const value = el("span", { className: "value", textContent: `${percent}%` });
    const step = (delta) => {
      percent = Math.max(0, Math.min(100, percent + delta));
      value.textContent = `${percent}%`;
      applyEdit(hours, "lighting_level", percent / 100, impact);
    };
    root.append(
      el("div", { className: "field" },
        el("label", { textContent: t("edit.level") }),
        el("div", { className: "stepper" },
          el("button", { type: "button", textContent: "−", "aria-label": "−10%", onclick: () => step(-10) }),
          value,
          el("button", { type: "button", textContent: "+", "aria-label": "+10%", onclick: () => step(10) }))));
  }

  root.append(
    el("div", { className: "field" },
      el("label", { textContent: t("edit.hours") }),
      el("p", { textContent: `${hourLabel(action.start)} – ${hourLabel(action.end)}` })),
    impact,
    el("p", { className: "muted small", textContent: t("trust.will_check") }),
    el("div", { className: "button-row", style: "margin-top:18px" },
      el("button", {
        className: "quiet", textContent: t("edit.restore"),
        onclick: () => { restoreAction(action, impact); },
      })));
}

/* Re-check on every edit. The grower is told the result in plain words. */
let checkTimer = null;
function applyEdit(hours, field, value, impact) {
  for (const row of state.editedPlan) {
    if (hours.includes(Number(row.hour))) row[field] = value;
  }
  impact.className = "impact checking";
  impact.querySelector(".k").textContent = t("edit.checking");
  impact.querySelector(".v").textContent = "";

  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    try {
      const verdict = await api("/api/verify", {
        run_id: state.run.run_id, revision: state.run.revision,
        plan_hash: state.run.plan_hash, plan: state.editedPlan,
      });
      state.run.revision = verdict.revision;
      state.run.plan_hash = verdict.plan_hash;
      const ok = verdict.accepted;
      impact.className = `impact ${ok ? "" : "bad"}`.trim();
      impact.querySelector(".k").textContent = ok ? t("edit.reverified") : t("edit.unsafe");
      impact.querySelector(".v").textContent =
        money((verdict.metrics || {}).net_cost_eur ?? 0);
      // An edit is a disagreement with the plan, whether or not a concern is
      // written afterwards, so it is recorded here rather than only on rejection.
      recordEdits();
    } catch (error) {
      impact.className = "impact bad";
      impact.querySelector(".k").textContent = String(error.message || error);
      impact.querySelector(".v").textContent = "";
    }
  }, 500);
}

function restoreAction(action, impact) {
  const original = new Map((state.run.plan || []).map((r) => [Number(r.hour), r]));
  for (const row of state.editedPlan) {
    const source = original.get(Number(row.hour));
    if (source && action.hours.includes(Number(row.hour))) row[action.field_name] = source[action.field_name];
  }
  renderEditPanel(action);
  impact.className = "impact";
}

/* -------------------------------------------------------------- 3. Goals */

const PRIORITIES = ["crop_first", "balance", "cost_first"];

function renderGoals() {
  const root = $("priority");
  root.replaceChildren();
  const current = state.settings.priority || "balance";
  for (const key of PRIORITIES) {
    const input = el("input", { type: "radio", name: "priority", value: key });
    input.checked = key === current;
    input.addEventListener("change", () => { state.settings.priority = key; });
    root.append(el("label", { className: "choice-item" }, input,
      el("span", {},
        el("span", { className: "title", textContent: t(`goals.${key}`) }),
        el("span", { className: "desc", textContent: t(`goals.${key}.note`) }))));
  }

  const limits = $("crop-limits");
  limits.replaceChildren(
    limitRow(t("goals.temp"), `${state.settings["hub.crop.temp_min_c"] ?? 15} – ${state.settings["hub.crop.temp_max_c"] ?? 32} °C`),
    limitRow(t("goals.light"), `${state.settings["hub.crop.dli_target_mol_m2"] ?? 10} mol/m²`));

  const energy = $("energy-prefs");
  energy.replaceChildren(
    switchRow("avoid_expensive", t("goals.avoid_expensive")),
    switchRow("prefer_stored", t("goals.prefer_stored")));

  $("brief").value = state.settings.brief || "";
  loadPreferences();
}

const limitRow = (label, value) => el("div", { className: "limit-row" },
  el("span", { textContent: label }), el("span", { className: "v", textContent: value }));

function switchRow(key, label) {
  const input = el("input", { type: "checkbox", id: `sw-${key}` });
  input.checked = state.settings[key] !== false;
  input.addEventListener("change", () => { state.settings[key] = input.checked; });
  return el("div", { className: "switch-row" },
    el("label", { className: "k", htmlFor: `sw-${key}`, textContent: label }), input);
}

$("save-goals").addEventListener("click", () => {
  state.settings.brief = $("brief").value.trim();
  LS.set("kasflex.grower.settings", state.settings);
  $("goals-note").textContent = t("goals.saved");
});

/* ------------------------------------------------------------ 4. Results */

function renderResults() {
  const root = $("results-body");
  root.replaceChildren();
  const run = state.run;
  if (!run || !run.normal_settings) {
    root.append(el("p", { className: "muted", textContent: t("results.none") }));
    return;
  }

  const metrics = run.metrics || {};
  const normal = run.normal_settings;
  const band = Number(metrics.temperature_band_hours);
  const reached = Number.isFinite(band) && band >= 22;

  const tiles = el("div", { className: "tiles" },
    tile("results.crop", t(reached ? "tile.crop.good" : "tile.crop.watch"), "", reached ? "good" : "warn"),
    tile("results.temp", t(reached ? "results.reached" : "results.missed"), "", reached ? "good" : "warn"),
    tile("results.cost", money(metrics.net_cost_eur), "", "cost"),
    tile("results.savings", money(normal.saving_eur), "", normal.saving_eur > 0 ? "good" : ""));
  root.append(tiles);

  root.append(el("h3", { textContent: t("results.vs"), style: "margin:24px 0 12px" }));
  const table = el("table", { className: "plain" },
    el("thead", {}, el("tr", {},
      el("th", { textContent: "" }),
      el("th", { textContent: t("results.vs.kasflex") }),
      el("th", { textContent: t("results.vs.normal") }))),
    el("tbody", {},
      el("tr", {},
        el("td", { textContent: t("results.cost") }),
        el("td", { className: "num", textContent: money(metrics.net_cost_eur) }),
        el("td", { className: "num", textContent: money(normal.net_cost_eur) })),
      el("tr", {},
        el("td", { textContent: t("results.safety") }),
        el("td", { className: "num", textContent: String(run.realised_hard ?? 0) }),
        el("td", { className: "num", textContent: "0" })),
      el("tr", {},
        el("td", { textContent: t("results.changes") }),
        el("td", { className: "num", textContent: String((run.actions || []).length) }),
        el("td", { className: "num", textContent: "0" }))));
  root.append(table);

  root.append(el("p", { style: "margin-top:24px" },
    el("a", { href: "/advanced", textContent: t("results.detailed") })),
    el("p", { className: "muted small", textContent: t("results.detailed.note") }));
}

/* --------------------------------------------------------------- 5. More */

function renderMore() {
  const root = $("more-list");
  root.replaceChildren(
    el("a", { href: "/advanced", textContent: t("more.report") }),
    el("a", { href: "/advanced#experiments", textContent: t("more.compare") }),
    el("a", { href: "/advanced#review", textContent: t("more.safety") }),
    el("a", { href: "/advanced#history", textContent: t("more.history") }),
    el("a", { href: "/setup", textContent: t("more.setup") }));
  loadSettings();
  renderConsentControls();
}

/* ---------------------------------------------------------- preferences */

async function loadPreferences() {
  const root = $("prefs-list");
  let payload;
  try { payload = await api("/api/preferences"); }
  catch (error) { showError(error); return; }
  root.replaceChildren();

  if (!payload.preferences.length) {
    root.append(el("p", { className: "muted", textContent: t("prefs.empty") }));
    return;
  }
  for (const pref of payload.preferences) {
    const card = el("div", { className: `pref ${pref.active ? "" : "retired"}`.trim() },
      el("div", { className: "rule", textContent: pref.rule }));
    if (pref.reason) card.append(el("div", { className: "reason", textContent: `"${pref.reason}"` }));

    const meta = el("div", { className: "meta" },
      el("span", { className: `tag ${pref.strength}`,
                   textContent: t(`prefs.strength.${pref.strength}`).split("—")[0].trim() }));
    if (!pref.confirmed) meta.append(el("span", { className: "tag unconfirmed", textContent: t("prefs.confirm.title") }));
    if (pref.applied_count) meta.append(el("span", { textContent: t("prefs.applied", { n: pref.applied_count }) }));
    if (pref.active) {
      meta.append(el("button", {
        className: "quiet", textContent: t("prefs.remove"),
        onclick: async () => {
          try { await api("/api/preferences/change", { pref_id: pref.pref_id, action: "retire" }); loadPreferences(); }
          catch (error) { showError(error); }
        },
      }));
    }
    card.append(meta);
    root.append(card);
  }
}

$("add-pref").addEventListener("click", () => {
  const sheet = $("sheet");
  const rule = textField("pref-rule", t("prefs.rule"), t("prefs.rule.hint"), "");
  const reason = textField("pref-reason", t("prefs.reason"), t("prefs.reason.hint"), "");
  const strength = el("select", { id: "pref-strength" });
  for (const value of ["preference", "strong", "absolute"]) {
    strength.append(el("option", { value, textContent: t(`prefs.strength.${value}`) }));
  }
  sheet.replaceChildren(el("div", { style: "padding:26px" },
    el("h2", { textContent: t("prefs.add"), style: "margin-bottom:18px" }),
    rule.wrap, reason.wrap,
    el("div", { className: "field" },
      el("label", { htmlFor: "pref-strength", textContent: t("prefs.strength") }), strength),
    el("div", { className: "button-row end" },
      el("button", { textContent: t("common.cancel"), onclick: () => sheet.close() }),
      el("button", {
        className: "primary", textContent: t("common.save"),
        onclick: async () => {
          if (!rule.input.value.trim()) { rule.input.focus(); return; }
          try {
            await api("/api/preferences", {
              rule: rule.input.value, reason: reason.input.value, strength: strength.value,
            });
            sheet.close();
            loadPreferences();
          } catch (error) { showError(error); }
        },
      }))));
  sheet.showModal();
});

/* ------------------------------------------------------------------ undo */

const UNDO_SECONDS = 10;
let pending = null;

function commitPending() {
  if (!pending) return;
  const job = pending;
  pending = null;
  clearInterval(job.ticker);
  job.bar.remove();
  job.send().catch(showError);
}

function cancelPending() {
  if (!pending) return;
  clearInterval(pending.ticker);
  pending.bar.remove();
  pending.revert();
  pending = null;
}

function deferWithUndo({ label, send, revert }) {
  commitPending();
  const count = el("span", { className: "count" });
  const bar = el("div", { className: "undo-bar", role: "status" },
    el("span", { textContent: label }),
    el("button", { type: "button", textContent: t("common.undo"), onclick: cancelPending }),
    count);
  document.body.append(bar);

  let left = UNDO_SECONDS;
  count.textContent = `${left}s`;
  const ticker = setInterval(() => {
    left -= 1;
    count.textContent = `${left}s`;
    if (left <= 0) commitPending();
  }, 1000);
  pending = { send, revert, bar, ticker };
}

window.addEventListener("pagehide", commitPending);

/* -------------------------------------------------------------- decision */

function lockDecision(note) {
  $("decision-note").textContent = note;
  $("approve").disabled = true;
  $("keep-normal").disabled = true;
}

function unlockDecision() {
  state.decision = null;
  $("decision-note").textContent = "";
  $("approve").disabled = false;
  $("keep-normal").disabled = false;
}

$("approve").addEventListener("click", () => {
  if (!state.run) return;
  const run = state.run;
  state.decision = "approve";
  lockDecision(t("approved.note"));
  deferWithUndo({
    label: t("approved.note"),
    revert: unlockDecision,
    send: async () => {
      await api("/api/decision", {
        run_id: run.run_id, revision: run.revision,
        plan_hash: run.plan_hash, decision: "approve", comment: "",
      });
      resolveElicitation(dominantHeatSource(run.plan));
    },
  });
});

/* Keeping normal settings is a legitimate choice, not a failure. No warning
 * colour, no guilt, and it is confirmed rather than instant because it discards
 * the plan. */
$("keep-normal").addEventListener("click", () => {
  const sheet = $("sheet");
  sheet.replaceChildren(el("div", { style: "padding:26px" },
    el("h2", { textContent: t("btn.normal.confirm"), style: "margin-bottom:12px" }),
    el("p", { className: "muted", textContent: t("trust.normal_available") }),
    el("div", { className: "button-row end", style: "margin-top:22px" },
      el("button", { textContent: t("common.cancel"), onclick: () => sheet.close() }),
      el("button", {
        className: "primary", textContent: t("btn.normal.yes"),
        onclick: () => {
          sheet.close();
          state.decision = "normal";
          lockDecision(t("normal.note"));
          if (state.elicitation) resolveElicitation(state.elicitation.grower_choice);
          deferWithUndo({
            label: t("normal.note"), revert: unlockDecision,
            send: async () => {
              if (!state.run) return;
              await api("/api/decision", {
                run_id: state.run.run_id, revision: state.run.revision,
                plan_hash: state.run.plan_hash, decision: "reject",
                comment: "keep normal settings",
              });
            },
          });
        },
      }))));
  sheet.showModal();
});

/* --------------------------------------------------------- I have concerns */

/* The most valuable thing a grower gives us is the reason. A rejection without
 * one records that somebody disagreed and throws away what the study is for, so
 * this asks in prose and keeps the words verbatim.
 *
 * It works with no model configured: the objection is still stored, and only the
 * assistant's wording of a rule is skipped. */
function openObjectionSheet() {
  const sheet = $("sheet");
  const input = el("textarea", { rows: 4, id: "objection-text" });
  const status = el("p", { className: "muted small", role: "status" });

  const submit = el("button", {
    className: "primary", textContent: t("common.save"),
    onclick: async () => {
      const objection = input.value.trim();
      if (!objection) { input.focus(); return; }
      submit.disabled = true;
      status.textContent = t("chat.thinking");

      const runId = state.run ? state.run.run_id : "";
      try {
        const proposal = await api("/api/preferences/from-objection", {
          run_id: runId, objection,
          plan: state.run ? state.run.plan : [],
          metrics: state.run ? state.run.metrics : {},
          overrides: overrides(),
        });
        sheet.close();
        confirmPreference(proposal);
      } catch (error) {
        // No model is the ordinary first run. Keep the words rather than lose
        // them because an AI was not set up.
        try {
          await api("/api/preferences", {
            rule: objection.slice(0, 200), reason: objection,
            strength: "preference", source: "grower", run_id: runId,
          });
          sheet.close();
          noteConcernRecorded();
        } catch (inner) {
          status.textContent = String(inner.message || error.message);
        }
      } finally { submit.disabled = false; }
    },
  });

  sheet.replaceChildren(el("div", { style: "padding:26px" },
    el("h2", { textContent: t("chat.disagree"), style: "margin-bottom:8px" }),
    el("p", { className: "muted", textContent: t("chat.disagree.prompt"), style: "margin-bottom:16px" }),
    el("div", { className: "field" }, input),
    status,
    el("div", { className: "button-row end", style: "margin-top:16px" },
      el("button", { textContent: t("common.cancel"), onclick: () => sheet.close() }), submit)));
  sheet.showModal();
}

/* An inferred rule is shown before it binds. A model wording a standing
 * instruction and applying it unseen would be worse than having no memory. */
function confirmPreference(proposal) {
  const sheet = $("sheet");
  sheet.replaceChildren(el("div", { style: "padding:26px" },
    el("h2", { textContent: t("prefs.confirm.title"), style: "margin-bottom:12px" }),
    el("p", { textContent: proposal.restatement || proposal.rule, style: "margin-bottom:8px" }),
    el("p", { className: "muted small", textContent: proposal.rule }),
    el("div", { className: "button-row end", style: "margin-top:20px" },
      el("button", {
        textContent: t("prefs.confirm.no"),
        onclick: async () => {
          try { await api("/api/preferences/change", { pref_id: proposal.pref_id, action: "retire", reason: "declined" }); }
          catch { /* already gone */ }
          sheet.close();
          noteConcernRecorded();
        },
      }),
      el("button", {
        className: "primary", textContent: t("prefs.confirm.yes"),
        onclick: async () => {
          try { await api("/api/preferences/change", { pref_id: proposal.pref_id, action: "confirm" }); }
          catch (error) { showError(error); }
          sheet.close();
          noteConcernRecorded();
        },
      }))));
  sheet.showModal();
}

function noteConcernRecorded() {
  $("decision-note").textContent = t("plan.rejected");
  // Raising a concern is keeping their own position on what we asked about.
  if (state.elicitation) resolveElicitation(state.elicitation.grower_choice);
  recordEdits();
}

/* Any hour the grower changed, against what the planner chose. Pure arithmetic
 * server-side, so this is recorded even with no model configured. */
async function recordEdits() {
  if (!state.run || !state.editedPlan) return;
  try {
    await api("/api/conflicts", {
      run_id: state.run.run_id, revision: state.run.revision,
      original: state.run.plan, edited: state.editedPlan,
      reason: $("objection-text") ? $("objection-text").value.trim() : "",
    });
  } catch { /* measurement must never cost the grower their decision */ }
}

$("concerns").addEventListener("click", openObjectionSheet);

/* ------------------------------------------------- asking first (RQ1) */

const HEAT_OPTIONS = ["boiler", "chp", "mix"];

function dominantHeatSource(plan) {
  const counts = {};
  for (const row of plan || []) counts[row.heat_source] = (counts[row.heat_source] || 0) + 1;
  const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (!ranked.length) return "mix";
  const [top, count] = ranked[0];
  if (count < (plan.length || 1) * 0.6) return "mix";
  return HEAT_OPTIONS.includes(top) ? top : "mix";
}

function askBeforeReveal() {
  return new Promise((resolve) => {
    const sheet = $("sheet");
    let choice = "";
    let confidence = 0;

    const options = el("div", { className: "choice-list" });
    for (const value of HEAT_OPTIONS) {
      const input = el("input", { type: "radio", name: "elicit-heat", value });
      input.addEventListener("change", () => { choice = value; submit.disabled = !(choice && confidence); });
      options.append(el("label", { className: "choice-item" }, input,
        el("span", {}, el("span", { className: "title", textContent: t(`elicit.option.${value}`) }))));
    }

    const scale = el("div", { className: "choice-list" });
    for (let level = 1; level <= 5; level += 1) {
      const input = el("input", { type: "radio", name: "elicit-confidence", value: String(level) });
      input.addEventListener("change", () => { confidence = level; submit.disabled = !(choice && confidence); });
      scale.append(el("label", { className: "choice-item" }, input,
        el("span", {}, el("span", { className: "title", textContent: `${level} — ${t(`elicit.confidence.${level}`)}` }))));
    }

    const finish = (record) => {
      sheet.close();
      resolve(record && choice && confidence ? { choice, confidence } : null);
    };
    const submit = el("button", {
      className: "primary", textContent: t("elicit.submit"), disabled: true,
      onclick: () => finish(true),
    });

    sheet.replaceChildren(el("div", { style: "padding:26px" },
      el("h2", { textContent: t("elicit.title"), style: "margin-bottom:8px" }),
      el("p", { className: "muted small", textContent: t("elicit.why"), style: "margin-bottom:20px" }),
      el("div", { className: "field" }, el("label", { textContent: t("elicit.heat.question") }), options),
      el("div", { className: "field" }, el("label", { textContent: t("elicit.confidence") }), scale),
      el("div", { className: "button-row end" },
        el("button", { className: "quiet", textContent: t("elicit.skip"), onclick: () => finish(false) }),
        submit)));
    sheet.showModal();
  });
}

async function recordElicitation(answer, runId) {
  try {
    return await api("/api/elicit", {
      run_id: runId || "unsaved", question: "heat_source@day",
      grower_choice: answer.choice, confidence: answer.confidence,
      condition: state.settings.condition || "",
    });
  } catch { return null; }
}

async function revealToElicitation(result) {
  if (!state.elicitation) return;
  try {
    state.elicitation = await api("/api/elicit/step", {
      elicitation_id: state.elicitation.elicitation_id, action: "reveal",
      ai_choice: dominantHeatSource(result.plan),
      ai_confidence: (result.uncertainty && result.uncertainty.confidence) || "",
    });
  } catch { /* measurement must never cost the grower their plan */ }
}

async function resolveElicitation(finalChoice) {
  if (!state.elicitation || !state.elicitation.ai_choice) return;
  try {
    state.elicitation = await api("/api/elicit/step", {
      elicitation_id: state.elicitation.elicitation_id,
      action: "resolve", final_choice: finalChoice,
    });
  } catch { /* as above */ }
}

/* ------------------------------------------------------------- settings */

function textField(id, label, hint, value) {
  const input = el("input", { type: "text", id, value });
  const wrap = el("div", { className: "field" },
    el("label", { htmlFor: id, textContent: label }),
    hint ? el("p", { className: "hint", textContent: hint }) : null, input);
  return { wrap, input };
}

function numberField(id, label, hint, value, attrs = {}) {
  const input = Object.assign(el("input", { type: "number", id, value }), attrs);
  const wrap = el("div", { className: "field" },
    el("label", { htmlFor: id, textContent: label }),
    hint ? el("p", { className: "hint", textContent: hint }) : null, input);
  return { wrap, input };
}

async function loadSettings() {
  const root = $("model-settings");
  root.replaceChildren();
  let payload;
  try { payload = await api("/api/models"); }
  catch (error) { root.append(el("p", { className: "muted", textContent: String(error.message) })); return; }

  const select = el("select", { id: "provider-select" });
  for (const provider of payload.providers) {
    select.append(el("option", { value: provider.id,
      textContent: provider.name + (provider.configured ? "" : ` — ${t("settings.ai.key")}`) }));
  }
  select.value = state.settings.llm_provider || payload.selected.provider;
  const model = el("input", { type: "text", id: "model-name",
    value: state.settings.llm_model || payload.selected.model });
  select.addEventListener("change", () => {
    state.settings.llm_provider = select.value;
    const chosen = payload.providers.find((p) => p.id === select.value);
    if (chosen && chosen.models.length) { state.settings.llm_model = chosen.models[0]; model.value = chosen.models[0]; }
    LS.set("kasflex.grower.settings", state.settings);
  });
  model.addEventListener("change", () => {
    state.settings.llm_model = model.value.trim();
    LS.set("kasflex.grower.settings", state.settings);
  });

  const status = el("p", { className: "muted small", role: "status" });
  const test = el("button", {
    textContent: t("settings.ai.test"),
    onclick: async () => {
      test.disabled = true;
      status.textContent = t("common.loading");
      try {
        const result = await api("/api/models/test", { provider: select.value, model: model.value });
        status.textContent = `${result.ok ? "✓ " + t("settings.ai.ok") : "✕ " + t("settings.ai.failed")} — ${result.message}`;
      } catch (error) { status.textContent = String(error.message); }
      finally { test.disabled = false; }
    },
  });
  const key = el("input", { type: "password", id: "api-key", autocomplete: "off" });
  const saveKey = el("button", {
    textContent: t("common.save"),
    onclick: async () => {
      if (!key.value.trim()) return;
      try {
        await api("/api/connections", { provider: select.value, api_key: key.value.trim() });
        key.value = "";
        status.textContent = t("settings.ai.ok");
      } catch (error) { status.textContent = String(error.message); }
    },
  });

  root.append(
    el("div", { className: "field" }, el("label", { htmlFor: "provider-select", textContent: t("settings.ai.provider") }), select),
    el("div", { className: "field" }, el("label", { htmlFor: "model-name", textContent: t("settings.ai.model") }), model),
    el("div", { className: "field" }, el("label", { htmlFor: "api-key", textContent: t("settings.ai.key") }),
      el("div", { className: "button-row" }, key, saveKey)),
    el("div", { className: "button-row" }, test), status);

  const data = $("data-settings");
  data.replaceChildren();
  const list = el("div", { className: "choice-list" });
  for (const [value, label] of [["synthetic", t("settings.data.demo")], ["cache", t("settings.data.real")]]) {
    const input = el("input", { type: "radio", name: "data_source", value });
    input.checked = (state.settings.data_source || "synthetic") === value;
    input.addEventListener("change", () => {
      state.settings.data_source = value;
      LS.set("kasflex.grower.settings", state.settings);
    });
    list.append(el("label", { className: "choice-item" }, input,
      el("span", {}, el("span", { className: "title", textContent: label }))));
  }
  data.append(list);

  const profileRoot = $("profile-settings");
  profileRoot.replaceChildren();
  if (state.profile) {
    profileRoot.append(el("p", { textContent: t("onboard.profile.saved", { name: state.profile.name }) }));
    if (state.profile.profile_id) {
      profileRoot.append(el("p", { style: "margin-top:12px" },
        el("a", { href: `/api/profiles/export/${state.profile.profile_id}`,
                  download: "kasflex-setup.json", textContent: t("onboard.profile.export") })));
    }
  }
}

$("restart-onboarding").addEventListener("click", () => {
  LS.del("kasflex.grower.profile");
  LS.del("kasflex.grower.lastRun");
  showOnboarding(true);
});

/* -------------------------------------------------------------- consent */

/* The participant's own consent screen.
 *
 * The server gates recording on consent and the researcher console can see it,
 * but until now nobody ever asked the grower. A gate that cannot be satisfied is
 * not a safeguard, it is a broken study.
 *
 * Declining is a real option that costs nothing: the app works identically, and
 * only the research stores stay empty. Consent that is a condition of use is not
 * freely given. */
async function checkConsent() {
  let status;
  try {
    const params = new URLSearchParams();
    if (state.settings.participant_id) params.set("participant_id", state.settings.participant_id);
    status = await api(`/api/consent?${params}`);
  } catch { return; }

  state.consent = status;
  if (!status.study_active || !status.needs_consent) return;
  await askConsent(status);
}

function askConsent(status) {
  return new Promise((resolve) => {
    const sheet = $("sheet");
    const scopes = {};

    const list = el("div", { className: "choice-list" });
    for (const [key, description] of Object.entries(status.scopes || {})) {
      const input = el("input", { type: "checkbox", checked: true });
      scopes[key] = true;
      input.addEventListener("change", () => { scopes[key] = input.checked; });
      list.append(el("label", { className: "choice-item" }, input,
        el("span", {}, el("span", { className: "title", textContent: t(`consent.scope.${key}`) !== `consent.scope.${key}` ? t(`consent.scope.${key}`) : key }),
          el("span", { className: "desc", textContent: description }))));
    }

    const send = async (agreed) => {
      try {
        await api("/api/consent", {
          participant_id: status.participant_id, version: status.version,
          scopes: agreed ? scopes : {},
        });
      } catch (error) { showError(error); }
      sheet.close();
      resolve();
    };

    sheet.replaceChildren(el("div", { style: "padding:26px" },
      el("h2", { textContent: t("consent.title"), style: "margin-bottom:10px" }),
      el("p", { className: "muted", textContent: t("consent.intro"), style: "margin-bottom:18px" }),
      status.participant_id
        ? el("p", { className: "muted small", style: "margin-bottom:14px",
                    textContent: `${t("consent.who")}: ${status.participant_id}` })
        : null,
      el("p", { style: "font-weight:700;margin-bottom:10px", textContent: t("consent.what") }),
      list,
      el("p", { className: "muted small", textContent: t("consent.voluntary"), style: "margin-top:16px" }),
      el("div", { className: "button-row end", style: "margin-top:20px" },
        el("button", { textContent: t("consent.decline"), onclick: () => send(false) }),
        el("button", { className: "primary", textContent: t("consent.agree"), onclick: () => send(true) }))));
    sheet.showModal();
  });
}

/* Withdrawal has to be reachable without asking anyone, so it lives on More. */
function renderConsentControls() {
  const root = $("consent-settings");
  if (!root) return;
  root.replaceChildren();
  const status = state.consent;
  if (!status || !status.study_active) {
    root.append(el("p", { className: "muted", textContent: t("sim.note") }));
    return;
  }

  const taking = status.current && status.current.active && status.current.scopes
    && status.current.scopes.research;
  root.append(el("p", { textContent: t(taking ? "consent.active" : "consent.inactive") }));

  if (taking) {
    root.append(el("div", { className: "button-row", style: "margin-top:14px" },
      el("button", {
        className: "danger", textContent: t("consent.withdraw"),
        onclick: async () => {
          try {
            await api("/api/consent/withdraw", { participant_id: status.participant_id });
            root.replaceChildren(el("p", { textContent: t("consent.withdrawn") }));
            state.consent = await api("/api/consent");
          } catch (error) { showError(error); }
        },
      })));
  }
}

/* ----------------------------------------------------------- onboarding */

const ONBOARDING_STEPS = ["language", "site", "equipment", "ai", "done"];
let onboardingStep = 0;
let onboardingDraft = {};

const needsOnboarding = () => !LS.get("kasflex.grower.profile");

function showOnboarding(fromStart = true) {
  if (fromStart) { onboardingStep = -1; onboardingDraft = { equipment: {}, settings: {} }; }
  $("onboarding").hidden = false;
  renderOnboarding();
}

function finishOnboarding() { $("onboarding").hidden = true; clearError(); }

function renderOnboarding() {
  const body = $("step-body");
  const actions = $("step-actions");
  body.replaceChildren();
  actions.replaceChildren();
  if (onboardingStep < 0) return renderWelcome(body, actions);

  const progress = $("progress");
  progress.hidden = false;
  progress.replaceChildren(...ONBOARDING_STEPS.map((_, i) =>
    el("span", { className: i <= onboardingStep ? "done" : "" })));
  const label = $("step-label");
  label.hidden = false;
  label.textContent = t("onboard.step", { n: onboardingStep + 1, total: ONBOARDING_STEPS.length });

  ({ language: stepLanguage, site: stepSite, equipment: stepEquipment,
     ai: stepAi, done: stepDone })[ONBOARDING_STEPS[onboardingStep]](body, actions);
}

function renderWelcome(body, actions) {
  $("progress").hidden = true;
  $("step-label").hidden = true;
  body.append(el("h1", { textContent: t("onboard.welcome.title") }),
    el("p", { className: "lede", textContent: t("onboard.welcome.body") }));
  actions.append(
    el("button", { className: "primary", textContent: t("onboard.welcome.start"),
      onclick: () => { onboardingStep = 0; renderOnboarding(); } }),
    el("button", { textContent: t("onboard.welcome.load"), onclick: renderProfilePicker }),
    el("button", { className: "quiet", textContent: t("onboard.welcome.demo"),
      onclick: () => { saveProfileLocally({ name: "Demo", settings: { data_source: "synthetic" } }); finishOnboarding(); } }));
}

async function renderProfilePicker() {
  const body = $("step-body");
  const actions = $("step-actions");
  body.replaceChildren(el("h1", { textContent: t("onboard.profile.pick") }));
  actions.replaceChildren();

  let profiles = [];
  try { profiles = (await api("/api/profiles")).profiles; } catch { /* file import still works */ }
  if (!profiles.length) body.append(el("p", { className: "lede", textContent: t("onboard.profile.none") }));

  for (const profile of profiles) {
    body.append(el("div", { className: "profile-item" },
      el("div", { className: "grow" },
        el("div", { className: "name", textContent: profile.name }),
        el("div", { className: "when", textContent: (profile.updated_at || "").slice(0, 10) })),
      el("button", { textContent: t("common.next"),
        onclick: () => {
          state.settings = { ...profile.settings };
          saveProfileLocally(profile);
          if (profile.language) loadLanguage(profile.language).then(renderCurrentView);
          finishOnboarding();
        } })));
  }

  const picker = el("input", { type: "file", accept: "application/json,.json", hidden: true });
  picker.addEventListener("change", async () => {
    const file = picker.files && picker.files[0];
    if (!file) return;
    try {
      const profile = await api("/api/profiles/import", { text: await file.text() });
      state.settings = { ...profile.settings };
      saveProfileLocally(profile);
      finishOnboarding();
    } catch (error) {
      body.prepend(el("div", { className: "error", textContent: String(error.message || error) }));
    }
  });
  body.append(picker);
  actions.append(
    el("button", { className: "primary", textContent: t("onboard.profile.import"), onclick: () => picker.click() }),
    el("button", { className: "quiet", textContent: t("common.back"),
      onclick: () => { onboardingStep = -1; renderOnboarding(); } }));
}

function stepLanguage(body, actions) {
  body.append(el("h1", { textContent: t("onboard.language.title") }),
    el("p", { className: "lede", textContent: t("onboard.language.body") }));
  const list = el("div", { className: "choice-list" });
  for (const language of state.languages) {
    const input = el("input", { type: "radio", name: "lang", value: language.code });
    input.checked = language.code === state.lang;
    input.addEventListener("change", async () => {
      await loadLanguage(language.code);
      onboardingDraft.language = language.code;
      renderOnboarding();
    });
    list.append(el("label", { className: "choice-item" }, input,
      el("span", {}, el("span", { className: "title", textContent: language.endonym }))));
  }
  body.append(list);
  actions.append(nextButton(), backButton(() => { onboardingStep = -1; }));
}

function stepSite(body, actions) {
  body.append(el("h1", { textContent: t("onboard.site.title") }));
  const name = textField("site-name-in", t("onboard.site.name"), t("onboard.site.name.hint"), onboardingDraft.name || "");
  const area = numberField("site-area", t("onboard.site.area"), t("onboard.site.area.hint"),
    onboardingDraft.area ?? 5, { min: 0.01, max: 20, step: 0.01 });
  const lat = numberField("site-lat", t("onboard.site.location"), t("onboard.site.location.hint"),
    onboardingDraft.latitude ?? 51.99, { min: -90, max: 90, step: 0.001 });
  body.append(name.wrap, area.wrap, lat.wrap);
  actions.append(nextButton(() => {
    if (!name.input.value.trim()) { name.input.focus(); return false; }
    const hectares = Number(area.input.value);
    if (!(hectares > 0)) { area.input.focus(); return false; }
    onboardingDraft.name = name.input.value.trim();
    onboardingDraft.area = hectares;
    onboardingDraft.latitude = Number(lat.input.value);
    onboardingDraft.settings["hub.floor_area_m2"] = Math.round(hectares * 10000);
    onboardingDraft.settings.latitude = Number(lat.input.value);
    return true;
  }), backButton());
}

function stepEquipment(body, actions) {
  body.append(el("h1", { textContent: t("onboard.equipment.title") }),
    el("p", { className: "lede", textContent: t("onboard.equipment.body") }));
  const list = el("div", { className: "choice-list" });
  for (const key of ["chp", "boiler", "battery", "buffer", "lights", "pv"]) {
    const input = el("input", { type: "checkbox" });
    input.checked = onboardingDraft.equipment[key] !== false;
    input.addEventListener("change", () => { onboardingDraft.equipment[key] = input.checked; });
    onboardingDraft.equipment[key] = input.checked;
    list.append(el("label", { className: "choice-item" }, input,
      el("span", {}, el("span", { className: "title", textContent: t(`onboard.equipment.${key}`) }))));
  }
  body.append(list);
  actions.append(nextButton(), backButton());
}

function stepAi(body, actions) {
  body.append(el("h1", { textContent: t("onboard.ai.title") }),
    el("p", { className: "lede", textContent: t("onboard.ai.body") }));
  const list = el("div", { className: "choice-list" });
  api("/api/models").then(({ providers }) => {
    for (const provider of providers) {
      const input = el("input", { type: "radio", name: "provider", value: provider.id });
      input.checked = provider.id === (onboardingDraft.settings.llm_provider || "");
      input.addEventListener("change", () => {
        onboardingDraft.settings.llm_provider = provider.id;
        if (provider.models.length) onboardingDraft.settings.llm_model = provider.models[0];
      });
      const title = el("span", { className: "title", textContent: provider.name });
      if (provider.local) title.append(el("span", { className: "badge-local", textContent: t("onboard.ai.local.badge") }));
      list.append(el("label", { className: "choice-item" }, input,
        el("span", {}, title, el("span", { className: "desc", textContent: provider.purpose }))));
    }
  }).catch(() => {});
  body.append(list);
  actions.append(nextButton(), el("button", { className: "quiet", textContent: t("onboard.ai.skip"),
    onclick: () => { onboardingStep += 1; renderOnboarding(); } }), backButton());
}

function stepDone(body, actions) {
  body.append(el("h1", { textContent: t("onboard.done.title") }),
    el("p", { className: "lede", textContent: t("onboard.done.body") }));
  actions.append(el("button", {
    className: "primary", textContent: t("onboard.done.cta"),
    onclick: async () => {
      const payload = {
        name: onboardingDraft.name || "My greenhouse",
        language: state.lang,
        settings: { ...onboardingDraft.settings, language: state.lang },
        equipment: onboardingDraft.equipment,
      };
      try { saveProfileLocally(await api("/api/profiles", payload)); }
      catch { saveProfileLocally(payload); }
      state.settings = { ...payload.settings };
      finishOnboarding();
      runPlan();
    },
  }));
}

function saveProfileLocally(profile) {
  state.profile = profile;
  LS.set("kasflex.grower.profile", profile);
  LS.set("kasflex.grower.settings", profile.settings || {});
  $("site-name").textContent = profile.name || "Greenhouse";
}

function nextButton(validate) {
  return el("button", { className: "primary", textContent: t("common.next"),
    onclick: () => { if (validate && validate() === false) return; onboardingStep += 1; renderOnboarding(); } });
}

function backButton(before) {
  return el("button", { className: "quiet", textContent: t("common.back"),
    onclick: () => { if (before) before(); else onboardingStep -= 1; renderOnboarding(); } });
}

/* ----------------------------------------------------------- navigation */

const VIEWS = ["tomorrow", "plan", "goals", "results", "more"];
let currentView = "tomorrow";

function navigate(view) {
  if (!VIEWS.includes(view)) view = "tomorrow";
  // Setting the hash below fires hashchange, which lands back here. Without this
  // guard every view renders twice and overlapping loaders each append a copy.
  if (view === currentView && location.hash.slice(1) === view) return;
  currentView = view;
  for (const name of VIEWS) $(`view-${name}`).hidden = name !== view;
  for (const button of document.querySelectorAll("[data-view]")) {
    const active = button.dataset.view === view;
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  location.hash = view;
  renderCurrentView();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function renderCurrentView() {
  if (currentView === "goals") renderGoals();
  else if (currentView === "results") renderResults();
  else if (currentView === "more") renderMore();
  else if (currentView === "plan") renderPlanScreen(state.run);
  else renderTiles(state.run);
}

for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => navigate(button.dataset.view));
}
window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));

/* ----------------------------------------------------------------- boot */

async function boot() {
  state.profile = LS.get("kasflex.grower.profile");
  state.settings = LS.get("kasflex.grower.settings", {}) || {};
  if (state.profile) $("site-name").textContent = state.profile.name || "Greenhouse";

  try { await loadLanguage(state.settings.language || navigator.language || "en"); }
  catch (error) { showError(error); return; }

  try {
    const settings = await api("/api/settings");
    state.adjustable = new Set(settings.fields.map((f) => f.path));
  } catch { state.adjustable = new Set(["language"]); }

  const saved = LS.get("kasflex.grower.lastRun");
  if (saved && saved.plan) {
    state.run = saved;
    state.editedPlan = saved.plan.map((row) => ({ ...row }));
    renderTomorrow(saved);
    $("tomorrow-empty").hidden = true;
    $("tomorrow-result").hidden = false;
  } else {
    renderTiles(null);
  }

  navigate(location.hash.slice(1) || "tomorrow");
  if (needsOnboarding()) showOnboarding(true);
  else await checkConsent();
}

boot();
