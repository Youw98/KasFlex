"use strict";

// Workshop admin: the researcher chooses the study version, the scenario the
// participants plan, edits scenarios, and clears remembered reasons between groups.

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const state = {lang: readStore("kasflex.demo.lang") === "nl" ? "nl" : "en", status: null, editing: null,
               token: readSession("kasflex.admin.token") || ""};

function readSession(key) { try { return sessionStorage.getItem(key); } catch { return null; } }
function writeSession(key, value) {
  try { value ? sessionStorage.setItem(key, value) : sessionStorage.removeItem(key); } catch {}
}
function readStore(key) { try { return localStorage.getItem(key); } catch { return null; } }
function writeStore(key, value) { try { localStorage.setItem(key, value); } catch {} }
function T(en, nl) { return state.lang === "nl" ? nl : en; }
function el(tag, className="", text="") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

async function api(path, body) {
  const headers = body === undefined ? {} : {"Content-Type": "application/json"};
  if (state.token) headers["X-KasFlex-Admin"] = state.token;
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch {}
  if (response.status === 401 && path !== "/api/admin/login") {
    showLogin();
    throw new Error(payload.error || "Locked");
  }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

// -- the password gate: nothing on this page shows until the server accepts it ----

function showLogin(message="") {
  state.token = "";
  writeSession("kasflex.admin.token", "");
  $("workspace").hidden = true;
  $("login-main").hidden = false;
  $("admin-login-error").hidden = !message;
  $("admin-login-error").textContent = message;
  $("admin-password").value = "";
  $("admin-password").focus();
}
async function unlock(event) {
  event?.preventDefault();
  try {
    const result = await api("/api/admin/login", {password:$("admin-password").value});
    state.token = result.token;
    writeSession("kasflex.admin.token", result.token);
    await start();
  } catch (error) {
    showLogin(T("Wrong password.", "Verkeerd wachtwoord."));
  }
}
async function start() {
  try { await api("/api/site-settings"); } catch { return; }
  $("login-main").hidden = true;
  $("workspace").hidden = false;
  await load();
}
function showError(error) {
  $("error").textContent = String(error?.message || error);
  $("error").hidden = false;
  window.scrollTo({top:0, behavior:"smooth"});
}
function clearError() { $("error").hidden = true; }
function toast(text) {
  const node = $("toast");
  node.textContent = text;
  node.hidden = false;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.hidden = true, 2600);
}

const VERSION_TEXT = {
  manual:[["1 · No advisor", "The grower sets priority and targets. KasFlex calculates and checks the plan, but does not suggest, argue or explain."],
          ["1 · Zonder adviseur", "De teler kiest prioriteit en doelen. KasFlex rekent en controleert, maar stelt niets voor, discussieert niet en legt niet uit."]],
  ai:[["2 · AI suggests", "KasFlex suggests a plan first. The grower agrees or disagrees per part, with a reason that KasFlex remembers."],
      ["2 · AI stelt voor", "KasFlex doet eerst een voorstel. De teler is het per onderdeel eens of oneens, met een reden die KasFlex onthoudt."]],
  collab:[["3 · AI + chat", "As version 2, plus a chat panel to ask KasFlex questions about the plan."],
          ["3 · AI + chat", "Als versie 2, plus een chatvenster om KasFlex vragen over het plan te stellen."]],
};
const FLAW_TEXT = {
  "":["No error", "Geen fout"],
  hidden_curtailment:["Grid operator notice (lower import in some hours)", "Melding netbeheerder (minder afname in sommige uren)"],
  hidden_maintenance:["CHP maintenance (CHP must stay off)", "WKK-onderhoud (WKK moet uit)"],
  forecast_miss:["Forecast miss (night colder than forecast)", "Verkeerde verwachting (nacht kouder dan verwacht)"],
};

function translate() {
  document.documentElement.lang = state.lang;
  $("language-select").value = state.lang;
  const texts = {
    "t-subtitle":["Workshop admin", "Workshopbeheer"], "t-password":["Password", "Wachtwoord"],
    "admin-unlock":["Unlock", "Ontgrendelen"], "t-open-grower":["Open grower page ↗", "Telerscherm openen ↗"],
    "t-language":["Language", "Taal"], "t-title":["Workshop set-up", "Workshop instellen"],
    "t-intro":["Choose what participants see, which day they plan, and manage the scenarios.",
               "Kies wat deelnemers zien, welke dag ze plannen, en beheer de scenario's."],
    "t-version":["1 · Study version", "1 · Versie van het onderzoek"],
    "t-active":["2 · Scenario for participants", "2 · Scenario voor deelnemers"],
    "t-scenario":["Scenario", "Scenario"], "t-lock":["Lock it: participants cannot switch day or data", "Vastzetten: deelnemers kunnen geen andere dag of data kiezen"],
    "save-active":["Save", "Opslaan"], "t-scenarios":["3 · Scenarios", "3 · Scenario's"], "new-scenario":["+ New scenario", "+ Nieuw scenario"],
    "t-kind":["Kind", "Soort"], "t-date":["Date", "Datum"], "t-contract":["Grid contract", "Netcontract"], "t-winter":["Winter", "Winter"],
    "t-seed":["Weather seed", "Weer-seed"], "t-sun":["Sunlight × (0–3)", "Zonlicht × (0–3)"], "t-texts":["Texts", "Teksten"],
    "t-day":["Prices and temperatures", "Prijzen en temperaturen"],
    "t-day-hint":["24 values each, separated by commas or spaces. Leave empty to use a simulated day.",
                  "Elk 24 waarden, gescheiden door komma's of spaties. Leeg laten voor een gesimuleerde dag."],
    "t-prices":["Power price per hour (ct/kWh)", "Stroomprijs per uur (ct/kWh)"],
    "t-temps":["Outside temperature per hour (°C)", "Buitentemperatuur per uur (°C)"],
    "t-hub":["Installation (empty = standard)", "Installatie (leeg = standaard)"],
    "t-boiler":["Boiler (kW)", "Ketel (kW)"], "t-buffer":["Heat buffer (kWh)", "Warmtebuffer (kWh)"],
    "t-battery":["Battery (kWh)", "Batterij (kWh)"], "t-import":["Grid import limit (kW)", "Netafnamegrens (kW)"],
    "t-flaw":["Deliberate error (flawed scenarios)", "Bewuste fout (scenario's met fout)"],
    "t-flaw-hint":["The story tells participants a fact that the planner never sees. After approval, KasFlex checks the plan against that fact.",
                   "Het verhaal vertelt deelnemers iets wat de planner niet weet. Na goedkeuren controleert KasFlex het plan daartegen."],
    "t-flaw-type":["Type", "Soort"], "t-flaw-hours":["Hours (e.g. 16-19 or 8,9,10)", "Uren (bijv. 16-19 of 8,9,10)"],
    "t-flaw-import":["Max. grid import then (kW)", "Max. netafname dan (kW)"], "t-flaw-drop":["Night colder than forecast by (°C)", "Nacht kouder dan verwacht met (°C)"],
    "save-scenario":["Save scenario", "Scenario opslaan"], "cancel-edit":["Cancel", "Annuleren"],
    "t-memory":["5 · Remembered reasons", "5 · Onthouden redenen"], "forget-all":["Forget all", "Alles vergeten"],
    "t-docs":["4 · Documents for the chat", "4 · Documenten voor de chat"],
    "t-docs-hint":["The chat answers from the plan and from these documents, and names the document it used. Load a Word file, or paste text (for a PDF, copy its text).",
                   "De chat antwoordt uit het plan en uit deze documenten, en noemt het document dat hij gebruikte. Laad een Wordbestand, of plak tekst (kopieer de tekst uit een pdf)."],
    "t-doc-title":["Title", "Titel"], "t-doc-file":["Load a file (.docx, .txt, .md)", "Bestand laden (.docx, .txt, .md)"], "t-doc-text":["Text", "Tekst"],
    "save-doc":["Add document", "Document toevoegen"],
    "t-memory-hint":["What participants said when they disagreed. KasFlex uses these in later plans of the same participant. Clear them between workshop groups.",
                     "Wat deelnemers zeiden toen ze het oneens waren. KasFlex gebruikt dit in latere plannen van dezelfde deelnemer. Wis dit tussen workshopgroepen."],
  };
  for (const [id, pair] of Object.entries(texts)) if ($(id)) $(id).textContent = T(...pair);
}

async function load() {
  clearError();
  try {
    state.status = await api(`/api/workshop?lang=${state.lang}`);
  } catch (error) { showError(error); return; }
  renderVersions();
  renderActive();
  renderScenarios();
  renderContractOptions();
  await loadDocuments();
  await loadMemory();
}

function renderVersions() {
  const root = $("versions");
  root.replaceChildren();
  for (const version of state.status.versions) {
    const [name, text] = VERSION_TEXT[version]?.[state.lang === "nl" ? 1 : 0] || [version, ""];
    const label = el("label");
    const input = el("input");
    input.type = "radio";
    input.name = "version";
    input.value = version;
    input.checked = state.status.version === version;
    input.addEventListener("change", () => save({version}, T("Version saved.", "Versie opgeslagen.")));
    label.append(input, el("strong", "", name), el("small", "", text));
    root.append(label);
  }
}

function renderActive() {
  const select = $("active-scenario");
  select.replaceChildren();
  const none = el("option", "", T("— none: participants choose the data —", "— geen: deelnemers kiezen zelf —"));
  none.value = "";
  select.append(none);
  for (const scenario of state.status.scenarios) {
    const option = el("option", "", `${scenario.title_text} (${scenario.kind})`);
    option.value = scenario.id;
    select.append(option);
  }
  select.value = state.status.scenario_id || "";
  $("lock-scenario").checked = Boolean(state.status.lock_scenario);
  const active = state.status.scenarios.find((s) => s.id === state.status.scenario_id);
  $("active-note").textContent = active
    ? T(`Participants open “${active.title_text}”${state.status.lock_scenario ? " and cannot switch." : "; they can still switch."}`,
        `Deelnemers openen “${active.title_text}”${state.status.lock_scenario ? " en kunnen niet wisselen." : "; ze kunnen nog wisselen."}`)
    : T("No scenario chosen.", "Geen scenario gekozen.");
}

async function save(payload, message) {
  clearError();
  try {
    state.status = await api("/api/workshop", {...payload, language:state.lang});
    renderVersions();
    renderActive();
    renderScenarios();
    toast(message);
  } catch (error) { showError(error); }
}

function scenarioOrigin(scenario) {
  const builtinId = state.status.builtin_ids.includes(scenario.id);
  if (scenario.builtin) return ["builtin", T("built-in", "standaard")];
  if (builtinId) return ["edited", T("edited built-in", "aangepaste standaard")];
  return ["custom", T("own", "eigen")];
}

function renderScenarios() {
  const root = $("scenario-list");
  root.replaceChildren();
  for (const scenario of state.status.scenarios) {
    const item = el("article", "scenario-item" + (scenario.id === state.status.scenario_id ? " active" : ""));
    const badges = el("div", "badges-row");
    badges.append(el("span", `badge ${scenario.kind}`, scenario.kind === "flawed" ? T("with error", "met fout") : T("good", "goed")));
    const [origin, originText] = scenarioOrigin(scenario);
    badges.append(el("span", "badge", originText));
    if (scenario.id === state.status.scenario_id) badges.append(el("span", "badge active", T("active", "actief")));
    const contract = state.status.contract_types.find((c) => c.key === scenario.grid_contract_type);
    item.append(badges, el("h3", "", scenario.title_text), el("p", "", scenario.framing_text),
                el("p", "", `${scenario.date} · ${contract?.name || scenario.grid_contract_type}`
                  + (scenario.flaw?.type ? ` · ${T(...FLAW_TEXT[scenario.flaw.type] || [scenario.flaw.type, scenario.flaw.type])}` : "")));
    const actions = el("div", "item-actions");
    const button = (text, handler, extra="") => {
      const node = el("button", `ghost ${extra}`, text);
      node.type = "button";
      node.addEventListener("click", handler);
      actions.append(node);
    };
    button(T("Use", "Gebruiken"), () => save({scenario_id:scenario.id}, T("Scenario active.", "Scenario actief.")));
    button(T("Edit", "Bewerken"), () => openEditor(scenario, false));
    button(T("Duplicate", "Kopiëren"), () => openEditor(scenario, true));
    if (origin !== "builtin") {
      button(origin === "edited" ? T("Reset", "Herstellen") : T("Delete", "Verwijderen"), () => removeScenario(scenario, origin), "danger");
    }
    item.append(actions);
    root.append(item);
  }
}

function renderContractOptions() {
  const select = $("f-contract");
  select.replaceChildren();
  for (const contract of state.status.contract_types) {
    const option = el("option", "", contract.name);
    option.value = contract.key;
    option.title = contract.summary;
    select.append(option);
  }
  const flaw = $("f-flaw-type");
  flaw.replaceChildren();
  for (const type of ["", ...state.status.flaw_types]) {
    const option = el("option", "", T(...(FLAW_TEXT[type] || [type, type])));
    option.value = type;
    flaw.append(option);
  }
}

async function removeScenario(scenario, origin) {
  const question = origin === "edited"
    ? T(`Undo your changes to “${scenario.title_text}”?`, `Uw wijzigingen aan “${scenario.title_text}” ongedaan maken?`)
    : T(`Delete “${scenario.title_text}”?`, `“${scenario.title_text}” verwijderen?`);
  if (!window.confirm(question)) return;
  try {
    await api("/api/scenarios/delete", {scenario_id:scenario.id});
    toast(T("Done.", "Gedaan."));
    await load();
  } catch (error) { showError(error); }
}

// -- editor --------------------------------------------------------------------------

function hoursText(hours) {
  const sorted = [...(hours || [])].map(Number).sort((a, b) => a - b);
  if (!sorted.length) return "";
  const contiguous = sorted.every((h, i) => !i || h === sorted[i - 1] + 1);
  return contiguous && sorted.length > 2 ? `${sorted[0]}-${sorted.at(-1)}` : sorted.join(",");
}
function parseHours(text) {
  const hours = new Set();
  for (const part of String(text || "").split(/[,\s]+/).filter(Boolean)) {
    const range = part.match(/^(\d{1,2})-(\d{1,2})$/);
    if (range) {
      for (let h = Number(range[1]); h <= Number(range[2]); h++) if (h >= 0 && h <= 23) hours.add(h);
    } else if (/^\d{1,2}$/.test(part) && Number(part) <= 23) hours.add(Number(part));
    else throw new Error(T(`Cannot read the hours “${part}”.`, `Kan de uren “${part}” niet lezen.`));
  }
  return [...hours].sort((a, b) => a - b);
}
function parseSeries(text, label, scale=1) {
  const values = String(text || "").split(/[,;\s]+/).filter(Boolean).map((v) => Number(v.replace(",", ".")));
  if (!values.length) return [];
  if (values.length !== 24 || values.some((v) => !Number.isFinite(v))) {
    throw new Error(T(`${label}: give 24 numbers (now ${values.length}).`, `${label}: geef 24 getallen (nu ${values.length}).`));
  }
  return values.map((v) => v * scale);
}

function openEditor(scenario, duplicate) {
  state.editing = {original: duplicate ? null : scenario.id};
  $("editor").hidden = false;
  $("editor-title").textContent = duplicate || !scenario.id ? T("New scenario", "Nieuw scenario") : T("Edit scenario", "Scenario bewerken");
  $("f-id").value = duplicate ? `${scenario.id}-copy`.slice(0, 41) : (scenario.id || "");
  $("f-id").readOnly = Boolean(scenario.id) && !duplicate;
  $("f-kind").value = scenario.kind || "good";
  $("f-date").value = scenario.date || "2023-01-16";
  $("f-contract").value = scenario.grid_contract_type || "cbc";
  $("f-winter").checked = scenario.winter !== false;
  $("f-seed").value = scenario.seed ?? 0;
  $("f-sun").value = scenario.irradiance_scale ?? 1;
  for (const lang of ["en", "nl"]) {
    $(`f-title-${lang}`).value = scenario.title?.[lang] || "";
    $(`f-framing-${lang}`).value = scenario.framing?.[lang] || "";
    $(`f-debrief-${lang}`).value = scenario.debrief?.[lang] || "";
  }
  $("f-prices").value = (scenario.prices_eur_kwh || []).map((p) => +(p * 100).toFixed(2)).join(", ");
  $("f-temps").value = (scenario.temperatures_c || []).join(", ");
  for (const key of ["boiler_kw", "buffer_kwh", "battery_kwh", "import_limit_kw"]) {
    $(`f-${key}`).value = scenario.hub?.[key] ?? "";
  }
  const flaw = scenario.flaw || {};
  $("f-flaw-type").value = flaw.type || "";
  $("f-flaw-hours").value = hoursText(flaw.hours);
  $("f-flaw-import").value = flaw.import_kw ?? "";
  $("f-flaw-drop").value = flaw.night_temp_drop_c ?? "";
  updateFlawFields();
  renderPreview();
  $("editor").scrollIntoView({behavior:"smooth", block:"start"});
}

function updateFlawFields() {
  const type = $("f-flaw-type").value;
  document.querySelector(".flaw-hours").hidden = !["hidden_curtailment", "hidden_maintenance"].includes(type);
  document.querySelector(".flaw-import").hidden = type !== "hidden_curtailment";
  document.querySelector(".flaw-drop").hidden = type !== "forecast_miss";
  if (type && $("f-kind").value === "good") $("f-kind").value = "flawed";
}

function collect() {
  const number = (id) => ($(id).value.trim() === "" ? null : Number($(id).value));
  const hub = {};
  for (const key of ["boiler_kw", "buffer_kwh", "battery_kwh", "import_limit_kw"]) {
    const value = number(`f-${key}`);
    if (value !== null) hub[key] = value;
  }
  const type = $("f-flaw-type").value;
  const flaw = {type};
  if (type === "hidden_curtailment" || type === "hidden_maintenance") {
    flaw.hours = parseHours($("f-flaw-hours").value);
    if (!flaw.hours.length) throw new Error(T("Give the hours of the error.", "Geef de uren van de fout."));
  }
  if (type === "hidden_curtailment") flaw.import_kw = number("f-flaw-import") ?? 0;
  if (type === "hidden_maintenance") flaw.asset = "chp";
  if (type === "forecast_miss") flaw.night_temp_drop_c = number("f-flaw-drop") ?? 8;
  const texts = (prefix) => ({en:$(`f-${prefix}-en`).value.trim(), nl:$(`f-${prefix}-nl`).value.trim()});
  return {
    id:$("f-id").value.trim(),
    kind:$("f-kind").value,
    title:texts("title"), framing:texts("framing"), debrief:texts("debrief"),
    date:$("f-date").value,
    winter:$("f-winter").checked,
    seed:Number($("f-seed").value || 0),
    irradiance_scale:Number($("f-sun").value || 1),
    grid_contract_type:$("f-contract").value,
    prices_eur_kwh:parseSeries($("f-prices").value, T("Prices", "Prijzen"), 0.01),
    temperatures_c:parseSeries($("f-temps").value, T("Temperatures", "Temperaturen")),
    hub, flaw,
  };
}

async function saveScenario() {
  clearError();
  let scenario;
  try { scenario = collect(); } catch (error) { showError(error); return; }
  if (!scenario.title.en && !scenario.title.nl) { showError(T("Give the scenario a title.", "Geef het scenario een titel.")); return; }
  try {
    await api("/api/scenarios", {scenario});
    $("editor").hidden = true;
    toast(T("Scenario saved.", "Scenario opgeslagen."));
    await load();
  } catch (error) { showError(error); }
}

/** Prices and temperatures as two small charts on the same hour axis. */
function renderPreview() {
  const root = $("preview");
  root.replaceChildren();
  let prices, temps;
  try {
    prices = parseSeries($("f-prices").value, "p");
    temps = parseSeries($("f-temps").value, "t");
  } catch { return; }
  const node = (tag, attrs, parent) => {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.append(n);
    return n;
  };
  for (const [values, label] of [[prices, T("Power price (ct/kWh)", "Stroomprijs (ct/kWh)")],
                                 [temps, T("Outside (°C)", "Buiten (°C)")]]) {
    if (!values.length) continue;
    const W = 640, H = 120, L = 44, R = 10, top = 22, bottom = 22, step = (W - L - R) / 24;
    const chart = node("svg", {viewBox:`0 0 ${W} ${H}`, class:"svg-chart"}, null);
    const min = Math.min(...values, 0), max = Math.max(...values, 1);
    const y = (v) => top + (H - top - bottom) * (1 - (v - min) / (max - min));
    for (const v of [min, max]) {
      node("line", {x1:L, x2:W - R, y1:y(v), y2:y(v), class:"gridline"}, chart);
      node("text", {x:L - 6, y:y(v) + 4, class:"tick", "text-anchor":"end"}, chart).textContent = v.toFixed(0);
    }
    node("text", {x:L, y:14, class:"panel-label"}, chart).textContent = label;
    node("path", {d:values.map((v, h) => `${h ? "L" : "M"}${L + step * h + step / 2},${y(v)}`).join(""), class:"line-series"}, chart);
    for (const hour of [0, 6, 12, 18, 23]) {
      node("text", {x:L + step * hour + step / 2, y:H - 6, class:"tick", "text-anchor":"middle"}, chart)
        .textContent = `${String(hour).padStart(2, "0")}:00`;
    }
    root.append(chart);
  }
}

// -- documents ---------------------------------------------------------------------------

async function loadDocuments() {
  const root = $("doc-list");
  root.replaceChildren();
  try {
    const result = await api("/api/documents", {language:state.lang});
    for (const doc of result.documents) {
      const row = el("div", "memory-row");
      const what = el("span");
      what.append(el("strong", "", doc.title), el("small", "", `${doc.text.slice(0, 140)}${doc.text.length > 140 ? "…" : ""}`));
      const right = el("span", "item-actions");
      if (doc.builtin) right.append(el("span", "badge", T("built-in", "standaard")));
      else {
        const remove = el("button", "ghost danger", T("Delete", "Verwijderen"));
        remove.type = "button";
        remove.addEventListener("click", async () => {
          if (!window.confirm(T(`Delete “${doc.title}”?`, `“${doc.title}” verwijderen?`))) return;
          try { await api("/api/documents/delete", {id:doc.id}); await loadDocuments(); } catch (error) { showError(error); }
        });
        right.append(remove);
      }
      row.append(el("span", "muted", `${(doc.characters / 1000).toFixed(1)}k`), what, right);
      root.append(row);
    }
  } catch (error) { showError(error); }
}

async function saveDocument() {
  clearError();
  try {
    // A Word file is read on the server; its text replaces whatever is in the box.
    const upload = state.upload ? {filename:state.upload.name, docx_xml:state.upload.xml} : {};
    await api("/api/documents/save", {title:$("doc-title").value, text:$("doc-text").value, ...upload});
    state.upload = null;
    $("doc-title").value = "";
    $("doc-text").value = "";
    $("doc-file").value = "";
    toast(T("Document added.", "Document toegevoegd."));
    await loadDocuments();
  } catch (error) { showError(error); }
}

/** The text part (word/document.xml) of a Word file. A .docx is a zip archive; the
 *  pictures in it can make it megabytes, so only this part goes to the server. */
async function docxDocumentXml(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
    if (view.getUint32(i, true) === 0x06054b50) { end = i; break; }
  }
  if (end < 0) throw new Error(T("not a Word (.docx) file", "geen Wordbestand (.docx)"));
  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  for (let n = 0; n < count; n++) {
    if (view.getUint32(at, true) !== 0x02014b50) break;
    const method = view.getUint16(at + 10, true);
    const size = view.getUint32(at + 20, true);
    const nameLength = view.getUint16(at + 28, true);
    const extra = view.getUint16(at + 30, true), comment = view.getUint16(at + 32, true);
    const local = view.getUint32(at + 42, true);
    const name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nameLength));
    if (name === "word/document.xml") {
      const start = local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true);
      const data = bytes.subarray(start, start + size);
      if (method === 0) return new TextDecoder().decode(data);
      if (method !== 8 || typeof DecompressionStream === "undefined") {
        throw new Error(T("this browser cannot open it; paste the text", "deze browser kan het niet openen; plak de tekst"));
      }
      const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
      return await new Response(stream).text();
    }
    at += 46 + nameLength + extra + comment;
  }
  throw new Error(T("no text found in it", "er staat geen tekst in"));
}

function loadDocumentFile(event) {
  const file = event.target.files?.[0];
  state.upload = null;
  if (!file) return;
  if (!$("doc-title").value) $("doc-title").value = file.name.replace(/\.(txt|md|docx)$/i, "");
  const reader = new FileReader();
  if (/\.docx$/i.test(file.name)) {
    reader.onload = async () => {
      try {
        const xml = await docxDocumentXml(new Uint8Array(reader.result));
        state.upload = {name:file.name, xml};
        $("doc-text").value = "";
        $("doc-text").placeholder = T(`Word file “${file.name}” is read when you add it.`,
                                      `Wordbestand “${file.name}” wordt gelezen bij toevoegen.`);
      } catch (error) {
        showError(T(`Could not open “${file.name}”: ${error.message}`, `Kan “${file.name}” niet openen: ${error.message}`));
      }
    };
    reader.readAsArrayBuffer(file);
    return;
  }
  reader.onload = () => { $("doc-text").value = String(reader.result || ""); };
  reader.readAsText(file);
}

// -- memory -----------------------------------------------------------------------------

async function loadMemory() {
  const root = $("memory-list");
  root.replaceChildren();
  try {
    const result = await api("/api/memory", {everyone:true});
    if (!result.remembered.length) {
      root.append(el("p", "muted", T("Nothing remembered.", "Niets onthouden.")));
      return;
    }
    for (const item of result.remembered) {
      const row = el("div", "memory-row");
      const who = el("span");
      who.append(el("strong", "", item.participant || "local"), el("small", "", (item.created_at || "").slice(0, 16).replace("T", " ")));
      const what = el("span");
      what.append(el("span", "", `“${item.said}”`), el("small", "", item.summary));
      row.append(who, what, el("span", "badge", item.applies === "always" ? T("always", "altijd")
        : item.applies === "cold" ? T("when cold", "bij kou") : T("once", "eenmalig")));
      root.append(row);
    }
  } catch (error) { showError(error); }
}

async function forgetAll() {
  if (!window.confirm(T("Forget every remembered reason, for all participants?", "Alle onthouden redenen vergeten, voor alle deelnemers?"))) return;
  try {
    const result = await api("/api/memory/forget", {everyone:true});
    toast(T(`${result.forgotten} forgotten.`, `${result.forgotten} vergeten.`));
    await loadMemory();
  } catch (error) { showError(error); }
}

$("language-select").addEventListener("change", async (event) => {
  state.lang = event.target.value === "nl" ? "nl" : "en";
  writeStore("kasflex.demo.lang", state.lang);
  translate();
  await load();
});
$("save-active").addEventListener("click", () => save({
  scenario_id:$("active-scenario").value, lock_scenario:$("lock-scenario").checked,
}, T("Saved.", "Opgeslagen.")));
$("new-scenario").addEventListener("click", () => openEditor({kind:"good", winter:true, seed:0, irradiance_scale:1, grid_contract_type:"cbc"}, false));
$("close-editor").addEventListener("click", () => $("editor").hidden = true);
$("cancel-edit").addEventListener("click", () => $("editor").hidden = true);
$("save-scenario").addEventListener("click", saveScenario);
$("forget-all").addEventListener("click", forgetAll);
$("save-doc").addEventListener("click", saveDocument);
$("doc-file").addEventListener("change", loadDocumentFile);
$("f-flaw-type").addEventListener("change", updateFlawFields);
$("f-prices").addEventListener("input", renderPreview);
$("f-temps").addEventListener("input", renderPreview);

$("admin-unlock").addEventListener("click", unlock);
$("admin-login").addEventListener("submit", unlock);
$("admin-lock").addEventListener("click", async () => {
  try { await api("/api/admin/logout", {}); } catch {}
  showLogin();
});

translate();
if (state.token) start(); else showLogin();
