# syntax=docker/dockerfile:1

# One image for both roles (SPEC 17): `APP_ROLE=api` is the product and serves the built
# frontend at the root of its own origin; `APP_ROLE=carrier` is the mock carrier. The image
# holds no role and no secret: both come from the environment of the service.
#
# Base images are pinned by digest. Each digest was resolved on 2026-11-11 with
# `docker buildx imagetools inspect <image>:<tag>`; to move a pin, resolve the new tag the
# same way and change tag comment and digest together.
#
#   node:24.19.0-bookworm-slim    the Node.js version of the development container
#   python:3.12-slim-bookworm     the Python line of backend/pyproject.toml
#   ghcr.io/astral-sh/uv:0.12.12  the uv version of the development container and uv.lock

# --- Frontend build ------------------------------------------------------------------------
FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS web

WORKDIR /web
# corepack installs the pnpm version named by `packageManager` in package.json.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=true
RUN corepack enable

# Dependencies first: this layer is reused until the manifest or the lock file changes.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# --- Backend dependencies ------------------------------------------------------------------
# The pattern of the uv documentation for images (docs.astral.sh/uv/guides/integration/docker):
# dependencies in their own layer from the lock file, then the project, installed
# non-editable so the next stage needs the virtual environment and nothing else.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS deps

COPY --from=ghcr.io/astral-sh/uv:0.12.12@sha256:73d2665b478d8fa2de1cf105c6841f8e9cb6b09e568fc7700440c09f8fcd7ac4 /uv /bin/uv

# No development dependencies (and not the `cube` group: the Earth Engine client belongs to the
# offline cube build and never reaches the running service). The interpreter is the
# image's, never a download.
ENV UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# --- Runtime -------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS runtime

# A fixed numeric user: the process never runs as root. The local data root (VERANICO_DATA_ROOT
# below) is made here and handed to that user: a volume mounted under it (compose.yaml mounts
# the weather store at /tmp/veranico/weather) would otherwise make Docker create the root as
# root, and the `local` blob store could not write documents/ or points beside it.
RUN groupadd --gid 10001 veranico \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin veranico \
    && mkdir -p /tmp/veranico/weather /tmp/veranico/blobs \
    && chown -R 10001:10001 /tmp/veranico

WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY --from=web /web/dist /app/frontend

# The release the image was built from; the deploy workflow passes the tag.
ARG VERSION=0.0.0

# Paths only. The local data root is used by the `local` blob and weather backends; the
# file system of the image is read-only for this user except /tmp, where the data root
# belongs to it.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VERANICO_FRONTEND_DIST=/app/frontend \
    VERANICO_DATA_ROOT=/tmp/veranico \
    VERANICO_CLIMATE__STORE_ROOT=/tmp/veranico/weather \
    VERANICO_TELEMETRY__SERVICE_VERSION=${VERSION}

USER 10001:10001

# Cloud Run sends requests to the container port of the service, which Terraform sets to
# this one; the server listens on every interface, as the container contract requires.
EXPOSE 8080

# Exec form: the server is process 1 and receives SIGTERM itself. Cloud Run and `docker
# stop` wait 10 seconds before SIGKILL, so open connections get 8 seconds to end; the
# application announces the shutdown to open streams as soon as the signal arrives.
# The access log prints the client address and stays off.
CMD ["uvicorn", "veranico.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--timeout-graceful-shutdown", "8"]
