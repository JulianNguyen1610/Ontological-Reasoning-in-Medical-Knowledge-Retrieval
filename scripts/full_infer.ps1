param(
    [Parameter(Mandatory = $true)][string]$Config
)

$ErrorActionPreference = "Stop"
python -m medlink_ie.cli offline-preflight --config $Config
python -m medlink_ie.cli infer --config $Config
