from __future__ import annotations

"""Release-hygiene gate for the deployable CampusPass source tree.

This validator is intentionally stdlib-only. It protects against the failures
that are easy to introduce when a large, long-lived repository carries old
release material next to current runtime code: release metadata drift, a code
release being incorrectly forced to have a database migration, Python
file/package name collisions, cache artifacts, and aggressive/conflicting
Render Free settings.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"RELEASE HYGIENE VALIDATION FAILED: {message}")


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def literal_version() -> str:
    tree = ast.parse(read("app/__init__.py"), filename="app/__init__.py")
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    fail("app.__version__ must remain a literal string for release tooling")
    raise AssertionError


def semver_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?", value.strip())
    if not match:
        fail(f"invalid release identifier: {value!r}")
    return tuple(int(part) for part in match.groups())


def env_value(document: str, key: str) -> str | None:
    pattern = re.compile(
        rf"^\s*-\s+key:\s*{re.escape(key)}\s*$\n\s+value:\s*[\"']?([^\"'\n#]+)",
        re.MULTILINE,
    )
    match = pattern.search(document)
    return match.group(1).strip() if match else None


def check_versions() -> tuple[str, str]:
    version_file = read("VERSION.txt").strip()
    app_version = literal_version()
    if version_file != app_version:
        fail(f"VERSION.txt={version_file!r} does not match app={app_version!r}")
    semver_tuple(app_version)

    migrations = read("app/db/migrations.py")
    versions = re.findall(r'Migration\(\s*version="([^"]+)"', migrations)
    if not versions:
        fail("could not discover custom migration versions")
    if len(versions) != len(set(versions)):
        fail("duplicate custom migration versions")
    tuples = [semver_tuple(value) for value in versions]
    if any(left > right for left, right in zip(tuples, tuples[1:])):
        fail("custom migrations are not ordered by release")
    if tuples[-1] > semver_tuple(app_version):
        fail(f"schema head {versions[-1]!r} is newer than application {app_version!r}")
    return app_version, versions[-1]


def check_python_collisions() -> None:
    app_root = ROOT / "app"
    collisions: list[str] = []
    for directory in app_root.rglob("*"):
        if directory.is_dir() and (directory.parent / f"{directory.name}.py").is_file():
            collisions.append(str(directory.relative_to(ROOT)))
    if collisions:
        fail("Python file/package name collisions: " + ", ".join(collisions[:20]))


def check_generated_artifacts() -> None:
    bad: list[str] = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part == ".git" for part in rel.parts):
            continue
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}:
            bad.append(str(rel))
        elif path.is_file() and path.suffix == ".pyc":
            bad.append(str(rel))
    if bad:
        fail("generated cache artifacts are present: " + ", ".join(bad[:20]))


def check_docker_quarantine() -> None:
    dockerignore = read(".dockerignore")
    required = (
        "docs/",
        "examples/",
        "tests/",
        "tests_legacy/",
        "loadtests/",
        "windows_tools/",
        "scripts/validate_v10_*.py",
        "scripts/validate_v11_*.py",
        "scripts/verify_phase*.py",
    )
    for marker in required:
        if marker not in dockerignore:
            fail(f".dockerignore is not quarantining legacy/non-runtime material: {marker}")


def check_render_free_profiles() -> None:
    profiles = {
        "render.yaml": read("render.yaml"),
        "render.free.yaml": read("render.free.yaml"),
    }
    expected = {
        "DB_POOL_SIZE": "3",
        "DB_MAX_OVERFLOW": "2",
        "TELEGRAM_UPDATE_CONSUMERS": "2",
        "BOT_UPDATE_CONCURRENCY": "8",
        "TELEGRAM_HTTP_CONNECTION_LIMIT": "16",
        "UVICORN_LIMIT_CONCURRENCY": "50",
        "UVICORN_BACKLOG": "128",
        "UVICORN_TIMEOUT_KEEP_ALIVE": "5",
        "AI_CONCURRENCY_LIMIT": "1",
        "REPORT_CONCURRENCY_LIMIT": "1",
        "LONG_OPERATION_CONCURRENCY_LIMIT": "2",
    }
    for name, source in profiles.items():
        if "plan: free" not in source:
            fail(f"{name} is not the free profile")
        if not re.search(r"^\s*region:\s*frankfurt(?:\s*(?:#.*)?)?$", source, re.MULTILINE):
            fail(f"{name} must use Render Blueprint region 'frankfurt'")
        if "value: combined" not in source:
            fail(f"{name} must run the free service in combined mode")
        env_keys = re.findall(r"^\s*-\s+key:\s*([A-Z0-9_]+)\s*$", source, re.MULTILINE)
        duplicates = sorted({key for key in env_keys if env_keys.count(key) > 1})
        if duplicates:
            fail(f"{name} contains duplicate environment keys: {', '.join(duplicates)}")
        for key, wanted in expected.items():
            actual = env_value(source, key)
            if actual != wanted:
                fail(f"{name} {key}={actual!r}; expected conservative free-tier value {wanted!r}")


def check_manual_render_profile() -> None:
    source = read("RENDER_VARIABLES.txt")
    expected_lines = {
        "RUNTIME_MODE": "combined",
        "REQUIRE_REDIS_IN_PRODUCTION": "false",
        "DB_POOL_SIZE": "3",
        "DB_MAX_OVERFLOW": "2",
        "TELEGRAM_UPDATE_CONSUMERS": "2",
        "BOT_UPDATE_CONCURRENCY": "8",
        "TELEGRAM_HTTP_CONNECTION_LIMIT": "16",
        "UVICORN_LIMIT_CONCURRENCY": "50",
        "AI_CONCURRENCY_LIMIT": "1",
        "REPORT_CONCURRENCY_LIMIT": "1",
        "LONG_OPERATION_CONCURRENCY_LIMIT": "2",
        "FEATURE_MASTERCARD": "false",
        "FEATURE_PROVIDER_WITHDRAWALS": "false",
    }
    values: dict[str, str] = {}
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            fail(f"RENDER_VARIABLES.txt contains duplicate key {key}")
        values[key] = value
    for key, wanted in expected_lines.items():
        if values.get(key) != wanted:
            fail(f"RENDER_VARIABLES.txt {key}={values.get(key)!r}; expected {wanted!r}")


def check_historical_test_quarantine() -> None:
    current_tests = ROOT / "tests"
    stale_v10 = sorted(path.name for path in current_tests.glob("test_v10_*.py"))
    if stale_v10:
        fail("historical V10 tests must live under tests_legacy/: " + ", ".join(stale_v10))


def check_docker_gate() -> None:
    dockerfile = read("Dockerfile")
    marker = "python -m scripts.validate_release_hygiene"
    if marker not in dockerfile:
        fail("Dockerfile is not running the release-hygiene gate")


def main() -> None:
    app_version, schema_head = check_versions()
    check_python_collisions()
    check_generated_artifacts()
    check_docker_quarantine()
    check_render_free_profiles()
    check_manual_render_profile()
    check_historical_test_quarantine()
    check_docker_gate()
    print(f"Release hygiene validation passed: app={app_version}, schema_head={schema_head}")


if __name__ == "__main__":
    main()
