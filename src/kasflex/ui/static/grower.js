/* KasFlex grower interface.
 *
 * Vanilla JS, no build step, matching the rest of the project. Three habits
 * throughout, each for a reason:
 *
 * - Every visible string comes from the server's catalogue via t(). Hard-coding
 *   English here is how a Dutch screen ends up half translated.
 * - Text goes in through textContent, never innerHTML. Plan reasoning and the
 *   assistant's answers are model output, and model output is data.
 * - Anything that can fail says what to do about it. "Request failed" is not an
 *   error message for someone who did not want to use a computer today.
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
  fields: [],
  profile: null,
  run: null,
  originalPlan: null,
  decision: null,
  elicitation: null,
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

/* ------------------------------------------------------------------ api */

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error(t("common.error"));
  }
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch { /* non-JSON body */ }
  if (!response.ok) throw new Error(payload.error || t("common.error"));
  return payload;
}

function showError(message) {
  const box = $("error");
  box.textContent = String(message && message.message ? message.message : message);
  box.hidden = false;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
const clearError = () => { $("error").hidden = true; };

/* ------------------------------------------------------------- language */

function applyStrings() {
  document.documentElement.lang = state.lang;
  for (const node of document.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
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
  const code = event.target.value;
  await loadLanguage(code);
  state.settings.language = code;
  LS.set("kasflex.grower.settings", state.settings);
  if (state.run) renderPlan(state.run);
  renderCurrentView();
});

/* ------------------------------------------------- overrides for the API */

function overrides() {
  const out = { language: state.lang };
  for (const [key, value] of Object.entries(state.settings)) {
    if (value !== null && value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

/* ----------------------------------------------------------- onboarding */

const ONBOARDING_STEPS = ["language", "site", "equipment", "ai", "done"];
let onboardingStep = 0;
let onboardingDraft = {};

function needsOnboarding() {
  return !LS.get("kasflex.grower.profile");
}

function showOnboarding(fromStart = true) {
  if (fromStart) { onboardingStep = -1; onboardingDraft = { equipment: {}, settings: {} }; }
  $("onboarding").hidden = false;
  renderOnboarding();
}

function finishOnboarding() {
  $("onboarding").hidden = true;
  clearError();
}

function renderOnboarding() {
  const body = $("step-body");
  const actions = $("step-actions");
  body.replaceChildren();
  actions.replaceChildren();

  if (onboardingStep < 0) return renderWelcome(body, actions);

  const total = ONBOARDING_STEPS.length;
  const progress = $("progress");
  progress.hidden = false;
  progress.replaceChildren(...ONBOARDING_STEPS.map((_, i) =>
    el("span", { className: i <= onboardingStep ? "done" : "" })));
  const label = $("step-label");
  label.hidden = false;
  label.textContent = t("onboard.step", { n: onboardingStep + 1, total });

  const renderers = { language: stepLanguage, site: stepSite, equipment: stepEquipment, ai: stepAi, done: stepDone };
  renderers[ONBOARDING_STEPS[onboardingStep]](body, actions);
}

function renderWelcome(body, actions) {
  $("progress").hidden = true;
  $("step-label").hidden = true;
  body.append(
    el("h1", { textContent: t("onboard.welcome.title") }),
    el("p", { className: "lede", textContent: t("onboard.welcome.body") }),
  );
  actions.append(
    el("button", {
      className: "primary big", textContent: t("onboard.welcome.start"),
      onclick: () => { onboardingStep = 0; renderOnboarding(); },
    }),
    el("button", {
      className: "big", textContent: t("onboard.welcome.load"),
      onclick: renderProfilePicker,
    }),
    el("button", {
      className: "quiet", textContent: t("onboard.welcome.demo"),
      onclick: () => { saveProfileLocally({ name: "Demo", settings: { data_source: "synthetic" } }); finishOnboarding(); },
    }),
  );
}

async function renderProfilePicker() {
  const body = $("step-body");
  const actions = $("step-actions");
  body.replaceChildren(el("h1", { textContent: t("onboard.profile.pick") }));
  actions.replaceChildren();

  let profiles = [];
  try { profiles = (await api("/api/profiles")).profiles; } catch { /* offline: file import still works */ }

  if (!profiles.length) {
    body.append(el("p", { className: "lede", textContent: t("onboard.profile.none") }));
  }
  for (const profile of profiles) {
    body.append(el("div", { className: "profile-item" },
      el("div", { className: "grow" },
        el("div", { className: "name", textContent: profile.name }),
        el("div", { className: "when", textContent: (profile.updated_at || "").slice(0, 10) })),
      el("button", {
        textContent: t("common.next"),
        onclick: () => {
          state.settings = { ...profile.settings };
          saveProfileLocally(profile);
          if (profile.language) loadLanguage(profile.language).then(renderCurrentView);
          finishOnboarding();
          refreshAll();
        },
      })));
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
      refreshAll();
    } catch (error) { showErrorInOnboarding(error); }
  });
  body.append(picker);

  actions.append(
    el("button", { className: "primary", textContent: t("onboard.profile.import"), onclick: () => picker.click() }),
    el("button", { className: "quiet", textContent: t("common.back"), onclick: () => { onboardingStep = -1; renderOnboarding(); } }),
  );
}

function showErrorInOnboarding(error) {
  const body = $("step-body");
  const existing = body.querySelector(".error");
  if (existing) existing.remove();
  body.prepend(el("div", { className: "error", textContent: String(error.message || error) }));
}

function stepLanguage(body, actions) {
  body.append(
    el("h1", { textContent: t("onboard.language.title") }),
    el("p", { className: "lede", textContent: t("onboard.language.body") }),
  );
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
  const name = textField("site-name", t("onboard.site.name"), t("onboard.site.name.hint"), onboardingDraft.name || "");
  const area = numberField("site-area", t("onboard.site.area"), t("onboard.site.area.hint"),
    onboardingDraft.area != null ? onboardingDraft.area : 5, { min: 0.01, max: 20, step: 0.01 });
  const lat = numberField("site-lat", t("onboard.site.location"), t("onboard.site.location.hint"),
    onboardingDraft.latitude != null ? onboardingDraft.latitude : 51.99, { min: -90, max: 90, step: 0.001 });
  body.append(name.wrap, area.wrap, lat.wrap);

  actions.append(nextButton(() => {
    const label = name.input.value.trim();
    if (!label) { name.input.focus(); return false; }
    const hectares = Number(area.input.value);
    if (!(hectares > 0)) { area.input.focus(); return false; }
    onboardingDraft.name = label;
    onboardingDraft.area = hectares;
    onboardingDraft.latitude = Number(lat.input.value);
    onboardingDraft.settings["hub.floor_area_m2"] = Math.round(hectares * 10000);
    onboardingDraft.settings.latitude = Number(lat.input.value);
    return true;
  }), backButton());
}

function stepEquipment(body, actions) {
  body.append(
    el("h1", { textContent: t("onboard.equipment.title") }),
    el("p", { className: "lede", textContent: t("onboard.equipment.body") }),
  );
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
  body.append(
    el("h1", { textContent: t("onboard.ai.title") }),
    el("p", { className: "lede", textContent: t("onboard.ai.body") }),
  );
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
  }).catch(() => { /* the step is skippable; a model is not required to plan */ });
  body.append(list);

  actions.append(nextButton(), el("button", {
    className: "quiet", textContent: t("onboard.ai.skip"),
    onclick: () => { onboardingStep += 1; renderOnboarding(); },
  }), backButton());
}

function stepDone(body, actions) {
  body.append(
    el("h1", { textContent: t("onboard.done.title") }),
    el("p", { className: "lede", textContent: t("onboard.done.body") }),
  );
  actions.append(el("button", {
    className: "primary big", textContent: t("onboard.done.cta"),
    onclick: async () => {
      const payload = {
        name: onboardingDraft.name || "My greenhouse",
        language: state.lang,
        settings: { ...onboardingDraft.settings, language: state.lang },
        equipment: onboardingDraft.equipment,
      };
      try {
        const profile = await api("/api/profiles", payload);
        saveProfileLocally(profile);
      } catch {
        saveProfileLocally(payload);   // a failed save must not trap the grower here
      }
      state.settings = { ...payload.settings };
      finishOnboarding();
      refreshAll();
      runPlan();
    },
  }));
}

function saveProfileLocally(profile) {
  state.profile = profile;
  LS.set("kasflex.grower.profile", profile);
  LS.set("kasflex.grower.settings", profile.settings || {});
}

function nextButton(validate) {
  return el("button", {
    className: "primary", textContent: t("common.next"),
    onclick: () => {
      if (validate && validate() === false) return;
      onboardingStep += 1;
      renderOnboarding();
    },
  });
}

function backButton(before) {
  return el("button", {
    className: "quiet", textContent: t("common.back"),
    onclick: () => { if (before) before(); else onboardingStep -= 1; renderOnboarding(); },
  });
}

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

/* ------------------------------------------------------------ the plan */

async function runPlan() {
  if (state.busy) return;
  state.busy = true;
  clearError();
  $("today-empty").hidden = true;
  $("today-result").hidden = true;
  $("today-loading").hidden = false;
  try {
    // The request goes out first and runs while the grower answers, so the wait
    // happens behind the question instead of in front of it. Asking afterwards
    // would measure nothing anyway -- by then the answer is the plan's answer.
    const pendingRun = api("/api/run", { overrides: overrides() });
    pendingRun.catch(() => {});   // handled below; this only silences the race

    let answer = null;
    if (state.settings.ask_first !== false) {
      $("today-loading").hidden = true;
      answer = await askBeforeReveal();
      $("today-loading").hidden = false;
    }

    const result = await pendingRun;
    state.run = result;
    state.originalPlan = (result.plan || []).map((row) => ({ ...row }));
    state.decision = null;
    LS.set("kasflex.grower.lastRun", result);

    // Posted now rather than when it was typed, because only now is there a
    // run to attach it to. The ordering that matters is still intact: the
    // answer was given, and the reveal below happens strictly after it.
    state.elicitation = answer ? await recordElicitation(answer, result.run_id) : null;

    renderPlan(result);
    $("today-result").hidden = false;
    await revealToElicitation(result);
  } catch (error) {
    showError(error);
    $("today-empty").hidden = false;
  } finally {
    $("today-loading").hidden = true;
    state.busy = false;
  }
}

/* --------------------------------------------------- asking first (RQ1) */

const HEAT_OPTIONS = ["boiler", "chp", "mix"];

/** The plan's dominant heat source, so the comparison is like for like. */
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

    const scale = el("div", { className: "confidence-scale" });
    for (let level = 1; level <= 5; level += 1) {
      const input = el("input", { type: "radio", name: "elicit-confidence", value: String(level) });
      input.addEventListener("change", () => { confidence = level; submit.disabled = !(choice && confidence); });
      scale.append(el("label", {}, input,
        el("span", { textContent: `${level} — ${t(`elicit.confidence.${level}`)}` })));
    }

    const finish = (record) => {
      sheet.close();
      resolve(record && choice && confidence ? { choice, confidence } : null);
    };

    const submit = el("button", {
      className: "primary", textContent: t("elicit.submit"), disabled: true,
      onclick: () => finish(true),
    });

    sheet.replaceChildren(el("div", { style: "padding:24px;max-width:520px" },
      el("h2", { textContent: t("elicit.title"), style: "margin-bottom:8px" }),
      el("p", { className: "muted small", textContent: t("elicit.why"), style: "margin-bottom:18px" }),
      el("div", { className: "field" },
        el("label", { textContent: t("elicit.heat.question") }), options),
      el("div", { className: "field" },
        el("label", { textContent: t("elicit.confidence") }), scale),
      el("div", { className: "button-row end" },
        el("button", { className: "quiet", textContent: t("elicit.skip"), onclick: () => finish(false) }),
        submit)));
    sheet.showModal();
  });
}

/** Store the answer against the run it belongs to. Never blocks the plan. */
async function recordElicitation(answer, runId) {
  try {
    return await api("/api/elicit", {
      run_id: runId || "unsaved", question: "heat_source@day",
      grower_choice: answer.choice, confidence: answer.confidence,
      condition: state.settings.condition || "",
    });
  } catch {
    return null;   // measurement failing must never cost the grower their plan
  }
}

/** Record what the planner chose, at the moment the grower sees it. */
async function revealToElicitation(result) {
  if (!state.elicitation) return;
  const theirs = dominantHeatSource(result.plan);
  try {
    state.elicitation = await api("/api/elicit/step", {
      elicitation_id: state.elicitation.elicitation_id, action: "reveal",
      ai_choice: theirs,
      ai_confidence: (result.uncertainty && result.uncertainty.confidence) || "",
    });
  } catch { return; }

  const recap = $("elicit-recap");
  const mine = state.elicitation.grower_choice;
  $("elicit-recap-text").textContent = mine === theirs
    ? t("elicit.agreed")
    : t("elicit.differed", { yours: t(`elicit.option.${mine}`), theirs: t(`elicit.option.${theirs}`) });
  recap.hidden = false;
}

/** Close the loop when the grower commits, so reliance can be classified. */
async function resolveElicitation(finalChoice) {
  if (!state.elicitation || !state.elicitation.ai_choice) return;
  try {
    state.elicitation = await api("/api/elicit/step", {
      elicitation_id: state.elicitation.elicitation_id,
      action: "resolve", final_choice: finalChoice,
    });
  } catch { /* measurement must never block the decision itself */ }
}

function money(value) {
  const whole = Math.round(Math.abs(Number(value) || 0)).toLocaleString(state.lang === "nl" ? "nl-NL" : "en-GB");
  return (Number(value) < 0 ? "-" : "") + (state.lang === "nl" ? `€ ${whole}` : `€${whole}`);
}

const hourLabel = (hour) => state.lang === "nl"
  ? `${String(hour).padStart(2, "0")}.00 uur`
  : `${String(hour).padStart(2, "0")}:00`;

function setSignal(node, level, value) {
  node.className = `signal ${level}`;
  node.querySelector(".icon").textContent = level === "good" ? "✓" : level === "warn" ? "!" : "✕";
  node.querySelector(".value").textContent = value;
}

function renderPlan(result) {
  const metrics = result.metrics || {};
  $("headline-cost").textContent = money(metrics.net_cost_eur);
  $("headline-date").textContent = result.date || "";
  $("data-basis").textContent = result.data_source === "cache"
    ? t("plan.real_notice") : t("plan.demo_notice");

  const band = Number(metrics.temperature_band_hours);
  const cropLevel = !Number.isFinite(band) ? "warn" : band >= 22 ? "good" : band >= 18 ? "warn" : "bad";
  setSignal($("signal-crop"), cropLevel,
    t(cropLevel === "good" ? "plan.crop.good" : cropLevel === "warn" ? "plan.crop.warning" : "plan.crop.bad"));

  const safe = result.checker_enabled && result.accepted && !result.realised_hard;
  setSignal($("signal-safety"), safe ? "good" : "bad",
    t(safe ? "plan.safety.ok" : "plan.safety.bad"));

  // Cleared here, refilled by revealToElicitation. Otherwise a recap from the
  // previous run survives into a plan it does not describe.
  $("elicit-recap").hidden = true;
  $("elicit-recap-text").textContent = "";

  renderUncertainty(result.uncertainty);
  renderStory(result.plan || []);
  renderHours(result.plan || []);

  $("approve").disabled = false;
  $("concerns").disabled = false;
  $("decision-note").textContent = "";
  renderChatSuggestions();
}

/* The server decides whether a range is defensible. The interface's job is to
 * honour that answer, including when the answer is "I can't tell you" -- an
 * invented band looks exactly like a real one, which is why this never
 * substitutes a friendlier message of its own. */
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
  for (const caveat of uncertainty.caveats || []) {
    caveats.append(el("li", { textContent: caveat }));
  }
}

/* Group consecutive hours that share a mode into readable chapters. Twenty-four
 * rows is a table; four or five phases is a story someone will actually read. */
function renderStory(plan) {
  const root = $("story");
  root.replaceChildren();
  if (!plan.length) return;

  const key = (row) => `${row.heat_source}|${row.battery}|${Math.round((row.lighting_level || 0) * 4)}`;
  const phases = [];
  for (const row of plan) {
    const last = phases[phases.length - 1];
    if (last && key(last.rows[0]) === key(row)) last.rows.push(row);
    else phases.push({ rows: [row] });
  }

  for (const phase of phases) {
    const first = phase.rows[0];
    const last = phase.rows[phase.rows.length - 1];
    const when = phase.rows.length === 1
      ? hourLabel(first.hour)
      : `${hourLabel(first.hour)}–${hourLabel(last.hour)}`;

    const parts = [];
    const heat = { chp: t("asset.chp"), boiler: t("asset.boiler"), buffer: t("asset.buffer") }[first.heat_source];
    if (heat) parts.push(state.lang === "nl" ? `Warmte van de ${heat}` : `Heat from the ${heat}`);
    const lights = Math.round((first.lighting_level || 0) * 100);
    if (lights > 0) parts.push(state.lang === "nl" ? `${t("asset.lights")} op ${lights}%` : `${t("asset.lights")} at ${lights}%`);
    if (first.battery === "charge") parts.push(t("action.charge"));
    else if (first.battery === "discharge") parts.push(t("action.discharge"));

    // Scan anchors: a grower looking for "when does the CHP run" finds it by
    // shape, then reads the line. The words still carry the meaning.
    const marks = [];
    if (first.heat_source === "chp") marks.push("⚙");
    else if (first.heat_source === "boiler") marks.push("🔥");
    else if (first.heat_source === "buffer") marks.push("♨");
    if ((first.lighting_level || 0) > 0) marks.push("💡");
    if (first.battery === "charge") marks.push("🔌");
    else if (first.battery === "discharge") marks.push("🔋");

    const average = phase.rows.reduce((sum, r) => sum + (r.power_price_eur_kwh || 0), 0) / phase.rows.length;
    const priceWord = state.lang === "nl"
      ? `Gemiddelde ${t("term.price")}: € ${average.toFixed(3).replace(".", ",")}/kWh`
      : `Average ${t("term.price")}: €${average.toFixed(3)}/kWh`;

    root.append(el("div", { className: "chapter" },
      el("div", { className: "marks", "aria-hidden": "true", textContent: marks.join("") }),
      el("div", { className: "when", textContent: when }),
      el("div", {},
        el("div", { className: "what", textContent: parts.join(" · ") || t("action.idle") }),
        el("div", { className: "why", textContent: priceWord }))));
  }
}

function renderHours(plan) {
  const body = $("hours-body");
  body.replaceChildren();
  for (const row of plan) {
    const battery = row.battery === "charge" ? t("action.charge")
      : row.battery === "discharge" ? t("action.discharge") : t("action.idle");
    body.append(el("tr", {},
      el("td", { textContent: hourLabel(row.hour) }),
      el("td", { textContent: `€${(row.power_price_eur_kwh || 0).toFixed(3)}` }),
      el("td", { textContent: t(`asset.${row.heat_source}`) !== `asset.${row.heat_source}` ? t(`asset.${row.heat_source}`) : (row.heat_source || "—") }),
      el("td", { textContent: `${Math.round((row.lighting_level || 0) * 100)}%` }),
      el("td", { textContent: battery })));
  }
}

$("make-plan").addEventListener("click", runPlan);
$("remake-plan").addEventListener("click", runPlan);

/* ------------------------------------------------------------- decision */

/* ------------------------------------------------------------------ undo */

/* A decision is shown as done immediately and sent after a delay, during which
 * it can be taken back. The alternative -- a confirm dialog before every action
 * -- makes the common case slower to protect against the rare one, and people
 * learn to dismiss it without reading.
 *
 * The send also fires on page hide, so closing the tab commits rather than
 * silently dropping the decision. */
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

/* --------------------------------------------------------------- decision */

function lockDecision(noteKey) {
  $("decision-note").textContent = t(noteKey);
  $("approve").disabled = true;
  $("concerns").disabled = true;
}

function unlockDecision() {
  state.decision = null;
  $("decision-note").textContent = "";
  $("approve").disabled = false;
  $("concerns").disabled = false;
}

$("approve").addEventListener("click", () => {
  if (!state.run) return;
  const run = state.run;
  state.decision = "approve";
  lockDecision("plan.approved");

  deferWithUndo({
    label: t("plan.approved"),
    revert: unlockDecision,
    send: async () => {
      await api("/api/decision", {
        run_id: run.run_id, revision: run.revision,
        plan_hash: run.plan_hash, decision: "approve", comment: "",
      });
      // Approving is going with the planner, whatever they said beforehand.
      resolveElicitation(dominantHeatSource(run.plan));
    },
  });
});

$("concerns").addEventListener("click", () => {
  // Raising a concern is keeping their own position on the decision we asked about.
  if (state.elicitation) resolveElicitation(state.elicitation.grower_choice);
  openObjectionSheet();
});

/* A concern is the most valuable thing a grower gives us, so the sheet asks for
 * prose rather than a rating, and offers to remember it afterwards. */
function openObjectionSheet() {
  const sheet = $("sheet");
  const input = el("textarea", { rows: 4, id: "objection-text" });
  const status = el("p", { className: "small muted", role: "status" });

  const submit = el("button", {
    className: "primary", textContent: t("common.save"),
    onclick: async () => {
      const objection = input.value.trim();
      if (!objection) { input.focus(); return; }
      submit.disabled = true;
      status.textContent = t("chat.thinking");
      try {
        const proposal = await api("/api/preferences/from-objection", {
          run_id: state.run ? state.run.run_id : "", objection,
          plan: state.run ? state.run.plan : [], metrics: state.run ? state.run.metrics : {},
          overrides: overrides(),
        });
        sheet.close();
        confirmPreference(proposal);
      } catch (error) {
        // No model configured is the common case; record the objection anyway so
        // the reason is never lost just because an AI was not set up.
        try {
          await api("/api/preferences", {
            rule: objection.slice(0, 200), reason: objection,
            strength: "preference", source: "grower",
            run_id: state.run ? state.run.run_id : "",
          });
          sheet.close();
          state.decision = "reject";
          $("decision-note").textContent = t("plan.rejected");
          loadPreferences();
        } catch (inner) { status.textContent = String(inner.message || error.message); }
      } finally { submit.disabled = false; }
    },
  });

  sheet.replaceChildren(el("div", { style: "padding:24px;max-width:520px" },
    el("h2", { textContent: t("chat.disagree"), style: "margin-bottom:8px" }),
    el("p", { className: "muted small", textContent: t("chat.disagree.prompt"), style: "margin-bottom:14px" }),
    el("div", { className: "field" }, input),
    status,
    el("div", { className: "button-row end", style: "margin-top:14px" },
      el("button", { textContent: t("common.cancel"), onclick: () => sheet.close() }), submit)));
  sheet.showModal();
}

function confirmPreference(proposal) {
  const sheet = $("sheet");
  sheet.replaceChildren(el("div", { style: "padding:24px;max-width:520px" },
    el("h2", { textContent: t("prefs.confirm.title"), style: "margin-bottom:12px" }),
    el("p", { textContent: proposal.restatement || proposal.rule, style: "margin-bottom:8px" }),
    el("p", { className: "muted small", textContent: proposal.rule }),
    el("div", { className: "button-row end", style: "margin-top:18px" },
      el("button", {
        textContent: t("prefs.confirm.no"),
        onclick: async () => {
          try { await api("/api/preferences/change", { pref_id: proposal.pref_id, action: "retire", reason: "declined" }); }
          catch { /* already gone */ }
          sheet.close();
          loadPreferences();
        },
      }),
      el("button", {
        className: "primary", textContent: t("prefs.confirm.yes"),
        onclick: async () => {
          try { await api("/api/preferences/change", { pref_id: proposal.pref_id, action: "confirm" }); }
          catch (error) { showError(error); }
          sheet.close();
          state.decision = "reject";
          $("decision-note").textContent = t("plan.rejected");
          loadPreferences();
        },
      }))));
  sheet.showModal();
}

/* ----------------------------------------------------------------- chat */

function addBubble(role, text, className = "") {
  const bubble = el("div", { className: `bubble ${role} ${className}`.trim(), textContent: text });
  $("chat-log").append(bubble);
  bubble.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return bubble;
}

async function renderChatSuggestions() {
  const root = $("suggestions");
  root.replaceChildren();
  try {
    const { questions } = await api("/api/suggested-questions", { overrides: overrides() });
    for (const question of questions) {
      root.append(el("button", {
        textContent: question,
        onclick: () => { $("chat-input").value = question; askQuestion(); },
      }));
    }
  } catch { /* suggestions are a convenience, not a requirement */ }
}

async function askQuestion() {
  const input = $("chat-input");
  const question = input.value.trim();
  if (!question) return;
  if (!state.run) { showError(t("plan.empty.body")); return; }

  input.value = "";
  addBubble("grower", question);
  const pending = addBubble("assistant", t("chat.thinking"), "thinking");
  try {
    const reply = await api("/api/explain", {
      run_id: state.run.run_id, date: state.run.date, plan: state.run.plan,
      metrics: state.run.metrics, cost_forecast: state.run.cost_forecast,
      data_source: state.run.data_source, question, overrides: overrides(),
    });
    pending.classList.remove("thinking");
    pending.textContent = reply.answer;
  } catch (error) {
    pending.classList.remove("thinking");
    pending.classList.add("error");
    pending.textContent = String(error.message || error);
  }
}

$("chat-form").addEventListener("submit", (event) => { event.preventDefault(); askQuestion(); });
$("chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); askQuestion(); }
});

/* ---------------------------------------------------------- preferences */

async function loadPreferences() {
  const root = $("prefs-list");
  let payload;
  try { payload = await api("/api/preferences"); }
  catch (error) { showError(error); return; }
  // Cleared after the await, not before: two overlapping loads would otherwise
  // both clear an empty list and then each append their own copy.
  root.replaceChildren();

  if (!payload.preferences.length) {
    root.append(el("div", { className: "card" },
      el("div", { className: "empty" },
        el("div", { className: "mark", textContent: "📋" }),
        el("p", { textContent: t("prefs.empty") }))));
    return;
  }

  for (const pref of payload.preferences) {
    const card = el("div", { className: `pref ${pref.active ? "" : "retired"}`.trim() });
    card.append(el("div", { className: "rule", textContent: pref.rule }));
    if (pref.reason) card.append(el("div", { className: "reason", textContent: `"${pref.reason}"` }));

    const meta = el("div", { className: "meta" },
      el("span", { className: `tag ${pref.strength}`, textContent: t(`prefs.strength.${pref.strength}`).split("—")[0].trim() }));
    if (!pref.confirmed) meta.append(el("span", { className: "tag unconfirmed", textContent: t("prefs.confirm.title") }));
    if (pref.applied_count) meta.append(el("span", { textContent: t("prefs.applied", { n: pref.applied_count }) }));
    if (pref.overridden_count) meta.append(el("span", { textContent: t("prefs.overridden", { n: pref.overridden_count }) }));

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
  const strengthWrap = el("div", { className: "field" },
    el("label", { htmlFor: "pref-strength", textContent: t("prefs.strength") }), strength);

  sheet.replaceChildren(el("div", { style: "padding:24px;max-width:520px" },
    el("h2", { textContent: t("prefs.add"), style: "margin-bottom:16px" }),
    rule.wrap, reason.wrap, strengthWrap,
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

/* ------------------------------------------------------------- settings */

async function loadSettings() {
  const root = $("model-settings");
  root.replaceChildren();
  let payload;
  try { payload = await api("/api/models"); }
  catch (error) { root.append(el("p", { className: "muted", textContent: String(error.message) })); return; }

  const select = el("select", { id: "provider-select" });
  for (const provider of payload.providers) {
    select.append(el("option", {
      value: provider.id,
      textContent: provider.name + (provider.configured ? "" : ` — ${t("settings.ai.key")}`),
    }));
  }
  select.value = state.settings.llm_provider || payload.selected.provider;
  select.addEventListener("change", () => {
    state.settings.llm_provider = select.value;
    const chosen = payload.providers.find((p) => p.id === select.value);
    if (chosen && chosen.models.length) {
      state.settings.llm_model = chosen.models[0];
      model.value = chosen.models[0];
    }
    LS.set("kasflex.grower.settings", state.settings);
  });

  const model = el("input", { type: "text", id: "model-name", value: state.settings.llm_model || payload.selected.model });
  model.addEventListener("change", () => {
    state.settings.llm_model = model.value.trim();
    LS.set("kasflex.grower.settings", state.settings);
  });

  const status = el("p", { className: "small muted", role: "status" });
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
        loadSettings();
      } catch (error) { status.textContent = String(error.message); }
    },
  });

  root.append(
    el("div", { className: "field" }, el("label", { htmlFor: "provider-select", textContent: t("settings.ai.provider") }), select),
    el("div", { className: "field" }, el("label", { htmlFor: "model-name", textContent: t("settings.ai.model") }), model),
    el("div", { className: "field" }, el("label", { htmlFor: "api-key", textContent: t("settings.ai.key") }),
      el("div", { className: "button-row" }, key, saveKey)),
    el("div", { className: "button-row" }, test), status,
  );

  // Data mode
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

  // Saved setup
  const profileRoot = $("profile-settings");
  profileRoot.replaceChildren();
  if (state.profile) {
    profileRoot.append(el("p", { textContent: t("onboard.profile.saved", { name: state.profile.name }) }));
    if (state.profile.profile_id) {
      profileRoot.append(el("div", { className: "button-row", style: "margin-top:12px" },
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

/* ------------------------------------------------------------ navigation */

const VIEWS = ["today", "chat", "prefs", "settings"];
let currentView = "today";

function navigate(view) {
  if (!VIEWS.includes(view)) view = "today";
  // Setting location.hash below fires hashchange, which lands back here. Without
  // this guard every view renders twice and each async loader runs concurrently,
  // so a list that clears itself then appends shows every row twice.
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
  if (currentView === "prefs") loadPreferences();
  else if (currentView === "settings") loadSettings();
  else if (currentView === "chat") renderChatSuggestions();
}

for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => navigate(button.dataset.view));
}
window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));

/* ----------------------------------------------------------------- boot */

function refreshAll() { renderCurrentView(); }

async function boot() {
  state.profile = LS.get("kasflex.grower.profile");
  state.settings = LS.get("kasflex.grower.settings", {}) || {};
  try {
    await loadLanguage(state.settings.language || navigator.language || "en");
  } catch (error) {
    showError(error);
    return;
  }

  const saved = LS.get("kasflex.grower.lastRun");
  if (saved && saved.plan) {
    state.run = saved;
    state.originalPlan = saved.plan.map((row) => ({ ...row }));
    renderPlan(saved);
    $("today-empty").hidden = true;
    $("today-result").hidden = false;
  }

  navigate(location.hash.slice(1) || "today");
  if (needsOnboarding()) showOnboarding(true);
}

boot();
