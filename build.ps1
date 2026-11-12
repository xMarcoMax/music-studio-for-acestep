# Builds dist\Music Studio\Music Studio.exe (PyInstaller --onedir --noconsole) and a desktop shortcut.
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1 [-Zip] [-NoShortcut]
#   -Zip         also create dist\Music-Studio-for-ACE-Step-<version>.zip for a GitHub release (no personal files inside)
#   -NoShortcut  do not create the desktop shortcut
param([switch]$Zip, [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$dist = Join-Path $PSScriptRoot 'dist\Music Studio'
$keep = Join-Path $PSScriptRoot 'build\_keep'
$personal = 'config.json', 'server_info.json', 'logs', 'webview_data'

if (Get-Process -Name 'Music Studio' -ErrorAction SilentlyContinue) {
    throw 'Close Music Studio before building. / Chiudi Music Studio prima di ricostruirlo.'
}

uv sync
uv run python make_icon.py

# Version (from version.py) also embedded in the exe: Properties > Details
$version = (Select-String -Path version.py -Pattern 'VERSION\s*=\s*"(.+)"').Matches[0].Groups[1].Value
$v4 = (($version.Split('.') + @('0', '0', '0', '0'))[0..3] | ForEach-Object { [int]$_ }) -join ', '
New-Item -ItemType Directory -Force build | Out-Null
$versionFile = Join-Path $PSScriptRoot 'build\version_info.txt'
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v4), prodvers=($v4), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Music Studio for ACE-Step contributors'),
      StringStruct('FileDescription', 'Music Studio for ACE-Step'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'Music Studio'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'Music Studio.exe'),
      StringStruct('ProductName', 'Music Studio for ACE-Step'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Encoding utf8 $versionFile

# PyInstaller empties dist\Music Studio: keep the user's config, logs and browser data
if (Test-Path $keep) { Remove-Item $keep -Recurse -Force }
New-Item -ItemType Directory -Force $keep | Out-Null
foreach ($item in $personal) {
    if (Test-Path (Join-Path $dist $item)) { Move-Item (Join-Path $dist $item) $keep }
}

try {
    uv run pyinstaller --noconfirm --clean --noconsole --onedir --name 'Music Studio' `
        --icon assets\icon.ico --version-file $versionFile --add-data "assets;assets" app.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
} finally {
    Get-ChildItem $keep | ForEach-Object { Move-Item $_.FullName $dist -Force }
}

# MCP server, docs and license travel with the executable
Copy-Item mcp (Join-Path $dist 'mcp') -Recurse -Force
Get-ChildItem (Join-Path $dist 'mcp') -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Copy-Item README.md, README.it.md, LICENSE $dist -Force

# Remove a possible "downloaded from the Internet" mark (usually absent for a local build)
Get-ChildItem $dist -Recurse -File | Unblock-File

$exe = Join-Path $dist 'Music Studio.exe'
if (-not $NoShortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $desktop 'Music Studio for ACE-Step.lnk'))
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $dist
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = 'Music Studio for ACE-Step'
    $lnk.Save()
    Write-Host "Shortcut: $(Join-Path $desktop 'Music Studio for ACE-Step.lnk')"
}

if ($Zip) {
    $stage = Join-Path $PSScriptRoot "build\release\Music Studio"
    if (Test-Path (Split-Path $stage)) { Remove-Item (Split-Path $stage) -Recurse -Force }
    Copy-Item $dist $stage -Recurse
    foreach ($item in $personal) { Remove-Item (Join-Path $stage $item) -Recurse -Force -ErrorAction SilentlyContinue }
    $zipPath = Join-Path $PSScriptRoot "dist\Music-Studio-for-ACE-Step-$version.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath }
    Compress-Archive -Path $stage -DestinationPath $zipPath
    Write-Host "Release zip: $zipPath"
}

Write-Host "Done: $exe"
