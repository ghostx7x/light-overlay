$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$source = "D:\Tools\LibreHardwareMonitor-win"
$vendor = Join-Path $PSScriptRoot "vendor\LibreHardwareMonitor"
if (-not (Test-Path (Join-Path $source "LibreHardwareMonitor.exe"))) {
    throw "LibreHardwareMonitor.exe was not found at $source"
}

if (Test-Path $vendor) {
    Remove-Item $vendor -Recurse -Force
}
New-Item -ItemType Directory -Path $vendor | Out-Null

Get-ChildItem $source -Force | Where-Object {
    $_.Extension -notin ".pdb", ".xml" -and $_.Name -ne "LibreHardwareMonitor.config"
} | ForEach-Object {
    Copy-Item $_.FullName -Destination (Join-Path $vendor $_.Name) -Recurse -Force
}

@'
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="runWebServerMenuItem" value="true" />
    <add key="startMinMenuItem" value="true" />
    <add key="minTrayMenuItem" value="true" />
    <add key="minCloseMenuItem" value="true" />
    <add key="listenerIp" value="127.0.0.1" />
    <add key="listenerPort" value="8085" />
  </appSettings>
</configuration>
'@ | Set-Content -Encoding utf8 (Join-Path $vendor "LibreHardwareMonitor.config")

python make_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name LightOverlay --icon "assets\lightoverlay.ico" --add-data "vendor\LibreHardwareMonitor;LibreHardwareMonitor" --add-data "assets\lightoverlay.ico;." overlay.py
