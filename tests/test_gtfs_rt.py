"""Unit tests for the dependency-free GTFS-rt decoder and mapper."""

import importlib.util
import random
import sys
import time
from pathlib import Path

import pytest
from google.protobuf import json_format
from google.transit import gtfs_realtime_pb2 as pb

sys.path.insert(0, str(Path(__file__).parent))
import fixtures  # noqa: E402

# Load api/models.py and api/gtfs_rt.py as a package without importing aiohttp code.
API = Path(__file__).resolve().parents[1] / "custom_components" / "swiftly_is_straeto" / "api"
pkg = type(sys)("straeto_api")
pkg.__path__ = [str(API)]
sys.modules["straeto_api"] = pkg
for name in ("models", "gtfs_rt"):
    spec = importlib.util.spec_from_file_location(f"straeto_api.{name}", API / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
g = sys.modules["straeto_api.gtfs_rt"]

NOW = 1_792_000_000.0
ROUTES = fixtures.ROUTES["data"]["routes"]
NAMES = {"11": "11 - Mjódd <-> Seltjarnarnes"}
STOPS = {"90000295": ["11"], "90000011": ["11"], "90000030": ["11"]}


def build(vehicle_feed, trip_feed, routes=ROUTES, route_ids=("11",), stops=STOPS):
    return g.build_realtime(vehicle_feed, trip_feed, list(route_ids), stops, routes, NAMES, NOW)


def _reference(msg):
    return json_format.MessageToDict(msg, preserving_proto_field_name=True, use_integers_for_enums=True)


def _close(ours, ref, path=""):
    if isinstance(ref, dict):
        for key, value in ref.items():
            assert key in ours, f"missing {path}.{key}"
            _close(ours[key], value, f"{path}.{key}")
    elif isinstance(ref, list):
        assert len(ours) == len(ref), path
        for i, (a, b) in enumerate(zip(ours, ref)):
            _close(a, b, f"{path}[{i}]")
    elif isinstance(ref, float):
        assert ours == pytest.approx(ref, rel=1e-6, abs=1e-6), path
    elif isinstance(ref, str) and isinstance(ours, int):
        assert ours == int(ref), path  # int64 is a string in the JSON mapping
    else:
        assert ours == ref, path


def random_feed(rng, n_trips=150, n_stops=40):
    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(NOW)
    for t in range(n_trips):
        ent = feed.entity.add()
        ent.id = f"e{t}"
        tu = ent.trip_update
        tu.trip.trip_id = f"trip-{t}-ÁÐÉÍÓÚÝÞÆÖ"
        tu.trip.route_id = f"ST.{rng.randint(1, 60)}"
        tu.trip.start_date = "20261021"
        if rng.random() < 0.5:
            tu.trip.direction_id = rng.randint(0, 1)
        tu.vehicle.id = str(rng.randint(1, 9999))
        tu.timestamp = int(NOW) - rng.randint(0, 60)
        tu.delay = rng.randint(-2_000_000, 2_000_000)
        for s in range(rng.randint(1, n_stops)):
            u = tu.stop_time_update.add()
            u.stop_sequence = s + 1
            u.stop_id = str(90_000_000 + rng.randint(0, 999))
            u.arrival.time = int(NOW) + rng.randint(-100, 7200)
            u.arrival.delay = rng.randint(-900, 900)
            if rng.random() < 0.3:
                u.departure.time = u.arrival.time + 20
                u.departure.uncertainty = rng.randint(0, 120)
            if rng.random() < 0.05:
                u.schedule_relationship = rng.randint(0, 2)
        ent = feed.entity.add()
        ent.id = f"v{t}"
        vp = ent.vehicle
        vp.trip.trip_id = tu.trip.trip_id
        vp.vehicle.label = f"bus {t}"
        vp.position.latitude = 64 + rng.random()
        vp.position.longitude = -22 + rng.random()
        vp.position.bearing = rng.random() * 360
        vp.position.odometer = rng.random() * 1e6
        vp.position.speed = rng.random() * 30
        vp.current_status = rng.randint(0, 2)
        vp.timestamp = int(NOW)
        vp.occupancy_status = rng.randint(0, 6)
    # An alert entity, which the decoder should skip
    alert = feed.entity.add()
    alert.id = "alert"
    alert.alert.header_text.translation.add().text = "Hálka"
    return feed


def test_decoder_matches_official_bindings():
    rng = random.Random(7)
    for _ in range(5):
        feed = random_feed(rng)
        ours = g.parse_feed(feed.SerializeToString())
        ref = _reference(feed)
        ref["entity"] = [e for e in ref["entity"] if "alert" not in e]
        ours["entity"] = [e for e in ours["entity"] if set(e) != {"id"}]
        _close(ours, ref)


def test_negative_numbers_and_unknown_fields():
    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    ent = feed.entity.add()
    ent.id = "x"
    ent.trip_update.trip.trip_id = "T"
    ent.trip_update.delay = -1
    u = ent.trip_update.stop_time_update.add()
    u.arrival.delay = -2_147_483_648
    u.arrival.time = -5
    ent.trip_update.trip.Extensions  # noqa: B018  (extensions exist but are not used)
    decoded = g.parse_feed(feed.SerializeToString())
    tu = decoded["entity"][0]["trip_update"]
    assert tu["delay"] == -1
    assert tu["stop_time_update"][0]["arrival"] == {"delay": -2_147_483_648, "time": -5}


def test_bad_feeds_raise():
    for raw in (b"", b"<html>Unauthorized</html>", b"\x0a\xff", b"Not Found"):
        with pytest.raises(g.GTFSRealtimeDecodeError):
            g.parse_feed(raw)


def test_json_mapping_gives_same_result():
    vehicles, trips = fixtures.feeds(NOW)
    proto = build(g.parse_feed(vehicles.SerializeToString()), g.parse_feed(trips.SerializeToString()))
    as_json = build(
        g.parse_feed(json_format.MessageToJson(vehicles).encode()),
        g.parse_feed(json_format.MessageToJson(trips).encode()),
    )
    assert proto == as_json


@pytest.mark.parametrize("prefix", ["ST.", ""])
def test_mapping(prefix):
    vehicles, trips = fixtures.feeds(NOW, prefix)
    vs, ps = build(g.parse_feed(vehicles.SerializeToString()), g.parse_feed(trips.SerializeToString()))
    by_id = {v["id"]: v for v in vs}
    assert set(by_id) == {"V1", "V2", "V5"}  # V3 other route, V4 stale

    v1 = by_id["V1"]
    assert v1["routeId"] == "11" and v1["routeName"] == "11 - Mjódd <-> Seltjarnarnes"
    assert v1["blockId"] == "1101" and v1["tripId"] == "T1"
    assert v1["headsign"] == "Mjódd" and v1["directionId"] == "0"
    assert v1["nextStopName"] == "Eiðistorg" and v1["nextStopId"] == "90000295"
    assert v1["schAdhSecs"] == 180 and v1["schAdhStr"] == "3.0 min (late)"
    assert v1["loc"]["heading"] == 90.0 and v1["loc"]["lat"] == pytest.approx(64.1503, abs=1e-5)
    assert v1["scheduledHeadwaySecs"] is None

    v2 = by_id["V2"]
    assert v2["headsign"] == "Seltjarnarnes" and v2["isAtStop"]
    assert v2["nextStopName"] == "Hlemmur"
    assert v2["schAdhSecs"] == -90 and v2["schAdhStr"] == "1.5 min (early)"

    v5 = by_id["V5"]
    assert v5["headsign"] == "Seltjarnarnes" and v5["schAdhSecs"] is None
    assert v5["schAdhStr"] == "" and v5["nextStopName"] == ""

    by_stop = {p["stopId"]: p for p in ps}
    assert set(by_stop) == set(STOPS)
    eid = by_stop["90000295"]
    assert eid["stopName"] == "Eiðistorg" and eid["stopCode"] == 1295
    d = eid["destinations"][0]
    assert d["headsign"] == "Mjódd"
    assert [p["tripId"] for p in d["predictions"]] == ["T1", "T5"]  # T4 is cancelled
    first = d["predictions"][0]
    assert first["time"] == NOW + 120 and first["vehicleId"] == "V1" and first["blockId"] == "1101"
    assert first["min"] == 2 and not first["departure"]

    hl = by_stop["90000011"]["destinations"][0]
    assert hl["headsign"] == "Seltjarnarnes"
    assert [p["tripId"] for p in hl["predictions"]] == ["T2"]  # T3 is on route 14
    assert hl["predictions"][0]["departure"] is True

    lind = by_stop["90000030"]["destinations"][0]  # skipped by T2, no other trips
    assert lind["predictions"] == [] and lind["headsign"] == "Seltjarnarnes"


def test_without_route_info():
    vehicles, trips = fixtures.feeds(NOW, "")
    vs, ps = build(g.parse_feed(vehicles.SerializeToString()), g.parse_feed(trips.SerializeToString()), routes=[])
    assert {v["id"] for v in vs} == {"V1", "V2", "V5"}
    assert {v["routeName"] for v in vs} == {"11 - Mjódd <-> Seltjarnarnes"}
    assert len(ps) == 3


def test_trip_without_route_id_uses_stops():
    vehicles, trips = fixtures.feeds(NOW)
    for ent in trips.entity:
        ent.trip_update.trip.ClearField("route_id")
    for ent in vehicles.entity:
        ent.vehicle.trip.ClearField("route_id")
    vs, ps = build(g.parse_feed(vehicles.SerializeToString()), g.parse_feed(trips.SerializeToString()))
    # T1 has 3 stops on route 11; T2 only 2 served stops so it cannot be placed
    assert {v["id"] for v in vs} == {"V1"}


def test_speed_of_a_large_feed():
    feed = random_feed(random.Random(1), n_trips=400, n_stops=45)
    raw = feed.SerializeToString()
    start = time.perf_counter()
    decoded = g.parse_feed(raw)
    build(decoded, decoded, routes=ROUTES)
    elapsed = time.perf_counter() - start
    print(f"\n{len(raw) / 1024:.0f} KB decoded and mapped in {elapsed * 1000:.0f} ms")
    assert elapsed < 2
