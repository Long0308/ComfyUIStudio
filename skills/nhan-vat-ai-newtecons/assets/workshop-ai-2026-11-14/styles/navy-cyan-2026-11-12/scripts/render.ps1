#requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$HeroPath,
    [string]$OutputDir = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Run with Windows PowerShell 5.1 (powershell.exe), which provides the native GDI+ renderer.'
}
Add-Type -AssemblyName System.Drawing
$styleRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$packageRoot = [IO.Path]::GetFullPath((Join-Path $styleRoot '..\..'))
$HeroPath = [IO.Path]::GetFullPath($HeroPath)
if ([string]::IsNullOrWhiteSpace($OutputDir)) { $OutputDir = Join-Path $styleRoot 'output' }
$OutputDir = [IO.Path]::GetFullPath($OutputDir).TrimEnd('\')
if (-not (Test-Path -LiteralPath $HeroPath -PathType Leaf)) { throw "Missing hero: $HeroPath" }
if (-not $OutputDir.StartsWith($styleRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDir must be a child of this style directory; original package outputs are protected.'
}
foreach ($protected in @('scripts','assets','references','prompts')) {
    $protectedPath = Join-Path $styleRoot $protected
    if ($OutputDir -ieq $protectedPath -or $OutputDir.StartsWith($protectedPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "OutputDir is protected: $protectedPath" }
}
$family = New-Object Drawing.FontFamily('Roboto Condensed')
try {
    if ($family.Name -cne 'Roboto Condensed') { throw 'Required font Roboto Condensed is not installed.' }
    foreach ($face in @([Drawing.FontStyle]::Regular,[Drawing.FontStyle]::Bold,[Drawing.FontStyle]::Italic)) {
        if (-not $family.IsStyleAvailable($face)) { throw "Roboto Condensed is missing $face." }
    }
} finally { $family.Dispose() }
$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $packageRoot 'assets-manifest.json') | ConvertFrom-Json
$inputs = @{}
foreach ($role in @('logo','qr')) {
    $entries = @($manifest.assets | Where-Object role -EQ $role)
    if ($entries.Count -ne 1) { throw "Expected one manifest asset for $role." }
    $assetPath = [IO.Path]::GetFullPath((Join-Path $packageRoot $entries[0].path))
    $assetsRoot = [IO.Path]::GetFullPath((Join-Path $packageRoot 'assets')).TrimEnd('\')
    if (-not $assetPath.StartsWith($assetsRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Asset escapes package assets: $assetPath" }
    if ((Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash -ine $entries[0].sha256) { throw "Authentic $role asset hash mismatch: $assetPath" }
    $inputs[$role] = $assetPath
}
if ('PosterRenderer' -as [type]) { throw 'Start a fresh powershell.exe process to avoid stale renderer source.' }
$sources = @((Join-Path $packageRoot 'scripts\PosterRenderer.cs'),(Join-Path $PSScriptRoot 'NavyCyanRenderer.cs'))
Add-Type -Path $sources -ReferencedAssemblies System.Drawing
$names = @('Newtecons-Workshop-AI-Navy-Cyan-9x16-4K.png','Newtecons-Workshop-AI-Navy-Cyan-16x9-4K.png','layout-audit.json')
foreach ($name in $names) {
    if (Test-Path -LiteralPath (Join-Path $OutputDir $name)) { throw "Refusing to overwrite an existing render: $name. Choose a fresh OutputDir." }
}
[IO.Directory]::CreateDirectory($OutputDir) | Out-Null
$stage = Join-Path $OutputDir ('.render-' + [Guid]::NewGuid().ToString('N'))
try {
    [PosterRenderer]::RenderNavyCyan($HeroPath,$inputs.logo,$inputs.qr,$stage)
    $audit = [ordered]@{
        Style = 'navy-cyan-2026-11-12'
        Hero = [ordered]@{ Path = $HeroPath; Sha256 = (Get-FileHash -LiteralPath $HeroPath -Algorithm SHA256).Hash }
        AuthenticAssets = $inputs
        Text = @([PosterRenderer]::Audit.ToArray())
        Bounds = @([PosterRenderer]::NavyCyanBounds.ToArray())
        Images = @([PosterRenderer]::NavyCyanImages.ToArray())
    }
    [IO.File]::WriteAllText((Join-Path $stage 'layout-audit.json'),(ConvertTo-Json -InputObject $audit -Depth 10),(New-Object Text.UTF8Encoding($false)))
    foreach ($name in $names) { Move-Item -LiteralPath (Join-Path $stage $name) -Destination (Join-Path $OutputDir $name) }
    foreach ($name in $names) { Get-Item -LiteralPath (Join-Path $OutputDir $name) | Select-Object FullName,Length }
} finally {
    $resolvedStage = [IO.Path]::GetFullPath($stage)
    if (-not $resolvedStage.StartsWith($OutputDir.TrimEnd('\') + '\.render-', [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe temporary path: $resolvedStage" }
    if (Test-Path -LiteralPath $resolvedStage) { Remove-Item -LiteralPath $resolvedStage -Recurse -Force }
}
