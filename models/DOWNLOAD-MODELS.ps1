<#
  DOWNLOAD-MODELS.ps1 - tai model ComfyUI theo models/model-manifest.csv (khong chua file model trong repo).

  Cach dung:
    .\DOWNLOAD-MODELS.ps1 -BaseDir C:\AI-Models-Fast\2.Model-AI-Local            # tai tat ca dong ComfyUI co URL
    .\DOWNLOAD-MODELS.ps1 -BaseDir D:\Models -Only "minimax_h3","seedvr2"          # loc theo chuoi trong ten file
    .\DOWNLOAD-MODELS.ps1 -BaseDir D:\Models -WhatIf                               # chi liet ke, khong tai

  Quy tac:
    * File dich = <BaseDir>\<relative_path trong CSV>  (vd <BaseDir>\ComfyUI\diffusion_models\xxx.safetensors).
      -> mount <BaseDir>\ComfyUI vao container thanh /opt/ComfyUI/models (xem docker/comfyui/compose.yaml).
    * Da co file dung size + sha256 thi bo qua. Tai vao .part roi doi ten sau khi sha256 khop.
    * Dong VoiceStudio / HuggingFace la repo cache: script chi IN lenh `huggingface-cli download`, khong tu tai.
    * Mot so repo HF co the can dang nhap (`huggingface-cli login`); token KHONG bao gio ghi vao repo.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$BaseDir,
    [string]$Manifest = "",
    [string[]]$Only = @(),
    [switch]$SkipHash
)
$ErrorActionPreference = "Stop"
if (-not $Manifest) { $Manifest = Join-Path $PSScriptRoot "model-manifest.csv" }
if (-not (Test-Path -LiteralPath $Manifest)) { throw "Khong thay manifest: $Manifest" }
$rows = Import-Csv -LiteralPath $Manifest -Encoding UTF8
$ok = 0; $skip = 0; $fail = 0

# `powershell -File x.ps1 -Only "a","b"` binds ONE string "a,b" in Windows PowerShell 5.1: split it.
$Only = @($Only | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().Trim('"').Trim("'") } | Where-Object { $_ })
if ($Only.Count -gt 0) {
    $matched = @($rows | Where-Object { $row = $_; $Only | Where-Object { $row.file_or_repo -like "*$_*" } })
    if ($matched.Count -eq 0) { throw "-Only khong khop dong nao trong manifest: $($Only -join ', ')" }
    Write-Host "-Only khop $($matched.Count) dong: $(($matched | ForEach-Object { Split-Path $_.file_or_repo -Leaf }) -join ', ')"
}

foreach ($r in $rows) {
    if ($Only.Count -gt 0 -and -not ($Only | Where-Object { $r.file_or_repo -like "*$_*" })) { continue }

    if ($r.app -ne "ComfyUI") {
        if ($r.repo_or_url -and $r.revision) {
            Write-Host "[HF-REPO] huggingface-cli download $($r.repo_or_url) --revision $($r.revision)   # $($r.app)/$($r.type)"
        } elseif ($r.repo_or_url) {
            Write-Host "[HF-REPO] huggingface-cli download $($r.repo_or_url)   # $($r.app)/$($r.type)"
        }
        continue
    }
    if (-not $r.url) { Write-Warning "Khong co URL (nguon chua xac minh): $($r.relative_path)"; continue }
    $target = Join-Path $BaseDir ($r.relative_path -replace '/', '\')
    $size = [long]$r.size_bytes

    if (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target
        if ($item.Length -eq $size) {
            if ($SkipHash -or -not $r.sha256) { Write-Host "[SKIP] $($r.relative_path) (dung size)"; $skip++; continue }
            $h = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower()
            if ($h -eq $r.sha256.ToLower()) { Write-Host "[SKIP] $($r.relative_path) (sha256 khop)"; $skip++; continue }
            Write-Warning "sha256 lech, tai lai: $($r.relative_path)"
        }
    }
    if (-not $PSCmdlet.ShouldProcess($target, "Tai $($r.url) ($([math]::Round($size/1GB,2)) GB)")) { continue }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    $part = "$target.part"
    try {
        # curl.exe co san tren Windows 10/11, ho tro resume (-C -) va follow redirect (-L).
        & curl.exe -L --fail --retry 5 -C - -o $part $r.url
        if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE" }
        if ((Get-Item -LiteralPath $part).Length -ne $size) { throw "sai size (cho $size)" }
        if (-not $SkipHash -and $r.sha256) {
            $h = (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLower()
            if ($h -ne $r.sha256.ToLower()) { throw "sha256 khong khop ($h)" }
        }
        Move-Item -LiteralPath $part -Destination $target -Force
        Write-Host "[OK]   $($r.relative_path)"; $ok++
    } catch {
        Write-Warning "[FAIL] $($r.relative_path): $_"; $fail++
    }
}
Write-Host "Xong: tai=$ok, bo qua=$skip, loi=$fail"
if ($fail -gt 0) { exit 1 }
