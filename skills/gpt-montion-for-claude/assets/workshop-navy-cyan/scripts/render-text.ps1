#requires -Version 5.1
param([string]$OutputDir)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSEdition -ne 'Desktop') { throw 'Use a fresh Windows PowerShell 5.1 process.' }
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
if (-not $OutputDir) { $OutputDir = Join-Path $root 'assets\text' }
$OutputDir = [IO.Path]::GetFullPath($OutputDir).TrimEnd('\')
$allowedRoots = @((Join-Path $root 'assets\text'), (Join-Path $root 'evidence\text-rerender'))
if ($OutputDir -notin $allowedRoots) { throw 'OutputDir must be assets/text or evidence/text-rerender inside this package.' }
$check = $OutputDir
while ($check.Length -gt $root.Length) {
    if ((Test-Path -LiteralPath $check) -and ((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Linked output paths are not permitted.' }
    $check = Split-Path $check -Parent
}
$manifestPath = Join-Path $root 'text-content.json'
$spec = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$canonicalPath = Join-Path $root 'references\workshop-content.json'
$canonical = Get-Content -LiteralPath $canonicalPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (@($spec.assets.id | Select-Object -Unique).Count -ne $spec.assets.Count) { throw 'Duplicate text asset IDs.' }
if ((Get-FileHash -LiteralPath $canonicalPath -Algorithm SHA256).Hash -ine $spec.canonicalSha256) { throw 'Canonical source hash differs from manifest.' }
$opening = @($canonical.sections | Where-Object { $_.id -eq 'opening' })[0]
$part1 = @($canonical.sections | Where-Object { $_.id -eq 'part1' })[0]
$part2 = @($canonical.sections | Where-Object { $_.id -eq 'part2' })[0]
$part3 = @($canonical.sections | Where-Object { $_.id -eq 'part3' })[0]
$partLabel = 'PH' + [char]0x1EA6 + 'N '
$expected = @{
    T01_WORKSHOP='WORKSHOP'; T02_AI='AI'; T03_DEPARTMENT=$canonical.event.department
    T04_FIELD_APPLICATION=$part1.title; T05_RESPONSIBLE_AI=$part2.title
    T06_DATE=([datetime]::ParseExact($canonical.event.date,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture).ToString('dd.MM.yyyy'))
    T07_LOCATION=$canonical.event.location; T08_TIME=($canonical.event.start + ' ' + [char]0x2013 + ' ' + $canonical.event.end)
    T09_OPENING=$opening.title; T10_PART1=($partLabel+'1'); T11_PART2=($partLabel+'2'); T12_PART3=($partLabel+'3'); T13_SUMMARY=$part3.title
    T24_PART2_PRESENTER=$part2.presenter
    T29_OPENING_SPEAKER=$opening.children[0].title; T30_OPENING_ROLE=$opening.children[0].subtitle
    T31_MINIGAME=$opening.children[1].title; T32_MINIGAME_SUBTITLE=$opening.children[1].subtitle
    T33_DASHBOARD_HOOK=('TH' + [char]0x00D4 + 'NG TIN TRONG T' + [char]0x1EA6 + 'M TAY')
    T34_AI_BIM_HOOK=('AI ' + [char]0x00D7 + ' BIM')
}
if (-not $canonical.event.title.EndsWith('WORKSHOP AI')) { throw 'Canonical event title no longer matches intro title.' }
for ($i = 0; $i -lt 5; $i++) {
    $titleId = 'T{0:D2}_TOPIC_{1}' -f (14 + $i), ($i + 1)
    $presenterId = 'T{0:D2}_PRESENTER_{1}' -f (19 + $i), ($i + 1)
    $expected[$titleId] = $part1.children[$i].title
    $expected[$presenterId] = $part1.children[$i].presenter
}
for ($i = 0; $i -lt 4; $i++) { $expected[('T{0:D2}_PART2_SUBTOPIC_{1}' -f (25+$i),($i+1))] = $part2.children[$i].title }
if ($spec.assets.Count -ne $expected.Count) { throw 'Incomplete text asset set; expected 34.' }
foreach ($asset in $spec.assets) {
    if (-not $expected.ContainsKey($asset.id) -or $asset.text -cne $expected[$asset.id]) { throw "Text contract mismatch: $($asset.id)" }
}
$dashboard = @($spec.assets | Where-Object { $_.id -eq 'T16_TOPIC_3' })[0].text
if (-not $dashboard.Contains([string][char]0x1EA7)) { throw 'Required Vietnamese circumflex-grave glyph is missing.' }
if ('TextAssetRenderer' -as [type]) { throw 'TextAssetRenderer already loaded; use a fresh process.' }
Add-Type -AssemblyName PresentationCore
$fontPins = @{
    Bold='32E42D57A7A9E62DD943722D5ECE99AF4736FBD11A9927CF07378299C117D3BD'
    Italic='776BFB34E9311C23DCB64137EA81FF49056B13CCE7212E4F71870EBE01653E4E'
}
$fonts = foreach ($style in @('Bold','Italic')) {
    $fontPath = Join-Path ([Environment]::GetFolderPath('Fonts')) ('RobotoCondensed-'+$style+'.ttf')
    $fontHash = (Get-FileHash -LiteralPath $fontPath -Algorithm SHA256).Hash
    if ($fontHash -cne $fontPins[$style]) { throw "Font version mismatch: $style ($fontPath). Use the pinned source font; existing PNG/SVG need no installation." }
    $glyph = [Windows.Media.GlyphTypeface]::new([Uri]$fontPath)
    [ordered]@{ style=$style; file=$fontPath; sha256=$fontHash; version=$glyph.Version }
}
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'TextAssetRenderer.cs'), [Text.Encoding]::UTF8)) -ReferencedAssemblies System.Drawing
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$measurements = foreach ($asset in $spec.assets) {
    if ($asset.id -notmatch '^T[0-9]{2}_[A-Z0-9_]+$') { throw 'Unexpected text asset ID.' }
    $png = Join-Path $OutputDir ($asset.id + '.png')
    $svg = Join-Path $OutputDir ($asset.id + '.svg')
    $fontFile = @($fonts | Where-Object { $_.style -ceq $asset.fontStyle })[0].file
    $result = [TextAssetRenderer]::Render($asset.id, $asset.text, $png, $svg, [single]$asset.fontSizePx, ($asset.fontStyle -ceq 'Italic'), $asset.color, 3840, $fontFile)
    $asset.width = $result.Width
    $asset.height = $result.Height
    $asset.fontSizePx = $result.FontSizePx
    [ordered]@{ id=$asset.id; width=$result.Width; height=$result.Height; font=$result.FontFamily; style=$result.FontStyle; alpha_zero_pixels=$result.TransparentPixels; painted_pixels=$result.PaintedPixels; partial_alpha_pixels=$result.AntialiasedPixels; bounds=@($result.MinimumPaintX,$result.MinimumPaintY,$result.MaximumPaintX,$result.MaximumPaintY); png_sha256=(Get-FileHash -LiteralPath $png -Algorithm SHA256).Hash; svg_sha256=(Get-FileHash -LiteralPath $svg -Algorithm SHA256).Hash }
}
$report = [ordered]@{ generated_at_utc=[DateTime]::UtcNow.ToString('o'); runtime=$PSVersionTable.PSVersion.ToString(); output_directory=$OutputDir; count=$measurements.Count; text_contract_checks=$expected.Count; canonical_sha256=$spec.canonicalSha256; fonts=@($fonts); svg_grouping='One intact phrase outline per RUN_01; individual word/glyph groups are not provided.'; measurements=@($measurements) }
$reportPath = Join-Path $root 'evidence\text-assets-verification.json'
if ($OutputDir -eq $allowedRoots[0]) {
    [IO.File]::WriteAllText($manifestPath, (($spec | ConvertTo-Json -Depth 20) + "`n"), [Text.UTF8Encoding]::new($false))
} else { $reportPath = Join-Path $OutputDir 'verification.json' }
[IO.File]::WriteAllText($reportPath, (($report | ConvertTo-Json -Depth 12) + "`n"), [Text.UTF8Encoding]::new($false))
Write-Output ("Rendered {0} transparent PNG and {0} outlined SVG assets; canonical text checks passed." -f $measurements.Count)
