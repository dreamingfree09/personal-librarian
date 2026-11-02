[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
python (Join-Path $PSScriptRoot 'build_release.py') --repository-root $repositoryRoot --build-only
if ($LASTEXITCODE -ne 0) { throw "Controlled Windows build failed with exit code $LASTEXITCODE." }
