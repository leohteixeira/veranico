"""The default label of a quote's location."""


def format_coordinates(lat: float, lon: float) -> str:
    """Latitude then longitude in decimal degrees, four places: `-12.5500, -55.7200`."""
    return f"{lat:.4f}, {lon:.4f}"
