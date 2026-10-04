# Show Amane proxy dispatcher status (ASCII only)
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$port = 18111
$cfg = Join-Path $root "amaneproxy.json"
if (Test-Path $cfg) {
  try { $port = (Get-Content $cfg -Raw | ConvertFrom-Json).panel_port } catch { }
}
try {
  $s = Invoke-RestMethod "http://127.0.0.1:$port/api/state" -TimeoutSec 20
  Write-Host ("running      : {0}   {1}" -f $s.running, $s.singbox_version)
  Write-Host ("entry / panel: 127.0.0.1:{0}  /  http://127.0.0.1:{1}" -f $s.ports.entry, $s.ports.panel)
  Write-Host ("default out  : {0}" -f $s.settings.default_outbound)
  Write-Host ("selectors    : {0}" -f ($s.selectors | ConvertTo-Json -Compress))
  foreach ($p in $s.probe.PSObject.Properties) {
    $v = $p.Value
    Write-Host ("  {0,-4} ok={1,-6} {2,-16} {3} / {4}  {5}ms" -f $p.Name, $v.ok, $v.ip, $v.country, $v.city, $v.ms)
  }
  Write-Host ("Amane proxy  : {0}" -f $s.amane.proxy)
} catch {
  Write-Host "dispatcher not running (panel http://127.0.0.1:$port unreachable)" -ForegroundColor Yellow
  Write-Host ("start it: wscript `"{0}`"   or   powershell -File `"{1}`"" -f (Join-Path $root "start.vbs"), (Join-Path $root "ensure.ps1"))
}
