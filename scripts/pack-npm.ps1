# 打包前端离线依赖：把 frontend 的 npm 下载缓存灌进 vendor/npm，随项目上传 git，
# 让下载慢的用户 clone 后跑 start-dev 能离线装前端(无需联网/镜像源)。与 vendor/pip 同理。
# 跑：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pack-npm.ps1
#
# 原理：npm 的缓存是内容寻址的 cacache(按 integrity 存 tarball)。这里用 npm ci 按 package-lock.json
#   把所有依赖 tarball 拉进 vendor/npm；用户端 start-dev 再用 `npm ci --offline --cache vendor/npm`
#   纯离线还原。package-lock 已锁定确切版本+integrity，离线装无需连 registry。
# 注意：原生二进制包(rolldown/esbuild 等)只会下当前平台(win_amd64)的 optional 依赖，与 vendor/pip 一致——
#   本工具面向 Windows，跨平台用户仍会联网兜底。
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $projectRoot "frontend"
$lockFile = Join-Path $frontendDir "package-lock.json"
$npmCache = Join-Path $projectRoot "vendor\npm"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "未找到 npm，请先安装 Node.js 18+" }
if (-not (Test-Path -LiteralPath $lockFile)) { throw "找不到 $lockFile，请先在 frontend 下跑一次 npm install 生成锁文件" }

# 国内镜像加速下载(仅打包时用；离线装不连 registry)。默认 npmmirror(淘宝)，可改。
$registry = "https://registry.npmmirror.com"

New-Item -ItemType Directory -Force -Path $npmCache | Out-Null
Write-Host "打包前端离线依赖到 $npmCache"
Write-Host "使用 registry: $registry"
Write-Host ""

# npm ci 会按 lock 精确安装并把 tarball 灌入指定 cache。node_modules 是副产物(已 gitignore)，不影响。
Push-Location $frontendDir
try {
  & npm ci --cache $npmCache --registry $registry
  if ($LASTEXITCODE -ne 0) { throw "npm ci 失败，前端离线依赖未打全" }
} finally {
  Pop-Location
}

# 只留 _cacache(离线还原真正需要的内容寻址存储)；_logs 含本机路径、通知文件是杂项 → 删掉不进 git
foreach ($junk in "_logs", "_update-notifier-last-checked") {
  Remove-Item -LiteralPath (Join-Path $npmCache $junk) -Recurse -Force -ErrorAction SilentlyContinue
}

$fileCount = (Get-ChildItem -LiteralPath $npmCache -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
$sizeMB = [math]::Round((Get-ChildItem -LiteralPath $npmCache -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "完成：vendor/npm 共 $fileCount 个缓存文件，约 $sizeMB MB"
Write-Host "把 vendor/ 一起提交 git，慢速用户 clone 后 start-dev 即可离线装前端。"
