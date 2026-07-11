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

# 测某个 pip 源的下载速度(KB/s)：用系统自带 curl 限时下载一个真实大 wheel，取 curl 报告的平均速度。
# 返回值：>=0 = 可达；-1 = 连不上/失败。
# 为何用 curl 而非 .NET(HttpWebRequest/HttpClient)：.NET 的 TLS 栈在部分机器上与某些镜像源(如清华)
# 握手失败(SendFailure)误判为连不上；Windows 10/11 自带 curl.exe 的 TLS 兼容性好，与 pip 实际下载一致。
function Measure-MirrorSpeed([string]$Url, [int]$Seconds = 4) {
  try {
    $curl = "$env:SystemRoot\System32\curl.exe"
    if (-not (Test-Path -LiteralPath $curl)) { $curl = "curl" }  # 老系统回退 PATH 里的 curl
    # --max-time 到点后 curl 主动截断(退出码 28)，但 %{speed_download} 已算好这段的平均字节/秒
    $out = & $curl -s -o (Join-Path $env:TEMP "laf_probe.tmp") -w "%{http_code} %{speed_download}" --max-time $Seconds $Url 2>$null
    $parts = ($out -split '\s+') | Where-Object { $_ -ne "" }
    if ($parts.Count -lt 2) { return -1 }
    $code = [int]($parts[0])
    $bps = [double]($parts[1])
    if ($code -lt 200 -or $code -ge 400) { return -1 }   # HTTP 错误=不可用
    if ($bps -le 0) { return -1 }                         # 没下到任何数据=连不上
    return [math]::Round($bps / 1024.0, 0)
  } catch { return -1 }
  finally { Remove-Item -LiteralPath (Join-Path $env:TEMP "laf_probe.tmp") -Force -ErrorAction SilentlyContinue }
}

# 用国内镜像装依赖：临时彻底清空代理(环境变量 + NO_PROXY=*)再装，装完恢复。
# 为何要清环境变量：仅 --proxy "" 不够——urllib3 仍会读 HTTP(S)_PROXY 环境变量或系统代理，
# 走翻墙代理连国内源会把 HTTPS 切断(SSLEOF)。清空环境变量 + NO_PROXY=* 才真正直连。
# $backendPython 为全局；$reqPath 由调用方传入。返回 $true/$false（是否成功）。
function Install-FromMirror([string]$IndexUrl, [string]$TrustedHost) {
  $saved = @{}
  foreach ($v in 'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy') {
    $saved[$v] = [Environment]::GetEnvironmentVariable($v)
    [Environment]::SetEnvironmentVariable($v, $null)
  }
  $savedNo = $env:NO_PROXY
  $env:NO_PROXY = "*"
  try {
    & $backendPython -m pip install --proxy "" -i $IndexUrl --trusted-host $TrustedHost -r requirements.txt
    return ($LASTEXITCODE -eq 0)
  } finally {
    foreach ($v in $saved.Keys) { [Environment]::SetEnvironmentVariable($v, $saved[$v]) }
    $env:NO_PROXY = $savedNo
  }
}

# 首次运行装依赖：优先用随包附带的离线依赖(vendor/)离线安装，没有再联网装；都装好则跳过。
# 用「依赖指纹文件」判断是否需要（重）装——存 requirements.txt 的 hash：
#   - 无指纹/指纹不符(requirements.txt 改过) → 需要装；
#   - venv 已在且完好 → 只增量补装(pip install -r 幂等，只装缺的/新增的)，不删 venv；
#   - venv 缺失或半装(python.exe 都没有) → 清残留全新建。
# 相比只看 python.exe 存在：能在 requirements.txt 更新后自动补装新依赖，老用户不会因跳过而起不来。
$reqFile = Join-Path $backendDir "requirements.txt"
$depFingerprint = Join-Path $backendDir ".venv\.deps_hash"
$reqHash = (Get-FileHash -LiteralPath $reqFile -Algorithm SHA256).Hash
$savedHash = if (Test-Path -LiteralPath $depFingerprint) { (Get-Content -LiteralPath $depFingerprint -Raw).Trim() } else { "" }
$venvOk = Test-Path -LiteralPath $backendPython
if ($savedHash -ne $reqHash) {
  $py = (Get-Command python -ErrorAction SilentlyContinue)
  if (-not $py -and -not $venvOk) { throw "未找到 python，请先安装 Python 3.10+ 并加入 PATH" }
  if ($venvOk) {
    # venv 完好、只是 requirements 变了 → 增量补装(不删 venv，pip 自动跳过已装的)
    Write-Host "检测到依赖清单有更新，增量补装缺失依赖..."
  } else {
    # 无 venv 或半装残留 → 清掉重建
    if (Test-Path -LiteralPath (Join-Path $backendDir ".venv")) {
      Write-Host "检测到上次未装完的残留，清理后重装..."
      Remove-Item -LiteralPath (Join-Path $backendDir ".venv") -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host "首次运行：创建后端虚拟环境并安装依赖..."
    Push-Location $backendDir
    python -m venv .venv
    Pop-Location
    if (-not (Test-Path -LiteralPath $backendPython)) { throw "后端环境创建失败" }
  }
  $vendorPy = Join-Path $projectRoot "vendor\pip"    # 离线 wheel 目录(随包附带)
  Push-Location $backendDir
  try { & $backendPython -m pip cache purge *>$null } catch {}   # 清 pip 缓存(缓存空时 pip 往 stderr 打 WARNING，Stop 模式会升级成终止错误，故 try/catch 吞掉)
  $installed = $false
  # 先读出本机 venv 的 Python 版本(如 "312")，判断 vendor 里有没有该版本的 wheel。
  # 为何要判断：pip --find-links 会按本机版本挑 wheel，本机版本不在 vendor 覆盖范围时，
  # 编译型包(chromadb/tiktoken 等)找不到匹配 wheel 会刷一屏红字才失败——先判断可直接跳过、干净地走联网。
  $pyTag = (& $backendPython -c "import sys;print(f'{sys.version_info.major}{sys.version_info.minor}')" 2>$null)
  $vendorHasThisPy = $false
  if (Test-Path -LiteralPath $vendorPy) {
    # 该版本被 vendor 覆盖的判据：目录里带 cp<tag> 标签的编译型 wheel 数量达到门槛。
    # 为何用门槛而非"存在任一"：老版本(如 3.9)可能只有个别包有 cp39 wheel(实测仅 3 个)，
    # 大多数编译包缺该版本 → 离线装必然失败刷红字。用完整版本(3.10+)实测约 28-30 个做基准，
    # 取半数(15)为门槛：达标才认定覆盖走离线，否则(3.8=0、3.9=3)干净跳过直接联网。
    $cpCount = (Get-ChildItem -LiteralPath $vendorPy -Filter "*cp$pyTag*.whl" -ErrorAction SilentlyContinue | Measure-Object).Count
    $vendorHasThisPy = $pyTag -and ($cpCount -ge 15)
  }
  if ($vendorHasThisPy) {
    Write-Host "检测到 Python 3.$($pyTag.Substring(1)) 的离线依赖，使用随包离线安装(无需联网)..."
    & $backendPython -m pip install --no-index --find-links $vendorPy -r requirements.txt
    $installed = ($LASTEXITCODE -eq 0)
    # 离线装仍可能失败(个别包缺该版本 wheel) → 回退联网装
    if (-not $installed) { Write-Host "离线依赖不完整，回退联网安装..." }
  } elseif (Test-Path -LiteralPath $vendorPy) {
    Write-Host "随包离线依赖未覆盖本机 Python 版本($pyTag)，直接联网安装..."
  }
  if (-not $installed) {
    # 联网装：先给各源测速，按速度排序，优先用 >=100KB/s 的快源；
    # 慢源(<100KB/s)排到最后，只有快源都装失败(或全都慢)时才用慢源兜底。
    # 探针用真实大 wheel(numpy ~15MB)而非小索引页——小索引页会被 CDN 边缘缓存+gzip，
    # 测出的是突发峰值(曾虚高到 600KB/s 实际只 25KB/s)；大文件走存储回源才是真实持续吞吐。
    $probeRel = "packages/3f/6b/5610004206cf7f8e7ad91c5a85a8c71b2f2f8051a0c0c4d5916b76d6cbb2/numpy-1.26.4-cp311-cp311-win_amd64.whl"
    $mirrors = @(
      @{ name = "默认源(PyPI)"; url = ""; probe = "https://files.pythonhosted.org/$probeRel" },
      @{ name = "阿里云";       url = "https://mirrors.aliyun.com/pypi/simple/";        probe = "https://mirrors.aliyun.com/pypi/$probeRel" },
      @{ name = "清华源";       url = "https://pypi.tuna.tsinghua.edu.cn/simple/";       probe = "https://pypi.tuna.tsinghua.edu.cn/$probeRel" }
    )
    $SLOW = 100  # KB/s 阈值：低于此视为慢源
    Write-Host "测速各下载源(每个约 4 秒)..."
    foreach ($m in $mirrors) {
      $m.speed = Measure-MirrorSpeed $m.probe 4
      $tag = if ($m.speed -lt 0) { "连不上" } elseif ($m.speed -lt $SLOW) { "慢" } else { "快" }
      Write-Host ("  {0}: {1} KB/s ({2})" -f $m.name, $m.speed, $tag)
    }
    # 排序：连不上的(-1)最后；能连上的里，快源(>=SLOW)按速度降序在前，慢源(含 0=极慢)殿后
    $ordered = $mirrors | Sort-Object -Property `
      @{ Expression = { $_.speed -lt 0 }; Ascending = $true }, `
      @{ Expression = { $_.speed -lt $SLOW -and $_.speed -ge 0 }; Ascending = $true }, `
      @{ Expression = { $_.speed }; Descending = $true }

    # 不单独升级 pip：升级 pip 会连默认源(国外)易卡住/失败，且非必需。装依赖各自指定源。
    foreach ($m in $ordered) {
      if ($m.speed -lt 0) { Write-Host "$($m.name) 测速连不上，跳过(仅在其余源都失败时才回头尝试)"; continue }
      $note = if ($m.speed -lt $SLOW) { "(慢源兜底)" } else { "" }
      Write-Host "用 $($m.name) 安装依赖 $note ..."
      if ($m.url) {
        # 国内镜像：清代理直连（见 Install-FromMirror）
        $ok = Install-FromMirror $m.url ([Uri]$m.url).Host
      } else {
        # 默认源(PyPI，国外)保留系统代理——国内网络多半要靠代理才连得上
        & $backendPython -m pip install -r requirements.txt
        $ok = ($LASTEXITCODE -eq 0)
      }
      if ($ok) { $installed = $true; break }
      Write-Host "$($m.name) 安装失败，切换下一个源..."
    }
    # 兜底：所有连得上的源都装失败了，再试当初连不上的源(可能只是测速瞬时抖动)
    if (-not $installed) {
      foreach ($m in ($ordered | Where-Object { $_.speed -lt 0 })) {
        Write-Host "兜底再试 $($m.name)..."
        if ($m.url) {
          $ok = Install-FromMirror $m.url ([Uri]$m.url).Host
        } else {
          & $backendPython -m pip install -r requirements.txt
          $ok = ($LASTEXITCODE -eq 0)
        }
        if ($ok) { $installed = $true; break }
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
  # 写依赖指纹(requirements.txt 的 hash)，下次启动比对：一致则跳过，被改过则自动补装
  Set-Content -LiteralPath $depFingerprint -Value $reqHash -NoNewline -Encoding ascii
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