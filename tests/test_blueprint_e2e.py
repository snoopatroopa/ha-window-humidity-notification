"""End-to-End-Test des Blueprints gegen einen echten Home-Assistant-Core (im Prozess).

Ausführen (Python 3.14, HA-Core per pip/uv):

    uv venv -p 3.14 .venv && uv pip install -p .venv/bin/python homeassistant
    .venv/bin/python -I tests/test_blueprint_e2e.py blueprints/automation/raumfeuchte_lueftung.yaml

Fest eingebaute Dauern (2 min, 30 min, 60-s-Mindestintervall) werden in einer
Kopie des Blueprints auf Sekunden verkürzt. Das Skript nutzt interne HA-APIs
(z. B. ConfigEntries._entries) und kann bei neuen HA-Versionen Anpassung brauchen.
Getestet mit HA 2026.11.1.
"""
import asyncio
import logging
import os
import re
import shutil
import sys
import tempfile

from homeassistant import bootstrap, config_entries
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

SRC = sys.argv[1]
problems: list[str] = []


class Catch(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            msg = record.getMessage()
            if "We found a custom integration" in msg or "recorder" in msg.lower():
                return
            problems.append(f"{record.levelname} {record.name}: {msg}")


logging.basicConfig(level=logging.WARNING)
logging.getLogger().addHandler(Catch())

sent: list[dict] = []
results: list[tuple[str, bool]] = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def msgs(tag=None, clear=None):
    out = []
    for m in sent:
        if tag and m.get("data", {}).get("tag") != tag:
            continue
        is_clear = m.get("message") == "clear_notification"
        if clear is not None and is_clear != clear:
            continue
        out.append(m)
    return out


async def main():
    cfg = tempfile.mkdtemp()
    bpdir = os.path.join(cfg, "blueprints", "automation", "test")
    os.makedirs(bpdir)
    text = open(SRC, encoding="utf-8").read()
    # Shorten fixed durations for the test
    text = text.replace("for:\n        minutes: 2", "for:\n        seconds: 2")
    text = text.replace("timeout:\n              minutes: 30", "timeout:\n              seconds: 12")
    assert text.count("seconds: 12") == 2
    text = text.replace("+ 1800", "+ 12")
    text = text.replace(", 60] | max", ", 1] | max")
    open(os.path.join(bpdir, "bp.yaml"), "w", encoding="utf-8").write(text)

    hass = HomeAssistant(cfg)
    from homeassistant import loader
    loader.async_setup(hass)
    await hass.config.async_set_time_zone("Europe/Berlin")
    base = {
        "homeassistant": {"time_zone": "Europe/Berlin"},
        "persistent_notification": {},
        "scene": {},
        "input_datetime": {
            "feuchte_pause": {"has_date": True, "has_time": True},
            "fenster_pause": {"has_date": True, "has_time": True},
        },
    }
    assert await bootstrap.async_from_config_dict(base, hass) is not None
    await hass.async_block_till_done()
    thermostat = "climate.bad"
    hass.states.async_set(thermostat, "heat", {"temperature": 22, "hvac_modes": ["off", "heat"], "supported_features": 1})

    async def clim(call: ServiceCall):
        st = hass.states.get(thermostat)
        attrs = dict(st.attributes)
        state = st.state
        if call.service == "set_temperature":
            attrs["temperature"] = call.data["temperature"]
            state = call.data.get("hvac_mode", state)
        elif call.service == "set_hvac_mode":
            state = call.data["hvac_mode"]
        elif call.service == "turn_off":
            state = "off"
        hass.states.async_set(thermostat, state, attrs)

    for sv in ("set_temperature", "set_hvac_mode", "turn_off", "turn_on"):
        hass.services.async_register("climate", sv, clim)
    # Fake mobile_app device + notify action
    entry = config_entries.ConfigEntry(
        data={}, discovery_keys={}, domain="mobile_app", minor_version=1, options={},
        source="user", subentries_data=None, title="Test", unique_id="x", version=1,
    )
    hass.config_entries._entries[entry.entry_id] = entry
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mobile_app", "p1")}, name="Test Phone"
    )

    async def notify(call: ServiceCall):
        d = dict(call.data)
        d["_t"] = dt_util.utcnow()
        sent.append(d)
        print("   notify:", round(asyncio.get_running_loop().time() % 1000, 1), d.get("message"), "| tag:", d.get("data", {}).get("tag"),
              "| actions:", [a["action"] for a in d.get("data", {}).get("actions", []) or []])

    hass.services.async_register("notify", "mobile_app_test_phone", notify)
    extra: list[dict] = []

    async def extra_cb(call: ServiceCall):
        extra.append(dict(call.data))

    hass.services.async_register("test", "extra", extra_cb)
    fan_calls: list[str] = []

    hass.states.async_set("sensor.bad_feuchte", "50", {"device_class": "humidity", "unit_of_measurement": "%"})
    hass.states.async_set("sensor.bad_temp", "23", {"device_class": "temperature", "unit_of_measurement": "°C"})
    hass.states.async_set("sensor.aussen_temp", "2.0", {"device_class": "temperature", "unit_of_measurement": "°C"})
    hass.states.async_set("sensor.aussen_feuchte", "80", {"device_class": "humidity", "unit_of_measurement": "%"})
    hass.states.async_set("sensor.bad_og_fenster", "closed")
    hass.states.async_set("switch.bad_luefter", "off")
    hass.states.async_set("sensor.kalt_feuchte", "50", {"device_class": "humidity", "unit_of_measurement": "%"})
    hass.states.async_set("sensor.kalt_fenster", "closed")

    async def sw(call: ServiceCall):
        for e in call.data["entity_id"] if isinstance(call.data["entity_id"], list) else [call.data["entity_id"]]:
            fan_calls.append(f"{call.service}:{e}")
            hass.states.async_set(e, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("switch", "turn_on", sw)
    hass.services.async_register("switch", "turn_off", sw)

    inputs = {
        "raum_name": "Bad OG",
        "feuchte_sensor": "sensor.bad_feuchte",
        "temperatur_sensor_innen": "sensor.bad_temp",
        "fenster_sensor": "sensor.bad_og_fenster",
        "feuchte_kritisch": 65,
        "feuchte_ok": 55,
        "mindestdauer_ueberschreitung": {"hours": 0, "minutes": 0, "seconds": 1},
        "max_dauer_nicht_zu": {"hours": 0, "minutes": 0, "seconds": 6},
        "max_dauer_ganz_offen": {"hours": 0, "minutes": 0, "seconds": 4},
        "cooldown": {"hours": 0, "minutes": 0, "seconds": 8},
        "taupunkt_pruefung_aktiv": True,
        "aussen_temperatur": "sensor.aussen_temp",
        "aussen_feuchte": "sensor.aussen_feuchte",
        "dauer_temperaturabhaengig": False,
        "notify_geraete": [dev.id],
        "zusaetzliche_aktionen": [{"action": "test.extra", "data": {"t": "{{ meldung_text }}"}}],
        "erinnerung_intervall": {"hours": 0, "minutes": 0, "seconds": 2},
        "max_erinnerungen": 2,
        "helfer_feuchte_pause": "input_datetime.feuchte_pause",
        "helfer_fenster_pause": "input_datetime.fenster_pause",
        "thermostat_aktiv": True,
        "thermostat": thermostat,
        "heizung_verzoegerung": {"hours": 0, "minutes": 0, "seconds": 1},
        "absenk_temperatur": 12,
        "luefter_aktiv": True,
        "luefter": "switch.bad_luefter",
    }
    import json
    autos = [
        {"id": "rfl_bad", "alias": "RFL Bad", "use_blueprint": {"path": "test/bp.yaml", "input": inputs}},
        {"id": "rfl_bad_falsch", "alias": "RFL falsch", "use_blueprint": {"path": "test/bp.yaml", "input": {
            **inputs, "raum_name": "Falsch", "feuchte_ok": 70}}},
        {"id": "rfl_kalt", "alias": "RFL Kalt", "use_blueprint": {"path": "test/bp.yaml", "input": {
            "raum_name": "Kalt", "feuchte_sensor": "sensor.kalt_feuchte", "fenster_sensor": "sensor.kalt_fenster",
            "max_dauer_ganz_offen": {"hours": 0, "minutes": 0, "seconds": 4},
            "max_dauer_nicht_zu": {"hours": 0, "minutes": 0, "seconds": 30},
            "dauer_temperaturabhaengig": True, "kalt_faktor": 0.5, "kalt_schwelle": 5,
            "aussen_temperatur": "sensor.aussen_temp", "notify_geraete": [dev.id], "max_erinnerungen": 0}}},
    ]
    open(os.path.join(cfg, "configuration.yaml"), "w").write("automation: !include automations.yaml\n")
    open(os.path.join(cfg, "automations.yaml"), "w").write(json.dumps(autos))
    ok = await async_setup_component(hass, "automation", {})
    await hass.services.async_call("automation", "reload", blocking=True)
    check("automation setup", ok)
    await hass.async_start()
    await hass.async_block_till_done()
    st = hass.states.get("automation.rfl_bad")
    check("automation loaded (state on)", st is not None and st.state == "on")
    if not st or st.state != "on":
        print(st, [x.entity_id for x in hass.states.async_all()])
        for p in problems: print(p)
        return

    async def wait(s):
        await asyncio.sleep(s)

    def setf(v):
        hass.states.async_set("sensor.bad_feuchte", v, {"device_class": "humidity", "unit_of_measurement": "%"})

    # --- 1. Restart guard: unavailable -> 70 must not notify
    setf("unavailable"); await wait(0.2)
    setf("70"); await wait(2)
    check("no humidity alert after unavailable -> 70", not msgs("feuchte_bad_og", clear=False))
    setf("60"); await wait(0.3)

    # --- 2. Humidity high, window closed -> 'bitte lüften' (or useless variant)
    sent.clear()
    setf("70"); await wait(2.0)
    m = msgs("feuchte_bad_og", clear=False)
    check("humidity alert sent with window closed", len(m) == 1)
    check("alert text mentions 70 %", m and "70 %" in m[0]["message"])
    check("alert has 2 action buttons", m and len(m[0]["data"]["actions"]) == 2)
    check("extra actions received meldung_text", extra and "Luftfeuchte im Bad OG" in extra[-1]["t"])
    check("fan switched on", "turn_on:switch.bad_luefter" in fan_calls)
    check("cooldown helper set in the future",
          hass.states.get("input_datetime.feuchte_pause").attributes["timestamp"] > dt_util.now().timestamp())
    # Hysteresis violation of the second instance
    pn = [s for s in hass.states.async_all() if "falsch" in s.entity_id]
    # --- 3. Cooldown: drop below crit (not ok) and rise again within cooldown -> no new alert
    sent.clear()
    setf("62"); await wait(0.3)
    setf("68"); await wait(1.6)
    check("cooldown suppresses second alert", not msgs("feuchte_bad_og", clear=False))
    await wait(6)

    # --- 4. Useless ventilation: outside humid & warm -> 'Lüften bringt nichts'
    hass.states.async_set("sensor.aussen_temp", "24", {"device_class": "temperature", "unit_of_measurement": "°C"})
    hass.states.async_set("sensor.aussen_feuchte", "90", {"device_class": "humidity", "unit_of_measurement": "%"})
    setf("60"); await wait(0.3)
    sent.clear()
    setf("72"); await wait(1.6)
    m = msgs("feuchte_bad_og", clear=False)
    check("dew point: 'Lüften bringt aktuell nichts' message", m and "bringt aktuell nichts" in m[0]["message"])
    print("   text:", m and m[0]["message"])
    hass.states.async_set("sensor.aussen_temp", "2.0", {"device_class": "temperature", "unit_of_measurement": "°C"})
    hass.states.async_set("sensor.aussen_feuchte", "80", {"device_class": "humidity", "unit_of_measurement": "%"})

    # --- 5. Window opens (tilted) -> clear humidity msg, thermostat lowered after delay
    sent.clear()
    t0 = hass.states.get(thermostat).attributes.get("temperature")
    hass.states.async_set("sensor.bad_og_fenster", "tilted"); await wait(1.5)
    check("feuchte notification cleared on window open", msgs("feuchte_bad_og", clear=True))
    check("thermostat lowered to 12", hass.states.get(thermostat).attributes.get("temperature") == 12)
    check("snapshot scene exists", hass.states.get("scene.rfl_bad_og_thermostat") is not None)

    # --- 6. tilted -> open after 3 s: nicht_zu must still fire at 6 s total, ganz_offen at 4 s open
    await wait(1.5)  # ~3 s since tilted
    hass.states.async_set("sensor.bad_og_fenster", "open")
    await wait(3.4)  # ~6.4 s since tilted, 3.4 s open
    m = msgs("fenster_bad_og", clear=False)
    check("nicht_zu alert fired despite tilted->open switch", any("nicht geschlossen" in x["message"] for x in m))
    print("   texts:", [x["message"] for x in m])
    await wait(1.0)  # 4.4 s open -> ganz_offen
    m = msgs("fenster_bad_og", clear=False)
    check("ganz_offen alert fired", any("ganz offen" in x["message"] and "Erinnerung" not in x["message"] for x in m))

    win_all_start = len(sent)
    # --- 7. Humidity ok while open -> 'Fenster kann geschlossen werden'; not blocked by loops
    setf("50"); await wait(2.5)
    m = [x for x in sent[win_all_start:] if x.get("data", {}).get("tag") == "feuchte_bad_og" and x["message"] != "clear_notification"]
    check("feuchte_ok message while loops are waiting", m and "kann geschlossen werden" in m[0]["message"])
    check("fan switched off", "turn_off:switch.bad_luefter" in fan_calls)

    # --- 8. Reminders: ganz_offen loop reminders every 2 s, max 2; nicht_zu loop must not duplicate
    await wait(4.5)
    m = [x for x in sent[win_all_start:] if x.get("data", {}).get("tag") == "fenster_bad_og" and x["message"] != "clear_notification"]
    print("   reminder texts:", [x["message"] for x in m])
    check("reminders sent", any("Erinnerung" in x["message"] for x in m))
    check("no duplicate reminders from nicht_zu loop while open", not any("nicht geschlossen" in x["message"] for x in m))

    # --- 9. Window closes -> loops end, notifications cleared, thermostat restored
    sent.clear()
    hass.states.async_set("sensor.bad_og_fenster", "closed"); await wait(0.5)
    check("fenster notification cleared", msgs("fenster_bad_og", clear=True))
    check("thermostat restored", hass.states.get(thermostat).attributes.get("temperature") == t0)
    check("snapshot scene deleted", hass.states.get("scene.rfl_bad_og_thermostat") is None)
    await wait(0.5)
    check("no running runs after close", hass.states.get("automation.rfl_bad").attributes.get("current") == 0)

    # --- 10. Snooze from window notification ends running loop and re-notifies later
    hass.states.async_set("sensor.bad_og_fenster", "open"); await wait(4.6)
    check("ganz_offen alert again", msgs("fenster_bad_og", clear=False))
    sent.clear()
    print("   SNOOZE at", round(asyncio.get_running_loop().time() % 1000, 1), hass.states.get("input_datetime.fenster_pause").state)
    hass.bus.async_fire("mobile_app_notification_action", {"action": "RFL_BAD_OG_FENSTER_SPAETER"})
    await wait(0.1); print("   helper", hass.states.get("input_datetime.fenster_pause").attributes, dt_util.now())
    await wait(8.0)
    print("   during snooze:", [x["message"] for x in msgs("fenster_bad_og", clear=False)])
    check("no reminders during snooze", not msgs("fenster_bad_og", clear=False))
    await wait(4.5)
    m = msgs("fenster_bad_og", clear=False)
    check("snooze re-notifies after delay", m and "seit mindestens" in m[0]["message"])
    # Ignore until closed
    hass.bus.async_fire("mobile_app_notification_action", {"action": "RFL_BAD_OG_FENSTER_IGNORIEREN"})
    await wait(0.5)
    sent.clear()
    await wait(4.5)
    check("no window messages while ignored", not msgs("fenster_bad_og", clear=False))
    hass.states.async_set("sensor.bad_og_fenster", "closed"); await wait(0.5)
    check("ignore reset on close",
          hass.states.get("input_datetime.fenster_pause").attributes["timestamp"] <= dt_util.now().timestamp() + 1)

    # --- 11. Unknown window state: only humidity msg, labelled
    await wait(3.5)
    hass.states.async_set("sensor.bad_og_fenster", "unavailable"); await wait(0.3)
    sent.clear()
    setf("75"); await wait(1.6)
    m = msgs("feuchte_bad_og", clear=False)
    check("humidity msg with unknown window", m and "Fensterstatus unbekannt" in m[0]["message"])
    print("   text:", m and m[0]["message"])
    await wait(5)
    check("no window msgs for unknown state", not msgs("fenster_bad_og", clear=False))

    # --- 12. Hysteresis guard of misconfigured instance
    pns = hass.data.get("persistent_notification", {})
    found = any("falsch" in k for k in (pns.keys() if isinstance(pns, dict) else []))
    check("persistent notification for bad hysteresis", found)

    # --- 13. Cold factor: 2 °C outside -> ganz_offen after 2 s instead of 4 s
    hass.states.async_set("sensor.aussen_temp", "2.0", {"device_class": "temperature", "unit_of_measurement": "°C"})
    sent.clear()
    hass.states.async_set("sensor.kalt_fenster", "open"); await wait(1.2)
    check("cold: no alert before shortened limit", not msgs("fenster_kalt", clear=False))
    await wait(1.5)
    m = msgs("fenster_kalt", clear=False)
    check("cold: alert after shortened limit", m and "kalt, Grenze verkürzt" in m[0]["message"])
    check("no helper -> no action buttons", m and m[0]["data"]["actions"] == [])
    print("   text:", m and m[0]["message"])
    hass.states.async_set("sensor.kalt_fenster", "closed"); await wait(0.5)
    # Warm: trigger fires at 2 s, actions wait the remaining 2 s
    hass.states.async_set("sensor.aussen_temp", "10", {"device_class": "temperature", "unit_of_measurement": "°C"})
    sent.clear()
    hass.states.async_set("sensor.kalt_fenster", "open"); await wait(3.2)
    check("warm: no alert before full limit", not msgs("fenster_kalt", clear=False))
    await wait(1.5)
    check("warm: alert after full limit", msgs("fenster_kalt", clear=False))
    # Warm, window closed during remaining wait -> no alert
    hass.states.async_set("sensor.kalt_fenster", "closed"); await wait(0.5)
    sent.clear()
    hass.states.async_set("sensor.kalt_fenster", "open"); await wait(3.0)
    hass.states.async_set("sensor.kalt_fenster", "closed"); await wait(2.0)
    check("warm: closed before full limit -> no alert", not msgs("fenster_kalt", clear=False))

    # --- 14. Humidity snooze / ignore
    hass.states.async_set("sensor.bad_og_fenster", "closed")
    setf("60"); await wait(9)  # cooldown expired
    sent.clear()
    setf("70"); await wait(1.6)
    check("humidity alert before snooze", msgs("feuchte_bad_og", clear=False))
    sent.clear()
    hass.bus.async_fire("mobile_app_notification_action", {"action": "RFL_BAD_OG_FEUCHTE_SPAETER"})
    await wait(8)
    check("humidity: nothing during snooze", not msgs("feuchte_bad_og", clear=False))
    await wait(5)
    m = msgs("feuchte_bad_og", clear=False)
    check("humidity: re-alert after snooze", m and "bitte lüften" in m[0]["message"])
    hass.bus.async_fire("mobile_app_notification_action", {"action": "RFL_BAD_OG_FEUCHTE_IGNORIEREN"})
    await wait(0.5)
    sent.clear()
    setf("60"); await wait(0.3); setf("71"); await wait(1.6)
    check("humidity: ignored until ok", not msgs("feuchte_bad_og", clear=False))
    setf("50"); await wait(2.5)
    check("humidity: ignore reset by feuchte_ok",
          hass.states.get("input_datetime.feuchte_pause").attributes["timestamp"] <= dt_util.now().timestamp() + 1)
    sent.clear()
    setf("72"); await wait(1.6)
    check("humidity: alerts again after ok", msgs("feuchte_bad_og", clear=False))

    await hass.async_stop()
    print("\n=== log warnings/errors ===")
    for p in problems:
        print(p)
    print(f"\n{sum(r for _, r in results)}/{len(results)} passed")


asyncio.run(main())
