from __future__ import annotations

from pathlib import Path

from medlink_ie.cli import main


def test_validate_config_writes_redacted_resolved_artifact(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """profile: mvp_deterministic\noffline: true\npaths:\n  run_dir: artifacts/demo\n""",
        encoding="utf-8",
    )

    assert main(["validate-config", "--config", str(config)]) == 0
    assert (tmp_path / "artifacts" / "demo" / "resolved_config.json").is_file()


def test_cli_returns_config_exit_code_for_bad_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("offline: false\n", encoding="utf-8")

    assert main(["validate-config", "--config", str(config)]) == 3


def test_infer_one_file_writes_submission_shaped_output(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("No entities in this test.", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        """profile: fast\noffline: true\npaths:\n  input: note.txt\n  run_dir: artifacts/demo\n""",
        encoding="utf-8",
    )

    assert main(["infer", "--config", str(config)]) == 0
    assert (tmp_path / "artifacts" / "demo" / "output" / "note.json").read_text(
        encoding="utf-8"
    ) == "[]"


def test_offline_preflight_writes_reports_without_network(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"artifact")
    from hashlib import sha256

    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(
        f"""schema_version: 1
artifacts:
  - name: fixture
    path: artifact.bin
    size_bytes: 8
    sha256: {sha256(b"artifact").hexdigest()}
    license: test
    required: true
""",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text(
        """offline: true
paths:
  run_dir: run
artifacts:
  inventory: inventory.yaml
""",
        encoding="utf-8",
    )

    assert main(["offline-preflight", "--config", str(config)]) == 0
    assert (tmp_path / "run" / "offline_preflight.json").is_file()
    assert (tmp_path / "run" / "environment.json").is_file()
