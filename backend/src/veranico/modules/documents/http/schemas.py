"""Response classes of the `documents` routes: they name the media type in OpenAPI."""

from fastapi import Response


class PdfResponse(Response):
    media_type = "application/pdf"


class NetCdfResponse(Response):
    media_type = "application/x-netcdf"
