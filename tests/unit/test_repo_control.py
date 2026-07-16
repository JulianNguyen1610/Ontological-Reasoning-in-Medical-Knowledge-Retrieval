from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_development_tooling_is_declared_and_configured() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]
    assert {dependency.split(">=")[0] for dependency in dev_dependencies} >= {
        "ruff",
        "mypy",
        "pytest",
    }
    assert "tool" in pyproject
    assert {"ruff", "mypy", "pytest"} <= set(pyproject["tool"])


def test_make_and_ci_use_the_same_local_quality_commands() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")

    for target in ("format-check", "lint", "typecheck", "test"):
        assert f"{target}:" in makefile
        assert f"make {target}" in workflow
