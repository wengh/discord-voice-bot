# Install uv
FROM python:3.11-alpine

# Install opus
RUN apk update && apk add --no-cache \
    opus-dev \
    && rm -rf /var/cache/apk/*

# Used in main.py
ENV LIBOPUS_PATH=/usr/lib/libopus.so

# Change the working directory to the `app` directory
WORKDIR /app

# Install dependencies
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

# Copy the project into the image
ADD . /app

# Sync the project
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

CMD [".venv/bin/python", "main.py"]
