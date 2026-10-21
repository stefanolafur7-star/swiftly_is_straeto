"""DataUpdateCoordinator for Swiftly integration."""

import asyncio
import time
from datetime import timedelta

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import _LOGGER, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GTFSRealtimeDecodeError,
    InvalidRequestError,
    JSONPredictionData,
    JSONRoute,
    JSONVehicle,
    RateLimitExceededError,
    SwiftlyAPIClient,
    UnauthorizedError,
    UnexpectedAPIError,
)
from .api.gtfs_rt import build_realtime, parse_feed, summarize
from .const import (
    CONF_ROUTE,
    CONF_ROUTE_NAME,
    CONF_ROUTES,
    DEFAULT_UPDATE_TIME,
    JSON_PREDICTIONS_DATA,
    JSON_VEHICLES,
)
from .models import CoordinatorData, Prediction, Vehicle
from .utils import get_subentry_data

# Stops and directions change rarely, so route info is only refreshed this often.
ROUTE_INFO_REFRESH_SECONDS = 6 * 60 * 60
ROUTE_INFO_RETRY_SECONDS = 5 * 60

type SwiftlyIsStraetoConfigEntry = ConfigEntry[SwiftlyIsStraetoDataUpdateCoordinator]


class SwiftlyIsStraetoDataUpdateCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Class to manage fetching Swiftly IS Straeto data from API."""

    config_entry: SwiftlyIsStraetoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: SwiftlyIsStraetoConfigEntry,
        api_client: SwiftlyAPIClient,
    ) -> None:
        """Initialize Swiftly IS Straeto data updater."""
        self.api_client = api_client
        self.config_entry = config_entry
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Swiftly IS Straeto Data Coordinator",
            update_interval=timedelta(seconds=DEFAULT_UPDATE_TIME),
        )
        # Set when the API key only has access to the GTFS-rt feeds
        self._use_gtfs_rt = False
        self._gtfs_rt_logged = False
        self._route_info: list[JSONRoute] = []
        self._route_info_ids: list[str] = []
        self._route_info_next = 0.0

    async def _get_stop_predictions(
        self, stops: dict[str, list[str]], route_subentry_mapping: dict[str, str]
    ) -> list[Prediction]:
        """Fetch predictions for monitored stops."""
        predictions: list[Prediction] = []
        for stop, routes in stops.items():
            prediction = await self.api_client.get_predictions(stop, routes)
            prediction_data = prediction.get(JSON_PREDICTIONS_DATA, [])
            for item in prediction_data:
                predictions.extend([Prediction(item, route_subentry_mapping)])
        return predictions

    async def _get_json_data(
        self,
        routes: list[str],
        stops: dict[str, list[str]],
        route_subentry_mapping: dict[str, str],
    ) -> CoordinatorData:
        """Fetch data from the JSON real-time endpoints."""
        vehicles = await self.api_client.get_vehicles(route=routes, verbose=True)
        predictions = (
            await self._get_stop_predictions(stops, route_subentry_mapping)
            if stops
            else []
        )

        return CoordinatorData(
            vehicles=[
                Vehicle(vehicle, route_subentry_mapping)
                for vehicle in vehicles.get(JSON_VEHICLES, [])
            ],
            predictions=predictions,
        )

    async def _get_route_info(self, routes: list[str]) -> list[JSONRoute]:
        """Return directions and stops for the monitored routes."""
        if routes == self._route_info_ids and time.monotonic() < self._route_info_next:
            return self._route_info
        try:
            data = await self.api_client.get_routes(routes, verbose=True)
        except (
            ClientError,
            TimeoutError,
            RateLimitExceededError,
            InvalidRequestError,
            UnexpectedAPIError,
        ) as err:
            # Route info only adds names and headsigns, so carry on without it
            _LOGGER.warning("Could not fetch Strætó route info: %s", err)
            if routes != self._route_info_ids:
                self._route_info, self._route_info_ids = [], list(routes)
            self._route_info_next = time.monotonic() + ROUTE_INFO_RETRY_SECONDS
            return self._route_info
        self._route_info = data.get(CONF_ROUTES, [])
        self._route_info_ids = list(routes)
        self._route_info_next = time.monotonic() + ROUTE_INFO_REFRESH_SECONDS
        return self._route_info

    async def _get_gtfs_rt_data(
        self,
        routes: list[str],
        stops: dict[str, list[str]],
        route_subentry_mapping: dict[str, str],
    ) -> CoordinatorData:
        """Fetch data from the GTFS-rt vehicle positions and trip updates feeds."""
        vehicle_feed, trip_feed = await asyncio.gather(
            self.api_client.get_gtfs_rt_vehicle_positions(),
            self.api_client.get_gtfs_rt_trip_updates(),
        )
        route_info = await self._get_route_info(routes)
        route_names = {
            subentry.data.get(CONF_ROUTE): subentry.data.get(CONF_ROUTE_NAME)
            for subentry in self.config_entry.subentries.values()
        }
        vehicles, predictions, summary = await self.hass.async_add_executor_job(
            _build_gtfs_rt_data,
            vehicle_feed,
            trip_feed,
            routes,
            stops,
            route_info,
            route_names,
            time.time(),
        )
        if not self._gtfs_rt_logged:
            self._gtfs_rt_logged = True
            # Without buses this is normal at night, otherwise the feed's route
            # ids do not match the routes set up here, so make it visible.
            (_LOGGER.info if vehicles else _LOGGER.warning)(
                "GTFS-rt: %s. Found %d buses and %d stops on routes %s",
                summary,
                len(vehicles),
                len(predictions),
                ", ".join(routes),
            )
        else:
            _LOGGER.debug("GTFS-rt: %s", summary)

        return CoordinatorData(
            vehicles=[Vehicle(vehicle, route_subentry_mapping) for vehicle in vehicles],
            predictions=[
                Prediction(item, route_subentry_mapping) for item in predictions
            ],
        )

    async def _async_update_data(self) -> CoordinatorData:
        """Fetch vehicle and prediction data for monitored routes and stops every DEFAULT_UPDATE_TIME seconds."""
        routes, stops, route_subentry_mapping = get_subentry_data(self.config_entry)
        if not routes:
            return CoordinatorData(vehicles=[], predictions=[])

        try:
            if not self._use_gtfs_rt:
                try:
                    return await self._get_json_data(
                        routes, stops, route_subentry_mapping
                    )
                except UnauthorizedError:
                    _LOGGER.info(
                        "API key has no access to the JSON real-time endpoints, "
                        "using the GTFS-rt feeds instead"
                    )
                    self._use_gtfs_rt = True
            return await self._get_gtfs_rt_data(routes, stops, route_subentry_mapping)
        except UnauthorizedError as err:
            raise UpdateFailed(
                f"{err} The key needs access to the GTFS-rt trip updates and "
                "vehicle positions endpoints."
            ) from err
        except (
            RateLimitExceededError,
            InvalidRequestError,
            UnexpectedAPIError,
            GTFSRealtimeDecodeError,
        ) as err:
            raise UpdateFailed(str(err)) from err


def _build_gtfs_rt_data(
    vehicle_raw: bytes,
    trip_raw: bytes,
    routes: list[str],
    stops: dict[str, list[str]],
    route_info: list[JSONRoute],
    route_names: dict[str, str],
    now: float,
) -> tuple[list[JSONVehicle], list[JSONPredictionData], str]:
    """Decode the GTFS-rt feeds and map them to vehicles and predictions."""
    feeds = []
    for name, raw in (("vehicle positions", vehicle_raw), ("trip updates", trip_raw)):
        try:
            feeds.append(parse_feed(raw))
        except GTFSRealtimeDecodeError as err:
            raise GTFSRealtimeDecodeError(
                f"Could not read the GTFS-rt {name} feed: {err} "
                f"(starts with {raw[:40]!r})"
            ) from err
    vehicle_feed, trip_feed = feeds
    vehicles, predictions = build_realtime(
        vehicle_feed, trip_feed, routes, stops, route_info, route_names, now
    )
    summary = (
        f"vehicle positions {summarize(vehicle_feed, 'vehicle')}; "
        f"trip updates {summarize(trip_feed, 'trip_update')}"
    )
    return vehicles, predictions, summary
