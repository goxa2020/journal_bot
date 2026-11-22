# Выкатка journal_bot на сервер одной командой (W5.1).
#
#   pwsh deploy/deploy.ps1                  # сборка на сервере (как раньше)
#   pwsh deploy/deploy.ps1 -NoBuild         # код + перезапуск без сборки
#   pwsh deploy/deploy.ps1 -ImageFile bot-image.tar.gz   # доставить готовый образ
#   pwsh deploy/deploy.ps1 -DeliverImage    # собрать локально, save|gzip и доставить
#
# Зачем режим образа: серверный BuildKit не всегда резолвит ghcr.io (`no such host`),
# а демон резолвит. `-ImageFile`/`-DeliverImage` не дают серверу ходить в сеть за базой:
# образ собирается на машине разработчика, `docker load` кладёт его в стор сервера, а
# `up -d --no-build` только перезапускает контейнеры.
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
    [switch]$NoBuild,
    [string]$ImageFile = '',
    [switch]$DeliverImage
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$known = Join-Path $env:TEMP 'journal_known_hosts'
$sshOpts = @('-i', $Key, '-o', "UserKnownHostsFile=$known", '-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes')
$target = "$User@$Server"
$compose = 'docker compose -f docker-compose.yml -f docker-compose.prod.yml'

if ($NoBuild -and ($ImageFile -or $DeliverImage)) {
    throw 'Выберите один режим: -NoBuild (код без сборки) или -ImageFile/-DeliverImage (доставка образа)'
}

# --- 1. Готовый образ (если выбран режим доставки) --------------------------------
$tempImage = $null
if ($DeliverImage -and -not $ImageFile) {
    Write-Host '== локальная сборка образа bot:latest'
    & docker build -t bot:latest $root
    if ($LASTEXITCODE -ne 0) { throw "локальная сборка завершилась с кодом $LASTEXITCODE" }
    $tempImage = Join-Path $env:TEMP 'journal_bot_image.tar.gz'
    $tarFile = Join-Path $env:TEMP 'journal_bot_image.tar'
    Write-Host '== docker save + gzip'
    & docker save -o $tarFile bot:latest
    if ($LASTEXITCODE -ne 0) { throw "docker save завершился с кодом $LASTEXITCODE" }
    # Сжатие средствами .NET: gzip.exe нет в PATH на чистой Windows.
    Add-Type -AssemblyName System.IO.Compression
    $raw = [System.IO.File]::OpenRead($tarFile)
    try {
        $packed = [System.IO.File]::Create($tempImage)
        try {
            $gzip = New-Object System.IO.Compression.GZipStream($packed, [System.IO.Compression.CompressionMode]::Compress)
            try { $raw.CopyTo($gzip) } finally { $gzip.Dispose() }
        }
        finally { $packed.Dispose() }
    }
    finally { $raw.Dispose() }
    Remove-Item $tarFile -ErrorAction SilentlyContinue
    $ImageFile = $tempImage
}
if ($ImageFile) {
    if (-not (Test-Path $ImageFile)) { throw "Файл образа не найден: $ImageFile" }
    Write-Host ("== доставка образа {0} ({1:N0} МБ)" -f $ImageFile, ((Get-Item $ImageFile).Length / 1MB))
}

# --- 2. Код и конфиги -------------------------------------------------------------
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
if ($ImageFile) {
    & scp @sshOpts $ImageFile "${target}:/tmp/journal_bot_image.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw "scp образа завершился с кодом $LASTEXITCODE" }
}

# --- 3. Распаковка, загрузка образа и перезапуск ----------------------------------
Write-Host '== распаковка и перезапуск'
$steps = "sudo -n mkdir -p $Remote && sudo -n tar -xzf /tmp/journal_bot_deploy.tgz -C $Remote && sudo -n chown -R ${User}:${User} $Remote && cd $Remote && "
if ($ImageFile) {
    $steps += 'sudo -n docker load -i /tmp/journal_bot_image.tar.gz && '
}
$steps += if ($ImageFile -or $NoBuild) {
    "$compose up -d --no-build && $compose ps"
} else {
    "$compose build && $compose up -d && $compose ps"
}
& ssh @sshOpts $target $steps
if ($LASTEXITCODE -ne 0) { throw "деплой завершился с кодом $LASTEXITCODE" }

if ($ImageFile -and $tempImage) {
    Remove-Item $tempImage -ErrorAction SilentlyContinue
}

Write-Host '== готово'
