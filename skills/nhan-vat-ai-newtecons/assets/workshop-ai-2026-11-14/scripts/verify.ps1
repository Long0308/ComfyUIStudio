#requires -Version 5.1
param(
    [string]$OutputDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'output'),
    [switch]$Render
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Run this verifier with Windows PowerShell 5.1 (powershell.exe).'
}
Add-Type -AssemblyName System.Drawing
$packageRoot = Split-Path $PSScriptRoot -Parent
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
function Read-Json([string]$Path) {
    $document = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    # Explicit return enumerates root arrays consistently in Windows PowerShell 5.1.
    return $document
}
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Package-Path([string]$RelativePath) {
    $path = [IO.Path]::GetFullPath((Join-Path $packageRoot $RelativePath))
    Assert-True ($path.StartsWith($packageRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) "Path escapes package: $RelativePath"
    return $path
}
function Image-Size([string]$Path) {
    $image = [Drawing.Image]::FromFile($Path)
    try { return @($image.Width, $image.Height) } finally { $image.Dispose() }
}
function Minutes([string]$Time) {
    Assert-True ($Time -cmatch '^(?:[01][0-9]|2[0-3]):[0-5][0-9]$') "Invalid HH:mm time: $Time"
    return ([int]$Time.Substring(0, 2) * 60 + [int]$Time.Substring(3, 2))
}
function Has-Field($Object, [string]$Field) { return $null -ne $Object.PSObject.Properties[$Field] }

$fonts = New-Object System.Drawing.Text.InstalledFontCollection
try {
    Assert-True (@($fonts.Families | Where-Object Name -CEQ 'Roboto Condensed').Count -gt 0) 'Roboto Condensed is not installed.'
} finally { $fonts.Dispose() }
$family = New-Object System.Drawing.FontFamily('Roboto Condensed')
try {
    foreach ($style in @([Drawing.FontStyle]::Regular, [Drawing.FontStyle]::Bold, [Drawing.FontStyle]::Italic)) {
        Assert-True ($family.IsStyleAvailable($style)) "Roboto Condensed is missing its $style face."
    }
} finally { $family.Dispose() }

# Source artifacts are checked independently of the output folder.
$manifest = Read-Json (Join-Path $packageRoot 'assets-manifest.json')
Assert-True (@($manifest.assets).Count -ge 6) 'The manifest must include all supplied source assets and references.'
foreach ($asset in $manifest.assets) {
    foreach ($field in @('id', 'path', 'width', 'height', 'bytes', 'sha256', 'role')) {
        Assert-True (Has-Field $asset $field) "Asset manifest is missing $field."
    }
    $path = Package-Path $asset.path
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing source artifact: $path"
    Assert-True ((Get-Item -LiteralPath $path).Length -eq $asset.bytes) "Source byte length mismatch: $path"
    Assert-True ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ieq $asset.sha256) "Source SHA256 mismatch: $path"
    $size = Image-Size $path
    Assert-True ($size[0] -eq $asset.width -and $size[1] -eq $asset.height) "Source dimensions mismatch: $path"
}
foreach ($role in @('hero', 'bim_reference', 'portrait_reference', 'landscape_reference', 'logo', 'qr')) {
    Assert-True (@($manifest.assets | Where-Object role -EQ $role).Count -eq 1) "Expected exactly one asset with role $role."
}
Assert-True (@($manifest.assets.id | Select-Object -Unique).Count -eq @($manifest.assets).Count) 'Duplicate asset IDs.'

$promptFiles = @(Get-ChildItem -LiteralPath (Join-Path $packageRoot 'prompts') -Filter '*.json' -File)
Assert-True ($promptFiles.Count -eq 4) 'Exactly four prompt JSON files are required.'
$prompts = @()
foreach ($file in $promptFiles) {
    $prompt = Read-Json $file.FullName
    foreach ($field in @('id', 'subject', 'style', 'composition', 'lighting', 'palette', 'material', 'aspect', 'negative', 'text_content', 'output', 'pipeline')) {
        Assert-True (Has-Field $prompt $field) "Prompt $($file.Name) is missing $field."
        Assert-True (-not [string]::IsNullOrWhiteSpace([string]$prompt.$field)) "Prompt $($file.Name) has empty $field."
    }
    foreach ($field in @('filename', 'width', 'height')) {
        Assert-True (Has-Field $prompt.output $field) "Prompt $($file.Name) output is missing $field."
    }
    Assert-True ($prompt.output.width -gt 0 -and $prompt.output.height -gt 0) "Invalid dimensions in $($file.Name)."
    Assert-True ($prompt.pipeline -cin @('native_poster', 'image_recreation')) "Unknown pipeline in $($file.Name)."
    Assert-True ($prompt.text_content -is [Array]) "text_content must be an array in $($file.Name)."
    foreach ($line in $prompt.text_content) { Assert-True ($line -is [string] -and $line.Length -gt 0) "Invalid text_content in $($file.Name)." }
    $prompts += $prompt
}
Assert-True (@($prompts.id | Select-Object -Unique).Count -eq 4) 'Duplicate prompt IDs.'
$nativePrompts = @($prompts | Where-Object pipeline -CEQ 'native_poster')
Assert-True ($nativePrompts.Count -eq 2) 'Exactly two native poster workflows are required.'
Assert-True (@($nativePrompts.output.filename | Select-Object -Unique).Count -eq 2) 'Native posters must have distinct output filenames.'
Assert-True (@($prompts | Where-Object pipeline -CEQ 'image_recreation').Count -eq 2) 'Exactly two image recreation workflows are required.'

$content = Read-Json (Join-Path $packageRoot 'content.json')
$eventStart = Minutes $content.event.start
$eventEnd = Minutes $content.event.end
Assert-True ($eventEnd -gt $eventStart) 'Event end must follow event start.'
Assert-True (@($content.sections).Count -gt 0) 'The timeline has no sections.'
$cursor = $eventStart
$timedChildren = 0
foreach ($section in $content.sections) {
    $start = Minutes $section.start
    $end = Minutes $section.end
    Assert-True ($start -eq $cursor -and $end -gt $start) "Section $($section.id) has a gap, overlap or invalid interval."
    $children = @($section.children)
    $withTime = @($children | Where-Object { (Has-Field $_ 'start') -or (Has-Field $_ 'end') })
    if ($withTime.Count -gt 0) {
        Assert-True ($withTime.Count -eq $children.Count) "Mixed timed and untimed children in $($section.id)."
        $childCursor = $start
        foreach ($child in $children) {
            Assert-True ((Has-Field $child 'start') -and (Has-Field $child 'end')) "Incomplete child interval in $($section.id)."
            $childStart = Minutes $child.start
            $childEnd = Minutes $child.end
            Assert-True ($childStart -eq $childCursor -and $childEnd -gt $childStart -and $childEnd -le $end) "Child $($child.id) has a gap, overlap or escapes its parent."
            $childCursor = $childEnd
            $timedChildren++
        }
        Assert-True ($childCursor -eq $end) "Children do not cover section $($section.id)."
    } elseif ($children.Count -gt 0) {
        Assert-True ($section.id -ceq 'part2') 'Only part2 has topics without individual times.'
        foreach ($child in $children) { Assert-True (-not [string]::IsNullOrWhiteSpace($child.title)) 'Untimed topic requires a title.' }
    }
    $cursor = $end
}
Assert-True ($cursor -eq $eventEnd) 'Sections do not cover the full event.'

if ($Render) {
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'render.ps1') -OutputDir $OutputDir | Out-Host
    Assert-True ($LASTEXITCODE -eq 0) "Fresh rendering failed with exit code $LASTEXITCODE."
}
$auditPath = Join-Path $OutputDir 'layout-audit.json'
Assert-True (Test-Path -LiteralPath $auditPath -PathType Leaf) 'Missing render audit. Run verify.ps1 -Render to produce fresh outputs.'
$audit = @(Read-Json $auditPath)
Assert-True (@($audit | Select-Object -ExpandProperty Poster -Unique).Count -eq 2) 'Render audit must contain both poster formats.'
$outputResults = @()
foreach ($prompt in $nativePrompts) {
    if ($prompt.output.width -eq 2160 -and $prompt.output.height -eq 3840) {
        $poster = 'portrait-9x16'; $role = 'portrait_reference'; $expectedName = 'Newtecons-Workshop-AI-MEP-FINAL-9x16-4K-v2.png'
    } elseif ($prompt.output.width -eq 3840 -and $prompt.output.height -eq 2160) {
        $poster = 'landscape-16x9'; $role = 'landscape_reference'; $expectedName = 'Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png'
    } else { throw "Unsupported native dimensions: $($prompt.id)" }
    Assert-True ($prompt.output.filename -ceq $expectedName) "Unexpected native output filename: $($prompt.output.filename)"
    $path = Join-Path $OutputDir $expectedName
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing rendered output: $path"
    $size = Image-Size $path
    Assert-True ($size[0] -eq $prompt.output.width -and $size[1] -eq $prompt.output.height) "Rendered dimensions mismatch: $path"
    $reference = @($manifest.assets | Where-Object role -CEQ $role)[0]
    Assert-True ([IO.Path]::GetFullPath($path) -ine (Package-Path $reference.path)) 'Source reference cannot be used as the rendered output.'
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    Assert-True ($hash -ieq $reference.sha256) "Rendered PNG differs from the selected reference: $path"
    $rows = @($audit | Where-Object Poster -CEQ $poster)
    Assert-True ($rows.Count -eq @($prompt.text_content).Count) "Audit/text_content count mismatch for $poster."
    for ($i = 0; $i -lt $rows.Count; $i++) {
        Assert-True ($rows[$i].Text -ceq $prompt.text_content[$i]) "Exact text mismatch at $poster row $i."
        Assert-True ($rows[$i].Fits -eq $true -and $rows[$i].MeasuredWidth -le ($rows[$i].Width + 0.1)) "Measured horizontal text overflow in $poster row $i."
        Assert-True ($rows[$i].Font -ceq 'Roboto Condensed') "Unexpected font in $poster row $i."
    }
    $outputResults += [pscustomobject]@{ filename = $expectedName; width = $size[0]; height = $size[1]; sha256 = $hash; exact_text_rows = $rows.Count; reference_match = $true }
}
[pscustomobject]@{
    status = 'PASS'
    source_artifacts_checked = @($manifest.assets).Count
    prompt_workflows_checked = $prompts.Count
    timeline_sections_checked = @($content.sections).Count
    timed_children_checked = $timedChildren
    output_origin = $(if ($Render) { 'fresh render in this invocation' } else { 'existing output files; no fresh render claimed' })
    outputs = $outputResults
    qr_decoding = 'NOT RUN by this verifier; image/hash preservation is checked, decoding is a separate check.'
    text_fit_scope = 'GDI+ measured horizontal width; no OCR or vertical-glyph-boundary claim.'
} | ConvertTo-Json -Depth 6
