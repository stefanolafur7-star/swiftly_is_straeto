"""Swiftly API Client."""

from aiohttp import ClientSession

from .gtfs_rt import GTFSRealtimeDecodeError
from .models import (
    JSONInfoData,
    JSONInfoResponse,
    JSONLocation,
    JSONPrediction,
    JSONPredictionData,
    JSONPredictionResponse,
    JSONPredictionResponseData,
    JSONRoute,
    JSONRouteData,
    JSONRouteResponse,
    JSONStop,
    JSONVehicle,
    JSONVehicleDetailData,
    JSONVehicleDetailResponse,
)

__all__ = [
    "GTFSRealtimeDecodeError",
    "InvalidRequestError",
    "JSONInfoData",
    "JSONInfoResponse",
    "JSONLocation",
    "JSONPrediction",
    "JSONPredictionData",
    "JSONPredictionResponse",
    "JSONPredictionResponseData",
    "JSONRoute",
    "JSONRouteData",
    "JSONRouteResponse",
    "JSONStop",
    "JSONVehicle",
    "JSONVehicleDetailData",
    "JSONVehicleDetailResponse",
    "RateLimitExceededError",
    "SwiftlyAPIClient",
    "UnauthorizedError",
    "UnexpectedAPIError",
]


class RateLimitExceededError(Exception):
    """Raised when Swiftly API rate limit is exceeded."""


class UnauthorizedError(Exception):
    """Raised when Swiftly API returns unauthorized error."""


class InvalidRequestError(Exception):
    """Raised when Swiftly API returns invalid request error."""


class UnexpectedAPIError(Exception):
    """Raised when Swiftly API returns an unexpected error."""


class SwiftlyAPIClient:
    """Client to interact with Swiftly API."""

    BASE_URL = "https://api.goswift.ly"
    AGENCY_KEY = "is-straeto"

    def __init__(self, api_key: str, session: ClientSession) -> None:
        """Initialize the Swiftly API Client."""
        self.api_key = api_key
        self.session = session
        self.headers = {"Authorization": api_key, "Accept": "application/json"}

    def _raise_for_status(self, status_code: int) -> None:
        """Raise appropriate exceptions based on status code."""
        if status_code in {401, 403}:
            raise UnauthorizedError("Unauthorized: Invalid API key.")
        if status_code == 429:
            raise RateLimitExceededError("Rate limit exceeded.")
        if status_code == 400:
            raise InvalidRequestError("Invalid request.")
        if status_code >= 500:
            raise UnexpectedAPIError("Unexpected server error.")

    def _validate_response(self, response: dict) -> None:
        """Validate the API response has success and data."""
        if not response.get("success", False):
            raise UnexpectedAPIError("API response indicates failure.")
        if "data" not in response:
            raise UnexpectedAPIError("API response missing data field.")

    async def get_agency_info(self) -> JSONInfoData:
        """Fetch agency information from Swiftly API."""
        url = f"{self.BASE_URL}/info/{self.AGENCY_KEY}"
        async with self.session.get(url, headers=self.headers) as response:
            self._raise_for_status(response.status)
            data = await response.json()
            self._validate_response(data)
            return JSONInfoResponse(**data).get("data")

    async def get_routes(
        self, route: list[str] | None = None, verbose=False
    ) -> JSONRouteData:
        """Fetch routes information from Swiftly API.

        :param route: List of route IDs to filter results.
        :param verbose: If True, fetch detailed route information.
        """
        url = f"{self.BASE_URL}/info/{self.AGENCY_KEY}/routes"
        params = {}
        if route:
            params["route"] = ",".join(route)
        if verbose:
            params["verbose"] = "true"
        async with self.session.get(
            url, headers=self.headers, params=params
        ) as response:
            self._raise_for_status(response.status)
            data = await response.json()
            self._validate_response(data)
            return JSONRouteResponse(**data).get("data")

    async def get_predictions(
        self, stop_id: str, route: list[str] | None = None, number=1
    ) -> JSONPredictionResponseData:
        """Fetch predictions for a given stop from Swiftly API.

        :param stop_id: The stop ID to fetch predictions for.
        :param route: Route ID to filter results. Skip to get all routes for stop.
        """
        url = f"{self.BASE_URL}/real-time/{self.AGENCY_KEY}/predictions"
        params = {"stop": stop_id, "number": number}
        if route:
            params["route"] = ",".join(route)
        async with self.session.get(
            url, headers=self.headers, params=params
        ) as response:
            self._raise_for_status(response.status)
            data = await response.json()
            self._validate_response(data)
            return JSONPredictionResponse(**data).get("data")

    async def get_vehicles(
        self, route: list[str] | None = None, verbose=False
    ) -> JSONVehicleDetailData:
        """Fetch vehicles information from Swiftly API.

        :param route: List of route IDs to filter results.
        :param verbose: If True, fetch detailed vehicle information.
        """
        url = f"{self.BASE_URL}/real-time/{self.AGENCY_KEY}/vehicles"
        params = {}
        if route:
            params["route"] = ",".join(route)
        if verbose:
            params["verbose"] = "true"
        async with self.session.get(
            url, headers=self.headers, params=params
        ) as response:
            self._raise_for_status(response.status)
            data = await response.json()
            self._validate_response(data)
            return JSONVehicleDetailResponse(**data).get("data")

    async def _get_gtfs_rt(self, feed: str) -> bytes:
        """Fetch a raw GTFS-rt protobuf feed from Swiftly API."""
        url = f"{self.BASE_URL}/real-time/{self.AGENCY_KEY}/{feed}"
        headers = {"Authorization": self.api_key, "Accept": "application/x-protobuf"}
        async with self.session.get(url, headers=headers) as response:
            self._raise_for_status(response.status)
            if response.status != 200:
                raise UnexpectedAPIError(f"Unexpected status {response.status}.")
            return await response.read()

    async def get_gtfs_rt_vehicle_positions(self) -> bytes:
        """Fetch the GTFS-rt vehicle positions feed."""
        return await self._get_gtfs_rt("gtfs-rt-vehicle-positions")

    async def get_gtfs_rt_trip_updates(self) -> bytes:
        """Fetch the GTFS-rt trip updates feed."""
        return await self._get_gtfs_rt("gtfs-rt-trip-updates")
