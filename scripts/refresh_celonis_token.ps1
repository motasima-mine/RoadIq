# ─────────────────────────────────────────────────────────────────────────────
# Celonis MCP Token Refresh Script
# ─────────────────────────────────────────────────────────────────────────────
# Run this to get a fresh OAuth token and update ~/.kiro/settings/mcp.json
# Token expires every 15 minutes (899 seconds)
#
# Reads credentials from .env in the project root — never hardcode secrets here.
#
# Usage:  .\scripts\refresh_celonis_token.ps1
# ─────────────────────────────────────────────────────────────────────────────

# Load .env from project root (one level up from scripts/)
$envPath = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envPath)) {
    Write-Host "ERROR: .env file not found at $envPath" -ForegroundColor Red
    Write-Host "Copy .env.example to .env and fill in your credentials first." -ForegroundColor Yellow
    exit 1
}

$envVars = @{}
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$') {
        $envVars[$matches[1]] = $matches[2]
    }
}

$ClientId = $envVars["CELONIS_CLIENT_ID"]
$ClientSecret = $envVars["CELONIS_CLIENT_SECRET"]
$TokenUrl = $envVars["CELONIS_TOKEN_URL"]
$McpServerUrl = "https://ai-context-model-pilot-pov.us-2.celonis.cloud/studio-copilot/api/v1/mcp-servers/mcp/64c73b17-5383-4263-a6aa-58de560edf6d"
$McpConfigPath = "$env:USERPROFILE\.kiro\settings\mcp.json"

if (-not $ClientId -or -not $ClientSecret -or -not $TokenUrl) {
    Write-Host "ERROR: Missing CELONIS_CLIENT_ID, CELONIS_CLIENT_SECRET, or CELONIS_TOKEN_URL in .env" -ForegroundColor Red
    exit 1
}

Write-Host "Requesting new Celonis OAuth token..." -ForegroundColor Cyan

try {
    $body = "grant_type=client_credentials&client_id=$ClientId&client_secret=$ClientSecret&scope=mcp-asset.tools:execute"
    $response = Invoke-RestMethod -Method Post -Uri $TokenUrl -Body $body -ContentType "application/x-www-form-urlencoded"
    $token = $response.access_token
    $expiresIn = $response.expires_in

    Write-Host "Token obtained. Expires in $expiresIn seconds." -ForegroundColor Green

    # Build new mcp.json
    $config = @{
        mcpServers = @{
            celonis = @{
                url = $McpServerUrl
                headers = @{
                    Authorization = "Bearer $token"
                }
            }
        }
    }

    $json = $config | ConvertTo-Json -Depth 4
    Set-Content -Path $McpConfigPath -Value $json -Encoding UTF8

    Write-Host "Updated $McpConfigPath" -ForegroundColor Green
    Write-Host "Kiro will auto-reconnect to Celonis MCP." -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Token preview: $($token.Substring(0, 50))..." -ForegroundColor DarkGray

} catch {
    Write-Host "ERROR: Token request failed." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
