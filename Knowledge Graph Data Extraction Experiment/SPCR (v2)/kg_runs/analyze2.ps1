$base = $PSScriptRoot
$files = @(
    "$base\任叔永_等4篇\combined_extract.json",
    "$base\孙伏园_等3篇\combined_extract.json",
    "$base\张东荪_等3篇\combined_extract.json",
    "$base\王平陵_等4篇\combined_extract.json"
)

$report = @()

foreach ($f in $files) {
    $dirName = Split-Path (Split-Path $f -Parent) -Leaf
    $txt = "`n========================================"
    $txt += "`nFILE: $dirName"
    $txt += "`n========================================"
    
    try {
        $json = Get-Content -Raw -Encoding UTF8 $f | ConvertFrom-Json
    } catch {
        $txt += "`nERROR: JSON PARSE FAILED"
        $report += $txt
        continue
    }
    
    # 1. Schema version
    $sv = $json.metadata.schema_version
    $txt += "`n[1] schema_version: $sv"
    if ($sv -ne 'lite_v3.0') { $txt += " MISMATCH!" } else { $txt += " OK" }
    
    # 2. Metadata
    $mKeys = $json.metadata.PSObject.Properties.Name -join ', '
    $txt += "`n[2] Metadata keys: $mKeys"
    $txt += "`n    articles=$($json.metadata.article_count), segments=$($json.metadata.segment_count), model=$($json.metadata.model)"
    
    # ENTITIES
    $entities = $json.entities
    $txt += "`n[3-6] Entity count: $($entities.Count)"
    
    $etypeHash = @{}
    $engTypes = @(); $otherTypes = @(); $emptyName = 0; $emptyType = 0
    
    foreach ($e in $entities) {
        $t = $e.type
        $n = $e.name
        if (-not $t) { $emptyType++ }
        if (-not $n) { $emptyName++ }
        if (-not $etypeHash.ContainsKey($t)) { $etypeHash[$t] = 0 }
        $etypeHash[$t]++
        
        # Check if type looks English (starts with ASCII letter)
        if ($t -match '^[A-Za-z]') { $engTypes += $t }
    }
    
    $txt += "`n    Entity types:"
    foreach ($k in ($etypeHash.Keys | Sort-Object)) { $txt += "`n      $($k): $($etypeHash[$k])" }
    if ($engTypes.Count -gt 0) { $txt += "`n    WARNING: English entity types: $($engTypes.Count) - $($engTypes | Select-Object -Unique)" }
    else { $txt += "`n    NO English entity types - OK" }
    if ($emptyName -gt 0) { $txt += "`n    WARNING: Empty entity names: $emptyName" }
    if ($emptyType -gt 0) { $txt += "`n    WARNING: Empty entity types: $emptyType" }
    
    # CLAIMS
    $claims = $json.claims
    $txt += "`n[7-9] Claim count: $($claims.Count)"
    $ctypeHash = @{}
    $emptySpeaker = 0; $emptyText = 0
    foreach ($c in $claims) {
        $ct = $c.claim_type
        if (-not $ctypeHash.ContainsKey($ct)) { $ctypeHash[$ct] = 0 }
        $ctypeHash[$ct]++
        if (-not $c.speaker) { $emptySpeaker++ }
        if (-not $c.claim_text) { $emptyText++ }
    }
    $txt += "`n    Claim types: $($ctypeHash.Keys -join ', ')"
    if ($emptySpeaker -gt 0) { $txt += "`n    WARNING: Empty speaker: $emptySpeaker" }
    if ($emptyText -gt 0) { $txt += "`n    WARNING: Empty claim_text: $emptyText" }
    
    # RELATIONS
    $relations = $json.relations
    $txt += "`n[10-15] Relation count: $($relations.Count)"
    $rtypeHash = @{}
    $missS = 0; $missI = 0; $missSub = 0; $missH = 0; $missT = 0; $missE = 0
    $sOOR = 0; $iOOR = 0
    $depFound = @()
    foreach ($r in $relations) {
        $rt = $r.relation_type
        if (-not $rtypeHash.ContainsKey($rt)) { $rtypeHash[$rt] = 0 }
        $rtypeHash[$rt]++
        if ($rt -in @('中外','为证据支持','相关','关注')) { $depFound += $rt }
        if ($null -eq $r.stance_score) { $missS++ }
        if ($null -eq $r.intensity) { $missI++ }
        if (-not $r.relation_subtype) { $missSub++ }
        if (-not $r.head_id) { $missH++ }
        if (-not $r.tail_id) { $missT++ }
        if (-not $r.evidence) { $missE++ }
        $ss = $r.stance_score
        if ($null -ne $ss -and ($ss -lt -1 -or $ss -gt 1)) { $sOOR++ }
        $inten = $r.intensity
        if ($null -ne $inten -and ($inten -lt 0 -or $inten -gt 1)) { $iOOR++ }
    }
    $txt += "`n    Relation types: $($rtypeHash.Keys -join ', ')"
    if ($depFound.Count -gt 0) { $txt += "`n    WARNING: Deprecated relation types: $($depFound | Select-Object -Unique)" }
    $txt += "`n    stance_score: missing=$missS, outOfRange=$sOOR"
    $txt += "`n    intensity: missing=$missI, outOfRange=$iOOR"
    $txt += "`n    relation_subtype missing=$missSub"
    $txt += "`n    empty head=$missH, tail=$missT, evidence=$missE"
    
    # Other sections
    $txt += "`n[16] definitions: $($json.definitions.Count)"
    $txt += "`n[17] citations: $($json.citations.Count)"
    $txt += "`n[18] rhetorical_devices: $($json.rhetorical_devices.Count)"
    
    # Duplicates
    $ids = $entities | ForEach-Object { $_.id }
    $grp = $ids | Group-Object | Where-Object { $_.Count -gt 1 }
    if ($grp.Count -gt 0) { $txt += "`n    WARNING: Duplicate entity IDs: $($grp.Count) groups" }
    else { $txt += "`n    No duplicate entity IDs - OK" }
    
    # Sample relations
    $txt += "`n[21] First 3 relations:"
    $max = [Math]::Min(3, $relations.Count)
    for ($i = 0; $i -lt $max; $i++) {
        $r = $relations[$i]
        $txt += "`n    #$i`t: $($r.head_id) --[$($r.relation_type)]--> $($r.tail_id) | stance=$($r.stance_score) intensity=$($r.intensity) subtype=$($r.relation_subtype)"
    }
    
    # Counts for totals
    $report += @{
        text = $txt
        entities = $entities.Count
        claims = $claims.Count
        relations = $relations.Count
        defs = $json.definitions.Count
        cits = $json.citations.Count
        rhet = $json.rhetorical_devices.Count
    }
}

# Output all per-file reports
foreach ($r in $report) { Write-Host $r.text }

# Grand totals
$ge = ($report | Measure-Object -Property entities -Sum).Sum
$gc = ($report | Measure-Object -Property claims -Sum).Sum
$gr = ($report | Measure-Object -Property relations -Sum).Sum
$gd = ($report | Measure-Object -Property defs -Sum).Sum
$gci = ($report | Measure-Object -Property cits -Sum).Sum
$grh = ($report | Measure-Object -Property rhet -Sum).Sum

Write-Host "`n========================================"
Write-Host "GRAND TOTALS ACROSS ALL 4 FILES"
Write-Host "========================================"
Write-Host "[20] entities=$ge, claims=$gc, relations=$gr, definitions=$gd, citations=$gci, rhetorical_devices=$grh"
