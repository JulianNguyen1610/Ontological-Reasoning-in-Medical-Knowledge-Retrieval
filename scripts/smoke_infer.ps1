param(
    [string]$Config = "examples/smoke/config.yaml"
)

$ErrorActionPreference = "Stop"
python -m medlink_ie.cli offline-preflight --config $Config
python -m medlink_ie.cli infer --config $Config
@'
from hashlib import sha256
from pathlib import Path
import yaml

expected = yaml.safe_load(Path("examples/smoke/expected_hashes.yaml").read_text(encoding="utf-8"))["outputs"]
for name, digest in expected.items():
    actual = sha256((Path("examples/smoke/run/output") / name).read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f"smoke hash mismatch for {name}")
print("smoke inference verified")
'@ | python -
