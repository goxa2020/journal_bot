set shell := ["powershell", "-c"]
set dotenv-load
set export

# Variables
LOCALES := "bot/locales"

# Display this help screen
help:
    @just --list

# Install dependencies
deps:
    @uv sync --frozen

# Run docker compose
compose-up:
    docker compose up --build -d

# Down docker compose
compose-down:
    docker compose down

# docker compose stop
compose-stop:
    docker compose stop

# docker compose kill
compose-kill:
    docker compose kill

# docker compose build
compose-build:
    docker compose build

# docker compose ps
compose-ps:
    docker compose ps

# Exec command in app container (usage: just compose-exec <cmd>)
compose-exec +args:
    docker compose exec app {{args}}

# View logs (usage: just logs <args>)
logs +args='':
    docker compose logs {{args}} -f

# --- MIGRATIONS ---

# Create new migrations (usage: just mm "message")
mm message:
    docker compose exec bot alembic revision --autogenerate -m "{{message}}"

# Upgrade migrations in docker compose
migrate:
    docker compose exec bot alembic upgrade head

# Downgrade to specific migration (usage: just downgrade <revision>)
downgrade revision:
    docker compose exec bot alembic downgrade {{revision}}

# --- STYLE ---

# Run linters to check code
check:
    @uv run ruff check .
    @uv run ruff format --check .

# Run linters to fix code
format:
    @uv run ruff check --fix .
    @uv run ruff format .

# Delete all temporary and generated files
clean:
    # Remove specific directories and files if they exist
    Get-ChildItem -Path .pytest_cache,.ruff_cache,.hypothesis,build,dist,.eggs,.coverage,coverage.xml,coverage.json,htmlcov,.mypy_cache -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    # Recursively remove patterns
    Get-ChildItem -Path . -Include *.egg-info,*.egg,*.pyc,*.pyo,*~,__pycache__,.pytest_cache,.ipynb_checkpoints -Recurse -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

# --- BACKUPS ---

# Create backup
backup:
    docker compose exec bot scripts/postgres/backup

# Mount docker backup (usage: just mount-docker-backup <filename>)
mount-docker-backup filename:
    docker cp app_db:/backups/{{filename}} ./{{filename}}

# Restore from backup (usage: just restore <filename>)
restore filename:
    docker compose exec app_db scripts/postgres/restore {{filename}}

# --- I18N ---

# Extracts translatable strings from the source code into a .pot file
babel-extract:
    @uv run pybabel extract --input-dirs=. -o {{LOCALES}}/messages.pot -k n_ -k _

# Updates .pot files by merging changed strings into the existing .pot files
babel-update:
    @uv run pybabel update -d {{LOCALES}} -i {{LOCALES}}/messages.pot

# Compiles translation .po files into binary .mo files
babel-compile:
    @uv run pybabel compile -d {{LOCALES}}

# Run extract and update
babel: babel-extract babel-update
