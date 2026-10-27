"""End-to-end tests of the integration in Home Assistant with a mocked Swiftly API."""

from datetime import datetime, timedelta, UTC
import time

import pytest
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

import fixtures

BASE = "https://api.goswift.ly"
DOMAIN = "swiftly_is_straeto"
VEHICLES = f"{BASE}/real-time/is-straeto/vehicles"
PREDICTIONS = f"{BASE}/real-time/is-straeto/predictions"
ROUTES = f"{BASE}/info/is-straeto/routes"
VP = f"{BASE}/real-time/is-straeto/gtfs-rt-vehicle-positions"
TU = f"{BASE}/real-time/is-straeto/gtfs-rt-trip-updates"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Strætó BS",
        data={CONF_API_KEY: "test-key"},
        subentries_data=[
            ConfigSubentryData(
                data={
                    "route": "11",
                    "route_name": "11 - Mjódd <-> Seltjarnarnes",
                    "stops": ["90000295", "90000011", "90000030"],
                },
                subentry_type="device",
                title="11 - Mjódd <-> Seltjarnarnes",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


def _calls(aioclient_mock, url):
    return sum(1 for call in aioclient_mock.mock_calls if str(call[1]).split("?")[0] == url)


def _state(hass, unique_id, domain="sensor"):
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, f"no entity for {unique_id}"
    return hass.states.get(entity_id)


async def test_gtfs_rt_fallback(hass: HomeAssistant, aioclient_mock) -> None:
    now = time.time()
    vehicles, trips = fixtures.feeds(now)
    aioclient_mock.get(VEHICLES, status=401, json={"success": False})
    aioclient_mock.get(PREDICTIONS, status=401, json={"success": False})
    aioclient_mock.get(ROUTES, json=fixtures.ROUTES)
    aioclient_mock.get(VP, content=vehicles.SerializeToString())
    aioclient_mock.get(TU, content=trips.SerializeToString())

    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    sub = next(iter(entry.subentries))

    tracker = _state(hass, f"{sub}_1101_tracker", "device_tracker")
    assert tracker.attributes["latitude"] == pytest.approx(64.1503)
    assert tracker.attributes["longitude"] == pytest.approx(-21.9876)
    assert tracker.attributes["direction"] == 90.0

    adherence = _state(hass, f"{sub}_1101_schedule_adherence_seconds")
    assert float(adherence.state) == 180
    assert adherence.attributes["schedule_adherence_string"] == "3.0 min (late)"
    assert adherence.attributes["vehicle_id"] == "V1"
    assert adherence.attributes["headsign"] == "Mjódd"
    assert _state(hass, f"{sub}_1101_next_stop_name").state == "Eiðistorg"
    assert _state(hass, f"{sub}_1102_next_stop_name").state == "Hlemmur"
    assert float(_state(hass, f"{sub}_1102_schedule_adherence_seconds").state) == -90

    eid = _state(hass, f"{sub}_11_90000295_predicted_arrival_time")
    assert dt_util.parse_datetime(eid.state) == datetime.fromtimestamp(int(now) + 120, UTC)
    assert eid.attributes["vehicle_id"] == "V1"
    assert eid.attributes["device_class"] == "timestamp"
    assert eid.name.endswith("Eiðistorg -> Mjódd")
    assert eid.attributes["route"] == "11"
    assert eid.attributes["stop_name"] == "Eiðistorg"
    assert eid.attributes["headsign"] == "Mjódd"
    hl = _state(hass, f"{sub}_11_90000011_predicted_arrival_time")
    assert hl.name.endswith("Hlemmur -> Seltjarnarnes")
    lind = _state(hass, f"{sub}_11_90000030_predicted_arrival_time")
    assert lind.state == "unknown"
    assert lind.attributes["stop_name"] == "Lindarbraut" and "vehicle_id" not in lind.attributes

    device = er.async_get(hass).async_get(eid.entity_id).device_id
    assert device == er.async_get(hass).async_get(tracker.entity_id).device_id
    entities = [e for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)]
    assert len(entities) == 3 * 3 + 3  # 3 buses x (tracker + 2 sensors) + 3 stops

    # Next update goes straight to GTFS-rt, and route info is cached
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert _calls(aioclient_mock, VEHICLES) == 1
    assert _calls(aioclient_mock, VP) == 2
    assert _calls(aioclient_mock, TU) == 2
    assert _calls(aioclient_mock, ROUTES) == 1


async def test_key_without_any_access(hass: HomeAssistant, aioclient_mock) -> None:
    for url in (VEHICLES, PREDICTIONS, VP, TU):
        aioclient_mock.get(url, status=403, json={"success": False})
    aioclient_mock.get(ROUTES, json=fixtures.ROUTES)
    entry = _entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert "GTFS-rt" in (entry.reason or "")


async def test_garbage_feed(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(VEHICLES, status=401, json={"success": False})
    aioclient_mock.get(ROUTES, json=fixtures.ROUTES)
    aioclient_mock.get(VP, content=b"<html>oops</html>")
    aioclient_mock.get(TU, content=b"<html>oops</html>")
    entry = _entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert "vehicle positions" in (entry.reason or "")


async def test_json_endpoints_still_used_when_allowed(hass: HomeAssistant, aioclient_mock) -> None:
    now = int(time.time())
    aioclient_mock.get(VEHICLES, json={"success": True, "route": "", "data": {"agencyKey": "is-straeto", "vehicles": [{
        "id": "V9", "routeId": "11", "routeName": "11 - Mjódd <-> Seltjarnarnes", "headsign": "Mjódd",
        "loc": {"lat": 64.1, "lon": -21.9, "time": now, "speed": 1, "heading": 10},
        "schAdhSecs": 30, "schAdhStr": "0.5 min (late)", "scheduledHeadwaySecs": 600,
        "nextStopName": "Hlemmur", "blockId": "11-3", "tripId": "T"}]}})
    aioclient_mock.get(PREDICTIONS, json={"success": True, "route": "", "data": {"agencyKey": "is-straeto", "predictionsData": [{
        "routeId": "11", "routeName": "11 - Mjódd <-> Seltjarnarnes", "stopId": "90000295", "stopName": "Eiðistorg",
        "destinations": [{"directionId": "0", "headsign": "Mjódd", "predictions": [
            {"time": now + 60, "sec": 60, "min": 1, "blockId": "11-3", "vehicleId": "V9", "tripId": "T"}]}]}]}})
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sub = next(iter(entry.subentries))
    assert _state(hass, f"{sub}_113_next_stop_name").state == "Hlemmur"
    assert _calls(aioclient_mock, VP) == 0
