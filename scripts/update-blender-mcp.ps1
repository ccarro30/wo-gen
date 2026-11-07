<#
.SYNOPSIS
    Pins MCP for Blender (PyPI: mcp-for-blender) to one version for both the MCP server and the Blender add-on.

.DESCRIPTION
    1. Downloads the wheel for -Version from PyPI and verifies its SHA-256 against PyPI's metadata.
    2. Extracts the Blender add-on (the .py file declaring bl_info) to blender\addons\blender_mcp.py.
    3. Rewrites the pinned version in .mcp.json (mcp-for-blender@X.Y.Z).
    4. Records the version and hashes in blender\addons\blender_mcp.VERSION.

    Afterwards: restart Blender (or disable and re-enable the add-on) and restart Claude Code.

    With no arguments, it pins the newest release on PyPI and exits early if that's already pinned.

.EXAMPLE
    .\scripts\update-blender-mcp.ps1                  # update to latest (no-op if current)
.EXAMPLE
    .\scripts\update-blender-mcp.ps1 -Version 2.2.6   # pin a specific version / roll back
.EXAMPLE
    .\scripts\update-blender-mcp.ps1 -Force           # re-extract even if already current
#>
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root      = Split-Path -Parent $PSScriptRoot
$addonDir  = Join-Path $root 'blender\addons'
$addonPath = Join-Path $addonDir 'blender_mcp.py'
$verFile   = Join-Path $addonDir 'blender_mcp.VERSION'
$mcpJson   = Join-Path $root '.mcp.json'

if (-not $Version) {
    $Version = (Invoke-RestMethod 'https://pypi.org/pypi/mcp-for-blender/json').info.version
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Unexpected latest version string from PyPI: '$Version'" }
}

$current = $null
if (Test-Path $verFile) {
    $line = Select-String -Path $verFile -Pattern '^version=(.+)$' | Select-Object -First 1
    if ($line) { $current = $line.Matches[0].Groups[1].Value.Trim() }
}
if ($current -eq $Version -and (Test-Path $addonPath) -and -not $Force) {
    Write-Host "mcp-for-blender $Version is already pinned. Nothing to do."
    return
}
Write-Host "Updating mcp-for-blender: $(if ($current) { $current } else { '(none)' }) -> $Version"

$cacheDir  = Join-Path $root ".cache\mcp-for-blender\$Version"

# 1. Resolve and download the wheel.
$meta  = Invoke-RestMethod "https://pypi.org/pypi/mcp-for-blender/$Version/json"
$wheel = $meta.urls | Where-Object { $_.packagetype -eq 'bdist_wheel' } | Select-Object -First 1
if (-not $wheel) { throw "No wheel published for mcp-for-blender $Version" }

New-Item -ItemType Directory -Force $cacheDir | Out-Null
$whlPath = Join-Path $cacheDir $wheel.filename
if (-not (Test-Path $whlPath)) {
    Invoke-WebRequest -Uri $wheel.url -OutFile $whlPath -UseBasicParsing
}
$actual = (Get-FileHash $whlPath -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $wheel.digests.sha256) {
    Remove-Item $whlPath -Force
    throw "SHA-256 mismatch for $($wheel.filename): expected $($wheel.digests.sha256), got $actual"
}

# 2. Extract and locate the add-on (the only module declaring bl_info).
$extractDir = Join-Path $cacheDir 'wheel'
if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
$zipCopy = Join-Path $cacheDir 'wheel.zip'   # Expand-Archive in PS 5.1 requires a .zip extension
Copy-Item $whlPath $zipCopy -Force
Expand-Archive -Path $zipCopy -DestinationPath $extractDir
Remove-Item $zipCopy -Force

$candidates = Get-ChildItem $extractDir -Recurse -Filter *.py |
    Where-Object { Select-String -Path $_.FullName -Pattern '^\s*bl_info\s*=' -Quiet }
if (@($candidates).Count -ne 1) {
    $names = ($candidates | ForEach-Object { $_.FullName.Substring($extractDir.Length + 1) }) -join ', '
    throw "Expected exactly one add-on file (bl_info) in the wheel, found $(@($candidates).Count): $names"
}
$addonSrc = @($candidates)[0]

New-Item -ItemType Directory -Force $addonDir | Out-Null
Copy-Item $addonSrc.FullName $addonPath -Force

# 3. Pin the server version in .mcp.json.
$json = Get-Content $mcpJson -Raw
$pinPattern = 'mcp-for-blender@\d+\.\d+\.\d+'
if ($json -notmatch $pinPattern) { throw ".mcp.json has no 'mcp-for-blender@X.Y.Z' pin to update" }
$json = $json -replace $pinPattern, "mcp-for-blender@$Version"
[IO.File]::WriteAllText($mcpJson, $json, (New-Object Text.UTF8Encoding $false))

# 4. Record provenance.
$addonHash = (Get-FileHash $addonPath -Algorithm SHA256).Hash.ToLower()
$record = @(
    "version=$Version"
    "wheel=$($wheel.filename)"
    "wheel_sha256=$($wheel.digests.sha256)"
    "addon_source=$($addonSrc.FullName.Substring($extractDir.Length + 1))"
    "addon_sha256=$addonHash"
) -join "`n"
[IO.File]::WriteAllText($verFile, "$record`n", (New-Object Text.UTF8Encoding $false))

Write-Host "Pinned mcp-for-blender $Version"
Write-Host "  add-on : $addonPath  (from $($addonSrc.Name))"
Write-Host "  server : .mcp.json -> uvx mcp-for-blender@$Version"
Write-Host 'Restart Blender and Claude Code to pick up the new version.'
