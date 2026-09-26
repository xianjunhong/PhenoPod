[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$pythonCommand = Get-Command python -ErrorAction Stop
& $pythonCommand.Source -m PyInstaller --noconfirm --clean PhenoPod_onedir.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($isccCommand) {
        $iscc = $isccCommand.Source
    }
}
if (-not $iscc) {
    throw "Inno Setup 6 compiler (ISCC.exe) was not found"
}

& $iscc PhenoPod_Setup.iss
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed with exit code $LASTEXITCODE"
}

$issText = Get-Content -LiteralPath (Join-Path $projectRoot "PhenoPod_Setup.iss") -Raw
$versionMatch = [regex]::Match($issText, '#define\s+AppVersion\s+"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "Unable to read AppVersion from PhenoPod_Setup.iss"
}

$version = $versionMatch.Groups[1].Value
$installerDir = Join-Path $projectRoot "dist\installer"
$installerName = "PhenoPod_Setup_$version.exe"
$installerPath = Join-Path $installerDir $installerName
if (-not (Test-Path -LiteralPath $installerPath)) {
    throw "Installer was not generated: $installerPath"
}

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash
$hashPath = Join-Path $installerDir "PhenoPod_Setup_${version}_SHA256.txt"
Set-Content -LiteralPath $hashPath -Encoding ascii -Value "SHA256  $hash  $installerName"

Write-Host "Setup package: $installerPath"
Write-Host "SHA256:       $hash"
Write-Host "Checksum file: $hashPath"
