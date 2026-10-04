# Stop the Amane proxy dispatcher (manager + sing-box). ASCII only.
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$py = "__PYTHON__"
if (-not (Test-Path $py -ErrorAction SilentlyContinue)) {
  $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source }
}
if (-not $py -or -not (Test-Path $py -ErrorAction SilentlyContinue)) {
  Write-Host "python.exe not found. Run manually: python `"$root\amaneproxy.py`" --stop" -ForegroundColor Yellow
  exit 1
}
& $py (Join-Path $root "amaneproxy.py") --stop
Write-Host "Stop requested. If Amane still points at this dispatcher, restore the previous value in the panel first." -ForegroundColor Yellow
