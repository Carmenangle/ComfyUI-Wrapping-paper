## 主要更新

### 离线安装能力
- 前端依赖支持离线打包（vendor/npm），clone 后无需联网即可安装，与后端 vendor/pip 一致
- 新增一键发布脚本 scripts/release.ps1：刷新离线依赖 → git 提交推送 → 打 zip → 发 GitHub Release
- start-dev 前端安装改为「离线优先、联网兜底（淘宝镜像）」

### 依赖安装稳定性
- 依赖安装按本机 Python 版本自适应，vendor 覆盖 3.8–3.14，不再拿错版本 wheel 硬装
- 修复首次安装时 pip cache purge 的 stderr WARNING 在严格模式下被误判为致命错误、导致安装中断

### 缺陷修复
- 修复模板抓参崩溃：未连线端口/自定义节点缺 link/links 字段时 clone 传入 undefined，触发 JSON 解析报错
- 斜杠指令大小写兼容：输入 /W、/S 等大写也能识别，参数（模板名/主题）保持原样

### 文档
- README 新增「环境要求」章节，明确推荐 Python 3.10–3.12（离线机务必），说明 3.8/3.9 无编译型包 wheel 的限制

### 环境要求
- Python 3.10–3.12（强烈推荐） · Node.js ≥ 18 · 本机已装 ComfyUI
