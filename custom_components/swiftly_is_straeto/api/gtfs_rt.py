"""GTFS-realtime support for Swiftly API keys without the JSON real-time endpoints.

Some Swiftly API keys only have the GTFS-rt trip updates and vehicle positions
feeds enabled. This module decodes those protobuf feeds without extra
dependencies and turns them into the same shapes the JSON /vehicles and
/predictions endpoints return, so the entities work unchanged.
"""

from __future__ import annotations

import json
import re
import struct
from typing import Any

from .models import JSONPredictionData, JSONRoute, JSONVehicle


class GTFSRealtimeDecodeError(Exception):
    """Raised when a GTFS-rt feed cannot be decoded."""


# Field number -> (name, type, repeated) for the parts of gtfs-realtime.proto we use.
_SCHEMA: dict[str, dict[int, tuple[str, str, bool]]] = {
    "FeedMessage": {
        1: ("header", "FeedHeader", False),
        2: ("entity", "FeedEntity", True),
    },
    "FeedHeader": {
        1: ("gtfs_realtime_version", "string", False),
        2: ("incrementality", "enum", False),
        3: ("timestamp", "uint64", False),
    },
    "FeedEntity": {
        1: ("id", "string", False),
        2: ("is_deleted", "bool", False),
        3: ("trip_update", "TripUpdate", False),
        4: ("vehicle", "VehiclePosition", False),
    },
    "TripUpdate": {
        1: ("trip", "TripDescriptor", False),
        2: ("stop_time_update", "StopTimeUpdate", True),
        3: ("vehicle", "VehicleDescriptor", False),
        4: ("timestamp", "uint64", False),
        5: ("delay", "int32", False),
    },
    "StopTimeUpdate": {
        1: ("stop_sequence", "uint32", False),
        2: ("arrival", "StopTimeEvent", False),
        3: ("departure", "StopTimeEvent", False),
        4: ("stop_id", "string", False),
        5: ("schedule_relationship", "enum", False),
    },
    "StopTimeEvent": {
        1: ("delay", "int32", False),
        2: ("time", "int64", False),
        3: ("uncertainty", "int32", False),
    },
    "TripDescriptor": {
        1: ("trip_id", "string", False),
        2: ("start_time", "string", False),
        3: ("start_date", "string", False),
        4: ("schedule_relationship", "enum", False),
        5: ("route_id", "string", False),
        6: ("direction_id", "uint32", False),
    },
    "VehicleDescriptor": {
        1: ("id", "string", False),
        2: ("label", "string", False),
        3: ("license_plate", "string", False),
    },
    "VehiclePosition": {
        1: ("trip", "TripDescriptor", False),
        2: ("position", "Position", False),
        3: ("current_stop_sequence", "uint32", False),
        4: ("current_status", "enum", False),
        5: ("timestamp", "uint64", False),
        6: ("congestion_level", "enum", False),
        7: ("stop_id", "string", False),
        8: ("vehicle", "VehicleDescriptor", False),
        9: ("occupancy_status", "enum", False),
    },
    "Position": {
        1: ("latitude", "float", False),
        2: ("longitude", "float", False),
        3: ("bearing", "float", False),
        4: ("odometer", "double", False),
        5: ("speed", "float", False),
    },
}

_WIRE_TYPES = {
    "bool": 0,
    "enum": 0,
    "int32": 0,
    "int64": 0,
    "uint32": 0,
    "uint64": 0,
    "double": 1,
    "string": 2,
    "float": 5,
}

# Enum values used below, by number and by name (JSON feeds use names).
_TRIP_CANCELED = {3, "CANCELED"}
_STOP_NOT_SERVED = {1, 2, "SKIPPED", "NO_DATA"}
_STOPPED_AT = {1, "STOPPED_AT"}

# Vehicle positions older than this are left out.
_STALE_SECONDS = 15 * 60


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise GTFSRealtimeDecodeError("Truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift >= 70:
            raise GTFSRealtimeDecodeError("Varint too long")


def _decode_message(buf: bytes, pos: int, end: int, message: str) -> dict[str, Any]:
    fields = _SCHEMA[message]
    out: dict[str, Any] = {}
    while pos < end:
        key, pos = _read_varint(buf, pos)
        number, wire = key >> 3, key & 7
        start = pos
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 1:
            pos += 8
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            start = pos
            pos += length
        elif wire == 5:
            pos += 4
        else:
            raise GTFSRealtimeDecodeError(f"Unsupported wire type {wire}")
        if pos > end:
            raise GTFSRealtimeDecodeError("Truncated field")

        spec = fields.get(number)
        if spec is None:
            continue  # Alerts, extensions and other fields we do not need
        name, kind, repeated = spec
        if kind in _SCHEMA:
            if wire != 2:
                continue
            value = _decode_message(buf, start, pos, kind)
        elif wire != _WIRE_TYPES[kind]:
            continue
        elif kind == "string":
            value = buf[start:pos].decode("utf-8", "replace")
        elif kind == "float":
            value = struct.unpack_from("<f", buf, start)[0]
        elif kind == "double":
            value = struct.unpack_from("<d", buf, start)[0]
        elif kind == "bool":
            value = value != 0
        elif kind in ("int32", "int64") and value >= 1 << 63:
            value -= 1 << 64  # Negative numbers are sign-extended to 64 bits

        if repeated:
            out.setdefault(name, []).append(value)
        else:
            out[name] = value
    return out


def _snake_case(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): _snake_case(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_snake_case(item) for item in data]
    return data


def parse_feed(raw: bytes) -> dict[str, Any]:
    """Decode a GTFS-rt FeedMessage (protobuf, or the protobuf JSON mapping)."""
    # A protobuf FeedMessage starts with its header field (0x0A), never with "{".
    if raw[:1] != b"\n" and raw.lstrip()[:1] == b"{":
        try:
            feed = json.loads(raw)
        except ValueError as err:
            raise GTFSRealtimeDecodeError(f"Invalid JSON feed: {err}") from err
        return _snake_case(feed)
    feed = _decode_message(raw, 0, len(raw), "FeedMessage")
    if "header" not in feed:
        raise GTFSRealtimeDecodeError("Feed has no header")
    return feed


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int) -> float | None:
    # Feed floats are 32-bit, so extra decimals are only noise
    return None if value is None else round(value, digits)


def _key(value: Any) -> str:
    return str(value).strip().lower()


def _tail(value: Any) -> str:
    """Return the part after a feed prefix, e.g. ST.11 -> 11."""
    return re.split(r"[.:_]", _key(value))[-1]


def adherence_string(delay: int | None) -> str:
    """Describe a delay the way Swiftly's schAdhStr does (positive is late)."""
    if delay is None:
        return ""
    if abs(delay) < 60:
        return "on time"
    return f"{abs(delay) / 60:.1f} min ({'late' if delay > 0 else 'early'})"


class _RouteIndex:
    """Maps feed route and stop ids to the routes and stops set up in Home Assistant."""

    def __init__(
        self,
        route_ids: list[str],
        routes: list[JSONRoute],
        route_names: dict[str, str],
    ) -> None:
        self.route_ids = list(route_ids)
        self.info: dict[str, JSONRoute] = {
            route["id"]: route for route in routes if route.get("id") in route_ids
        }
        self.names = route_names
        self._exact: dict[str, str] = {}
        self._loose: dict[str, str] = {}
        self.stop_names: dict[str, str] = {}
        self.stop_codes: dict[str, Any] = {}
        self._stop_alias: dict[str, str] = {}
        self._stop_directions: dict[tuple[str, str], list[dict]] = {}
        for route_id in self.route_ids:
            route = self.info.get(route_id, {})
            for value in (route_id, route.get("shortName")):
                if value:
                    self._exact.setdefault(_key(value), route_id)
                    self._loose.setdefault(_tail(value), route_id)
            for direction in route.get("directions") or []:
                for stop in direction.get("stops") or []:
                    stop_id = str(stop.get("id"))
                    self.stop_names.setdefault(stop_id, stop.get("name") or stop_id)
                    self.stop_codes.setdefault(stop_id, stop.get("code"))
                    self._stop_alias.setdefault(stop_id, stop_id)
                    if stop.get("code") not in (None, ""):
                        self._stop_alias.setdefault(str(stop["code"]), stop_id)
                    self._stop_directions.setdefault((route_id, stop_id), []).append(
                        direction
                    )

    def route(self, feed_route_id: Any) -> str | None:
        if feed_route_id in (None, ""):
            return None
        return self._exact.get(_key(feed_route_id)) or self._loose.get(
            _tail(feed_route_id)
        )

    def stop(self, feed_stop_id: Any) -> str | None:
        if feed_stop_id in (None, ""):
            return None
        return self._stop_alias.get(str(feed_stop_id), str(feed_stop_id))

    def stop_name(self, stop_id: str | None) -> str:
        return self.stop_names.get(stop_id, stop_id or "") if stop_id else ""

    def route_name(self, route_id: str) -> str:
        return (
            self.info.get(route_id, {}).get("name")
            or self.names.get(route_id)
            or route_id
        )

    def short_name(self, route_id: str) -> str:
        return self.info.get(route_id, {}).get("shortName") or route_id

    def guess_route(self, stop_ids: list[str]) -> str | None:
        """Find the route for a trip without route_id from the stops it serves."""
        if len(stop_ids) < 3:
            return None
        matches = [
            route_id
            for route_id in self.route_ids
            if all((route_id, stop) in self._stop_directions for stop in stop_ids)
        ]
        return matches[0] if len(matches) == 1 else None

    def direction(
        self, route_id: str, direction_id: Any, stop_ids: list[str]
    ) -> dict | None:
        directions = self.info.get(route_id, {}).get("directions") or []
        if direction_id is not None:
            for direction in directions:
                if str(direction.get("id")) == str(direction_id):
                    return direction
        # Pick the direction sharing most stops with the trip, in the same order.
        best, best_score = None, (0, 0)
        for direction in directions:
            order = {
                str(stop.get("id")): i
                for i, stop in enumerate(direction.get("stops") or [])
            }
            hits = [order[stop] for stop in stop_ids if stop in order]
            score = (
                len(hits),
                sum(b > a for a, b in zip(hits, hits[1:], strict=False)),
            )
            if score > best_score:
                best, best_score = direction, score
        return best

    def stop_headsign(self, route_id: str, stop_id: str) -> tuple[str, str]:
        """Return (direction id, headsign) for a stop on a route from route info."""
        directions = self._stop_directions.get((route_id, stop_id), [])
        if not directions:
            return "", ""
        direction = directions[0]
        return str(direction.get("id", "")), _direction_headsign(direction)


def _direction_headsign(direction: dict | None, last_stop: str = "") -> str:
    if not direction:
        return last_stop
    headsigns = [h for h in direction.get("headsigns") or [] if h]
    if len(headsigns) == 1:
        return headsigns[0]
    if last_stop:
        return last_stop
    if headsigns:
        return headsigns[0]
    stops = direction.get("stops") or []
    return (stops[-1].get("name") if stops else "") or direction.get("title") or ""


def _event_time(update: dict) -> tuple[int | None, bool]:
    """Return (epoch seconds, is departure) for a stop time update."""
    arrival = _int((update.get("arrival") or {}).get("time"))
    if arrival:
        return arrival, False
    departure = _int((update.get("departure") or {}).get("time"))
    return (departure, True) if departure else (None, False)


def _event_delay(update: dict) -> int | None:
    for event in ("arrival", "departure"):
        delay = _int((update.get(event) or {}).get("delay"))
        if delay is not None:
            return delay
    return None


def _is_upcoming(stu: dict, current_sequence: int | None, now: float) -> bool:
    """Return True for stops the vehicle has not passed yet."""
    sequence = _int(stu.get("stop_sequence"))
    if current_sequence is not None and sequence is not None:
        return sequence >= current_sequence
    return (_event_time(stu)[0] or now) >= now - 30


def _vehicle_names(descriptor: dict | None, fallback: str) -> tuple[str, str]:
    """Return (vehicle id, block id) for a vehicle descriptor.

    GTFS-rt has no block ids, so the bus label (or id) takes its place.
    """
    descriptor = descriptor or {}
    vehicle_id = str(descriptor.get("id") or descriptor.get("label") or fallback)
    return vehicle_id, str(descriptor.get("label") or vehicle_id)


def build_realtime(
    vehicle_feed: dict[str, Any],
    trip_feed: dict[str, Any],
    route_ids: list[str],
    stops: dict[str, list[str]],
    routes: list[JSONRoute],
    route_names: dict[str, str],
    now: float,
) -> tuple[list[JSONVehicle], list[JSONPredictionData]]:
    """Turn GTFS-rt feeds into Swiftly JSON vehicles and predictions.

    Only routes and stops that are set up in Home Assistant are returned.
    """
    index = _RouteIndex(route_ids, routes, route_names)

    trips: dict[str, dict[str, Any]] = {}
    for entity in trip_feed.get("entity") or []:
        update = entity.get("trip_update")
        if not update or entity.get("is_deleted"):
            continue
        trip = update.get("trip") or {}
        if trip.get("schedule_relationship") in _TRIP_CANCELED:
            continue
        stop_updates = [
            {**stu, "stop_id": index.stop(stu.get("stop_id"))}
            for stu in update.get("stop_time_update") or []
            if stu.get("schedule_relationship") not in _STOP_NOT_SERVED
        ]
        stop_updates.sort(key=lambda stu: _int(stu.get("stop_sequence")) or 0)
        stop_ids = [stu["stop_id"] for stu in stop_updates if stu["stop_id"]]
        route_id = index.route(trip.get("route_id"))
        if route_id is None and not trip.get("route_id"):
            route_id = index.guess_route(stop_ids)
        if route_id is None:
            continue
        trip_id = str(trip.get("trip_id") or entity.get("id") or "")
        direction = index.direction(route_id, trip.get("direction_id"), stop_ids)
        vehicle_id, block_id = _vehicle_names(update.get("vehicle"), "")
        trips[trip_id] = {
            "route_id": route_id,
            "direction_id": str(direction.get("id", "")) if direction else "",
            "headsign": _direction_headsign(
                direction, index.stop_name(stop_ids[-1]) if stop_ids else ""
            ),
            "stop_updates": stop_updates,
            "delay": _int(update.get("delay")),
            "vehicle_id": vehicle_id,
            "block_id": block_id,
        }

    vehicles: list[JSONVehicle] = []
    seen_blocks: set[str] = set()
    for entity in vehicle_feed.get("entity") or []:
        position = entity.get("vehicle")
        if not position or entity.get("is_deleted"):
            continue
        location = position.get("position") or {}
        lat, lon = _float(location.get("latitude")), _float(location.get("longitude"))
        if lat is None or lon is None:
            continue
        timestamp = _int(position.get("timestamp"))
        if timestamp and now - timestamp > _STALE_SECONDS:
            continue
        descriptor = position.get("trip") or {}
        trip_id = str(descriptor.get("trip_id") or "")
        trip = trips.get(trip_id, {})
        route_id = index.route(descriptor.get("route_id")) or trip.get("route_id")
        if route_id is None:
            continue
        vehicle_id, block_id = _vehicle_names(
            position.get("vehicle"), str(entity.get("id") or trip_id)
        )
        if block_id in seen_blocks:
            continue
        seen_blocks.add(block_id)

        current_sequence = _int(position.get("current_stop_sequence"))
        upcoming = [
            stu
            for stu in trip.get("stop_updates", [])
            if _is_upcoming(stu, current_sequence, now)
        ]
        next_stop = index.stop(position.get("stop_id")) or next(
            (stu["stop_id"] for stu in upcoming if stu["stop_id"]), None
        )
        delay = next(
            (d for d in map(_event_delay, upcoming) if d is not None), trip.get("delay")
        )
        if trip:
            headsign = trip["headsign"]
            direction_id = trip["direction_id"]
        else:
            direction = (
                index.direction(route_id, descriptor["direction_id"], [])
                if descriptor.get("direction_id") is not None
                else None
            )
            headsign = _direction_headsign(direction)
            direction_id = str(direction.get("id", "")) if direction else ""
        vehicles.append(
            {
                "id": vehicle_id,
                "routeId": route_id,
                "routeShortName": index.short_name(route_id),
                "routeName": index.route_name(route_id),
                "headsign": headsign,
                "loc": {
                    "lat": _round(lat, 5),
                    "lon": _round(lon, 5),
                    "time": timestamp,
                    "speed": _round(_float(location.get("speed")), 2),
                    "heading": _round(_float(location.get("bearing")), 1),
                },
                "schAdhSecs": delay,
                "schAdhStr": adherence_string(delay),
                "scheduledHeadwaySecs": None,
                "isAtStop": position.get("current_status") in _STOPPED_AT,
                "nextStopId": next_stop,
                "nextStopName": index.stop_name(next_stop),
                "directionId": direction_id,
                "tripId": trip_id,
                "blockId": block_id,
            }
        )
        if trip and not trip["vehicle_id"]:
            trip["vehicle_id"], trip["block_id"] = vehicle_id, block_id

    predictions: list[JSONPredictionData] = []
    for stop_id, stop_routes in stops.items():
        for route_id in stop_routes:
            upcoming = []
            for trip_id, trip in trips.items():
                if trip["route_id"] != route_id:
                    continue
                for stu in trip["stop_updates"]:
                    if stu["stop_id"] == stop_id:
                        time, departure = _event_time(stu)
                        if time and time >= now - 30:
                            upcoming.append((time, departure, trip_id, trip))
                            break
            upcoming.sort(key=lambda item: item[0])
            direction_id, headsign = index.stop_headsign(route_id, stop_id)
            if upcoming:
                direction_id = upcoming[0][3]["direction_id"] or direction_id
                headsign = upcoming[0][3]["headsign"] or headsign
            predictions.append(
                {
                    "routeShortName": index.short_name(route_id),
                    "routeName": index.route_name(route_id),
                    "routeId": route_id,
                    "stopId": stop_id,
                    "stopName": index.stop_name(stop_id),
                    "stopCode": index.stop_codes.get(stop_id),
                    "destinations": [
                        {
                            "directionId": direction_id,
                            "headsign": headsign,
                            "predictions": [
                                {
                                    "time": time,
                                    "sec": max(0, int(time - now)),
                                    "min": max(0, int(time - now)) // 60,
                                    "departure": departure,
                                    "blockId": trip["block_id"],
                                    "vehicleId": trip["vehicle_id"],
                                    "tripId": trip_id,
                                }
                                for time, departure, trip_id, trip in upcoming[:3]
                            ],
                        }
                    ],
                }
            )

    return vehicles, predictions


def summarize(feed: dict[str, Any], kind: str) -> str:
    """Return a short description of a feed for the debug log."""
    entities = feed.get("entity") or []
    route_ids = sorted(
        {
            str(((entity.get(kind) or {}).get("trip") or {}).get("route_id"))
            for entity in entities
            if entity.get(kind)
        }
    )
    return f"{len(entities)} entities, route ids: {', '.join(route_ids[:15])}"
