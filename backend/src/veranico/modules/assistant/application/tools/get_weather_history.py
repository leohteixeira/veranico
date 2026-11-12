"""`get_weather_history`: the daily rainfall dataset of a point, ingested on first use."""

from veranico.modules.assistant.application.tools.models import (
    GetWeatherHistoryInput,
    Tool,
    ToolSuccess,
)
from veranico.modules.climate.contracts import ClimateFacade
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.principal import Principal

DESCRIPTION = (
    "Load the daily rainfall history of a point (it is fetched and cached on first use). "
    "Returns the `dataset_id` the pricing tools need, the grid point, the years covered, the "
    "number of missing days and the `source`. When `source` is `synthetic` the series is "
    "generated demonstration data, not real weather history: say so whenever you present "
    "figures based on it. Name the source in words, never by its code: `era5-land/cds` is "
    "ERA5-Land reanalysis (ECMWF), `era5/open-meteo` is ERA5 reanalysis (ECMWF) served by "
    "Open-Meteo, and `synthetic` is synthetic demonstration data. The `dataset_id` is for the "
    "pricing tools only; do not write it."
)


def get_weather_history_tool(climate: ClimateFacade) -> Tool[GetWeatherHistoryInput]:
    async def handler(principal: Principal, arguments: GetWeatherHistoryInput) -> ToolSuccess:
        dataset = await climate.ensure_history(arguments.lat, arguments.lon)
        summary = Coded(
            code="tool.get_weather_history",
            params={
                "dataset_id": dataset.dataset_id,
                "first_year": dataset.first_year,
                "last_year": dataset.last_year,
                "source": dataset.source,
            },
        )
        return ToolSuccess(output=dataset, summary=summary)

    return Tool(
        name="get_weather_history",
        description=DESCRIPTION,
        input_model=GetWeatherHistoryInput,
        handler=handler,
    )
