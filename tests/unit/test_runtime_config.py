from __future__ import annotations

from pathlib import Path

import pytest

from medlink_ie.runtime import ConfigError, load_config


def _write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_config_resolves_paths_relative_to_config(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "run.yaml",
        """profile: mvp_deterministic\noffline: true\npaths:\n  run_dir: artifacts/run\n""",
    )

    loaded = load_config(config)

    assert loaded.paths.run_dir == tmp_path / "artifacts" / "run"
    assert loaded.feature_flags.llm is False


def test_load_config_rejects_unknown_keys(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "run.yaml", "offline: true\nunknown: value\n")

    with pytest.raises(ConfigError, match="unknown configuration key: unknown"):
        load_config(config)


def test_load_config_rejects_incompatible_feature_combination(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path / "run.yaml",
        """profile: fast_fallback\noffline: true\nfeature_flags:\n  dense: true\n""",
    )

    with pytest.raises(ConfigError, match="fast_fallback"):
        load_config(config)


def test_load_config_rejects_secret_like_fields_without_echoing_value(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "run.yaml", "offline: true\napi_token: do-not-print-this\n")

    with pytest.raises(ConfigError) as error:
        load_config(config)

    assert "api_token" in str(error.value)
    assert "do-not-print-this" not in str(error.value)
