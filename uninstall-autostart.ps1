# Remove logon autostart + keep-alive task (ASCII only)
param([string]$TaskName = "AmaneProxyKeepAlive")
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "AmaneProxy.lnk"
if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "removed startup shortcut" }
schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
Write-Host "tried to delete scheduled task $TaskName"
Write-Host "NOTE: this only removes autostart; it does not stop the running dispatcher (use stop.ps1)."
