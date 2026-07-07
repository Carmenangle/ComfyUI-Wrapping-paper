$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$backendPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$frontendUrl = "http://127.0.0.1:5173"
$backendUrl = "http://127.0.0.1:8010/api/health"

# ComfyUI 配置：路径由工具「设置」写入 data/comfy_config.json，脚本据此启动（开源后无需改脚本）
$comfyConfigFile = Join-Path $backendDir "data\comfy_config.json"
$comfyExtYaml = Join-Path $backendDir "data\comfy_extra_paths.yaml"
$comfyExtSrc = Join-Path $projectRoot "comfyui-ext"

$comfyDir = ""
if (Test-Path -LiteralPath $comfyConfigFile) {
  try {
    $cfg = Get-Content -LiteralPath $comfyConfigFile -Raw -Encoding utf8 | ConvertFrom-Json
    if ($cfg.path) { $comfyDir = $cfg.path }
  } catch { }
}

function Test-PortOpen([int]$Port) {
  $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  return $null -ne $connection
}

function Test-ComfyRunning {
  # 端口已绑，或已有 main.py 进程在初始化（避免端口未就绪时重复启动）
  if (Test-PortOpen 8188) { return $true }
  $p = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match 'main\.py' -and $_.CommandLine -match 'extra-model-paths-config'
  } | Select-Object -First 1
  return $null -ne $p
}

function Wait-HttpOk([string]$Url, [int]$Seconds) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  return $false
}

# 首次运行装依赖：优先用随包附带的离线依赖(vendor/)离线安装，没有再联网装；都装好则跳过。
if (-not (Test-Path -LiteralPath $backendPython)) {
  Write-Host "首次运行：创建后端虚拟环境并安装依赖..."
  $py = (Get-Command python -ErrorAction SilentlyContinue)
  if (-not $py) { throw "未找到 python，请先安装 Python 3.10+ 并加入 PATH" }
  $vendorPy = Join-Path $projectRoot "vendor\pip"    # 离线 wheel 目录(随包附带)
  Push-Location $backendDir
  python -m venv .venv
  if (Test-Path -LiteralPath $vendorPy) {
    Write-Host "使用随包离线依赖安装(无需联网)..."
    & $backendPython -m pip install --no-index --find-links $vendorPy -r requirements.txt
  } else {
    # 联网装：先默认官方源，失败换阿里云，再失败换清华源
    $mirrors = @(
      @{ name = "默认源(PyPI)"; url = "" },
      @{ name = "阿里云";       url = "https://mirrors.aliyun.com/pypi/simple/" },
      @{ name = "清华源";       url = "https://pypi.tuna.tsinghua.edu.cn/simple/" }
    )
    & $backendPython -m pip install --upgrade pip
    $installed = $false
    foreach ($m in $mirrors) {
      Write-Host "尝试用 $($m.name) 安装依赖..."
      if ($m.url) {
        $host_ = ([Uri]$m.url).Host
        & $backendPython -m pip install -i $m.url --trusted-host $host_ -r requirements.txt
      } else {
        & $backendPython -m pip install -r requirements.txt
      }
      if ($LASTEXITCODE -eq 0) { $installed = $true; break }
      Write-Host "$($m.name) 安装失败，切换下一个源..."
    }
    if (-not $installed) { throw "依赖安装失败：默认源/阿里云/清华源均未成功，请检查网络" }
  }
  Pop-Location
  if (-not (Test-Path -LiteralPath $backendPython)) { throw "后端环境创建失败" }
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
  Write-Host "首次运行：安装前端依赖..."
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "未找到 npm，请先安装 Node.js 18+" }
  Push-Location $frontendDir
  npm install
  Pop-Location
}

if (Test-PortOpen 8010) {
  Write-Host "Backend already running on http://127.0.0.1:8010"
} else {
  Write-Host "Starting backend on http://127.0.0.1:8010"
  Start-Process -FilePath $backendPython -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010", "--reload", "--reload-dir", "app") -WorkingDirectory $backendDir -WindowStyle Hidden | Out-Null
}

if (Test-PortOpen 5173) {
  Write-Host "Frontend already running on $frontendUrl"
} else {
  Write-Host "Starting frontend on $frontendUrl"
  Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173") -WorkingDirectory $frontendDir -WindowStyle Hidden | Out-Null
}

# 启动 ComfyUI（带锁定扩展 + 自动开浏览器），已在跑或正在初始化则跳过
if (Test-ComfyRunning) {
  Write-Host "ComfyUI already running or starting on http://127.0.0.1:8188"
} elseif (-not $comfyDir) {
  Write-Host "ComfyUI path not set. Open the app -> Settings -> fill ComfyUI directory, save, then restart."
} elseif (-not (Test-Path -LiteralPath (Join-Path $comfyDir "main.py"))) {
  Write-Host "ComfyUI main.py not found under: $comfyDir ; check Settings path."
} else {
  # 生成把锁定扩展注册为 custom_nodes 的 yaml（不改 ComfyUI 本体）
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $comfyExtYaml) | Out-Null
  $extPosix = $comfyExtSrc -replace '\\', '/'
  "laf_ext:`n  custom_nodes: $extPosix`n" | Set-Content -LiteralPath $comfyExtYaml -Encoding utf8

  # 优先用整合包内置 python
  $comfyPy = $null
  foreach ($cand in @(
    (Join-Path (Split-Path -Parent $comfyDir) "python\python.exe"),
    (Join-Path (Split-Path -Parent $comfyDir) "python312\python.exe"),
    (Join-Path $comfyDir "python\python.exe")
  )) {
    if (Test-Path -LiteralPath $cand) { $comfyPy = $cand; break }
  }
  if (-not $comfyPy) { $comfyPy = "python" }

  Write-Host "Starting ComfyUI on http://127.0.0.1:8188 (with lock extension)"
  Start-Process -FilePath $comfyPy -ArgumentList @("main.py", "--extra-model-paths-config", $comfyExtYaml, "--enable-cors-header", "*", "--auto-launch") -WorkingDirectory $comfyDir | Out-Null
}

Write-Host "Waiting for backend..."
$backendReady = Wait-HttpOk $backendUrl 20
if (-not $backendReady) { Write-Host "Backend not ready yet; it may still be starting." }

Write-Host "Opening browser: $frontendUrl"
Start-Process $frontendUrl | Out-Null
Write-Host "Done. Use stop-dev.bat to stop local services."