"""
后处理：在 combine_segment_outputs 之后调用
功能：
A. 东荪按 → source_author = 张东荪
B. 别名归一化（张君→张君劢等）
C. claim_type=Definition → definitions
D. TRANSLATION_OF 过滤（仅保留英文译名）
E. OTHER → OUTSIDE_OF
F. claims 去重
G. rhetorical_devices 补取
"""

import re
import json

# ============================================================
# A. 标题→作者映射（处理东荪按等）
# ============================================================

TITLE_AUTHOR_MAP = {
    "东荪按": "张东荪",
    "独秀按": "陈独秀",
    "适之按": "胡适",
    "在君按": "丁文江",
    "君劢按": "张君劢",
    "伏园按": "孙伏园",
    "宰平按": "林宰平",
}

def fix_section_author(combined: dict, segments: list) -> dict:
    """根据 article_title 修复 source_author"""
    seg_lookup = {s["segment_id"]: s for s in segments}

    for art in combined.get("articles", []):
        raw_title = art.get("article_title", "")
        # 去掉末尾冒号等
        clean_title = raw_title.rstrip(":：").strip()
        if clean_title in TITLE_AUTHOR_MAP:
            author = TITLE_AUTHOR_MAP[clean_title]
            art["source_author"] = author

    for item in combined.get("entities", []):
        seg = seg_lookup.get(item.get("segment_id", ""))
        if seg:
            sec_author = seg.get("section_author", "")
            if sec_author and sec_author in TITLE_AUTHOR_MAP:
                item["source_author"] = TITLE_AUTHOR_MAP[sec_author]
            elif item.get("article_title", "").rstrip(":：").strip() in TITLE_AUTHOR_MAP:
                item["source_author"] = TITLE_AUTHOR_MAP[item["article_title"].rstrip(":：").strip()]

    for item in combined.get("claims", []):
        title_clean = item.get("article_title", "").rstrip(":：").strip()
        if title_clean in TITLE_AUTHOR_MAP:
            expected = TITLE_AUTHOR_MAP[title_clean]
            # 修复 speaker
            speaker = item.get("speaker", "")
            if speaker in {"", "作者", "我", "我们", "吾", "余", "笔者"}:
                item["speaker"] = expected
            # 修复 target 别名
            item["target"] = alias_map.get(item.get("target", ""), item.get("target", ""))
        else:
            # 也检查 segment_id 是否属于东荪按等段落
            seg = seg_lookup.get(item.get("segment_id", ""))
            if seg:
                sec_author = seg.get("section_author", "")
                if sec_author in TITLE_AUTHOR_MAP:
                    expected = TITLE_AUTHOR_MAP[sec_author]
                    speaker = item.get("speaker", "")
                    if speaker in {"", "作者", "我", "我们", "吾", "余", "笔者"}:
                        item["speaker"] = expected

    for item in combined.get("relations", []):
        title_clean = item.get("article_title", "").rstrip(":：").strip()
        if title_clean in TITLE_AUTHOR_MAP:
            expected = TITLE_AUTHOR_MAP[title_clean]
            head = item.get("head", "")
            if head in {"", "作者", "我", "我们", "吾", "余", "笔者"}:
                item["head"] = expected
            # tail 别名归一化
            item["tail"] = alias_map.get(item.get("tail", ""), item.get("tail", ""))
        else:
            seg = seg_lookup.get(item.get("segment_id", ""))
            if seg:
                sec_author = seg.get("section_author", "")
                if sec_author in TITLE_AUTHOR_MAP:
                    expected = TITLE_AUTHOR_MAP[sec_author]
                    head = item.get("head", "")
                    if head in {"", "作者", "我", "我们", "吾", "余", "笔者"}:
                        item["head"] = expected

    for item in combined.get("citations", []):
        title_clean = item.get("article_title", "").rstrip(":：").strip()
        if title_clean in TITLE_AUTHOR_MAP:
            expected = TITLE_AUTHOR_MAP[title_clean]
            citer = item.get("citer", "")
            if citer in {"", "作者", "我", "我们", "吾", "余", "笔者"}:
                item["citer"] = expected

    return combined


# ============================================================
# B. 别名映射（从别名汇总.txt 提取）
# ============================================================

ALIAS_MAP = {
    # 丁文江
    "丁在君": "丁文江",
    "在君": "丁文江",
    "丁君": "丁文江",
    "丁先生": "丁文江",
    "在君先生": "丁文江",
    "在公": "丁文江",
    "丁在君先生": "丁文江",
    # 张君劢
    "张嘉森": "张君劢",
    "张君": "张君劢",
    "君劢": "张君劢",
    "张先生": "张君劢",
    "君劢先生": "张君劢",
    "张君劢先生": "张君劢",
    "张氏": "张君劢",
    # 胡适
    "胡适之": "胡适",
    "适之": "胡适",
    "胡先生": "胡适",
    "胡氏": "胡适",
    "胡适之先生": "胡适",
    # 梁启超（梁先生 在文章语境中区分，见 normalize_aliases）
    "梁任公": "梁启超",
    "任公": "梁启超",
    "梁卓如": "梁启超",
    "梁氏": "梁启超",
    # 陈独秀
    "独秀": "陈独秀",
    "独秀先生": "陈独秀",
    # 吴稚晖
    "吴老先生": "吴稚晖",
    "吴先生": "吴稚晖",
    # 孙伏园
    "伏园": "孙伏园",
    "伏园先生": "孙伏园",
    # 张东荪
    "东荪": "张东荪",
    # 林宰平
    "宰平": "林宰平",
    "林先生": "林宰平",
    "林氏": "林宰平",
    # 唐钺
    "唐钺先生": "唐钺",
    "唐氏": "唐钺",
    # 王星拱
    "王抚五": "王星拱",
    "王氏": "王星拱",
    # 任鸿隽（任叔永）
    "任叔永": "任鸿隽",
    "任君": "任鸿隽",
    "任先生": "任鸿隽",
    "叔永": "任鸿隽",
    "任氏": "任鸿隽",
    # 范寿康
    "范先生": "范寿康",
    # 朱经农
    "经农": "朱经农",
    # 陆志韦
    "志韦": "陆志韦",
    "志韦先生": "陆志韦",
    # 瞿菊农
    "菊农": "瞿菊农",
    "瞿世英": "瞿菊农",
    # 甘蛰仙
    "蛰仙": "甘蛰仙",
    # 梁漱溟（梁先生 在文章语境中区分，见 normalize_aliases）
    # 章太炎
    "章炳麟": "章太炎",
    # 杜威
    "杜威博士": "杜威",
    # 罗素
    "罗素氏": "罗素",
    # 西方学者
    "柏氏": "柏格森",
    "皮氏": "皮尔逊",
    "詹姆斯": "詹姆士",
    "马哈": "马赫",
    "欧立克": "倭伊铿",
    "汤姆生": "托摩生",
    "冯德": "翁特",
    "斯宾娜萨": "斯宾诺莎",
    "佛洛伊德": "佛罗特",
    "穆勒·约翰": "穆勒约翰",
    "穆勒约翰": "穆勒约翰",
}

alias_map = ALIAS_MAP  # 方便其他函数引用

PERSON_GROUPS = {"丁张两君", "丁张两先生", "两位", "双方", "两方", "两造", "两先生", "两军主帅"}

GENERIC_PERSON_TERMS = {"诸公", "专门家", "心理学者"}


# ============================================================
# B 函数：别名归一化入口
# ============================================================

def normalize_aliases(combined: dict) -> dict:
    """对 entities/claims/relations 应用 ALIAS_MAP"""

    # --- Step 0: 为梁先生构建文章级消歧上下文 ---
    # 收集每篇文章中出现的实体原始名称
    article_raw_names = {}
    for e in combined.get("entities", []):
        aid = e.get("article_id", "")
        raw = e.get("name", "")
        article_raw_names.setdefault(aid, set()).add(raw)

    def resolve_mr_liang(aid: str) -> str:
        """根据文章上下文判断梁先生 → 梁启超 / 梁漱溟"""
        names = article_raw_names.get(aid, set())
        has_qichao = any(alias_map.get(n, "") == "梁启超" or n == "梁启超" for n in names)
        has_shuming = any(alias_map.get(n, "") == "梁漱溟" or n == "梁漱溟" for n in names)
        if has_shuming and not has_qichao:
            return "梁漱溟"
        return "梁启超"  # 默认：科玄论战中梁任公更常见

    def map_name(raw: str, aid: str = "") -> str:
        if raw == "梁先生":
            return resolve_mr_liang(aid)
        return alias_map.get(raw, raw)

    # --- Step 1: entities ---
    for e in combined.get("entities", []):
        raw = e.get("name", "")
        e["original_name"] = raw
        e["name"] = map_name(raw, e.get("article_id", ""))

        raw_canonical = e.get("canonical_name", raw)
        if raw.startswith("《"):
            e["canonical_name"] = raw
        else:
            e["canonical_name"] = map_name(raw_canonical, e.get("article_id", ""))

        if e["name"] in PERSON_GROUPS or raw in PERSON_GROUPS:
            e["type"] = "PersonGroup"
        if e["name"] in GENERIC_PERSON_TERMS or raw in GENERIC_PERSON_TERMS:
            e["type"] = "概念"

    # --- Step 2: claims ---
    for c in combined.get("claims", []):
        c["speaker"] = map_name(c.get("speaker", ""), c.get("article_id", ""))
        c["target"] = map_name(c.get("target", ""), c.get("article_id", ""))

    # --- Step 3: relations ---
    for r in combined.get("relations", []):
        r["head"] = map_name(r.get("head", ""), r.get("article_id", ""))
        r["tail"] = map_name(r.get("tail", ""), r.get("article_id", ""))

    # --- Step 4: citations ---
    for c in combined.get("citations", []):
        c["citer"] = map_name(c.get("citer", ""), c.get("article_id", ""))
        c["quoted_author"] = map_name(c.get("quoted_author", ""), c.get("article_id", ""))

    return combined


# ============================================================
# C. claim_type=Definition → definitions
# ============================================================

def extract_definitions(combined: dict) -> dict:
    """将 claim_type=Definition 的 claim 转为 definition，过滤非真定义"""

    def is_genuine_definition(term: str, definition: str, evidence: str) -> bool:
        """判断是否是真定义：排除问句、清单、关系描述、泛指、碎片化 term"""

        # 排除问句
        if "?" in definition or "？" in definition:
            return False

        # 排除列举、清单（含"分为""包括但不限于"等）
        if re.search(r"^(分为|包括|包含|列举)", definition):
            return False

        # 排除"X对于Y的关系"这类非定义
        if re.match(r"^[^是]+对于[^是]+的关系", definition):
            return False

        # 排除关系描述（介乎…之间、在…之间、包在…范围）
        if re.search(r"介乎.*之间|在.*之间", definition):
            return False
        if re.search(r"包在.*范围", definition):
            return False

        # 排除泛指（所谓）
        if re.search(r"所谓", definition):
            return False

        # 排除碎片化 term：空、太短（<2）、以数字开头（"第二部分"）、无中文实词
        if not term or len(term) < 2:
            return False
        if re.match(r"^\d", term):
            return False
        if not re.search(r"[\u4e00-\u9fff]{2,}", term):
            return False
        # term 以系词/助词结尾 → 文本切分错误（"人生观就"→截断在"就"）
        if re.search(r"[是就即便乃了]$", term):
            return False

        # definition 必须含「是/即是/就是/便是/乃是」
        if not re.search(r"(?:即|就|便|乃)?是", definition):
            return False

        # 排除"位置定义"：definition 含"以外"/"之外"且 term 不直接跟在"是/即"后面
        # 如"玄学与科学以外又有一个名词即是哲学"——这不是在定义"哲学"
        if re.search(r"以外|之外", definition):
            # 检查"是/即"后面紧接的是否是 term
            copula_m = re.search("(?:即|就|便|乃)?是[\u201c\u201d\"']?(?P<term_candidate>[^\uff0c\u3002,.]+)", definition)
            if copula_m and copula_m.group("term_candidate") != term:
                return False

        # definition 必须包含 term（或 evidence 中含"X是Y"结构）
        if term not in definition:
            if not re.search(rf"{re.escape(term)}[即就便乃]?是", evidence):
                return False

        return True

    new_defs = []
    kept_claims = []

    for c in combined.get("claims", []):
        ct = c.get("claim_type", "").lower()
        if ct == "definition":
            term = c.get("target", "")
            definition = c.get("claim", "")
            definer = c.get("speaker", "")
            evidence = c.get("evidence", "")

            if not term:
                m = re.match(r"^([^是]+)是", evidence)
                if m:
                    term = m.group(1).strip()

            if term and definition and is_genuine_definition(term, definition, evidence):
                new_defs.append({
                    "id": f"def{len(new_defs) + 1}",
                    "term": term,
                    "definition": definition,
                    "definer": definer,
                    "evidence": evidence,
                    "article_id": c.get("article_id", ""),
                    "article_title": c.get("article_title", ""),
                    "source_author": c.get("source_author", ""),
                    "segment_id": c.get("segment_id", ""),
                })
            continue
        kept_claims.append(c)

    combined["definitions"] = new_defs
    combined["claims"] = kept_claims

    return combined


# ============================================================
# D0. PART_OF 方向修复
# ============================================================

SUPERSET = {"哲学", "科学", "玄学"}
SUBSET = {"人生哲学", "社会学", "心理学", "教育学", "认识论", "本体论", "宇宙论", "人生观"}

def fix_part_of_direction(combined: dict) -> dict:
    """
    属于/包含 方向统一：小概念 属于 大概念，大概念 包含 小概念。
    - SUPERSET (领域) > SUBSET (分支): 翻转，如 哲学 属于 人生哲学 → 人生哲学 属于 哲学
    - SUPERSET > 一般名词: 翻转
    - SUBSET > 一般名词: 若 tail 不在 SUPERSET，翻转
    """
    for r in combined.get("relations", []):
        rel = r.get("relation", "")
        if rel not in ("属于", "包含"):
            continue
        head = r.get("head", "")
        tail = r.get("tail", "")
        head_in_super = head in SUPERSET
        tail_in_super = tail in SUPERSET
        head_in_sub = head in SUBSET
        tail_in_sub = tail in SUBSET

        should_flip = False
        # "属于": A 属于 B → A is subset/small, B is superset/big
        # "包含": A 包含 B → A is superset/big, B is subset/small (opposite direction)
        if rel == "属于":
            if head_in_super and tail_in_sub:
                should_flip = True  # 大概念 属于 小概念 → 翻转
            elif head_in_super and not tail_in_super and not tail_in_sub:
                should_flip = True
            elif head_in_sub and not tail_in_super and not tail_in_sub:
                should_flip = True
        else:  # "包含"
            if head_in_sub and tail_in_super:
                should_flip = True  # 小概念 包含 大概念 → 翻转
            elif head_in_sub and not tail_in_super and not tail_in_sub and tail_in_super:
                should_flip = True

        if should_flip:
            r["head"], r["tail"] = r["tail"], r["head"]
            r["head_type"], r["tail_type"] = r["tail_type"], r["head_type"]
    return combined


# ============================================================
# D. TRANSLATION_OF 过滤
# ============================================================

ENGLISH_PATTERN = re.compile(r"[a-zA-Z]{3,}")

def has_english_origin(term: str) -> bool:
    """判断 term 是否本身是英文术语或"X的译语"结构"""
    if ENGLISH_PATTERN.search(term):
        return True
    return False


def filter_translation_of(combined: dict) -> dict:
    """
    只保留 tail 是英文术语 或 evidence 含"译语"的翻译/译名关系。
    注：当前中文 prompt 不使用"翻译关系"等类型，此函数主要为兼容旧数据。
    """

    kept = []
    for r in combined.get("relations", []):
        rel = r.get("relation", "")
        if rel not in ("TRANSLATION_OF", "翻译关系", "翻译"):
            kept.append(r)
            continue

        tail = r.get("tail", "")
        evidence = r.get("evidence", "")

        if has_english_origin(tail):
            kept.append(r)
        elif "译语" in evidence or "译名" in evidence:
            kept.append(r)
        else:
            # 这条 TRANSLATION_OF 是误抽，丢掉
            continue

    combined["relations"] = kept
    return combined


# ============================================================
# E. ASSOCIATED_WITH 细化 + OTHER 修复
# ============================================================

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

def refine_relations(combined: dict) -> dict:
    """将 相关/其他 按 evidence 模式细化为具体关系类型"""
    for r in combined.get("relations", []):
        ev = r.get("evidence", "")
        rel = r.get("relation", "")

        if rel in ("相关", "ASSOCIATED_WITH"):
            for pattern, target_rel in ASSOCIATED_RULES:
                if re.search(pattern, ev):
                    r["relation"] = target_rel
                    break

        elif rel in ("其他", "OTHER"):
            if "以外" in ev or "之外" in ev:
                r["relation"] = "以外"
            else:
                for pattern, target_rel in ASSOCIATED_RULES:
                    if re.search(pattern, ev):
                        r["relation"] = target_rel
                        break
    return combined


# ============================================================
# F. claims 去重（按 claim 文本）
# ============================================================

def _normalize_claim(text: str) -> str:
    """标准化 claim 文本：去空格、去助词/连接词、去末尾标点、统一引号"""
    t = re.sub(r"\s+", "", text)
    # 去常见助词/语气词
    for w in ("的", "了", "吗", "呢", "吧", "啊", "么"):
        t = t.replace(w, "")
    # 去"的问题"/"问题的"/"问题"
    t = t.replace("的问题", "").replace("问题的", "")
    # 去"那末"/"那么"
    t = t.replace("那末", "").replace("那么", "")
    # 全角逗号也去除（非仅末尾），统一"一方面"→"方面"
    t = t.replace("，", "").replace("一方面", "方面")
    t = t.rstrip("。；：！？.;:!? ")
    t = t.replace("“", '"').replace("”", '"').replace("「", '"').replace("」", '"')
    return t


def dedupe_claims(combined: dict) -> dict:
    # 第一轮：去空
    all_claims = [c for c in combined.get("claims", []) if c.get("claim", "").strip()]

    # 第二轮：按标准化 key 去重，保留长度较长的版本
    seen = {}
    for c in all_claims:
        text = c.get("claim", "").strip()
        key = _normalize_claim(text)
        if key in seen:
            existing_len = len(seen[key].get("claim", ""))
            if len(text) > existing_len:
                seen[key] = c
        else:
            seen[key] = c

    combined["claims"] = list(seen.values())
    return combined


# ============================================================
# G. 补取 rhetorical_devices
# ============================================================

RHETORICAL_META = {
    "攻守一个要塞": ("围绕同一个核心问题争论", "metaphor", "批评论战双方没有聚焦"),
    "观战人": ("旁观辩论的读者", "metaphor", "描述第三方视角"),
    "参战人": ("参与辩论的作者", "metaphor", "描述参与者视角"),
    "死尸队": ("无谓的争论", "metaphor", "贬抑无意义的争论"),
    "运动会的预赛": ("正式辩论前的初步交锋", "metaphor", "建议将当前争论视为预备阶段"),
    "重整旗鼓": ("重新组织论据再战", "idiom", "建议重新开始正式辩论"),
    "独具只眼": ("有独到的见解", "idiom", "称赞对方观点独特"),
    "附骥尾": ("追随他人之后发言", "metaphor", "自谦说法"),
    "附伏园先生的骥尾": ("追随伏园先生之后发言", "metaphor", "自谦说法"),
    "风马牛不相及": ("完全无关", "idiom", "强调两个话题没有关联"),
    "扭做一团": ("争执不休", "metaphor", "描述激烈但无效率的争论"),
    "枝叶": ("次要的细节问题", "metaphor", "指出对方关注点偏离核心"),
    "先入之见": ("预先形成的偏见", "idiom", "批评对方缺乏客观性"),
    "支离": ("论证散乱没有重点", "metaphor", "批评对方论证不集中"),
}

RHETORICAL_PATTERNS = [(expr, info[1]) for expr, info in RHETORICAL_META.items()]
# 再加正则模式
RHETORICAL_PATTERNS.extend([
    (r"附.*?骥尾", "metaphor"),
])


def extract_rhetorical_devices_simple(combined: dict, segments: list) -> dict:
    seg_lookup = {s["segment_id"]: s for s in segments}
    seen = set()
    devices = []

    for r in combined.get("rhetorical_devices", []):
        expr = r.get("expression", "")
        if expr:
            seen.add(expr)

    for seg in segments:
        text = seg.get("text", "")
        sid = seg.get("segment_id", "")
        aid = seg.get("article_id", "")
        a_title = seg.get("article_title", "")
        s_author = seg.get("source_author", "")

        for pattern, dtype in RHETORICAL_PATTERNS:
            for m in re.finditer(pattern, text):
                expr = m.group(0).strip()
                if expr in seen or len(expr) < 2:
                    continue
                seen.add(expr)

                # 查 literal_target 和 function
                meta = RHETORICAL_META.get(expr)
                literal_target = meta[0] if meta else ""
                function = meta[2] if meta else ""

                devices.append({
                    "id": f"rh{len(devices) + 1}",
                    "expression": expr,
                    "device_type": dtype,
                    "literal_target": literal_target,
                    "function": function,
                    "evidence": text[max(0, m.start() - 20):m.end() + 20],
                    "segment_id": sid,
                    "article_id": aid,
                    "article_title": a_title,
                    "source_author": s_author,
                })

    combined["rhetorical_devices"] = devices
    return combined


# ============================================================
# H. final_polish — 最终规范化
# ============================================================

# --- H1. claim_type/claim_status 枚举统一 ---

CLAIM_TYPE_NORMALIZE = {
    # English values (backward compat)
    "opinion": "opinion", "Opinion": "opinion",
    "observation": "opinion", "Observation": "opinion",
    "evaluation": "evaluation", "Evaluation": "evaluation",
    "statement": "statement", "Statement": "statement",
    "assertion": "assertion", "Assertion": "assertion",
    "critique": "critique", "Critique": "critique",
    "agreement": "agreement", "Agreement": "agreement",
    "suggestion": "suggestion", "Suggestion": "suggestion",
    "classification": "classification", "Classification": "classification",
    "interpretation": "interpretation",
    "distinction": "distinction",
    "disagreement": "disagreement",
    "belief": "belief", "Belief": "belief",
    # Chinese values (rich taxonomy)
    "方法论主张": "方法论主张",
    "知识论主张": "知识论主张",
    "本体论主张": "本体论主张",
    "社会理论主张": "社会理论主张",
    "教育主张": "教育主张",
    "文明批评": "文明批评",
    "论战策略批评": "论战策略批评",
    "定义性主张": "定义性主张",
    "历史解释": "历史解释",
    "价值评价": "价值评价",
    "反驳性主张": "反驳性主张",
    "回应性主张": "回应性主张",
    "问题提出": "问题提出",
    "结论性主张": "结论性主张",
    "不明": "不明",
}

CLAIM_STATUS_NORMALIZE = {
    # English values (backward compat)
    "asserted": "asserted", "Asserted": "asserted",
    "stated": "asserted", "Stated": "asserted",
    "attributed": "attributed", "Attributed": "attributed",
    "hypothetical": "hypothetical", "Hypothetical": "hypothetical",
    "reported": "reported", "Reported": "reported",
    # Chinese values (rich taxonomy)
    "作者直接主张": "作者直接主张",
    "对手直接主张": "对手直接主张",
    "直接引用": "直接引用",
    "间接转述": "间接转述",
    "作者概括": "作者概括",
    "作者讽刺性归纳": "作者讽刺性归纳",
    "作者推论": "作者推论",
    "归谬构造": "归谬构造",
    "假设情境": "假设情境",
}


def _normalize_enums(combined: dict) -> dict:
    for c in combined.get("claims", []):
        raw_ct = c.get("claim_type", "")
        c["claim_type"] = CLAIM_TYPE_NORMALIZE.get(raw_ct, raw_ct.lower())
        raw_cs = c.get("claim_status", "")
        c["claim_status"] = CLAIM_STATUS_NORMALIZE.get(raw_cs, raw_cs.lower())
    return combined


# --- H2. MAY_INFLUENCE 方向修复 ---

def _fix_influence_direction(combined: dict) -> dict:
    """
    evidence 含「受...影响」时，INFLUENCES 方向反了。
    如 人生观 INFLUENCES 科学 (evidence: "人生观可以受科学的影响")
    应改为 科学 MAY_INFLUENCE 人生观
    """
    for r in combined.get("relations", []):
        rel = r.get("relation", "")
        if rel not in ("INFLUENCES", "MAY_INFLUENCE"):
            continue
        ev = r.get("evidence", "")
        if not re.search(r"受[^。]*影响", ev):
            continue
        r["relation"] = "MAY_INFLUENCE"
        # head 和 tail 互换（受影响者在 tail）
        r["head"], r["tail"] = r["tail"], r["head"]
        r["head_type"], r["tail_type"] = r["tail_type"], r["head_type"]
    return combined


# --- H3. 单字 Person 合并（程朱陆王 / 陆王） ---

def _merge_single_char_persons(combined: dict, segments: list) -> dict:
    seg_map = {s["segment_id"]: s.get("text", "") for s in segments}

    single_char_persons = {}
    remove_ids = set()
    for e in combined.get("entities", []):
        name = e.get("name", "")
        if len(name) == 1 and e.get("type") in ("人物", "Person"):
            seg = e.get("segment_id", "")
            single_char_persons.setdefault(seg, []).append(e)

    for seg_id, persons in single_char_persons.items():
        if len(persons) < 2:
            continue
        seg_text = seg_map.get(seg_id, "")
        persons.sort(key=lambda p: seg_text.find(p["name"]) if p["name"] in seg_text else 999)

        sorted_names = [p["name"] for p in persons]
        combined_name = "".join(sorted_names)
        if len(combined_name) < 2:
            continue

        ref = persons[0]
        new_entity = {
            "id": f"{seg_id}:merged_{combined_name}",
            "name": combined_name,
            "canonical_name": combined_name,
            "type": "PersonGroup",
            "evidence": seg_text,
            "confidence": 0.8,
            "segment_id": seg_id,
            "local_id": f"merged_{combined_name}",
            "article_id": ref.get("article_id", ""),
            "article_title": ref.get("article_title", ""),
            "source_author": ref.get("source_author", ""),
            "original_name": combined_name,
        }
        combined["entities"].append(new_entity)

        if "陆" in sorted_names and "王" in sorted_names:
            combined["entities"].append({
                "id": f"{seg_id}:merged_陆王",
                "name": "陆王",
                "canonical_name": "陆王",
                "type": "PersonGroup",
                "evidence": seg_text,
                "confidence": 0.8,
                "segment_id": seg_id,
                "local_id": "merged_陆王",
                "article_id": ref.get("article_id", ""),
                "article_title": ref.get("article_title", ""),
                "source_author": ref.get("source_author", ""),
                "original_name": "陆王",
            })

        for p in persons:
            remove_ids.add(p["id"])

    combined["entities"] = [e for e in combined["entities"] if e["id"] not in remove_ids]

    name_map = {}
    for seg_id, persons in single_char_persons.items():
        names = [p["name"] for p in persons]
        if len(names) < 2:
            continue
        seg_text = seg_map.get(seg_id, "")
        names.sort(key=lambda n: seg_text.find(n) if n in seg_text else 999)
        combined_name = "".join(names)
        for n in names:
            name_map[(seg_id, n)] = combined_name

    for r in combined.get("relations", []):
        seg = r.get("segment_id", "")
        for side in ("head", "tail"):
            val = r.get(side, "")
            # 优先判断 陆/王 → 陆王（不能等 name_map 先替换成 broad 名称）
            if val in ("陆", "王"):
                r[side] = "陆王"
            elif (seg, val) in name_map:
                r[side] = name_map[(seg, val)]

    # dedup relations after merge
    seen_rel = set()
    deduped = []
    for r in combined.get("relations", []):
        key = (r.get("head", ""), r.get("relation", ""), r.get("tail", ""))
        if key in seen_rel:
            continue
        seen_rel.add(key)
        deduped.append(r)
    combined["relations"] = deduped

    return combined


# --- H4a. 移除翻译类定义（已在 relations 中用 TRANSLATION_OF 表达） ---

def _remove_translation_defs(combined: dict) -> dict:
    kept = []
    removed = 0
    for d in combined.get("definitions", []):
        if re.search(r"的译[语名]", d.get("definition", "")):
            removed += 1
            continue
        kept.append(d)
    if removed:
        print(f"  H4a. 移除 {removed} 条翻译类定义")
    combined["definitions"] = kept
    return combined


# --- H4b. definitions 精准去重（标准化文本 + 保留最长） ---

def _dedupe_definitions(combined: dict) -> dict:
    def _norm_def(text: str) -> str:
        t = re.sub(r"\s+", "", text)
        t = re.sub(r"[（(][^）)]*[）)]", "", t)
        t = t.replace("的", "").replace("了", "")
        t = t.replace("“", "").replace("”", "").replace("《", "").replace("》", "")
        t = re.sub(r"[吗呢吧啊么]", "", t)
        t = t.rstrip("。，；：！？.,;:!? ")
        return t

    seen = {}
    for d in combined.get("definitions", []):
        term = d.get("term", "")
        defn = d.get("definition", "")
        key = (term, _norm_def(defn))
        old = seen.get(key)
        if old is None or len(defn) > len(old.get("definition", "")):
            seen[key] = d

    combined["definitions"] = list(seen.values())
    return combined


# --- H5. PersonGroup 补 members + canonical_name ---

PERSONGROUP_MEMBERS = {
    "丁张两君": {"members": ["丁文江", "张君劢"], "canonical": "丁文江 + 张君劢"},
    "丁张两先生": {"members": ["丁文江", "张君劢"], "canonical": "丁文江 + 张君劢"},
    "程朱陆王": {"members": ["程颐", "程颢", "朱熹", "陆九渊", "王守仁"], "canonical": "程朱陆王"},
    "陆王":      {"members": ["陆九渊", "王守仁"], "canonical": "陆王"},
}

def _fix_persongroup_metadata(combined: dict) -> dict:
    for e in combined.get("entities", []):
        name = e.get("name", "")
        entry = PERSONGROUP_MEMBERS.get(name)
        if entry:
            e["members"] = entry["members"]
            e["canonical_name"] = entry["canonical"]
    return combined


# --- H6. 修正 relation 中 PersonGroup 的 tail_type / head_type ---

def _fix_relation_types(combined: dict) -> dict:
    pg_names = set()
    for e in combined.get("entities", []):
        if e.get("type") == "PersonGroup":
            pg_names.add(e.get("name", ""))
    for r in combined.get("relations", []):
        if r.get("tail", "") in pg_names:
            r["tail_type"] = "PersonGroup"
        if r.get("head", "") in pg_names:
            r["head_type"] = "PersonGroup"
    return combined


# --- H7. 缩短 merged entity 的 evidence ---

def _extract_sentence_containing(text: str, keyword: str) -> str:
    """从 text 中找到包含 keyword 的短句/子句"""
    # 精确匹配位置
    pos = text.find(keyword.strip())
    if pos == -1:
        # 松散匹配：keyword 各字之间可插入任意间隔（处理 程朱陆王 → 程、朱、陆、王）
        fuzzy = r".*?".join(re.escape(c) for c in keyword)
        m = re.search(fuzzy, text)
        if m:
            pos = m.start()
    if pos == -1:
        return text[:80]
    # 从句边界：向后找上一个句尾，向前找下一个句尾
    left_dot = text.rfind("。", 0, pos)
    left_comma = text.rfind("，", 0, pos)
    left = 0
    if left_dot != -1:
        left = left_dot + 1
    elif left_comma != -1:
        left = left_comma + 1
    right = text.find("。", pos)
    if right == -1:
        right = text.find("，", pos)
        if right == -1:
            right = len(text)
        else:
            right += 1
    else:
        right += 1
    clause = text[left:right].strip()
    if len(clause) > 80:
        truncated = clause[:80]
        last_comma = truncated.rfind("，")
        last_period = truncated.rfind("。")
        cutoff = max(last_comma, last_period)
        if cutoff > 30:
            clause = truncated[:cutoff + 1].rstrip("，；、").strip()
        else:
            clause = truncated.strip()
    return clause


def _fix_merged_entity_evidence(combined: dict, segments: list) -> dict:
    seg_map = {s["segment_id"]: s.get("text", "") for s in segments}
    for e in combined.get("entities", []):
        eid = e.get("id", "")
        if "merged_" not in eid:
            continue
        name = e.get("name", "")
        seg_text = seg_map.get(e.get("segment_id", ""), "")
        short = _extract_sentence_containing(seg_text, name)
        if short:
            e["evidence"] = short
    return combined


# --- H8. 可选： 如果…… 句子标记为 hypothetical ---

def _fix_hypothetical_claims(combined: dict) -> dict:
    for c in combined.get("claims", []):
        text = c.get("claim", "")
        if re.match(r"^如果", text.strip()):
            c["claim_status"] = "hypothetical"
    return combined


# --- H9. 清理超长 speaker/head/tail（文本片段误填入人名/概念） ---

MAX_NAME_LENGTH = 30

def _fix_overlong_names(combined: dict) -> dict:
    """将 speaker/head/tail 中超过 MAX_NAME_LENGTH 的标记为疑似误抽"""
    cleaned = 0
    for c in combined.get("claims", []):
        sp = c.get("speaker", "")
        if len(sp) > MAX_NAME_LENGTH:
            c["speaker"] = ""
            cleaned += 1
        tg = c.get("target", "")
        if len(tg) > MAX_NAME_LENGTH:
            c["target"] = ""
            cleaned += 1

    # relations 中也检查 head/tail
    for r in combined.get("relations", []):
        tail = r.get("tail", "")
        if len(tail) > MAX_NAME_LENGTH:
            r["tail"] = ""
            cleaned += 1

    if cleaned:
        print(f"  H9. 清理了 {cleaned} 处超长 name 字段")
    return combined


# ============================================================
# final_polish — 综合入口
# ============================================================

def final_polish(combined: dict, segments: list) -> dict:
    combined = _normalize_enums(combined)
    combined = _fix_influence_direction(combined)
    combined = _merge_single_char_persons(combined, segments)
    combined = _remove_translation_defs(combined)
    combined = _dedupe_definitions(combined)
    combined = _fix_persongroup_metadata(combined)
    combined = _fix_relation_types(combined)
    combined = _fix_merged_entity_evidence(combined, segments)
    combined = _fix_hypothetical_claims(combined)
    combined = _fix_overlong_names(combined)
    return combined


# ============================================================
# 综合入口
# ============================================================

def post_process_all(combined: dict, segments: list) -> dict:
    print("开始后处理...")

    # B. 别名归一化（先做，让后面的逻辑基于规范名）
    combined = normalize_aliases(combined)
    print(f"  B. 别名归一化完成")

    # B2. 泛称 Person 修正（诸公/专门家/心理学者 → Concept）
    for e in combined.get("entities", []):
        if e.get("type") in ("人物", "Person") and e.get("name") in GENERIC_PERSON_TERMS:
            e["type"] = "概念"
    print(f"  B2. 泛称 Person→Concept 完成")

    # A. 修复东荪按等 source_author = 张东荪
    combined = fix_section_author(combined, segments)
    print(f"  A. 标题→作者修复完成")

    # C. Definition 提取
    combined = extract_definitions(combined)
    print(f"  C. definitions 提取完成: {len(combined['definitions'])} 条")

    # D0. 属于/包含 方向修复
    combined = fix_part_of_direction(combined)
    print(f"  D0. 属于/包含方向修复完成")

    # D. 翻译关系 过滤
    combined = filter_translation_of(combined)
    print(f"  D. 翻译关系过滤完成")

    # E. 相关/其他 细化 (→ 已迁移至 fix_combined_json.py)
    # combined = refine_relations(combined)
    # print(f"  E. 关系细化完成")

    # F. claims 去重 (→ 已迁移至 fix_combined_json.py)
    # combined = dedupe_claims(combined)
    # print(f"  F. claims 去重完成")

    # G. rhetorical_devices 补取 (→ 已迁移至 fix_combined_json.py)
    # combined = extract_rhetorical_devices_simple(combined, segments)
    # print(f"  G. rhetorical_devices 补取完成")

    # H. final_polish — 最终规范化
    combined = final_polish(combined, segments)
    print(f"  H. final_polish 完成")

    # 更新 counts
    counts = combined.get("counts", {})
    for field in ["entities", "claims", "relations", "definitions", "citations", "rhetorical_devices", "uncertainties"]:
        counts[field] = len(combined.get(field, []))
    combined["counts"] = counts

    print("后处理全部完成。")
    print(f"  最终 counts: {json.dumps(combined['counts'], ensure_ascii=False)}")

    return combined
