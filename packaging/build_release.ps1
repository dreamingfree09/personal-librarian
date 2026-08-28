[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $PSScriptRoot 'build_windows.ps1'
$releaseScript = Join-Path $PSScriptRoot 'build_release.py'

Push-Location -LiteralPath $repositoryRoot
try {
    & $buildScript
    python $releaseScript `
        --repository-root $repositoryRoot `
        --base-source-commit 5cc9cb6
    if ($LASTEXITCODE -ne 0) {
        throw "Release packaging failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
