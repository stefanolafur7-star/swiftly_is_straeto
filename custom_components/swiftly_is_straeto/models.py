"""Models for Swiftly IS Straeto integration."""

from datetime import UTC, datetime
from typing import TypedDict

from homeassistant.helpers.typing import StateType

from .api import (
    JSONLocation,
    JSONPrediction,
    JSONPredictionData,
    JSONRoute,
    JSONStop,
    JSONVehicle,
)


class VehicleExtraStateAttributes(TypedDict):
    """Extra state attributes for a Swiftly IS Straeto vehicle."""

    vehicle_id: str
    schedule_adherence_string: int
    headsign: str
    interval_seconds: int


class PredictionExtraStateAttributes(TypedDict, total=False):
    """Extra state attributes for a Swiftly IS Straeto prediction."""

    route: str
    stop_name: str
    headsign: str
    vehicle_id: str
    block_id: int
    trip_id: str


class Vehicle:
    """Class for a vehicle on a specific route direction within a specific route."""

    def __init__(
        self,
        vehicle_data: JSONVehicle,
        route_subentry_mapping: dict[str, str],
    ) -> None:
        """Initialize Vehicle."""
        self._vehicle_data = vehicle_data
        self._subentry_id = route_subentry_mapping.get(vehicle_data["routeId"])

    @property
    def route_id(self) -> str:
        """Return the route ID for this vehicle."""
        return self._vehicle_data["routeId"]

    @property
    def route_name(self) -> str:
        """Return the route Name for this vehicle."""
        return self._vehicle_data["routeName"]

    @property
    def next_stop_name(self) -> str:
        """Return the next stop name for this vehicle."""
        return self._vehicle_data["nextStopName"]

    @property
    def schedule_adherence(self) -> int:
        """Return the schedule adherence in seconds for this vehicle."""
        return self._vehicle_data["schAdhSecs"]

    @property
    def headsign(self) -> str:
        """Return the headsign for this vehicle."""
        return self._vehicle_data["headsign"]

    @property
    def block_id(self) -> str:
        """Return the block ID for this vehicle."""
        return self._vehicle_data["blockId"]

    @property
    def extra_state_attributes(self) -> VehicleExtraStateAttributes:
        """Return the extra state attributes for this vehicle."""
        return {
            "vehicle_id": self._vehicle_data["id"],
            "schedule_adherence_string": self._vehicle_data["schAdhStr"],
            "headsign": self._vehicle_data["headsign"],
            "interval_seconds": self._vehicle_data["scheduledHeadwaySecs"],
        }

    @property
    def location(self) -> JSONLocation | None:
        """Return the current location of the vehicle."""
        return self._vehicle_data.get("loc", None)

    @property
    def subentry_id(self) -> str:
        """Return the subentry ID for this vehicle."""
        return self._subentry_id

    def get_unique_id(self, key: str) -> str:
        """Return a unique ID for a vehicle entity."""
        return f"{self._subentry_id}_{self._vehicle_data['blockId'].replace('-', '')}_{key}"


class Prediction:
    """Class for a prediction for a specific stop on a specific route direction within a specific route."""

    def __init__(
        self,
        prediction_data: JSONPredictionData,
        route_subentry_mapping: dict[str, str],
    ) -> None:
        """Initialize Prediction."""
        self._prediction_data = prediction_data
        self._subentry_id = route_subentry_mapping.get(prediction_data["routeId"])

    @property
    def route_id(self) -> str:
        """Return the route ID for this prediction."""
        return self._prediction_data["routeId"]

    @property
    def route_name(self) -> str:
        """Return the route Name for this prediction."""
        return self._prediction_data["routeName"]

    @property
    def stop_name(self) -> str:
        """Return the stop name for this prediction."""
        return self._prediction_data["stopName"]

    @property
    def stop_id(self) -> str:
        """Return the stop ID for this prediction."""
        return self._prediction_data["stopId"]

    @property
    def headsign(self) -> str:
        """Return the destination for this prediction."""
        try:
            return self._prediction_data["destinations"][0]["headsign"]
        except (IndexError, KeyError):
            return ""

    @property
    def prediction(self) -> JSONPrediction:
        """Return the first prediction."""
        try:
            return self._prediction_data["destinations"][0]["predictions"][0]
        except (IndexError, KeyError):
            return {}

    @property
    def arrival_time(self) -> datetime | StateType:
        """Return the predicted arrival time in epoch milliseconds for this prediction."""
        return (
            datetime.fromtimestamp(self.prediction["time"], tz=UTC)
            if self.prediction
            else None
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID for a prediction entity."""
        return (
            f"{self._subentry_id}_{self.route_id}_{self.stop_id}_predicted_arrival_time"
        )

    @property
    def extra_state_attributes(self) -> PredictionExtraStateAttributes | None:
        """Return the extra state attributes for this prediction.

        Route, stop and headsign are always there, so dashboards can show the
        stop even while no bus is on its way.
        """
        attributes: PredictionExtraStateAttributes = {
            "route": self._prediction_data.get("routeShortName") or self.route_id,
            "stop_name": self.stop_name,
            "headsign": self.headsign,
        }
        if self.prediction:
            attributes["vehicle_id"] = self.prediction["vehicleId"]
            attributes["block_id"] = self.prediction["blockId"]
            attributes["trip_id"] = self.prediction["tripId"]
        return attributes

    @property
    def subentry_id(self) -> str:
        """Return the subentry ID for this prediction."""
        return self._subentry_id


class StraetoSubentryData(TypedDict, total=False):
    """Holds the data for Swiftly IS Straeto subentry."""

    route: str
    route_name: str
    stops: list[str]


class CoordinatorData(TypedDict):
    """Data model for Swiftly IS Straeto coordinator data."""

    vehicles: list[Vehicle]
    predictions: list[Prediction]


class ConfigFlowData(TypedDict):
    """Data model for Swiftly IS Straeto config flow data."""

    title: str
    id: str
    url: str
    api_key: str
    routes: list[JSONRoute]


class Route(JSONRoute):
    """Data model for a route with additional fields for Swiftly IS Straeto."""


class ErrorResponse(TypedDict):
    """Data model for a Swiftly error response."""

    errorCode: int
    errorMessage: str


class RouteStop:
    """Class for a stop on a specific route direction within a specific route."""

    def __init__(
        self,
        route_id: str,
        direction_id: str,
        direction_title: str,
        stop: JSONStop,
    ) -> None:
        """Initialize RouteStop."""
        self.route_id = route_id
        self.direction_id = direction_id
        self.direction_title = direction_title
        self.stop_id = stop["id"]
        self.stop_name = stop["name"]
        self.stop_code = stop["code"]

    def __str__(self) -> str:
        """Return string representation of RouteStop."""
        return f"{self.route_id} - {self.stop_name} ({self.direction_title})"
