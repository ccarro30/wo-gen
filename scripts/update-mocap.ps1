<#
.SYNOPSIS
    Downloads the motion-capture clips listed in assets\mocap\manifest.json (BVH) at the pinned
    source commit, into assets\mocap\cmu\.

.DESCRIPTION
    1. Reads the manifest: source repo + commit, and clips (name -> file in the repo).
    2. Downloads each listed file that's missing (or every file with -Force) from
       raw.githubusercontent.com at exactly that commit, and checks it's a BVH file.
    3. Removes .bvh files in assets\mocap\cmu\ that the manifest no longer lists.
    4. Records the commit and each file's SHA-256 in assets\mocap\cmu\LOCK. On later runs a file
       whose hash differs from the lock (same commit) is reported and re-downloaded.

    To add a clip: pick it from the source's index file, add a "name": {"file": ...} entry to the
    manifest, and rerun. To move to a newer source commit: change "commit" and rerun with -Force.
    Downloads data only (no software is installed).

.EXAMPLE
    .\scripts\update-mocap.ps1           # fetch whatever is missing (no-op if complete)
.EXAMPLE
    .\scripts\update-mocap.ps1 -Force    # re-download everything (e.g. after changing commit)
#>
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$root     = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content (Join-Path $root 'assets\mocap\manifest.json') -Raw | ConvertFrom-Json
$outDir   = Join-Path $root 'assets\mocap\cmu'
$lockFile = Join-Path $outDir 'LOCK'
$repo     = $manifest.source.repo
$commit   = $manifest.source.commit
if ($commit -notmatch '^[0-9a-f]{40}$') { throw "manifest source.commit must be a full 40-character SHA" }
New-Item -ItemType Directory -Force $outDir | Out-Null

# Previous lock: commit + file hashes.
$locked = @{}
$lockedCommit = $null
if (Test-Path $lockFile) {
    foreach ($line in Get-Content $lockFile) {
        if ($line -match '^commit=(.+)$') { $lockedCommit = $Matches[1].Trim() }
        elseif ($line -match '^([^=\s]+\.bvh)=([0-9a-f]{64})$') { $locked[$Matches[1]] = $Matches[2] }
    }
}
if ($lockedCommit -and $lockedCommit -ne $commit -and -not $Force) {
    Write-Host "Manifest commit changed ($lockedCommit -> $commit): re-downloading all clips."
    $Force = $true
}

$wanted = @{}
$fetched = 0
foreach ($clip in $manifest.clips.PSObject.Properties) {
    $file = $clip.Value.file
    $name = Split-Path $file -Leaf
    $wanted[$name] = $true
    $dest = Join-Path $outDir $name
    $stale = (Test-Path $dest) -and $locked.ContainsKey($name) -and
             ((Get-FileHash $dest -Algorithm SHA256).Hash.ToLower() -ne $locked[$name])
    if ($stale) { Write-Host "  $name changed since the lock; re-downloading" }
    if ($Force -or $stale -or -not (Test-Path $dest)) {
        $url = "https://raw.githubusercontent.com/$repo/$commit/$file"
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        if ((Get-Content $dest -TotalCount 1) -notmatch '^HIERARCHY') {
            Remove-Item $dest -Force
            throw "$url is not a BVH file"
        }
        Write-Host "  fetched $($clip.Name) <- $file"
        $fetched++
    }
}

$removed = 0
foreach ($f in Get-ChildItem $outDir -Filter *.bvh) {
    if (-not $wanted.ContainsKey($f.Name)) { Remove-Item $f.FullName -Force; $removed++; Write-Host "  removed $($f.Name) (not in manifest)" }
}

$lines = @("commit=$commit")
foreach ($name in ($wanted.Keys | Sort-Object)) {
    $lines += "$name=$((Get-FileHash (Join-Path $outDir $name) -Algorithm SHA256).Hash.ToLower())"
}
[IO.File]::WriteAllText($lockFile, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))

Write-Host "Mocap clips: $($wanted.Count) listed, $fetched downloaded, $removed removed (source $repo @ $($commit.Substring(0, 7)))."
