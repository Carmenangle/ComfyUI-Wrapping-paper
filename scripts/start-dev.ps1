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

# 测某个 pip 源的下载速度(KB/s)：流式拉取其 simple 索引大页面，统计 $seconds 秒内下了多少字节。
# 连不上/超时返回 0。用于「首次装依赖时优先挑快源」。
function Measure-MirrorSpeed([string]$Url, [int]$Seconds = 3) {
  try {
    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds($Seconds + 3)
    $cts = New-Object System.Threading.CancellationTokenSource
    $cts.CancelAfter([TimeSpan]::FromSeconds($Seconds))
    $resp = $client.GetAsync($Url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cts.Token).GetAwaiter().GetResult()
    $stream = $resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
    $buffer = New-Object byte[] 65536
    $total = 0
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Seconds) {
      try { $read = $stream.ReadAsync($buffer, 0, $buffer.Length, $cts.Token).GetAwaiter().GetResult() }
      catch { break }
      if ($read -le 0) { break }
      $total += $read
    }
    $sw.Stop(); $client.Dispose()
    if ($sw.Elapsed.TotalSeconds -le 0) { return 0 }
    return [math]::Round(($total / 1024.0) / $sw.Elapsed.TotalSeconds, 0)
  } catch { return 0 }
}

# 首次运行装依赖：优先用随包附带的离线依赖(vendor/)离线安装，没有再联网装；都装好则跳过。
# 用「完成标记文件」判断是否真装好——只看 python.exe 存在会误判：上次装到一半被关掉，
# venv 建好了但依赖没装全，下次就会跳过安装导致后端起不来。无标记 = 未完成 → 清残留重装。
$depMarker = Join-Path $backendDir ".venv\.deps_ok"
if (-not (Test-Path -LiteralPath $depMarker)) {
  $py = (Get-Command python -ErrorAction SilentlyContinue)
  if (-not $py) { throw "未找到 python，请先安装 Python 3.10+ 并加入 PATH" }
  # 清理上次中断的残留：半装的 venv + pip 下载缓存(避免坏缓存导致反复失败)
  if (Test-Path -LiteralPath (Join-Path $backendDir ".venv")) {
    Write-Host "检测到上次未装完的残留，清理后重装..."
    Remove-Item -LiteralPath (Join-Path $backendDir ".venv") -Recurse -Force -ErrorAction SilentlyContinue
  }
  Write-Host "首次运行：创建后端虚拟环境并安装依赖..."
  $vendorPy = Join-Path $projectRoot "vendor\pip"    # 离线 wheel 目录(随包附带)
  Push-Location $backendDir
  python -m venv .venv
  & $backendPython -m pip cache purge 2>$null   # 清 pip 下载缓存，防坏缓存反复失败
  if (Test-Path -LiteralPath $vendorPy) {
    Write-Host "使用随包离线依赖安装(无需联网)..."
    & $backendPython -m pip install --no-index --find-links $vendorPy -r requirements.txt
  } else {
    # 联网装：先给各源测速，按速度排序，优先用 >=100KB/s 的快源；
    # 慢源(<100KB/s)排到最后，只有快源都装失败(或全都慢)时才用慢源兜底。
    $mirrors = @(
      @{ name = "默认源(PyPI)"; url = ""; probe = "https://pypi.org/simple/pip/" },
      @{ name = "阿里云";       url = "https://mirrors.aliyun.com/pypi/simple/";        probe = "https://mirrors.aliyun.com/pypi/simple/pip/" },
      @{ name = "清华源";       url = "https://pypi.tuna.tsinghua.edu.cn/simple/";       probe = "https://pypi.tuna.tsinghua.edu.cn/simple/pip/" }
    )
    $SLOW = 100  # KB/s 阈值：低于此视为慢源
    Write-Host "测速各下载源(每个约 3 秒)..."
    foreach ($m in $mirrors) {
      $m.speed = Measure-MirrorSpeed $m.probe 3
      $tag = if ($m.speed -eq 0) { "连不上" } elseif ($m.speed -lt $SLOW) { "慢" } else { "快" }
      Write-Host ("  {0}: {1} KB/s ({2})" -f $m.name, $m.speed, $tag)
    }
    # 排序：能连上的优先(speed>0)，其中快源(>=SLOW)按速度降序在前，慢源殿后；连不上的最后
    $ordered = $mirrors | Sort-Object -Property `
      @{ Expression = { $_.speed -le 0 }; Ascending = $true }, `
      @{ Expression = { $_.speed -lt $SLOW -and $_.speed -gt 0 }; Ascending = $true }, `
      @{ Expression = { $_.speed }; Descending = $true }

    & $backendPython -m pip install --upgrade pip
    $installed = $false
    foreach ($m in $ordered) {
      if ($m.speed -le 0) { Write-Host "$($m.name) 测速连不上，跳过(仅在其余源都失败时才回头尝试)"; continue }
      $note = if ($m.speed -lt $SLOW) { "(慢源兜底)" } else { "" }
      Write-Host "用 $($m.name) 安装依赖 $note ..."
      if ($m.url) {
        $host_ = ([Uri]$m.url).Host
        & $backendPython -m pip install -i $m.url --trusted-host $host_ -r requirements.txt
      } else {
        & $backendPython -m pip install -r requirements.txt
      }
      if ($LASTEXITCODE -eq 0) { $installed = $true; break }
      Write-Host "$($m.name) 安装失败，切换下一个源..."
    }
    # 兜底：所有测得速度的源都失败了，再试当初连不上的源(可能只是测速瞬时抖动)
    if (-not $installed) {
      foreach ($m in ($ordered | Where-Object { $_.speed -le 0 })) {
        Write-Host "兜底再试 $($m.name)..."
        if ($m.url) {
          $host_ = ([Uri]$m.url).Host
          & $backendPython -m pip install -i $m.url --trusted-host $host_ -r requirements.txt
        } else {
          & $backendPython -m pip install -r requirements.txt
        }
        if ($LASTEXITCODE -eq 0) { $installed = $true; break }
      }
    }
    if (-not $installed) { throw "依赖安装失败：默认源/阿里云/清华源均未成功，请检查网络" }
  }
  Pop-Location
  if (-not (Test-Path -LiteralPath $backendPython)) { throw "后端环境创建失败" }
  # 校验关键依赖真的装上了(防「装了一半、命令返回 0 但包不全」)，通过才打完成标记
  & $backendPython -c "import fastapi, uvicorn, langchain_chroma, chromadb, langgraph" 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw "依赖校验失败：关键包未装全(可能下载中断)。请重新运行 start-dev.bat 会自动清理残留重装。"
  }
  New-Item -ItemType File -Path $depMarker -Force | Out-Null   # 打完成标记，下次跳过安装
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