# KasFlex Team Progress Demo Runbook

> **Purpose:** provide a reliable, repeatable progress-update demo that shows the
> KasFlex decision workflow end to end.
>
> **Audience:** project team, supervisors, researchers and technical stakeholders.
>
> **Demo objective:** show that KasFlex can turn a greenhouse-energy scenario into
> an understandable 24-hour plan, independently verify it, let a grower disagree
> with individual parts of the recommendation, generate a targeted alternative,
> re-check that alternative and record a final human decision.
>
> **Important:** this is a **progress demo**, not an operational validation claim.
> The default Showcase mode intentionally uses deterministic simulated input/output
> so the workflow can be demonstrated offline and reproducibly.

---

## 1. The one-sentence story

**Grower gives priorities → KasFlex proposes a 24-hour plan → an independent
checker verifies it → the grower challenges one part → KasFlex proposes a
quantified alternative → the alternative is checked again → the grower decides.**

Everything shown during the team demo should support this story.

---

## 2. What this demo is proving

The progress demo is meant to prove that the **decision architecture and user
interaction work**.

It should demonstrate all of the following:

- A planning day has an electricity-price profile, weather conditions and grid
  limits.
- The grower can choose what matters most: balanced, lowest cost, crop first or
  grid relief.
- The grower can add practical preferences such as avoiding CHP overnight,
  preferring stored heat and keeping a battery reserve.
- KasFlex creates a complete 24-hour energy plan.
- The plan contains real internal decisions for lighting, CHP, battery, boiler,
  heat buffer, CO2 source and grid interaction.
- A deterministic checker evaluates the plan independently from the planner.
- Checker ON and checker OFF can be demonstrated separately.
- KasFlex shows understandable headline numbers for money, crop, grid and energy
  position.
- The grower does not have to accept/reject the whole plan at once.
- The grower can agree with the money side and disagree with the crop side.
- A crop disagreement generates a crop-specific alternative.
- The alternative shows its trade-off numerically.
- Applying an alternative creates a new plan revision.
- The new revision is checked again.
- Final approval is only available after the four decision dimensions have been
  considered and the current plan passes verification.
- The final human decision is attached to the checked revision rather than to a
  stale plan.

This is enough for a strong progress update even while greenhouse-model calibration
is still ongoing.

---

## 3. What the numbers mean

### Showcase mode

The default **Showcase (offline)** mode uses a fixed deterministic scenario:

- Date: **2023-01-15**
- Seed: **0**
- Scenario: the default Westland winter greenhouse scenario
- Data source: synthetic/showcase
- Planner: collaborative
- Greenhouse outcomes: simulated
- Safety verification: real KasFlex checker logic
- Decision workflow: real KasFlex application logic

This mode exists so that a team presentation does not depend on Wi-Fi, ENTSO-E,
Open-Meteo or API availability.

The numbers may therefore be used to demonstrate:

- how KasFlex reasons about a plan;
- how priorities change a plan;
- how trade-offs are shown;
- how a checker blocks bad plans;
- how human disagreement changes the proposal;
- how approval is gated.

They must **not** be described as measured greenhouse performance.

### Real historical mode

The demo also offers **Real historical** input mode.

This uses the stricter KasFlex historical-input path and can demonstrate data
provenance. It may require cached/downloaded data and can therefore be less reliable
for a live presentation.

Use Real historical mode only when:

1. the historical day has already been successfully prepared;
2. it has been tested on the exact presentation machine;
3. the presentation does not depend on a network request succeeding live.

For the normal progress update, use Showcase mode.

---

## 4. Safe wording for the presentation

Recommended wording:

> "For this progress demo I am using a fixed showcase scenario so the results are
> reproducible and the demonstration does not depend on external APIs. The
> decision-making, planning, checker, alternative generation and approval flow are
> the actual KasFlex application. Greenhouse outcomes are still simulated and are
> not being presented as operational predictions."

If asked whether the numbers are real:

> "The showcase numbers are simulated and deterministic. KasFlex can also load real
> historical Dutch market and weather inputs, but the greenhouse model still needs
> further calibration before its crop and heat predictions should be treated as
> operational estimates."

If asked why simulated numbers are useful:

> "At this stage we are demonstrating the decision process: whether the system can
> propose, verify, explain, negotiate and revise a plan correctly. Model calibration
> is a separate validation workstream."

---

## 5. Things not to claim

Do **not** say:

- "KasFlex is proven to save this exact amount of money."
- "The tomato-growth number is measured."
- "The model is accurate enough to control a greenhouse."
- "The checker proves the crop is safe."
- "Real data means all outputs are real."
- "The AI controls equipment."
- "KasFlex is connected to SCADA or physical greenhouse hardware."
- "The current model is commercially validated."

Better wording:

- "estimated scenario cost"
- "simulated tomato outcome"
- "planner-independent deterministic verification"
- "research prototype"
- "showcase result"
- "checked against configured hard constraints"
- "human-approved plan"
- "not connected to equipment"

---

# 6. Pre-demo checklist

Complete this **before** the team meeting.

## Application

- [ ] Pull the latest `main` branch.
- [ ] Confirm the app launches normally.
- [ ] Confirm the grower/demo screen opens.
- [ ] Confirm **Showcase (offline)** is selected.
- [ ] Confirm the top data badge says **Showcase data · offline**.
- [ ] Confirm the simulation notice is visible.
- [ ] Confirm **Build tomorrow's plan** becomes enabled.
- [ ] Confirm no browser console errors appear during the main flow.

## Planning

- [ ] Balanced priority can be selected.
- [ ] Lowest cost can be selected.
- [ ] Crop first can be selected.
- [ ] Grid relief can be selected.
- [ ] Avoid CHP overnight can be toggled.
- [ ] Prefer stored heat can be toggled.
- [ ] Battery reserve changes visibly.
- [ ] A free-text practical note can be entered.
- [ ] Independent safety check can be toggled.

## Checker demonstration

- [ ] Click **Show what the check prevents**.
- [ ] Confirm two comparison cards appear.
- [ ] Confirm one card represents a baseline without checking.
- [ ] Confirm the checked version reports no hard realised violation.
- [ ] Confirm cost and simulated crop values are displayed.
- [ ] Confirm the checker comparison does not replace the grower's active plan.

## Plan generation

- [ ] Click **Build tomorrow's plan**.
- [ ] Confirm the decision screen loads.
- [ ] Confirm an expected/estimated cost appears.
- [ ] Confirm simulated tomato growth appears.
- [ ] Confirm energy position appears.
- [ ] Confirm the checker badge appears.
- [ ] Confirm plan highlights contain at least one meaningful change.

## Deliberation

- [ ] Agree with **saves money**.
- [ ] Disagree with **protects the crop**.
- [ ] Confirm KasFlex returns a targeted crop alternative.
- [ ] Confirm the response includes a numerical trade-off.
- [ ] Confirm **Use this alternative** works.
- [ ] Confirm the page updates to the new revision.
- [ ] Confirm the new revision is independently checked again.

## Approval

- [ ] Answer all four dimensions.
- [ ] Confirm the progress changes from 0/4 to 4/4.
- [ ] Confirm approval remains disabled before all four dimensions are answered.
- [ ] Confirm approval remains impossible for an unchecked/unaccepted plan.
- [ ] Confirm **Approve final plan** works on a checked revision.
- [ ] Confirm the success message is shown.

## Optional detail screens

- [ ] Position & grid opens.
- [ ] Risk & confidence opens.
- [ ] 24-hour plan opens.
- [ ] Data sources opens.
- [ ] All detail screens can be closed or navigated back from.

---

# 7. Recommended 7-minute demo

The demo below is deliberately short. Do not try to show every feature.

## 0:00–0:45 — Introduce the problem

Say:

> "A grower has to make an energy plan while balancing electricity prices, crop
> needs, grid restrictions and practical operating preferences. KasFlex is designed
> to support that decision rather than simply output one AI answer."

Point to:

- planning day;
- electricity prices;
- outside temperature;
- grid contract.

Do not explain implementation details yet.

---

## 0:45–1:45 — Show grower priorities

Point to the four priorities:

- Balanced
- Lowest cost
- Crop first
- Grid relief

Say:

> "Before the system makes a plan, the grower states what matters most for this
> specific day."

Leave **Balanced** selected for the standard demo.

Keep:

- Prefer stored heat: ON
- Battery reserve: 45%
- Safety checker: ON

Optional practical note:

> "Keep the evening peak low and avoid unnecessary cycling."

Explain that these are actual planning inputs.

---

## 1:45–2:30 — Demonstrate independent verification

Click:

**Show what the check prevents**

Say:

> "The planner and checker are separate. This button deliberately shows what can
> happen when a constraint-blind plan is allowed through versus when independent
> verification is active."

Point to:

- hard breaches;
- cost;
- simulated tomato growth.

Key message:

**A cheaper plan is not automatically an acceptable plan.**

Do not spend too long here.

---

## 2:30–3:15 — Build the plan

Click:

**Build tomorrow's plan**

When the decision page appears, stop and let the team read it.

Point to the four headline metrics:

1. Estimated cost
2. Simulated tomato growth
3. Bad-weather / uncertainty information
4. Energy position

Then point to the checker badge.

Say:

> "The system has produced a plan, but the grower still has to decide whether each
> part of the recommendation is acceptable."

---

## 3:15–4:45 — Show dimension-level decision-making

This is the most important part of the demo.

For **saves money**:

Click **Agree**.

Say:

> "I agree with the financial side."

For **protects the crop**:

Click **Disagree**.

Say:

> "But I am not comfortable with the crop side. I do not want to reject everything
> I already agreed with."

Wait for the targeted counterproposal.

Point to the changed numbers.

The response should explain a trade-off such as:

- supplemental light changes;
- simulated growth changes;
- expected cost changes.

Say:

> "KasFlex does not silently create a completely unrelated plan. It addresses the
> dimension I disagreed with and makes the trade-off visible."

---

## 4:45–5:30 — Apply the alternative

Click:

**Use this alternative**

Explain:

> "This creates a new revision. The previous approval state is not reused. The new
> proposal has to pass verification again."

Point out that:

- the headline values can change;
- plan highlights can change;
- the checker still applies.

This is an important safety/research point.

---

## 5:30–6:15 — Finish the four-part review

Respond to the remaining dimensions:

- respects the grid → Agree
- fits how I work → Agree or Unsure

If an alternative was applied, re-answer any dimensions that the UI correctly
requires again.

Point to the **0/4 → 4/4** progress indicator.

Say:

> "The application requires an explicit view on each dimension rather than treating
> a single click as consent to everything."

---

## 6:15–7:00 — Final approval

Click:

**Approve final plan**

Say:

> "The final decision remains human. KasFlex records approval against this specific
> checked revision, so an older approval cannot accidentally carry over to a changed
> plan."

Finish with:

> "The current work is therefore not just a dashboard. We now have an end-to-end
> workflow for proposing, checking, challenging, revising and approving a
> greenhouse-energy plan."

---

# 8. Optional 10-minute version

If there is more time, add the following after the main flow.

## Energy position

Open **Position & grid**.

Show:

- contracted electricity;
- planned requirement;
- short/long hours;
- settlement;
- grid limit.

Explain:

> "The grower does not only see a total cost. KasFlex also shows how the plan sits
> relative to the contracted position and grid capacity."

## 24-hour plan

Open **24-hour plan**.

Pick two or three hours only.

Good examples:

- expensive evening hour;
- cheap daytime hour;
- an hour with battery charging/discharging;
- an hour affected by the congestion window.

Do not walk through all 24 rows.

## Data sources

Open **Data sources**.

Explain the distinction:

- Showcase = deterministic presentation data
- Real historical = cached/downloaded market and weather data
- Measured validation = separate model-evaluation evidence

---

# 9. The demo scenario to rehearse

Use this exact default flow so the result is repeatable.

## Setup

- Input mode: **Showcase (offline)**
- Language: English
- Priority: **Balanced**
- Avoid CHP overnight: OFF
- Prefer stored heat: ON
- Battery reserve: **45%**
- Safety checker: ON
- Brief: optional

## Decision sequence

1. Build plan.
2. Money → Agree.
3. Crop → Disagree.
4. Read crop-specific trade-off aloud.
5. Use crop alternative.
6. Grid → Agree.
7. Work → Agree.
8. Re-answer anything reset by the plan revision.
9. Approve final plan.

This is the canonical progress-update path.

---

# 10. What should happen when crop is rejected

The server-side deliberation logic should:

1. keep the current plan as the reference;
2. copy the current grower policy;
3. switch the priority to `crop`;
4. ensure battery reserve is at least 55%;
5. run the collaborative planner again;
6. calculate new metrics;
7. produce a crop-specific explanation;
8. report:
   - old supplemental DLI;
   - new supplemental DLI;
   - old simulated tomato growth;
   - new simulated tomato growth;
   - change in expected cost;
9. offer the grower:
   - **Use this alternative**
   - **Keep current plan**

The alternative must not be applied until the grower explicitly selects it.

---

# 11. What should happen for every disagreement

| Dimension | Alternative objective |
|---|---|
| Money | Re-plan with cost as first priority |
| Crop | Re-plan with crop margin first and >=55% battery reserve |
| Grid | Re-plan with peak import reduction first |
| Work | Balanced plan + avoid CHP overnight + prefer stored heat |

Each alternative should show the trade-off relevant to the objection.

---

# 12. Checker story to explain

The checker is not the planner.

The planner proposes intent.

The checker evaluates configured constraints such as:

- grid import limit;
- grid export limit;
- battery charge/discharge power;
- battery state of charge;
- CHP minimum run time;
- CHP minimum down time;
- CHP ramp behaviour;
- heat demand coverage;
- supplemental-light target;
- model-dependent crop/climate bounds where applicable.

Hard deterministic constraints and model-dependent projected outcomes should not be
described as the same thing.

Recommended wording:

> "KasFlex independently verifies hard plan constraints. Some crop/climate outcomes
> still depend on the greenhouse model and therefore carry model uncertainty."

---

# 13. Why the checker ON/OFF comparison matters

This is one of the strongest research-demo moments.

With the checker disabled, a deliberately constraint-blind planner can create a
plan with hard violations.

With the checker enabled, KasFlex catches the violations and can fall back to a
known feasible baseline when necessary.

The comparison shows **what verification changes** rather than merely claiming that
verification is useful.

Important:

- The checker-OFF result is a demonstration condition.
- It is not an approvable grower plan.
- The grower workflow should keep the checker ON.

---

# 14. AI model selector: how to present it

The model selector is optional for the core demo.

The core collaborative planning flow does **not** require an external LLM to
function.

Recommended explanation:

> "The planning and verification workflow remains functional without an LLM. A
> language model can be used for explanation and conversational rewriting, but the
> deterministic planner/checker path does not depend on it."

If Claude or another configured model works during the demo, it can improve the
natural-language counterproposal.

If the model is unavailable, the deterministic counter-response must still work.

Do not make the main demo dependent on a live external model call.

---

# 15. Fallback plan if something fails

## If Wi-Fi fails

Stay in **Showcase (offline)**.

Nothing in the main progress-update flow should require internet access.

## If the AI provider fails

Continue.

The deterministic collaborative planner and counterproposal logic should still work.

Say:

> "The language-model layer is optional; the planning and safety workflow is still
> running locally."

## If Real historical fails

Switch back to **Showcase (offline)**.

Say:

> "The real-data path deliberately refuses to invent missing data. For the live
> presentation I will use the reproducible showcase scenario."

This is a feature, not an embarrassment.

## If a plan fails verification

Show it.

Say:

> "This is exactly why the checker exists."

Then rebuild with normal settings or return to the standard Balanced showcase path.

## If the browser UI becomes stale

1. Refresh the page.
2. Select Showcase (offline).
3. Use the canonical settings.
4. Rebuild the plan.

Because the showcase scenario is deterministic, the demo can be restarted.

---

# 16. Questions the team is likely to ask

## "Are these real prices?"

In Showcase mode:

> "No. They are deterministic showcase inputs used so the presentation is
> reproducible. The application also has a separate real-historical-data mode."

## "Are these tomato-growth numbers real?"

> "They are model outputs. They are deliberately labelled simulated. The greenhouse
> model has been replayed against measured AGC2 data, but calibration is not yet
> good enough for operational claims."

## "Then what is actually working?"

> "The planning workflow, energy dispatch logic, hard-constraint verification,
> human deliberation, targeted alternatives, revision handling and approval gating
> are working. Physical-model calibration is the next research step."

## "Why use AI?"

> "The project is studying decision support rather than autonomous control. AI can
> propose or explain, but verification is deterministic and the final decision
> remains with the grower."

## "Can the AI bypass the checker?"

> "No plan is eligible for final approval unless the current revision has passed the
> checker."

## "What happens if I change my mind?"

> "A changed alternative becomes a new revision and must be checked again. Approval
> is tied to the revision rather than to the session in general."

## "Why four separate decisions?"

> "A grower may accept the financial logic while rejecting the crop impact or
> practical operation. A single accept/reject button hides those differences."

## "Is it connected to a greenhouse?"

> "No. The current prototype is simulation/research software and the UI states that
> no equipment is connected."

## "What still needs to be done?"

> "The main next steps are greenhouse-model calibration, commercial-site data,
> grower usability testing, historical backtesting and evaluation of appropriate
> human reliance."

---

# 17. Progress-update structure for slides

A simple presentation can follow this order:

1. **Problem**
   Growers balance cost, crop, grid and operations.

2. **KasFlex concept**
   Human + planner + independent verification.

3. **What now works**
   Show the implemented end-to-end workflow.

4. **Live demo**
   Use the 7-minute flow in this document.

5. **What we learned**
   Decision-making and verification workflow is functional.

6. **Current limitation**
   Physical greenhouse calibration is not yet operationally acceptable.

7. **Next phase**
   Calibration + site data + grower testing + backtesting.

The presentation should use real screenshots from the current KasFlex interface,
not recreated or fake UI screenshots.

---

# 18. Technical acceptance criteria for the progress-demo release

The demo is ready only when all items below pass.

## Offline/reproducibility

- [ ] Showcase mode does not perform a required network fetch.
- [ ] Showcase uses fixed date 2023-01-15.
- [ ] Showcase uses fixed seed 0.
- [ ] Re-running the same choices gives reproducible results.
- [ ] Real historical mode remains separate.
- [ ] Synthetic/showcase input is visibly labelled.

## Plan generation

- [ ] Plan has 24 hourly intent rows.
- [ ] All hours are 0–23 exactly once.
- [ ] Metrics are finite.
- [ ] Cost is shown as an estimate/scenario result.
- [ ] Crop output is shown as simulated.
- [ ] Plan highlights are derived from the actual plan versus normal settings.

## Safety

- [ ] Checker ON result exposes its verification state.
- [ ] Checker OFF cannot be approved as checked.
- [ ] Deliberately unsafe edits are rejected.
- [ ] Hard violation count is visible in checker comparison.
- [ ] Revisions are re-verified.
- [ ] Stale revisions cannot be approved.

## Human deliberation

- [ ] Money response works.
- [ ] Crop response works.
- [ ] Grid response works.
- [ ] Work/practical-fit response works.
- [ ] Agree does not silently regenerate a plan.
- [ ] Disagree creates a dimension-specific alternative.
- [ ] Alternative contains a useful trade-off.
- [ ] Use alternative creates/loads a new revision.
- [ ] Keep current plan leaves current revision active.
- [ ] Approval requires all four dimensions.

## Presentation robustness

- [ ] Main demo works without an LLM provider.
- [ ] Main demo works without ENTSO-E credentials.
- [ ] Main demo works without a network connection.
- [ ] Errors are shown as user-readable messages rather than stack traces.
- [ ] Refreshing the page provides a clean restart path.
- [ ] English interface is fully usable.
- [ ] No fake interface screenshots are needed.

---

# 19. Suggested automated regression flow

A browser end-to-end test should eventually reproduce the canonical demo:

1. Open the demo page.
2. Confirm Showcase mode.
3. Wait until Build plan is enabled.
4. Select Balanced.
5. Keep stored heat enabled.
6. Set reserve to 45%.
7. Keep checker enabled.
8. Build plan.
9. Assert checker badge is present.
10. Assert cost is numeric.
11. Assert simulated crop output is numeric.
12. Agree with money.
13. Disagree with crop.
14. Assert targeted alternative appears.
15. Assert response contains crop trade-off information.
16. Use alternative.
17. Assert revision changes.
18. Assert checker status is refreshed.
19. Answer grid.
20. Answer work.
21. Assert approval is enabled only at 4/4.
22. Approve.
23. Assert final approved state is shown.

This should become a Playwright test before a higher-stakes public demo.

---

# 20. Current research limitation to keep visible

Measured replay against the Autonomous Greenhouse Challenge Second Edition has been
completed, but the current parameterisation is **not calibrated sufficiently for
operational use**.

The existing validation result currently indicates that electricity accounting is
much closer than heating and CO2 behaviour.

Therefore:

- the demo may show simulated numbers;
- the demo may show how decisions react to those numbers;
- the demo may show checker behaviour;
- the demo may not present the numbers as proven predictions for a commercial
  greenhouse.

This distinction protects the credibility of the project.

---

# 21. Definition of success for the team meeting

The demo is successful if, by the end, the team understands these five points:

1. **KasFlex can produce a complete plan.**
2. **The planner cannot simply approve itself.**
3. **A grower can disagree with one part without rejecting everything.**
4. **KasFlex exposes the trade-off of the alternative numerically.**
5. **The final decision remains with the grower and is tied to a checked revision.**

If those five ideas are clear, the progress update has done its job.

---

# 22. Final presenter checklist

Immediately before presenting:

- [ ] Laptop plugged in.
- [ ] Browser already open.
- [ ] KasFlex server already running.
- [ ] Showcase mode selected.
- [ ] Browser zoom at a readable level.
- [ ] No unrelated tabs/windows visible.
- [ ] Notifications disabled.
- [ ] Canonical demo flow rehearsed at least once.
- [ ] Presentation deck open as backup.
- [ ] One screenshot of the decision screen available as a visual backup.
- [ ] One screenshot of the crop-disagreement alternative available as backup.
- [ ] Do not update dependencies immediately before the presentation.
- [ ] Do not switch to Real historical unless it was tested on the same machine.
- [ ] Keep the demo under ten minutes.

---

# 23. Final message to the team

A concise closing statement:

> "The main progress is that the interaction loop now works end to end. KasFlex can
> take priorities, generate a plan, verify it independently, let the grower challenge
> individual dimensions, quantify an alternative, verify the new revision and record
> a final human decision. The next phase is not adding more interface features; it is
> improving the physical calibration and evaluating the workflow with real growers
> and real site data."
