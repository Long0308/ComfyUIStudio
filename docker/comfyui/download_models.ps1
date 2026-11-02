param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("flux1-dev-fp8", "flux1-turbo-alpha", "zimage-turbo", "zimage-vae")]
    [string]$Name
)

$ErrorActionPreference = "Stop"

$comfyRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\ComfyUI"))
$downloadRoot = Join-Path $PSScriptRoot "downloads"
$logRoot = Join-Path $downloadRoot "logs"
$receiptRoot = Join-Path $downloadRoot "receipts"
$pidRoot = Join-Path $downloadRoot "pids"

foreach ($directory in @($downloadRoot, $logRoot, $receiptRoot, $pidRoot)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$artifacts = @{
    "flux1-dev-fp8" = @{
        RelativePath = "models\checkpoints\flux1-dev-fp8.safetensors"
        Size = [long]17246524772
        Sha256 = "8e91b68084b53a7fc44ed2a3756d821e355ac1a7b6fe29be760c1db532f3d88a"
        Url = "https://huggingface.co/Comfy-Org/Flux-1-Dev/resolve/83c446ef27a6ac1e9e36ecf13257283aa12cf22a/flux1-dev-fp8.safetensors"
    }
    "flux1-turbo-alpha" = @{
        RelativePath = "models\loras\flux1_turbo_alpha.safetensors"
        Size = [long]694082424
        Sha256 = "77f7523a5e9c3da6cfc730c6b07461129fa52997ea06168e9ed5312228aa0bff"
        Url = "https://huggingface.co/alimama-creative/FLUX.1-Turbo-Alpha/resolve/7b29bf041b413949089d78b826a5c9726e3c8e50/diffusion_pytorch_model.safetensors"
    }
    "zimage-turbo" = @{
        RelativePath = "models\diffusion_models\z_image_turbo_int8_convrot.safetensors"
        Size = [long]6201001296
        Sha256 = "be517ebd47c912a5626a588e1aeea43e6be4a43c0cdcd2b48a2a780d9f358635"
        Url = "https://huggingface.co/Comfy-Org/Z-Image-Turbo/resolve/main/split_files/diffusion_models/z_image_turbo_int8_convrot.safetensors"
    }
    "zimage-vae" = @{
        RelativePath = "models\vae\ae.safetensors"
        Size = [long]335304388
        Sha256 = "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"
        Url = "https://huggingface.co/Comfy-Org/Z-Image-Turbo/resolve/main/split_files/vae/ae.safetensors"
    }
}

$artifact = $artifacts[$Name]
$target = [System.IO.Path]::GetFullPath((Join-Path $comfyRoot $artifact.RelativePath))
$part = "$target.part"
$logPath = Join-Path $logRoot "$Name.log"
$receiptPath = Join-Path $receiptRoot "$Name.json"
$pidPath = Join-Path $pidRoot "$Name.pid"

function Write-Log([string]$Message) {
    $line = "{0:o} {1}" -f [DateTimeOffset]::UtcNow, $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
}

function Write-Receipt([string]$State, [string]$ActualSha256, [string]$Message) {
    $receipt = [ordered]@{
        name = $Name
        state = $State
        url = $artifact.Url
        target = $target
        expected_size = $artifact.Size
        expected_sha256 = $artifact.Sha256
        actual_size = if (Test-Path -LiteralPath $target) { (Get-Item -LiteralPath $target).Length } else { $null }
        actual_sha256 = $ActualSha256
        message = $Message
        updated_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding utf8
}

if (Test-Path -LiteralPath $pidPath) {
    $existingPid = Get-Content -LiteralPath $pidPath -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue)) {
        Write-Log "Worker already active for $Name with PID $existingPid."
        exit 0
    }
}

$PID | Set-Content -LiteralPath $pidPath -Encoding ascii
try {
    $targetDirectory = Split-Path -Parent $target
    New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null

    if (Test-Path -LiteralPath $target) {
        $targetSize = (Get-Item -LiteralPath $target).Length
        if ($targetSize -ne $artifact.Size) {
            throw "Existing target has size $targetSize, expected $($artifact.Size); refusing to overwrite."
        }
        Write-Log "Target exists with expected size. Calculating SHA256."
        $actualSha = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -ne $artifact.Sha256) {
            throw "Existing target SHA256 $actualSha does not match expected $($artifact.Sha256); refusing to overwrite."
        }
        Write-Receipt "verified-existing" $actualSha "Existing artifact verified."
        Write-Log "Artifact already complete and verified."
        exit 0
    }

    $partialSize = if (Test-Path -LiteralPath $part) { (Get-Item -LiteralPath $part).Length } else { 0L }
    if ($partialSize -gt $artifact.Size) {
        throw "Partial size $partialSize exceeds expected $($artifact.Size); preserving it for inspection."
    }

    Write-Log "Download starting or resuming. URL: $($artifact.Url). Partial bytes: $partialSize."
    Write-Receipt "downloading" $null "Download in progress. Partial bytes: $partialSize."

    & curl.exe `
        --fail `
        --location `
        --retry 8 `
        --retry-delay 5 `
        --retry-all-errors `
        --connect-timeout 30 `
        --continue-at - `
        --output $part `
        $artifact.Url 2>&1 | ForEach-Object { Write-Log ([string]$_) }
    if ($LASTEXITCODE -ne 0) {
        throw "curl.exe exited with code $LASTEXITCODE."
    }

    $completedSize = (Get-Item -LiteralPath $part).Length
    if ($completedSize -ne $artifact.Size) {
        throw "Downloaded size $completedSize does not match expected $($artifact.Size)."
    }

    Write-Log "Size matches. Calculating SHA256 for the completed partial file."
    $actualSha = (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha -ne $artifact.Sha256) {
        throw "Downloaded SHA256 $actualSha does not match expected $($artifact.Sha256); partial file preserved."
    }

    if (Test-Path -LiteralPath $target) {
        throw "Target appeared while downloading; refusing to overwrite."
    }
    Move-Item -LiteralPath $part -Destination $target
    Write-Receipt "verified" $actualSha "Download completed, size and SHA256 verified."
    Write-Log "Verified and promoted artifact to target."
} catch {
    Write-Receipt "failed" $null $_.Exception.Message
    Write-Log "FAILED: $($_.Exception.Message)"
    throw
} finally {
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}
