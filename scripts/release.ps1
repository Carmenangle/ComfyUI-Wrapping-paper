# 一键发布：刷新离线依赖(可选) → git 提交+推送 → git archive 打 zip(只含 git 追踪的文件，
# 自动排除 .gitignore 里的隐私/大文件：backend/data、.venv、node_modules、.env、docs、.claude 等)。
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release.ps1 -Version v0.13 -Message "更新说明"
#   加 -RefreshVendor 会先重跑 pack-vendor.ps1 + pack-npm.ps1 刷新离线依赖(依赖清单改了才需要)。
#   加 -NoPush 只提交本地、不推送远端。
#   加 -Publish 打完 zip 后自动建 tag(<Version>) + GitHub Release 并上传 zip(需已装 gh 并 gh auth login)。
param(
  [Parameter(Mandatory = $true)][string]$Version,   # zip 文件名 + git tag + Release 名，如 v0.13
  [string]$Message = "",                            # git commit 简短说明(单行)，缺省用 "release <Version>"
  [string]$NotesFile = "",                           # GitHub Release 正文的 markdown 文件路径(多行说明用它，避免命令行引号踩坑)
  [switch]$RefreshVendor,                            # 是否先刷新 vendor 离线依赖
  [switch]$NoPush,                                    # 只本地提交，不 push
  [switch]$Publish                                    # 建 tag + 发 GitHub Release 并上传 zip
)
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $Message) { $Message = "release $Version" }
# Release 正文：优先用 -NotesFile 指向的文件(支持多行/引号/箭头等)，没给就退回单行 $Message
$notesPath = ""
if ($NotesFile) {
  $notesPath = if ([System.IO.Path]::IsPathRooted($NotesFile)) { $NotesFile } else { Join-Path $projectRoot $NotesFile }
  if (-not (Test-Path -LiteralPath $notesPath)) { throw "找不到 NotesFile: $notesPath" }
}

# 1) 可选：刷新离线依赖(依赖清单变了才需要，平时跳过省时间)
if ($RefreshVendor) {
  Write-Host "== 刷新后端离线依赖 (vendor/pip) =="
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "pack-vendor.ps1")
  Write-Host "== 刷新前端离线依赖 (vendor/npm) =="
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "pack-npm.ps1")
}

# 2) git 提交(含 vendor)。有改动才提交，没改动跳过。
Write-Host "== git 提交 =="
& git add -A
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  & git commit -m $Message
  if ($LASTEXITCODE -ne 0) { throw "git commit 失败" }
} else {
  Write-Host "无改动，跳过提交。"
}

# 3) 可选推送
if (-not $NoPush) {
  Write-Host "== git 推送 =="
  $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
  & git push origin $branch
  if ($LASTEXITCODE -ne 0) { throw "git push 失败(检查远端/网络)" }
}

# 4) 打 zip：git archive 只打 HEAD 里被追踪的文件，天然排除所有 gitignore 内容(隐私零泄漏)
Write-Host "== 打包 zip =="
$zipName = "ComfyUI-Wrapping-paper-$Version.zip"
$zipPath = Join-Path $projectRoot $zipName
& git archive --format=zip -o $zipPath HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive 失败" }

$sizeMB = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "完成：$zipName ($sizeMB MB)"
Write-Host "该 zip 含代码 + vendor 离线依赖(pip/npm)，不含 backend/data 等隐私文件。"

# 5) 可选：建 tag + 发 GitHub Release 并上传 zip
if ($Publish) {
  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "未找到 gh，请先安装 GitHub CLI 并 gh auth login" }
  Write-Host ""
  Write-Host "== 发布 GitHub Release ($Version) =="
  # Release 已存在(同名 tag 重发)→ 只覆盖上传 zip(--clobber)；否则新建 Release(gh 会自动建同名 tag 指向当前 HEAD)
  # gh release view 对"不存在"会往 stderr 打字并返回非0；Stop 模式下 stderr 会被升级成终止错误，
  # 故临时把 ErrorActionPreference 调回 Continue，只看退出码判断是否存在。
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & gh release view $Version *>$null
  $releaseExists = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $prevEAP
  if ($releaseExists) {
    Write-Host "Release $Version 已存在，覆盖上传 zip..."
    & gh release upload $Version $zipPath --clobber
    if ($LASTEXITCODE -ne 0) { throw "上传 zip 到已有 Release 失败" }
  } else {
    if ($notesPath) {
      & gh release create $Version $zipPath --title $Version --notes-file $notesPath
    } else {
      & gh release create $Version $zipPath --title $Version --notes $Message
    }
    if ($LASTEXITCODE -ne 0) { throw "创建 GitHub Release 失败" }
  }
  $repo = (& gh repo view --json url -q .url).Trim()
  Write-Host "已发布：$repo/releases/tag/$Version"
}
