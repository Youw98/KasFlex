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
function showError(error) { const box=$("error"); box.hidden=false; box.textContent=String(error.message||error); box.scrollIntoView({behavior:"smooth",block:"center"}); }
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
    showError(error);
  } finally {
    $("refresh-data").disabled=false;
  }
}

function renderContext(ctx) {
  $("planning-date").textContent = new Date(ctx.date+"T12:00:00").toLocaleDateString("en-GB",{weekday:"short",day:"numeric",month:"short",year:"numeric"});
  const origins = ctx.sources || {};
  $("source-summary").textContent = `prices: ${origins.prices || "cache"} · weather: ${origins.forecast_weather || "cache"}`;
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
  if (!state.context || state.busy) return;
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
  } catch(error){showError(error)}
  finally{state.busy=false;btn.disabled=false;btn.textContent=old}
}

function renderResult(result) {
  state.run=result;
  const normal=result.normal_settings;
  const saving=normal?Number(normal.saving_eur||0):0;
  $("result-cost").textContent=euro(result.metrics?.net_cost_eur);
  $("result-saving").textContent=normal ? (saving>=0 ? `${euro(saving)} below normal plan` : `${euro(-saving)} above normal plan`) : "No baseline comparison";
  $("result-peak").textContent=(Number(result.metrics?.peak_import_kw||0)/1000).toFixed(2)+" MW";
  $("result-band").textContent=Math.round(Number(result.metrics?.temperature_band_hours||0))+"/24 h";
  $("result-actions").textContent=String((result.actions||[]).length);
  $("plan-subtitle").textContent=`${labelPriority(result.policy?.priority)} · battery reserve ${Math.round(result.policy?.battery_reserve_pct||0)}% · compared with normal control.`;

  const badge=$("checker-badge");
  if(result.checker_enabled && result.accepted){
    badge.className="checker-badge"; badge.textContent="✓ Independently verified";
    $("approve-plan").disabled=false;
  } else {
    badge.className="checker-badge bad"; badge.textContent="Not safe to approve";
    $("approve-plan").disabled=true;
  }
  renderChanges(result);
  renderTimeline(result.plan||[]);
  renderTable(result.plan||[]);
}

function labelPriority(value){
  return value==="cost"?"Lowest cost":value==="grid"?"Grid relief":"Balanced";
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
  if(!state.run) return;
  const payload={
    run_id:state.run.run_id,revision:state.run.revision,plan_hash:state.run.plan_hash,
    plan:rows,
  };
  try{
    const revised=await api("/api/verify",payload);
    state.run=revised; state.currentPlan=(revised.plan||[]).map(r=>({...r}));
    renderResult(revised); toast(message);
  }catch(error){showError(error)}
}

async function applyNormalForAction(action){
  const normal=state.run?.normal_settings?.plan||[];
  const byHour=new Map(normal.map(r=>[Number(r.hour),r]));
  const edited=state.currentPlan.map(row=>{
    if(!(action.hours||[]).includes(Number(row.hour))) return {...row};
    const base=byHour.get(Number(row.hour)); if(!base) return {...row};
    return {...row,[action.field_name]:base[action.field_name]};
  });
  await verifyPlan(edited,"Your change was re-checked.");
}

async function restoreAiForAction(action){
  const byHour=new Map(state.aiPlan.map(r=>[Number(r.hour),r]));
  const edited=state.currentPlan.map(row=>{
    if(!(action.hours||[]).includes(Number(row.hour))) return {...row};
    const base=byHour.get(Number(row.hour)); if(!base) return {...row};
    return {...row,[action.field_name]:base[action.field_name]};
  });
  await verifyPlan(edited,"KasFlex suggestion restored and re-checked.");
}

async function useNormalPlan(){
  const normal=state.run?.normal_settings?.plan;
  if(!normal) return;
  await verifyPlan(normal.map(r=>({...r})),"Normal plan loaded and independently checked.");
}

function renderTimeline(plan){
  const root=$("timeline"); root.replaceChildren();
  const rows=[
    ["Price",r=>Number(r.power_price_eur_kwh||0)>.15?"hot":""],
    ["Lights",r=>Number(r.lighting_level||0)>.05?(Number(r.lighting_level)>.65?"hi":"on"):""],
    ["CHP",r=>r.chp_mode&&r.chp_mode!=="off"?"hi":""],
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
  if(!state.run)return;
  const btn=$("approve-plan");btn.disabled=true;
  try{
    await api("/api/decision",{run_id:state.run.run_id,revision:state.run.revision,plan_hash:state.run.plan_hash,decision:"approve",comment:"Approved in team demo"});
    $("decision-copy").textContent="Approved. This revision is now recorded as the final day plan.";
    btn.textContent="✓ Approved";toast("Final plan approved.");
  }catch(error){showError(error);btn.disabled=false}
}

function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));}

$("battery-reserve").addEventListener("input",()=>$("reserve-value").textContent=$("battery-reserve").value+"%");
$("refresh-data").addEventListener("click",loadContext);
$("build-plan").addEventListener("click",buildPlan);
$("use-normal-plan").addEventListener("click",useNormalPlan);
$("approve-plan").addEventListener("click",approve);
$("recalculate").addEventListener("click",()=>{document.querySelector(".collaboration").scrollIntoView({behavior:"smooth",block:"start"});toast("Change the grower choices, then build the plan again.");});

loadContext();
