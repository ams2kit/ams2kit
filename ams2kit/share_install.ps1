# Installs or removes a car shared from ams2kit. Written into the share zip by ams2kit/share.py, which fills in
# the car name. Needs only Windows PowerShell (5.1, built into Windows 10/11).
#
#   install.bat                  -> powershell -File install.ps1
#   uninstall.bat                -> powershell -File install.ps1 -Uninstall
#   install.ps1 -GameDir "D:\SteamLibrary\steamapps\common\Automobilista 2"
#
# What it does (the same as ams2kit's Install, docs/safety.md):
# - copies game\* into the game folder, refusing to overwrite any file it did not write itself;
# - adds the car's paks to Pakfiles\PakDirInfo.dat (the game's pak registry; unregistered paks are ignored),
#   after backing the file up once to PakDirInfo.dat.ams2kit-backup;
# - lists every file it wrote in UserData\Mods\<car>\ams2kit-share-files.txt, so uninstall removes exactly those.
param([string]$GameDir = "", [switch]$Uninstall)
$ErrorActionPreference = "Stop"
$Name = "__NAME__"
$Here = $PSScriptRoot

function Find-Game {
    $roots = @()
    foreach ($key in "HKCU:\Software\Valve\Steam", "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam") {
        try {
            $k = Get-ItemProperty $key
            foreach ($v in $k.SteamPath, $k.InstallPath) { if ($v) { $roots += $v } }
        } catch {}
    }
    $roots += "C:\Program Files (x86)\Steam"
    $libs = @()
    foreach ($r in $roots) {
        $libs += $r
        $vdf = Join-Path $r "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"')) {
                $libs += $m.Groups[1].Value.Replace("\\", "\")
            }
        }
    }
    foreach ($l in $libs) {
        $g = Join-Path $l "steamapps\common\Automobilista 2"
        if (Test-Path (Join-Path $g "AMS2AVX.exe")) { return $g }
    }
    return $null
}

function Read-Registry($path) {
    $b = [System.IO.File]::ReadAllBytes($path)
    if ([System.Text.Encoding]::ASCII.GetString($b, 0, 4) -ne "RIDP") { throw "$path is not a pak registry" }
    $n = [BitConverter]::ToUInt32($b, 8)
    $entries = New-Object System.Collections.Generic.List[byte[]]
    for ($i = 0; $i -lt $n; $i++) { $entries.Add($b[(16 + 24 * $i)..(16 + 24 * $i + 23)]) }
    return @{ Head = $b[0..15]; Entries = $entries }
}

function Write-Registry($path, $reg, $add, $remove) {
    $keep = @($reg.Entries | Where-Object { $remove -notcontains [BitConverter]::ToUInt64($_, 0) })
    $all = @($keep) + @($add)
    $out = New-Object System.Collections.Generic.List[byte]
    $out.AddRange([byte[]]$reg.Head)
    foreach ($e in $all) { $out.AddRange([byte[]]$e) }
    $bytes = $out.ToArray()
    [BitConverter]::GetBytes([UInt32]$all.Count).CopyTo($bytes, 8)
    [System.IO.File]::WriteAllBytes($path, $bytes)
}

# our registry entries: one line per pak, "uid meta span orig flags" (written by ams2kit)
$ours = @()
$uids = @()
foreach ($line in Get-Content (Join-Path $Here "registry.txt")) {
    $f = $line.Trim() -split "\s+"
    if ($f.Count -lt 5) { continue }
    $uid = [UInt64]::Parse($f[0])
    $e = New-Object byte[] 24
    [BitConverter]::GetBytes($uid).CopyTo($e, 0)
    for ($i = 1; $i -le 4; $i++) { [BitConverter]::GetBytes([UInt32]::Parse($f[$i])).CopyTo($e, 4 + 4 * $i) }
    $ours += , $e
    $uids += $uid
}

try {
    if (-not $GameDir) { $GameDir = Find-Game }
    if (-not $GameDir) { $GameDir = Read-Host "Automobilista 2 folder (the one with AMS2AVX.exe)" }
    $GameDir = $GameDir.Trim('"')
    if (-not (Test-Path (Join-Path $GameDir "Pakfiles\PakDirInfo.dat"))) { throw "Not an Automobilista 2 folder: $GameDir" }
    if (Get-Process -Name AMS2AVX, AMS2 -ErrorAction SilentlyContinue) { throw "Close Automobilista 2 first." }
    $GameDir = (Resolve-Path $GameDir).Path
    $pdi = Join-Path $GameDir "Pakfiles\PakDirInfo.dat"
    $receipt = Join-Path $GameDir "UserData\Mods\$Name\ams2kit-share-files.txt"
    $old = @()
    if (Test-Path $receipt) { $old = @(Get-Content $receipt) }
    $src = Join-Path $Here "game"
    $files = @(Get-ChildItem -LiteralPath $src -Recurse -File)
    if (-not $Uninstall) {   # check everything before changing anything
        foreach ($s in $files) {
            $dst = Join-Path $GameDir $s.FullName.Substring($src.Length + 1)
            if ((Test-Path -LiteralPath $dst) -and ($old -notcontains $dst)) {
                throw "Refusing to overwrite a file this package didn't install: $dst"
            }
        }
    }

    # remove what an earlier install wrote (also the first step of a reinstall)
    foreach ($f in $old) { if ($f -and (Test-Path -LiteralPath $f)) { Remove-Item -LiteralPath $f -Force } }
    if (Test-Path $receipt) { Remove-Item -LiteralPath $receipt -Force }
    foreach ($f in $old) {
        $d = Split-Path $f -Parent
        while ($d -and $d.Length -gt $GameDir.Length -and (Test-Path -LiteralPath $d) -and -not (Get-ChildItem -LiteralPath $d -Force)) {
            Remove-Item -LiteralPath $d -Force
            $d = Split-Path $d -Parent
        }
    }

    if ($Uninstall) {
        Write-Registry $pdi (Read-Registry $pdi) @() $uids
        if ($old.Count) { Write-Host "Removed $Name ($($old.Count) files) from $GameDir." }
        else { Write-Host "$Name was not installed by this package (nothing to remove), registry entries cleared." }
        exit 0
    }

    if (-not (Test-Path "$pdi.ams2kit-backup")) { Copy-Item -LiteralPath $pdi "$pdi.ams2kit-backup" }
    $written = @()
    foreach ($s in $files) {
        $dst = Join-Path $GameDir $s.FullName.Substring($src.Length + 1)
        New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
        Copy-Item -LiteralPath $s.FullName $dst -Force
        $written += $dst
    }
    Write-Registry $pdi (Read-Registry $pdi) $ours $uids
    New-Item -ItemType Directory -Force -Path (Split-Path $receipt -Parent) | Out-Null
    Set-Content -LiteralPath $receipt -Value $written -Encoding UTF8
    Write-Host "Installed $Name into $GameDir ($($written.Count) files, $($ours.Count) paks registered)."
    Write-Host "Start the game and look for the car in its class. Run uninstall.bat to remove it."
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
