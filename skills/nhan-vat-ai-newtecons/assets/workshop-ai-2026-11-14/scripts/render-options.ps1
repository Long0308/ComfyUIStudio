#requires -Version 5.1
param(
    [string]$OutputDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'output\options')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Run with Windows PowerShell 5.1 (powershell.exe), which provides the original GDI+ renderer.'
}
$packageRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$outputRoot = [IO.Path]::GetFullPath((Join-Path $packageRoot 'output')).TrimEnd('\')
$OutputDir = [IO.Path]::GetFullPath($OutputDir).TrimEnd('\')
if ($OutputDir -ine $outputRoot -and -not $OutputDir.StartsWith($outputRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay inside the package output directory: $outputRoot"
}
# Reject existing links in the output chain, including a linked output root.
$checkPath = $OutputDir
while ($checkPath.Length -gt $packageRoot.Length) {
    if (Test-Path -LiteralPath $checkPath) {
        if ((Get-Item -LiteralPath $checkPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "OutputDir cannot use a linked directory: $checkPath"
        }
    }
    $checkPath = Split-Path $checkPath -Parent
}
Add-Type -AssemblyName System.Drawing
foreach ($fontName in @('Roboto Condensed', 'Arial')) {
    $family = New-Object Drawing.FontFamily($fontName)
    try {
        if ($family.Name -cne $fontName) { throw "Required font is not installed: $fontName" }
        $requiredStyles = @([Drawing.FontStyle]::Regular, [Drawing.FontStyle]::Bold)
        if ($fontName -ceq 'Roboto Condensed') { $requiredStyles += [Drawing.FontStyle]::Italic }
        foreach ($style in $requiredStyles) {
            if (-not $family.IsStyleAvailable($style)) { throw "$fontName is missing its $style face." }
        }
    } finally { $family.Dispose() }
}
$inputs = [ordered]@{
    'styles\editorial-2026-11-05\assets\option-01-natural-site.png' = '960A4A35A4F81D56109E9A144F32AF25AE9DC6D6C227B2F5F21D5FD0C0D2CADF'
    'styles\signature-navy-2026-11-05\assets\option-02-natural-mep.png' = 'ECC926B81DDABC6294CBF68B9C83B2355C2CBE38FA3432655CE6859B39769EF7'
    'assets\newtecons-original-logo.png' = '506685CF632DA0A63D0D3B79920239E2394B30DFF25EFBA7FE2F8E1DDB7F02C5'
    'assets\original-workshop-qr.jpg' = '7FF0C3CA98A1347C3318E90204C89C3EAE58FE3A3402F5D9FE9A0B5C2BBF949A'
}
foreach ($entry in $inputs.GetEnumerator()) {
    $path = Join-Path $packageRoot $entry.Key
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $entry.Value) { throw "Input hash mismatch: $path" }
}
if ('PosterRenderer' -as [type]) { throw 'PosterRenderer is already loaded. Start a fresh powershell.exe process to avoid stale source.' }
$baseSource = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'PosterRenderer.cs'), [Text.Encoding]::UTF8)
$optionSource = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'OptionsRenderer.cs'), [Text.Encoding]::UTF8)
Add-Type -TypeDefinition ($baseSource + [Environment]::NewLine + $optionSource) -ReferencedAssemblies System.Drawing
$expected = [ordered]@{
    'Option-01-Editorial-9x16-4K.png' = 'EA79528E41A95E4B69E27E63B6A7BC1837F157B589A700873A3B4D3D4834C547'
    'Option-01-Editorial-16x9-4K.png' = '81BF848270A616B1CDEC57AC01BD81501C84B0ECCCD8939E812CE7E9A6E86B4F'
    'Option-02-Signature-Navy-9x16-4K.png' = '67043F4178B033464C3E4648FE429AA85B397D3D4F48E0150A1516A51444BFF9'
    'Option-02-Signature-Navy-16x9-4K.png' = '6113F59727B77583ECACD621AB02F196717906C57307BD2C07F2742EEC7CD086'
}
[IO.Directory]::CreateDirectory($OutputDir) | Out-Null
$stage = Join-Path $OutputDir ('.render-' + [Guid]::NewGuid().ToString('N'))
try {
    [PosterRenderer]::RenderOptions(
        (Join-Path $packageRoot 'styles\editorial-2026-11-05\assets\option-01-natural-site.png'),
        (Join-Path $packageRoot 'styles\signature-navy-2026-11-05\assets\option-02-natural-mep.png'),
        (Join-Path $packageRoot 'assets\newtecons-original-logo.png'),
        (Join-Path $packageRoot 'assets\original-workshop-qr.jpg'),
        $stage
    )
    if (@([PosterRenderer]::Audit | Where-Object { -not $_.Fits }).Count -or
        @([PosterRenderer]::OptionBounds | Where-Object { -not $_.FitsCanvas }).Count) {
        throw 'A rendered text-width or canvas-bound record failed.'
    }
    foreach ($entry in $expected.GetEnumerator()) {
        $path = Join-Path $stage $entry.Key
        $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($actualHash -ine $entry.Value) {
            throw "Rendered PNG differs from the archived historical final: $($entry.Key); expected $($entry.Value), actual $actualHash. Check fonts and environment; do not replace archived finals."
        }
    }
    $audit = ConvertTo-Json -InputObject ([PosterRenderer]::Audit.ToArray()) -Depth 8
    $bounds = ConvertTo-Json -InputObject ([PosterRenderer]::OptionBounds.ToArray()) -Depth 8
    [IO.File]::WriteAllText((Join-Path $stage 'options-layout-audit.json'), $audit, (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $stage 'options-canvas-bounds.json'), $bounds, (New-Object Text.UTF8Encoding($false)))
    foreach ($file in Get-ChildItem -LiteralPath $stage -File) {
        Move-Item -LiteralPath $file.FullName -Destination (Join-Path $OutputDir $file.Name) -Force
    }
    Get-ChildItem -LiteralPath $OutputDir -File | Select-Object Name, Length
} finally {
    $resolvedStage = [IO.Path]::GetFullPath($stage)
    if (-not $resolvedStage.StartsWith($OutputDir + '\.render-', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unsafe temporary-directory cleanup: $resolvedStage"
    }
    if (Test-Path -LiteralPath $resolvedStage) { Remove-Item -LiteralPath $resolvedStage -Recurse -Force }
}
