# 打包离线依赖：把 backend/requirements.txt 的 wheel 下到 vendor/pip，随项目上传 git，
# 让下载慢的用户 clone 后跑 start-dev 能离线装(无需联网/镜像源)。
# 跑：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pack-vendor.ps1
#
# 为何多版本：编译型包(chromadb/tiktoken 等)的 wheel 与 Python 版本绑定，
# 只打一个版本的话别的版本用户装不上。这里覆盖项目实际支持的 3.10-3.14(win_amd64)。
# 3.8/3.9 已不满足当前 LangChain/Chroma 依赖的 Python 下限，start-dev 会引导用户使用 3.10+。
# 为何 --only-binary :all:：离线装必须要现成 wheel；源码包(sdist)在用户机上要现编译，离线环境编不了。
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$reqFile = Join-Path $backendDir "requirements.txt"
$vendorDir = Join-Path $projectRoot "vendor\pip"

if (-not (Test-Path -LiteralPath $reqFile)) { throw "找不到 $reqFile" }

# 用哪个 python 跑 pip download 都行(只是下载，不装)；优先后端 venv，回退 PATH。
$py = Join-Path $backendDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
  $py = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $py) { throw "未找到 python，请先装 Python 或先跑一次 start-dev 建好 venv" }
}

# 目标 Python 版本(与 README 声明的支持范围一致)与平台。纯 wheel 包各版本重复下，pip 自动去重同名文件。
$pyVersions = @("310", "311", "312", "313", "314")
$platform = "win_amd64"

New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null
Write-Host "打包离线依赖到 $vendorDir"
Write-Host "覆盖 Python 版本: $($pyVersions -join ', ')  平台: $platform"
Write-Host ""

# 清代理直连国内源下载(与 start-dev 同理：翻墙代理连国内源会 SSLEOF)。默认清华源，可改。
$indexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple/"
$trustedHost = "pypi.tuna.tsinghua.edu.cn"

$saved = @{}
foreach ($v in 'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy') {
  $saved[$v] = [Environment]::GetEnvironmentVariable($v)
  [Environment]::SetEnvironmentVariable($v, $null)
}
$savedNo = $env:NO_PROXY
$env:NO_PROXY = "*"

try {
  $failed = @()
  foreach ($ver in $pyVersions) {
    Write-Host "=== 下载 Python $ver 的 wheel ==="
    # --only-binary :all: 只要 wheel；--python-version/--platform 指定目标环境(可跨版本下载)；
    # --implementation cp 限 CPython(整合包/官方 python 都是 cp)。用参数数组传，避免反引号续行。
    # 不放 --proxy ""：空串参数在数组 splatting 时会被丢弃，导致后面 -r 错位；清代理已靠上面的环境变量+NO_PROXY=*。
    $dlArgs = @(
      "-m", "pip", "download",
      "--only-binary", ":all:",
      "--python-version", $ver,
      "--platform", $platform,
      "--implementation", "cp",
      "-d", $vendorDir,
      "-i", $indexUrl, "--trusted-host", $trustedHost,
      "-r", $reqFile
    )
    & $py @dlArgs
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Python $ver 有部分包下载失败(可能某包无该版本 wheel)"
      $failed += $ver
    }
  }
} finally {
  foreach ($v in $saved.Keys) { [Environment]::SetEnvironmentVariable($v, $saved[$v]) }
  $env:NO_PROXY = $savedNo
}

$count = (Get-ChildItem -LiteralPath $vendorDir -Filter *.whl -ErrorAction SilentlyContinue).Count
$sizeMB = [math]::Round((Get-ChildItem -LiteralPath $vendorDir -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "完成：vendor/pip 共 $count 个 wheel，约 $sizeMB MB"
if ($failed.Count -gt 0) {
  Write-Host "注意：以下 Python 版本有包未下全，这些版本的用户可能仍需联网兜底：$($failed -join ', ')"
}
Write-Host "把 vendor/ 一起提交 git，慢速用户 clone 后 start-dev 即可离线装。"
