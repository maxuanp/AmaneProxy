# Install logon autostart + 5-minute keep-alive task (ASCII only, no admin needed)
param(
  [string]$Root = "",
  [string]$PythonW = "",
  [string]$TaskName = "AmaneProxyKeepAlive"
)
$ErrorActionPreference = "Stop"

if (-not $Root) {
  $Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
}
if (-not (Test-Path $Root)) { throw "not found: $Root" }
Write-Host "install dir: $Root"

# 1. locate pythonw.exe
if (-not $PythonW) {
  $cands = @()
  $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
  if ($cmd) { $cands += $cmd.Source }
  foreach ($glob in @("$env:LOCALAPPDATA\Programs\Python\Python3*\pythonw.exe",
                      "$env:ProgramFiles\Python3*\pythonw.exe",
                      "${env:ProgramFiles(x86)}\Python3*\pythonw.exe",
                      "C:\Python3*\pythonw.exe")) {
    $cands += (Get-ChildItem $glob -ErrorAction SilentlyContinue |
               Sort-Object { [int]($_.FullName -replace '.*Python(\d+).*', '$1') } -Descending |
               Select-Object -ExpandProperty FullName)
  }
  $PythonW = ($cands | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1)
}
if (-not $PythonW) { throw "pythonw.exe not found; pass -PythonW <path>" }
Write-Host "pythonw: $PythonW"

# 2. materialise interpreter paths into start.vbs / stop.ps1 (idempotent)
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($f in @("start.vbs", "ensure.ps1", "status.ps1")) {
  $p = Join-Path $Root $f
  if (Test-Path $p) {
    $t = (Get-Content $p -Raw) -replace "__PYTHONW__", $PythonW
    [System.IO.File]::WriteAllText($p, $t, $utf8)
  }
}
$pyExe = $PythonW -replace "pythonw\.exe$", "python.exe"
foreach ($f in @("stop.ps1")) {
  $p = Join-Path $Root $f
  if (Test-Path $p) {
    $t = (Get-Content $p -Raw) -replace "__PYTHON__", $pyExe
    [System.IO.File]::WriteAllText($p, $t, $utf8)
  }
}
Write-Host "patched start.vbs / stop.ps1"

# 3. logon shortcut in the Startup folder
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "AmaneProxy.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = "wscript.exe"
$sc.Arguments = '"' + (Join-Path $Root "start.vbs") + '"'
$sc.WorkingDirectory = $Root
$sc.WindowStyle = 7
$sc.Description = "Amane proxy dispatcher"
$sc.Save()
Write-Host "startup shortcut: $lnk"

# 4. scheduled task: make sure it runs every 5 minutes
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$arg = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $Root "ensure.ps1") + '"'
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try { schtasks /Delete /TN $TaskName /F 2>&1 | Out-Null } catch { }
$out = schtasks /Create /TN $TaskName /TR "`"$ps`" $arg" /SC MINUTE /MO 5 /F 2>&1
$rc = $LASTEXITCODE
$ErrorActionPreference = $prevEap
Write-Host $out
if ($rc -ne 0) {
  Write-Host "scheduled task failed (rerun as admin, or ignore: logon autostart is enough)" -ForegroundColor Yellow
}

# 5. run ensure once so it is up right now
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "ensure.ps1")
Write-Host ""
Write-Host "Done. Panel: http://127.0.0.1:18111" -ForegroundColor Green
