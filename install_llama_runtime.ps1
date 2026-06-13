param(
    [string]$LlamaCppVersion = "b9616",
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$runtimeRoot = Join-Path $ProjectDir ".runtime\llama.cpp"
$targetDir = Join-Path $runtimeRoot $LlamaCppVersion
$serverPath = Join-Path $targetDir "llama-server.exe"

if ((Test-Path -LiteralPath $serverPath) -and -not $Force) {
    Write-Host "llama.cpp runtime already installed: $serverPath"
    exit 0
}

$expectedRoot = [IO.Path]::GetFullPath((Join-Path $ProjectDir ".runtime"))
$resolvedTarget = [IO.Path]::GetFullPath($targetDir)
if (-not $resolvedTarget.StartsWith($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to install runtime outside project .runtime directory"
}

$releaseBase = (
    "https://github.com/ggml-org/llama.cpp/releases/download/" +
    $LlamaCppVersion
)
$binaryName = "llama-$LlamaCppVersion-bin-win-cuda-12.4-x64.zip"
$cudaName = "cudart-llama-bin-win-cuda-12.4-x64.zip"
$binaryUrl = "$releaseBase/$binaryName"
$cudaUrl = "$releaseBase/$cudaName"

$tempDir = Join-Path (
    [IO.Path]::GetTempPath()
) ("bilive-llama-" + [Guid]::NewGuid().ToString("N"))
$binaryZip = Join-Path $tempDir "llama.zip"
$cudaZip = Join-Path $tempDir "cuda.zip"
$binaryExtract = Join-Path $tempDir "llama"
$cudaExtract = Join-Path $tempDir "cuda"
$stagingDir = Join-Path $runtimeRoot (".$LlamaCppVersion.staging")

New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

try {
    Invoke-WebRequest -Uri $binaryUrl -OutFile $binaryZip
    Invoke-WebRequest -Uri $cudaUrl -OutFile $cudaZip
    Expand-Archive -LiteralPath $binaryZip -DestinationPath $binaryExtract -Force
    Expand-Archive -LiteralPath $cudaZip -DestinationPath $cudaExtract -Force

    if (Test-Path -LiteralPath $stagingDir) {
        Remove-Item -LiteralPath $stagingDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
    Get-ChildItem -LiteralPath $binaryExtract -Force |
        Copy-Item -Destination $stagingDir -Recurse -Force
    Get-ChildItem -LiteralPath $cudaExtract -Force |
        Copy-Item -Destination $stagingDir -Recurse -Force

    $stagedServer = Get-ChildItem `
        -LiteralPath $stagingDir `
        -Filter "llama-server.exe" `
        -File `
        -Recurse |
        Select-Object -First 1
    if (-not $stagedServer) {
        throw "Downloaded runtime does not contain llama-server.exe"
    }
    if ($stagedServer.DirectoryName -ne $stagingDir) {
        Get-ChildItem -LiteralPath $stagedServer.DirectoryName -Force |
            Copy-Item -Destination $stagingDir -Recurse -Force
    }
    $stagedCudaDll = Get-ChildItem `
        -LiteralPath $stagingDir `
        -Filter "cudart64_12.dll" `
        -File `
        -Recurse |
        Select-Object -First 1
    if (-not $stagedCudaDll) {
        throw "Downloaded CUDA runtime does not contain cudart64_12.dll"
    }
    if ($stagedCudaDll.DirectoryName -ne $stagingDir) {
        Get-ChildItem -LiteralPath $stagedCudaDll.DirectoryName -Force |
            Copy-Item -Destination $stagingDir -Recurse -Force
    }

    & (Join-Path $stagingDir "llama-server.exe") --version
    if ($LASTEXITCODE -ne 0) {
        throw "Downloaded llama-server.exe failed its version check"
    }

    if (Test-Path -LiteralPath $targetDir) {
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }
    Move-Item -LiteralPath $stagingDir -Destination $targetDir
} finally {
    if (Test-Path -LiteralPath $stagingDir) {
        Remove-Item -LiteralPath $stagingDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $tempDir) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}

Write-Host "llama.cpp runtime ready: $serverPath"
