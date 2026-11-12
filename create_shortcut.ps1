# Creates a desktop shortcut that starts Music Studio for ACE-Step from source with pythonw.exe (no console),
# with the app icon. Use it when Windows Smart App Control blocks the unsigned Music Studio.exe.
# Usage (in the repository folder):  powershell -ExecutionPolicy Bypass -File create_shortcut.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

uv sync
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found in .venv: run 'uv sync' first." }

$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop 'Music Studio for ACE-Step.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($link)
$lnk.TargetPath = $pythonw
$lnk.Arguments = '"' + (Join-Path $PSScriptRoot 'app.py') + '"'
$lnk.WorkingDirectory = $PSScriptRoot
$lnk.IconLocation = (Join-Path $PSScriptRoot 'assets\icon.ico') + ',0'
$lnk.Description = 'Music Studio for ACE-Step'
$lnk.Save()
Write-Host "Shortcut: $link"
Write-Host "The app started this way uses config.json and logs\ in this folder."
