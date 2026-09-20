"use strict";

const $ = (id) => document.getElementById(id);
const state = { context:null, run:null, aiPlan:null, currentPlan:null, busy:false };

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : {"Content-Type":"application/json"},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch {}
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function euro(value, digits=0) {
  return "€" + Number(value || 0).toLocaleString("en-NL", {minimumFractionDigits:digits, maximumFractionDigits:digits});
}
function cents(value) { return (Number(value || 0) * 100).toFixed(1) + " ct/kWh"; }
function hours(list) { return (list || []).map(h => String(h).padStart(2,"0")+":00").join(", "); }
function showError(error, action="This action") {
  const box=$("error");
  const reason=String(error && error.message ? error.message : error || "Unknown error");
  box.hidden=false;
  box.textContent=`${action} failed: ${reason}`;
  box.scrollIntoView({behavior:"smooth",block:"center"});
}
function clearError(){ $("error").hidden=true; }
function toast(text){ const el=$("toast"); el.textContent=text; el.hidden=false; clearTimeout(el._t); el._t=setTimeout(()=>el.hidden=true,3200); }

function policy() {
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
    "checker.enabled":$("safety-check").checked,
  };
}

async function loadContext() {
  clearError();
  $("data-pill").className="status-pill loading";
  $("data-pill").textContent="Preparing real demo data…";
  $("refresh-data").disabled=true;
  try {
    const prepared = await api("/api/demo-prepare", {overrides:{data_source:"demo"}});
    state.context = await api("/api/day-context", {
      overrides:{data_source:"demo",date:prepared.date,planner:"collaborative"}
    });
    renderContext(state.context);
    $("data-pill").className="status-pill";
    $("data-pill").textContent=prepared.reused_cache ? "Real demo data · cached" : "Real demo data · ready";
  } catch (error) {
    $("data-pill").className="status-pill loading";
    $("data-pill").textContent="Demo data unavailable";
    showError(error, "Preparing the real demo data");
  } finally {
    $("refresh-data").disabled=false;
  }
}

function renderContext(ctx) {
  $("planning-date").textContent = new Date(ctx.date+"T12:00:00").toLocaleDateString("en-GB",{weekday:"short",day:"numeric",month:"short",year:"numeric"});
  const origins = ctx.sources || {};
  const provenance = ctx.provenance || {};
  const market = provenance.prices?.dataset_key === "entsoe_da"
    ? "ENTSO-E-derived NL prices" : "electricity prices";
  const weather = provenance.forecast_weather?.dataset_key === "openmeteo_hist_forecast"
    ? "Open-Meteo archived forecast" : "weather forecast";
  const local = origins.prices === "cache" && origins.forecast_weather === "cache"
    ? "cached locally" : "prepared now";
  $("source-summary").textContent = `${market} · ${weather} · ${local}`;
  $("price-low").textContent = cents(ctx.price.min_eur_kwh);
  $("price-high").textContent = cents(ctx.price.max_eur_kwh);
  $("price-low-hours").textContent = "Best: " + hours(ctx.price.cheapest_hours);
  $("price-high-hours").textContent = "Peak: " + hours(ctx.price.dearest_hours);
  $("temp-range").textContent = `${ctx.weather.min_temp_c.toFixed(1)}–${ctx.weather.max_temp_c.toFixed(1)} °C`;
  $("sun-hours").textContent = `${ctx.weather.sun_hours} h with useful daylight`;
  $("grid-limit").textContent = Math.round(ctx.grid.import_limit_kw/1000*10)/10 + " MW";
  const windows = Object.keys(ctx.grid.congestion_windows || {});
  $("grid-window").textContent = windows.length ? `Reduced limit: ${windows[0]}:00–${Number(windows.at(-1))+1}:00` : "No congestion window";
  renderPriceChart(ctx.price.series);
}

function renderPriceChart(values) {
  const root=$("price-chart"); root.replaceChildren();
  const min=Math.min(...values), max=Math.max(...values), span=Math.max(.001,max-min);
  values.forEach((v,h)=>{
    const height=18+((v-min)/span)*125;
    const bar=document.createElement("div");
    bar.className="price-bar "+(v>min+span*.65?"dear":"");
    bar.style.height=height+"px";
    bar.dataset.tip=`${String(h).padStart(2,"0")}:00 · ${cents(v)}`;
    root.append(bar);
  });
}

async function buildPlan() {
  if (state.busy) return;
  if (!state.context) {
    showError(new Error("Real demo data is not ready yet."), "Building tomorrow's plan");
    return;
  }
  state.busy=true; clearError();
  const btn=$("build-plan"); const old=btn.textContent; btn.disabled=true; btn.textContent="Planning…";
  try {
    const result=await api("/api/run",{overrides:overrides(),policy:policy()});
    state.run=result;
    state.aiPlan=(result.plan||[]).map(r=>({...r}));
    state.currentPlan=(result.plan||[]).map(r=>({...r}));
    renderResult(result);
    $("plan-section").hidden=false;
    $("plan-section").scrollIntoView({behavior:"smooth",block:"start"});
  } catch(error){showError(error, "Building tomorrow's plan")}
  finally{state.busy=false;btn.disabled=false;btn.textContent=old}
}

function renderResult(result) {
  state.run=result;
  const normal=result.normal_settings;
  const saving=normal?Number(normal.saving_eur||0):0;
  $("result-cost").textContent=euro(result.metrics?.net_cost_eur);
  $("result-saving").textContent=normal ? (saving>=0 ? `${euro(saving)} below normal plan` : `${euro(-saving)} above normal plan`) : "No baseline comparison";
  $("result-grid-energy").textContent=(Number(result.metrics?.grid_import_kwh||0)/1000).toFixed(1)+" MWh";
  $("result-gas").textContent=(Number(result.metrics?.gas_input_kwh||0)/1000).toFixed(1)+" MWh";
  $("result-peak").textContent=(Number(result.metrics?.peak_import_kw||0)/1000).toFixed(2)+" MW";
  const cropHours=Math.round(Number(result.metrics?.temperature_band_hours||0));
  $("result-band").textContent=cropHours+"/24 h";
  $("result-crop").textContent=cropHours>=22?"On target":cropHours>=18?"Needs attention":"At risk";
  $("result-crop-note").textContent=`Temperature in range for ${cropHours} of 24 hours · simulated, not measured`;
  $("crop-card").className=`result-metric crop-card ${cropHours>=22?"good":"warn"}`;
  $("result-actions").textContent=String((result.actions||[]).length);
  $("plan-subtitle").textContent=`${labelPriority(result.policy?.priority)} · battery reserve ${Math.round(result.policy?.battery_reserve_pct||0)}% · compared with normal control.`;

  const badge=$("checker-badge");
  if(result.checker_enabled && result.accepted){
    badge.className="checker-badge"; badge.textContent="✓ Independently verified";
    $("approve-plan").disabled=false;
  } else if(!result.checker_enabled) {
    badge.className="checker-badge bad"; badge.textContent="Safety check off · not verified";
    $("approve-plan").disabled=true;
  } else {
    badge.className="checker-badge bad"; badge.textContent="Not safe to approve";
    $("approve-plan").disabled=true;
  }
  renderChanges(result);
  renderTimeline(result.plan||[]);
  renderTable(result.plan||[]);
}

function labelPriority(value){
  return value==="cost"?"Lowest cost":value==="crop"?"Tomatoes first":value==="grid"?"Grid relief":"Balanced";
}

function renderChanges(result){
  const root=$("changes-list"); root.replaceChildren();
  const actions=result.actions||[];
  if(!actions.length){
    root.innerHTML='<p style="color:#617069">KasFlex does not need to change anything material from the normal schedule.</p>';
    return;
  }
  actions.forEach(action=>{
    const item=document.createElement("div"); item.className="change";
    const info=document.createElement("div");
    info.innerHTML=`<div class="change-title">${escapeHtml(action.title)}</div>
      <div class="change-reason">${escapeHtml(action.why||"")}</div>
      <div class="change-meta"><span class="chip">${String(action.start).padStart(2,"0")}:00–${String(action.end+1).padStart(2,"0")}:00</span>
      ${action.saving_eur?'<span class="chip">share of saving '+euro(action.saving_eur)+'</span>':""}</div>`;
    const controls=document.createElement("div"); controls.className="change-actions";
    const normal=document.createElement("button"); normal.textContent="Use normal";
    normal.onclick=()=>applyNormalForAction(action);
    const ai=document.createElement("button"); ai.textContent="Use KasFlex";
    ai.onclick=()=>restoreAiForAction(action);
    controls.append(normal,ai); item.append(info,controls); root.append(item);
  });
}

async function verifyPlan(rows, message) {
  if(!state.run) {
    showError(new Error("There is no active plan to verify."), "Checking your plan change");
    return null;
  }
  const payload={
    run_id:state.run.run_id,revision:state.run.revision,plan_hash:state.run.plan_hash,
    plan:rows,
  };
  try{
    const revised=await api("/api/verify",payload);
    state.run=revised; state.currentPlan=(revised.plan||[]).map(r=>({...r}));
    renderResult(revised); toast(message);
    return revised;
  }catch(error){showError(error, "Checking your plan change");return null}
}

async function applyNormalForAction(action){
  const normal=state.run?.normal_settings?.plan;
  if(!normal || !normal.length) {
    showError(new Error("The normal-control comparison is not available for this run."), "Using the normal setting");
    return;
  }
  const byHour=new Map(normal.map(r=>[Number(r.hour),r]));
  const edited=state.currentPlan.map(row=>{
    if(!(action.hours||[]).includes(Number(row.hour))) return {...row};
    const base=byHour.get(Number(row.hour)); if(!base) return {...row};
    return {...row,[action.field_name]:base[action.field_name]};
  });
  await verifyPlan(edited,"Your change was re-checked.");
}

async function restoreAiForAction(action){
  if(!state.aiPlan || !state.aiPlan.length) {
    showError(new Error("The original KasFlex proposal is no longer available."), "Restoring the KasFlex suggestion");
    return;
  }
  const byHour=new Map(state.aiPlan.map(r=>[Number(r.hour),r]));
  const edited=state.currentPlan.map(row=>{
    if(!(action.hours||[]).includes(Number(row.hour))) return {...row};
    const base=byHour.get(Number(row.hour)); if(!base) return {...row};
    return {...row,[action.field_name]:base[action.field_name]};
  });
  await verifyPlan(edited,"KasFlex suggestion restored and re-checked.");
}

async function useNormalPlan(){
  if(!state.run) {
    showError(new Error("Build a plan before switching to normal control."), "Using the normal plan");
    return;
  }
  const normal=state.run.normal_settings?.plan;
  if(!normal || !normal.length) {
    showError(new Error("The normal-control baseline is not available for this run."), "Using the normal plan");
    return;
  }
  await verifyPlan(normal.map(r=>({...r})),"Normal plan loaded and independently checked.");
}

async function compareSafety(){
  if(!state.context){showError(new Error("Prepare the day first."),"Comparing safety");return}
  const button=$("compare-safety");button.disabled=true;button.textContent="Running both…";
  try{
    const result=await api("/api/safety-comparison",{overrides:overrides(),policy:policy()});
    const root=$("safety-comparison");root.replaceChildren();root.hidden=false;
    for(const row of result.rows||[]){
      const card=document.createElement("div");card.className=`safety-result ${row.checker_enabled?"on":"off"}`;
      const title=document.createElement("strong");title.textContent=row.checker_enabled?"Safety check on":"Safety check off";
      const outcome=document.createElement("span");
      outcome.textContent=`${row.hard_violations} hard limit problem${row.hard_violations===1?"":"s"} · ${euro(row.cost_eur)} · crop ${Math.round(row.crop_band_hours)}/24 h`;
      const note=document.createElement("span");
      note.textContent=row.checker_enabled?(row.fell_back?"Unsafe proposal stopped; normal control took over.":"Plan verified before review."):"Executed only for comparison; cannot be approved.";
      card.append(title,outcome,note);root.append(card);
    }
  }catch(error){showError(error,"Comparing safety on and off")}
  finally{button.disabled=false;button.textContent="Compare on/off"}
}

function openConcern(){
  if(!state.run){showError(new Error("Build a plan first."),"Opening partial review");return}
  for(const input of document.querySelectorAll('#concern-form input[type="checkbox"]'))input.checked=false;
  const root=$("concern-actions");root.replaceChildren();
  for(const action of state.run.actions||[]){
    const label=document.createElement("label");
    const input=document.createElement("input");input.type="checkbox";input.value=action.action_id;
    label.append(input,document.createTextNode(`${action.title} (${String(action.start).padStart(2,"0")}:00–${String(action.end+1).padStart(2,"0")}:00)`));
    root.append(label);
  }
  if(!(state.run.actions||[]).length) root.textContent="There are no remaining changes to reject separately.";
  $("concern-status").textContent="";$("concern-note").value="";
  $("concern-dialog").showModal();
}

async function submitConcern(){
  const accepted=[...document.querySelectorAll('#concern-form input[name="accepted"]:checked')].map(x=>x.value);
  const objected=[...document.querySelectorAll('#concern-form input[name="objected"]:checked')].map(x=>x.value);
  const overlap=accepted.filter(value=>objected.includes(value));
  if(!objected.length){$("concern-status").textContent="Choose at least one part you disagree with.";return}
  if(overlap.length){$("concern-status").textContent="The same part cannot be both okay and a concern.";return}
  const rejected=[...$("concern-actions").querySelectorAll('input:checked')].map(x=>x.value);
  const button=$("submit-concern");button.disabled=true;$("concern-status").textContent="Updating only those parts…";
  try{
    if(rejected.length){
      const normal=state.run.normal_settings?.plan||[];const byHour=new Map(normal.map(r=>[Number(r.hour),r]));
      const actions=(state.run.actions||[]).filter(action=>rejected.includes(action.action_id));
      const edited=state.currentPlan.map(row=>{
        const next={...row};
        for(const action of actions){
          if((action.hours||[]).includes(Number(row.hour))){const base=byHour.get(Number(row.hour));if(base)next[action.field_name]=base[action.field_name]}
        }
        return next;
      });
      const revised=await verifyPlan(edited,"Selected parts returned to normal and re-checked.");
      if(!revised)throw new Error("The revised plan could not be verified.");
    }
    const reply=await api("/api/concerns",{
      run_id:state.run.run_id,revision:state.run.revision,plan_hash:state.run.plan_hash,
      accepted_aspects:accepted,objected_aspects:objected,rejected_action_ids:rejected,
      comment:$("concern-note").value.trim(),overrides:overrides(),
    });
    $("concern-status").textContent=reply.answer;toast("Your partial concern is attached to this plan.");
  }catch(error){$("concern-status").textContent=String(error.message||error)}
  finally{button.disabled=false}
}

async function loadParameterSummary(){
  try{
    const registry=await api("/api/parameters");const c=registry.counts||{};
    const guesses=(registry.parameters||[]).filter(row=>row.status==="assumption").slice(0,3).map(row=>row.path);
    $("parameter-summary").textContent=`${registry.parameters.length} operating numbers are registered: ${c.sourced||0} sourced, ${c.assumption||0} clearly marked assumptions and ${c.choice||0} software choices. First assumptions to replace for Tahir: ${guesses.join(", ")}.`;
  }catch(error){$("parameter-summary").textContent="The source register could not be loaded."}
}

function renderTimeline(plan){
  const root=$("timeline"); root.replaceChildren();
  const rows=[
    ["Price",r=>Number(r.power_price_eur_kwh||0)>.15?"hot":""],
    ["Lights",r=>Number(r.lighting_level||0)>.05?(Number(r.lighting_level)>.65?"hi":"on"):""],
    ["Engine",r=>r.chp_mode&&r.chp_mode!=="off"?"hi":""],
    ["Battery",r=>r.battery==="charge"?"charge":r.battery==="discharge"?"discharge":""],
  ];
  rows.forEach(([label,fn])=>{
    const line=document.createElement("div");line.className="timeline-row";
    const l=document.createElement("div");l.className="timeline-label";l.textContent=label;line.append(l);
    plan.forEach(row=>{const c=document.createElement("div");c.className="timeline-cell "+fn(row);c.title=`${row.hour}:00`;line.append(c)});
    root.append(line);
  });
}

function renderTable(plan){
  const body=$("plan-table");body.replaceChildren();
  plan.forEach(r=>{
    const tr=document.createElement("tr");
    const batt=r.battery==="idle"?"idle":`${r.battery} ${Math.round(r.battery_power_kw)} kW`;
    [String(r.hour).padStart(2,"0")+":00",cents(r.power_price_eur_kwh),r.heat_source,Math.round(r.lighting_level*100)+"%",batt,r.chp_mode].forEach(v=>{
      const td=document.createElement("td");td.textContent=v;tr.append(td);
    });body.append(tr);
  });
}

async function approve(){
  if(!state.run) {
    showError(new Error("There is no checked plan to approve."), "Approving the final plan");
    return;
  }
  const btn=$("approve-plan");btn.disabled=true;
  try{
    await api("/api/decision",{run_id:state.run.run_id,revision:state.run.revision,plan_hash:state.run.plan_hash,decision:"approve",comment:"Approved in team demo"});
    $("decision-copy").textContent="Approved. This revision is now recorded as the final day plan.";
    btn.textContent="✓ Approved";toast("Final plan approved.");
  }catch(error){showError(error, "Approving the final plan");btn.disabled=false}
}

function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));}

$("battery-reserve").addEventListener("input",()=>$("reserve-value").textContent=$("battery-reserve").value+"%");
$("refresh-data").addEventListener("click",loadContext);
$("build-plan").addEventListener("click",buildPlan);
$("use-normal-plan").addEventListener("click",useNormalPlan);
$("compare-safety").addEventListener("click",compareSafety);
$("raise-concern").addEventListener("click",openConcern);
$("submit-concern").addEventListener("click",submitConcern);
$("approve-plan").addEventListener("click",approve);
$("recalculate").addEventListener("click",()=>{document.querySelector(".collaboration").scrollIntoView({behavior:"smooth",block:"start"});toast("Change the grower choices, then build the plan again.");});

loadContext();
loadParameterSummary();
