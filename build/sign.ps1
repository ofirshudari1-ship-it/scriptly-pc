# sign.ps1 - DOCUMENTED TEMPLATE ONLY. Never run automatically by build.ps1 or
# by any AI tool - code signing requires a real private key on a USB token/HSM
# that only the human owner can touch. This script is here so the manual step
# is written down once, not so it gets executed unattended.
#
# Prerequisites (as of 2026):
#   - An EV or OV code-signing certificate on a USB hardware token (private
#     key never leaves the token - required by CA/Browser Forum baseline
#     requirements since 2023 for new certs).
#   - signtool.exe (comes with the Windows SDK).
#   - A timestamp authority - RFC 3161 timestamping means the signature stays
#     valid even after the certificate itself expires (certs are typically
#     issued for up to 458 days as of 2026 policy).
#
# Usage (run manually, token plugged in, after build.ps1 has produced the exe):
#   powershell -ExecutionPolicy Bypass -File build\sign.ps1 -ExePath "Scriptly-PC-Setup-0.10.2.exe"

param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)

$SignTool = "${env:ProgramFiles(x86)}\Windows Kits\10\bin\x64\signtool.exe"
$TimestampUrl = "http://timestamp.digicert.com"  # any RFC 3161 TSA works

if (-not (Test-Path $SignTool)) {
    throw "signtool.exe not found - install the Windows SDK."
}
if (-not (Test-Path $ExePath)) {
    throw "File not found: $ExePath"
}

Write-Host "This will sign $ExePath using the certificate on your connected USB token." -ForegroundColor Yellow
Write-Host "Make sure the token is plugged in and its PIN is ready." -ForegroundColor Yellow
$confirm = Read-Host "Continue? (y/n)"
if ($confirm -ne "y") { exit 0 }

& $SignTool sign /a /fd SHA256 /tr $TimestampUrl /td SHA256 $ExePath

if ($LASTEXITCODE -eq 0) {
    Write-Host "Signed successfully. Verifying..." -ForegroundColor Green
    & $SignTool verify /pa $ExePath
} else {
    throw "Signing failed - check that the token is connected and the PIN was entered correctly."
}
