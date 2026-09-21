"use strict";

/* KasFlex interface.
 *
 * No framework and no build step: this is one page talking to a local server, and
 * a toolchain would sit between a researcher and a one-line change.
 *
 * Two rules the code enforces rather than trusts:
 *   - An edited plan is never approvable until it has been re-verified. The
 *     Approve button disables the moment a cell changes.
 *   - The server decides feasibility. Nothing here judges a plan; it only shows
 *     what came back.
 */

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const api = async (path, body) => {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `${res.status} ${res.statusText}` }));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
};

const HEAT = ["boiler", "chp", "buffer", "none"];
const BATT = ["idle", "charge", "discharge"];
const CHP = ["off", "heat_led", "max_export"];
const CO2 = ["none", "chp", "liquid"];

const state = {
  fields: [],
  defaults: {},
  plan: [],
  dirty: false,
  verified: true,
  runOverrides: {},
  runSettings: {},
  hasRun: false,
  shownAt: null,   // when the plan appeared, for the decision-time metric (R26)
};

function renderMetricRows(root, metrics) {
  root.replaceChildren();
  for (const [key, value] of Object.entries(metrics || {})) {
    const row = document.createElement("tr");
    const label = document.createElement("td");
    const amount = document.createElement("td");
    label.textContent = key.replace(/_/g, " ");
    amount.className = "num";
    amount.textContent = num(value, 2);
    row.append(label, amount);
    root.appendChild(row);
  }
}

/* ------------------------------------------------------------- settings */

function buildSettings(payload) {
  state.fields = payload.fields;
  $("scenario-name").textContent = payload.scenario.replace(/-/g, " ");
  $("scenario-summary").textContent = payload.scenario.replace(/-/g, " ");
  $("site-name").textContent = payload.scenario.replace(/-/g, " ");
  const form = $("settings-form");
  form.innerHTML = "";

  const groups = {};
  const descriptions = {
    'Basics':'Choose a day, your data, and how the plan should be made.',
    'Greenhouse':'Describe your greenhouse and the light your crop needs.',
    'Energy system':'Set the equipment and connection limits for this site.',
    'Data sources':'Check what is available before you run a real-data estimate.',
    'APIs':'Connect your data providers. Keys stay on this computer.',
    'Advanced':'Research controls. The defaults are a good starting point.'
  };
  $('configuration-nav').replaceChildren();
  for (const [i,title] of Object.keys(descriptions).entries()) {
    const group = document.createElement('section');
    group.className = 'settings-group'; group.dataset.section=title;
    group.id=`configuration-panel-${i}`;group.setAttribute('role','tabpanel');group.setAttribute('aria-labelledby',`configuration-tab-${i}`);
    const heading=document.createElement('h3');heading.textContent=title;
    const intro=document.createElement('p');intro.className='section-intro';intro.textContent=descriptions[title];
    group.append(heading,intro);form.appendChild(group);groups[title]=group;
    const button=document.createElement('button');button.type='button';button.id=`configuration-tab-${i}`;button.textContent=title;button.dataset.section=title;button.setAttribute('role','tab');button.setAttribute('aria-controls',group.id);
    button.addEventListener('click',()=>selectConfigurationSection(title));
    button.addEventListener('keydown',e=>{
      if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;
      e.preventDefault();const names=Object.keys(descriptions);let next=e.key==='Home'?0:e.key==='End'?names.length-1:(i+(e.key==='ArrowDown'?1:-1)+names.length)%names.length;
      selectConfigurationSection(names[next]);$('configuration-nav').children[next].focus();
    });
    $('configuration-nav').appendChild(button);
  }
  const basicOrder=['data_source','date','planner','brief','checker.enabled'];
  const displayFields=[...payload.fields].sort((a,b)=>{const ai=basicOrder.indexOf(a.path),bi=basicOrder.indexOf(b.path);return (ai<0?99:ai)-(bi<0?99:bi);});
  for (const f of displayFields) {
    state.defaults[f.path] = f.value;
    const wrap = document.createElement("div");
    wrap.className = "field" + (f.kind === "bool" ? " bool" : "");

    const label = document.createElement("label");
    label.htmlFor = `f-${f.path}`;
    label.textContent = ({planner:'Planning method',date:'Day to plan',brief:'What matters for this day?',winter:'Use winter demo weather', 'hub.floor_area_m2':'Greenhouse size', 'hub.contract.import_limit_kw':'Maximum electricity import', 'hub.contract.export_limit_kw':'Maximum electricity export',seed:'Repeatability seed'})[f.path] || f.label;
    if(f.unit) label.append(' ');
    if (f.unit) {
      const u = document.createElement("span");
      u.className = "unit";
      u.textContent = `(${f.unit})`;
      label.appendChild(u);
    }

    let input;
    if (f.kind === "choice") {
      input = document.createElement("select");
      for (const c of f.choices) {
        const o = document.createElement("option");
        o.value = c; o.textContent = ({demo:'Real-input demo',synthetic:'Synthetic test data',cache:'Downloaded real data', collaborative:'KasFlex collaborative planner', 'rule-based':'Standard baseline', learned:'Research demand planner', naive:'Simple planner',llm:'Language model — setup required',mpc:'MPC — not available yet'})[c] || c;
        if(c==='mpc' || c==='llm')o.disabled=true;
        input.appendChild(o);
      }
      input.value = f.value;
    } else if (f.kind === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(f.value);
    } else if (f.kind === "textarea") {
      input = document.createElement("textarea");
      input.value = f.value ?? "";
    } else if (f.kind === "text") {
      input = document.createElement("input");
      input.type = f.path === "date" ? "date" : "text";
      input.value = f.value ?? "";
    } else {
      input = document.createElement("input");
      input.type = "number";
      if (f.min !== undefined) input.min = f.min;
      if (f.max !== undefined) input.max = f.max;
      if (f.step !== undefined) input.step = f.kind === "int" ? f.step : "any";
      input.value = f.value;
    }
    input.id = `f-${f.path}`;
    input.dataset.path = f.path;
    input.dataset.kind = f.kind;

    if (f.kind === "bool") { wrap.appendChild(input); wrap.appendChild(label); }
    else { wrap.appendChild(label); wrap.appendChild(input); }

    if (f.help) {
      const h = document.createElement("p");
      h.className = "help";
      h.textContent = ({planner:'Start with Standard. The experimental demand planner still trains on simulated history.',date:'Choose the date you want to estimate. Published prices may not be available far ahead.', 'checker.enabled':'Checks the plan against limits. Keep this on for normal use.',brief:'Describe a goal or planned event, such as limiting evening imports. The standard planner may not interpret every instruction.', 'hub.floor_area_m2':'5 hectares = 50,000 m². The research compartment is 96 m².'})[f.path] || f.help;
      wrap.appendChild(h);
    }
    const title = ['data_source','date','planner','brief','checker.enabled'].includes(f.path) ? 'Basics' : ['hub.floor_area_m2','hub.crop.dli_target_mol_m2','winter'].includes(f.path) ? 'Greenhouse' : ['latitude','longitude','gas_price_eur_kwh'].includes(f.path) ? 'Data sources' : f.path.startsWith('hub.') ? 'Energy system' : 'Advanced';
    groups[title].appendChild(wrap);
    input.addEventListener('input',updateConfigurationSummary);
  }
  const tomorrow=document.createElement('button');tomorrow.type='button';tomorrow.className='text-button tomorrow-button';tomorrow.textContent='Use tomorrow';
  tomorrow.addEventListener('click',()=>{const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Amsterdam',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const d=Object.fromEntries(parts.map(p=>[p.type,p.value]));const t=new Date(`${d.year}-${d.month}-${d.day}T12:00:00Z`);t.setUTCDate(t.getUTCDate()+1);$('f-date').value=t.toISOString().slice(0,10);updateConfigurationSummary();});
  $('f-date').parentElement.appendChild(tomorrow);
  const sourcePanel=document.createElement('div');sourcePanel.className='source-panel';sourcePanel.innerHTML='<h4>Download once. Run offline.</h4><p>Netherlands electricity prices: ENTSO-E. Weather: Open-Meteo. A live gas feed is not connected.</p><div class="source-actions"><button id="check-data" type="button">Check availability</button><button id="download-data" type="button">Download for this day</button></div><div id="data-status" role="status">Choose a date, then check availability. Add your ENTSO-E key in the APIs section to download prices.</div><p class="small">For an earlier date, use an existing cache. Archived forecast downloads are not connected yet. Published future prices may not be available.</p>';
  groups['Data sources'].appendChild(sourcePanel);
  $('check-data').addEventListener('click',()=>checkData(false));$('download-data').addEventListener('click',()=>checkData(true));
  const apiList=document.createElement('div');apiList.id='api-connections-list';apiList.textContent='Loading API connections…';groups['APIs'].appendChild(apiList);
  loadConnections();
  if(!state.restored){
    state.restored=true;
    try{const saved=JSON.parse(localStorage.getItem('kasflex.configuration.v1')||'{}');applyFieldValues(saved);}catch{}
  }
  selectConfigurationSection('Basics');updateConfigurationSummary();
}

/** Only send what the user actually changed, so a run is reproducible from the
 *  scenario file plus a short list of overrides. */
function overrides() {
  const out = {};
  for (const f of state.fields) {
    const el = $(`f-${f.path}`);
    if (!el) continue;
    let v;
    if (f.kind === "bool") v = el.checked;
    else if (f.kind === "int") v = parseInt(el.value, 10);
    else if (f.kind === "number") v = parseFloat(el.value);
    else v = el.value;
    if (f.kind === "int" && Number.isNaN(v)) continue;
    if (f.kind === "number" && Number.isNaN(v)) continue;
    if (v !== state.defaults[f.path]) out[f.path] = v;
  }
  return out;
}

/* -------------------------------------------------------------- helpers */

const eur = (v) => "€ " + Number(v).toLocaleString("en-GB", { maximumFractionDigits: 0 });
const num = (v, d = 0) => Number(v).toLocaleString("en-GB",
  { minimumFractionDigits: d, maximumFractionDigits: d });

function busy(on) {
  document.body.classList.toggle("busy", on);
  $("run").textContent = on ? "Generating…" : "Generate daily plan";
  $("loading-overlay").hidden = !on;
  document.querySelectorAll('#run,#start-plan,#compare,#reverify,#approve,#reject,#apply-settings,#reset,#export-plan,#export-pdf').forEach(el => {
    if (on) { el.dataset.wasDisabled = String(el.disabled); el.disabled = true; }
    else if (el.dataset.wasDisabled !== undefined) { el.disabled = el.dataset.wasDisabled === "true"; delete el.dataset.wasDisabled; }
  });
  if (!on && state.hasRun) { $("export-plan").disabled = false; $("export-pdf").disabled = false; $("reverify").disabled = !state.dirty; $("approve").disabled = state.dirty || !state.approvable || Boolean(state.decision); $("reject").disabled = Boolean(state.decision); }
  $("run").setAttribute("aria-busy", String(on));
}

function showError(err) {
  const box = $("error");
  box.textContent = String(err.message || err);
  box.hidden = false;
  $("empty").hidden = true;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* --------------------------------------------------------------- render */

function renderOutcome(r) {
  $("empty").hidden = true;
  $("error").hidden = true;
  $("outcome").hidden = false;
  $("elapsed").textContent = `ran in ${r.elapsed_s}s`;

  state.reference = {run_id:r.run_id, revision:r.revision, plan_hash:r.plan_hash};
  state.decision = null;
  state.originalPlan = null;
  state.runOverrides = { ...r.overrides };
  state.runSettings = r.configuration || Object.fromEntries(state.fields.map(f => [f.path, state.runOverrides[f.path] ?? state.defaults[f.path]]));
  state.hasRun = true;
  state.approvable = Boolean(r.accepted && r.checker_enabled);
  $("review-empty").hidden = true;
  $("review-content").hidden = false;
  $("export-plan").disabled = false;
  renderSnapshot(r);
  $("revision-label").textContent = `Saved plan ${r.run_id.slice(0,8)} · revision ${r.revision}`;
  $('data-basis').textContent = (r.data_source === 'cache' || r.data_source === 'demo') ? (r.actuals_available ? 'Real market/weather inputs · evaluated with separate realised weather · greenhouse outcomes remain simulated.' : 'Real market prices and forecast weather · realised weather is not available yet · greenhouse outcomes remain simulated.') : 'Synthetic test inputs · greenhouse outcomes are simulated.';
  const m = r.metrics;
  renderCostForecast(r.cost_forecast);
  $("stat-cost").textContent = eur(m.net_cost_eur);
  $("stat-cost-m2").textContent = `€ ${num(m.net_cost_eur_per_m2, 3)} per m²`;
  $("stat-growth").textContent = r.edited_preview ? "—" : num(m.fruit_growth_kg_m2, 3) + " kg/m²";
  $("stat-band").textContent = r.edited_preview ? "Crop outcome not recomputed for this edited preview" : `${num(m.temperature_band_hours)} of 24 h in the crop band`;

  $("stat-violations").textContent = r.realised_hard ?? "—";
  $("stat-projected").textContent = r.realised_projected
    ? `${r.realised_projected} projected (climate bands)`
    : r.edited_preview ? "Edited preview: inspect the checker verdict" : "none projected";
  $("card-violations").className = "stat " + (r.realised_hard ? "bad" : "good");

  const badge = $("verdict-badge");
  if (!r.checker_enabled) {
    badge.textContent = "not verified";
    badge.className = "badge no";
  } else {
    badge.textContent = r.accepted ? "accepted" : "rejected";
    badge.className = "badge " + (r.accepted ? "ok" : "no");
  }
  renderVerdict(r.accepted, r.feedback, r.violations, r.checker_enabled);

  const notes = [];
  if (!r.checker_enabled) notes.push("Turn the checker back on to see what it would have caught.");
  if (r.fell_back) notes.push(`The planner was rejected ${r.revisions_used} time(s); the rule-based baseline took over.`);
  $("verdict-note").textContent = notes.join(" ");

  $("model-note").textContent = r.validated
    ? `Greenhouse model: ${r.greenhouse_model}.`
    : `Greenhouse model “${r.greenhouse_model}” has a measured replay, but is not calibrated for operational use. These figures are research estimates.`;

  renderMetricRows($("metrics"), m);

  renderPlan(r.plan);
  renderChart(r.plan);
  renderWeatherChart(r.plan);
  renderSocChart(r.plan, r.battery_config);
  renderDispatch();
  renderAssetCards(r.plan);
  renderNarrative(r.plan);
  updateReviewSummary(r);
  state.shownAt = performance.now();
  markVerified(true);
  $("approve").disabled = !r.accepted || !r.checker_enabled;
  if (!r.checker_enabled) {
    $("approve").disabled = true;
    $("decision-note").textContent =
      "Nothing to approve: this plan was never verified. Approval exists to record a " +
      "human decision on a checked plan.";
  }
}

function select(options, value, onChange) {
  const el = document.createElement("select");
  for (const o of options) {
    const opt = document.createElement("option");
    opt.value = o; opt.textContent = o.replace(/_/g, " ");
    el.appendChild(opt);
  }
  el.value = value;
  el.addEventListener("change", onChange);
  return el;
}

function renderPlan(plan) {
  state.plan = plan.map((p) => ({ ...p }));
  if (!state.originalPlan) state.originalPlan = plan.map((p) => ({ ...p }));
  const body = document.querySelector("#plan tbody");
  body.innerHTML = "";

  state.plan.forEach((row, i) => {
    const tr = document.createElement("tr");
    const orig = state.originalPlan[i];
    const touched = () => {
      tr.classList.add("edited");
      markVerified(false);
      renderDispatch();
      highlightChanges(tr, row, orig);
    };

    const cell = (html, cls) => {
      const td = document.createElement("td");
      if (cls) td.className = cls;
      if (typeof html === "string") td.textContent = html;
      else td.appendChild(html);
      tr.appendChild(td);
      return td;
    };

    cell(String(row.hour).padStart(2, "0"));
    cell("€ " + row.power_price_eur_kwh.toFixed(3), "num");
    cell(num(row.heat_demand_kw) + " kW", "num");

    cell(select(HEAT, row.heat_source, (e) => { row.heat_source = e.target.value; touched(); }));

    const lamp = document.createElement("input");
    lamp.type = "number"; lamp.min = 0; lamp.max = 1; lamp.step = 0.05;
    // Round for display: an optimiser happily emits 0.1157, which is noise to a
    // grower and makes the column unreadable.
    const lamps = (v) => Math.round(Math.min(1, Math.max(0, v)) * 100) / 100;
    lamp.value = lamps(row.lighting_level).toFixed(2);
    lamp.addEventListener("input", (e) => {
      row.lighting_level = lamps(parseFloat(e.target.value) || 0);

      touched();
    });
    lamp.addEventListener("change", () => lamp.value = row.lighting_level.toFixed(2));
    cell(lamp, "num");

    const batWrap = document.createElement("span");
    batWrap.appendChild(select(BATT, row.battery, (e) => { row.battery = e.target.value; touched(); }));
    const kw = document.createElement("input");
    kw.type = "number"; kw.min = 0; kw.step = 50; kw.value = row.battery_power_kw;
    kw.addEventListener("input", (e) => {
      row.battery_power_kw = Math.max(0, parseFloat(e.target.value) || 0);

      touched();
    });
    kw.addEventListener("change", () => kw.value = row.battery_power_kw);
    batWrap.appendChild(kw);
    cell(batWrap);

    cell(select(CHP, row.chp_mode, (e) => { row.chp_mode = e.target.value; touched(); }));
    cell(select(CO2, row.co2_source, (e) => { row.co2_source = e.target.value; touched(); }));
    cell(row.reasoning || "", "why");

    tr.querySelectorAll('input,select').forEach((el, index) => el.setAttribute('aria-label', `Hour ${row.hour}: ${['heat source','lighting level','battery mode','battery power','CHP mode','CO2 source'][index]}`));
    body.appendChild(tr);
  });
}

/** An edited plan cannot be approved until the checker has seen it (R23). */
function markVerified(ok) {
  if (!ok) { $("review-title").textContent = "Edits need verification"; $("review-summary").textContent = "Re-check your updated hourly intent before recording approval."; document.querySelector(".review-teaser").classList.add("needs-review"); $("verdict-badge").textContent = "edits pending"; $("verdict-badge").className = "badge no"; }
  state.verified = ok;
  state.dirty = !ok;
  if ($('cost-forecast')) $('cost-forecast').hidden = !ok || !state.costForecast;
  $("reverify").disabled = ok;
  $("approve").disabled = !ok || !state.approvable;
  $("decision-note").textContent = ok
    ? ""
    : "Plan edited. Re-verify before approving — an edit is checked like any other plan.";
}

/* -------------------------------------------------------- asset cards */

function renderAssetCards(plan) {
  const root = $('asset-cards');
  if (!plan || !plan.length) { root.hidden = true; return; }
  root.hidden = false;
  root.replaceChildren();

  const totalHours = plan.length;
  const heatingHours = plan.filter(p => p.heat_source !== 'none').length;
  const litHours = plan.filter(p => p.lighting_level > 0).length;
  const avgLight = plan.reduce((s, p) => s + p.lighting_level, 0) / totalHours;
  const battActive = plan.filter(p => p.battery !== 'idle').length;
  const battCharge = plan.filter(p => p.battery === 'charge').length;
  const battDischarge = plan.filter(p => p.battery === 'discharge').length;
  const chpActive = plan.filter(p => p.chp_mode !== 'off').length;

  const cards = [
    {
      cls: 'heating',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 3c-6 7 6 11 0 18m6-18c-6 7 6 11 0 18m6-18c-6 7 6 11 0 18"/></svg>',
      name: 'Heating',
      value: `${heatingHours} h`,
      pct: heatingHours / totalHours * 100,
      desc: heatingHours === 0 ? 'No heating needed today.'
        : `Active ${heatingHours} of ${totalHours} hours. Primary source: ${mostCommon(plan.map(p => p.heat_source).filter(h => h !== 'none'))}.`,
    },
    {
      cls: 'lighting',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="4"/><path d="M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2"/></svg>',
      name: 'Grow lights',
      value: `${Math.round(avgLight * 100)}%`,
      pct: avgLight * 100,
      desc: litHours === 0 ? 'Lights off all day — enough sunlight.'
        : `On for ${litHours} hours, averaging ${Math.round(avgLight * 100)}% intensity.`,
    },
    {
      cls: 'battery',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="6" width="17" height="12" rx="3"/><path d="M23 10v4M7 10v4m4-4v4m4-4v4"/></svg>',
      name: 'Battery',
      value: battActive === 0 ? 'Idle' : `${battActive} h`,
      pct: battActive / totalHours * 100,
      desc: battActive === 0 ? 'Battery stays idle today.'
        : `Charges ${battCharge} h, discharges ${battDischarge} h. Shifts energy to cheaper hours.`,
    },
    {
      cls: 'chp',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="m13 2-8 12h6l-1 8 9-13h-7Z"/></svg>',
      name: 'CHP',
      value: chpActive === 0 ? 'Off' : `${chpActive} h`,
      pct: chpActive / totalHours * 100,
      desc: chpActive === 0 ? 'CHP stays off — grid power is cheaper.'
        : `Runs ${chpActive} hours, producing heat and electricity together.`,
    },
  ];

  for (const c of cards) {
    const card = document.createElement('article');
    card.className = 'asset-card';
    const head = document.createElement('div'); head.className = 'asset-card-head';
    const icon = document.createElement('div'); icon.className = `asset-card-icon ${c.cls}`;
    icon.innerHTML = c.icon; // Static, developer-owned SVG only.
    const name = document.createElement('span'); name.className = 'asset-card-name'; name.textContent = c.name;
    head.append(icon, name);
    const value = document.createElement('span'); value.className = 'asset-card-value'; value.textContent = c.value;
    const bar = document.createElement('div'); bar.className = 'asset-card-bar';
    const fill = document.createElement('div'); fill.className = `asset-card-fill ${c.cls}`;
    fill.style.width = `${Math.max(0, Math.min(100, Math.round(Number(c.pct) || 0)))}%`;
    bar.appendChild(fill);
    const description = document.createElement('p'); description.className = 'asset-card-desc'; description.textContent = c.desc;
    card.append(head, value, bar, description);
    root.appendChild(card);
  }
}

function mostCommon(arr) {
  const counts = {};
  for (const v of arr) counts[v] = (counts[v] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || '—';
}

/* ----------------------------------------------------- narrative plan */

function renderNarrative(plan) {
  const panel = $('plan-narrative');
  const content = $('narrative-content');
  if (!plan || !plan.length) { panel.hidden = true; return; }

  const phases = [];
  let current = null;
  for (const iv of plan) {
    const key = `${iv.heat_source}|${iv.battery}|${iv.chp_mode}|${iv.lighting_level > 0 ? 'lit' : 'dark'}`;
    if (!current || current.key !== key) {
      current = { key, start: iv.hour, end: iv.hour, intervals: [iv] };
      phases.push(current);
    } else {
      current.end = iv.hour;
      current.intervals.push(iv);
    }
  }

  content.replaceChildren();
  const grid = document.createElement('div');
  grid.className = 'narrative-phases';

  for (const phase of phases) {
    const el = document.createElement('div');
    el.className = 'narrative-phase';

    const timeRange = phase.start === phase.end
      ? `${String(phase.start).padStart(2, '0')}:00`
      : `${String(phase.start).padStart(2, '0')}:00 – ${String(phase.end).padStart(2, '0')}:59`;
    const duration = phase.end - phase.start + 1;

    const iv = phase.intervals[0];
    const title = phaseTitle(iv);
    const description = phaseDescription(iv, duration);
    const avgPrice = phase.intervals.reduce((s, p) => s + p.power_price_eur_kwh, 0) / phase.intervals.length;

    const time = document.createElement('div'); time.className = 'phase-time'; time.textContent = timeRange;
    const durationLabel = document.createElement('small'); durationLabel.textContent = `${duration} hour${duration > 1 ? 's' : ''}`;
    time.appendChild(durationLabel);
    const body = document.createElement('div'); body.className = 'phase-body';
    const heading = document.createElement('h3'); heading.textContent = title;
    const copy = document.createElement('p'); copy.textContent = description;
    const cost = document.createElement('span'); cost.className = 'phase-cost'; cost.textContent = `Avg. electricity: €${avgPrice.toFixed(3)}/kWh`;
    body.append(heading, copy, cost); el.append(time, body);
    grid.appendChild(el);
  }

  content.appendChild(grid);
  panel.hidden = false;
}

function phaseTitle(iv) {
  if (iv.battery === 'charge') return 'Charge the battery';
  if (iv.battery === 'discharge') return 'Discharge the battery';
  if (iv.chp_mode === 'max_export') return 'CHP at full output';
  if (iv.chp_mode === 'heat_led') return 'CHP follows heat demand';
  if (iv.lighting_level > 0 && iv.heat_source !== 'none') return 'Lights and heating on';
  if (iv.lighting_level > 0) return 'Grow lights on';
  if (iv.heat_source === 'boiler') return 'Boiler keeps the greenhouse warm';
  if (iv.heat_source === 'buffer') return 'Draw heat from the buffer';
  if (iv.heat_source === 'chp') return 'CHP provides heat';
  return 'Steady state — minimal energy';
}

function phaseDescription(iv, hours) {
  const parts = [];
  if (iv.battery === 'charge')
    parts.push(`Power is stored at ${num(iv.battery_power_kw)} kW while electricity is cheap.`);
  else if (iv.battery === 'discharge')
    parts.push(`The battery supplies ${num(iv.battery_power_kw)} kW, reducing grid import.`);

  if (iv.heat_source === 'boiler') parts.push('The boiler provides heating.');
  else if (iv.heat_source === 'buffer') parts.push('Stored heat from the buffer covers the demand.');
  else if (iv.heat_source === 'chp') parts.push('CHP waste heat covers heating needs.');

  if (iv.lighting_level > 0)
    parts.push(`Grow lights at ${Math.round(iv.lighting_level * 100)}% intensity.`);

  if (iv.co2_source === 'liquid') parts.push('Liquid CO₂ for enrichment.');
  else if (iv.co2_source === 'chp') parts.push('CHP exhaust provides CO₂.');

  return parts.join(' ') || 'Equipment stays idle to save costs.';
}

/* ------------------------------------------------ structured verdict */

const CONSTRAINT_LABELS = {
  'grid.import_limit': 'Grid import exceeds your contract limit',
  'grid.export_limit': 'Grid export exceeds your contract limit',
  'battery.power_limit': 'Battery power exceeds its rating',
  'battery.capacity': 'Battery would be over- or undercharged',
  'chp.heat_only_when_running': 'CHP heat requested but engine is off',
  'boiler.capacity': 'Boiler capacity exceeded',
  'heat_buffer.capacity': 'Heat buffer capacity exceeded',
  'dli.below_minimum': 'Not enough light for the crop today',
  'dli.above_maximum': 'Too much light for the crop today',
  'temperature.below_band': 'Greenhouse temperature below the safe band',
  'temperature.above_band': 'Greenhouse temperature above the safe band',
  'humidity.above_band': 'Humidity above the safe band',
  'co2.above_band': 'CO₂ concentration above the safe band',
};

function renderVerdict(accepted, feedback, violations, checkerEnabled) {
  const root = $('verdict-text');
  root.replaceChildren();

  if (!checkerEnabled) {
    const msg = document.createElement('p');
    msg.className = 'verdict-disabled';
    msg.textContent = 'The safety checker is turned off. Approval is unavailable until a plan has been verified.';
    root.appendChild(msg);
    return;
  }

  if (accepted && (!violations || violations.length === 0)) {
    const msg = document.createElement('p');
    msg.className = 'verdict-accepted';
    msg.textContent = 'All limits respected. This plan is safe to approve.';
    root.appendChild(msg);
    return;
  }

  if (violations && violations.length > 0) {
    const hard = violations.filter(v => v.severity === 'hard');
    const projected = violations.filter(v => v.severity === 'projected');

    if (hard.length > 0) {
      const summary = document.createElement('p');
      summary.className = 'verdict-summary';
      summary.textContent = `${hard.length} hard limit${hard.length > 1 ? 's' : ''} breached. These must be fixed before approval.`;
      root.appendChild(summary);
    }

    const list = document.createElement('div');
    list.className = 'violation-list';

    for (const v of [...hard, ...projected]) {
      const card = document.createElement('div');
      card.className = `violation-card ${v.severity}`;

      const label = CONSTRAINT_LABELS[v.constraint] || v.constraint.replace(/[_.]/g, ' ');
      const hourStr = v.hour !== null && v.hour !== undefined ? `Hour ${String(v.hour).padStart(2, '0')}` : 'Whole day';

      const heading = document.createElement('strong'); heading.textContent = label;
      const detail = document.createElement('span');
      detail.textContent = `${hourStr}: needs ${num(v.actual, 1)} ${v.unit}, limit is ${num(v.bound, 1)} ${v.unit}. ${v.severity === 'hard' ? 'Over by ' + num(Math.abs(v.actual - v.bound), 1) + ' ' + v.unit + '.' : 'Projected from the greenhouse model.'}`;
      card.append(heading, detail);
      list.appendChild(card);
    }

    root.appendChild(list);

    if (projected.length > 0 && hard.length === 0) {
      const note = document.createElement('p');
      note.className = 'verdict-summary';
      note.style.marginTop = '12px';
      note.textContent = `${projected.length} projected violation${projected.length > 1 ? 's' : ''} from the climate model. The plan can still be approved — these are estimates, not hard limits.`;
      root.appendChild(note);
    }
  }

  if (feedback && (!violations || violations.length === 0)) {
    const fallback = document.createElement('p');
    fallback.className = 'verdict-summary';
    fallback.textContent = feedback;
    root.appendChild(fallback);
  }
}

/* ------------------------------------------------------------- actions */

async function run() {
  busy(true);
  try {
    if (!validateSettings()) { moveSheet(true); return; }
    const result = await api("/api/run", { overrides: overrides() });
    renderOutcome(result);
    try { localStorage.setItem('kasflex.lastRun.v1', JSON.stringify(result)); } catch {}
    navigate("overview");
    $("comparison").hidden = true;
  } catch (e) { showError(e); } finally { busy(false); }
}

async function reverify() {
  busy(true);
  try {
    const r = await api("/api/verify", { ...state.reference, plan: state.plan });
    renderCostForecast(r.cost_forecast);
    state.reference = {run_id:r.run_id, revision:r.revision, plan_hash:r.plan_hash};
    state.decision = null;
    renderPlan(r.plan);
    $("revision-label").textContent = `Saved plan ${r.run_id.slice(0,8)} · revision ${r.revision}`;
    const badge = $("verdict-badge");
    badge.textContent = r.accepted ? "accepted" : "rejected";
    badge.className = "badge " + (r.accepted ? "ok" : "no");
    renderVerdict(r.accepted, r.feedback, r.violations, true);
    $("stat-growth").textContent = "—";
    $("stat-band").textContent = "Crop outcome unavailable for edited plan";
    $("stat-violations").textContent = "—";
    $("stat-projected").textContent = "Edited plan: inspect the safety review below";
    $("card-violations").className = "stat";
    renderMetricRows($("metrics"), r.metrics);
    $("stat-cost").textContent = eur(r.metrics.net_cost_eur);
    $("stat-cost-m2").textContent = `€ ${num(r.metrics.net_cost_eur_per_m2, 3)} per m²`;
    $("verdict-note").textContent = "Re-verified after your edits.";
    state.approvable = Boolean(r.accepted);
    markVerified(true);
    updateReviewSummary({accepted:r.accepted, checker_enabled:true});
    $("approve").disabled = !r.accepted;
    if (!r.accepted) {
      $("decision-note").textContent = "The edited plan breaks a limit, so it cannot be approved.";
    }
  } catch (e) {
    // Never leave the previous verdict standing after a failed re-verification:
    // an operator seeing "accepted" for a plan that was not re-checked is the
    // worst possible failure mode for this screen.
    const badge = $("verdict-badge");
    badge.textContent = "not verified";
    badge.className = "badge no";
    $("verdict-text").textContent =
      "Re-verification failed, so the previous verdict no longer applies to this plan.";
    markVerified(false);
    showError(e);
  } finally { busy(false); }
}

async function decide(decision) {
  if (decision === "approve" && (state.dirty || !state.approvable)) return;
  busy(true);
  try {
    await api("/api/decision", {
      ...state.reference,
      decision,
      research_consent: $("research-consent").checked,
      comment: $("comment").value,
      seconds_to_decide: $("research-consent").checked && state.shownAt
        ? Math.round((performance.now() - state.shownAt) / 100) / 10
        : null,
      overrides: state.runOverrides,
    });
    $("decision-note").textContent =
      decision === "approve"
        ? "Approved and written to the audit log."
        : "Rejected and written to the audit log.";
    state.decision = decision;
    $("comment").value = "";
    $("review-title").textContent = decision === "approve" ? "Review approved" : "Review rejected";
    $("review-summary").textContent = "Your decision was recorded in the audit log.";
  } catch (e) { showError(e); } finally { busy(false); }
}

async function compare() {
  busy(true);
  $("compare").textContent = "Comparing…";
  try {
    const r = await api("/api/compare", {
      overrides: overrides(),
      planners: ["rule-based", "learned", "naive"],
    });
    const body = document.querySelector("#compare-table tbody");
    body.innerHTML = "";
    const ok = r.rows.filter((x) => !x.error).map((x) => x.cost_eur);
    const best = ok.length ? Math.min(...ok) : null;

    for (const row of r.rows) {
      const tr = document.createElement("tr");
      const cell = (value, className = "", colSpan = 1) => {
        const td = document.createElement("td");
        td.textContent = value;
        if (className) td.className = className;
        if (colSpan > 1) td.colSpan = colSpan;
        tr.appendChild(td);
      };
      if (row.error) {
        cell(row.planner);
        cell(row.error, "muted", 6);
      } else {
        const flags = [];
        if (row.fell_back) flags.push("fell back to baseline");
        if (row.cost_eur === best) flags.push("cheapest");
        cell(row.planner); cell(eur(row.cost_eur), "num"); cell(row.hard_violations, "num");
        cell(num(row.growth_kg_m2, 3), "num"); cell(`${num(row.band_hours)} h`, "num");
        cell(`${num(row.peak_import_kw)} kW`, "num"); cell(flags.join(" · "), "muted small");
      }
      body.appendChild(tr);
    }
    renderComparisonBars(r.rows);
    navigate("experiments");
    $("comparison").hidden = false;
    $("comparison").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { showError(e); } finally {
    busy(false);
    $("compare").textContent = "Compare planners";
  }
}

/* ----------------------------------------------------------------- init */

$("run").addEventListener("click", run);
$("compare").addEventListener("click", compare);
$("reverify").addEventListener("click", reverify);
$("approve").addEventListener("click", () => decide("approve"));
$("reject").addEventListener("click", () => decide("reject"));
$("reset").addEventListener("click", async () => {
  buildSettings(await api("/api/settings"));
});

api("/api/settings").then(s => {
  buildSettings(s);
  try {
    const saved = localStorage.getItem('kasflex.lastRun.v1');
    if (saved) { renderOutcome(JSON.parse(saved)); }
  } catch {}
}).catch(showError);
$("export-plan").disabled = true;

function renderChart(plan) {
  const values = plan.map(p => p.power_price_eur_kwh);
  const lo = Math.min(0, ...values), hi = Math.max(...values, lo + .01);
  const x = i => 52 + i * 700 / Math.max(1, plan.length - 1);
  const y = v => 164 - (v - lo) / (hi - lo) * 125;
  let svg = '<svg viewBox="0 0 790 205" role="img" aria-label="Hourly electricity prices for this scenario">';
  for (let i=0;i<4;i++) { const v=lo+(hi-lo)*i/3; svg += `<path d="M52 ${y(v)}H752" stroke="#e5e5ea" stroke-dasharray="3 5"/><text x="0" y="${y(v)+4}" fill="#6e6e73" font-size="11">${v.toFixed(2)}</text>`; }
  const points = values.map((v,i)=>`${x(i)},${y(v)}`).join(' ');
  svg += `<polygon points="52,164 ${points} 752,164" fill="#e8f2ff"/><polyline points="${points}" fill="none" stroke="#007aff" stroke-width="2.5"/>`;
  plan.forEach((p,i) => { svg += `<circle tabindex="0" cx="${x(i)}" cy="${y(values[i])}" r="4" fill="#007aff" stroke="#fff" stroke-width="2"><title>${String(p.hour).padStart(2,'0')}:00 · €${values[i].toFixed(3)}/kWh · ${p.heat_demand_kw.toFixed(0)} kW heat demand</title></circle>`; if(i%4===0 || i===plan.length-1) svg+=`<text x="${x(i)}" y="191" text-anchor="middle" fill="#6e6e73" font-size="11">${String(p.hour).padStart(2,'0')}:00</text>`; });
  $("price-chart").innerHTML = svg+'</svg>';
}

const viewTitles = {overview:'Overview', review:'Plan & review', experiments:'Experiments', history:'History', research:'Research notes'};
function navigate(view) {
  if (!viewTitles[view]) view = 'overview';
  document.querySelectorAll('.view').forEach(el => el.hidden = el.id !== `view-${view}`);
  document.querySelectorAll('[data-view]').forEach(el => {
    const active = el.dataset.view === view;
    el.classList.toggle('active', active);
    if (active) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current');
  });
  $('current-view').textContent = viewTitles[view];
  history.replaceState(null, '', `#${view}`);
  if(view==='history')loadReviewHistory();
  window.scrollTo({top:0, behavior:'instant'});
}
document.querySelectorAll('[data-view]').forEach(el => el.addEventListener('click', () => navigate(el.dataset.view)));
document.querySelectorAll('[data-go]').forEach(el => el.addEventListener('click', () => navigate(el.dataset.go)));
window.addEventListener('hashchange', () => navigate(location.hash.slice(1)));
navigate(location.hash.slice(1) || 'overview');
$('start-plan').addEventListener('click', run);

function renderSnapshot(r) {
  const rows = [ ['Date',r.date], ['Area',`${num(state.runSettings['hub.floor_area_m2'] / 10000, 2)} ha`], ['Planner',r.planner], ['Seed',state.runSettings.seed], ['Model',r.greenhouse_model], ['Checker',r.checker_enabled ? 'Enabled' : 'Disabled'] ];
  $('run-snapshot').replaceChildren();
  for (const [label,value] of rows) {
    const dt = document.createElement('dt'); dt.textContent = label;
    const dd = document.createElement('dd'); dd.textContent = value;
    $('run-snapshot').append(dt,dd);
  }
  $('brief-summary').textContent = state.runSettings.brief || 'No operator brief provided.';
}
function updateReviewSummary(r) {
  document.querySelector(".review-teaser").classList.toggle("needs-review", !r.checker_enabled || !r.accepted);
  $('review-title').textContent = !r.checker_enabled ? 'Verification is off' : r.accepted ? 'Ready for your review' : 'A limit needs attention';
  $('review-summary').textContent = !r.checker_enabled ? 'This plan has not been safety-checked. Approval is unavailable.' : r.accepted ? 'The checker accepted this plan. Inspect the hourly intent and record your decision.' : 'The checker rejected this plan. Inspect the feedback, edit the intent, and re-verify.';
  document.querySelector('.seal').textContent = r.checker_enabled && r.accepted ? '✓' : '!';
}
function renderDispatch() {
  const root = $('dispatch-map'); root.replaceChildren();
  const grid = document.createElement('div'); grid.className = 'dispatch-grid';
  grid.appendChild(document.createElement('span'));
  state.plan.forEach((row,i) => { const span = document.createElement('span'); span.className='hour-label'; span.textContent = i % 3 === 0 ? String(row.hour).padStart(2,'0') : ''; grid.appendChild(span); });
  const assets = [
    ['Heating',r=>r.heat_source,r=>({none:0,boiler:4,chp:3,buffer:2}[r.heat_source])],
    ['Lighting',r=>`${Math.round(r.lighting_level*100)}%`,r=>r.lighting_level===0 ? 0 : r.lighting_level<.5 ? 1 : 2],
    ['Battery',r=>`${r.battery} · ${r.battery_power_kw} kW`,r=>({idle:0,charge:1,discharge:3}[r.battery])],
    ['CHP',r=>r.chp_mode.replace(/_/g,' '),r=>({off:0,heat_led:2,max_export:3}[r.chp_mode])],
  ];
  for (const [name,description,mode] of assets) {
    const label = document.createElement('span'); label.className='asset-name'; label.textContent=name; grid.appendChild(label);
    state.plan.forEach((row,i) => {
      const button = document.createElement('button');
      button.className = `dispatch-cell mode-${mode(row)}`;
      button.title = `${String(row.hour).padStart(2,'0')}:00 · ${name}: ${description(row)}`;
      button.setAttribute('aria-label', `${button.title}. Inspect hour.`);
      button.addEventListener('click', () => {
        navigate('review');
        const rows = document.querySelectorAll('#plan tbody tr'); rows.forEach(tr=>tr.classList.remove('selected-hour'));
        rows[i].classList.add('selected-hour'); rows[i].scrollIntoView({block:'center'}); rows[i].querySelector('select').focus({preventScroll:true});
      });
      grid.appendChild(button);
    });
  }
  root.appendChild(grid);
  const legend = document.createElement('div'); legend.className='map-legend';
  ['Idle / off','Low / charge','Active / buffer','CHP / discharge','Boiler'].forEach((label,i)=>{const span=document.createElement('span');const dot=document.createElement('i');dot.className=`mode-${i}`;span.append(dot,document.createTextNode(label));legend.appendChild(span)});
  root.appendChild(legend);
}
function renderComparisonBars(rows) {
  const root = $('comparison-bars'); root.replaceChildren();
  const good = rows.filter(r=>!r.error && Number.isFinite(r.cost_eur));
  const max = Math.max(...good.map(r=>Math.abs(r.cost_eur)),1);
  for (const row of good) {
    const bar = document.createElement('div'); bar.className='compare-bar';
    const label=document.createElement('span');label.textContent=row.planner;
    const track=document.createElement('div');track.className='compare-bar-track';
    const fill=document.createElement('div');fill.className='compare-bar-fill';fill.style.width=`${Math.abs(row.cost_eur)/max*100}%`;track.appendChild(fill);
    const value=document.createElement('strong');value.textContent=eur(row.cost_eur);
    bar.append(label,track,value);root.appendChild(bar);
  }
}
$('export-plan').addEventListener('click', () => {
  if (!state.hasRun) return;
  const data={...state.reference, decision:state.decision, date:state.runSettings.date,scenario_settings:state.runSettings,edited:state.dirty,accepted:!state.dirty && state.approvable,intervals:state.plan,cost_forecast:state.dirty ? null : state.costForecast};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=`kasflex-plan-${state.runSettings.date}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

function renderCostForecast(forecast) {
  state.costForecast = forecast || null;
  let panel = $('cost-forecast');
  if (!panel) {
    panel = document.createElement('article');
    panel.id = 'cost-forecast'; panel.className = 'panel cost-forecast';
    document.querySelector('#outcome .cards').after(panel);
  }
  panel.hidden = !forecast;
  if (!forecast) return;
  panel.innerHTML = '<div class="panel-head"><div><p class="eyebrow">FORECAST · SAVED PLAN</p><h2>What could this day cost?</h2></div><strong id="forecast-total"></strong></div><p class="small muted">Uses forecast weather, the selected day’s electricity prices and your gas assumption. The greenhouse response is simulated.</p><dl id="cost-components"></dl><details><summary>Explore a change in prices</summary><p class="small">Keep this plan and its energy use fixed. Change prices to see the cost impact.</p><div class="price-assumptions"><label>Electricity price change (€/kWh)<input id="cost-power-shift" type="number" min="-1" max="1" step="0.01" value="0"></label><label>Gas price change (%)<input id="cost-gas-shift" type="number" min="-100" max="500" step="5" value="0"></label></div><p id="cost-sensitivity" role="status"></p><p class="small muted">Electricity change applies to both buying and selling. Negative prices are retained. This is a price scenario, not a probability range; weather, usage and the schedule stay fixed.</p></details><p class="small muted">Energy and liquid CO₂ only (€0.30/kg). Excludes taxes, grid tariffs, supplier fees, investment, maintenance and crop sales. This is not a bill estimate.</p>';
  const t = forecast.totals;
  $('forecast-total').textContent = eur(t.net_cost_eur);
  for (const [label,value] of [['Electricity bought',t.electricity_import_eur],['Gas',t.gas_eur],['Liquid CO₂',t.liquid_co2_eur],['Electricity sold (deducted)',t.export_revenue_eur]]) {
    const pair=document.createElement('div'), term=document.createElement('dt'), detail=document.createElement('dd');
    term.textContent=label; detail.textContent=eur(value); pair.append(term,detail); $('cost-components').append(pair);
  }
  const update = () => {
    const power=$('cost-power-shift'), gas=$('cost-gas-shift');
    if (!power.value || !gas.value || !power.checkValidity() || !gas.checkValidity()) {
      $('cost-sensitivity').textContent='Enter an electricity change from −1 to 1 and a gas change from −100% to 500%.'; return;
    }
    const delta=(t.import_kwh-t.export_kwh)*Number(power.value)+t.gas_eur*Number(gas.value)/100;
    $('cost-sensitivity').textContent=`Scenario cost: ${eur(t.net_cost_eur+delta)} · change: ${eur(delta)}`;
  };
  $('cost-power-shift').addEventListener('input',update); $('cost-gas-shift').addEventListener('input',update); update();
}

// Critically damped sheet motion, retargeted from its current position and velocity.
// No transition disables input; Escape or the close button can reverse the spring.
const sheet = $('settings-dialog');
const sheetMotion = {x:1,v:0,target:1,frame:0,last:0,trigger:null};
let configurationDraft = null;
let commitConfiguration = false;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
function paintSheet() {
  sheet.style.transform = reducedMotion.matches ? 'none' : `translateY(${sheetMotion.x*24}px) scale(${1-sheetMotion.x*.025})`;
  sheet.style.opacity = String(1-sheetMotion.x);
}
function tickSheet(now) {
  const dt=Math.min((now-(sheetMotion.last||now))/1000,.025);sheetMotion.last=now;
  const w=24;
  sheetMotion.v += (-w*w*(sheetMotion.x-sheetMotion.target)-2*w*sheetMotion.v)*dt;
  sheetMotion.x += sheetMotion.v*dt;
  if (reducedMotion.matches || (Math.abs(sheetMotion.x-sheetMotion.target)<.001 && Math.abs(sheetMotion.v)<.01)) {
    sheetMotion.x=sheetMotion.target;sheetMotion.v=0;sheetMotion.frame=0;sheetMotion.last=0;paintSheet();
    if(sheetMotion.target===1){document.querySelectorAll('.api-key-input').forEach(el=>el.value='');if(!commitConfiguration && configurationDraft)applyFieldValues(configurationDraft);configurationDraft=null;commitConfiguration=false;updateConfigurationSummary();sheet.close();sheetMotion.trigger?.focus();}
    return;
  }
  paintSheet();sheetMotion.frame=requestAnimationFrame(tickSheet);
}
function moveSheet(open, trigger) {
  if (open) {
    sheetMotion.trigger=trigger || document.activeElement;
    if(!sheet.open) {configurationDraft=allFieldValues();commitConfiguration=false;sheetMotion.x=1;sheetMotion.v=0;sheet.showModal();}
  }
  sheetMotion.target=open?0:1;
  if(!sheetMotion.frame){paintSheet();sheetMotion.frame=requestAnimationFrame(tickSheet);}
}
$('open-settings').addEventListener('click',e=>moveSheet(true,e.currentTarget));
$('edit-brief').addEventListener('click',e=>{moveSheet(true,e.currentTarget);selectConfigurationSection('Basics');$('f-brief').focus();});
$('close-settings').addEventListener('click',()=>moveSheet(false));
sheet.addEventListener('cancel',e=>{e.preventDefault();moveSheet(false);});
$('apply-settings').addEventListener('click',()=>{if(!validateSettings())return;commitConfiguration=true;try{localStorage.setItem('kasflex.configuration.v1',JSON.stringify(allFieldValues()));$('save-feedback').textContent='Configuration saved on this browser.';}catch{$('save-feedback').textContent='Configuration applied for this session.';}moveSheet(false);});
sheet.addEventListener('click',e=>{if(e.target===sheet){const r=sheet.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)moveSheet(false);}});

function validateSettings() {
  const invalid = $('settings-form').querySelector(':invalid');
  if (!invalid) return true;
  selectConfigurationSection(invalid.closest('.settings-group').dataset.section);
  if (!sheet.open) moveSheet(true);
  invalid.reportValidity(); invalid.focus();
  return false;
}
function selectConfigurationSection(title) {
  document.querySelectorAll('#settings-form .settings-group').forEach(el=>el.hidden=el.dataset.section!==title);
  document.querySelectorAll('#configuration-nav button').forEach(el=>{const active=el.dataset.section===title;el.setAttribute('aria-selected',String(active));el.tabIndex=active?0:-1;el.classList.toggle('active',active);});
}
function allFieldValues() {
  return Object.fromEntries(state.fields.map(f=>{const el=$(`f-${f.path}`);return [f.path,f.kind==='bool'?el.checked:el.value];}));
}
function applyFieldValues(values) {
  for(const f of state.fields){if(!(f.path in values))continue;const el=$(`f-${f.path}`);if(!el)continue;const value=values[f.path];if(f.kind==='bool')el.checked=Boolean(value);else if(f.kind!=='choice'||f.choices.includes(value))el.value=value;}
}
function updateConfigurationSummary() {
  if(!$('f-data_source'))return;
  const demo=$('f-data_source').value==='synthetic';
  const area=Number($('f-hub.floor_area_m2').value)/10000;
  $('configuration-summary').textContent=`${demo?'Demo data':'Downloaded real data'} · ${$('f-date').value || 'Choose a date'} · ${num(area,2)} ha`;
  $('configuration-help').textContent=demo?'Demo mode is ready without accounts or downloads. Its results are illustrative.':'Real data requires cached electricity prices and weather for this date. Check the Data sources section before generating a plan.';
  $('f-winter').disabled=!demo;
  $('f-winter').closest('.field').style.opacity=demo?'1':'.5';
}
async function checkData(download) {
  if(!validateSettings())return;
  const buttons=[$('check-data'),$('download-data')];buttons.forEach(b=>b.disabled=true);
  const box=$('data-status');box.textContent=download?'Downloading available inputs…':'Checking downloaded data…';
  try{
    const r=await api(download?'/api/data-download':'/api/data-status',{overrides:overrides()});
    box.replaceChildren();
    const title=document.createElement('strong');title.textContent=r.ready?'Ready for a real-input estimate':'Data is incomplete for this date';box.appendChild(title);
    for(const row of r.series){const line=document.createElement('p');line.textContent=`${row.ready?'✓':'○'} ${row.label}: ${row.ready?'cached · '+row.retrieved_on:'not available'}`;box.appendChild(line);}
    const info=document.createElement('p');info.textContent=r.entsoe_configured?'ENTSO-E token is configured on the server.':'No ENTSO-E key saved. Open Configuration → APIs to add one.';box.appendChild(info);
    if(r.message){const msg=document.createElement('p');msg.textContent=r.message;box.appendChild(msg);}
    if(!r.actuals_available){const note=document.createElement('p');note.textContent='Without weather reanalysis, results are estimates evaluated against the forecast.';box.appendChild(note);}
  }catch(e){box.textContent=e.message || 'Could not check data. Please try again.';}
  finally{buttons.forEach(b=>b.disabled=false);}
}


async function loadConnections() {
  try { renderConnections(await api('/api/connections')); }
  catch { $('api-connections-list').textContent='Could not load connections. Refresh the workspace and try again.'; }
}
function renderConnections(payload) {
  const root=$('api-connections-list');root.replaceChildren();
  for(const provider of payload.connections) {
    const card=document.createElement('article');card.className='api-connection';
    const head=document.createElement('div');head.className='api-connection-head';
    const title=document.createElement('h4');title.textContent=provider.name;
    const status=document.createElement('span');status.className='api-status';status.textContent=provider.requires_key?(provider.configured?'Key configured':'Key needed'):'No key needed';
    head.append(title,status);
    const purpose=document.createElement('p');purpose.textContent=provider.purpose;
    const endpoint=document.createElement('code');endpoint.className='api-endpoint';endpoint.textContent=provider.endpoint;
    card.append(head,purpose,endpoint);
    if(provider.requires_key) {
      const label=document.createElement('label');label.htmlFor=`api-key-${provider.id}`;label.textContent=provider.configured?'Replace API key':'Your API key';
      const wrap=document.createElement('div');wrap.className='api-key-row';
      const input=document.createElement('input');input.type='password';input.id=label.htmlFor;input.className='api-key-input';input.autocomplete='new-password';input.spellcheck=false;input.maxLength=2048;input.placeholder=provider.configured?'Enter a new key to replace the saved one':'Paste your personal token';
      const show=document.createElement('button');show.type='button';show.textContent='Show';show.setAttribute('aria-label','Show entered API key');show.addEventListener('click',()=>{input.type=input.type==='password'?'text':'password';show.textContent=input.type==='password'?'Show':'Hide';show.setAttribute('aria-label',`${show.textContent} entered API key`);});
      wrap.append(input,show);
      const actions=document.createElement('div');actions.className='api-key-actions';
      const save=document.createElement('button');save.type='button';save.className='primary';save.textContent=provider.configured?'Replace key':'Save key';
      const remove=document.createElement('button');remove.type='button';remove.textContent='Remove key';remove.disabled=!provider.configured;
      const help=document.createElement('a');help.href=provider.help_url;help.target='_blank';help.rel='noopener noreferrer';help.textContent='Get an API key ↗';
      const message=document.createElement('p');message.className='api-key-message';message.setAttribute('role','status');message.textContent=provider.configured?'A key is configured. Saving a key does not verify provider access.':'The token comes from your ENTSO-E account. Keys are not supplied with this project.';
      async function submit(removing) {
        if(!removing && !input.value.trim()){message.textContent='Paste your API key first.';input.focus();return;}
        save.disabled=true;remove.disabled=true;show.disabled=true;input.disabled=true;
        message.textContent=removing?'Removing key…':'Saving key locally…';
        try {
          const response=await api('/api/connections',{provider:provider.id,api_key:removing?'':input.value,remove:removing});
          input.value='';renderConnections(response);
          $('api-save-result').textContent=removing?'API key removed.':'API key saved in .env. It is available immediately; no restart needed.';
        } catch(e){input.value='';message.textContent=e.message||'Could not save this key.';}
        finally{save.disabled=false;remove.disabled=!provider.configured;show.disabled=false;input.disabled=false;}
      }
      save.addEventListener('click',()=>submit(false));remove.addEventListener('click',()=>submit(true));
      input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();submit(false);}});
      actions.append(save,remove,help);card.append(label,wrap,actions,message);
    } else {
      const note=document.createElement('p');note.className='api-key-message';note.textContent='The current public connector works without a token. Provider usage limits still apply.';card.appendChild(note);
    }
    root.appendChild(card);
  }
  const notice=document.createElement('p');notice.className='api-storage-note';notice.textContent='Save key takes effect immediately, separately from Save configuration. Keys are stored as text in the local .env file, not in browser storage or exported plans. The file is excluded from Git and project downloads.';
  const result=document.createElement('p');result.id='api-save-result';result.setAttribute('role','status');
  root.append(notice,result);
}

async function loadReviewHistory() {
  const root=$('review-history-list');root.replaceChildren();$('history-status').textContent='Loading saved plans…';
  try {
    const payload=await api('/api/reviews');
    $('history-status').textContent=payload.runs.length?'Latest saved plans. Reopening uses the original configuration and inputs.':'No saved plans yet. Generate a daily plan to start your history.';
    for(const entry of payload.runs) {
      const r=entry.result,card=document.createElement('article');card.className='history-item';
      const detail=document.createElement('div');
      const title=document.createElement('h3');title.textContent=`${r.date} · ${r.planner}`;
      const info=document.createElement('p');info.textContent=`${(r.data_source==='cache'||r.data_source==='demo')?'Real-input data':'Synthetic test'} · revision ${r.revision} · ${entry.decision?entry.decision.decision:'Awaiting review'}`;
      const money=document.createElement('strong');money.textContent=eur(r.metrics.net_cost_eur);
      const open=document.createElement('button');open.type='button';open.textContent='Open saved plan';
      open.addEventListener('click',async()=>{
        open.disabled=true;
        try {
          const saved=await api(`/api/reviews/${r.run_id}`);renderOutcome(saved.result);try{localStorage.setItem('kasflex.lastRun.v1',JSON.stringify(saved.result));}catch{}state.decision=saved.decision?.decision||null;
          if(state.decision){$('approve').disabled=true;$('reject').disabled=true;$('decision-note').textContent=`This revision was ${state.decision==='approve'?'approved':state.decision==='reject'?'rejected':'marked for editing'} at ${saved.decision.timestamp}. Edit and re-verify to create a new revision.`;}
          navigate('review');
        }catch(e){$('history-status').textContent=e.message;}finally{open.disabled=false;}
      });
      detail.append(title,info);card.append(detail,money,open);root.appendChild(card);
    }
  }catch(e){$('history-status').textContent=e.message;}
}
$('refresh-history').addEventListener('click',loadReviewHistory);

/* --------------------------------------------------------- weather chart */

function renderWeatherChart(plan) {
  const root = $('weather-chart');
  if (!root || !plan || !plan.length) return;
  const temps = plan.map(p => p.outdoor_temp_c ?? 0);
  const rads = plan.map(p => p.irradiance_w_m2 ?? 0);
  const tLo = Math.min(...temps) - 2, tHi = Math.max(...temps) + 2;
  const rHi = Math.max(...rads, 1);
  const W = 790, H = 170, PAD = 52, R = W - 12;
  const x = i => PAD + i * (R - PAD) / Math.max(1, plan.length - 1);
  const yT = v => 10 + (1 - (v - tLo) / (tHi - tLo)) * (H - 30);
  const yR = v => 10 + (1 - v / rHi) * (H - 30);

  let svg = `<svg viewBox="0 0 ${W} ${H + 20}" role="img" aria-label="Weather conditions">`;
  for (let i = 0; i < 3; i++) {
    const v = tLo + (tHi - tLo) * i / 2;
    svg += `<text x="0" y="${yT(v) + 4}" fill="#86868b" font-size="10">${v.toFixed(0)}°</text>`;
    svg += `<path d="M${PAD} ${yT(v)}H${R}" stroke="#f0f0f4" stroke-dasharray="3 5"/>`;
  }
  // Radiation bars
  plan.forEach((p, i) => {
    const bw = (R - PAD) / plan.length * 0.6;
    svg += `<rect x="${x(i) - bw / 2}" y="${yR(rads[i])}" width="${bw}" height="${H - 20 - yR(rads[i])}" fill="#f5dfa0" rx="2"><title>${String(p.hour).padStart(2,'0')}:00 · ${rads[i]} W/m²</title></rect>`;
  });
  // Temperature line
  const tPts = temps.map((v, i) => `${x(i)},${yT(v)}`).join(' ');
  svg += `<polyline points="${tPts}" fill="none" stroke="#e8593f" stroke-width="2.5"/>`;
  temps.forEach((v, i) => {
    svg += `<circle cx="${x(i)}" cy="${yT(v)}" r="3" fill="#e8593f" stroke="#fff" stroke-width="1.5"><title>${String(plan[i].hour).padStart(2,'0')}:00 · ${v.toFixed(1)}°C · ${rads[i]} W/m²</title></circle>`;
  });
  // Radiation axis on right
  svg += `<text x="${R + 4}" y="${yR(rHi) + 4}" fill="#b08d2b" font-size="9">${Math.round(rHi)}</text>`;
  svg += `<text x="${R + 4}" y="${H - 16}" fill="#b08d2b" font-size="9">0</text>`;
  // Hour labels
  plan.forEach((p, i) => { if (i % 4 === 0 || i === plan.length - 1) svg += `<text x="${x(i)}" y="${H + 12}" text-anchor="middle" fill="#86868b" font-size="10">${String(p.hour).padStart(2,'0')}:00</text>`; });
  root.innerHTML = svg + '</svg>';
}

/* ----------------------------------------------------- battery SOC chart */

function renderSocChart(plan, battConfig) {
  const root = $('soc-chart');
  if (!root || !plan || !plan.length) return;
  const cap = battConfig?.capacity_kwh || 2000;
  const initSoc = battConfig?.soc_init_kwh ?? cap * 0.5;
  const eff = 0.95;
  const soc = [initSoc];
  for (const iv of plan) {
    let prev = soc[soc.length - 1];
    if (iv.battery === 'charge') prev += iv.battery_power_kw * eff;
    else if (iv.battery === 'discharge') prev -= iv.battery_power_kw / eff;
    soc.push(Math.max(0, Math.min(cap, prev)));
  }
  const W = 790, H = 170, PAD = 52, R = W - 12;
  const x = i => PAD + i * (R - PAD) / Math.max(1, plan.length);
  const lo = 0, hi = cap;
  const y = v => 10 + (1 - (v - lo) / (hi - lo)) * (H - 30);

  let svg = `<svg viewBox="0 0 ${W} ${H + 20}" role="img" aria-label="Battery state of charge">`;
  for (let i = 0; i <= 4; i++) {
    const v = hi * i / 4;
    svg += `<text x="0" y="${y(v) + 4}" fill="#86868b" font-size="10">${Math.round(v)}</text>`;
    svg += `<path d="M${PAD} ${y(v)}H${R}" stroke="#f0f0f4" stroke-dasharray="3 5"/>`;
  }
  // Fill area
  const pts = soc.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  svg += `<polygon points="${x(0)},${y(0)} ${pts} ${x(soc.length - 1)},${y(0)}" fill="#e6f4ea"/>`;
  svg += `<polyline points="${pts}" fill="none" stroke="#34a853" stroke-width="2.5"/>`;
  soc.forEach((v, i) => {
    const label = i < plan.length ? `${String(plan[i].hour).padStart(2,'0')}:00` : 'End';
    const mode = i < plan.length ? plan[i].battery : '';
    svg += `<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="#34a853" stroke="#fff" stroke-width="1.5"><title>${label} · SOC: ${Math.round(v)} kWh (${Math.round(v / cap * 100)}%)${mode ? ' · ' + mode : ''}</title></circle>`;
  });
  plan.forEach((p, i) => { if (i % 4 === 0 || i === plan.length - 1) svg += `<text x="${x(i)}" y="${H + 12}" text-anchor="middle" fill="#86868b" font-size="10">${String(p.hour).padStart(2,'0')}:00</text>`; });
  root.innerHTML = svg + '</svg>';
}

/* ---------------------------------------------------------- PDF export */

$('export-pdf').addEventListener('click', () => {
  if (!state.hasRun) return;
  const cfg = state.runSettings;
  const m = document.querySelector('#metrics')?.innerHTML || '';
  const planRows = state.plan.map(p =>
    `<tr><td>${escapeHtml(String(p.hour).padStart(2,'0'))}</td><td>€${escapeHtml(p.power_price_eur_kwh.toFixed(3))}</td><td>${escapeHtml(p.heat_source)}</td><td>${escapeHtml((p.lighting_level*100).toFixed(0))}%</td><td>${escapeHtml(p.battery)}</td><td>${escapeHtml(p.chp_mode.replace(/_/g,' '))}</td><td>${escapeHtml(p.reasoning||'')}</td></tr>`
  ).join('');
  const violations = document.querySelector('.violation-list')?.innerHTML || '<p>No violations.</p>';
  const badge = $('verdict-badge');
  const verdictStatus = badge ? badge.textContent : '';
  const cost = $('stat-cost')?.textContent || '';
  const growth = $('stat-growth')?.textContent || '';
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>KasFlex Report — ${escapeHtml(cfg.date || '')}</title>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:11px;color:#1d1d1f;padding:32px;max-width:900px;margin:auto}
h1{font-size:22px;margin-bottom:4px}h2{font-size:14px;margin:20px 0 8px;color:#007aff;border-bottom:1px solid #e5e5ea;padding-bottom:4px}
.meta{color:#6e6e73;font-size:10px;margin-bottom:16px}.stats{display:flex;gap:24px;margin:12px 0}.stat{flex:1;background:#f5f5f7;padding:14px;border-radius:8px}.stat .label{font-size:9px;color:#6e6e73;text-transform:uppercase;letter-spacing:.5px}.stat .val{font-size:22px;font-weight:600;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:10px;margin:8px 0}th{background:#f7f7fa;padding:6px 8px;text-align:left;font-size:9px;color:#6e6e73;text-transform:uppercase}td{padding:6px 8px;border-bottom:1px solid #f0f0f3}
.verdict{padding:12px;border-radius:8px;margin:8px 0}.verdict.ok{background:#e6f4ea;color:#248a3d}.verdict.no{background:#fff0ed;color:#933e23}
.footer{margin-top:24px;padding-top:12px;border-top:1px solid #e5e5ea;font-size:9px;color:#86868b}
@media print{body{padding:16px}}</style></head><body>
<h1>KasFlex Energy Plan</h1>
  <p class="meta">${escapeHtml(cfg.date || '')} · ${escapeHtml(cfg.planner || 'rule-based')} · ${cfg.data_source === 'cache' ? 'Real data' : 'Demo'} · Generated ${escapeHtml(new Date().toLocaleString())}</p>
  <div class="stats"><div class="stat"><div class="label">Net cost</div><div class="val">${escapeHtml(cost)}</div></div><div class="stat"><div class="label">Crop growth</div><div class="val">${escapeHtml(growth)}</div></div><div class="stat"><div class="label">Verdict</div><div class="val">${escapeHtml(verdictStatus)}</div></div></div>
<h2>Safety check</h2>${violations}
<h2>Hourly plan</h2><table><thead><tr><th>Hour</th><th>Price</th><th>Heat</th><th>Lights</th><th>Battery</th><th>CHP</th><th>Reasoning</th></tr></thead><tbody>${planRows}</tbody></table>
<h2>Metrics</h2><table>${m}</table>
<div class="footer">KasFlex · 4TU.NIRICT · Research simulation — not validated for operational use.</div>
  </body></html>`;
  const w = window.open('', '_blank');
  if (!w) { showError(new Error('The report window was blocked. Allow pop-ups for this local app and try again.')); return; }
  w.document.write(html);
  w.document.close();
  w.onload = () => { w.print(); };
});
$('export-pdf').disabled = true;

/* -------------------------------------------------- edit diff highlight */

function highlightChanges(tr, current, original) {
  const fields = ['heat_source', 'lighting_level', 'battery', 'battery_power_kw', 'chp_mode', 'co2_source'];
  const cells = tr.querySelectorAll('td');
  // Cells: 0=hour, 1=price, 2=heat need, 3=heat source, 4=lamps, 5=battery, 6=chp, 7=co2, 8=why
  const cellMap = [3, 4, 5, 5, 6, 7];
  fields.forEach((f, idx) => {
    const ci = cellMap[idx];
    if (ci < cells.length) {
      const changed = current[f] !== original[f];
      cells[ci].classList.toggle('cell-changed', changed);
    }
  });
}
