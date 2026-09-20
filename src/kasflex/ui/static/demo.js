"use strict";

const $ = (id) => document.getElementById(id);
const DIMENSIONS = ["money", "crop", "grid", "work"];

const state = {
  lang: localStorage.getItem("kasflex.demo.lang") || "en",
  strings: {},
  context: null,
  run: null,
  sessionId: crypto.randomUUID(),
  participantId: localStorage.getItem("kasflex.demo.participant") || "",
  studyConsented: false,
  planShownAt: 0,
  sessionStartedAt: performance.now(),
  detailExpansions: 0,
  whyClicks: 0,
  editsMade: 0,
  dimensions: {},
  providers: [],
  selectedProvider: "",
  selectedModel: "",
};

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

function tr(key, fallback="") {
  return state.strings[key] || fallback || key;
}

async function loadLanguage(language) {
  state.lang = language === "nl" ? "nl" : "en";
  localStorage.setItem("kasflex.demo.lang", state.lang);
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

  if (state.context) renderContext(state.context);
  if (state.run) renderDecision(state.run, {preserveDimensions:true});
}

function euro(value, digits=0) {
  return Number(value || 0).toLocaleString(state.lang === "nl" ? "nl-NL" : "en-NL", {
    style:"currency", currency:"EUR", minimumFractionDigits:digits, maximumFractionDigits:digits,
  });
}
function cents(value) {
  return `${(Number(value || 0) * 100).toFixed(1)} ct/kWh`;
}
function hourList(values) {
  return (values || []).map((h) => String(h).padStart(2,"0") + ":00").join(", ");
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
  node._timer = setTimeout(() => node.hidden = true, 2800);
}
function secondsSince(timestamp) {
  return Math.max(0, (performance.now() - timestamp) / 1000);
}

function selectedPolicy() {
  return {
    priority: document.querySelector('input[name="priority"]:checked')?.value || "balanced",
    avoid_chp_night: $("avoid-chp-night").checked,
    prefer_stored_heat: $("prefer-buffer").checked,
    battery_reserve_pct: Number($("battery-reserve").value),
    brief: $("brief").value.trim(),
  };
}
function overrides() {
  return {
    data_source:"demo",
    planner:"collaborative",
    date:state.context?.date || undefined,
    language:state.lang,
    llm_provider:state.selectedProvider || undefined,
    llm_model:state.selectedModel || undefined,
    participant_id:state.participantId || undefined,
  };
}
function runRef(run=state.run) {
  return {run_id:run.run_id, revision:run.revision, plan_hash:run.plan_hash};
}

async function loadModels() {
  const payload = await api("/api/models");
  state.providers = payload.providers || [];
  const selected = payload.selected || {};
  state.selectedProvider = selected.provider || "";
  state.selectedModel = selected.model || "";

  const select = $("model-select");
  select.replaceChildren();
  for (const provider of state.providers) {
    const models = provider.models?.length ? provider.models : [state.selectedModel || "default"];
    for (const model of models) {
      const option = document.createElement("option");
      option.value = JSON.stringify({provider:provider.id, model});
      const status = provider.configured === false ? " · setup needed" : "";
      option.textContent = `${provider.name} — ${model}${status}`;
      if (provider.id === state.selectedProvider && model === state.selectedModel) option.selected = true;
      select.append(option);
    }
  }
  if (!select.options.length) {
    const option = document.createElement("option");
    option.value = JSON.stringify({provider:"", model:""});
    option.textContent = "Collaborative planner";
    select.append(option);
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

async function loadContext() {
  clearError();
  $("data-pill").className = "pill loading";
  $("data-pill").textContent = state.lang === "nl" ? "Echte data voorbereiden…" : "Preparing real data…";
  $("refresh-data").disabled = true;
  try {
    const prepared = await api("/api/demo-prepare", {overrides:{data_source:"demo"}});
    state.context = await api("/api/day-context", {
      overrides:{...overrides(), date:prepared.date, data_source:"demo"}
    });
    renderContext(state.context);
    $("data-pill").className = "pill";
    $("data-pill").textContent = state.lang === "nl"
      ? (prepared.reused_cache ? "Echte data · lokaal opgeslagen" : "Echte data · klaar")
      : (prepared.reused_cache ? "Real data · cached" : "Real data · ready");
  } catch (error) {
    $("data-pill").className = "pill loading";
    $("data-pill").textContent = state.lang === "nl" ? "Data niet beschikbaar" : "Data unavailable";
    showError(error, state.lang === "nl" ? "Data voorbereiden" : "Preparing data");
  } finally {
    $("refresh-data").disabled = false;
  }
}

function renderContext(ctx) {
  const locale = state.lang === "nl" ? "nl-NL" : "en-GB";
  $("planning-date").textContent = new Date(ctx.date + "T12:00:00").toLocaleDateString(locale, {
    weekday:"short", day:"numeric", month:"short", year:"numeric"
  });
  const provenance = ctx.provenance || {};
  const market = provenance.prices?.dataset_key === "entsoe_da"
    ? (state.lang === "nl" ? "ENTSO-E-afgeleide NL-prijzen" : "ENTSO-E-derived NL prices")
    : (state.lang === "nl" ? "stroomprijzen" : "electricity prices");
  const weather = provenance.forecast_weather?.dataset_key === "openmeteo_hist_forecast"
    ? "Open-Meteo"
    : (state.lang === "nl" ? "weersverwachting" : "weather forecast");
  $("source-summary").textContent = `${market} · ${weather}`;
  $("price-low").textContent = cents(ctx.price.min_eur_kwh);
  $("price-high").textContent = cents(ctx.price.max_eur_kwh);
  $("price-low-hours").textContent = hourList(ctx.price.cheapest_hours);
  $("price-high-hours").textContent = hourList(ctx.price.dearest_hours);
  $("temp-range").textContent = `${ctx.weather.min_temp_c.toFixed(1)}–${ctx.weather.max_temp_c.toFixed(1)} °C`;
  $("sun-hours").textContent = state.lang === "nl"
    ? `${ctx.weather.sun_hours} uur bruikbaar daglicht`
    : `${ctx.weather.sun_hours} h useful daylight`;
  $("grid-limit").textContent = `${(ctx.grid.import_limit_kw / 1000).toFixed(1)} MW`;
  const windows = Object.keys(ctx.grid.congestion_windows || {}).map(Number).sort((a,b)=>a-b);
  $("grid-window").textContent = windows.length
    ? `${windows[0]}:00–${windows.at(-1)+1}:00`
    : (state.lang === "nl" ? "Geen congestievenster" : "No congestion window");
  renderPriceChart(ctx.price.series);
}

function renderPriceChart(values) {
  const root = $("price-chart");
  root.replaceChildren();
  const min = Math.min(...values), max = Math.max(...values), span = Math.max(0.001, max-min);
  values.forEach((value, hour) => {
    const bar = document.createElement("div");
    bar.className = "price-bar" + (value > min + span * .65 ? " high" : "");
    bar.style.height = `${18 + ((value-min)/span)*116}px`;
    bar.title = `${String(hour).padStart(2,"0")}:00 · ${cents(value)}`;
    root.append(bar);
  });
}

async function buildPlan() {
  if (!state.context) {
    showError(new Error(state.lang === "nl" ? "De dagdata is nog niet klaar." : "Day data is not ready yet."));
    return;
  }
  const button = $("build-plan");
  button.disabled = true;
  clearError();
  const old = button.textContent;
  button.textContent = state.lang === "nl" ? "Plan maken…" : "Building plan…";
  try {
    state.run = await api("/api/run", {overrides:overrides(), policy:selectedPolicy()});
    state.planShownAt = performance.now();
    state.dimensions = {};
    $("prepare-view").hidden = true;
    $("decision-view").hidden = false;
    renderDecision(state.run);
  } catch (error) {
    showError(error, state.lang === "nl" ? "Plan maken" : "Building plan");
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

function renderDecision(run, {preserveDimensions=false}={}) {
  $("result-cost").textContent = euro(run.metrics?.net_cost_eur);
  const saving = Number(run.normal_settings?.saving_eur || 0);
  $("result-saving").textContent = run.normal_settings
    ? (state.lang === "nl"
      ? `${euro(Math.abs(saving))} ${saving >= 0 ? "lager" : "hoger"} dan normaal`
      : `${euro(Math.abs(saving))} ${saving >= 0 ? "below" : "above"} normal`)
    : "—";

  const band = run.uncertainty?.cost;
  $("result-badcase").textContent = band && run.uncertainty?.is_defensible
    ? euro(band.high_eur)
    : (state.lang === "nl" ? "Nog onbekend" : "Not defensible yet");
  $("result-confidence").textContent = run.uncertainty?.words?.detail || "";

  const position = run.position?.summary || {};
  const direction = position.net_direction === "short"
    ? (state.lang === "nl" ? "Tekort" : "Short")
    : position.net_direction === "long"
      ? (state.lang === "nl" ? "Over" : "Long")
      : (state.lang === "nl" ? "Vlak" : "Flat");
  $("result-position").textContent = direction;
  $("result-settlement").textContent = `${euro(position.settlement_eur || 0)} ${state.lang === "nl" ? "spotafrekening" : "spot settlement"}`;
  const crop = Number(run.metrics?.fruit_growth_kg_m2 || 0);
  $("result-crop").textContent = `${crop.toFixed(2)} kg/m²`;
  $("result-crop-note").textContent = state.lang === "nl"
    ? "modeluitkomst · nog niet gevalideerd"
    : "model output · not yet validated";

  const badge = $("checker-badge");
  if (run.checker_enabled && run.accepted) {
    badge.className = "checker good";
    badge.textContent = state.lang === "nl" ? "✓ Onafhankelijk gecontroleerd" : "✓ Independently checked";
  } else {
    badge.className = "checker bad";
    badge.textContent = state.lang === "nl" ? "Niet veilig om goed te keuren" : "Not safe to approve";
  }

  renderChanges(run);
  if (!preserveDimensions) state.dimensions = {};
  renderDimensions();
  updateApproval();
}

function dimensionEvidence(dimension) {
  const run = state.run;
  if (dimension === "money") {
    const saving = Number(run.normal_settings?.saving_eur || 0);
    return state.lang === "nl"
      ? `Verwachte kosten ${euro(run.metrics?.net_cost_eur)}; ${euro(Math.abs(saving))} verschil met normale regeling.`
      : `Expected cost ${euro(run.metrics?.net_cost_eur)}; ${euro(Math.abs(saving))} difference from normal control.`;
  }
  if (dimension === "crop") {
    const dli = Number(run.metrics?.supplemental_dli_mol_m2 || run.metrics?.dli_mol_m2 || 0);
    const hours = Number(run.metrics?.temperature_band_hours || 0);
    return state.lang === "nl"
      ? `${hours.toFixed(0)}/24 uur binnen temperatuurband; ${dli.toFixed(1)} mol/m² aanvullend licht (gesimuleerd).`
      : `${hours.toFixed(0)}/24 h inside temperature band; ${dli.toFixed(1)} mol/m² supplemental light (simulated).`;
  }
  if (dimension === "grid") {
    const peak = Number(run.metrics?.peak_import_kw || 0) / 1000;
    const limit = Number(state.context?.grid?.import_limit_kw || 0) / 1000;
    return state.lang === "nl"
      ? `Piek ${peak.toFixed(2)} MW bij een contractgrens van ${limit.toFixed(1)} MW.`
      : `Peak ${peak.toFixed(2)} MW against a ${limit.toFixed(1)} MW contract limit.`;
  }
  const policy = run.policy || {};
  const bits = [];
  if (policy.avoid_chp_night) bits.push(state.lang === "nl" ? "WKK 's nachts uit" : "CHP quiet overnight");
  if (policy.prefer_stored_heat) bits.push(state.lang === "nl" ? "buffer eerst" : "stored heat first");
  return bits.length ? bits.join(" · ") : (state.lang === "nl" ? "Geen extra praktijkregels ingesteld." : "No extra operating rules set.");
}

function renderDimensions() {
  const root = $("dimensions");
  root.replaceChildren();
  for (const dimension of DIMENSIONS) {
    const saved = state.dimensions[dimension] || {};
    const card = document.createElement("article");
    card.className = "dimension-card" + (saved.final ? " resolved" : "");
    card.dataset.dimension = dimension;

    const top = document.createElement("div");
    top.className = "dimension-card-top";
    const title = document.createElement("strong");
    title.textContent = tr(`dimension.${dimension}`, dimension);
    const why = document.createElement("button");
    why.className = "why";
    why.type = "button";
    why.textContent = state.lang === "nl" ? "Waarom?" : "Why?";
    why.addEventListener("click", () => {
      state.whyClicks += 1;
      openDetail(dimension === "grid" ? "position" : dimension === "money" ? "risk" : "plan");
    });
    top.append(title, why);

    const evidence = document.createElement("p");
    evidence.className = "evidence";
    evidence.textContent = dimensionEvidence(dimension);

    const choices = document.createElement("div");
    choices.className = "response-choices";
    for (const response of ["agree","unsure","disagree"]) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `dimension-${dimension}`;
      input.value = response;
      input.checked = saved.initial === response;
      input.disabled = Boolean(saved.final);
      const span = document.createElement("span");
      span.textContent = tr(`response.${response}`, response);
      input.addEventListener("change", () => respondDimension(dimension, response));
      label.append(input, span);
      choices.append(label);
    }

    const reason = document.createElement("input");
    reason.type = "text";
    reason.className = "dimension-reason";
    reason.placeholder = state.lang === "nl" ? "Optioneel: waarom?" : "Optional: why?";
    reason.value = saved.reason || "";
    reason.addEventListener("input", () => {
      state.dimensions[dimension] = {
        ...(state.dimensions[dimension] || {}),
        reason: reason.value,
      };
    });

    card.append(top, evidence, choices, reason);

    if (saved.counter) {
      const counter = document.createElement("div");
      counter.className = "counter";
      const text = document.createElement("p");
      text.textContent = saved.counter;
      counter.append(text);
      if (saved.alternative && !saved.final) {
        const actions = document.createElement("div");
        actions.className = "counter-actions";
        const use = document.createElement("button");
        use.type = "button";
        use.className = "small-primary";
        use.textContent = tr("counter.use", "Use this alternative");
        use.addEventListener("click", () => useAlternative(dimension));
        const keep = document.createElement("button");
        keep.type = "button";
        keep.className = "small-ghost";
        keep.textContent = tr("counter.keep", "Keep current plan");
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
    reason:state.dimensions[dimension]?.reason || "",
  };
  try {
    const reply = await api("/api/deliberate", payload);
    state.dimensions[dimension] = {
      ...previous,
      initial:response,
      counter:reply.counter_response,
      counterModel:reply.counter_model || "",
      alternative:reply.alternative,
      reason:previous.reason || "",
      final: response === "disagree" ? "" : response,
    };
    if (response !== "disagree") {
      await finaliseDimension(dimension, response);
    }
    renderDimensions();
    updateApproval();
  } catch (error) {
    showError(error, state.lang === "nl" ? "Uw oordeel verwerken" : "Recording your view");
  }
}

async function finaliseDimension(
  dimension,
  finalResponse,
  acceptedFinally=null,
  outcomeShown=false,
  outcomeResult=""
) {
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
    showError(error, state.lang === "nl" ? "Onderzoeksrecord opslaan" : "Saving research record");
  }
}

async function useAlternative(dimension) {
  const item = state.dimensions[dimension];
  if (!item?.alternative) return;
  state.editsMade += 1;
  state.run = item.alternative;
  state.planShownAt = performance.now();
  state.dimensions = {
    [dimension]: {...item, final:"agree", alternative:null},
  };
  await finaliseDimension(dimension, "agree");
  renderDecision(state.run, {preserveDimensions:true});
  toast(state.lang === "nl" ? "Alternatief toegepast. Beoordeel de andere onderdelen opnieuw." : "Alternative applied. Review the other dimensions again.");
}

async function keepCurrent(dimension) {
  const item = state.dimensions[dimension];
  state.dimensions[dimension] = {...item, final:"disagree", alternative:null};
  await finaliseDimension(dimension, "disagree");
  renderDimensions();
  updateApproval();
}

function updateApproval() {
  const done = DIMENSIONS.filter((dimension) => state.dimensions[dimension]?.final).length;
  $("review-progress").textContent = `${done}/4`;
  $("approve-plan").disabled = !(done === 4 && state.run?.checker_enabled && state.run?.accepted);
}

function renderChanges(run) {
  const root = $("changes-list");
  root.replaceChildren();
  const actions = (run.actions || []).slice(0, 4);
  if (!actions.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = state.lang === "nl" ? "Geen grote wijzigingen ten opzichte van normaal." : "No material changes from normal control.";
    root.append(p);
    return;
  }
  for (const action of actions) {
    const item = document.createElement("div");
    item.className = "change-item";
    const title = document.createElement("strong");
    title.textContent = action.title || "Change";
    const why = document.createElement("small");
    why.textContent = action.why || "";
    const alternative = document.createElement("small");
    alternative.className = "alternative";
    const value = action.baseline_value || "normal";
    const saving = Number(action.saving_eur || 0);
    alternative.textContent = state.lang === "nl"
      ? `Alternatief: normale regeling (${value}). Grove bijdrage aan dagverschil: ${euro(Math.abs(saving))}.`
      : `Alternative: normal control (${value}). Rough share of whole-day difference: ${euro(Math.abs(saving))}.`;
    const confidence = document.createElement("small");
    confidence.className = "confidence-note";
    const uncertain = new Set(state.run?.uncertainty?.hours_most_uncertain || []);
    const touchesUncertain = (action.hours || []).some((hour) => uncertain.has(Number(hour)));
    const band = state.run?.uncertainty?.confidence || "unknown";
    confidence.textContent = touchesUncertain
      ? (state.lang === "nl" ? "Lagere zekerheid: deze uren horen bij de meest onzekere uren." : "Lower confidence: these hours are among the most uncertain.")
      : (state.lang === "nl" ? `Zekerheid van het dagplan: ${band}.` : `Day-plan confidence: ${band}.`);
    item.append(title, why, alternative, confidence);
    root.append(item);
  }
}

function openDetail(kind) {
  state.detailExpansions += 1;
  const dialog = $("detail-dialog");
  const body = $("dialog-body");
  body.replaceChildren();
  $("dialog-eyebrow").textContent = state.lang === "nl" ? "Verdieping" : "Detail";

  if (kind === "position") renderPositionDetail(body);
  else if (kind === "risk") renderRiskDetail(body);
  else if (kind === "plan") renderPlanDetail(body);
  else renderDataDetail(body);

  dialog.showModal();
}

function renderPositionDetail(root) {
  $("dialog-title").textContent = state.lang === "nl" ? "Positie, afwijking en net" : "Position, deviation and grid";
  const summary = state.run?.position?.summary || {};
  root.innerHTML = `
    <div class="detail-grid">
      <article><span>${state.lang==="nl"?"Gecontracteerd":"Contracted"}</span><strong>${(Number(summary.contracted_energy_kwh||0)/1000).toFixed(1)} MWh</strong></article>
      <article><span>${state.lang==="nl"?"Geplande netto-afname":"Planned net use"}</span><strong>${(Number(summary.planned_net_energy_kwh||0)/1000).toFixed(1)} MWh</strong></article>
      <article><span>${state.lang==="nl"?"Absolute afwijking":"Absolute deviation"}</span><strong>${(Number(summary.absolute_deviation_kwh||0)/1000).toFixed(1)} MWh</strong></article>
      <article><span>${state.lang==="nl"?"Spotafrekening":"Spot settlement"}</span><strong>${euro(summary.settlement_eur||0)}</strong></article>
      <article><span>${state.lang==="nl"?"Export":"Export"}</span><strong>${(Number(summary.export_energy_kwh||0)/1000).toFixed(1)} MWh</strong></article>
      <article><span>${state.lang==="nl"?"Exportopbrengst":"Export revenue"}</span><strong>${euro(summary.export_revenue_eur||0)}</strong></article>
    </div>
    <p class="detail-note">${state.lang==="nl"
      ? "Positierisico = het verschil tussen vooraf gecontracteerd volume en wat het plan werkelijk van het net vraagt. Positieve afwijking is tekort; negatieve afwijking is over."
      : "Volume risk is the difference between the contracted position and what the plan actually needs from the grid. Positive deviation is short; negative deviation is long."}</p>
    <div id="position-bars" class="position-bars"></div>`;
  const bars = root.querySelector("#position-bars");
  for (const row of state.run?.position?.hours || []) {
    const line = document.createElement("div");
    line.className = `position-line ${row.direction}`;
    line.innerHTML = `<span>${String(row.hour).padStart(2,"0")}:00</span><b>${(row.planned_net_kw/1000).toFixed(2)} MW</b><small>${row.direction} · ${euro(row.settlement_eur,0)}</small>`;
    bars.append(line);
  }
}

function renderRiskDetail(root) {
  $("dialog-title").textContent = state.lang === "nl" ? "Risico en onzekerheid" : "Risk and uncertainty";
  const u = state.run?.uncertainty || {};
  const band = u.cost;
  root.innerHTML = `
    <div class="detail-grid">
      <article><span>${state.lang==="nl"?"Verwacht":"Expected"}</span><strong>${euro(state.run?.metrics?.net_cost_eur)}</strong></article>
      <article><span>${state.lang==="nl"?"Ongunstig 90e percentiel":"Bad-case 90th percentile"}</span><strong>${band && u.is_defensible ? euro(band.high_eur) : "—"}</strong></article>
      <article><span>${state.lang==="nl"?"Weeronzekerheid":"Weather uncertainty"}</span><strong>${u.forecast_error?.basis || "—"}</strong></article>
      <article><span>${state.lang==="nl"?"Modelbekendheid":"Model familiarity"}</span><strong>${u.novelty?.band || "—"}</strong></article>
    </div>
    <div class="risk-copy">
      <h3>${state.lang==="nl"?"Onvermijdelijke onzekerheid":"Irreducible uncertainty"}</h3>
      <p>${u.words?.detail || "—"}</p>
      <h3>${state.lang==="nl"?"Modelonzekerheid":"Model uncertainty"}</h3>
      <p>${u.novelty?.known
        ? (state.lang==="nl" ? `Deze dag is geclassificeerd als: ${u.novelty.band}.` : `This day is classified as: ${u.novelty.band}.`)
        : (state.lang==="nl" ? "Nog te weinig historische dagen om modelonzekerheid betrouwbaar te schatten." : "Not enough historical days yet to estimate model uncertainty reliably.")}</p>
      ${state.run?.actuals_available ? `<h3>${state.lang==="nl"?"Historische replay-uitkomst":"Historical replay outcome"}</h3>
      <p>${state.lang==="nl"
        ? `Werkelijke replay-kosten: ${euro(state.run.metrics?.net_cost_eur)} tegenover ${euro(state.run.cost_forecast?.totals?.net_cost_eur || state.run.metrics?.net_cost_eur)} voorspeld.`
        : `Replay realised cost: ${euro(state.run.metrics?.net_cost_eur)} versus ${euro(state.run.cost_forecast?.totals?.net_cost_eur || state.run.metrics?.net_cost_eur)} predicted.`}</p>` : ""}
      <p class="warning">${state.lang==="nl"?"Het kasmodel zelf is nog niet gevalideerd tegen AGC-metingen.":"The greenhouse model itself is still not validated against AGC measurements."}</p>
    </div>`;
}

function renderPlanDetail(root) {
  $("dialog-title").textContent = state.lang === "nl" ? "Volledig 24-uursplan" : "Full 24-hour plan";
  const table = document.createElement("table");
  table.innerHTML = `<thead><tr><th>Hour</th><th>Price</th><th>Heat</th><th>Lights</th><th>Battery</th><th>CHP</th></tr></thead><tbody></tbody>`;
  const body = table.querySelector("tbody");
  for (const row of state.run?.plan || []) {
    const trNode = document.createElement("tr");
    const battery = row.battery === "idle" ? "idle" : `${row.battery} ${Math.round(row.battery_power_kw)} kW`;
    for (const value of [
      `${String(row.hour).padStart(2,"0")}:00`,
      cents(row.power_price_eur_kwh),
      row.heat_source,
      `${Math.round(row.lighting_level*100)}%`,
      battery,
      row.chp_mode,
    ]) {
      const td = document.createElement("td");
      td.textContent = value;
      trNode.append(td);
    }
    body.append(trNode);
  }
  root.append(table);
}

function renderDataDetail(root) {
  $("dialog-title").textContent = state.lang === "nl" ? "Data en herkomst" : "Data and provenance";
  const provenance = state.context?.provenance || {};
  const items = Object.entries(provenance);
  if (!items.length) {
    root.textContent = state.lang === "nl" ? "Geen bronmetadata beschikbaar." : "No provenance metadata available.";
    return;
  }
  for (const [role, info] of items) {
    const card = document.createElement("article");
    card.className = "source-card";
    card.innerHTML = `<strong>${role}</strong><span>${info.dataset_key || ""}</span><small>${info.source || ""}</small><small>SHA256 ${String(info.sha256||"").slice(0,16)}…</small>`;
    root.append(card);
  }
}

async function approvePlan() {
  if (!state.run) return;
  const button = $("approve-plan");
  button.disabled = true;
  try {
    await api("/api/decision", {
      ...runRef(),
      decision:"approve",
      comment:"Approved after dimension-level deliberation",
      research_consent:state.studyConsented,
      seconds_to_decide:secondsSince(state.planShownAt),
    });
    const predicted = Number(state.run.cost_forecast?.totals?.net_cost_eur || state.run.metrics?.net_cost_eur || 0);
    const actual = Number(state.run.metrics?.net_cost_eur || 0);
    const outcomeResult = !state.run.actuals_available
      ? ""
      : actual <= predicted ? "better_than_expected" : "worse_than_expected";

    for (const dimension of DIMENSIONS) {
      await finaliseDimension(
        dimension,
        state.dimensions[dimension]?.final || "unsure",
        true,
        Boolean(state.run.actuals_available),
        outcomeResult,
      );
    }

    if (state.run.actuals_available) {
      try {
        await api("/api/outcomes", {
          overrides:overrides(),
          run_id:state.run.run_id,
          predicted_cost_eur:predicted,
          actual_cost_eur:actual,
          ai_plan_cost_eur:predicted,
          final_plan_cost_eur:actual,
          within_predicted_band: Boolean(
            state.run.uncertainty?.cost &&
            actual >= state.run.uncertainty.cost.low_eur &&
            actual <= state.run.uncertainty.cost.high_eur
          ),
          note:"Historical demo replay",
        });
      } catch {}
    }

    $("decision-copy").textContent = state.lang === "nl"
      ? "Goedgekeurd. Deze gecontroleerde versie is vastgelegd als het definitieve dagplan."
      : "Approved. This checked revision is recorded as the final day plan.";
    button.textContent = state.lang === "nl" ? "✓ Goedgekeurd" : "✓ Approved";
    toast(state.lang === "nl" ? "Definitief plan vastgelegd." : "Final plan recorded.");
  } catch (error) {
    showError(error, state.lang === "nl" ? "Plan goedkeuren" : "Approving plan");
    updateApproval();
  }
}

function backToChoices() {
  $("decision-view").hidden = true;
  $("prepare-view").hidden = false;
}

async function consentStudy() {
  const participant = $("participant-id").value.trim();
  if (!participant) {
    $("participant-id").focus();
    return;
  }
  const status = await api("/api/consent");
  await api("/api/consent", {
    participant_id:participant,
    version:status.version,
    scopes:{research:true, quotes:true, outcomes:true},
    overrides:{participant_id:participant},
  });
  state.participantId = participant;
  state.studyConsented = true;
  localStorage.setItem("kasflex.demo.participant", participant);
  $("consent-dialog").close();
}

function consentAnonymous() {
  state.participantId = "";
  state.studyConsented = false;
  localStorage.removeItem("kasflex.demo.participant");
  $("consent-dialog").close();
}

$("battery-reserve").addEventListener("input", () => $("reserve-value").textContent = $("battery-reserve").value + "%");
$("refresh-data").addEventListener("click", loadContext);
$("build-plan").addEventListener("click", buildPlan);
$("open-position").addEventListener("click", () => openDetail("position"));
$("open-risk").addEventListener("click", () => openDetail("risk"));
$("open-plan").addEventListener("click", () => openDetail("plan"));
$("open-data").addEventListener("click", () => openDetail("data"));
$("approve-plan").addEventListener("click", approvePlan);
$("back-to-choices").addEventListener("click", backToChoices);
$("close-dialog").addEventListener("click", () => $("detail-dialog").close());
$("consent-anonymous").addEventListener("click", consentAnonymous);
$("consent-study").addEventListener("click", consentStudy);
$("language-select").addEventListener("change", (event) => loadLanguage(event.target.value));
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
    await loadModels();
    await handleConsent();
    await loadContext();
  } catch (error) {
    showError(error, state.lang === "nl" ? "Demo starten" : "Starting demo");
  }
}
boot();
