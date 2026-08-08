$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root '.env'
$python = Join-Path $root '.venv\Scripts\python.exe'

function Quote-Env([string]$value) {
    if ($null -eq $value) { return '""' }
    $escaped = $value.Replace('\\', '\\\\').Replace('"', '\"').Replace("`r", '').Replace("`n", '\n')
    return '"' + $escaped + '"'
}

Write-Host 'CampusPass IQ local configuration' -ForegroundColor Cyan
Write-Host 'Never send these secret values to anyone.' -ForegroundColor Yellow
Write-Host ''

$botToken = Read-Host 'Paste BOT_TOKEN'
if ([string]::IsNullOrWhiteSpace($botToken)) { throw 'BOT_TOKEN is required.' }

$adminIds = Read-Host 'Paste ADMIN_IDS (example: 123456789 or 123,456)'
if ([string]::IsNullOrWhiteSpace($adminIds)) { throw 'ADMIN_IDS is required.' }

Write-Host ''
Write-Host 'Paste an EXTERNAL PostgreSQL URL.' -ForegroundColor Yellow
Write-Host 'Do NOT use a URL containing .railway.internal.' -ForegroundColor Yellow
Write-Host 'For Supabase on a laptop, Session Pooler port 5432 is preferred.' -ForegroundColor Yellow
$dbUrl = Read-Host 'DATABASE_URL'
if ([string]::IsNullOrWhiteSpace($dbUrl)) { throw 'DATABASE_URL is required.' }
if ($dbUrl -match '\.railway\.internal') { throw 'A Railway internal database URL cannot be reached from your laptop. Use the public URL.' }

Write-Host ''
Write-Host 'To preserve old encrypted data, paste the SAME ENCRYPTION_KEY from Railway.' -ForegroundColor Yellow
Write-Host 'Leave blank only when the selected database is completely new and empty.' -ForegroundColor Yellow
$encryptionKey = Read-Host 'ENCRYPTION_KEY'
if ([string]::IsNullOrWhiteSpace($encryptionKey)) {
    $encryptionKey = & $python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    Write-Host 'A new ENCRYPTION_KEY was generated. Save a private backup of the .env file.' -ForegroundColor Yellow
}

if (Test-Path $envPath) {
    $backup = "$envPath.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $envPath $backup
    Write-Host "Previous .env backed up to: $backup" -ForegroundColor DarkGray
}

$lines = @(
    'BOT_TOKEN=' + (Quote-Env $botToken.Trim()),
    'ADMIN_IDS=' + (Quote-Env $adminIds.Trim()),
    'DATABASE_URL=' + (Quote-Env $dbUrl.Trim()),
    'ENCRYPTION_KEY=' + (Quote-Env $encryptionKey.Trim()),
    'ENVIRONMENT=production',
    'RUNTIME_MODE=combined',
    'TIMEZONE=Asia/Baghdad',
    'PORT=8080',
    'REQUIRE_EXTERNAL_DATABASE=true',
    'DB_SSL_MODE=require',
    'DB_POOL_SIZE=10',
    'DB_MAX_OVERFLOW=10',
    'DB_POOL_TIMEOUT_SECONDS=10',
    'DB_POOL_RECYCLE_SECONDS=900',
    'DB_CONNECT_TIMEOUT_SECONDS=10',
    'DB_STATEMENT_TIMEOUT_MS=15000',
    'DB_PREPARED_STATEMENT_CACHE_SIZE=0',
    'RATE_LIMIT_INTERVAL_MS=350',
    'PROCESSING_INDICATOR_DELAY_MS=50',
    'PROCESSING_MESSAGE_TEXT=' + (Quote-Env 'جاري المعالجة، يرجى الانتظار...'),
    'REQUIRE_REDIS_IN_PRODUCTION=false',
    'FEATURE_DISPUTES=false',
    'BACKUP_ENABLED=false',
    'AUTO_PRE_DEPLOY_BACKUP=false',
    'LOG_LEVEL=INFO',
    'RELEASE_ID=v10-laptop-speed'
)

[System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
Write-Host ''
Write-Host 'Saved .env successfully.' -ForegroundColor Green
Write-Host 'Optional Railway variables (Gemini, logos, support, etc.) can be added later.' -ForegroundColor DarkGray
