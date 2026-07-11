$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot

# 杀某 PID 的所有子进程（uvicorn --reload 的父 reloader 持有 socket，真正跑代码的是
# multiprocessing.spawn 子 worker；父变幽灵后 taskkill/Stop-Process 报「找不到进程」，
# 但子 worker 继承着 socket 句柄导致端口不释放）→ 杀掉子 worker，socket 立即释放、幽灵父随之消失。
function Stop-ChildProcesses([int]$ParentId) {
  $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ParentProcessId -eq $ParentId }
  foreach ($c in $children) {
    try {
      Stop-Process -Id $c.ProcessId -Force -ErrorAction Stop
      Write-Host "  Killed child worker PID $($c.ProcessId) (parent $ParentId) -> socket released"
    } catch {
      Write-Host "  Failed to kill child PID $($c.ProcessId): $_"
    }
  }
  return ($children | Measure-Object).Count
}

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
      # 幽灵父进程：owner PID 存在于 socket 表但进程已不可杀（Get-Process/Stop-Process 报找不到）。
      # 回退：杀它继承 socket 的子 worker，端口即释放。
      Write-Host "Failed to stop PID $processId on port ${Port}: $_"
      Write-Host "PID $processId looks like a zombie parent; trying to kill its child workers..."
      $n = Stop-ChildProcesses $processId
      if ($n -eq 0) { Write-Host "  No child workers found for PID $processId." }
    }
  }

  # 复查：若上面杀完子 worker 后端口仍被占，再兜底扫一遍还挂在该端口的 owner 并杀其子进程。
  Start-Sleep -Milliseconds 300
  $still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($still) {
    foreach ($pidLeft in ($still | Select-Object -ExpandProperty OwningProcess -Unique)) {
      Stop-ChildProcesses $pidLeft | Out-Null
      try { Stop-Process -Id $pidLeft -Force -ErrorAction SilentlyContinue } catch {}
    }
    Start-Sleep -Milliseconds 300
    $final = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($final) { Write-Host "WARNING: port $Port still occupied after cleanup." }
    else { Write-Host "Port $Port freed after killing child workers." }
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