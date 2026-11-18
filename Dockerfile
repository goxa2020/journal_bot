FROM ghcr.io/astral-sh/uv:0.5-python3.13-alpine

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/usr/src/app/.venv/bin:$PATH"

WORKDIR /usr/src/app

# 1. Зависимости отдельным слоем: переиспользуется, пока не менялись
#    pyproject.toml и uv.lock. Правка любого .py не сбрасывает установку.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --group bot --no-group admin --no-group dev

# 2. Пользователь и каталог логов создаются до копирования кода, чтобы
#    не делать дорогой `chown -R` по .venv на каждой сборке.
RUN adduser -D appuser \
    && mkdir -p /usr/src/app/logs \
    && chown -R appuser:appuser /usr/src/app/logs

# 3. Код и локали: меняются часто, поэтому копируются после зависимостей.
COPY --chown=appuser:appuser . .
RUN pybabel compile -d ./bot/locales

USER appuser

CMD ["python", "-m", "bot"]
