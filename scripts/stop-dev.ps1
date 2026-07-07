$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot

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

# 按命令行匹配杀本项目的后端进程：uvicorn --reload 有「父 reloader + 子 worker」两个进程，
# 只有子 worker 监听 8010，父 reloader 不占端口 → 仅按端口杀会漏掉父进程，残留占用 .venv
# 导致目录删不掉、旧代码复活。这里扫所有命令行含本项目路径的 python 进程，父子一并清掉。
function Stop-BackendByPath {
  $rootPattern = [Regex]::Escape($projectRoot)
  $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '^python' -and $_.CommandLine -and
    $_.CommandLine -match $rootPattern -and $_.CommandLine -match 'uvicorn|app\.main'
  }
  foreach ($p in $procs) {
    try {
      Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
      Write-Host "Stopped backend python PID $($p.ProcessId)"
    } catch {
      Write-Host "Failed to stop PID $($p.ProcessId): $_"
    }
  }
}

Stop-PortProcess 5173
Stop-PortProcess 8010
Stop-BackendByPath   # 补杀不监听端口的 uvicorn 父 reloader（按端口杀漏掉的）
Stop-PortProcess 8188
Write-Host "Done."