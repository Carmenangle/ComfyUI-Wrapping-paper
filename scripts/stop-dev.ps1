$ErrorActionPreference = "Continue"

function Stop-PortProcess([int]$Port) {
  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if (-not $connections) {
    Write-Host "No process listening on port $Port"
    return
  }

  $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($processId in $processIds) {
    try {
      $process = Get-Process -Id $processId -ErrorAction Stop
      Write-Host "Stopping $($process.ProcessName) PID $processId on port $Port"
      Stop-Process -Id $processId -Force
    } catch {
      Write-Host "Failed to stop PID $processId on port ${Port}: $_"
    }
  }
}

Stop-PortProcess 5173
Stop-PortProcess 8010
Stop-PortProcess 8188
Write-Host "Done."