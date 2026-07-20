"""发布前置校验：确保离线依赖和主题资产闭包可被 release archive 收集。"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


_CSS_ASSET = re.compile(
    r"url\(\s*[\"']?/(backgrounds|controls|ornaments|support|textures)/([^\"')\s]+)"
)
_SUPPORTED_PYTHON_VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")


def _normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_names(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if not value or value.startswith(("-", "git+", "http:")):
            continue
        names.append(re.split(r"[<>=!~;\[]", value, maxsplit=1)[0].strip())
    return names


def missing_vendor_distributions(requirements: Path, vendor_dir: Path) -> list[str]:
    wheel_dists = {
        _normalize_dist(path.name.split("-", 1)[0])
        for path in vendor_dir.glob("*.whl")
    }
    return [
        name for name in requirement_names(requirements)
        if _normalize_dist(name) not in wheel_dists
    ]


def css_asset_references(css_path: Path) -> set[Path]:
    refs: set[Path] = set()
    for category, relative in _CSS_ASSET.findall(css_path.read_text(encoding="utf-8")):
        refs.add(Path(category) / relative)
    return refs


def missing_css_assets(css_path: Path, public_dir: Path) -> list[str]:
    return sorted(
        str(reference).replace("\\", "/")
        for reference in css_asset_references(css_path)
        if not (public_dir / reference).is_file()
    )


def theme_targets(manifest_dir: Path) -> set[Path]:
    targets: set[Path] = set()
    for manifest in sorted(manifest_dir.glob("*.json")):
        plan = json.loads(manifest.read_text(encoding="utf-8"))
        for step in plan.get("steps", []):
            target = step.get("target")
            if isinstance(target, str):
                targets.add(Path(target))
    return targets


def missing_theme_outputs(manifest_dir: Path, public_dir: Path) -> list[str]:
    return sorted(
        str(target).replace("\\", "/")
        for target in theme_targets(manifest_dir)
        if not (public_dir / target).is_file()
    )


def ignored_release_paths(root: Path, paths: set[Path]) -> list[str]:
    relative_paths = sorted(
        str(path.relative_to(root)).replace("\\", "/") for path in paths
    )
    if not relative_paths:
        return []
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin"],
        input="\n".join(relative_paths),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git check-ignore 执行失败")
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def offline_dependency_error(root: Path, python_executable: str = sys.executable) -> str | None:
    failures: list[str] = []
    for version in _SUPPORTED_PYTHON_VERSIONS:
        result = subprocess.run(
            [
                python_executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--no-index",
                "--only-binary=:all:",
                "--platform",
                "win_amd64",
                "--implementation",
                "cp",
                "--python-version",
                version,
                "--find-links",
                str(root / "vendor" / "pip"),
                "-r",
                str(root / "backend" / "requirements.txt"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            failures.append(f"Python {version}: {detail}")
    if failures:
        return "基础 vendor 离线依赖树无法解析：" + "；".join(failures)
    return None


def offline_npm_dependency_error(root: Path) -> str | None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        return "未找到 npm，无法校验前端离线依赖"
    result = subprocess.run(
        [
            npm,
            "ci",
            "--dry-run",
            "--offline",
            "--cache",
            str(root / "vendor" / "npm"),
        ],
        cwd=root / "frontend",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    detail = result.stderr.strip() or result.stdout.strip()
    return "前端 vendor/npm 离线依赖树无法解析：" + detail


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    requirements = root / "backend" / "requirements.txt"
    vendor_dir = root / "vendor" / "pip"
    css_path = root / "frontend" / "src" / "styles.css"
    public_dir = root / "frontend" / "public"
    manifest_dir = root / "scripts" / "theme_assets"

    missing = missing_vendor_distributions(requirements, vendor_dir)
    if missing:
        errors.append("vendor/pip 缺少基础依赖 wheel：" + "、".join(missing))

    missing = missing_css_assets(css_path, public_dir)
    if missing:
        errors.append("CSS 引用了不存在的主题素材：" + "、".join(missing))

    missing = missing_theme_outputs(manifest_dir, public_dir)
    if missing:
        errors.append("主题清单产物未生成：" + "、".join(missing))

    release_assets = {
        public_dir / path
        for path in css_asset_references(css_path) | theme_targets(manifest_dir)
    }
    ignored = ignored_release_paths(root, release_assets)
    if ignored:
        errors.append("主题素材被 Git 忽略，无法进入发布包：" + "、".join(ignored))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate(root)
    dependency_error = offline_dependency_error(root)
    if dependency_error:
        errors.append(dependency_error)
    npm_error = offline_npm_dependency_error(root)
    if npm_error:
        errors.append(npm_error)
    if errors:
        for error in errors:
            print("ERROR: " + error)
        return 1
    print("发布前置校验通过：pip/npm 离线依赖树、CSS 主题素材和主题清单产物均完整。")
    print("可选 sentence-transformers/Reranker 依赖与模型权重不在基础发布包内。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
