param(
    [ValidateSet("clean-dir", "container")][string]$Mode = "clean-dir",
    [string]$Image = "medlink-ie:offline"
)

$ErrorActionPreference = "Stop"
if ($Mode -eq "container") {
  docker build -t $Image .
  if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }
  docker run --rm --network none `
    -v "${PWD}/data:/workspace/data:ro" `
    -v "${PWD}/artifacts:/workspace/artifacts:ro" `
    -v "${PWD}/examples/smoke:/workspace/examples/smoke" `
    $Image offline-preflight --config /workspace/examples/smoke/config.yaml
  if ($LASTEXITCODE -ne 0) { throw "Container preflight failed" }
  docker run --rm --network none `
    -v "${PWD}/data:/workspace/data:ro" `
    -v "${PWD}/artifacts:/workspace/artifacts:ro" `
    -v "${PWD}/examples/smoke:/workspace/examples/smoke" `
    $Image infer --config /workspace/examples/smoke/config.yaml
  if ($LASTEXITCODE -ne 0) { throw "Container inference failed" }
  exit 0
}

$CleanRoot = Join-Path ([IO.Path]::GetTempPath()) "medlink-ie-reproduce-$([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $CleanRoot | Out-Null
Copy-Item -Recurse -Path "$PWD/src", "$PWD/specs", "$PWD/examples" -Destination $CleanRoot
New-Item -ItemType Junction -Path (Join-Path $CleanRoot "data") -Target (Join-Path $PWD "data") | Out-Null
New-Item -ItemType Junction -Path (Join-Path $CleanRoot "artifacts") -Target (Join-Path $PWD "artifacts") | Out-Null
$env:PYTHONPATH = Join-Path $CleanRoot "src"
Push-Location $CleanRoot
try {
  python -m medlink_ie.cli offline-preflight --config examples/smoke/config.yaml
  if ($LASTEXITCODE -ne 0) { throw "Clean-directory preflight failed" }
  python -m medlink_ie.cli infer --config examples/smoke/config.yaml
  if ($LASTEXITCODE -ne 0) { throw "Clean-directory inference failed" }
  @'
from hashlib import sha256
from pathlib import Path
import yaml

expected = yaml.safe_load(Path("examples/smoke/expected_hashes.yaml").read_text(encoding="utf-8"))["outputs"]
for name, digest in expected.items():
    actual = sha256((Path("examples/smoke/run/output") / name).read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f"smoke hash mismatch for {name}")
print("clean-directory reproduction verified")
'@ | python -
  if ($LASTEXITCODE -ne 0) { throw "Clean-directory smoke verification failed" }
} finally {
  Pop-Location
}
Write-Output "Clean reproduction directory: $CleanRoot"
