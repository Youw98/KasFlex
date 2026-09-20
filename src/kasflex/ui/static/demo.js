"use strict";

const $ = id => document.getElementById(id);
const state = {
  context:null, run:null, aiPlan:null, currentPlan:null, locale:{}, lang:"nl",
  busy:false, openedAt:performance.now(), firstResponseAt:null,
  settings:{date:"",latitude:51.99,longitude:4.25,area:50000,battery:2000}, experimentRows:[],
};
const DIMENSIONS = [
  {id:"money",nl:"Geld",en:"Money",nlHelp:"Kosten en besparing",enHelp:"Cost and saving"},
  {id:"crop",nl:"Tomaten",en:"Tomatoes",nlHelp:"Groei en klimaat",enHelp:"Growth and climate"},
  {id:"grid",nl:"Net",en:"Grid",nlHelp:"Contract en piek",enHelp:"Contract and peak"},
  {id:"work",nl:"Werkwijze",en:"Way of working",nlHelp:"Apparatuur en timing",enHelp:"Equipment and timing"},
];

async function api(path, body) {
  const response = await fetch(path, {
    method:body === undefined ? "GET" : "POST",
    headers:body === undefined ? {} : {"Content-Type":"application/json"},
    body:body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch {}
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}
function t(key, fallback="") { return state.locale[key] || fallback || key; }
function euro(value, digits=0) {
  return new Intl.NumberFormat(state.lang === "nl" ? "nl-NL" : "en-GB",
    {style:"currency",currency:"EUR",minimumFractionDigits:digits,maximumFractionDigits:digits})
    .format(Number(value || 0));
}
function num(value, digits=0) {
  return Number(value || 0).toLocaleString(state.lang === "nl" ? "nl-NL" : "en-GB",
    {minimumFractionDigits:digits,maximumFractionDigits:digits});
}
function cents(value) { return num(Number(value || 0) * 100, 1) + " ct/kWh"; }
function showError(error, action=t("action","Deze actie")) {
  const reason=String(error?.message || error || t("unknownError","Onbekende fout"));
  $("error").hidden=false;
  $("error").textContent=state.lang==="nl"?`${action} mislukt: ${reason}`:`${action} failed: ${reason}`;
}
function clearError(){ $("error").hidden=true; }
function toast(message){const el=$("toast");el.textContent=message;el.hidden=false;clearTimeout(el._t);el._t=setTimeout(()=>el.hidden=true,3200)}

async function setLanguage(language) {
  state.lang = language === "en" ? "en" : "nl";
  document.documentElement.lang=state.lang;
  localStorage.setItem("kasflex.language",state.lang);
  try { state.locale=await fetch(`/locales/${state.lang}.json`).then(r=>r.json()); }
  catch { state.locale={}; }
  document.querySelectorAll("[data-t]").forEach(el=>el.textContent=t(el.dataset.t,el.textContent));
  $("language").value=state.lang;
  renderDimensions();
  if(state.context) renderContext(state.context);
  if(state.run) renderResult(state.run);
}

function policy(){
  return {
    priority:document.querySelector('input[name="priority"]:checked')?.value || "balanced",
    avoid_chp_night:$("avoid-chp-night").checked,
    prefer_stored_heat:$("prefer-buffer").checked,
    battery_reserve_pct:Number($("battery-reserve").value),
    brief:$("brief").value.trim(),
  };
}
function overrides(){
  const out={data_source:"demo",planner:"collaborative","checker.enabled":$("safety-check").checked,
    language:state.lang,latitude:Number(state.settings.latitude),longitude:Number(state.settings.longitude),
    "hub.floor_area_m2":Number(state.settings.area),
    "hub.battery.capacity_kwh":Number(state.settings.battery)};
  if(state.context?.date) out.date=state.context.date;
  return out;
}

async function loadContext(){
  clearError(); $("data-pill").className="status-pill loading";
  $("data-pill").textContent=t("loading","Gegevens laden…"); $("build-plan").disabled=true;
  try{
    const prepared=await api("/api/demo-prepare",{overrides:{data_source:"demo",
      latitude:Number(state.settings.latitude),longitude:Number(state.settings.longitude)}});
    state.context=await api("/api/day-context",{overrides:{...overrides(),date:prepared.date}});
    state.settings.date=prepared.date; renderContext(state.context);
    $("data-pill").className="status-pill";
    $("data-pill").textContent=t("dataReady","Echte invoer gereed");
  }catch(error){$("data-pill").textContent=t("dataFailed","Gegevens niet beschikbaar");showError(error,t("prepareFailed","Voorbereiden mislukt"))}
  finally{$("build-plan").disabled=false}
}
function renderContext(ctx){
  const locale=state.lang==="nl"?"nl-NL":"en-GB";
  $("planning-date").textContent=new Date(ctx.date+"T12:00:00").toLocaleDateString(locale,{weekday:"short",day:"numeric",month:"short"});
  $("setting-date").value=ctx.date;
  $("price-low").textContent=cents(ctx.price.min_eur_kwh);
  $("price-low-hours").textContent=(ctx.price.cheapest_hours||[]).map(h=>String(h).padStart(2,"0")+(state.lang==="nl"?".00":":00")).join(", ");
  $("temp-range").textContent=`${num(ctx.weather.min_temp_c,1)}–${num(ctx.weather.max_temp_c,1)} °C`;
  $("sun-hours").textContent=`${ctx.weather.sun_hours} ${t("sunHours","uur bruikbaar daglicht")}`;
  $("grid-limit").textContent=num(ctx.grid.import_limit_kw/1000,1)+" MW";
  const hours=Object.keys(ctx.grid.congestion_windows||{});
  $("grid-window").textContent=hours.length?`${t("lowerLimit","Lagere grens")} ${hours[0]}.00–${Number(hours.at(-1))+1}.00`:t("noCongestion","Geen congestievenster");
}

async function buildPlan(){
  if(state.busy||!state.context)return;
  state.busy=true;clearError();const button=$("build-plan"),label=button.textContent;
  button.disabled=true;button.textContent=t("planning","Plan berekenen…");
  try{
    const result=await api("/api/run",{overrides:overrides(),policy:policy()});
    state.run=result;state.aiPlan=(result.plan||[]).map(row=>({...row}));
    state.currentPlan=(result.plan||[]).map(row=>({...row}));
    $("empty-state").hidden=true;$("result-state").hidden=false;renderResult(result);
  }catch(error){showError(error,t("buildFailed","Plan berekenen mislukt"))}
  finally{state.busy=false;button.disabled=false;button.textContent=label}
}

function renderResult(result){
  state.run=result;
  const m=result.metrics||{}, normal=result.normal_settings, saving=Number(normal?.saving_eur||0);
  $("result-cost").textContent=euro(m.net_cost_eur);
  $("result-saving").textContent=normal?(saving>=0?`${euro(saving)} ${t("belowNormal","lager dan normaal")}`:`${euro(-saving)} ${t("aboveNormal","hoger dan normaal")}`):t("noBaseline","Geen vergelijking");
  const growth=Number(m.fruit_growth_kg_m2||0);
  $("result-crop").textContent=`${num(growth,2)} kg/m²`;
  const band=Math.round(Number(m.temperature_band_hours||0));
  $("result-crop-note").textContent=`${band}/24 ${t("hoursInRange","uur binnen de ingestelde temperatuurgrenzen")}`;
  $("crop-card").className="big-result crop "+(band>=22?"good":"warn");
  const uncertainty=result.uncertainty||{}, cost=uncertainty.cost;
  $("risk-range").textContent=cost?`${euro(cost.low_eur)} – ${euro(cost.high_eur)}`:t("unknown","Nog onbekend");
  $("risk-basis").textContent=uncertainty.words?.why||t("tooLittleData","Nog te weinig gegevens");
  $("model-confidence").textContent=result.validated?t("high","Hoog"):t("low","Laag");
  $("model-confidence-note").textContent=result.validated?t("validated","Gevalideerd"):t("notCalibrated","Kasmodel is nog niet gekalibreerd");
  const position=result.grid_position?.position||"—";
  $("grid-position").textContent=position==="short"?t("short","Tekort"):position==="long"?t("long","Overschot"):position==="balanced"?t("balancedPosition","In balans"):"—";
  const badge=$("checker-badge");
  if(result.checker_enabled&&result.accepted){badge.className="checker-badge";badge.textContent=t("verified","✓ Onafhankelijk gecontroleerd");$("approve-plan").disabled=false}
  else if(!result.checker_enabled){badge.className="checker-badge bad";badge.textContent=t("checkerOff","Controle uit · niet goed te keuren");$("approve-plan").disabled=true}
  else{badge.className="checker-badge bad";badge.textContent=t("unsafe","Niet veilig om goed te keuren");$("approve-plan").disabled=true}
  renderChanges(result);renderTable(result.plan||[]);renderGrid(result.grid_position||{});
}

function renderDimensions(){
  const root=$("dimension-review");if(!root)return;const previous={};
  root.querySelectorAll("input:checked").forEach(input=>previous[input.name]=input.value);
  root.replaceChildren();
  DIMENSIONS.forEach(d=>{
    const card=document.createElement("fieldset");card.className="dimension";card.dataset.dimension=d.id;
    const legend=document.createElement("legend");legend.innerHTML=`<b>${d[state.lang]}</b><small>${d[state.lang+"Help"]}</small>`;card.append(legend);
    const choices=document.createElement("div");choices.className="dimension-options";
    [["agree",t("agree","Eens")],["unsure",t("unsure","Twijfel")],["disagree",t("disagree","Oneens")]].forEach(([value,label])=>{
      const item=document.createElement("label"),input=document.createElement("input"),span=document.createElement("span");
      input.type="radio";input.name=`dimension-${d.id}`;input.value=value;
      input.checked=(previous[input.name]||"unsure")===value;span.textContent=label;item.append(input,span);choices.append(item);
    });card.append(choices);root.append(card);
  });
}

async function submitReview(){
  if(!state.run)return;
  if(!state.firstResponseAt)state.firstResponseAt=performance.now();
  const accepted=[],unsure=[],objected=[];
  DIMENSIONS.forEach(d=>{
    const value=document.querySelector(`input[name="dimension-${d.id}"]:checked`)?.value;
    ({agree:accepted,unsure,disagree:objected}[value]||unsure).push(d.id);
  });
  const button=$("submit-review"),old=button.textContent;button.disabled=true;button.textContent=t("answering","Reactie maken…");
  try{
    const reply=await api("/api/concerns",{run_id:state.run.run_id,revision:state.run.revision,
      plan_hash:state.run.plan_hash,accepted_aspects:accepted,unsure_aspects:unsure,
      objected_aspects:objected,rejected_action_ids:[],comment:"",overrides:overrides(),
      time_to_first_response_s:Math.round((state.firstResponseAt-state.openedAt)/1000),
      time_to_final_response_s:Math.round((performance.now()-state.openedAt)/1000)});
    renderCounterproposals(reply);toast(t("responseReady","Reactie per onderdeel is klaar."));
  }catch(error){showError(error,t("responseFailed","Reactie maken mislukt"))}
  finally{button.disabled=false;button.textContent=old}
}
function renderCounterproposals(reply){
  const root=$("counterproposals");root.replaceChildren();root.hidden=false;
  const intro=document.createElement("p");intro.className="counter-intro";intro.textContent=reply.answer;root.append(intro);
  (reply.counterproposals||[]).forEach(proposal=>{
    const card=document.createElement("article"),title=document.createElement("h4"),text=document.createElement("p"),impact=document.createElement("p"),button=document.createElement("button");
    card.className="counter-card";title.textContent=proposal.title;text.textContent=proposal.rationale;
    const cost=Number(proposal.cost_delta_eur||0);
    impact.className="impact";impact.textContent=cost===0?t("noCostChange","Geen berekende kostenverandering"):`${cost>0?"+":""}${euro(cost)} ${t("versusPlan","ten opzichte van dit plan")}`;
    button.className="secondary";button.textContent=t("applyAlternative","Pas dit alternatief toe");
    button.onclick=()=>applyAlternative(proposal);card.append(title,text,impact,button);root.append(card);
  });
  if(!(reply.counterproposals||[]).length){const p=document.createElement("p");p.textContent=t("allAccepted","Alle vier onderdelen zijn geaccepteerd.");root.append(p)}
}
async function applyAlternative(proposal){
  const normal=state.run?.normal_settings?.plan||[];if(!normal.length)return;
  const ids=new Set(proposal.affected_action_ids||[]),actions=(state.run.actions||[]).filter(a=>ids.has(a.action_id));
  if(!actions.length){toast(t("noPlanChange","Dit antwoord vraagt geen wijziging in de uurplanning."));return}
  const byHour=new Map(normal.map(r=>[Number(r.hour),r]));
  const edited=state.currentPlan.map(row=>{const next={...row};for(const action of actions){if((action.hours||[]).includes(Number(row.hour))){const base=byHour.get(Number(row.hour));if(base)next[action.field_name]=base[action.field_name]}}return next});
  await verifyPlan(edited,t("alternativeChecked","Alternatief toegepast en opnieuw gecontroleerd."));
}
async function verifyPlan(rows,message){
  try{
    const revised=await api("/api/verify",{run_id:state.run.run_id,revision:state.run.revision,plan_hash:state.run.plan_hash,plan:rows});
    state.run=revised;state.currentPlan=(revised.plan||[]).map(r=>({...r}));renderResult(revised);toast(message);return revised;
  }catch(error){showError(error,t("verifyFailed","Opnieuw controleren mislukt"));return null}
}

function renderChanges(result){
  const root=$("changes-list");root.replaceChildren();
  (result.actions||[]).forEach(action=>{
    const card=document.createElement("article");card.className="change";
    const info=document.createElement("div"),buttons=document.createElement("div");
    const title=document.createElement("b"),reason=document.createElement("p");title.textContent=action.title;reason.textContent=action.reason;
    info.append(title,reason);buttons.className="change-buttons";
    const normal=document.createElement("button");normal.className="secondary";normal.textContent=t("useNormal","Gebruik normaal");normal.onclick=()=>applyAlternative({affected_action_ids:[action.action_id]});
    buttons.append(normal);card.append(info,buttons);root.append(card);
  });
  if(!(result.actions||[]).length)root.textContent=t("noChanges","Geen belangrijke wijzigingen ten opzichte van normaal.");
}
function renderTable(plan){
  const body=$("plan-table");body.replaceChildren();
  plan.forEach(r=>{const tr=document.createElement("tr");[
    String(r.hour).padStart(2,"0")+":00",cents(r.power_price_eur_kwh),r.heat_source,
    Math.round(r.lighting_level*100)+"%",r.battery==="idle"?"—":r.battery+" "+Math.round(r.battery_power_kw)+" kW",r.chp_mode
  ].forEach(value=>{const td=document.createElement("td");td.textContent=value;tr.append(td)});body.append(tr)});
}
function renderGrid(g){
  const fields=[
    [t("contractVolume","Gecontracteerd volume"),num(g.contracted_kwh/1000,1)+" MWh"],
    [t("plannedUse","Gepland nettoverbruik"),num(g.planned_net_kwh/1000,1)+" MWh"],
    [t("deviation","Afwijking"),num(g.deviation_kwh/1000,1)+" MWh"],
    [t("settlement","Spotafrekening afwijking"),euro(g.deviation_settlement_eur)],
    [t("priceRisk","Prijsrisico"),euro(g.price_risk_eur)],
    [t("volumeRisk","Volumerisico"),euro(g.volume_risk_eur)],
    [t("export","Teruglevering"),num(g.export_kwh/1000,1)+" MWh"],
    [t("exportRevenue","Opbrengst teruglevering"),euro(g.export_revenue_eur)],
  ];const root=$("grid-details");root.replaceChildren();
  fields.forEach(([label,value])=>{const card=document.createElement("article"),s=document.createElement("span"),b=document.createElement("b");s.textContent=label;b.textContent=value;card.append(s,b);root.append(card)});
}

async function compareSafety(){
  const button=$("compare-safety"),old=button.textContent;button.disabled=true;button.textContent=t("comparing","Beide plannen draaien…");
  try{
    const result=await api("/api/safety-comparison",{overrides:overrides(),policy:policy()});
    const root=$("safety-comparison");root.replaceChildren();root.hidden=false;
    (result.rows||[]).forEach(row=>{const card=document.createElement("article");card.className=row.checker_enabled?"on":"off";
      const title=document.createElement("b"),text=document.createElement("span");title.textContent=row.checker_enabled?t("safetyOn","Controle aan"):t("safetyOff","Controle uit");
      text.textContent=`${row.hard_violations} ${t("hardProblems","harde problemen")} · ${euro(row.cost_eur)} · ${Math.round(row.crop_band_hours)}/24 h`;card.append(title,text);root.append(card)});
  }catch(error){showError(error,t("compareFailed","Vergelijken mislukt"))}
  finally{button.disabled=false;button.textContent=old}
}
async function approve(){
  if(!state.run)return;const button=$("approve-plan");button.disabled=true;
  try{await api("/api/decision",{run_id:state.run.run_id,revision:state.run.revision,plan_hash:state.run.plan_hash,decision:"approve",comment:"Approved in grower view",research_consent:false});
    $("decision-copy").textContent=t("approvedText","Goedgekeurd. Deze versie is vastgelegd als dagplanning.");button.textContent=t("approved","✓ Goedgekeurd");toast(t("approvedToast","Plan goedgekeurd."))
  }catch(error){showError(error,t("approveFailed","Goedkeuren mislukt"));button.disabled=false}
}

function saveConfig(){
  const name=$("config-name").value.trim()||"KasFlex";
  const all=JSON.parse(localStorage.getItem("kasflex.namedConfigs")||"{}");all[name]=readSettings();
  localStorage.setItem("kasflex.namedConfigs",JSON.stringify(all));$("settings-status").textContent=`“${name}” opgeslagen in deze browser.`;
}
function readSettings(){return{date:$("setting-date").value,latitude:Number($("setting-lat").value),longitude:Number($("setting-lon").value),area:Number($("setting-area").value),battery:Number($("setting-battery").value),repetitions:Number($("setting-repetitions").value),models:$("setting-models").value.split(",").map(x=>x.trim()).filter(Boolean),conditions:$("setting-conditions").value.split(",").map(x=>x.trim()).filter(Boolean),checker:$("setting-checker").value,feedback:$("setting-feedback").value==="true"}}
async function applySettings(){state.settings={...state.settings,...readSettings()};$("settings-dialog").close();await loadContext();toast(t("settingsApplied","Instellingen toegepast op de volgende berekening."))}
function exportCsv(){
  let headers,rows,name;
  if(state.experimentRows.length){headers=["planner","checker_enabled","repetition","cost_eur","growth_kg_m2","peak_import_kw","accepted","error"];rows=state.experimentRows.map(r=>headers.map(key=>r[key]??""));name="experiment"}
  else if(state.run){headers=["hour","price_eur_kwh","heat_source","lighting_pct","battery","battery_power_kw","chp_mode"];rows=(state.run.plan||[]).map(r=>[r.hour,r.power_price_eur_kwh,r.heat_source,Math.round(r.lighting_level*100),r.battery,r.battery_power_kw,r.chp_mode]);name=state.run.date}
  else{$("settings-status").textContent=t("buildFirst","Bereken eerst een plan.");return}
  const blob=new Blob([[headers,...rows].map(row=>row.join(",")).join("\n")],{type:"text/csv"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`kasflex-${name}.csv`;a.click();URL.revokeObjectURL(a.href);
}
async function runExperiment(){const settings=readSettings(),button=$("run-experiment"),old=button.textContent;button.disabled=true;button.textContent="Experiment draait…";$("settings-status").textContent="";try{const result=await api("/api/experiment",{overrides:overrides(),planners:settings.conditions,repetitions:settings.repetitions,checker:settings.checker,feedback:settings.feedback,models:settings.models});state.experimentRows=result.rows||[];$("settings-status").textContent=`${state.experimentRows.length} runs gereed; ${result.errors||0} fout(en). Exporteer CSV om de resultaten te bewaren.`}catch(error){$("settings-status").textContent=String(error.message||error)}finally{button.disabled=false;button.textContent=old}}
async function loadParameterSummary(){try{const r=await api("/api/parameters"),c=r.counts||{};$("parameter-summary").textContent=`${r.parameters.length} getallen geregistreerd: ${c.sourced||0} met bron, ${c.assumption||0} aannames en ${c.choice||0} softwarekeuzes. Klik in de repository op docs/PARAMETERS.md voor het volledige register.`}catch{$("parameter-summary").textContent="Bronnenregister niet beschikbaar."}}
async function loadConsent(){try{const status=await api("/api/consent");if(status.study_active&&status.needs_consent){state.consent=status;$("consent-dialog").showModal()}}catch(error){showError(error,"Toestemming laden")}}
async function grantConsent(){const button=$("consent-grant");button.disabled=true;try{await api("/api/consent",{participant_id:state.consent.participant_id,version:state.consent.version,scopes:{research:$("consent-research").checked,quotes:$("consent-quotes").checked,outcomes:$("consent-outcomes").checked}});$("consent-dialog").close();toast("Uw keuze over onderzoek is vastgelegd.")}catch(error){$("consent-status").textContent=String(error.message||error)}finally{button.disabled=false}}

$("battery-reserve").addEventListener("input",()=>$("reserve-value").textContent=$("battery-reserve").value+"%");
$("language").addEventListener("change",event=>setLanguage(event.target.value));
$("build-plan").addEventListener("click",buildPlan);
$("submit-review").addEventListener("click",submitReview);
$("compare-safety").addEventListener("click",compareSafety);
$("approve-plan").addEventListener("click",approve);
$("show-plan").addEventListener("click",()=>$("details-dialog").showModal());
$("open-grid").addEventListener("click",()=>$("grid-dialog").showModal());
$("open-settings").addEventListener("click",()=>$("settings-dialog").showModal());
$("save-config").addEventListener("click",saveConfig);
$("apply-settings").addEventListener("click",applySettings);
$("export-csv").addEventListener("click",exportCsv);
$("run-experiment").addEventListener("click",runExperiment);
$("consent-grant").addEventListener("click",grantConsent);
$("consent-decline").addEventListener("click",()=>{$("consent-dialog").close();toast("U gebruikt KasFlex zonder onderzoeksopslag.")});

(async()=>{await setLanguage(localStorage.getItem("kasflex.language")||"nl");renderDimensions();await Promise.all([loadContext(),loadParameterSummary(),loadConsent()])})();
