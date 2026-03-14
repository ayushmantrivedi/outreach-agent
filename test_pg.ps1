$env:PGPASSWORD = 'ayushman1301'
$schema = Join-Path $PSScriptRoot "ai_outreach_agent\database\schema.sql"
$result = & psql -U postgres -h 127.0.0.1 -d outreach_db -f $schema 2>&1
Write-Host $result
