"""ComfyUI-Wrapping-paper 终端用户启动器。
检查 GitHub 更新 → 进度对话框下载 → 启动/停止 Runtime。
纯标准库（tkinter + urllib），可用 PyInstaller 打成独立 .exe。
"""
from __future__ import annotations

import json
import hashlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote, urlparse

import tkinter as tk
from tkinter import messagebox, ttk

# ── 常量 ────────────────────────────────────────────────────────────────
APP_TITLE   = "ComfyUI Wrapping Paper"
APP_PORT    = 8010
API_TIMEOUT = 15  # GitHub/代理链路超时秒数
WINDOW_BG = "#f4f6f8"
PANEL_BG = "#ffffff"
TEXT = "#20242a"
MUTED = "#69717c"
ACCENT = "#2563eb"
PREFERENCE_KEYS = ("auto_start", "auto_update", "close_to_tray", "edition")
_WINDOW_ICON_IMAGES: list[tk.PhotoImage] = []


# ── 路径 & 配置 ──────────────────────────────────────────────────────────

def launcher_dir() -> Path:
    """启动器所在目录（frozen 环境取 exe 目录，开发环境取项目根）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def load_config() -> dict:
    """从同目录 launcher-config.json 读配置，缺省值兜底。"""
    suffix = ".exe" if platform.system() == "Windows" else ""
    defaults: dict = {
        "github_repo": "Carmenangle/ComfyUI-Wrapping-paper",
        # Runtime 主程序名（与启动器区分，避免自启自己）
        "app_exe": f"ComfyUI-Wrapping-paper-Runtime{suffix}",
        # 相对 launcher_dir 的子目录：Runtime 程序装这、用户数据落这
        "runtime_dir": "data/runtime",
        "data_dir": "data/userdata",
        "port": APP_PORT,
        "edition": "standard",
        "auto_start": True,
        "auto_update": True,
        "close_to_tray": True,
    }
    cfg = launcher_dir() / "launcher-config.json"
    if cfg.exists():
        try:
            defaults.update(json.loads(cfg.read_text(encoding="utf-8")))
        except Exception:
            pass
    settings = launcher_dir() / "data" / "launcher-settings.json"
    if settings.exists():
        try:
            saved = json.loads(settings.read_text(encoding="utf-8"))
            defaults.update({key: saved[key] for key in PREFERENCE_KEYS if key in saved})
        except Exception:
            pass
    return defaults


def save_config(cfg: dict) -> None:
    path = launcher_dir() / "data" / "launcher-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".json.tmp")
    payload = {key: cfg[key] for key in PREFERENCE_KEYS if key in cfg}
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(pending, path)


def app_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "app-icon.png"
    return Path(__file__).resolve().parents[1] / "release" / "app-icon.png"


def apply_window_icon(window: tk.Misc) -> None:
    try:
        image = tk.PhotoImage(file=str(app_icon_path()))
        window.winfo_toplevel().iconphoto(True, image)
        _WINDOW_ICON_IMAGES.append(image)
    except (tk.TclError, OSError):
        pass


def runtime_dir(cfg: dict) -> Path:
    """Runtime 程序安装目录（data/runtime）。"""
    return launcher_dir() / cfg.get("runtime_dir", "data/runtime")


def userdata_dir(cfg: dict) -> Path:
    """用户数据目录（data/userdata），传给 Runtime 的 LAF_DATA_DIR。"""
    return launcher_dir() / cfg.get("data_dir", "data/userdata")


def source_project_root() -> Path | None:
    """识别启动器同级或 release-assets 上级的完整源码项目。"""
    for root in (launcher_dir(), launcher_dir().parent):
        python = (
            root / "backend" / ".venv" / "Scripts" / "python.exe"
            if platform.system() == "Windows"
            else root / "backend" / ".venv" / "bin" / "python"
        )
        required = (
            root / "backend" / "app" / "main.py",
            root / "frontend" / "dist" / "index.html",
            python,
        )
        if all(path.is_file() for path in required):
            return root
    return None


def source_project_version() -> str:
    root = source_project_root()
    if root is None:
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
        )
        return result.stdout.strip() or "源码项目"
    except (OSError, subprocess.SubprocessError):
        return "源码项目"


def application_backend_ready(application_dir: Path) -> bool:
    return (
        (application_dir / "backend" / "app" / "main.py").is_file()
        or (application_dir / "backend.zip").is_file()
    )


def with_portable_git(env: dict[str, str]) -> dict[str, str]:
    result = env.copy()
    git_cmd = launcher_dir() / "dependencies" / "git" / "cmd"
    if git_cmd.is_dir():
        result["PATH"] = str(git_cmd) + os.pathsep + result.get("PATH", "")
    return result


def current_state(cfg: dict) -> dict:
    path = runtime_dir(cfg) / "current.json"
    if not path.is_file():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if state.get("schema_version") == 2 else {}
    except Exception:
        return {}


def installed_version(cfg: dict) -> str:
    """读取分层状态，兼容旧 Runtime manifest 和 version.txt。"""
    state = current_state(cfg)
    if state:
        return str(state.get("app_version", "")).strip()
    manifest = runtime_dir(cfg) / "runtime-manifest.json"
    if manifest.exists():
        try:
            return str(json.loads(manifest.read_text(encoding="utf-8")).get("app_version", "")).strip()
        except Exception:
            pass
    p = launcher_dir() / "version.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return source_project_version()


def runtime_installed(cfg: dict) -> bool:
    """Runtime 主程序和 Application 是否已就位。"""
    state = current_state(cfg)
    if state:
        base = runtime_dir(cfg) / "base" / str(state.get("base_id", ""))
        app = runtime_dir(cfg) / "apps" / str(state.get("application_id", ""))
        return (base / cfg["app_exe"]).is_file() and application_backend_ready(app)
    return (runtime_dir(cfg) / cfg["app_exe"]).exists()


def should_check_updates(cfg: dict, *, force: bool = False) -> bool:
    return force or bool(cfg.get("auto_update", True))


def primary_action(cfg: dict) -> str:
    return "start" if runtime_installed(cfg) or source_project_root() is not None else "install"


def runtime_executable(cfg: dict, state: dict | None = None) -> Path:
    selected = state if state is not None else current_state(cfg)
    if selected:
        return runtime_dir(cfg) / "base" / str(selected.get("base_id", "")) / cfg["app_exe"]
    return runtime_dir(cfg) / cfg["app_exe"]


def launch_spec(cfg: dict) -> tuple[list[str], Path, dict[str, str]]:
    """返回发布 Runtime 或现有源码项目的启动命令。"""
    if runtime_installed(cfg):
        executable = runtime_executable(cfg)
        return [str(executable)], runtime_dir(cfg), {}
    root = source_project_root()
    if root is None:
        raise FileNotFoundError("未找到 Runtime 或可运行的源码项目")
    python = (
        root / "backend" / ".venv" / "Scripts" / "python.exe"
        if platform.system() == "Windows"
        else root / "backend" / ".venv" / "bin" / "python"
    )
    command = [
        str(python), "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(cfg.get("port", APP_PORT)),
    ]
    environment = {
        "LAF_RUNTIME_ROOT": str(root),
        "LAF_DATA_DIR": str(root / "backend" / "data"),
        "LAF_FRONTEND_DIST": str(root / "frontend" / "dist"),
        "LAF_COMFY_EXT_DIR": str(root / "comfyui-ext"),
    }
    return command, root / "backend", environment


def target_id(edition: str) -> str:
    sys_map = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}
    sys_tag = sys_map.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    arch_tag = "arm64" if machine in ("arm64", "aarch64") else "x64"
    return f"{sys_tag}-{arch_tag}-{edition}"


def layer_directory(cfg: dict, layer: str, layer_id: str) -> Path:
    folder = {"base": "base", "application": "apps", "rag": "rag"}[layer]
    return runtime_dir(cfg) / folder / layer_id


def layer_update_plan(cfg: dict, manifest: dict) -> list[str]:
    state = current_state(cfg)
    plan = []
    for name in ("base", "application", "rag"):
        layer = manifest.get("layers", {}).get(name)
        if not layer:
            continue
        layer_id = str(layer.get("id", ""))
        dest = layer_directory(cfg, name, layer_id)
        required = dest.is_dir()
        if name == "base":
            required = (dest / cfg["app_exe"]).is_file()
        elif name == "application":
            required = application_backend_ready(dest) and (dest / "frontend" / "index.html").is_file()
        elif name == "rag":
            required = (dest / "site-packages").is_dir()
        state_key = "application_id" if name == "application" else f"{name}_id"
        if str(state.get(state_key, "")) != layer_id or not required:
            plan.append(name)
    return plan


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_state(manifest: dict) -> dict:
    layers = manifest["layers"]
    return {
        "schema_version": 2,
        "app_version": manifest["app_version"],
        "target": manifest["target"],
        "edition": manifest["edition"],
        "base_id": layers["base"]["id"],
        "application_id": layers["application"]["id"],
        "rag_id": layers.get("rag", {}).get("id", ""),
    }


def write_current_state(cfg: dict, state: dict) -> None:
    root = runtime_dir(cfg)
    root.mkdir(parents=True, exist_ok=True)
    current = root / "current.json"
    previous = root / "current.previous.json"
    if current.is_file():
        shutil.copy2(current, previous)
    pending = root / "current.json.tmp"
    pending.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(pending, current)


def write_version(v: str) -> None:
    (launcher_dir() / "version.txt").write_text(v, encoding="utf-8")


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


# ── GitHub 更新检查 ──────────────────────────────────────────────────────

class UpdateCheckError(RuntimeError):
    pass


def _fetch_github_api_release(repo: str) -> dict:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": APP_TITLE},
    )
    with urllib.request.urlopen(req, timeout=API_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub 返回了无效数据")
    return payload


def _release_asset(repo: str, tag: str, name: str) -> dict:
    encoded_tag = quote(tag, safe="")
    encoded_name = quote(name)
    return {
        "name": name,
        "browser_download_url": f"https://github.com/{repo}/releases/download/{encoded_tag}/{encoded_name}",
    }


def _fetch_release_without_api(repo: str, edition: str) -> dict:
    """API 被共享代理限流时，通过公开 Release 地址构造资产清单。"""
    request = urllib.request.Request(
        f"https://github.com/{repo}/releases/latest",
        headers={"User-Agent": APP_TITLE},
    )
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
        final_url = response.geturl()
    marker = "/releases/tag/"
    if marker not in final_url:
        raise ValueError("GitHub 未返回最新版本号")
    tag = unquote(urlparse(final_url).path.split(marker, 1)[1]).strip("/")
    version = tag.lstrip("v")
    target = target_id(edition)
    for release_version in dict.fromkeys((tag, version)):
        manifest_name = f"ComfyUI-Wrapping-paper-update-{release_version}-{target}.json"
        manifest_asset = _release_asset(repo, tag, manifest_name)
        manifest = fetch_json(manifest_asset["browser_download_url"])
        if manifest and manifest.get("schema_version") == 2:
            assets = [manifest_asset]
            for layer in manifest.get("layers", {}).values():
                for part in layer.get("assets", []):
                    assets.append(_release_asset(repo, tag, str(part["name"])))
            return {"tag_name": tag, "assets": assets}

    suffix = ".zip" if platform.system() == "Windows" else ".tar.gz"
    archive_name = f"ComfyUI-Wrapping-paper-v{version}-{target}{suffix}"
    if edition == "full-rag":
        parts_name = archive_name + ".parts.json"
        parts_asset = _release_asset(repo, tag, parts_name)
        parts_payload = fetch_json(parts_asset["browser_download_url"])
        if parts_payload and parts_payload.get("schema_version") == 1:
            assets = [parts_asset]
            assets.extend(
                _release_asset(repo, tag, str(name))
                for name in parts_payload.get("parts", [])
            )
            return {"tag_name": tag, "assets": assets}
    return {"tag_name": tag, "assets": [_release_asset(repo, tag, archive_name)]}


def fetch_latest_release(repo: str, edition: str) -> dict:
    errors = []
    try:
        return _fetch_github_api_release(repo)
    except Exception as exc:
        errors.append(f"API：{exc}")
    try:
        return _fetch_release_without_api(repo, edition)
    except Exception as exc:
        errors.append(f"Release：{exc}")
    raise UpdateCheckError("；".join(errors))


def pick_asset(assets: list[dict], edition: str) -> dict | None:
    """按平台+架构+版本从 release assets 里选最合适的。"""
    sys_map = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}
    sys_tag = sys_map.get(platform.system(), platform.system().lower())
    mach = platform.machine().lower()
    arch_tag = "arm64" if mach in ("arm64", "aarch64") else "x64"

    for asset in assets:
        n = asset.get("name", "").lower()
        if (
            sys_tag in n and arch_tag in n and edition in n
            and "-source-" not in n and ".part" not in n and not n.endswith(".parts.json")
        ):
            return asset
    return None


def pick_parts_manifest(assets: list[dict], edition: str) -> dict | None:
    sys_map = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}
    sys_tag = sys_map.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    arch_tag = "arm64" if machine in ("arm64", "aarch64") else "x64"
    for asset in assets:
        name = asset.get("name", "").lower()
        if (
            sys_tag in name and arch_tag in name and edition in name
            and "-source-" not in name and name.endswith(".parts.json")
        ):
            return asset
    return None


def pick_update_manifest(assets: list[dict], edition: str) -> dict | None:
    target = target_id(edition)
    for asset in assets:
        name = asset.get("name", "").lower()
        if "-update-" in name and name.endswith(f"-{target}.json"):
            return asset
    return None


def fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": APP_TITLE})
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


# ── 下载器 ───────────────────────────────────────────────────────────────

class DownloadCancelled(Exception):
    pass


class Downloader:
    def __init__(self) -> None:
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def download(
        self,
        url: str,
        dest: Path,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """下载 url 到 dest；on_progress(bytes_done, total, filename)。"""
        filename = url.split("/")[-1].split("?")[0]
        req = urllib.request.Request(url, headers={"User-Agent": APP_TITLE})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.getheader("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                while True:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total, filename)

    def extract(self, archive: Path, dest: Path) -> None:
        if self._cancel.is_set():
            raise DownloadCancelled()
        name = archive.name.lower()
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                members = zf.infolist()
                names = [info.filename.strip("/") for info in members if info.filename.strip("/")]
                roots = {name.split("/", 1)[0] for name in names}
                prefix = next(iter(roots)) + "/" if len(roots) == 1 else ""
                for info in members:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    rel = info.filename[len(prefix):] if prefix and info.filename.startswith(prefix) else info.filename
                    if not rel:
                        continue
                    tgt = self._safe_target(dest, rel)
                    if info.is_dir():
                        tgt.mkdir(parents=True, exist_ok=True)
                    else:
                        tgt.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(tgt, "wb") as dst:
                            shutil.copyfileobj(src, dst)
        elif name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive, "r:gz") as tf:
                members = tf.getmembers()
                names = [member.name.strip("/") for member in members if member.name.strip("/")]
                roots = {name.split("/", 1)[0] for name in names}
                prefix = next(iter(roots)) + "/" if len(roots) == 1 else ""
                for member in members:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    rel = member.name[len(prefix):] if prefix and member.name.startswith(prefix) else member.name
                    if not rel or member.isdir():
                        continue
                    target = self._safe_target(dest, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = tf.extractfile(member)
                    if source is not None:
                        with source, open(target, "wb") as output:
                            shutil.copyfileobj(source, output)

    @staticmethod
    def _safe_target(dest: Path, relative: str) -> Path:
        target = (dest / relative).resolve()
        root = dest.resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"压缩包包含非法路径：{relative}")
        return target


class TrayController:
    def __init__(self, app: "LauncherApp") -> None:
        self.app = app
        self.icon = None

    def show(self) -> bool:
        if self.icon is not None:
            return True
        try:
            import pystray
            from PIL import Image

            image = Image.open(app_icon_path()).convert("RGBA")
            self.icon = pystray.Icon(
                "comfyui-wrapping-paper",
                image,
                APP_TITLE,
                pystray.Menu(
                    pystray.MenuItem("显示窗口", self._restore, default=True),
                    pystray.MenuItem("退出程序", self._quit),
                ),
            )
            self.icon.run_detached()
            return True
        except Exception:
            self.icon = None
            return False

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()
            self.icon = None

    def _restore(self, _icon=None, _item=None) -> None:
        self.app.after(0, self.app._restore_window)

    def _quit(self, _icon=None, _item=None) -> None:
        self.app.after(0, self.app._quit_app)


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: "LauncherApp") -> None:
        super().__init__(parent)
        self.parent = parent
        self.title("设置")
        apply_window_icon(self)
        self.configure(bg=WINDOW_BG)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.close_to_tray = tk.BooleanVar(value=bool(parent.cfg.get("close_to_tray", True)))
        self.auto_update = tk.BooleanVar(value=bool(parent.cfg.get("auto_update", True)))
        self.auto_start = tk.BooleanVar(value=bool(parent.cfg.get("auto_start", True)))
        self.edition = tk.StringVar(value=str(parent.cfg.get("edition", "standard")))

        panel = tk.Frame(self, bg=PANEL_BG, padx=22, pady=20, width=390, height=320)
        panel.pack(padx=12, pady=12, fill="both", expand=True)
        panel.pack_propagate(False)
        tk.Label(panel, text="启动器设置", bg=PANEL_BG, fg=TEXT, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        tk.Label(panel, text="更改会保存在本机", bg=PANEL_BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(2, 14))

        options = (
            ("关闭窗口后在系统托盘运行", self.close_to_tray),
            ("自动检查并安装更新", self.auto_update),
            ("打开启动器后自动启动工具", self.auto_start),
        )
        for text, variable in options:
            tk.Checkbutton(
                panel, text=text, variable=variable, bg=PANEL_BG, activebackground=PANEL_BG,
                fg=TEXT, selectcolor=PANEL_BG, anchor="w", font=("Microsoft YaHei UI", 10),
                padx=0, pady=5,
            ).pack(fill="x")

        tk.Label(panel, text="运行版本", bg=PANEL_BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(10, 3))
        edition_row = tk.Frame(panel, bg=PANEL_BG)
        edition_row.pack(fill="x")
        for text, value in (("标准版", "standard"), ("完整 RAG 版", "full-rag")):
            tk.Radiobutton(
                edition_row, text=text, value=value, variable=self.edition,
                bg=PANEL_BG, activebackground=PANEL_BG, selectcolor=PANEL_BG,
                fg=TEXT, font=("Microsoft YaHei UI", 9), padx=0,
            ).pack(side="left", padx=(0, 18))

        actions = tk.Frame(panel, bg=PANEL_BG)
        actions.pack(side="bottom", fill="x")
        tk.Button(
            actions, text="取消", command=self.destroy, width=9,
            bg="#e8ebef", fg=TEXT, relief="flat", font=("Microsoft YaHei UI", 9),
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            actions, text="保存", command=self._save, width=9,
            bg=ACCENT, fg="#ffffff", activebackground="#1d4ed8", activeforeground="#ffffff",
            relief="flat", font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="right")

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_reqheight()) // 2
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.after_idle(lambda: apply_window_icon(self))

    def _save(self) -> None:
        self.parent.cfg.update({
            "close_to_tray": self.close_to_tray.get(),
            "auto_update": self.auto_update.get(),
            "auto_start": self.auto_start.get(),
            "edition": self.edition.get(),
        })
        try:
            save_config(self.parent.cfg)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.parent._log_msg("设置已保存")
        self.destroy()


# ── 更新进度对话框（仿绘世启动器样式） ────────────────────────────────────

class UpdateDialog(tk.Toplevel):
    """下载/更新进度对话框。与主窗口无关，可独立弹出。"""

    def __init__(
        self, parent: tk.Tk, total_files: int,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("正在启动应用程序")
        apply_window_icon(self)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._cancelled = threading.Event()
        self._on_cancel = on_cancel   # 通知真正的 Downloader 停止
        self._total = total_files
        self._current = 0

        # ── 布局 ──
        frame = tk.Frame(self, padx=24, pady=20)
        frame.pack(fill="both", expand=True)

        self._top_label = tk.Label(
            frame, text="正在下载更新文件。这可能需要一会儿时间。",
            font=("Microsoft YaHei", 10), anchor="w", wraplength=380,
        )
        self._top_label.pack(fill="x", pady=(0, 12))

        self._bar = ttk.Progressbar(frame, orient="horizontal", length=400, mode="determinate")
        self._bar.pack(fill="x", pady=(0, 8))

        self._detail = tk.Label(
            frame, text="", font=("Microsoft YaHei", 9),
            fg="#555555", anchor="w", wraplength=380,
        )
        self._detail.pack(fill="x", pady=(0, 16))

        btn_frame = tk.Frame(frame)
        btn_frame.pack(anchor="e")
        self._skip_btn = tk.Button(
            btn_frame, text="跳过更新", width=10,
            command=self._on_skip,
        )
        self._skip_btn.pack()

        self._center(parent)
        self.grab_set()
        self.after_idle(lambda: apply_window_icon(self))

    def _center(self, parent: tk.Tk) -> None:
        self.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_x(), parent.winfo_y()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{px + (pw - w)//2}+{py + (ph - h)//2}")

    def _on_skip(self) -> None:
        self._cancelled.set()
        if self._on_cancel is not None:
            self._on_cancel()      # 立即让下载线程中断
        # 进度条若在 indeterminate 动画中，停下来
        try:
            self._bar.stop()
        except Exception:
            pass
        self._skip_btn.config(state="disabled", text="正在取消…")

    def _on_close(self) -> None:
        self._on_skip()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def set_file(self, idx: int, name: str) -> None:
        self._current = idx
        self._detail.config(text=f"正在下载第 {idx} / {self._total} 个文件：\n{name}")

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._bar["value"] = done / total * 100
        else:
            self._bar["mode"] = "indeterminate"
            self._bar.start(10)

    def set_extracting(self) -> None:
        self._top_label.config(text="正在解压更新文件，请稍候…")
        self._bar["mode"] = "indeterminate"
        self._bar.start(10)

    def close(self) -> None:
        self.grab_release()
        self.destroy()


# ── 主窗口 ────────────────────────────────────────────────────────────────

class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self._proc: subprocess.Popen | None = None
        self._downloader: Downloader | None = None
        self._update_dlg: UpdateDialog | None = None
        self._tray = TrayController(self)

        self.title(APP_TITLE)
        apply_window_icon(self)
        self.configure(bg=WINDOW_BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_exit)

        frame = tk.Frame(self, bg=WINDOW_BG, width=380, height=260, padx=18, pady=18)
        frame.pack(fill="both", expand=True)
        frame.pack_propagate(False)

        header = tk.Frame(frame, bg=WINDOW_BG)
        header.pack(fill="x")
        tk.Label(header, text=APP_TITLE, bg=WINDOW_BG, fg=TEXT, font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")

        ver = installed_version(self.cfg) or "（未安装）"
        self._ver_label = tk.Label(header, text=f"本地版本：{ver}", bg=WINDOW_BG, fg=MUTED, font=("Microsoft YaHei UI", 9))
        self._ver_label.pack(anchor="w", pady=(2, 14))

        status_panel = tk.Frame(frame, bg=PANEL_BG, padx=14, pady=13)
        status_panel.pack(fill="x")
        self._status = tk.Label(status_panel, text="● 已停止", bg=PANEL_BG, fg=MUTED, font=("Microsoft YaHei UI", 10, "bold"))
        self._status.pack(anchor="w")

        btn_row = tk.Frame(status_panel, bg=PANEL_BG)
        btn_row.pack(anchor="w", pady=(12, 0))
        self._start_btn = tk.Button(
            btn_row, text="▶  启动", width=11, command=self._on_start,
            bg=ACCENT, fg="#ffffff", activebackground="#1d4ed8", activeforeground="#ffffff",
            relief="flat", font=("Microsoft YaHei UI", 9, "bold"), pady=4,
        )
        self._start_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = tk.Button(
            btn_row, text="■  停止", width=11, command=self._on_stop, state="disabled",
            bg="#e8ebef", fg=TEXT, activebackground="#dce1e7", relief="flat",
            font=("Microsoft YaHei UI", 9), pady=4,
        )
        self._stop_btn.pack(side="left")

        self._log = tk.Label(frame, text="", bg=WINDOW_BG, fg=MUTED, font=("Microsoft YaHei UI", 8), wraplength=340, justify="left")
        self._log.pack(anchor="w", pady=(10, 0))

        footer = tk.Frame(frame, bg=WINDOW_BG)
        footer.pack(side="bottom", fill="x")
        tk.Button(
            footer, text="⚙  设置", command=self._open_settings,
            bg=WINDOW_BG, fg=MUTED, activebackground=WINDOW_BG, activeforeground=TEXT,
            relief="flat", borderwidth=0, font=("Microsoft YaHei UI", 9), padx=0,
        ).pack(side="left")
        tk.Button(
            footer, text="检查更新", command=self._manual_check_update,
            bg=WINDOW_BG, fg=MUTED, activebackground=WINDOW_BG, activeforeground=TEXT,
            relief="flat", borderwidth=0, font=("Microsoft YaHei UI", 9), padx=0,
        ).pack(side="right")
        self.after_idle(lambda: apply_window_icon(self))

        # 定时刷新运行状态
        self._poll()
        # 启动时后台检查更新
        threading.Thread(target=self._check_update, daemon=True).start()

    # ── 状态轮询 ─────────────────────────────────────────────────────────

    def _poll(self) -> None:
        running = port_open(self.cfg["port"])
        if running:
            self._status.config(text="● 运行中", fg="#2a9d2a")
            self._start_btn.config(state="disabled")
            self._stop_btn.config(state="normal")
        else:
            self._status.config(text="● 已停止", fg="#999")
            self._start_btn.config(state="normal")
            self._start_btn.config(text="↓  安装" if primary_action(self.cfg) == "install" else "▶  启动")
            self._stop_btn.config(state="disabled")
        self.after(2000, self._poll)

    def _log_msg(self, msg: str) -> None:
        self._log.config(text=msg)

    def _open_settings(self) -> None:
        SettingsDialog(self)

    def _manual_check_update(self) -> None:
        if self._update_dlg is not None:
            return
        threading.Thread(target=lambda: self._check_update(force=True), daemon=True).start()

    # ── 启动 / 停止 ───────────────────────────────────────────────────────

    def _on_start(self) -> None:
        if primary_action(self.cfg) == "install":
            edition = "完整 RAG 版" if self.cfg.get("edition") == "full-rag" else "标准版"
            if messagebox.askyesno("安装 Runtime", f"当前尚未安装 Runtime。是否安装{edition}？"):
                self._manual_check_update()
            return
        self._start_btn.config(state="disabled")
        threading.Thread(target=self._do_start, daemon=True).start()

    def _do_start(self) -> None:
        rt = runtime_dir(self.cfg)
        try:
            command, working_dir, source_env = launch_spec(self.cfg)
        except FileNotFoundError:
            self.after(0, lambda: messagebox.showerror(
                "找不到程序", f"未找到可运行的源码项目或 {self.cfg['app_exe']}，请检查 {rt} 目录。"
            ))
            self.after(0, lambda: self._start_btn.config(state="normal"))
            return
        self.after(0, lambda: self._log_msg("正在启动…"))
        data = Path(source_env.get("LAF_DATA_DIR", str(userdata_dir(self.cfg))))
        data.mkdir(parents=True, exist_ok=True)
        env = with_portable_git({
            **os.environ,
            "LAF_NO_BROWSER": "0",
            "LAF_DATA_DIR": str(data),
            "LAF_RUNTIME_ROOT": str(rt),
            "LAF_RUNTIME_STATE": str(rt / "current.json"),
            **source_env,
        })
        try:
            self._proc = subprocess.Popen(
                command,
                cwd=str(working_dir),
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
            )
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror("启动失败", err))
            self.after(0, lambda: self._start_btn.config(state="normal"))
            return
        # 源码项目首次载入数据库和依赖较慢；固定 Runtime 保持 20 秒等待。
        wait_loops = 240 if source_env else 40
        for _ in range(wait_loops):
            if port_open(self.cfg["port"]):
                break
            time.sleep(0.5)
        if source_env and port_open(self.cfg["port"]):
            webbrowser.open(f"http://127.0.0.1:{self.cfg['port']}")
        self.after(0, lambda: self._log_msg(""))

    def _on_stop(self) -> None:
        self._stop_btn.config(state="disabled")
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        self.after(0, lambda: self._log_msg("已停止"))

    def _on_exit(self) -> None:
        if self.cfg.get("close_to_tray", True):
            if self._tray.show():
                self.withdraw()
                return
            messagebox.showerror("托盘启动失败", "无法创建系统托盘图标，启动器将保持打开。")
            return
        self._quit_app()

    def _restore_window(self) -> None:
        self._tray.stop()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_app(self) -> None:
        if self._downloader is not None:
            self._downloader.cancel()
        self._tray.stop()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        self.destroy()

    # ── 更新检查 ─────────────────────────────────────────────────────────

    def _check_update(self, force: bool = False) -> None:
        if not should_check_updates(self.cfg, force=force):
            message = "自动更新已关闭。" if runtime_installed(self.cfg) else "自动更新已关闭，点击“安装”获取 Runtime。"
            self.after(0, lambda msg=message: self._log_msg(msg))
            self.after(0, self._maybe_auto_start)
            return
        repo = self.cfg["github_repo"]
        self.after(0, lambda: self._log_msg("正在检查更新…"))
        try:
            release = fetch_latest_release(repo, self.cfg["edition"])
        except UpdateCheckError as exc:
            self.after(0, lambda err=str(exc): self._log_msg(f"检查更新失败：{err}"))
            self.after(0, self._maybe_auto_start)
            return
        latest = release.get("tag_name", "").lstrip("v")
        local  = installed_version(self.cfg).lstrip("v")
        if source_project_root() is not None and not runtime_installed(self.cfg):
            message = (
                f"已是最新版本 v{latest}。"
                if local == latest
                else f"源码项目当前为 {local}，最新发布为 v{latest}；请使用 Git 更新源码。"
            )
            self.after(0, lambda msg=message: self._log_msg(msg))
            self.after(0, self._maybe_auto_start)
            return
        manifest_asset = pick_update_manifest(release.get("assets", []), self.cfg["edition"])
        if manifest_asset:
            manifest = fetch_json(manifest_asset["browser_download_url"])
            expected_target = target_id(self.cfg["edition"])
            if manifest and manifest.get("schema_version") == 2 and manifest.get("target") == expected_target:
                plan = layer_update_plan(self.cfg, manifest)
                if not plan and runtime_installed(self.cfg):
                    write_current_state(self.cfg, candidate_state(manifest))
                    write_version(latest)
                    self.after(0, lambda: self._log_msg(f"已是最新版本 v{latest}。"))
                    self.after(0, self._maybe_auto_start)
                    return
                self.after(0, lambda: self._log_msg(f"发现新版本 v{latest}，准备分层更新…"))
                self.after(0, lambda: self._start_layer_update(release, manifest, plan, latest))
                return
        # 旧版 Release 没有分层清单时才按总版本判断。
        if runtime_installed(self.cfg) and local and local == latest:
            self.after(0, lambda: self._log_msg(f"已是最新版本 v{latest}。"))
            self.after(0, self._maybe_auto_start)
            return
        asset = pick_asset(release.get("assets", []), self.cfg["edition"])
        if not asset:
            parts_asset = pick_parts_manifest(release.get("assets", []), self.cfg["edition"])
            parts_payload = fetch_json(parts_asset["browser_download_url"]) if parts_asset else None
            if parts_payload and parts_payload.get("schema_version") == 1:
                self.after(0, lambda: self._log_msg(f"发现新版本 v{latest}，准备下载分片…"))
                self.after(0, lambda: self._start_parts_update(release, parts_payload, latest))
                return
            self.after(0, lambda: self._log_msg("未找到适合本机的更新包。"))
            self.after(0, self._maybe_auto_start)
            return
        label = f"发现新版本 v{latest}，准备下载…"
        self.after(0, lambda: self._log_msg(label))
        self.after(0, lambda: self._start_update(release, asset, latest))

    def _start_layer_update(self, release: dict, manifest: dict, plan: list[str], latest: str) -> None:
        self._downloader = Downloader()
        total = sum(len(manifest["layers"][name]["assets"]) for name in plan)
        dlg = UpdateDialog(self, total_files=max(total, 1), on_cancel=self._downloader.cancel)
        self._update_dlg = dlg
        threading.Thread(
            target=self._do_layer_update,
            args=(dlg, release, manifest, plan, latest),
            daemon=True,
        ).start()

    def _start_parts_update(self, release: dict, parts_payload: dict, latest: str) -> None:
        self._downloader = Downloader()
        dlg = UpdateDialog(
            self, total_files=len(parts_payload.get("parts", [])),
            on_cancel=self._downloader.cancel,
        )
        self._update_dlg = dlg
        threading.Thread(
            target=self._do_parts_update,
            args=(dlg, release, parts_payload, latest),
            daemon=True,
        ).start()

    def _do_parts_update(
        self, dlg: UpdateDialog, release: dict, parts_payload: dict, latest: str,
    ) -> None:
        dl = self._downloader
        assert dl is not None
        tmp = Path(tempfile.mkdtemp(prefix="laf_parts_update_"))
        release_assets = {asset["name"]: asset for asset in release.get("assets", [])}
        try:
            downloaded_parts = []
            part_names = parts_payload.get("parts", [])
            part_hashes = parts_payload.get("part_sha256", {})
            for index, name in enumerate(part_names, 1):
                asset = release_assets.get(name)
                if not asset:
                    raise RuntimeError(f"Release 缺少分片：{name}")
                destination = tmp / name
                self.after(0, lambda i=index, n=name: dlg.set_file(i, n))

                def on_progress(done: int, total: int, _fn: str) -> None:
                    self.after(0, lambda d=done, t=total: dlg.set_progress(d, t))

                dl.download(asset["browser_download_url"], destination, on_progress)
                if part_hashes.get(name) and sha256_file(destination) != part_hashes[name]:
                    raise RuntimeError(f"分片校验失败：{name}")
                downloaded_parts.append(destination)

            archive = tmp / str(parts_payload["archive"])
            with archive.open("wb") as output:
                for part in downloaded_parts:
                    with part.open("rb") as source:
                        shutil.copyfileobj(source, output)
            if archive.stat().st_size != int(parts_payload["size"]) or sha256_file(archive) != parts_payload["sha256"]:
                raise RuntimeError("完整归档校验失败")
            self.after(0, dlg.set_extracting)
            extracted = tmp / "extracted"
            dl.extract(archive, extracted)
            self._apply_update(extracted, runtime_dir(self.cfg))
            write_version(latest)
            self.after(0, lambda: self._ver_label.config(text=f"本地版本：v{latest}"))
            self.after(0, lambda: self._log_msg(f"已安装 v{latest}。"))
        except DownloadCancelled:
            self.after(0, lambda: self._log_msg("已取消安装。"))
        except Exception as exc:
            self.after(0, lambda err=str(exc): self._log_msg(f"安装失败：{err}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.after(0, dlg.close)
            self._update_dlg = None
            self.after(0, self._maybe_auto_start)

    def _do_layer_update(
        self, dlg: UpdateDialog, release: dict, manifest: dict,
        plan: list[str], latest: str,
    ) -> None:
        dl = self._downloader
        assert dl is not None
        tmp = Path(tempfile.mkdtemp(prefix="laf_layer_update_"))
        assets = {asset["name"]: asset for asset in release.get("assets", [])}
        index = 0
        try:
            for layer_name in plan:
                layer = manifest["layers"][layer_name]
                archive_parts = []
                for part in layer["assets"]:
                    index += 1
                    release_asset = assets.get(part["name"])
                    if not release_asset:
                        raise RuntimeError(f"Release 缺少分层资产：{part['name']}")
                    downloaded = tmp / part["name"]
                    self.after(0, lambda i=index, n=part["name"]: dlg.set_file(i, n))

                    def on_progress(done: int, total: int, _fn: str) -> None:
                        self.after(0, lambda d=done, t=total: dlg.set_progress(d, t))

                    dl.download(release_asset["browser_download_url"], downloaded, on_progress)
                    if sha256_file(downloaded) != part["sha256"]:
                        raise RuntimeError(f"下载校验失败：{part['name']}")
                    archive_parts.append(downloaded)
                archive = tmp / layer["archive"]
                if len(archive_parts) == 1:
                    archive = archive_parts[0]
                else:
                    with archive.open("wb") as output:
                        for part_path in archive_parts:
                            with part_path.open("rb") as source:
                                shutil.copyfileobj(source, output)
                if archive.stat().st_size != int(layer["size"]) or sha256_file(archive) != layer["sha256"]:
                    raise RuntimeError(f"分层归档校验失败：{layer_name}")
                self.after(0, dlg.set_extracting)
                extracted = tmp / f"extracted-{layer_name}"
                dl.extract(archive, extracted)
                self._install_layer(layer_name, str(layer["id"]), extracted)

            state = candidate_state(manifest)
            self._validate_candidate(state)
            write_current_state(self.cfg, state)
            write_version(latest)
            self.after(0, lambda: self._ver_label.config(text=f"本地版本：v{latest}"))
            self.after(0, lambda: self._log_msg(f"已更新到 v{latest}。"))
        except DownloadCancelled:
            self.after(0, lambda: self._log_msg("已跳过更新。"))
        except Exception as exc:
            self.after(0, lambda err=str(exc): self._log_msg(f"更新失败：{err}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.after(0, dlg.close)
            self._update_dlg = None
            self.after(0, self._maybe_auto_start)

    def _install_layer(self, layer: str, layer_id: str, extracted: Path) -> None:
        dest = layer_directory(self.cfg, layer, layer_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        staged = dest.with_name(f".{dest.name}.new")
        backup = dest.with_name(f".{dest.name}.old")
        shutil.rmtree(staged, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        shutil.copytree(extracted, staged)
        if dest.exists():
            os.replace(dest, backup)
        try:
            os.replace(staged, dest)
        except Exception:
            if backup.exists() and not dest.exists():
                os.replace(backup, dest)
            raise
        shutil.rmtree(backup, ignore_errors=True)

    def _validate_candidate(self, state: dict) -> None:
        rt = runtime_dir(self.cfg)
        exe = runtime_executable(self.cfg, state)
        if not exe.is_file():
            raise RuntimeError(f"候选 Runtime 缺少入口：{exe.name}")
        candidate = rt / "current.candidate.json"
        candidate.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        env = {
            **os.environ,
            "LAF_RUNTIME_ROOT": str(rt),
            "LAF_RUNTIME_STATE": str(candidate),
            "LAF_DATA_DIR": str(userdata_dir(self.cfg)),
            "LAF_RUNTIME_SELF_TEST": "1",
            "LAF_NO_BROWSER": "1",
        }
        try:
            result = subprocess.run(
                [str(exe)], cwd=str(rt), env=env, capture_output=True, text=True,
                timeout=120, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
            )
        finally:
            candidate.unlink(missing_ok=True)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"候选 Runtime 自检失败：{detail}")

    def _maybe_auto_start(self) -> None:
        """配置 auto_start 且应用未运行时，自动拉起（打开启动器即打开工具）。"""
        if self.cfg.get("auto_start") and primary_action(self.cfg) == "start" and not port_open(self.cfg["port"]) and (
            self._proc is None or self._proc.poll() is not None
        ):
            self._on_start()

    def _start_update(self, release: dict, asset: dict, latest: str) -> None:
        """在主线程弹出进度框，后台线程执行下载。"""
        self._downloader = Downloader()
        dlg = UpdateDialog(self, total_files=1, on_cancel=self._downloader.cancel)
        self._update_dlg = dlg
        threading.Thread(
            target=self._do_update,
            args=(dlg, asset, latest),
            daemon=True,
        ).start()

    def _do_update(self, dlg: UpdateDialog, asset: dict, latest: str) -> None:
        dl = self._downloader
        assert dl is not None
        url  = asset["browser_download_url"]
        name = asset["name"]
        tmp  = Path(tempfile.mkdtemp(prefix="laf_update_"))
        try:
            archive = tmp / name
            dlg.set_file(1, name)

            def on_progress(done: int, total: int, _fn: str) -> None:
                self.after(0, lambda d=done, t=total: dlg.set_progress(d, t))

            dl.download(url, archive, on_progress)
            if dlg.cancelled:
                return
            self.after(0, dlg.set_extracting)
            extract_to = tmp / "extracted"
            dl.extract(archive, extract_to)
            if dlg.cancelled:
                return
            # 覆盖安装 Runtime 到 data/runtime（启动器在根目录，不受影响）
            self._apply_update(extract_to, runtime_dir(self.cfg))
            write_version(latest)
            self.after(0, lambda: self._ver_label.config(text=f"本地版本：v{latest}"))
            self.after(0, lambda: self._log_msg(f"已更新到 v{latest}，重启后生效。"))
        except DownloadCancelled:
            self.after(0, lambda: self._log_msg("已跳过更新。"))
        except Exception as e:
            self.after(0, lambda err=str(e): self._log_msg(f"更新失败：{err}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.after(0, dlg.close)
            self._update_dlg = None
            self.after(0, self._maybe_auto_start)  # 更新完/跳过后自动启动

    def _apply_update(self, src_root: Path, dest: Path) -> None:
        """把解压目录的 Runtime 文件覆盖安装到 dest（data/runtime）。"""
        dest.mkdir(parents=True, exist_ok=True)
        # 找顶层目录（归档通常带一层 ComfyUI-Wrapping-paper-<ver>-<target>/）
        tops = [p for p in src_root.iterdir()]
        base = tops[0] if len(tops) == 1 and tops[0].is_dir() else src_root
        for src_file in base.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(base)
            tgt = dest / rel
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, tgt)


# ── 入口 ─────────────────────────────────────────────────────────────────

def main() -> None:
    app = LauncherApp()
    # Windows：居中显示
    app.update_idletasks()
    sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
    w, h = app.winfo_reqwidth(), app.winfo_reqheight()
    app.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
    app.mainloop()


if __name__ == "__main__":
    main()
