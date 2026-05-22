#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json, os, sys
from collections import Counter, defaultdict

base = r"E:\1研究生\岭南大学\论文毕业\capstone\资料\新的内容开始了\local_upload\kg_runs_v2"
dirs = ["任叔永_等4篇", "孙伏园_等3篇", "张东荪_等3篇", "王平陵_等4篇"]

valid_etypes = {"人物","阵营/群体","概念","理论/学说/思潮","方法","学科","事件","历史事件","观点","论据","论证","立场","动机/目标","议题","阶段","预设","评价"}
valid_ctypes = {"positive_claim","negative_claim","neutral_claim","definitional_claim","comparative_claim","causal_claim","normative_claim","existential_claim","hypothetical_claim","predictive_claim"}
deprecated_rtypes = {"中外","为证据支持","相关","关注"}
valid_rtypes = {"支持","反对","改进","包含","基于","导致","等价于","与...一致","与...矛盾","限制","增强","削弱","解释","定义","举例","类比","被解释","被包含","被反驳","被引用","被支持","先于","后于","评述","异于","同于"}

all_etypes = Counter()
all_ctypes = Counter()
all_rtypes = Counter()
grand = {"entities":0,"claims":0,"relations":0,"defs":0,"cits":0,"rhet":0}
all_issues = []

for d in dirs:
    fp = os.path.join(base, d, "combined_extract.json")
    print(f"\n{'='*60}")
    print(f"FILE: {d}")
    print(f"{'='*60}")
    issues = []
    
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: JSON PARSE FAILED - {e}")
        continue
    
    # 1. schema_version
    sv = data.get("metadata",{}).get("schema_version","")
    print(f"[1] schema_version: {sv} {'OK' if sv=='lite_v3.0' else 'MISMATCH!'}")
    if sv != "lite_v3.0": issues.append(f"schema_version={sv}")
    
    # 2. Metadata
    m = data.get("metadata",{})
    keys = list(m.keys())
    print(f"[2] Metadata keys: {keys}")
    print(f"    article_count={m.get('article_count')}, segment_count={m.get('segment_count')}, model={m.get('model')}")
    
    # ENTITIES
    entities = data.get("entities",[])
    ec = len(entities)
    print(f"[3-6] Entity count: {ec}")
    etypes = Counter()
    empty_name = 0; empty_type = 0; eng_types = []; invalid_types = []
    for e in entities:
        t = e.get("type","")
        n = e.get("name","")
        if not t: empty_type += 1
        if not n: empty_name += 1
        if t and t not in valid_etypes:
            if any(c.isascii() and c.isalpha() for c in t[:2]):
                eng_types.append(t)
            else:
                invalid_types.append(t)
        etypes[t] += 1
        all_etypes[t] += 1
    
    print("    Entity types:")
    for k,v in etypes.most_common():
        print(f"      {k}: {v}")
    if eng_types:
        issues.append(f"English entity types ({len(eng_types)}): {set(eng_types)}")
    else:
        print("    NO English entity types - OK")
    if invalid_types:
        issues.append(f"Invalid entity types: {set(invalid_types)}")
    if empty_name: issues.append(f"Empty entity names: {empty_name}")
    if empty_type: issues.append(f"Empty entity types: {empty_type}")
    
    # CLAIMS
    claims = data.get("claims",[])
    print(f"[7-9] Claim count: {len(claims)}")
    ctypes = Counter()
    empty_speaker = 0; empty_claim_text = 0; eng_ctypes = []
    for c in claims:
        ct = c.get("claim_type","")
        ctypes[ct] += 1
        all_ctypes[ct] += 1
        if not c.get("speaker",""): empty_speaker += 1
        if not c.get("claim_text",""): empty_claim_text += 1
        if ct and ct not in valid_ctypes and any(ch.isascii() and ch.isalpha() for ch in ct[:2]):
            eng_ctypes.append(ct)
    print(f"    Claim types: {dict(ctypes)}")
    if eng_ctypes: issues.append(f"English claim types: {set(eng_ctypes)}")
    if empty_speaker: issues.append(f"Empty speaker: {empty_speaker}")
    if empty_claim_text: issues.append(f"Empty claim_text: {empty_claim_text}")
    
    # RELATIONS
    relations = data.get("relations",[])
    rcount = len(relations)
    print(f"[10-15] Relation count: {rcount}")
    rtypes = Counter()
    miss_stance = 0; miss_intensity = 0; miss_subtype = 0
    miss_head = 0; miss_tail = 0; miss_evidence = 0
    stance_oor = 0; intensity_oor = 0
    deprecated_found = []
    for r in relations:
        rt = r.get("relation_type","")
        rtypes[rt] += 1
        all_rtypes[rt] += 1
        if rt in deprecated_rtypes: deprecated_found.append(rt)
        if r.get("stance_score") is None: miss_stance += 1
        if r.get("intensity") is None: miss_intensity += 1
        if not r.get("relation_subtype",""): miss_subtype += 1
        if not r.get("head_id",""): miss_head += 1
        if not r.get("tail_id",""): miss_tail += 1
        if not r.get("evidence",""): miss_evidence += 1
        ss = r.get("stance_score")
        if ss is not None and (ss < -1 or ss > 1): stance_oor += 1
        intens = r.get("intensity")
        if intens is not None and (intens < 0 or intens > 1): intensity_oor += 1
    
    print(f"    Relation types: {dict(rtypes)}")
    if deprecated_found: issues.append(f"Deprecated relation types: {set(deprecated_found)}")
    if miss_stance: issues.append(f"Missing stance_score: {miss_stance}")
    if miss_intensity: issues.append(f"Missing intensity: {miss_intensity}")
    if miss_subtype: issues.append(f"Missing relation_subtype: {miss_subtype}")
    if miss_head: issues.append(f"Empty head_id: {miss_head}")
    if miss_tail: issues.append(f"Empty tail_id: {miss_tail}")
    if miss_evidence: issues.append(f"Empty evidence: {miss_evidence}")
    if stance_oor: issues.append(f"stance_score out of [-1,1]: {stance_oor}")
    if intensity_oor: issues.append(f"intensity out of [0,1]: {intensity_oor}")
    print(f"    stance_score missing={miss_stance}, OOR={stance_oor}")
    print(f"    intensity missing={miss_intensity}, OOR={intensity_oor}")
    print(f"    relation_subtype missing={miss_subtype}")
    print(f"    empty head={miss_head}, tail={miss_tail}, evidence={miss_evidence}")
    
    # Other sections
    defs = data.get("definitions",[])
    cits = data.get("citations",[])
    rhet = data.get("rhetorical_devices",[])
    print(f"[16] definitions: {len(defs)}")
    print(f"[17] citations: {len(cits)}")
    print(f"[18] rhetorical_devices: {len(rhet)}")
    
    # Duplicate entity IDs
    eids = [e.get("id","") for e in entities]
    dupes = {eid: c for eid, c in Counter(eids).items() if c > 1}
    if dupes:
        issues.append(f"Duplicate entity IDs: {dupes}")
    else:
        print("    No duplicate entity IDs - OK")
    
    # Sample relations
    print("[21] First 3 relations:")
    for i, r in enumerate(relations[:3]):
        print(f"    #{i}: {r.get('head_id')} --[{r.get('relation_type')}]--> {r.get('tail_id')} | stance={r.get('stance_score')} intensity={r.get('intensity')} subtype={r.get('relation_subtype')}")
    
    # Grand totals
    grand["entities"] += ec
    grand["claims"] += len(claims)
    grand["relations"] += rcount
    grand["defs"] += len(defs)
    grand["cits"] += len(cits)
    grand["rhet"] += len(rhet)
    
    print(f"\n    ISSUES: {'NONE' if not issues else ''}")
    for iss in issues:
        print(f"    * {iss}")
    all_issues.append({"file": d, "issues": issues})

# GRAND TOTALS
print(f"\n{'='*60}")
print("GRAND TOTALS ACROSS ALL 4 FILES")
print(f"{'='*60}")
print(f"[20] entities={grand['entities']}, claims={grand['claims']}, relations={grand['relations']}, definitions={grand['defs']}, citations={grand['cits']}, rhetorical_devices={grand['rhet']}")
print(f"\nAll entity types across all files:")
for k,v in all_etypes.most_common():
    print(f"  {k}: {v}")
print(f"\nAll claim types across all files:")
for k,v in all_ctypes.most_common():
    print(f"  {k}: {v}")
print(f"\nAll relation types across all files:")
for k,v in all_rtypes.most_common():
    print(f"  {k}: {v}")
print(f"\n{'='*60}")
print("SUMMARY OF ALL ISSUES")
print(f"{'='*60}")
total_issues = 0
for fi in all_issues:
    if fi["issues"]:
        print(f"\n{fi['file']}:")
        for iss in fi["issues"]:
            print(f"  * {iss}")
            total_issues += 1
print(f"\nTotal issue count: {total_issues}")
