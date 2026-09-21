#!/usr/bin/env python3
"""GreenLight-Gym2 worker: a JSON-line server around the greenhouse physics model.

SPDX-License-Identifier: AGPL-3.0-or-later

This file runs in its own virtual environment and its own process, for two
independent reasons, either of which alone would force the split:

1. **Licence.** ``gl-gym`` is AGPL-3.0-or-later. Anything linked into it inherits
   that obligation. KasFlex core never imports ``gl_gym``; it talks to this worker
   over a pipe, so the core stays Apache-2.0 and reusable by partners who cannot
   take on a copyleft obligation.
2. **Dependencies.** ``gl-gym`` pins ``numpy<2.0``. ``power-grid-model`` requires
   ``numpy>=2.0``. They cannot be installed in the same environment at all.

The protocol is one JSON object per line on stdin, one per line on stdout. It is
deliberately dumb: this file imports nothing from KasFlex, so the AGPL surface is
exactly this file plus its own environment.

See ../../docs/DECISIONS.md ADR-0001 and ADR-0002.
"""

from __future__ import annotations

import json
import sys
import traceback

import gl_gym  # noqa: F401  -- registers gl_gym/GreenLightTomato-v0
import gymnasium as gym
import numpy as np
from gl_gym.components.rule_based import RuleBasedController
from gl_gym.core.types import StepContext
from gl_gym.environments.utils import co2dens2ppm, co2ppm2dens, satVp

# GreenLight parameter vector indices, from gl_gym/configs/greenlight_parameters.py.
P_FLOOR_AREA = 46
P_MAX_HEATING_POWER = 108
P_MAX_CO2_DOSING = 109
P_LAMP_POWER = 172

STEPS_PER_HOUR = 4  # 900 s solver timestep

# Defaults from configs/agents/rule_based.yml, which the GL-Gym baseline script loads.
RULE_BASED_DEFAULTS = dict(
    lamps_on=0, lamps_off=18, lamps_day_start=-1, lamps_day_stop=366,
    lamps_off_sun=400, lamp_rad_sum_limit=10,
    temp_setpoint_day=19.5, temp_setpoint_night=16.5,
    heat_correction=0, heat_deadzone=5,
    co2_day=800, vent_heat_Pband=4,
    rh_max=85, mech_dehumid_Pband=2, vent_rh_Pband=5,
    t_vent_off=1, vent_cold_Pband=-1,
    thScrSpDay=5, thScrSpNight=10, thScrPband=-1, thScrDeadZone=4,
    thScrRh=-2, thScrRhPband=2,
    lampExtraHeat=2, blScrExtraRh=100, rhMax=85,
    tHeatBand=-1, co2Band=-100, useBlScr=1,
)


def _context(env) -> StepContext:
    raw = env.unwrapped
    return StepContext(
        t=raw.timestep, dt=raw.dt, Np=raw.Np,
        x_prev=raw.x_prev, x=raw.x, u=raw.u, p=raw.p,
        d=raw.weather_data,
        hour_of_day=raw.hour_of_day, day_of_year=raw.day_of_year,
    )


def simulate_day(request: dict) -> dict:
    """Simulate one day of hourly energy intent and return demands and climate.

    The planner's intent governs three channels only -- lighting level, whether heat
    is delivered at all, and whether CO2 is dosed. Everything else (ventilation,
    screens, the proportional heating response) stays with the validated rule-based
    controller. That is the whole point of the intent abstraction: the research
    question is energy management, not climate control, and a language model cannot
    act reliably at a 15-minute control resolution.
    """
    plan = request["plan"]
    floor_area_m2 = float(request.get("floor_area_m2", 50_000.0))
    scenario = request.get("scenario") or {}
    seed = int(request.get("seed", 0))
    hours = len(plan["intervals"])

    env_kwargs = dict(request.get("env_kwargs") or {})
    env_kwargs.setdefault("normalize_actions", False)
    env = gym.make("gl_gym/GreenLightTomato-v0", **env_kwargs)

    reset_options = {}
    if scenario:
        reset_options["scenario"] = scenario
    if request.get("parameter_overrides"):
        reset_options["parameter_overrides"] = request["parameter_overrides"]
    reset_options = reset_options or None
    env.reset(seed=seed, options=reset_options)

    controller = RuleBasedController(**{**RULE_BASED_DEFAULTS, **(request.get("rule_based") or {})})
    raw = env.unwrapped
    p = np.asarray(raw.p, dtype=float)
    model_area = float(p[P_FLOOR_AREA])
    scale = floor_area_m2 / model_area if model_area > 0 else 1.0

    heat_kw, co2_kg_h, temp_c, rh_pct, co2_ppm = [], [], [], [], []
    natural_dli = 0.0
    lighting_electricity_kwh = 0.0
    fruit_start = float(raw.x[25])
    truncated_at = None
    replay = dict(request.get("replay_controls") or {})
    expected_steps = hours * STEPS_PER_HOUR

    def control_series(name: str) -> list[float] | None:
        values = replay.get(name)
        if values is None:
            return None
        if not isinstance(values, list) or len(values) != expected_steps:
            raise ValueError(
                f"replay control {name!r} must contain {expected_steps} quarter-hour values"
            )
        parsed = [float(value) for value in values]
        if not np.all(np.isfinite(parsed)):
            raise ValueError(f"replay control {name!r} contains a non-finite value")
        return parsed

    heat_setpoints = control_series("heating_setpoint_c")
    co2_setpoints = control_series("co2_setpoint_ppm")
    measured_lighting = control_series("lighting_fraction")
    measured_thermal_screen = control_series("thermal_screen_fraction")
    measured_blackout_screen = control_series("blackout_screen_fraction")
    measured_ventilation = control_series("ventilation_fraction")

    initial = replay.get("initial_indoor") or {}
    if initial:
        initial_temp = float(initial["temperature_c"])
        initial_rh = float(initial["relative_humidity_pct"])
        initial_co2 = float(initial["co2_ppm"])
        if not np.all(np.isfinite([initial_temp, initial_rh, initial_co2])):
            raise ValueError("initial indoor measurements must be finite")
        raw.x[0] = co2ppm2dens(initial_temp, initial_co2) * 1e6
        raw.x[1] = raw.x[0]
        for index in (2, 3, 4, 5, 6, 7, 8, 9):
            raw.x[index] = initial_temp
        raw.x[15] = np.clip(initial_rh, 0, 100) / 100 * satVp(initial_temp)
        raw.x[16] = raw.x[15]
        raw.x_prev = raw.x.copy()

    step_index = 0

    for interval in plan["intervals"]:
        lighting = float(interval.get("lighting_level", 0.0))
        heat_on = interval.get("heat_source", "boiler") != "none"
        co2_on = interval.get("co2_source", "none") != "none"

        hour_heat_kw = hour_co2 = 0.0
        hour_temp = hour_rh = hour_co2ppm = 0.0
        steps = 0

        for _ in range(STEPS_PER_HOUR):
            action = np.asarray(controller.predict(_context(env)), dtype=np.float32).copy()
            # --- the low-level controller: intent overrides three channels ---
            action[4] = lighting                       # uLamp
            if not heat_on:
                action[0] = 0.0                        # uBoil
            if not co2_on:
                action[1] = 0.0                        # uCO2

            # Measured validation supplies Reference-compartment setpoints and
            # actuator positions at the model's 15-minute resolution. Heating
            # and CO2 consumption remain model outputs; feeding their measured
            # consumption back as control would make the comparison circular.
            if heat_setpoints is not None:
                action[0] = controller.proportional_control(
                    raw.x[2], heat_setpoints[step_index], controller.tHeatBand, 0, 1
                )
            if co2_setpoints is not None:
                co2_in_ppm = co2dens2ppm(raw.x[2], 1e-6 * raw.x[0])
                action[1] = controller.proportional_control(
                    co2_in_ppm, co2_setpoints[step_index], controller.co2Band, 0, 1
                )
            if measured_lighting is not None:
                action[4] = np.clip(measured_lighting[step_index], 0, 1)
            if measured_thermal_screen is not None:
                action[2] = np.clip(measured_thermal_screen[step_index], 0, 1)
            if measured_ventilation is not None:
                action[3] = np.clip(measured_ventilation[step_index], 0, 1)
            if measured_blackout_screen is not None:
                action[5] = np.clip(measured_blackout_screen[step_index], 0, 1)

            obs, _reward, terminated, truncated, info = env.step(action)
            u = np.asarray(raw.u, dtype=float)

            # Energy coupling. GreenhouseReward computes heating as
            #   u[0] * p[108] / p[46]  ->  W per m2 of floor
            # so the hub-scale demand is that density times the hub floor area.
            # Multiplying by the area *ratio* instead would be off by model_area.
            heat_w_m2 = u[0] * p[P_MAX_HEATING_POWER] / model_area
            hour_heat_kw += heat_w_m2 * floor_area_m2 / 1000.0
            co2_mg_s_m2 = u[1] * p[P_MAX_CO2_DOSING] / model_area
            hour_co2 += co2_mg_s_m2 * floor_area_m2 * 3600e-6 / STEPS_PER_HOUR
            # Parameter 172 is already a power density [W/m2]. Dividing it by
            # floor area under-reported lighting electricity by a factor of 144.
            lamp_w_m2 = u[4] * p[P_LAMP_POWER]
            lighting_electricity_kwh += (
                lamp_w_m2 * floor_area_m2 / 1000.0 * float(raw.dt) / 3600.0
            )

            climate = np.asarray(obs["IndoorClimateObservations"], dtype=float)
            hour_co2ppm += climate[0]
            hour_temp += climate[1]
            hour_rh += climate[2]

            # ``env.step`` advances the cursor first; on the final step the new
            # cursor equals len(weather_data). Account the weather just consumed.
            weather_index = min(max(raw.timestep - 1, 0), len(raw.weather_data) - 1)
            natural_dli += (
                float(raw.weather_data[weather_index, 0]) * 2.1 * 0.45 * raw.dt / 1e6
            )
            steps += 1
            step_index += 1
            if terminated or truncated:
                truncated_at = interval["hour"]
                break

        n = max(1, steps)
        heat_kw.append(hour_heat_kw / n)
        co2_kg_h.append(hour_co2)
        temp_c.append(hour_temp / n)
        rh_pct.append(hour_rh / n)
        co2_ppm.append(hour_co2ppm / n)
        if truncated_at is not None:
            break

    # Pad if the episode ended early, so the caller always gets one value per hour.
    while len(heat_kw) < hours:
        for series in (heat_kw, co2_kg_h, temp_c, rh_pct, co2_ppm):
            series.append(series[-1] if series else 0.0)

    fruit_growth_dm_mg_m2 = float(raw.x[25]) - fruit_start
    env.close()

    return {
        "heat_demand_kw": heat_kw,
        "co2_demand_kg_h": co2_kg_h,
        "temp_c": temp_c,
        "rh_pct": rh_pct,
        "co2_ppm": co2_ppm,
        "fruit_growth_kg_m2": fruit_growth_dm_mg_m2 * 1e-6 / 0.065,
        "natural_dli_mol_m2": natural_dli,
        "model": "greenlight-gym2",
        "validated": False,
        "diagnostics": {
            "model_floor_area_m2": model_area,
            "scale_factor": scale,
            "lamp_power_w_m2": float(p[P_LAMP_POWER]),
            "max_heating_power_w_m2": float(p[P_MAX_HEATING_POWER] / model_area),
            "truncated_at_hour": -1 if truncated_at is None else truncated_at,
            "heating_energy_kwh": float(sum(heat_kw)),
            "lighting_electricity_kwh": float(lighting_electricity_kwh),
            "co2_dosed_kg": float(sum(co2_kg_h)),
        },
    }


HANDLERS = {"simulate_day": simulate_day}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if request.get("cmd") == "shutdown":
                break
            handler = HANDLERS.get(request.get("cmd", ""))
            if handler is None:
                raise ValueError(f"unknown command {request.get('cmd')!r}")
            response = {"ok": True, "outcome": handler(request)}
        except Exception as exc:  # noqa: BLE001 - the pipe must never die silently
            response = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
