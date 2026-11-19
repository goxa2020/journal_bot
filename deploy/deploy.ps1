# Выкатка journal_bot на сервер одной командой: pwsh deploy/deploy.ps1 [-NoBuild]
#
# На сервер уезжает только то, что там нужно для работы: код, миграции, конфиги и один
# вспомогательный скрипт. Документация, тесты, гайд по установке Debian и инструменты
# разработчика остаются в репозитории и на машине разработчика.
# .env на сервере свой и никогда не перезаписывается.
param(
    [string]$Server = '192.168.1.7',
    [string]$User   = 'george',
    [string]$Key    = "$env:USERPROFILE\.ssh\journal_server",
    [string]$Remote = '/srv/journal_bot',
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$known = Join-Path $env:TEMP 'journal_known_hosts'
$sshOpts = @('-i', $Key, '-o', "UserKnownHostsFile=$known", '-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes')
$target = "$User@$Server"

# Явный список: добавили каталог в проект — добавьте сюда, если он нужен на сервере.
$paths = @(
    'bot'
    'admin'
    'migrations'
    'configs'
    'alembic.ini'
    'pyproject.toml'
    'uv.lock'
    'Dockerfile'
    '.dockerignore'
    'docker-compose.yml'
    'docker-compose.prod.yml'
    'deploy/xray-refresh.sh'
)
$exclude = @('__pycache__', '*.pyc')

Write-Host "== упаковка: $($paths -join ', ')"
$archive = Join-Path $env:TEMP 'journal_bot_deploy.tgz'
$tarArgs = @('-czf', $archive) + ($exclude | ForEach-Object { "--exclude=$_" }) + @('-C', $root) + $paths
& tar @tarArgs
if ($LASTEXITCODE -ne 0) { throw "tar завершился с кодом $LASTEXITCODE" }

Write-Host ("   {0:N0} КБ" -f ((Get-Item $archive).Length / 1KB))

Write-Host "== передача на $target"
& scp @sshOpts $archive "${target}:/tmp/journal_bot_deploy.tgz"
if ($LASTEXITCODE -ne 0) { throw "scp завершился с кодом $LASTEXITCODE" }

Write-Host "== распаковка и перезапуск"
$compose = 'docker compose -f docker-compose.yml -f docker-compose.prod.yml'
$steps = "sudo -n mkdir -p $Remote && sudo -n tar -xzf /tmp/journal_bot_deploy.tgz -C $Remote && sudo -n chown -R ${User}:${User} $Remote && cd $Remote && "
$steps += if ($NoBuild) {
    "$compose up -d && $compose ps"
} else {
    "$compose build && $compose up -d && $compose ps"
}
& ssh @sshOpts $target $steps
if ($LASTEXITCODE -ne 0) { throw "деплой завершился с кодом $LASTEXITCODE" }

Write-Host "== готово"
