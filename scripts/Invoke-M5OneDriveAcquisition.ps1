param(
    [ValidateSet("CameraRoll","Screenshots","DesktopPhotos","All")]
    [string]$SourceGroup = "All",

    [ValidateRange(1,1000000)]
    [int]$MaxFiles = 10,

    [ValidateSet("PresentOnly","CloudOnly","All")]
    [string]$StorageMode = "PresentOnly",

    [switch]$Execute
)

# RETIRED HISTORICAL WORKFLOW. This fail-fast guard intentionally precedes all
# path construction and filesystem access. The original workflow targeted the
# retired Z: device and must remain unavailable in the current environment.
# Original recovered script blob before this guard: 2c516e28aa56ebb17728ee3515a50639757a9406
throw "M5_RETIRED_GUARD: This historical acquisition script targets retired storage and must not be executed."

$ErrorActionPreference = "Stop"

$roots = @(
    [PSCustomObject]@{
        Name = "CameraRoll"
        Source = Join-Path $env:USERPROFILE "OneDrive\Pictures\Camera Roll"
        Destination = "Z:\PersonalLibrary\Staging\OneDrive\Pictures\Camera Roll"
    }
    [PSCustomObject]@{
        Name = "Screenshots"
        Source = Join-Path $env:USERPROFILE "OneDrive\Pictures\Screenshots"
        Destination = "Z:\PersonalLibrary\Staging\OneDrive\Pictures\Screenshots"
    }
    [PSCustomObject]@{
        Name = "DesktopPhotos"
        Source = Join-Path $env:USERPROFILE "OneDrive\Desktop\photos"
        Destination = "Z:\PersonalLibrary\Staging\OneDrive\Desktop\photos"
    }
)

$mediaExtensions = @(
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".heic", ".heif", ".bmp", ".tif", ".tiff",
    ".dng", ".raw",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv",
    ".3gp", ".webm"
)

$auditDir = "Z:\PersonalLibrary\Staging\OneDrive\_audit"
[System.IO.Directory]::CreateDirectory($auditDir) | Out-Null

$selectedRoots = if ($SourceGroup -eq "All") {
    @($roots)
}
else {
    @($roots | Where-Object Name -eq $SourceGroup)
}

if ($selectedRoots.Count -eq 0) {
    throw "No matching source root was found."
}

$snapshot = @(
    foreach ($root in $selectedRoots) {
        $sourceBase = $root.Source.TrimEnd("\")

        Get-ChildItem `
            -LiteralPath $sourceBase `
            -Recurse `
            -File `
            -Force `
            -ErrorAction Stop |
        ForEach-Object {
            $file = $_
            $ext = $file.Extension.ToLowerInvariant()

            if ($ext -in $mediaExtensions) {
                $relative = $file.FullName.Substring($sourceBase.Length).TrimStart("\")

                $raw = [int64]$file.Attributes
                $cloudOnly = (
                    (($raw -band 0x00001000) -ne 0) -or
                    (($raw -band 0x00400000) -ne 0)
                )

                [PSCustomObject]@{
                    SourceGroup = $root.Name
                    SourcePath = $file.FullName
                    DestinationPath = Join-Path $root.Destination $relative
                    RelativePath = $relative
                    Bytes = $file.Length
                    AttributesRaw = $raw
                    StorageState = if ($cloudOnly) {
                        "CloudOnly"
                    } else {
                        "PresentOrProviderManaged"
                    }
                    LastWriteTime = $file.LastWriteTime
                }
            }
        }
    }
)

$verifiedDestinations = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)

$priorLogs = @(
    Get-ChildItem `
        -LiteralPath $auditDir `
        -Filter "M5_ACQUISITION_RUN_*.csv" `
        -File `
        -ErrorAction SilentlyContinue
)

foreach ($log in $priorLogs) {
    $rows = @(
        Import-Csv -LiteralPath $log.FullName
    )

    foreach ($row in $rows) {
        if (
            $row.Status -eq "VERIFIED" -and
            -not [string]::IsNullOrWhiteSpace($row.DestinationPath)
        ) {
            [void]$verifiedDestinations.Add($row.DestinationPath)
        }
    }
}

$eligibleSnapshot = @(
    $snapshot |
    Where-Object {
        $row = $_

        if ($StorageMode -eq "PresentOnly") {
            $row.StorageState -eq "PresentOrProviderManaged"
        }
        elseif ($StorageMode -eq "CloudOnly") {
            $row.StorageState -eq "CloudOnly"
        }
        else {
            $true
        }
    }
)

$verifiedComplete = @(
    $eligibleSnapshot |
    Where-Object {
        (Test-Path -LiteralPath $_.DestinationPath) -and
        $verifiedDestinations.Contains($_.DestinationPath)
    }
)

$existingUnverified = @(
    $eligibleSnapshot |
    Where-Object {
        (Test-Path -LiteralPath $_.DestinationPath) -and
        (-not $verifiedDestinations.Contains($_.DestinationPath))
    }
)

$pending = @(
    $eligibleSnapshot |
    Where-Object {
        (-not (Test-Path -LiteralPath $_.DestinationPath)) -or
        (-not $verifiedDestinations.Contains($_.DestinationPath))
    }
)

$work = @($pending | Select-Object -First $MaxFiles)

Write-Host ""
Write-Host "===== M5 ONEDRIVE ACQUISITION =====" -ForegroundColor Cyan

[PSCustomObject]@{
    Mode = if ($Execute) { "EXECUTE" } else { "DRY RUN" }
    SourceGroup = $SourceGroup
    StorageMode = $StorageMode
    SnapshotMediaFiles = $snapshot.Count
    EligibleMediaFiles = $eligibleSnapshot.Count
    VerifiedComplete = $verifiedComplete.Count
    ExistingUnverified = $existingUnverified.Count
    PendingMediaFiles = $pending.Count
    SelectedFiles = $work.Count
    SelectedGB = [math]::Round((($work | Measure-Object Bytes -Sum).Sum / 1GB), 4)
} | Format-List

$work |
    Select-Object SourceGroup, RelativePath, Bytes, AttributesRaw |
    Format-Table -AutoSize

if (-not $Execute) {
    Write-Host "DRY_RUN_ONLY - no files were copied." -ForegroundColor Yellow
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $auditDir "M5_ACQUISITION_RUN_$stamp.csv"

$processedCount = 0

$results = foreach ($row in $work) {
    $processedCount++
    Write-Host (
        "[{0}/{1}] Processing {2}" -f
        $processedCount,
        $work.Count,
        $row.RelativePath
    ) -ForegroundColor DarkGray

    $source = $row.SourcePath
    $dest = $row.DestinationPath
    $destDir = Split-Path -Parent $dest

    $before = Get-Item -LiteralPath $source -Force
    $beforeRaw = [int64]$before.Attributes
    $isZeroByte = ($before.Length -eq 0)
    $wasCloudOnly = (
        (($beforeRaw -band 0x00001000) -ne 0) -or
        (($beforeRaw -band 0x00400000) -ne 0)
    )

    $result = [ordered]@{
        Timestamp = (Get-Date).ToString("o")
        SourceGroup = $row.SourceGroup
        RelativePath = $row.RelativePath
        SourcePath = $source
        DestinationPath = $dest
        Bytes = $before.Length
        ZeroByte = $isZeroByte
        AttributesBefore = $beforeRaw
        Action = ""
        SourceSHA256 = ""
        DestinationSHA256 = ""
        HashMatch = $false
        SourceStillExists = $false
        AttributesAfterRead = ""
        CacheCleanupNeeded = $false
        CacheNote = ""
        AttributesFinal = ""
        Status = ""
        Error = ""
    }

    try {
        [System.IO.Directory]::CreateDirectory($destDir) | Out-Null

        if (Test-Path -LiteralPath $dest) {
            $result.Action = "VerifyExisting"
        }
        else {
            $result.Action = "Copy"

            Copy-Item `
                -LiteralPath $source `
                -Destination $dest `
                -ErrorAction Stop
        }

        $afterRead = Get-Item -LiteralPath $source -Force
        $afterReadRaw = [int64]$afterRead.Attributes
        $result.AttributesAfterRead = $afterReadRaw

        $sourceHash = (
            Get-FileHash -LiteralPath $source -Algorithm SHA256
        ).Hash

        $destHash = (
            Get-FileHash -LiteralPath $dest -Algorithm SHA256
        ).Hash

        $result.SourceSHA256 = $sourceHash
        $result.DestinationSHA256 = $destHash
        $result.HashMatch = ($sourceHash -eq $destHash)

        if (-not $result.HashMatch) {
            throw "SHA-256 mismatch."
        }

        $afterHash = Get-Item -LiteralPath $source -Force
        $afterHashRaw = [int64]$afterHash.Attributes

        $result.CacheCleanupNeeded = (
            $wasCloudOnly -and
            ($afterHashRaw -ne $beforeRaw)
        )

        if ($result.CacheCleanupNeeded) {
            $result.CacheNote = (
                "Verified copy succeeded; OneDrive source cache state " +
                "changed during acquisition. Cache cleanup is deferred."
            )
        }

        $final = Get-Item -LiteralPath $source -Force
        $result.AttributesFinal = [int64]$final.Attributes
        $result.SourceStillExists = Test-Path -LiteralPath $source

        if (-not $result.SourceStillExists) {
            throw "Source file no longer exists."
        }

        $result.Status = "VERIFIED"
    }
    catch {
        $result.Error = $_.Exception.Message
        $result.SourceStillExists = Test-Path -LiteralPath $source

        try {
            if ($result.SourceStillExists) {
                $result.AttributesFinal = [int64](
                    Get-Item -LiteralPath $source -Force
                ).Attributes
            }
        }
        catch {}

        $result.Status = "ERROR"
    }

    $object = [PSCustomObject]$result

    if ($object.Status -eq "VERIFIED") {
        Write-Host (
            "[{0}/{1}] VERIFIED {2}" -f
            $processedCount,
            $work.Count,
            $row.RelativePath
        ) -ForegroundColor Green
    }
    else {
        Write-Host (
            "[{0}/{1}] ERROR {2}: {3}" -f
            $processedCount,
            $work.Count,
            $row.RelativePath,
            $object.Error
        ) -ForegroundColor Red
    }

    $object |
        Export-Csv `
            -LiteralPath $logPath `
            -NoTypeInformation `
            -Encoding UTF8 `
            -Append

    $object
}

Write-Host ""
Write-Host "===== RUN SUMMARY =====" -ForegroundColor Cyan

[PSCustomObject]@{
    FilesProcessed = $results.Count
    Verified = @($results | Where-Object Status -eq "VERIFIED").Count
    Errors = @($results | Where-Object Status -eq "ERROR").Count
    CacheCleanupNeeded = @($results | Where-Object CacheCleanupNeeded).Count
    AuditLog = $logPath
} | Format-List

$results |
    Select-Object `
        SourceGroup,
        RelativePath,
        Action,
        HashMatch,
        CacheCleanupNeeded,
        Status |
    Format-Table -AutoSize

if (@($results | Where-Object Status -eq "ERROR").Count -gt 0) {
    exit 1
}

exit 0
