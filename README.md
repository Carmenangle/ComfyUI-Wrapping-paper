# Local AI ComfyUI Frontend

本地单机前端，把 ComfyUI 封装成更好用的创作台：对话生图、AI 搭工作流、资产库/知识库（RAG）、节点管理、模型下载一体。后端 FastAPI，前端 React + Vite，通过 iframe 嵌入本机 ComfyUI 画布。

## 快速开始

双击根目录 `start-dev.bat` 一键启动（后台拉起前后端 + ComfyUI，并打开浏览器）；`stop-dev.bat` 停止。

手动启动：

```powershell
# 后端
cd D:\tool\ComfyUI\ComfyUI-Wrapping-paper\backend
python -m venv .venv; .\.venv\Scripts\activate
pip install -r requirements.txt
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

## 首次配置

进入「设置」填三类模型（OpenAI 兼容接口，填 URL/Key/模型名）：

| 配置 | 用途 |
|---|---|
| 对话模型 | 对话、AI 搭工作流、反推提示词、灵感搜索的"大脑" |
| 嵌入模型 | 知识库/资产库 RAG 检索（如 Ollama `qwen3-embedding`） |
| 生图模型 | 基础 AI 生图（工作流生图走 ComfyUI 自身节点，不用这个） |

另填 ComfyUI 目录、工作流文件夹、输出目录；外网模型/下载需要时开代理。

## 主要功能

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
