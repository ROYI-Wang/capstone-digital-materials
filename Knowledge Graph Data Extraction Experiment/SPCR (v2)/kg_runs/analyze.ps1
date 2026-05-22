$ErrorActionPreference = 'Stop'
$base = "E:\1研究生\岭南大学\论文毕业\capstone\资料\新的内容开始了\local_upload\kg_runs_v2"
$dirs = @("任叔永_等4篇", "孙伏园_等3篇", "张东荪_等3篇", "王平陵_等4篇")

# Valid entity types (v2)
$validEntityTypes = @("人物","阵营/群体","概念","理论/学说/思潮","方法","学科","事件","历史事件","观点","论据","论证","立场","动机/目标","议题","阶段","预设","评价")

# Valid claim types
$validClaimTypes = @("positive_claim","negative_claim","neutral_claim","definitional_claim","comparative_claim","causal_claim","normative_claim","existential_claim","hypothetical_claim","predictive_claim")

# Deprecated relation types
$deprecatedRelTypes = @("中外","为证据支持","相关","关注")

# Valid relation types (v2)
$validRelTypes = @("支持","反对","改进","包含","基于","导致","等价于","与...一致","与...矛盾","限制","增强","削弱","解释","定义","举例","类比","被解释","被包含","被反驳","被引用","被支持","先于","后于","评述","异于","同于")

$grandTotals = @{}
$allEntityTypes = @{}
$allClaimTypes = @{}
$allRelTypes = @{}
$allIssues = @()
$grandEntities = 0
$grandClaims = 0
$grandRelations = 0
$grandDefs = 0
$grandCits = 0
$grandRhet = 0
$samples = @()

foreach ($dir in $dirs) {
    $file = "$base\$dir\combined_extract.json"
    Write-Host "`n========================================"
    Write-Host "FILE: $dir"
    Write-Host "========================================"
    
    try {
        $json = Get-Content -Raw -Encoding UTF8 $file | ConvertFrom-Json
    } catch {
        Write-Host "ERROR: JSON PARSE FAILED - $_"
        continue
    }
    
    $issues = @()
    
    # 1. Schema version
    $sv = $json.metadata.schema_version
    if ($sv -ne "lite_v3.0") { $issues += "schema_version=$sv (expected lite_v3.0)" }
    else { Write-Host "[1] schema_version: $sv - OK" }
    
    # 2. Metadata
    Write-Host "[2] Metadata keys: $($json.metadata.PSObject.Properties.Name -join ', ')"
    Write-Host "    article_count=$($json.metadata.article_count), segment_count=$($json.metadata.segment_count), model=$($json.metadata.model)"
    
    # Entities
    $entities = $json.entities
    $eCount = $entities.Count
    Write-Host "[3-6] Entity count: $eCount"
    
    $eTypes = @{}
    $emptyName = 0; $emptyType = 0; $englishTypes = 0; $invalidTypes = @()
    $engTypeList = @()
    foreach ($e in $entities) {
        $t = $e.type
        if (-not $t -or $t -eq "") { $emptyType++ }
        if (-not $e.name -or $e.name -eq "") { $emptyName++ }
        if ($t -and $validEntityTypes -notcontains $t) {
            if ($t -match "^[a-zA-Z]") {
                $englishTypes++
                $engTypeList += $t
            } else { $invalidTypes += $t }
        }
        if (-not $eTypes.ContainsKey($t)) { $eTypes[$t] = 0 }
        $eTypes[$t]++
        if (-not $allEntityTypes.ContainsKey($t)) { $allEntityTypes[$t] = 0 }
        $allEntityTypes[$t]++
    }
    
    Write-Host "    Entity types found:"
    foreach ($k in ($eTypes.Keys | Sort-Object)) { Write-Host "      $($k): $($eTypes[$k])" }
    if ($englishTypes -gt 0) { $issues += "English entity types: $englishTypes ($engTypeList)" }
    if ($invalidTypes.Count -gt 0) { $issues += "Invalid entity types: $($invalidTypes -join ', ')" }
    if ($emptyName -gt 0) { $issues += "Empty entity names: $emptyName" }
    if ($emptyType -gt 0) { $issues += "Empty entity types: $emptyType" }
    if ($englishTypes -eq 0) { Write-Host "    NO English entity types - OK" }
    
    # Claims
    $claims = $json.claims
    Write-Host "[7-9] Claim count: $($claims.Count)"
    $cTypes = @{}
    $emptySpeaker = 0; $emptyClaimText = 0; $engClaimTypes = 0
    foreach ($c in $claims) {
        $ct = $c.claim_type
        if (-not $cTypes.ContainsKey($ct)) { $cTypes[$ct] = 0 }
        $cTypes[$ct]++
        if (-not $allClaimTypes.ContainsKey($ct)) { $allClaimTypes[$ct] = 0 }
        $allClaimTypes[$ct]++
        if (-not $c.speaker -or $c.speaker -eq "") { $emptySpeaker++ }
        if (-not $c.claim_text -or $c.claim_text -eq "") { $emptyClaimText++ }
        if ($ct -and $validClaimTypes -notcontains $ct) {
            if ($ct -match "^[a-zA-Z]") { $engClaimTypes++ }
        }
    }
    Write-Host "    Claim types: $($cTypes.Keys -join ', ')"
    if ($engClaimTypes -gt 0) { $issues += "English claim types: $engClaimTypes" }
    if ($emptySpeaker -gt 0) { $issues += "Empty speaker: $emptySpeaker" }
    if ($emptyClaimText -gt 0) { $issues += "Empty claim_text: $emptyClaimText" }
    
    # Relations
    $relations = $json.relations
    Write-Host "[10-15] Relation count: $($relations.Count)"
    $rTypes = @{}
    $missingStance = 0; $missingIntensity = 0; $missingSubtype = 0
    $missingHead = 0; $missingTail = 0; $missingEvidence = 0
    $stanceOutOfRange = 0; $intensityOutOfRange = 0
    $deprecatedRels = @()
    foreach ($r in $relations) {
        $rt = $r.relation_type
        if (-not $rTypes.ContainsKey($rt)) { $rTypes[$rt] = 0 }
        $rTypes[$rt]++
        if (-not $allRelTypes.ContainsKey($rt)) { $allRelTypes[$rt] = 0 }
        $allRelTypes[$rt]++
        
        if ($deprecatedRelTypes -contains $rt) { $deprecatedRels += $rt }
        
        if ($null -eq $r.stance_score -and $r.stance_score -ne 0) { $missingStance++ }
        if ($null -eq $r.intensity -and $r.intensity -ne 0) { $missingIntensity++ }
        if (-not $r.relation_subtype -or $r.relation_subtype -eq "") { $missingSubtype++ }
        if (-not $r.head_id -or $r.head_id -eq "") { $missingHead++ }
        if (-not $r.tail_id -or $r.tail_id -eq "") { $missingTail++ }
        if (-not $r.evidence -or $r.evidence -eq "") { $missingEvidence++ }
        
        if ($null -ne $r.stance_score) {
            if ($r.stance_score -lt -1 -or $r.stance_score -gt 1) { $stanceOutOfRange++ }
        }
        if ($null -ne $r.intensity) {
            if ($r.intensity -lt 0 -or $r.intensity -gt 1) { $intensityOutOfRange++ }
        }
    }
    
    Write-Host "    Relation types: $($rTypes.Keys -join ', ')"
    if ($deprecatedRels.Count -gt 0) { $issues += "Deprecated relation types: $deprecatedRels" }
    if ($missingStance -gt 0) { $issues += "Missing stance_score: $missingStance" }
    if ($missingIntensity -gt 0) { $issues += "Missing intensity: $missingIntensity" }
    if ($missingSubtype -gt 0) { $issues += "Missing relation_subtype: $missingSubtype" }
    if ($missingHead -gt 0) { $issues += "Empty head_id: $missingHead" }
    if ($missingTail -gt 0) { $issues += "Empty tail_id: $missingTail" }
    if ($missingEvidence -gt 0) { $issues += "Empty evidence: $missingEvidence" }
    if ($stanceOutOfRange -gt 0) { $issues += "stance_score out of [-1,1]: $stanceOutOfRange" }
    if ($intensityOutOfRange -gt 0) { $issues += "intensity out of [0,1]: $intensityOutOfRange" }
    
    Write-Host "    stance_score missing=$missingStance, out of range=$stanceOutOfRange"
    Write-Host "    intensity missing=$missingIntensity, out of range=$intensityOutOfRange"
    Write-Host "    relation_subtype missing=$missingSubtype"
    Write-Host "    empty head=$missingHead, tail=$missingTail, evidence=$missingEvidence"
    
    # Other sections
    Write-Host "[16] definitions: $($json.definitions.Count)"
    Write-Host "[17] citations: $($json.citations.Count)"
    Write-Host "[18] rhetorical_devices: $($json.rhetorical_devices.Count)"
    
    # Duplicate entity IDs
    $ids = $entities | ForEach-Object { $_.id }
    $dupes = $ids | Group-Object | Where-Object { $_.Count -gt 1 }
    if ($dupes.Count -gt 0) {
        $issues += "Duplicate entity IDs: $($dupes.Count) IDs repeated ($($dupes | ForEach-Object { "$($_.Name)x$($_.Count)" }))"
    }
    
    # First 3 relations sample
    Write-Host "[21] First 3 relations:"
    $samples += @{file=$dir; relations=@()}
    for ($i=0; $i -lt [Math]::Min(3, $relations.Count); $i++) {
        $r = $relations[$i]
        Write-Host "    #$i: $($r.head_id) --[$($r.relation_type)]--> $($r.tail_id) | stance=$($r.stance_score) intensity=$($r.intensity) subtype=$($r.relation_subtype)"
        $samples[-1].relations += $r
    }
    
    # Counts
    $grandEntities += $eCount
    $grandClaims += $claims.Count
    $grandRelations += $relations.Count
    $grandDefs += $json.definitions.Count
    $grandCits += $json.citations.Count
    $grandRhet += $json.rhetorical_devices.Count
    
    # Summary
    Write-Host "`n    ISSUES:"
    if ($issues.Count -eq 0) { Write-Host "    NONE" } else { foreach ($iss in $issues) { Write-Host "    * $iss" } }
    $allIssues += @{file=$dir; issues=$issues}

}

# GRAND TOTALS
Write-Host "`n========================================"
Write-Host "GRAND TOTALS ACROSS ALL 4 FILES"
Write-Host "========================================"
Write-Host "[20] entities=$grandEntities, claims=$grandClaims, relations=$grandRelations, definitions=$grandDefs, citations=$grandCits, rhetorical_devices=$grandRhet"
Write-Host "`nAll entity types across all files:"
foreach ($k in ($allEntityTypes.Keys | Sort-Object)) { Write-Host "  $($k): $($allEntityTypes[$k])" }
Write-Host "`nAll claim types across all files:"
foreach ($k in ($allClaimTypes.Keys | Sort-Object)) { Write-Host "  $($k): $($allClaimTypes[$k])" }
Write-Host "`nAll relation types across all files:"
foreach ($k in ($allRelTypes.Keys | Sort-Object)) { Write-Host "  $($k): $($allRelTypes[$k])" }

Write-Host "`n========================================"
Write-Host "SUMMARY OF ALL ISSUES"
Write-Host "========================================"
$totalIssues = 0
foreach ($fi in $allIssues) {
    if ($fi.issues.Count -gt 0) {
        Write-Host "`n$($fi.file):"
        foreach ($iss in $fi.issues) { Write-Host "  * $iss"; $totalIssues++ }
    }
}
Write-Host "`nTotal issue count: $totalIssues"
