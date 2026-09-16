"""Price accounting, forecast isolation and sensitivity reconciliation."""
from dataclasses import replace
from pathlib import Path

import pytest

from kasflex.adapters.greenhouse import SurrogateGreenhouse
from kasflex.config import ScenarioConfig
from kasflex.controllers.base import PlanningContext
from kasflex.controllers.rule_based import RuleBasedPlanner
from kasflex.data.synthetic import synthetic_day
from kasflex.energy.dispatch import dispatch_plan
from kasflex.forecast.cost import project_cost


def setup_day():
    config = ScenarioConfig.from_yaml('configs/scenario_westland_winter.yaml')
    hub = config.hub
    day = synthetic_day(config.date, seed=2, floor_area_m2=hub.floor_area_m2)
    forecast = tuple(replace(c, power_price_eur_kwh=-0.05 if i < 12 else 0.20,
                             gas_price_eur_kwh=0.02 + i * 0.002,
                             feed_in_price_eur_kwh=-0.02 if i < 12 else 0.08)
                     for i, c in enumerate(day.forecast))
    plan = RuleBasedPlanner().plan(PlanningContext(date=config.date, forecast=forecast, hub=hub))
    return hub, forecast, plan


def test_signed_hourly_components_reconcile_with_dispatch():
    hub, forecast, plan = setup_day()
    model = SurrogateGreenhouse()
    result = project_cost(plan, hub, forecast, model)
    outcome = model.simulate_day(plan, forecast, hub.floor_area_m2)
    conditions = [replace(c, heat_demand_kw=outcome.heat_demand_kw[i],
                          co2_demand_kg_h=outcome.co2_demand_kg_h[i])
                  for i, c in enumerate(forecast)]
    dispatch = dispatch_plan(plan, hub, conditions)
    t = result['totals']
    assert t['net_cost_eur'] == pytest.approx(dispatch.total_cost_eur)
    assert t['net_cost_eur'] == pytest.approx(t['electricity_import_eur'] + t['gas_eur']
                                           + t['liquid_co2_eur'] - t['export_revenue_eur'])
    assert any(r['electricity_import_eur'] < 0 for r in result['hourly'])
    gas_total = sum(iv.gas_input_kw*c.gas_price_eur_kwh
                    for iv,c in zip(dispatch.intervals, conditions, strict=True))
    assert t['gas_eur'] == pytest.approx(gas_total)


def test_fixed_plan_price_sensitivity_matches_recalculation():
    hub, forecast, plan = setup_day()
    base = project_cost(plan, hub, forecast, SurrogateGreenhouse())['totals']
    changed = tuple(replace(c, power_price_eur_kwh=c.power_price_eur_kwh+0.03,
                            feed_in_price_eur_kwh=c.export_price+0.03,
                            gas_price_eur_kwh=c.gas_price_eur_kwh*1.25) for c in forecast)
    actual = project_cost(plan, hub, changed, SurrogateGreenhouse())['totals']
    expected = (base['net_cost_eur'] + 0.03*(base['import_kwh']-base['export_kwh'])
                + .25*base['gas_eur'])
    assert actual['net_cost_eur'] == pytest.approx(expected)


def test_projection_uses_the_selected_plan():
    hub, forecast, plan = setup_day()
    seen = []
    class RecordingModel(SurrogateGreenhouse):
        def simulate_day(self, candidate, conditions, area):
            seen.append(candidate)
            return super().simulate_day(candidate, conditions, area)
    result = project_cost(plan, hub, forecast, RecordingModel())
    assert seen == [plan]
    assert result['basis'] == 'forecast-only'
    assert result['validated'] is False


def test_ui_forecast_does_not_read_actual_weather(tmp_path, monkeypatch):
    import kasflex.ui.server as server
    config_path = Path('configs/scenario_westland_winter.yaml').resolve()
    monkeypatch.chdir(tmp_path)
    ui = server.UiServer(config_path=str(config_path))
    day = server._day_for(ui.base)
    monkeypatch.setattr(server, '_day_for', lambda config: day)
    first = ui.run({})
    warmer = replace(day, actual=tuple(replace(c, outdoor_temp_c=c.outdoor_temp_c+10)
                                      for c in day.actual))
    monkeypatch.setattr(server, '_day_for', lambda config: warmer)
    second = ui.run({})
    assert first['cost_forecast'] == second['cost_forecast']
    assert first['metrics']['net_cost_eur'] != second['metrics']['net_cost_eur']
