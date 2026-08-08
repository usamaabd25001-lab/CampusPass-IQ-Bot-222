from __future__ import annotations

"""Build a deterministic, Render-focused CampusPass deployment ZIP.

The full repository intentionally keeps historical documentation and validators.
This packager creates a minimal deployable source tree that contains the runtime,
current production gates, migrations, and Render profiles only. It never copies
secrets, tests, examples, caches, or obsolete exact-version validators.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_FILES = (
    ".dockerignore",
    "Dockerfile",
    "VERSION.txt",
    "requirements.txt",
    "pyproject.toml",
    "alembic.ini",
    "render.yaml",
    "render.free.yaml",
    "render.production.yaml",
    "RENDER_VARIABLES.txt",
    "RENDER_FREE_REQUIRED_VARIABLES.example",
    "ENV_ALL_VARIABLES.example",
    "README.md",
    "R4_2_RELEASE_HYGIENE_AR.md",
)
RUNTIME_DIRS = ("app", "ops", "alembic")
SCRIPT_PREFIX_EXCLUDES = (
    "validate_v10_",
    "validate_v11_",
    "verify_phase",
    "verify_v10_",
)
SCRIPT_EXACT_EXCLUDES = {
    "validate_final_ui_authorization_patch.py",
    "verify_project.py",
}


def is_excluded_script(path: Path) -> bool:
    name = path.name
    return name in SCRIPT_EXACT_EXCLUDES or any(name.startswith(prefix) for prefix in SCRIPT_PREFIX_EXCLUDES)


def clean_copy_tree(source: Path, destination: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}:
                ignored.add(name)
            elif name.endswith(".pyc") or name.endswith(".log"):
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, ignore=ignore)


def write_manifest(bundle_root: Path) -> None:
    files: dict[str, dict[str, object]] = {}
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file() or path.name == "DEPLOY_MANIFEST_SHA256.json":
            continue
        raw = path.read_bytes()
        files[str(path.relative_to(bundle_root))] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    payload = {
        "version": (bundle_root / "VERSION.txt").read_text(encoding="utf-8").strip(),
        "file_count": len(files),
        "files": files,
    }
    (bundle_root / "DEPLOY_MANIFEST_SHA256.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build(output: Path) -> Path:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, "-m", "scripts.validate_release_hygiene"],
        cwd=ROOT,
        env=env,
        check=True,
    )

    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    folder_name = f"CampusPass-IQ-{version}"
    with tempfile.TemporaryDirectory(prefix="campuspass-release-") as tmp:
        bundle_root = Path(tmp) / folder_name
        bundle_root.mkdir(parents=True)
        for name in ROOT_FILES:
            source = ROOT / name
            if source.is_file():
                shutil.copy2(source, bundle_root / name)
        for name in RUNTIME_DIRS:
            clean_copy_tree(ROOT / name, bundle_root / name)

        scripts_target = bundle_root / "scripts"
        scripts_target.mkdir()
        for source in sorted((ROOT / "scripts").glob("*.py")):
            if is_excluded_script(source):
                continue
            shutil.copy2(source, scripts_target / source.name)

        write_manifest(bundle_root)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(bundle_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle_root.parent))
    return output


def main() -> None:
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    default = ROOT.parent / f"CampusPass-IQ-{version}-DEPLOY.zip"
    output = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else default.resolve()
    result = build(output)
    print(result)


if __name__ == "__main__":
    main()
