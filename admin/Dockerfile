FROM ghcr.io/astral-sh/uv:0.5-python3.13-alpine

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/usr/src/app/.venv/bin:$PATH"

WORKDIR /usr/src/app

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --group admin --no-group bot --no-group dev \
    && adduser -u 10001 -D appuser \
    && chown -R 10001:10001 .

USER 10001

CMD ["gunicorn", "-c", "admin/gunicorn_conf.py"]
