"""
事后修复脚本 — 修补已经跑完的 combined_extract.json（中文原生版）
不重新调 API，不重新抽取，只做格式清洗。

用法：
  python fix_combined_json.py [数据根目录]
"""

import json, re, hashlib, shutil, traceback, sys, argparse
from pathlib import Path
from config import RUN_ROOT, WORKSPACE_DIR


# ============================================================
# 中文标准化映射表（LLM可能输出变体 → 统一为标准中文）
# ============================================================

ENTITY_CN_MAP = {
    # CN variations → standard CN
    "人物": "人物", "人名": "人物", "作者": "人物",
    "概念": "概念", "术语": "概念", "思想": "概念",
    "阵营": "阵营/群体", "阵营/群体": "阵营/群体", "群体": "阵营/群体",
    "主义": "主义/学说/理论", "学说": "主义/学说/理论", "理论": "主义/学说/理论",
    "方法": "方法", "方法论": "方法",
    "方法论原则": "方法论原则",
    "著作": "著作", "作品": "著作", "书籍": "著作",
    "文章": "文章", "论文": "文章",
    "组织": "组织", "机构": "组织",
    "地点": "地点", "位置": "地点",
    "历史事件": "历史事件", "事件": "历史事件",
    "观点": "观点", "立场": "观点",
    "论据": "论据", "前提": "论据",
    "结论": "结论",
    "评价": "评价",
    "比喻/类比": "比喻/类比", "比喻": "比喻/类比", "类比": "比喻/类比",
    "问题": "问题",
    "阶段": "阶段",
    "例证": "例证",
    "": "概念",
}

# EN → CN fallback (LLM sometimes outputs English types)
EN_TO_CN_ENTITY = {
    "Person": "人物", "Faction": "阵营/群体", "Concept": "概念",
    "Theory": "主义/学说/理论", "Method": "方法", "Principle": "方法论原则",
    "Book": "著作", "Article": "文章", "Event": "历史事件",
    "Viewpoint": "观点", "Argument": "论据", "Conclusion": "结论",
    "Evaluation": "评价", "Metaphor": "比喻/类比", "Question": "问题",
    "Phase": "阶段", "Example": "例证",
    "Organization": "组织", "Location": "地点", "Work": "著作",
    "Discipline": "概念", "Other": "概念", "person": "人物",
    "concept": "概念", "theory": "主义/学说/理论", "method": "方法",
    "viewpoint": "观点", "argument": "论据", "conclusion": "结论",
    "evaluation": "评价", "metaphor": "比喻/类比", "question": "问题",
    "phase": "阶段", "example": "例证", "PersonGroup": "人物",
}

# Allowed entity types in Chinese
VALID_ENTITY_CN = {
    "人物", "阵营/群体", "概念", "主义/学说/理论", "方法", "方法论原则",
    "著作", "文章", "组织", "地点", "历史事件",
    "观点", "论据", "结论", "评价", "比喻/类比", "问题", "阶段", "例证",
}

# 中文关系标准化：CN variations → standard CN
RELATION_CN_MAP = {
    "提到": "引用", "涉及": "引用", "宣传": "引用", "感谢": "引用",
    "支持": "支持", "赞同": "支持", "赞成": "支持", "肯定": "支持",
    "反对": "反对", "否定": "反对", "挑战": "反对", "攻击": "反对",
    "批评": "批评", "责难": "批评",
    "回应": "回应", "再回应": "回应", "回应于": "回应",
    "反驳": "反驳",
    "质疑": "质疑",
    "定义": "定义", "重新定义": "定义", "等同于": "定义",
    "区分": "区分", "区分于": "区分",
    "混淆": "混淆",
    "包含": "包含", "包含于": "包含",
    "属于": "属于",
    "导致": "导致", "造成": "导致", "支配": "导致", "引起": "导致", "形成": "导致",
    "归因于": "归因于",
    "解释": "解释", "说明": "解释", "表明": "解释",
    "证明": "证明", "推出": "推出",
    "作为论据支持": "作为论据支持", "作为例证": "作为例证",
    "作为理由反驳": "作为理由反驳",
    "作为反例反驳": "作为反例反驳",
    "归谬": "归谬",
    "类比": "类比", "比喻": "类比", "隐喻": "类比",
    "对比": "对比", "比较": "对比", "比": "对比",
    "引用": "引用", "引述": "引用", "转述": "引用", "著": "引用",
    "影响": "影响",
    "继承": "继承",
    "源自": "源自", "起于": "源自", "来自": "源自", "源于": "源自", "基于": "源自",
    "发展": "发展", "进步到": "发展", "发展到": "发展",
    "转化": "转化", "替代": "转化", "取代": "转化",
    "修正": "修正", "修改": "修正",
    "自相矛盾": "自相矛盾", "矛盾": "自相矛盾",
    "承接": "承接",
    "转折": "转折",
    "主张": "主张", "提出": "主张", "指出": "主张",
    "相关": "相关", "关联": "相关", "有关": "相关",
    "": "相关",
}

# EN → CN relation fallback (LLM sometimes outputs English)
EN_TO_CN_RELATION = {
    "MENTIONS": "引用", "CITES": "引用",
    "SUPPORTS": "支持", "OPPOSES": "反对",
    "CRITICIZES": "批评", "AFFIRMS": "支持",
    "DEFINES": "定义", "REDEFINES": "定义",
    "RESPONDS_TO": "回应",
    "COMPARES": "对比", "ANALOGY": "类比",
    "CAUSES": "导致",
    "PART_OF": "属于", "CONTAINS": "包含",
    "ASSOCIATED_WITH": "相关", "RELATED_TO": "相关",
    "QUESTIONS": "质疑", "REBUTS": "反驳",
    "EXPLAINS": "解释", "PROVES": "证明",
    "IMPLIES": "推出", "REDUCTIO": "归谬",
    "ATTRIBUTES_TO": "归因于", "DERIVES_FROM": "源自",
    "INFLUENCES": "影响", "DISTINGUISHES": "区分",
    "CONFUSES": "混淆",
    "EVIDENCE_FOR": "作为论据支持",
    "EVIDENCE_AGAINST": "作为理由反驳",
    "COUNTEREXAMPLE": "作为反例反驳",
    "INHERITS": "继承", "DEVELOPS": "发展",
    "TRANSFORMS": "转化", "CORRECTS": "修正",
    "CONTRADICTS": "自相矛盾", "CONTINUES": "承接",
    "TURNS": "转折", "PROPOSES": "主张",
    "OUTSIDE_OF": "区分", "EVALUATES": "评价",
    "APPLIED_TO": "相关", "USES": "相关", "OTHER": "相关",
}

# 需要填写 relation_subtype 的关系类型（中文）
NEEDS_SUBTYPE = {"批评", "反驳", "回应", "质疑", "评价", "归谬", "引用", "影响", "定义", "区分", "混淆",
                  "反对", "支持", "作为论据支持", "解释", "对比", "肯定", "攻击"}

# 已知别名映射（来自跨段归一化结果，可手动扩展）
KNOWN_ALIASES = {
    "赫诃尔": "赫胥黎",
    "托摩生": "汤姆生",
    "丁在君": "丁文江",
    "在君": "丁文江",
    "张嘉森": "张君劢",
    "胡适之": "胡适",
    "适之": "胡适",
    "梁任公": "梁启超",
    "任公": "梁启超",
    "梁卓如": "梁启超",
    "任叔永": "任鸿隽",
    "叔永": "任鸿隽",
    "独秀": "陈独秀",
    "吴老先生": "吴稚晖",
    "伏园": "孙伏园",
    "东荪": "张东荪",
    "宰平": "林宰平",
    "王抚五": "王星拱",
    "经农": "朱经农",
    "志韦": "陆志韦",
    "菊农": "瞿菊农",
    "瞿世英": "瞿菊农",
    "章炳麟": "章太炎",
    "杜威博士": "杜威",
    "罗素氏": "罗素",
    "柏氏": "柏格森",
    "皮氏": "皮尔逊",
    "詹姆斯": "詹姆士",
    "马哈": "马赫",
    "欧立克": "倭伊铿",
    "冯德": "翁特",
    "斯宾娜萨": "斯宾诺莎",
    "佛洛伊德": "佛罗特",
    "穆勒·约翰": "穆勒约翰",
}


def _s(x):
    return "" if x is None else str(x)


def coerce_entity_type(x):
    """标准化实体类型——中文输出"""
    x = _s(x).strip()
    if not x:
        return "概念"
    if x in VALID_ENTITY_CN:
        return x
    cn = ENTITY_CN_MAP.get(x) or ENTITY_CN_MAP.get(x.lower())
    if cn:
        return cn
    return EN_TO_CN_ENTITY.get(x, EN_TO_CN_ENTITY.get(x.lower(), "概念"))


def coerce_relation(x):
    """标准化关系类型——中文输出"""
    x = _s(x).strip()
    if not x:
        return "相关"
    cn = RELATION_CN_MAP.get(x) or RELATION_CN_MAP.get(x.lower())
    if cn:
        return cn
    return EN_TO_CN_RELATION.get(x, EN_TO_CN_RELATION.get(x.upper(), "相关"))


def _infer_relation_subtype(relation, evidence, polarity):
    """根据中文 relation + evidence + polarity 推断 relation_subtype"""
    if relation not in NEEDS_SUBTYPE:
        return "不适用"

    ev = (evidence or "")

    if relation == "批评":
        if any(w in ev for w in ["逻辑", "推理", "前提", "结论错误", "论证"]):
            return "逻辑反驳"
        if any(w in ev for w in ["事实", "实际", "现实", "不符合事实"]):
            return "事实质疑"
        if any(w in ev for w in ["证据不足", "缺乏证据", "没有证据", "毫无根据"]):
            return "证据不足批评"
        if any(w in ev for w in ["概念", "定义", "混淆", "混为一谈", "偷换概念"]):
            return "概念混淆批评"
        if any(w in ev for w in ["定义过宽", "定义过窄", "范围"]):
            return "定义过窄批评"
        if any(w in ev for w in ["道德", "良心", "人格", "责任"]):
            return "道德指责"
        if any(w in ev for w in ["危险", "危害", "后果严重", "流毒"]):
            return "道德风险批评"
        if any(w in ev for w in ["方法", "方法论", "研究方法"]):
            return "方法论批评"
        if any(w in ev for w in ["策略", "战术", "手段"]):
            return "论战策略批评"
        if any(w in ev for w in ["可笑", "荒唐", "岂有此理", "滑稽"]):
            return "讽刺"
        if any(w in ev for w in ["学术", "学问", "学理"]):
            return "学术质疑"
        if any(w in ev for w in ["自相矛盾", "前后不一致", "抵牾"]):
            return "前后矛盾批评"
        has_concession = any(w in ev for w in ["但是", "然而", "不过", "虽然", "尽管", "固然"])
        has_positive = any(w in ev for w in ["值得", "可贵", "有道理", "有理", "不错", "同意", "赞成", "肯定"])
        if has_concession and (has_positive or polarity == "mixed"):
            return "部分批评"
        if polarity == "mixed":
            return "混合评价"
        return "一般批评"

    if relation in ("反驳", "质疑"):
        if any(w in ev for w in ["逻辑", "推理", "论证"]):
            return "逻辑反驳"
        if any(w in ev for w in ["事实", "实际"]):
            return "事实质疑"
        if any(w in ev for w in ["证据", "根据"]):
            return "证据不足批评"
        if any(w in ev for w in ["学术", "方法"]):
            return "学术质疑"
        return "逻辑反驳" if relation == "反驳" else "学术质疑"

    if relation == "回应":
        if any(w in ev for w in ["反驳", "驳"]):
            return "逻辑反驳"
        if any(w in ev for w in ["同意", "赞成", "赞同"]):
            return "部分肯定"
        if any(w in ev for w in ["但是", "然而", "不过"]):
            has_positive = any(w in ev for w in ["同意", "赞成", "有理", "有理", "可以", "不错"])
            if has_positive:
                return "混合评价"
        return "一般批评"

    if relation == "评价":
        if polarity == "positive":
            return "部分肯定"
        if polarity == "negative":
            return "部分批评"
        return "混合评价"

    if relation == "归谬":
        return "归谬"

    if relation == "引用":
        return "援引权威"

    if relation == "影响":
        return "谱系归属"

    if relation in ("定义",):
        return "概念澄清"

    if relation == "区分":
        return "概念澄清"

    if relation == "混淆":
        return "概念混淆批评"

    if relation in ("支持", "作为论据支持"):
        if any(w in ev for w in ["权威", "引用", "如", "认为", "提出", "说过"]):
            return "援引权威"
        if polarity == "positive":
            return "肯定性支持"
        return "援引权威"

    if relation == "反对":
        if polarity == "negative":
            return "一般反对"
        if polarity == "mixed":
            return "混合评价"
        return "一般批评"

    if relation == "肯定":
        if polarity == "positive":
            return "完全肯定"
        return "部分肯定"

    if relation == "攻击":
        if any(w in ev for w in ["人身", "辱骂", "嘲讽", "讥"]):
            return "人身攻击"
        return "激烈批评"

    if relation == "解释":
        if any(w in ev for w in ["原因", "因为", "由于", "所以"]):
            return "因果解释"
        if any(w in ev for w in ["例如", "比如", "举例", "比方"]):
            return "举例解释"
        return "概念澄清"

    if relation == "对比":
        if any(w in ev for w in ["相反", "不同", "差异", "区别"]):
            return "差异对比"
        if any(w in ev for w in ["相似", "相同", "类似", "类比"]):
            return "相似对比"
        if any(w in ev for w in ["优", "胜于", "更好", "不如"]):
            return "优劣对比"
        return "一般对比"

    return "不适用"


def _normalize_claim(text):
    t = re.sub(r"\s+", "", text)
    t = t.replace("的", "").replace("了", "").replace("吗", "").replace("呢", "").replace("吧", "").replace("啊", "").replace("么", "")
    t = t.replace("的问题", "").replace("问题的", "")
    t = t.replace("那末", "").replace("那么", "")
    t = t.replace("，", "").replace("一方面", "方面")
    t = t.rstrip("。；：！？.;:!? ")
    t = t.replace("\u201c", "\"").replace("\u201d", "\"").replace("\u300c", "\"").replace("\u300d", "\"")
    return t


ASSOCIATED_RULES = [
    (r"译语|译名", "翻译关系"),
    (r"介乎.*之间|在.*之间", "介于"),
    (r"以外|之外", "以外"),
    (r"包括|包含|包在|分为", "包含"),
    (r"影响", "影响"),
    (r"骂|批评|挑剔|批判", "批评"),
    (r"支持|赞同|赞成|以为然", "支持"),
    (r"反对|反驳|否定|排斥", "反对"),
    (r"引|引用|转录", "引用"),
    (r"定义|称为|意思是", "定义"),
]


def refine_generic_relations(combined):
    """将 相关/其他 按 evidence 模式细化为具体关系类型"""
    changed = 0
    for r in combined.get("relations", []):
        ev = r.get("evidence", "")
        rel = r.get("relation", "")
        if rel in ("相关", "ASSOCIATED_WITH"):
            for pattern, target_rel in ASSOCIATED_RULES:
                if re.search(pattern, ev):
                    r["relation"] = target_rel
                    changed += 1
                    break
        elif rel in ("其他", "OTHER"):
            if "以外" in ev or "之外" in ev:
                r["relation"] = "以外"
                changed += 1
            else:
                for pattern, target_rel in ASSOCIATED_RULES:
                    if re.search(pattern, ev):
                        r["relation"] = target_rel
                        changed += 1
                        break
    return changed


def dedupe_similar_claims(combined):
    """按 claim 文本标准化后去重，保留较长的版本"""
    claims = [c for c in combined.get("claims", []) if c.get("claim", "").strip()]
    seen = {}
    for c in claims:
        text = c.get("claim", "").strip()
        key = _normalize_claim(text)
        if key in seen:
            if len(text) > len(seen[key].get("claim", "")):
                seen[key] = c
        else:
            seen[key] = c
    before = len(combined.get("claims", []))
    combined["claims"] = list(seen.values())
    return before - len(combined["claims"])


def stable_hash(s, n=10):
    return hashlib.sha1(str(s).encode("utf-8", errors="ignore")).hexdigest()[:n]


def fix_missing_id(items, prefix, keys_for_hash):
    fixed = 0
    for i, item in enumerate(items):
        if not item.get("id"):
            raw = "".join(_s(item.get(k, "")) for k in keys_for_hash)
            item["id"] = f"{prefix}_{stable_hash(raw + str(i), 12)}"
            fixed += 1
    return fixed


def drop_empty(items, field):
    before = len(items)
    items[:] = [x for x in items if _s(x.get(field, "")).strip()]
    return before - len(items)


def fix_claims_schema(claims):
    fixed = 0
    for c in claims:
        if not c.get("claim") and c.get("content"):
            c["claim"] = c["content"]
            if "content" in c: del c["content"]
            fixed += 1
        if not c.get("claim") and c.get("text"):
            c["claim"] = c["text"]
            if "text" in c: del c["text"]
            fixed += 1
        if not c.get("claim_type") and c.get("type"):
            c["claim_type"] = c["type"]
            if "type" in c: del c["type"]
            fixed += 1
    return fixed


def fix_entity_type_to_claim(items):
    """将完整命题类实体（不是标准实体类型）移入 claims"""
    moved = []
    kept = []
    for e in items:
        if e.get("type", "") in ("Claim",):
            c = {
                "id": e.get("id", ""),
                "speaker": "",
                "claim": e.get("name", ""),
                "target": "",
                "claim_type": "不明",
                "claim_status": "不明",
                "polarity": "neutral",
                "evidence": e.get("evidence", ""),
                "confidence": e.get("confidence", 0.5),
                "segment_id": e.get("segment_id", ""),
                "article_id": e.get("article_id", ""),
                "source_author": e.get("source_author", ""),
            }
            moved.append(c)
        else:
            kept.append(e)
    return kept, moved


def add_missing_metadata(items, default_meta):
    for item in items:
        for k, v in default_meta.items():
            if k not in item:
                item[k] = v


def fill_relation_subtype(relations):
    n = 0
    for r in relations:
        if r.get("relation_subtype") and r.get("relation_subtype") != "不适用":
            continue
        rel = r.get("relation", "")
        ev = r.get("evidence", "")
        pol = r.get("polarity", "neutral")
        subtype = _infer_relation_subtype(rel, ev, pol)
        r["relation_subtype"] = subtype
        if subtype != "不适用":
            n += 1
    return n


def fix_bridge_entities(entities, default_meta, all_segment_ids=None):
    fixed = 0
    if all_segment_ids is None:
        all_segment_ids = set()
    for e in entities:
        if e.get("source") == "cross_segment_bridge":
            old_type = e.get("type", "")
            new_type = coerce_entity_type(old_type)
            if new_type != old_type:
                e["type"] = new_type
                fixed += 1
            for k, v in default_meta.items():
                if k not in e:
                    e[k] = v
                    fixed += 1
            if not e.get("segment_id") and e.get("evidence"):
                ev = e["evidence"]
                m = re.search(r"(s\d+)", ev)
                if m:
                    e["segment_id"] = m.group(1)
                    fixed += 1
            if not e.get("segment_id") and all_segment_ids:
                e["segment_id"] = next(iter(all_segment_ids))
                fixed += 1
    return fixed


def fix_source_target_to_head_tail(relations):
    fixed = 0
    for r in relations:
        if "source" in r and "head" not in r:
            r["head"] = r.pop("source")
            fixed += 1
        if "target" in r and "tail" not in r:
            r["tail"] = r.pop("target")
            fixed += 1
    return fixed


def remove_zombie_entities(combined):
    """删除未被任何关系引用的孤立实体"""
    ents = combined.get("entities", [])
    used = set()
    for r in combined.get("relations", []):
        used.add(r.get("head", ""))
        used.add(r.get("tail", ""))
    used.discard("")
    before = len(ents)
    combined["entities"] = [e for e in ents if e.get("name", "") in used]
    return before - len(combined["entities"])


def merge_known_aliases(combined):
    """合并已知别名实体：将别名替换为正则名，更新所有引用"""
    changed = 0
    ents = combined.get("entities", [])
    alias_names = set(KNOWN_ALIASES.keys())
    for alias, canon in KNOWN_ALIASES.items():
        # 跳过没出现在实体列表中的
        if not any(e.get("name") == alias for e in ents):
            continue
        # 更新 relations
        for r in combined.get("relations", []):
            for k in ("head", "tail"):
                if r.get(k, "") == alias:
                    r[k] = canon
                    changed += 1
        # 删除别名实体
        before = len(ents)
        kept = [e for e in ents if e.get("name", "") != alias]
        combined["entities"] = kept
        after = len(kept)
        if before != after:
            changed += before - after
    return changed


def ensure_author_entity(combined):
    """确保文章作者作为实体存在于 entities 中"""
    ents = combined.get("entities", [])
    existing_names = set()
    for e in ents:
        existing_names.add(e.get("name", ""))
        existing_names.add(e.get("canonical_name", ""))
    existing_names.discard("")

    added = 0
    for art in combined.get("articles", []):
        author = art.get("source_author", "").strip()
        if not author:
            continue
        author_canon = KNOWN_ALIASES.get(author, author)
        all_names = {author, author_canon}
        if not all_names & existing_names:
            ent_id = f"author_entity_{hashlib.md5(author_canon.encode()).hexdigest()[:8]}"
            ents.append({
                "id": ent_id,
                "name": author_canon,
                "canonical_name": author_canon,
                "type": "人物",
                "evidence": f"文章作者: {author}",
                "confidence": 1.0,
                "segment_id": "",
                "article_id": art.get("article_id", ""),
                "article_title": art.get("article_title", ""),
                "source_author": author,
                "source_file": art.get("source_file", ""),
            })
            combined["entities"] = ents
            added += 1
    return added


SEGMENT_ID_PATTERN = re.compile(r"^s\d{3,4}$")

def _sanitize_seg_id(seg_id):
    if not seg_id or not isinstance(seg_id, str):
        return ""
    seg_id = seg_id.strip()
    if SEGMENT_ID_PATTERN.match(seg_id):
        return seg_id
    m = re.search(r"s\d{3,4}", seg_id)
    if m:
        return m.group(0)
    return ""


def fix_corrupted_segment_ids(combined):
    """修复损坏的 segment_id（如 's000 Wiggle'）"""
    fixed = 0
    for section in ["entities", "claims", "relations", "definitions", "citations", "rhetorical_devices"]:
        for item in combined.get(section, []):
            old_id = item.get("segment_id", "")
            new_id = _sanitize_seg_id(old_id)
            if new_id and new_id != old_id:
                item["segment_id"] = new_id
                fixed += 1
    return fixed


def cleanup(combined):
    changed = 0

    default_meta = {
        "article_id": "",
        "article_title": "",
        "source_author": "",
        "source_file": "",
    }

    # 收集已有 segment_id
    all_seg_ids = set()
    for seg in combined.get("articles", []):
        aid = seg.get("article_id", "")
        if aid: all_seg_ids.add(aid)
    for e in combined.get("entities", []):
        sid = e.get("segment_id", "")
        if sid: all_seg_ids.add(sid)
    for c in combined.get("claims", []):
        sid = c.get("segment_id", "")
        if sid: all_seg_ids.add(sid)

    # 1. 补 id
    for field, prefix, keys in [
        ("entities", "e", ["name", "type", "segment_id"]),
        ("claims", "c", ["speaker", "claim", "segment_id"]),
        ("relations", "r", ["head", "relation", "tail", "segment_id"]),
        ("definitions", "def", ["term", "definition", "segment_id"]),
        ("citations", "cit", ["quoted_author", "quoted_claim", "segment_id"]),
        ("rhetorical_devices", "rh", ["expression", "device_type", "segment_id"]),
    ]:
        n = fix_missing_id(combined.get(field, []), prefix, keys)
        if n:
            print(f"  {field}: 补 {n} 个 id")
            changed += n

    # 2. 删空 relation tail/head
    n = drop_empty(combined.get("relations", []), "tail")
    if n: print(f"  relations: 删除 {n} 条空 tail"); changed += n
    n = drop_empty(combined.get("relations", []), "head")
    if n: print(f"  relations: 删除 {n} 条空 head"); changed += n

    # 3. 修正 claims schema
    n = fix_claims_schema(combined.get("claims", []))
    if n: print(f"  claims: 修正 {n} 条 schema"); changed += n

    # 4. type=Claim 的 entity → claim
    ents = combined.get("entities", [])
    kept_ents, moved_claims = fix_entity_type_to_claim(ents)
    combined["entities"] = kept_ents
    if moved_claims:
        combined.setdefault("claims", []).extend(moved_claims)
        print(f"  entities→claims: 转移 {len(moved_claims)} 条")
        changed += len(moved_claims)

    # 5. 统一关系类型 → 中文
    n = 0
    for r in combined.get("relations", []):
        old = r.get("relation", "")
        new = coerce_relation(old)
        if new != old:
            r["relation"] = new
            n += 1
    if n: print(f"  relations: 转换 {n} 条关系类型"); changed += n

    # 5b. 细化通用关系类型
    n = refine_generic_relations(combined)
    if n: print(f"  relations: 细化 {n} 条通用关系"); changed += n

    # 6. 统一实体类型 → 中文
    n = 0
    for e in combined.get("entities", []):
        old = e.get("type", "")
        new = coerce_entity_type(old)
        if new != old:
            e["type"] = new
            n += 1
    if n: print(f"  entities: 转换 {n} 条实体类型"); changed += n

    # 7. source/target → head/tail
    n = fix_source_target_to_head_tail(combined.get("relations", []))
    if n: print(f"  relations: 转换 {n} 条 source/target"); changed += n

    # 8. 补缺失 metadata
    add_missing_metadata(combined.get("entities", []), default_meta)
    add_missing_metadata(combined.get("claims", []), default_meta)
    add_missing_metadata(combined.get("relations", []), default_meta)

    # 9. 修复桥接实体
    n = fix_bridge_entities(combined.get("entities", []), default_meta, all_seg_ids)
    if n: print(f"  entities: 修复桥接实体 {n} 处"); changed += n

    # 9b. claims 文本去重
    n = dedupe_similar_claims(combined)
    if n: print(f"  claims: 去重 {n} 条"); changed += n

    # 10. 填充 relation_subtype
    n = fill_relation_subtype(combined.get("relations", []))
    if n: print(f"  relations: 填充 {n} 条 relation_subtype"); changed += n

    # 10b. 清除孤立实体
    n = remove_zombie_entities(combined)
    if n: print(f"  entities: 删除 {n} 条孤立节点"); changed += n

    # 10c. 合并已知别名
    n = merge_known_aliases(combined)
    if n: print(f"  entities: 合并 {n} 处别名引用"); changed += n

    # 10d. 确保作者实体存在
    n = ensure_author_entity(combined)
    if n: print(f"  entities: 添加 {n} 个作者实体"); changed += n

    # 10e. 修复损坏的 segment_id
    n = fix_corrupted_segment_ids(combined)
    if n: print(f"  segment_id: 修复 {n} 处损坏"); changed += n

    # 11. 安全去重
    for field in ["entities", "claims", "relations", "definitions", "citations", "rhetorical_devices"]:
        items = combined.get(field, [])
        before = len(items)
        seen = set()
        kept = []
        for item in items:
            sig = json.dumps({k: item.get(k, "") for k in sorted(item.keys()) if k != "id"},
                             ensure_ascii=False, sort_keys=True)
            if sig not in seen:
                seen.add(sig)
                kept.append(item)
        combined[field] = kept
        after = len(combined.get(field, []))
        if before != after:
            print(f"  {field}: 去重 {before - after} 条")
            changed += before - after

    # 12. 更新 counts
    if "counts" in combined:
        for field in ["entities", "claims", "relations", "definitions",
                       "citations", "rhetorical_devices", "uncertainties"]:
            combined["counts"][field] = len(combined.get(field, []))

    return changed


def find_all_combined_json(custom_root=None):
    if custom_root:
        kg_root = Path(custom_root)
    else:
        kg_root = Path(RUN_ROOT)
    if not kg_root.exists():
        return []
    return sorted(kg_root.rglob("combined_extract.json"))


def main():
    parser = argparse.ArgumentParser(description="修复 combined_extract.json（中文原生版）")
    parser.add_argument("data_root", nargs="?", default=None,
                        help="数据根目录（可选）")
    args = parser.parse_args()

    combined_paths = find_all_combined_json(args.data_root)
    if not combined_paths:
        print("未找到 combined_extract.json，尝试默认路径...")
        for p in [WORKSPACE_DIR, Path(args.data_root) if args.data_root else None]:
            if p and p.exists():
                for f in p.glob("**/combined_extract.json"):
                    if "raw_outputs" not in str(f):
                        combined_paths.append(f)
        combined_paths = list(set(combined_paths))

    if not combined_paths:
        print("仍未找到。请手动指定路径。")
        return

    for cp in combined_paths:
        print(f"\n{'='*60}")
        print(f"修复: {cp}")
        print(f"{'='*60}")
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  读取失败: {e}")
            continue

        before = len(json.dumps(data, ensure_ascii=False))
        n = cleanup(data)
        after = len(json.dumps(data, ensure_ascii=False))

        if n == 0 and after == before:
            print(f"  无需修改")
            continue

        backup = cp.with_suffix(".json.bak")
        shutil.copy2(cp, backup)
        print(f"  备份: {backup}")

        cp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  共修复/删除 {n} 处")
        print(f"  文件大小: {before} → {after} 字符")
        print(f"  已保存: {cp}")

    print(f"\n全部修复完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"错误: {e}")
        traceback.print_exc()
        sys.exit(1)
