#requires -Version 5.1
param(
    [string]$OutputDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'output')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Run with Windows PowerShell 5.1 (powershell.exe), which provides the original GDI+ renderer.'
}
Add-Type -AssemblyName System.Drawing
$packageRoot = Split-Path $PSScriptRoot -Parent
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
foreach ($protected in @('assets', 'reference', 'references', 'scripts', 'prompts')) {
    $protectedPath = [IO.Path]::GetFullPath((Join-Path $packageRoot $protected)).TrimEnd('\')
    if ($OutputDir -ieq $protectedPath -or $OutputDir.StartsWith($protectedPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "OutputDir cannot overwrite package inputs: $protectedPath"
    }
}
$fonts = New-Object System.Drawing.Text.InstalledFontCollection
try {
    if (-not (@($fonts.Families | Where-Object Name -CEQ 'Roboto Condensed').Count)) {
        throw 'Required font Roboto Condensed is not installed. Install its Regular, Bold and Italic faces, then restart PowerShell.'
    }
} finally { $fonts.Dispose() }
$family = New-Object System.Drawing.FontFamily('Roboto Condensed')
try {
    foreach ($style in @([Drawing.FontStyle]::Regular, [Drawing.FontStyle]::Bold, [Drawing.FontStyle]::Italic)) {
        if (-not $family.IsStyleAvailable($style)) { throw "Roboto Condensed is missing its $style face." }
    }
} finally { $family.Dispose() }
$manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $packageRoot 'assets-manifest.json') | ConvertFrom-Json
$inputs = @{}
foreach ($role in @('hero', 'logo', 'qr')) {
    $entries = @($manifest.assets | Where-Object role -EQ $role)
    if ($entries.Count -ne 1) { throw "Expected exactly one manifest asset with role '$role'." }
    $path = [IO.Path]::GetFullPath((Join-Path $packageRoot $entries[0].path))
    if (-not $path.StartsWith($packageRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Asset escapes package: $path" }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing $role asset: $path" }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $entries[0].sha256) { throw "Asset hash mismatch: $path" }
    $inputs[$role] = $path
}
$requiredHero = Join-Path $packageRoot 'assets\ChatGPT Image Nov 5, 2026, 11_10_50 AM.png'
if ($inputs.hero -ine [IO.Path]::GetFullPath($requiredHero)) { throw "The selected hero must be $requiredHero" }
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'PosterRenderer.cs'), [Text.Encoding]::UTF8)
if ('PosterRenderer' -as [type]) { throw 'PosterRenderer is already loaded. Start a fresh powershell.exe process to avoid stale source.' }
Add-Type -TypeDefinition $source -ReferencedAssemblies System.Drawing
[IO.Directory]::CreateDirectory($OutputDir) | Out-Null
$stage = Join-Path $OutputDir ('.render-' + [Guid]::NewGuid().ToString('N'))
try {
    [PosterRenderer]::RenderAll($inputs.hero, $inputs.logo, $inputs.qr, $stage)
    $names = [ordered]@{
        'Newtecons-Workshop-AI-NEW-9x16-2160x3840.png' = 'Newtecons-Workshop-AI-MEP-FINAL-9x16-4K-v2.png'
        'Newtecons-Workshop-AI-NEW-16x9-3840x2160.png' = 'Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png'
    }
    foreach ($entry in $names.GetEnumerator()) {
        $destination = Join-Path $OutputDir $entry.Value
        foreach ($asset in $manifest.assets) {
            if ([IO.Path]::GetFullPath((Join-Path $packageRoot $asset.path)) -ieq $destination) { throw "Refusing to overwrite manifest source artifact: $destination" }
        }
        Move-Item -LiteralPath (Join-Path $stage $entry.Key) -Destination $destination -Force
    }
    $auditPath = Join-Path $OutputDir 'layout-audit.json'
    foreach ($asset in $manifest.assets) {
        if ([IO.Path]::GetFullPath((Join-Path $packageRoot $asset.path)) -ieq $auditPath) { throw "Refusing to overwrite manifest source artifact: $auditPath" }
    }
    $audit = ConvertTo-Json -InputObject ([PosterRenderer]::Audit.ToArray()) -Depth 8
    [IO.File]::WriteAllText($auditPath, $audit, (New-Object Text.UTF8Encoding($false)))
    foreach ($name in @($names.Values) + @('layout-audit.json')) {
        Get-Item -LiteralPath (Join-Path $OutputDir $name) | Select-Object FullName, Length
    }
} finally {
    $resolvedStage = [IO.Path]::GetFullPath($stage)
    if (-not $resolvedStage.StartsWith($OutputDir.TrimEnd('\') + '\.render-', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unsafe temporary-directory cleanup: $resolvedStage"
    }
    if (Test-Path -LiteralPath $resolvedStage) { Remove-Item -LiteralPath $resolvedStage -Recurse -Force }
}
