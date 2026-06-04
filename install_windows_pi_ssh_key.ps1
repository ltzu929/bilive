# Install the Pi public key for Windows OpenSSH administrator logins.

param(
    [string]$PublicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMfvJXQQmFDnxfKMM+sWRHd4x+gUw8W0CaUofGKGFJm1 pi-to-windows-bilive"
)

$ErrorActionPreference = "Stop"

$sshDir = Join-Path $env:ProgramData "ssh"
$authPath = Join-Path $sshDir "administrators_authorized_keys"

New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

if (-not (Test-Path -LiteralPath $authPath)) {
    New-Item -ItemType File -Path $authPath | Out-Null
}

if (-not (Select-String -LiteralPath $authPath -SimpleMatch $PublicKey -Quiet)) {
    Add-Content -LiteralPath $authPath -Value $PublicKey -Encoding ascii
}

icacls.exe $authPath /inheritance:r /grant "*S-1-5-32-544:F" /grant "*S-1-5-18:F" | Out-Null

Write-Host "Installed Pi SSH key:"
Write-Host $authPath
