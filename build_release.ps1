$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SpecPath = Join-Path $ProjectRoot "Smart_File_Organizer_Pro.spec"
$DistDir = Join-Path $ProjectRoot "dist"
$ReleaseDir = Join-Path $ProjectRoot "release"
$PortableDir = Join-Path $ReleaseDir "Smart_File_Organizer_Pro_Portable"
$ExePath = Join-Path $DistDir "Smart_File_Organizer_Pro.exe"
$ZipPath = Join-Path $ReleaseDir "Smart_File_Organizer_Pro_Portable_v1.0.1.zip"

Write-Host "Cleaning previous release artifacts..."
if (Test-Path $PortableDir) { Remove-Item -Recurse -Force $PortableDir }
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }

Write-Host "Building executable with PyInstaller..."
python -m PyInstaller --noconfirm --clean $SpecPath

if (-not (Test-Path $ExePath)) {
    throw "Build failed. Executable not found at $ExePath"
}

Write-Host "Preparing portable release folder..."
New-Item -ItemType Directory -Force -Path $PortableDir | Out-Null
Copy-Item $ExePath $PortableDir
Copy-Item (Join-Path $ProjectRoot "assets\\smart_file_organizer_pro.ico") $PortableDir
Copy-Item (Join-Path $ProjectRoot "RELEASE_NOTES.md") $PortableDir

Write-Host "Creating ZIP package..."
Compress-Archive -Path (Join-Path $PortableDir "*") -DestinationPath $ZipPath -Force

Write-Host "Release build complete."
Write-Host "Portable folder: $PortableDir"
Write-Host "ZIP package: $ZipPath"
