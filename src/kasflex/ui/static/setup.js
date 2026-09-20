/* Researcher setup page.
 *
 * Every field the scenario exposes, in one place, including the ones the grower
 * interface deliberately hides. Two habits carried over from the grower page:
 * text goes in through textContent, and nothing here silently rounds or reformats
 * a measurement on its way to the screen.
 *
 * Changes are held locally and applied to the *next* run rather than written back
 * to the YAML. The scenario file stays the reproducible record of what a run used;
 * a page that quietly rewrote it would make published figures untraceable.
 */

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const kid of kids.flat()) if (kid != null) node.append(kid);
  return node;
};

const state = { fields: [], values: {}, defaults: {}, consent: null };

const STUDY_PATHS = ["participant_id", "condition", "consent_version"];

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch { /* non-JSON */ }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function showError(error) {
  const box = $("error");
  box.textContent = String(error.message || error);
  box.hidden = false;
}
const clearError = () => { $("error").hidden = true; };

const LS_KEY = "kasflex.setup.overrides";
const loadOverrides = () => {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch { return {}; }
};
const saveOverrides = (value) => {
  try { localStorage.setItem(LS_KEY, JSON.stringify(value)); } catch { /* private mode */ }
};

/* ------------------------------------------------------------- settings */

function controlFor(field, value, onChange) {
  if (field.kind === "bool") {
    const input = el("input", { type: "checkbox", id: `s-${field.path}`, checked: Boolean(value) });
    input.addEventListener("change", () => onChange(input.checked));
    return input;
  }
  if (field.kind === "choice") {
    const select = el("select", { id: `s-${field.path}` });
    for (const choice of field.choices || []) {
      select.append(el("option", { value: choice, textContent: choice }));
    }
    select.value = value;
    select.addEventListener("change", () => onChange(select.value));
    return select;
  }
  if (field.kind === "textarea") {
    const area = el("textarea", { id: `s-${field.path}`, rows: 3, value: value ?? "" });
    area.addEventListener("change", () => onChange(area.value));
    return area;
  }
  const numeric = field.kind === "int" || field.kind === "number";
  const input = el("input", {
    type: numeric ? "number" : "text", id: `s-${field.path}`, value: value ?? "",
  });
  if (numeric) {
    if (field.min !== undefined) input.min = field.min;
    if (field.max !== undefined) input.max = field.max;
    if (field.step !== undefined) input.step = field.step;
  }
  input.addEventListener("change", () => {
    onChange(numeric ? (input.value === "" ? null : Number(input.value)) : input.value);
  });
  return input;
}

function renderSetting(field, root) {
  const value = state.values[field.path];
  const row = el("div", { className: "setting" });

  const label = el("div", { className: "label", textContent: field.label || field.path });
  if (field.scope === "researcher") {
    label.append(el("span", { className: "researcher-only", textContent: "researcher only" }));
  }
  const left = el("div", {}, label, el("div", { className: "path", textContent: field.path }));
  if (field.help) left.append(el("div", { className: "help", textContent: field.help }));

  const control = controlFor(field, value, (next) => {
    state.values[field.path] = next;
    const changed = next !== state.defaults[field.path];
    row.classList.toggle("changed", changed);
    markDirty();
  });
  // Read-only fields are shown so a researcher can see what is in force, but the
  // server refuses them as overrides, so offering an editable box would be a lie.
  if (field.readonly) {
    control.disabled = true;
    control.title = "Set in the scenario file";
  }
  const right = el("div", {}, control);
  if (field.readonly) {
    right.append(el("div", { className: "path", textContent: "scenario file only" }));
  }
  if (field.unit) right.append(el("div", { className: "path", textContent: field.unit }));

  row.classList.toggle("changed", value !== state.defaults[field.path]);
  row.append(left, right);
  root.append(row);
  return row;
}

/** Group by the leading path segment, so related knobs sit together. */
function groupOf(field) {
  if (STUDY_PATHS.includes(field.path)) return "Study";
  if (field.path.startsWith("hub.contract")) return "Grid connection";
  if (field.path.startsWith("hub.battery")) return "Battery";
  if (field.path.startsWith("hub.chp")) return "CHP";
  if (field.path.startsWith("hub.boiler")) return "Boiler";
  if (field.path.startsWith("hub.buffer")) return "Heat buffer";
  if (field.path.startsWith("hub.crop")) return "Crop limits";
  if (field.path.startsWith("hub.")) return "Greenhouse";
  if (field.path.startsWith("checker.")) return "Safety checker";
  if (field.path.startsWith("llm_")) return "AI model";
  return "Scenario";
}

function renderSettings() {
  const studyRoot = $("study-settings");
  const root = $("settings");
  studyRoot.replaceChildren();
  root.replaceChildren();

  const groups = new Map();
  for (const field of state.fields) {
    if (STUDY_PATHS.includes(field.path)) { renderSetting(field, studyRoot); continue; }
    const name = groupOf(field);
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(field);
  }

  for (const [name, fields] of groups) {
    const body = el("div");
    for (const field of fields) renderSetting(field, body);
    const details = el("details", { className: "group", open: name === "Scenario" },
      el("summary", {}, el("span", { textContent: name }),
        el("span", { className: "count", textContent: `${fields.length}` })),
      body);
    root.append(details);
  }
}

function overridesFromState() {
  const out = {};
  for (const field of state.fields) {
    if (field.readonly) continue;
    const value = state.values[field.path];
    if (value !== state.defaults[field.path] && value !== null && value !== undefined) {
      out[field.path] = value;
    }
  }
  return out;
}

function markDirty() {
  const changes = Object.keys(overridesFromState()).length;
  $("apply").disabled = changes === 0;
  $("status").textContent = changes
    ? `${changes} change${changes === 1 ? "" : "s"} not yet applied`
    : "No changes";
}

/* -------------------------------------------------------------- consent */

async function loadConsent() {
  const params = new URLSearchParams();
  if (state.values.participant_id) params.set("participant_id", state.values.participant_id);
  let status;
  try { status = await api(`/api/consent?${params}`); }
  catch (error) { showError(error); return; }
  state.consent = status;

  const root = $("consent-state");
  root.replaceChildren();
  root.append(el("p", {
    textContent: status.study_active
      ? `Study active. Consent text version "${status.version}".`
      : "No study running — nothing is gated and nothing is recorded against a participant.",
    style: "font-weight:600",
  }));

  if (status.study_active) {
    const scopes = el("ul", { className: "small muted", style: "margin:8px 0 0;padding-left:20px" });
    for (const [key, description] of Object.entries(status.scopes || {})) {
      scopes.append(el("li", { textContent: `${key} — ${description}` }));
    }
    root.append(scopes);
    if (status.participant_id) {
      root.append(el("p", {
        className: "small",
        textContent: status.needs_consent
          ? `"${status.participant_id}" has not consented to this version. Nothing will be recorded for them.`
          : `"${status.participant_id}" has consented.`,
      }));
    }
  }
  renderPeople(status.summary);
}

function renderPeople(summary) {
  const root = $("people");
  root.replaceChildren();
  if (!summary || !summary.participants) {
    root.append(el("p", { className: "muted", textContent: "No participants yet." }));
    return;
  }

  root.append(el("p", { className: "small muted", textContent:
    `${summary.participants} participant(s): ${summary.active} active, ${summary.withdrawn} withdrawn.` }));

  const table = el("table", { className: "people" });
  table.append(el("thead", {}, el("tr", {},
    ...["Scope", "Consented"].map((h) => el("th", { textContent: h })))));
  const body = el("tbody");
  for (const [scope, count] of Object.entries(summary.by_scope || {})) {
    body.append(el("tr", {},
      el("td", { textContent: scope }),
      el("td", { textContent: String(count) })));
  }
  table.append(body);
  root.append(table);

  const who = el("input", { type: "text", placeholder: "participant id",
    style: "font:inherit;padding:10px 12px;border-radius:10px;border:1.5px solid var(--line);min-height:44px" });
  const withdraw = el("button", {
    className: "danger", textContent: "Withdraw and erase",
    onclick: async () => {
      const participant = who.value.trim();
      if (!participant) { who.focus(); return; }
      withdraw.disabled = true;
      try {
        const result = await api("/api/consent/withdraw", { participant_id: participant });
        const rows = Object.entries(result.deleted || {})
          .map(([table, n]) => `${table}: ${n}`).join(", ") || "nothing";
        $("status").textContent = `Withdrew ${participant}. Deleted — ${rows}.`;
        who.value = "";
        loadConsent();
        loadReliance();
      } catch (error) { showError(error); }
      finally { withdraw.disabled = false; }
    },
  });
  root.append(el("div", { className: "button-row", style: "margin-top:14px" }, who, withdraw));
}

/* ------------------------------------------------------------- reliance */

const METRICS = [
  ["elicitations", "Decisions asked", ""],
  ["scored", "Scored", "outcome known"],
  ["disagreements", "Disagreements", ""],
  ["appropriate_reliance_rate", "Appropriate reliance", "followed when right, held when wrong"],
  ["over_reliance_rate", "Over-reliance", "followed a wrong suggestion"],
  ["under_reliance_rate", "Under-reliance", "ignored a right one"],
  ["rair", "RAIR", "switched when switching helped"],
  ["rsr", "RSR", "held when holding helped"],
  ["switch_rate", "Switch rate", "of disagreements"],
  ["mean_confidence", "Mean confidence", "1–5, stated before seeing the plan"],
  ["band_coverage", "Band coverage", "outcomes inside the range shown"],
  ["mean_absolute_prediction_error_eur", "Mean |error|", "EUR per day"],
];

function formatMetric(key, value) {
  if (value === null || value === undefined) return "—";
  if (key.endsWith("_rate") || key === "rair" || key === "rsr" || key === "band_coverage") {
    return `${(value * 100).toFixed(0)}%`;
  }
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
  return String(value);
}

async function loadReliance() {
  const condition = $("condition-filter").value.trim();
  const root = $("reliance");
  let metrics;
  try { metrics = await api(`/api/reliance?condition=${encodeURIComponent(condition)}`); }
  catch (error) { showError(error); return; }

  root.replaceChildren();
  for (const [key, label, note] of METRICS) {
    const value = metrics[key];
    root.append(el("div", { className: "metric" },
      el("div", { className: "n", textContent: formatMetric(key, value) }),
      el("div", { className: "k" }, el("span", { textContent: label }),
        note ? el("small", { textContent: note }) : null)));
  }
}

$("condition-filter").addEventListener("change", loadReliance);

/* ----------------------------------------------------------------- boot */

$("apply").addEventListener("click", () => {
  const overrides = overridesFromState();
  saveOverrides(overrides);
  // The grower page reads this key, so a change here reaches the next run there.
  try {
    const existing = JSON.parse(localStorage.getItem("kasflex.grower.settings") || "{}");
    localStorage.setItem("kasflex.grower.settings", JSON.stringify({ ...existing, ...overrides }));
  } catch { /* private mode */ }
  $("status").textContent = `Applied. ${Object.keys(overrides).length} setting(s) will be used on the next run.`;
  $("apply").disabled = true;
  loadConsent();
});

$("reset").addEventListener("click", () => {
  state.values = { ...state.defaults };
  saveOverrides({});
  renderSettings();
  markDirty();
  $("status").textContent = "Changes discarded.";
});

async function boot() {
  clearError();
  let settings;
  try { settings = await api("/api/settings"); }
  catch (error) { showError(error); return; }

  state.fields = settings.fields;
  state.defaults = Object.fromEntries(settings.fields.map((f) => [f.path, f.value]));
  state.values = { ...state.defaults, ...loadOverrides() };

  renderSettings();
  markDirty();
  await loadConsent();
  await loadReliance();
}

boot();
