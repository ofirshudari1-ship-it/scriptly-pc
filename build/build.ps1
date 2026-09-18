# build.ps1 - builds Scriptly PC end to end: exe (PyInstaller) + installer (Inno Setup).
# Run from anywhere; paths below are relative to this script's own location.
#
# Usage:  powershell -ExecutionPolicy Bypass -File build\build.ps1
#
# Reads version.json at the project root as the single source of truth for the
# version number, and passes it into the .iss via /D so the installer filename
# and AppVersion never drift from app/config.py (which also reads version.json).

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Push-Location $ProjectRoot
try {
    $Version = (Get-Content "version.json" | ConvertFrom-Json).version
    Write-Host "=== Building Scriptly PC v$Version ===" -ForegroundColor Cyan

    # --- 1. Python dependencies (into the existing venv, or create one) ---
    if (-not (Test-Path "venv")) {
        Write-Host "Creating virtual environment..." -ForegroundColor Yellow
        python -m venv venv
    }
    & ".\venv\Scripts\pip.exe" install -q -r "build\requirements.txt"
    & ".\venv\Scripts\pip.exe" install -q -r "build\requirements-dev.txt"

    # --- 2. Smoke tests - fail fast before spending minutes on a bad build ---
    Write-Host "Running smoke tests..." -ForegroundColor Yellow
    & ".\venv\Scripts\python.exe" -m unittest discover tests
    if ($LASTEXITCODE -ne 0) { throw "Smoke tests failed - aborting build." }

    # --- 3. Regenerate branded assets (icons + installer wizard banner) ---
    # Cheap and deterministic - always regenerate rather than trust stale .bmp/.ico
    # files left over from a previous version's palette.
    Write-Host "Regenerating icons and installer banner..." -ForegroundColor Yellow
    & ".\venv\Scripts\python.exe" "build\generate_icons.py"
    & ".\venv\Scripts\python.exe" "build\generate_installer_banner.py"

    # --- 4. PyInstaller: exe ---
    Write-Host "Building executable (PyInstaller)..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "dist", "build\pyinstaller_work" -ErrorAction SilentlyContinue
    # NOTE: --specpath build changes the base that PyInstaller resolves *relative*
    # --icon/--add-data paths against (to build\, not the project root) - this bit
    # us for real the first time build.ps1 was actually run end-to-end (it had
    # never been exercised before, only written from a template). Absolute paths
    # sidestep the ambiguity entirely.
    & ".\venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed --onedir `
        --name "Scriptly PC" `
        --distpath "dist" `
        --workpath "build\pyinstaller_work" `
        --specpath "build" `
        --icon "$ProjectRoot\assets\icon_idle.ico" `
        --add-data "$ProjectRoot\assets;assets" `
        --add-data "$ProjectRoot\locales;locales" `
        --add-data "$ProjectRoot\version.json;." `
        --collect-all faster_whisper `
        --collect-all ctranslate2 `
        --collect-all pyaudiowpatch `
        --collect-all pystray `
        --collect-all customtkinter `
        --collect-all darkdetect `
        --collect-all docx `
        --collect-all google_auth_oauthlib `
        --collect-all googleapiclient `
        --collect-all google.auth `
        --collect-binaries nvidia.cublas `
        --collect-binaries nvidia.cudnn `
        --hidden-import keyboard `
        run.pyw
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    # --- 5. Custom PyQt6 installer wizard (output goes straight to project root) ---
    # Replaces Inno Setup as of v0.13.0 (see CHANGELOG): Inno's wizard pages
    # always render native Windows button chrome no matter how the bitmaps are
    # branded, which doesn't meet the "genuinely custom-styled, brand-colored
    # controls" bar. build_installer.py compiles a PyQt6 wizard (dark navy/
    # teal theme, Fusion style so QSS actually applies) into a small installer
    # exe that bundles/copies the onedir app payload built in step 4.
    Write-Host "Building installer (custom PyQt6 wizard)..." -ForegroundColor Yellow
    & ".\venv\Scripts\python.exe" "build\build_installer.py"
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }

    # --- 6. Cleanup intermediate build output (keep only source + final exe) ---
    Remove-Item -Recurse -Force "dist", "build\pyinstaller_work" -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Host "=== Build complete: Scriptly-PC-Setup-$Version.exe ===" -ForegroundColor Green
} finally {
    Pop-Location
}
