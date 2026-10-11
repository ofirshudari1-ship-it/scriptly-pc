# build.ps1 - builds Scriptly PC end to end: exe (PyInstaller) + custom PyQt6
# installer wizard (build_installer.py - Inno Setup was replaced in v0.13.0).
# Run from anywhere; paths below are relative to this script's own location.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File build\build.ps1              # CPU-only, ~250MB (default)
#   powershell -ExecutionPolicy Bypass -File build\build.ps1 -IncludeGPU  # + CUDA/cuDNN, ~2GB
#
# The CPU build is the default because most users don't have a compatible
# NVIDIA GPU, and bundling ~1.8GB of CUDA/cuDNN DLLs into every download
# regardless was the actual root cause of "why is this installer 2GB"
# (see CHANGELOG). The app already falls back to CPU/int8 automatically if
# CUDA isn't available (app/transcribe.py) - CPU-only is fully functional,
# just slower per-recording, not a crippled build.
#
# Reads version.json at the project root as the single source of truth for the
# version number, and passes it into build_installer.py so the installer
# filename and displayed AppVersion never drift from app/config.py (which also
# reads version.json).

param(
    [switch]$IncludeGPU
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Push-Location $ProjectRoot
try {
    $Version = (Get-Content "version.json" | ConvertFrom-Json).version
    $BuildLabel = if ($IncludeGPU) { "v$Version (GPU)" } else { "v$Version (CPU-only)" }
    Write-Host "=== Building Scriptly PC $BuildLabel ===" -ForegroundColor Cyan

    # --- 1. Python dependencies (into the existing venv, or create one) ---
    if (-not (Test-Path "venv")) {
        Write-Host "Creating virtual environment..." -ForegroundColor Yellow
        python -m venv venv
    }
    & ".\venv\Scripts\pip.exe" install -q -r "build\requirements.txt"
    & ".\venv\Scripts\pip.exe" install -q -r "build\requirements-dev.txt"
    if ($IncludeGPU) {
        Write-Host "Installing GPU (CUDA/cuDNN) dependencies (~1.8GB download)..." -ForegroundColor Yellow
        & ".\venv\Scripts\pip.exe" install -q -r "build\requirements-gpu.txt"
    }

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
    $PyInstallerArgs = @(
        "--noconfirm", "--windowed", "--onedir",
        "--name", "Scriptly PC",
        "--distpath", "dist",
        "--workpath", "build\pyinstaller_work",
        "--specpath", "build",
        "--icon", "$ProjectRoot\assets\icon_idle.ico",
        "--add-data", "$ProjectRoot\assets;assets",
        "--add-data", "$ProjectRoot\locales;locales",
        "--add-data", "$ProjectRoot\version.json;.",
        "--collect-all", "faster_whisper",
        "--collect-all", "ctranslate2",
        "--collect-all", "pyaudiowpatch",
        "--collect-all", "pystray",
        "--collect-all", "customtkinter",
        "--collect-all", "darkdetect",
        "--collect-all", "docx",
        "--collect-all", "google_auth_oauthlib",
        "--collect-all", "googleapiclient",
        "--collect-all", "google.auth",
        "--hidden-import", "keyboard"
    )
    if ($IncludeGPU) {
        # These two flags alone are what pulled ~1.8GB of CUDA/cuDNN DLLs into
        # every installer regardless of -IncludeGPU, before this switch existed.
        $PyInstallerArgs += @("--collect-binaries", "nvidia.cublas", "--collect-binaries", "nvidia.cudnn")
    }
    $PyInstallerArgs += "run.pyw"

    & ".\venv\Scripts\python.exe" -m PyInstaller @PyInstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    # --- 5. Custom PyQt6 installer wizard (output goes straight to project root) ---
    # Replaces Inno Setup as of v0.13.0 (see CHANGELOG): Inno's wizard pages
    # always render native Windows button chrome no matter how the bitmaps are
    # branded, which doesn't meet the "genuinely custom-styled, brand-colored
    # controls" bar. build_installer.py compiles a PyQt6 wizard (dark navy/
    # teal theme, Fusion style so QSS actually applies) into a small installer
    # exe that bundles/copies the onedir app payload built in step 4.
    Write-Host "Building installer (custom PyQt6 wizard)..." -ForegroundColor Yellow
    $env:SCRIPTLY_BUILD_VARIANT = if ($IncludeGPU) { "gpu" } else { "cpu" }
    & ".\venv\Scripts\python.exe" "build\build_installer.py"
    $BuildInstallerExitCode = $LASTEXITCODE
    Remove-Item Env:\SCRIPTLY_BUILD_VARIANT -ErrorAction SilentlyContinue
    if ($BuildInstallerExitCode -ne 0) { throw "Installer build failed." }

    # --- 6. Cleanup intermediate build output (keep only source + final exe) ---
    Remove-Item -Recurse -Force "dist", "build\pyinstaller_work" -ErrorAction SilentlyContinue

    $OutputSuffix = if ($IncludeGPU) { "-gpu" } else { "" }
    Write-Host ""
    Write-Host "=== Build complete: Scriptly-PC-Setup-$Version$OutputSuffix.exe ===" -ForegroundColor Green
} finally {
    Pop-Location
}
