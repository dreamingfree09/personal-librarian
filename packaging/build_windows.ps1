[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$specPath = Join-Path $PSScriptRoot 'personal_librarian.spec'

Push-Location -LiteralPath $repositoryRoot
try {
    python -m PyInstaller --clean --noconfirm $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
    $executable = Join-Path $repositoryRoot 'dist\PersonalLibrarian\PersonalLibrarian.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Expected packaged executable was not created: $executable"
    }
    Write-Output "PACKAGED_EXECUTABLE=$executable"
}
finally {
    Pop-Location
}
