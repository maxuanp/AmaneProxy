# AmaneProxy keep-alive: start the manager if it is not running (ASCII only).
# Called by a scheduled task every 5 minutes; the manager is single-instance, so repeats are harmless.
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$pidFile = Join-Path $root "amaneproxy.pid"
$port = 18111
$cfg = Join-Path $root "amaneproxy.json"
if (Test-Path $cfg) {
  try { $port = (Get-Content $cfg -Raw | ConvertFrom-Json).panel_port } catch { }
}
$alive = $false
if (Test-Path $pidFile) {
  $raw = (Get-Content $pidFile -Raw).Trim()
  if ($raw -match '^\d+$') {
    if (Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue) { $alive = $true }
  }
}
if (-not $alive) {
  Start-Process -FilePath "wscript.exe" -ArgumentList (Join-Path $root "start.vbs") -WindowStyle Hidden
  Start-Sleep -Seconds 6
  $ok = $false
  try { $null = Invoke-RestMethod "http://127.0.0.1:$port/api/state" -TimeoutSec 20; $ok = $true } catch { }
  $msg = "{0}  keepalive: manager was not running, started now (panel ok={1})" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $ok
  Add-Content -Path (Join-Path $root "logs\keepalive.log") -Value $msg -Encoding UTF8
}
