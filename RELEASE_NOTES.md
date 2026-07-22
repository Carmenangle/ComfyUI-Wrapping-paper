# v0.15

## 普通 Windows 用户只需二选一

- **标准版**：[点击下载](https://github.com/Carmenangle/ComfyUI-Wrapping-paper/releases/download/v0.15/ComfyUI-Wrapping-paper-00-USER-DOWNLOAD-Windows-x64-Standard-v0.15.zip)
- **完整 RAG 版**：[点击下载](https://github.com/Carmenangle/ComfyUI-Wrapping-paper/releases/download/v0.15/ComfyUI-Wrapping-paper-00-USER-DOWNLOAD-Windows-x64-Full-RAG-v0.15.zip)

解压后直接运行根目录的 `ComfyUI-Wrapping-paper.exe`。下面的 Base、Application、RAG、Update JSON 和分片文件是启动器自动更新使用的内部资产，普通用户不要手动下载或组合。

## 分层发布与启动器

- Runtime 拆分为 Base、Application、RAG 三层；普通代码和前端更新只下载 Application 层。
- 新增 Windows portable 支撑包，内置 MinGit、Python 基础运行环境、Application 源码和启动器，首次解压即可运行。
- 新增 Windows 独立启动器，支持自动更新、自动启动、关闭到托盘和标准版/完整 RAG 版选择。
- 启动器设置持久化到本机 `data/launcher-settings.json`，关闭自动更新后不再强制下载。
- 源码模式直接复用当前项目及 `backend/data`，与 `start-dev` 共享设置、会话、API 配置和 RAG 数据。
- GitHub API 被代理出口限流时自动改用公开 Release 地址检查更新。
- 窗口、exe 和系统托盘统一使用同一应用图标。

## 后台任务与恢复

- 对话排队和 AI 工作流搭建改为 SQLite 持久化后台任务，刷新页面后可继续查询状态。
- 增加任务租约、心跳、取消、过期恢复和结果持久化，避免多进程重复执行。
- 工作流搭建会话支持后台恢复、增量更新和错误状态记录。

## 界面与功能

- 新增灰色主题及完整背景、控件、装饰和助手状态资源。
- 优化 AI 搭建、聊天后台活动、ComfyUI 进度显示和设置页面交互。
- 改进 ComfyUI Manager 状态分析、版本处理和错误提示。

## 隐私与发布闭包

- `backend/data`、根目录 `data`、Runtime 用户数据和本机构建产物均排除在 Git 提交与发布包之外。
- GitHub Actions 自动构建各平台源码包、分层 Runtime 和 Windows 启动器。
