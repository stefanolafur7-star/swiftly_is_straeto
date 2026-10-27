"""Synthetic Strætó data: Swiftly route info plus GTFS-rt feeds built with the official bindings."""

from google.transit import gtfs_realtime_pb2 as pb


def stop(sid, name, code):
    return {"id": sid, "name": name, "code": code, "lat": 64.1, "lon": -21.9}


EIDISTORG_0 = stop("90000295", "Eiðistorg", 1295)
HLEMMUR_0 = stop("90000010", "Hlemmur", 1010)
MJODD = stop("90000500", "Mjódd", 1500)
HLEMMUR_1 = stop("90000011", "Hlemmur", 1011)
LINDARBRAUT_1 = stop("90000030", "Lindarbraut", 1030)
EIDISTORG_1 = stop("90000296", "Eiðistorg", 1296)

ROUTES = {
    "success": True,
    "route": "/info/is-straeto/routes",
    "data": {
        "agencyKey": "is-straeto",
        "routes": [
            {
                "id": "11",
                "name": "11 - Mjódd <-> Seltjarnarnes",
                "shortName": "11",
                "longName": "Mjódd <-> Seltjarnarnes",
                "color": "f5a800",
                "type": "3",
                "directions": [
                    {"id": "0", "title": "Til Mjóddar", "headsigns": ["Mjódd"],
                     "stops": [EIDISTORG_0, HLEMMUR_0, MJODD]},
                    {"id": "1", "title": "Til Seltjarnarness", "headsigns": ["Seltjarnarnes"],
                     "stops": [MJODD, HLEMMUR_1, LINDARBRAUT_1, EIDISTORG_1]},
                ],
            }
        ],
    },
}

ROUTES_LIST = {
    "success": True,
    "route": "/info/is-straeto/routes",
    "data": {"agencyKey": "is-straeto", "routes": [{"id": "11", "name": "11 - Mjódd <-> Seltjarnarnes", "shortName": "11"}]},
}


def _header(feed, now):
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.incrementality = pb.FeedHeader.FULL_DATASET
    feed.header.timestamp = int(now)


def _trip(entity_id, feed, trip_id, route_id, stus, *, direction=None, vehicle=None,
          canceled=False, use_code=False):
    ent = feed.entity.add()
    ent.id = entity_id
    tu = ent.trip_update
    tu.trip.trip_id = trip_id
    if route_id is not None:
        tu.trip.route_id = route_id
    if direction is not None:
        tu.trip.direction_id = direction
    if canceled:
        tu.trip.schedule_relationship = pb.TripDescriptor.CANCELED
    if vehicle:
        tu.vehicle.id = vehicle[0]
        tu.vehicle.label = vehicle[1]
    for seq, st, when, delay, kind in stus:
        u = tu.stop_time_update.add()
        u.stop_sequence = seq
        u.stop_id = str(st["code"] if use_code else st["id"])
        if kind == "skip":
            u.schedule_relationship = pb.TripUpdate.StopTimeUpdate.SKIPPED
            continue
        ev = u.departure if kind == "dep" else u.arrival
        ev.time = int(when)
        ev.delay = delay
    return tu


def _vehicle(feed, entity_id, vid, label, trip_id, route_id, lat, lon, ts, *,
             direction=None, stop_id=None, seq=None, status=None, bearing=None, speed=None):
    ent = feed.entity.add()
    ent.id = entity_id
    vp = ent.vehicle
    if trip_id:
        vp.trip.trip_id = trip_id
    if route_id:
        vp.trip.route_id = route_id
    if direction is not None:
        vp.trip.direction_id = direction
    vp.vehicle.id = vid
    vp.vehicle.label = label
    vp.position.latitude = lat
    vp.position.longitude = lon
    if bearing is not None:
        vp.position.bearing = bearing
    if speed is not None:
        vp.position.speed = speed
    vp.timestamp = int(ts)
    if stop_id:
        vp.stop_id = stop_id
    if seq is not None:
        vp.current_stop_sequence = seq
    if status is not None:
        vp.current_status = status
    return vp


def feeds(now, route_prefix="ST."):
    r11, r14 = f"{route_prefix}11", f"{route_prefix}14"
    trips = pb.FeedMessage()
    _header(trips, now)
    _trip("t1", trips, "T1", r11, [
        (5, EIDISTORG_0, now + 120, 180, "arr"),
        (6, HLEMMUR_0, now + 900, 200, "arr"),
        (7, MJODD, now + 1800, 240, "arr"),
    ], vehicle=("V1", "1101"))
    _trip("t2", trips, "T2", r11, [
        (3, HLEMMUR_1, now + 300, -90, "dep"),
        (4, LINDARBRAUT_1, 0, 0, "skip"),
        (5, EIDISTORG_1, now + 700, -90, "arr"),
    ], direction=1, vehicle=("V2", "1102"))
    _trip("t3", trips, "T3", r14, [(2, HLEMMUR_1, now + 60, 0, "arr")], vehicle=("V3", "1401"))
    _trip("t4", trips, "T4", r11, [(1, EIDISTORG_0, now + 30, 0, "arr")], canceled=True)
    _trip("t5", trips, "T5", r11, [
        (1, EIDISTORG_0, now + 1500, 0, "arr"),
        (2, HLEMMUR_0, now + 2100, 0, "arr"),
    ], use_code=True)

    vehicles = pb.FeedMessage()
    _header(vehicles, now)
    _vehicle(vehicles, "v1", "V1", "1101", "T1", r11, 64.1503, -21.9876, now - 10,
             stop_id=EIDISTORG_0["id"], seq=5, status=pb.VehiclePosition.IN_TRANSIT_TO,
             bearing=90.0, speed=8.5)
    _vehicle(vehicles, "v2", "V2", "1102", "T2", r11, 64.1432, -21.9123, now - 5,
             direction=1, stop_id=HLEMMUR_1["id"], seq=3, status=pb.VehiclePosition.STOPPED_AT,
             bearing=270.0)
    _vehicle(vehicles, "v3", "V3", "1401", "T3", r14, 64.13, -21.90, now - 5)
    _vehicle(vehicles, "v4", "V4", "1104", "T8", r11, 64.13, -21.90, now - 3600)
    _vehicle(vehicles, "v5", "V5", "1105", "T9", r11, 64.12, -21.85, now - 20, direction=1)
    return vehicles, trips
