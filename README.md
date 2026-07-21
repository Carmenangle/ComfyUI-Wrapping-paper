# ComfyUI-Wrapping-paper

本地单机前端，把 ComfyUI 封装成更好用的创作台：**工作流模板化 + AI 智能编排**、对话生图、AI 搭工作流、资产库/知识库（RAG）、节点管理、模型下载一体。后端 FastAPI，前端 React + Vite，通过 iframe 嵌入本机 ComfyUI 画布。

## 环境要求

普通用户优先下载 GitHub Release 的固定 Runtime 包，不需要安装 Python、Node.js 或项目依赖。以下环境要求只适用于源码开发版。

| 项 | 要求 | 说明 |
|---|---|---|
| **Python** | **3.10 – 3.14** | 各平台 `source-*` 发布包内置对应系统与架构的 wheels；直接 clone 的仓库只保留 Windows vendor。 |
| Node.js | ≥ 18 | 前端 `npm install` 需要。 |
| ComfyUI | 本机已装并能启动（默认 8188） | 本工具是其前端封装，需指向已有 ComfyUI 目录。 |

> ⚠️ **离线/内网机器务必用 Python 3.10–3.12。**
> chromadb / tiktoken 等编译型包在 PyPI 上**没有 Python 3.8/3.9 的现成 wheel**，vendor 无法收录。用 3.9 及以下的机器会自动回退联网编译安装——**无网环境下会直接装不上、工具起不来**。这不是 vendor 缺包，是上游就没有该版本 wheel，换 3.10+ 是唯一稳妥解。

## 快速开始

### 固定 Runtime（推荐）

按系统选择发布资产：

| 系统 | 标准版 | 完整 RAG 版 |
|---|---|---|
| Windows x64 | `windows-x64-standard` | `windows-x64-full-rag`（NVIDIA CUDA） |
| macOS Apple Silicon | `macos-arm64-standard` | `macos-arm64-full-rag`（MPS） |
| macOS Intel | `macos-x64-standard` | 不提供，CPU Reranker 不进入交互精排 |
| Linux x64 | `linux-x64-standard` | `linux-x64-full-rag`（NVIDIA CUDA） |

标准版已封装工具运行所需的 Python、全部基础后端依赖和已构建前端，支持远程或 Ollama Embedding 与 Hybrid RAG。完整 RAG 版在此基础上额外封装对应平台 Torch、Transformers、SentenceTransformers 等本地 Embedding/Reranker 运行依赖，但不内置任何模型权重。图片、对话、视频 API 和本地模型目录均由用户在设置中配置。解压后运行 `ComfyUI-Wrapping-paper.exe`（Windows）或 `ComfyUI-Wrapping-paper`（macOS/Linux），无需安装 Python、wheel、pip、npm 或 Node.js，应用会打开 `http://127.0.0.1:8010`。

本工具 Runtime 与 ComfyUI 的 Python 完全分离。设置中的“ComfyUI Python”可留空自动识别整合包或 `.venv/venv`；自定义安装位置需填写其解释器路径。工具不会使用自己的 Python 启动 ComfyUI。提交工作流前会释放本地 Reranker 显存，避免与 ComfyUI 采样同时占用 GPU/MPS。

完整 RAG 包超过 GitHub 单文件限制时会带 `.parts.json` 和多个 `.partNN`。下载同一 Release 的合并工具后，Windows 执行 `powershell -File .\join-runtime.ps1 -Manifest <清单>`，macOS/Linux 执行 `sh ./join-runtime.sh <清单>`；两者都会流式合并并校验 SHA256。

### 源码开发

双击根目录 `start-dev.bat` 一键启动（后台拉起前后端 + ComfyUI，并打开浏览器）；`stop-dev.bat` 停止。

离线环境应下载与本机匹配的源码发布包：`source-windows-x64.zip`、`source-linux-x64.tar.gz`、`source-macos-arm64.tar.gz` 或 `source-macos-x64.tar.gz`。Windows、Linux 和 macOS ARM64 包含本平台 Python 3.10–3.14 wheels；macOS Intel 因上游 `chroma-hnswlib` 没有 Python 3.14 wheel，覆盖 3.10–3.13。各包均带本平台 npm 缓存。Windows 使用 `start-dev.bat`；macOS/Linux 使用：

```sh
sh ./start-dev.sh
```

维护者在 Windows 使用 `scripts/release.ps1`；macOS/Linux 使用 `sh scripts/release.sh <版本> "<说明>" --publish`。GitHub Runtime 工作流会在对应原生 Runner 上重新生成并离线复验各平台源码包，不把多平台 wheels 混入同一个归档。

手动启动：

```powershell
# 后端
cd D:\tool\ComfyUI\ComfyUI-Wrapping-paper\backend
python -m venv .venv; .\.venv\Scripts\activate
pip install -r requirements.txt
# 使用本地 Transformers Embedding 或 Cross-Encoder Reranker 时再安装：
pip install -r requirements-reranker.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010 --reload-dir app

# 前端
cd D:\tool\ComfyUI\ComfyUI-Wrapping-paper\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

## 本地服务地址

| 服务 | 地址 |
|---|---|
| 前端 | http://127.0.0.1:5173 |
| 后端 API | http://127.0.0.1:8010/api |
| ComfyUI | http://127.0.0.1:8188 |

固定 Runtime 的前端和后端同在 `http://127.0.0.1:8010`；源码开发时前端仍使用 5173。

## 首次配置

进入「设置」填三类模型（OpenAI 兼容接口，填 URL/Key/模型名）：

| 配置 | 用途 |
|---|---|
| 对话模型 | 对话、AI 搭工作流、反推提示词、灵感搜索的"大脑" |
| 嵌入模型 | 知识库/资产库 RAG 检索（如 Ollama `qwen3-embedding`） |
| 生图模型 | 基础 AI 生图（工作流生图走 ComfyUI 自身节点，不用这个） |

另填 ComfyUI 目录、工作流文件夹、输出目录；外网模型/下载需要时开代理。

## 主要功能

### 工作流模板 + AI 智能编排（核心）
把任意 ComfyUI 工作流**模板化**，再在对话里用大白话驱动它出图，不用每次进画布手动改参数。

- **做模板（模板管理页）**：导入工作流 JSON 或扫描工作流文件夹，从里面**挑出想开放的节点字段，暴露成"输入口 / 输出口"**（正向/负向提示词、尺寸、种子、采样步数、输入图、输出节点等），每个字段配好控件类型（文本/数字/下拉/开关/图片/随机种子），存成模板。
- **进对话调用**：对话框里 `/w` 或点图标选模板，模板作为一张**工作流卡片**进入对话。
- **AI 智能调控**：`/a` + 一句自然语言需求（或点「AI 编排」按钮），AI 读取该工作流的真实节点结构，自动**填充输入口参数、切换输入/输出口、调节点参数**，先出一张**计划卡**给你确认（可同意 / 编辑 / 取消），确认后写进画布。新手无需记指令——AI 会先判断这句是不是编排意图，不是就自动转普通对话。
- **出图**：确认后 `/s` 交给 ComfyUI 执行，出图自动进资产库。

> 与「AI 搭工作流」的区别：这里是**用现成工作流**（模板化后 AI 填参驱动），后者是**从零/骨架搭新工作流**。

### 对话生图（仓库）
- 每个"仓库"是一个创作主题，内含对话、生成的图、知识库。
- 图像智能体：一个对话大脑自主调用生图 / 反推（看图出提示词）/ 联网找灵感工具。
- 生成的图自动进**资产库**（= 知识库的"生成历史"，同一份 RAG 记录：提示词 + 图 + 标签）。

### 资产库 / 知识库（RAG）
- 资产库聚合仓库里所有生成图，支持标签化管理、多词搜索、按仓库检索。
- 知识库按仓库隔离（系统指令全局共享 + 每仓库独立），AI 对话时检索"系统指令 + 本仓库"。
- 上下文压缩：把历史对话总结成一条摘要，只清对话层、不碰知识库（图/提示词不丢）。

### AI 搭工作流
左侧对话 + 右侧完整 ComfyUI 画布（laf_full 模式，与生图链路隔离）。

- **骨架底座**：内置 5 个精简骨架（文生图/图生图各含 Checkpoint 一体式 + UNET 分离式 ANIMA/Flux，反推起步）+ 扫工作流文件夹里的 .json，选一个 load 进画布再改，比从零硬搭稳。
- **三种模式**：
  - 精简直连（默认）：信任强模型一次到位，只调 1 次模型，最快不易超时。
  - 增量模式：冻结现有画布、逐块加模块，适合逐步搭大工作流。
  - 顾问模式：先出大白话方案给你审核（同意/编辑/取消），确认后再动画布，适合新手。
- **节点知识库**：同步 ComfyUI 已装节点入库（收录节点自带说明，不调大模型），AI 据此检索真实节点接口来接线。检索用 Hybrid（向量 + BM25 关键词），治专有名词召回。
- **健壮性**：AI 用了本机没装的节点会被自动拆掉、提示去安装并给本机同类平替；combo 值近似自动纠正、缺省 widget 自动补默认；缺失节点可一键跳节点管理市场搜索安装。
- 进度保存 + 多开：搭建进度（对话 + 画布）自动落盘，装节点重启 ComfyUI 后自动恢复。

### 节点管理
- 已装插件：检查更新（自建 git 检查带代理，绕开 Manager 超时）、单个更新/卸载。
- 官方插件市场：搜索安装、Git 链接安装。
- ComfyUI 本体：切换正式版/开发版（带进度与版本复查）。
- 工作流模板下载：复用 Civitai 浏览（类型选 Workflows），下到工作流文件夹即可当骨架。

### 模型下载
CivitAI / CivArchive / HuggingFace 浏览 + 下载，跨 tab 共享的下载进度面板；外网走代理。

## 架构

```text
ComfyUI-Wrapping-paper/
  backend/    FastAPI：ai(对话/搭流/知识库) · rag(Chroma) · generation · comfyui_client · models · node_manager
  frontend/   React + Vite：views(各功能页) · lib(状态机/编排) · api · components
  comfyui-ext/  laf_lock 扩展：postMessage 协议嵌入 ComfyUI 画布（laf_lock 生图锁定 / laf_full 搭流）
  docs/       排障与设计文档
```

存储：Chroma（RAG 知识库/资产库，按仓库隔离）+ SQLite（LangGraph 对话记忆）+ JSON 快照（对话流）+ 磁盘图片。

## 说明

- 单机 MVP：API key 明文存本地，后续可改加密。
- 改后端需重启 8010（--reload 偶尔不触发时按进程树杀 worker）；改 comfyui-ext 扩展 JS 需重启 ComfyUI(8188)。
- 详细排障见 `docs/`。
