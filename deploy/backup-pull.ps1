# Забрать последний дамп PostgreSQL с сервера на машину разработчика (W5.2).
#
#   pwsh deploy/backup-pull.ps1                 # скачать и проверить gzip
#   pwsh deploy/backup-pull.ps1 -RestoreCheck   # ещё и восстановить в отдельную БД
#
# Дампы pgbackup называются в UTC (`bot_db-20261122-002956.sql.gz`), поэтому скрипт
# печатает время в UTC и в МСК. Восстановление идёт в отдельную БД
# `bot_db_restorecheck` локального postgres-контейнера — рабочая БД не трогается.
param(
    [string]$Server = '192.168.1.7',
    [string]$User   = 'george',
    [string]$Key    = "$env:USERPROFILE\.ssh\journal_server",
    [string]$LocalDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'backups'),
    [string]$PgContainer = 'tgbot-postgres',
    [string]$RestoreDatabase = 'bot_db_restorecheck',
    [switch]$RestoreCheck
)

$ErrorActionPreference = 'Stop'
$known = Join-Path $env:TEMP 'journal_known_hosts'
$sshOpts = @('-i', $Key, '-o', "UserKnownHostsFile=$known", '-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes')
$target = "$User@$Server"
$compose = 'cd /srv/journal_bot && sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml'

Write-Host "== поиск последнего дампа на $target"
$remotePath = (& ssh @sshOpts $target "$compose exec -T pgbackup sh -c 'ls /backups/last/bot_db-*.sql.gz | grep -v latest | sort | tail -1'").Trim()
if ($LASTEXITCODE -ne 0 -or -not $remotePath) { throw 'не удалось найти дамп на сервере' }
$fileName = Split-Path -Leaf $remotePath
Write-Host "   $remotePath"

New-Item -ItemType Directory -Force $LocalDir | Out-Null
$localPath = Join-Path $LocalDir $fileName

Write-Host '== копирование через /tmp сервера'
$remoteTmp = "/tmp/$fileName"
& ssh @sshOpts $target "sudo docker cp tgbot-pgbackup:$remotePath $remoteTmp && sudo chmod 644 $remoteTmp"
if ($LASTEXITCODE -ne 0) { throw 'docker cp завершился с ошибкой' }
try {
    & scp @sshOpts "${target}:$remoteTmp" $localPath
    if ($LASTEXITCODE -ne 0) { throw 'scp завершился с ошибкой' }
}
finally {
    & ssh @sshOpts $target "sudo rm -f $remoteTmp"
}

Write-Host "== проверка gzip: $localPath"
Add-Type -AssemblyName System.IO.Compression
$sqlPath = Join-Path $env:TEMP "$fileName.check.sql"
try {
    $archive = [System.IO.File]::OpenRead($localPath)
    try {
        $gzip = New-Object System.IO.Compression.GZipStream($archive, [System.IO.Compression.CompressionMode]::Decompress)
        try {
            $output = [System.IO.File]::Create($sqlPath)
            try { $gzip.CopyTo($output) } finally { $output.Dispose() }
        }
        finally { $gzip.Dispose() }
    }
    finally { $archive.Dispose() }
}
catch {
    Remove-Item $sqlPath -ErrorAction SilentlyContinue
    throw "gzip повреждён: $($_.Exception.Message)"
}
$sqlSize = (Get-Item $sqlPath).Length
Write-Host ("   gzip валиден, распаковано {0:N0} КБ" -f ($sqlSize / 1KB))

# Имя файла: bot_db-YYYYMMDD-HHMMSS.sql.gz, время в UTC (так пишет pgbackup).
if ($fileName -match '^bot_db-(\d{8})-(\d{6})') {
    $utc = [datetime]::SpecifyKind(
        [datetime]::ParseExact("$($Matches[1])$($Matches[2])", 'yyyyMMddHHmmss', $null),
        [System.DateTimeKind]::Utc
    )
    $msk = $utc.ToLocalTime()  # машина разработчика в Europe/Moscow
    Write-Host ("   дамп: {0} UTC = {1:yyyy-MM-dd HH:mm:ss} МСК" -f $utc.ToString('yyyy-MM-dd HH:mm:ss'), $msk)
    $age = (Get-Date).ToUniversalTime() - $utc
    Write-Host ("   возраст: {0:N0} мин" -f $age.TotalMinutes)
}

if (-not $RestoreCheck) {
    Remove-Item $sqlPath -ErrorAction SilentlyContinue
    Write-Host '== готово (восстановление не проверялось; добавьте -RestoreCheck)'
    exit 0
}

Write-Host "== восстановление в отдельную БД $RestoreDatabase ($PgContainer)"
& docker cp $sqlPath "${PgContainer}:/tmp/check.sql"
if ($LASTEXITCODE -ne 0) { throw 'docker cp в postgres завершился с ошибкой' }
$restore = @"
set -e
psql -U "`$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $RestoreDatabase;"
psql -U "`$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $RestoreDatabase;"
# pg_dump с --schema=public пишет `CREATE SCHEMA public`, поэтому в новой БД
# стандартную схему нужно убрать — иначе восстановление падает на «already exists».
psql -U "`$POSTGRES_USER" -d $RestoreDatabase -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS public CASCADE;"
psql -U "`$POSTGRES_USER" -d $RestoreDatabase -v ON_ERROR_STOP=1 -f /tmp/check.sql >/dev/null
psql -U "`$POSTGRES_USER" -d $RestoreDatabase -tAc "select count(*) from information_schema.tables where table_schema='public'"
psql -U "`$POSTGRES_USER" -d $RestoreDatabase -tAc "select count(*) from users"
"@
& docker exec $PgContainer sh -c $restore
if ($LASTEXITCODE -ne 0) {
    & docker exec $PgContainer rm -f /tmp/check.sql
    Remove-Item $sqlPath -ErrorAction SilentlyContinue
    throw 'восстановление не прошло'
}
& docker exec $PgContainer rm -f /tmp/check.sql
Remove-Item $sqlPath -ErrorAction SilentlyContinue
Write-Host '== восстановление проверено: таблицы и users прочитаны из отдельной БД'
