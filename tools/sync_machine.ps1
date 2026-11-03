<#
  sync_machine.ps1 - kiem tra / dong bo workflow giua 2 may (HOME / COMPANY).

  Dry-run mac dinh (chi doc). Xem docs/HANDOVER-SYNC.md.
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\sync_machine.ps1 -Machine home [-Scope H3_Character_Sheet] [-Apply] [-Report]

  Exit code: 0 = khong thieu gi, 2 = co thieu. Chi dung GET toi ComfyUI. Khong tai model, khong xoa file.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Machine,
    [string]$Scope = "",
    [switch]$Apply,
    [switch]$Report
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Web.Extensions

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ProfilePath = Join-Path $RepoRoot ("machines\" + $Machine + ".json")
if (-not (Test-Path -LiteralPath $ProfilePath)) { throw "Khong thay profile: $ProfilePath (copy machines\company.example.json -> machines\$Machine.json)" }
$Prof = Get-Content -LiteralPath $ProfilePath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($key in "workflows_dir", "custom_nodes_dir", "input_dir", "models_root", "api_url") {
    $val = [string]$Prof.$key
    if (-not $val -or $val.StartsWith("<")) { throw "Profile $Machine chua dien khoa '$key'" }
}

$Json = New-Object System.Web.Script.Serialization.JavaScriptSerializer
$Json.MaxJsonLength = [int]::MaxValue
$Json.RecursionLimit = 500
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$WfRepoBase = Join-Path $RepoRoot "comfyui\workflows\user"
$CnRepoBase = Join-Path $RepoRoot "comfyui\custom_nodes"
$InRepoDir = Join-Path $RepoRoot "comfyui\input"
$ModelExt = @(".safetensors", ".gguf", ".pth", ".ckpt", ".bin", ".pt")
# Node chi ton tai o frontend, khong co trong /object_info
$FrontendTypes = @("Note", "MarkdownNote", "Reroute", "PrimitiveNode", "Label", "Group")
$GuidRx = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

function Get-ApiJson([string]$Url) {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 30
    return $Json.DeserializeObject($resp.Content)
}

function Read-WorkflowFile([string]$Path) {
    $txt = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    return $Json.DeserializeObject($txt)
}

function Add-StringsFromValue($Value, $Sink) {
    if ($null -eq $Value) { return }
    if ($Value -is [string]) { [void]$Sink.Add($Value); return }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($v in $Value.Values) { Add-StringsFromValue $v $Sink }
        return
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        foreach ($v in $Value) { Add-StringsFromValue $v $Sink }
    }
}

function Get-NodeList($Doc) {
    $all = New-Object System.Collections.ArrayList
    if ($Doc.ContainsKey("nodes")) { foreach ($n in $Doc["nodes"]) { [void]$all.Add($n) } }
    if ($Doc.ContainsKey("definitions") -and $Doc["definitions"] -is [System.Collections.IDictionary] -and $Doc["definitions"].ContainsKey("subgraphs")) {
        foreach ($sg in $Doc["definitions"]["subgraphs"]) {
            if ($sg.ContainsKey("nodes")) { foreach ($n in $sg["nodes"]) { [void]$all.Add($n) } }
        }
    }
    return $all
}

# Tra ve doi tuong: types, models, inputs (HashSet)
function Get-WorkflowNeeds([string]$Path) {
    $doc = Read-WorkflowFile $Path
    if (-not ($doc -is [System.Collections.IDictionary]) -or -not $doc.ContainsKey("nodes")) { return $null }
    $types = New-Object 'System.Collections.Generic.HashSet[string]'
    $models = New-Object 'System.Collections.Generic.HashSet[string]'
    $inputs = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($node in (Get-NodeList $doc)) {
        $type = [string]$node["type"]
        if (-not $type -or $type -match $GuidRx -or $FrontendTypes -contains $type) { continue }
        [void]$types.Add($type)
        $strs = New-Object System.Collections.ArrayList
        if ($node.ContainsKey("widgets_values")) { Add-StringsFromValue $node["widgets_values"] $strs }
        if ($type -eq "LoadImage" -or $type -eq "LoadImageMask") {
            if ($strs.Count -gt 0) { [void]$inputs.Add((([string]$strs[0]) -replace '\s*\[(input|output|temp)\]\s*$', '')) }
            continue
        }
        foreach ($s in $strs) {
            if ($s.Length -lt 260 -and $s -notmatch '[\r\n"<>|*?]' -and $s -match '\.(safetensors|gguf|pth|ckpt|bin|pt)$') { [void]$models.Add($s) }
        }
    }
    return [pscustomobject]@{ types = $types; models = $models; inputs = $inputs }
}

function Get-Leaf([string]$Name) { return ($Name -replace '\\', '/').Split('/')[-1] }

# ---------- manifest ----------
$ManifestPath = Join-Path $RepoRoot "models\model-manifest.csv"
$ManifestByLeaf = @{}
if (Test-Path -LiteralPath $ManifestPath) {
    foreach ($row in (Import-Csv -LiteralPath $ManifestPath -Encoding UTF8)) {
        if ($row.app -eq "ComfyUI" -and -not $ManifestByLeaf.ContainsKey($row.file_or_repo)) { $ManifestByLeaf[$row.file_or_repo] = $row }
    }
}

# ---------- custom node index (type -> folder) ----------
$PyIndex = $null
$FolderCache = @{}
function Find-CustomNodeFolder([string]$TypeName) {
    if ($FolderCache.ContainsKey($TypeName)) { return $FolderCache[$TypeName] }
    if ($null -eq $script:PyIndex) {
        $script:PyIndex = New-Object System.Collections.ArrayList
        foreach ($dir in (Get-ChildItem -LiteralPath $CnRepoBase -Directory)) {
            foreach ($pf in (Get-ChildItem -LiteralPath $dir.FullName -Recurse -Filter *.py -File -ErrorAction SilentlyContinue |
                    Where-Object { $_.FullName -notmatch '\\(tests|node_modules|\.git)\\' })) {
                [void]$script:PyIndex.Add([pscustomobject]@{ folder = $dir.Name; text = [System.IO.File]::ReadAllText($pf.FullName) })
            }
        }
    }
    $rx = '(class\s+' + [regex]::Escape($TypeName) + '\b|["'']' + [regex]::Escape($TypeName) + '["'']\s*:\s*[A-Za-z_])'
    $found = $null
    foreach ($item in $script:PyIndex) { if ($item.text -match $rx) { $found = $item.folder; break } }
    $FolderCache[$TypeName] = $found
    return $found
}

# ---------- workflows trong scope ----------
$ScopeDir = $WfRepoBase
if ($Scope) { $ScopeDir = Join-Path $WfRepoBase $Scope }
if (-not (Test-Path -LiteralPath $ScopeDir)) { throw "Scope khong ton tai: $ScopeDir" }
$wfFiles = Get-ChildItem -LiteralPath $ScopeDir -Filter *.json -File -Recurse |
    Where-Object { $_.FullName.Substring($WfRepoBase.Length) -notmatch '(^|\\)archive[^\\]*\\' } | Sort-Object FullName

$Entries = New-Object System.Collections.ArrayList
$SkippedNonGraph = New-Object System.Collections.ArrayList
foreach ($f in $wfFiles) {
    $rel = $f.FullName.Substring($WfRepoBase.Length).TrimStart('\')
    $needs = Get-WorkflowNeeds $f.FullName
    if ($null -eq $needs) { [void]$SkippedNonGraph.Add($rel); continue }
    [void]$Entries.Add([pscustomobject]@{ rel = $rel; full = $f.FullName; needs = $needs })
}

# ---------- trang thai may ----------
$ApiUp = $false
$ApiNote = ""
$LiveTypes = $null
$LiveModelNames = $null
try {
    $objInfo = Get-ApiJson ($Prof.api_url.TrimEnd('/') + "/object_info")
    $LiveTypes = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($k in $objInfo.Keys) { [void]$LiveTypes.Add([string]$k) }
    $LiveModelNames = New-Object 'System.Collections.Generic.HashSet[string]'
    $folders = Get-ApiJson ($Prof.api_url.TrimEnd('/') + "/models")
    foreach ($fd in $folders) {
        if (@("custom_nodes", "configs") -contains $fd) { continue }
        try {
            foreach ($mn in (Get-ApiJson ($Prof.api_url.TrimEnd('/') + "/models/" + $fd))) {
                [void]$LiveModelNames.Add(($mn -replace '\\', '/'))
                [void]$LiveModelNames.Add((Get-Leaf $mn))
            }
        } catch { }
    }
    $ApiUp = $true
} catch {
    $ApiNote = "API khong truy cap duoc ($($Prof.api_url)): " + $_.Exception.Message
}

$FileIndex = $null
function Test-ModelOnDisk([string]$Name) {
    if ($null -eq $script:FileIndex) {
        $script:FileIndex = New-Object 'System.Collections.Generic.HashSet[string]'
        if (Test-Path -LiteralPath $Prof.models_root) {
            foreach ($mf in (Get-ChildItem -LiteralPath $Prof.models_root -Recurse -File -ErrorAction SilentlyContinue)) {
                [void]$script:FileIndex.Add($mf.Name)
            }
        }
    }
    return $script:FileIndex.Contains((Get-Leaf $Name))
}

function Test-ModelPresent([string]$Name) {
    if ($ApiUp) {
        if ($LiveModelNames.Contains(($Name -replace '\\', '/')) -or $LiveModelNames.Contains((Get-Leaf $Name))) { return $true }
    }
    return (Test-ModelOnDisk $Name)
}

# ---------- kiem tra ----------
$WfMissing = New-Object System.Collections.ArrayList
$ModelUse = @{}; $TypeUse = @{}; $InputUse = @{}

foreach ($e in $Entries) {
    $target = Join-Path $Prof.workflows_dir $e.rel
    if (-not (Test-Path -LiteralPath $target)) {
        [void]$WfMissing.Add([ordered]@{ workflow = $e.rel; reason = "missing" })
    } elseif ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $e.full -Algorithm SHA256).Hash) {
        [void]$WfMissing.Add([ordered]@{ workflow = $e.rel; reason = "differs" })
    }
    foreach ($m in $e.needs.models) { if (-not $ModelUse.ContainsKey($m)) { $ModelUse[$m] = New-Object System.Collections.ArrayList }; [void]$ModelUse[$m].Add($e.rel) }
    foreach ($t in $e.needs.types) { if (-not $TypeUse.ContainsKey($t)) { $TypeUse[$t] = New-Object System.Collections.ArrayList }; [void]$TypeUse[$t].Add($e.rel) }
    foreach ($i in $e.needs.inputs) { if (-not $InputUse.ContainsKey($i)) { $InputUse[$i] = New-Object System.Collections.ArrayList }; [void]$InputUse[$i].Add($e.rel) }
}

$MissingModels = New-Object System.Collections.ArrayList
foreach ($m in ($ModelUse.Keys | Sort-Object)) {
    if (Test-ModelPresent $m) { continue }
    $leaf = Get-Leaf $m
    $mrow = $ManifestByLeaf[$leaf]
    $sizeBytes = $null; $hasUrl = $false
    if ($mrow) { $sizeBytes = [long]$mrow.size_bytes; $hasUrl = [bool]$mrow.url }
    [void]$MissingModels.Add([ordered]@{
        name = $m; leaf = $leaf; in_manifest = [bool]$mrow; downloadable = $hasUrl
        size_bytes = $sizeBytes; size_gb = $(if ($sizeBytes) { [math]::Round($sizeBytes / 1e9, 2) } else { $null })
        workflows = @($ModelUse[$m])
    })
}

$MissingTypes = New-Object System.Collections.ArrayList
$TypeNotChecked = $false
if ($ApiUp) {
    foreach ($t in ($TypeUse.Keys | Sort-Object)) {
        if ($LiveTypes.Contains($t)) { continue }
        [void]$MissingTypes.Add([ordered]@{ type = $t; custom_node_folder = (Find-CustomNodeFolder $t); workflows = @($TypeUse[$t]) })
    }
} else { $TypeNotChecked = $true }

$MissingInputs = New-Object System.Collections.ArrayList
foreach ($i in ($InputUse.Keys | Sort-Object)) {
    $found = (Test-Path -LiteralPath (Join-Path $Prof.input_dir $i)) -or (Test-Path -LiteralPath (Join-Path $InRepoDir $i))
    if (-not $found) { [void]$MissingInputs.Add([ordered]@{ name = $i; workflows = @($InputUse[$i]) }) }
}

# ---------- apply ----------
$Applied = New-Object System.Collections.ArrayList
function Copy-AddOnly([string]$Src, [string]$Dst) {
    $stamp = Get-Date -Format "yyyyMMdd"
    if (Test-Path -LiteralPath $Dst) {
        if ((Get-FileHash -LiteralPath $Src -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $Dst -Algorithm SHA256).Hash) { return "same" }
        Copy-Item -LiteralPath $Dst -Destination ($Dst + ".bak-" + $stamp) -Force
        Copy-Item -LiteralPath $Src -Destination $Dst -Force
        return "updated"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dst) | Out-Null
    Copy-Item -LiteralPath $Src -Destination $Dst
    return "added"
}
if ($Apply) {
    foreach ($e in $Entries) {
        $r = Copy-AddOnly $e.full (Join-Path $Prof.workflows_dir $e.rel)
        if ($r -ne "same") { [void]$Applied.Add([ordered]@{ kind = "workflow"; path = $e.rel; result = $r }) }
    }
    foreach ($dir in (Get-ChildItem -LiteralPath $CnRepoBase -Directory)) {
        foreach ($cf in (Get-ChildItem -LiteralPath $dir.FullName -Recurse -File -Force |
                Where-Object { $_.FullName -notmatch '\\(__pycache__|\.git|node_modules)\\' -and $_.Extension -ne '.pyc' })) {
            $crel = $cf.FullName.Substring($CnRepoBase.Length).TrimStart('\')
            $r = Copy-AddOnly $cf.FullName (Join-Path $Prof.custom_nodes_dir $crel)
            if ($r -ne "same") { [void]$Applied.Add([ordered]@{ kind = "custom_node"; path = $crel; result = $r }) }
        }
    }
}

# ---------- bao cao ra man hinh ----------
$BaseDir = Split-Path -Parent $Prof.models_root
$DlScript = Join-Path $RepoRoot "models\DOWNLOAD-MODELS.ps1"
Write-Host ""
Write-Host ("== sync_machine: machine=$Machine scope=" + $(if ($Scope) { $Scope } else { "(all)" }) + " apply=$([bool]$Apply) ==")
Write-Host ("Workflows in scope: " + $Entries.Count + " (skipped non-LiteGraph: " + $SkippedNonGraph.Count + ")")
if ($ApiUp) { Write-Host "ComfyUI API: OK $($Prof.api_url)" } else { Write-Host "ComfyUI API: NOT REACHABLE -> node types NOT CHECKED; models checked by file search only. $ApiNote" }

Write-Host ""
Write-Host "[Workflow chua co/lech o may nay: $($WfMissing.Count)]"
foreach ($w in $WfMissing) { Write-Host ("  - {0} ({1})" -f $w.workflow, $w.reason) }

Write-Host ""
Write-Host "[Model thieu: $($MissingModels.Count)]"
foreach ($m in $MissingModels) {
    $sz = if ($m.size_gb) { ("{0:N2} GB" -f $m.size_gb) } else { "size unknown (not in manifest)" }
    Write-Host ("  - {0}  [{1}]  {2}" -f $m.name, $sz, $(if ($m.downloadable) { "co URL" } elseif ($m.in_manifest) { "manifest khong co URL" } else { "KHONG co trong manifest" }))
}
$dlNames = @($MissingModels | Where-Object { $_.downloadable } | ForEach-Object { '"' + $_.leaf + '"' })
if ($dlNames.Count -gt 0) {
    Write-Host "  Lenh tai (chay tay, script nay khong tai):"
    Write-Host ("  powershell -NoProfile -ExecutionPolicy Bypass -File `"{0}`" -BaseDir `"{1}`" -Only {2}" -f $DlScript, $BaseDir, ($dlNames -join ","))
}

Write-Host ""
if ($TypeNotChecked) {
    Write-Host "[Node type: NOT CHECKED (API khong len)]"
} else {
    Write-Host "[Node type thieu trong ComfyUI dang chay: $($MissingTypes.Count)]"
    foreach ($t in $MissingTypes) {
        $fo = if ($t.custom_node_folder) { $t.custom_node_folder } else { "(khong thay trong repo custom_nodes - co the la node core/ngoai)" }
        Write-Host ("  - {0} -> {1}" -f $t.type, $fo)
    }
    if (@($MissingTypes | Where-Object { $_.custom_node_folder }).Count -gt 0) {
        Write-Host "  Cach xu ly: chep folder custom node (-Apply) + them ten vao --whitelist-custom-nodes trong docker compose + restart container (khong tu lam)."
    }
}

Write-Host ""
Write-Host "[Input image thieu: $($MissingInputs.Count)]"
foreach ($i in $MissingInputs) { Write-Host ("  - " + $i.name) }

if ($Apply) {
    Write-Host ""
    Write-Host "[Apply: $($Applied.Count) file chep/cap nhat]"
    foreach ($a in $Applied) { Write-Host ("  - {0} {1} {2}" -f $a.kind, $a.result, $a.path) }
}

# ---------- receipt ----------
$TotalMissing = $WfMissing.Count + $MissingModels.Count + $MissingTypes.Count + $MissingInputs.Count
$receipt = [ordered]@{
    machine = $Machine; scope = $(if ($Scope) { $Scope } else { "(all)" }); timestamp = (Get-Date).ToString("s")
    applied = [bool]$Apply; api_up = $ApiUp; node_types_checked = (-not $TypeNotChecked)
    counts = [ordered]@{
        workflows = $Entries.Count; workflows_missing_or_differs = $WfMissing.Count
        models_missing = $MissingModels.Count; node_types_missing = $MissingTypes.Count; inputs_missing = $MissingInputs.Count
    }
    missing = [ordered]@{ workflows = @($WfMissing); models = @($MissingModels); node_types = @($MissingTypes); inputs = @($MissingInputs) }
    download_command = $(if ($dlNames.Count -gt 0) { "powershell -NoProfile -ExecutionPolicy Bypass -File `"$DlScript`" -BaseDir `"$BaseDir`" -Only " + ($dlNames -join ",") } else { $null })
    applied_files = @($Applied)
}
$SyncDir = Join-Path $RepoRoot "docs\sync"
New-Item -ItemType Directory -Force -Path $SyncDir | Out-Null
$ReceiptPath = Join-Path $SyncDir ("SYNC-" + $Machine + "-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".json")
[System.IO.File]::WriteAllText($ReceiptPath, ($receipt | ConvertTo-Json -Depth 8), $Utf8NoBom)
Write-Host ""
Write-Host "Receipt: $ReceiptPath"

# ---------- REQUIREMENTS.json ----------
if ($Report) {
    $ReqPath = Join-Path $RepoRoot "comfyui\REQUIREMENTS.json"
    $wfMap = [ordered]@{}
    if (Test-Path -LiteralPath $ReqPath) {
        $old = Read-WorkflowFile $ReqPath
        if ($old.ContainsKey("workflows")) { foreach ($k in $old["workflows"].Keys) { $wfMap[$k] = $old["workflows"][$k] } }
    }
    foreach ($e in $Entries) {
        $mods = @(); foreach ($m in ($e.needs.models | Sort-Object)) {
            $mrow = $ManifestByLeaf[(Get-Leaf $m)]
            $mods += [ordered]@{ name = $m; size_bytes = $(if ($mrow) { [long]$mrow.size_bytes } else { $null }); in_manifest = [bool]$mrow }
        }
        $nts = @(); foreach ($t in ($e.needs.types | Sort-Object)) {
            $nts += [ordered]@{ type = $t; custom_node_folder = (Find-CustomNodeFolder $t) }
        }
        $wfMap[$e.rel -replace '\\', '/'] = [ordered]@{ models = $mods; node_types = $nts; inputs = @($e.needs.inputs | Sort-Object) }
    }
    $req = [ordered]@{ generated = (Get-Date).ToString("s"); generated_on = $Machine; workflows = $wfMap }
    [System.IO.File]::WriteAllText($ReqPath, ($req | ConvertTo-Json -Depth 8), $Utf8NoBom)
    Write-Host "Requirements: $ReqPath"
}

Write-Host ""
Write-Host ("Tong thieu: {0} -> exit {1}" -f $TotalMissing, $(if ($TotalMissing -eq 0) { 0 } else { 2 }))
if ($TotalMissing -eq 0) { exit 0 } else { exit 2 }
