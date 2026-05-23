import os, re, json, sys, time
from pathlib import Path
from collections import defaultdict
from getpass import getpass
from openai import OpenAI

from config import WORKSPACE_DIR, RUN_ROOT, API_KEY_ENV_NAME, BASE_URL, MODEL

def _resolve_api_key() -> str:
    key = os.getenv(API_KEY_ENV_NAME, "").strip()
    if key:
        try:
            key.encode("ascii")
            if not (len(key) > 200 or any(c in key for c in (" ", "\n", "\r", "\t"))):
                return key
        except UnicodeEncodeError:
            pass
    for attempt in range(3):
        raw = getpass(f"API Key (尝试 {attempt+1}/3): ").strip()
        if len(raw) > 200 or any(c in raw for c in (" ", "\n", "\r", "\t")):
            print(f"API Key 无效（长度={len(raw)}），请重新输入")
            continue
        try:
            raw.encode("ascii")
        except UnicodeEncodeError:
            print("API Key 包含非 ASCII 字符，请重新输入")
            continue
        return raw
    raise RuntimeError(
        "无法获取有效的 API Key。请先在命令行设置环境变量:\n"
        "  set SILICONFLOW_API_KEY=sk-你的Key\n"
        "或在 config.py 中配置，然后重新运行。"
    )

API_KEY = _resolve_api_key()
os.environ[API_KEY_ENV_NAME] = API_KEY

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ---- 路径（由 init_paths() 动态设置） ----
RUN_DIR = None
COMBINED_PATH = None
SEGMENTS_PATH = None
NEO4J_DIR = None


def find_run_dir():
    override = os.environ.get("KG_RUN_DIR_OVERRIDE", "").strip()
    if override:
        override_path = Path(RUN_ROOT) / override
        if (override_path / "combined_extract.json").exists():
            return override_path
    kg_root = Path(RUN_ROOT)
    if not kg_root.exists():
        raise FileNotFoundError(f"{RUN_ROOT} 目录不存在，请先运行 workflow_complete.py")
    dirs = sorted([d for d in kg_root.iterdir() if d.is_dir() and (d / "combined_extract.json").exists()],
                  key=lambda d: d.stat().st_mtime, reverse=True)
    if not dirs:
        raise FileNotFoundError("未找到包含 combined_extract.json 的目录，请先运行 workflow_complete.py")
    return dirs[0]


def init_paths():
    global RUN_DIR, COMBINED_PATH, SEGMENTS_PATH, NEO4J_DIR
    RUN_DIR = find_run_dir()
    COMBINED_PATH = RUN_DIR / "combined_extract.json"
    SEGMENTS_PATH = RUN_DIR / "segments.jsonl"
    NEO4J_DIR = RUN_DIR / "neo4j"
    NEO4J_DIR.mkdir(parents=True, exist_ok=True)
    print(f"检测到运行目录: {RUN_DIR}")


def load_jsonl(path):
    rows = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def build_segment_input(combined, segments):
    seg_map = {s["segment_id"]: s for s in segments}
    by_seg = defaultdict(lambda: {"segments": [], "entities": [], "claims": [], "relations": [],
                                   "definitions": [], "citations": [], "rhetorical_devices": [], "uncertainties": []})

    for e in combined.get("entities", []):
        by_seg[e.get("segment_id", "")]["entities"].append(e)
    for c in combined.get("claims", []):
        by_seg[c.get("segment_id", "")]["claims"].append(c)
    for r in combined.get("relations", []):
        by_seg[r.get("segment_id", "")]["relations"].append(r)
    for d in combined.get("definitions", []):
        by_seg[d.get("segment_id", "")]["definitions"].append(d)
    for c in combined.get("citations", []):
        by_seg[c.get("segment_id", "")]["citations"].append(c)
    for rd in combined.get("rhetorical_devices", []):
        by_seg[rd.get("segment_id", "")]["rhetorical_devices"].append(rd)
    for u in combined.get("uncertainties", []):
        by_seg[u.get("segment_id", "")]["uncertainties"].append(u)

    for s in segments:
        sid = s["segment_id"]
        if sid not in by_seg:
            by_seg[sid] = {"segments": [], "entities": [], "claims": [], "relations": [],
                           "definitions": [], "citations": [], "rhetorical_devices": [], "uncertainties": []}

    ordered = []
    for s in segments:
        sid = s["segment_id"]
        d = by_seg[sid]
        d["segments"] = [s]
        ordered.append(d)

    return ordered


def format_segment_block(seg_data):
    parts = []
    seg = seg_data["segments"][0] if seg_data["segments"] else {}
    sid = seg.get("segment_id", "")
    text = seg.get("text", "")
    parts.append(f"## {sid}")
    parts.append(f"T: {text}")
    if seg_data["entities"]:
        for e in seg_data["entities"]:
            parts.append(f"  E: {e.get('name','')} ({e.get('type','')})")
    if seg_data["claims"]:
        for c in seg_data["claims"]:
            parts.append(f"  C: {c.get('speaker','')}→{c.get('target','')} \"{c.get('claim','')}\" ({c.get('claim_status','')})")
    if seg_data["relations"]:
        for r in seg_data["relations"]:
            parts.append(f"  R: {r.get('head','')} --[{r.get('relation','')}]--> {r.get('tail','')}")
    if seg_data["definitions"]:
        for d in seg_data["definitions"]:
            parts.append(f"  D: {d.get('term','')} = {d.get('definition','')}")
    if seg_data["citations"]:
        for c in seg_data["citations"]:
            parts.append(f"  Cit: {c.get('citer','')} → {c.get('quoted_author','')}")
    if seg_data["rhetorical_devices"]:
        for rd in seg_data["rhetorical_devices"]:
            parts.append(f"  RD: {rd.get('device','')}")
    if seg_data["uncertainties"]:
        for u in seg_data["uncertainties"]:
            parts.append(f"  U: {u.get('item','')} ({u.get('reason','')})")
    return "\n".join(parts)


def build_prompt(combined, segments):
    prompt = """# 跨段关系补全 Prompt

你是一个思想史论战文本的跨段关系补全助手。

我会提供若干连续文本片段的抽取结果，包括 entities / claims / relations / definitions / citations / rhetorical_devices / uncertainties。

你的任务不是重新抽取原文，而是检查这些片段之间是否存在遗漏的跨段关系、标准化问题、桥梁节点、方向错误或观点版本变化。

请只输出新增或修正结果。不要重复已有关系。不要重写全部 JSON。输出必须是严格 JSON。不要输出 Markdown。不要输出解释文字。

## 一、任务目标

检查连续片段之间是否存在以下问题：

1. 前文提出的问题，后文是否回应
2. 前文提出的观点，后文是否反驳、修正、承接、转折或归谬
3. 某人物是否在后文改变、扩展或重新定义前文观点
4. 是否存在"论据 → 中间结论 → 总结论"的缺失桥梁
5. 是否存在同阵营内部批评
6. 是否存在概念名称不一致
7. 是否存在思想谱系关系
8. 是否存在对比结构
9. 是否存在因果方向错误或归因反向
10. 是否存在问题节点没有被统一
11. 是否存在同一人物前后观点变化
12. 是否存在引用链没有连接到被支持或被攻击观点
13. 是否存在修辞表达跨段延续
14. 是否存在前文设问、后文作答
15. 是否存在前文定义、后文重新定义或修正

## 二、重要限制

1. **不要重新抽取** — 只输出跨段新增关系、修正建议、标准化更新、桥梁节点和不确定项
2. **不要凭空补充** — 跨段关系必须基于已提供片段中的抽取结果、原文 evidence 或明显的跨段承接
3. **不要重复已有关系** — 如果某条关系已在输入结果中出现，不要重复输出
4. **跨段关系也需要依据** — 每条 cross_segment_link 都必须说明 reason，尽量提供 source_evidence 和 target_evidence
5. **不确定则放入 uncertainties**

## 三、允许的关系类型

cross_segment_links 中的 relation 只能从以下列表选择：

主张, 反对, 批评, 支持, 质疑, 回应, 再回应, 反驳, 定义, 重新定义,
区分, 混淆, 包含, 属于, 导致, 归因于, 解释, 证明, 推出,
作为论据支持, 作为理由反驳, 作为反例反驳, 归谬, 类比, 对比,
引用, 影响, 继承, 源自, 发展, 转化, 修正, 自相矛盾, 承接, 转折, 相关

## 四、允许的节点类型

source_type、target_type、node_type 只能从以下列表选择：

text, 人物, 阵营/群体, 概念, 主义/学说/理论, 方法, 方法论原则,
著作, 文章, 历史事件, 观点, 论据, 结论, 评价, 比喻/类比, 问题, 阶段, 例证

## 五、claim_version_links 中 relation 允许值

发展, 转化, 修正, 重新定义, 自相矛盾, 承接, 转折, 回应, 反驳, 再回应, 归谬, 相关

## 六、direction_corrections 使用说明

如果发现原抽取中方向错误（因果方向错误、归因方向错误、支持/反驳方向错误等），应输出 direction_corrections，明确 corrected_relation。

## 七、normalization_updates 使用说明

如果发现跨段中同一实体名称不一致，应输出 normalization_updates。例如：

{
  "surface_forms": ["胡适之", "胡适"],
  "canonical_form": "胡适",
  "reason": "两个名称指向同一人物",
  "related_segments": ["s1", "s3"],
  "confidence": 0.95
}

## 八、missing_bridge_nodes 使用说明

如果跨段论证中缺少必要中间节点，应输出 missing_bridge_nodes。桥梁节点必须满足：能够连接多个片段的观点或问题，由已有片段中的 evidence 支持。

## 九、输出 JSON 格式

{
  "cross_segment_links": [
    {
      "id": "cs1",
      "source_segment": "",
      "target_segment": "",
      "source": "",
      "source_type": "",
      "relation": "",
      "target": "",
      "target_type": "",
      "reason": "",
      "source_evidence": "",
      "target_evidence": "",
      "confidence": 0.0
    }
  ],
  "normalization_updates": [
    {
      "surface_forms": [],
      "canonical_form": "",
      "reason": "",
      "related_segments": [],
      "confidence": 0.0
    }
  ],
  "missing_bridge_nodes": [
    {
      "node": "",
      "node_type": "",
      "why_needed": "",
      "related_segments": [],
      "evidence_or_basis": "",
      "confidence": 0.0
    }
  ],
  "direction_corrections": [
    {
      "original_relation_id": "",
      "original_relation": "",
      "corrected_relation": "",
      "reason": "",
      "related_segments": [],
      "confidence": 0.0
    }
  ],
  "claim_version_links": [
    {
      "speaker": "",
      "topic": "",
      "earlier_segment": "",
      "later_segment": "",
      "earlier_claim": "",
      "later_claim": "",
      "relation": "",
      "reason": "",
      "evidence_or_basis": "",
      "confidence": 0.0
    }
  ],
  "uncertainties": [
    {
      "item": "",
      "reason": ""
    }
  ]
}

## 十、输出前自检清单

- 是否只输出跨段新增或修正内容？
- 是否重复了已有关系？
- 是否根据外部常识补充了信息？
- 是否为每条跨段关系提供 reason？
- 是否尽量提供 source_evidence 和 target_evidence？
- 关系类型是否在允许列表中？
- 节点类型是否在允许列表中？
- 标准化是否有依据？
- 桥梁节点是否由片段内容支持？
- 方向修正是否明确说明原方向和正确方向？
- claim_version_links 是否真实体现前后变化？
- 不确定内容是否放入 uncertainties？
"""
    prompt += "\n---\n以下是各文本片段的抽取结果：\n\n"
    seg_blocks = build_segment_input(combined, segments)
    for i, sb in enumerate(seg_blocks):
        prompt += format_segment_block(sb) + "\n\n"
    return prompt


# 中文→英文关系类型映射
CN_RELATION_SET = {
    "主张", "反对", "批评", "支持", "质疑", "回应", "再回应",
    "反驳", "定义", "重新定义", "区分", "混淆", "包含", "属于",
    "导致", "归因于", "解释", "证明", "推出", "作为论据支持",
    "作为理由反驳", "作为反例反驳", "归谬", "类比", "对比",
    "引用", "影响", "继承", "源自", "发展", "转化", "修正",
    "自相矛盾", "承接", "转折", "相关",
}

DIRECTIONAL_RELS = {
    "批评", "回应", "再回应", "反驳", "支持", "反对", "质疑",
    "影响", "引用", "修正", "自相矛盾", "重新定义", "归因于",
    "作为论据支持", "作为理由反驳", "作为反例反驳",
    "继承", "源自", "发展", "转化", "证明", "推出", "解释", "归谬",
}

DIRECTIONAL_ACTIONS = ["回应", "批评", "反驳", "支持", "反对", "质疑", "赞扬", "同意",
                       "批评了", "反驳了", "回应了", "支持了", "反对了", "同意"]


def _infer_direction(head, tail, rel, reason):
    if rel not in DIRECTIONAL_RELS or not reason:
        return head, tail
    r = reason.replace(" ", "").replace("，", "").replace("。", "")
    for a in DIRECTIONAL_ACTIONS:
        if f"{tail}{a}{head}" in r:
            return tail, head
        if f"{head}{a}{tail}" in r:
            return head, tail
    return head, tail


SEGMENT_ID_PATTERN = re.compile(r"^s\d{3,4}$")

def _sanitize_segment_id(seg_id):
    if not seg_id or not isinstance(seg_id, str):
        return ""
    seg_id = seg_id.strip()
    if SEGMENT_ID_PATTERN.match(seg_id):
        return seg_id
    m = re.search(r"s\d{3,4}", seg_id)
    if m:
        return m.group(0)
    return ""


def apply_fixes(combined, fixes, segments):
    old_rels = [r for r in combined.get("relations", []) if r.get("id", "").startswith("cross_seg_")]
    if old_rels:
        print(f"  cleaning {len(old_rels)} old cross_seg relations")
    combined["relations"] = [r for r in combined.get("relations", []) if not r.get("id", "").startswith("cross_seg_")]

    for nu in fixes.get("normalization_updates", []):
        forms = nu.get("surface_forms", [])
        canonical = nu.get("canonical_form", "")
        if not forms or not canonical:
            continue
        for e in combined.get("entities", []):
            if e.get("canonical_name") in forms or e.get("name") in forms:
                e["canonical_name"] = canonical

    existing_rels = set()
    for r in combined.get("relations", []):
        existing_rels.add((r.get("head", ""), r.get("relation", ""), r.get("tail", "")))
    next_rid = sum(1 for _ in combined.get("relations", [])) + 1

    for cl in fixes.get("cross_segment_links", []):
        head = cl.get("source", "")
        rel = cl.get("relation", "")
        tail = cl.get("target", "")
        if not head or not rel or not tail:
            continue
        if rel not in CN_RELATION_SET:
            continue
        head, tail = _infer_direction(head, tail, rel, cl.get("reason", ""))
        if (head, rel, tail) in existing_rels:
            continue
        seg_id = cl.get("source_segment", "")
        seg_id = _sanitize_segment_id(seg_id)
        combined.setdefault("relations", []).append({
            "id": f"cross_seg_{next_rid}",
            "head": head,
            "head_type": cl.get("source_type", "概念"),
            "relation": rel,
            "tail": tail,
            "tail_type": cl.get("target_type", "概念"),
            "polarity": cl.get("polarity", "neutral"),
            "evidence": cl.get("reason", ""),
            "confidence": cl.get("confidence", 0.7),
            "segment_id": seg_id,
            "article_id": "",
            "source": "cross_segment_fix",
            "relation_subtype": "不适用",
        })
        next_rid += 1

    for dc in fixes.get("direction_corrections", []):
        orig_id = dc.get("original_relation_id", "")
        corrected_rel = dc.get("corrected_relation", "")
        if corrected_rel and corrected_rel not in CN_RELATION_SET:
            continue
        for r in combined.get("relations", []):
            if r.get("id") == orig_id and corrected_rel:
                r["relation"] = corrected_rel

    next_eid = sum(1 for _ in combined.get("entities", [])) + 1
    for mb in fixes.get("missing_bridge_nodes", []):
        node_name = mb.get("node", "")
        node_type = mb.get("node_type", "Concept")
        if not node_name:
            continue
        combined.setdefault("entities", []).append({
            "id": f"bridge_{next_eid}",
            "name": node_name,
            "canonical_name": node_name,
            "type": node_type,
            "evidence": mb.get("evidence_or_basis", ""),
            "confidence": mb.get("confidence", 0.7),
            "segment_id": "",
            "article_id": "",
            "source": "cross_segment_bridge",
        })
        next_eid += 1

    for cv in fixes.get("claim_version_links", []):
        pass

    return combined


def _try_parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fixed = text.rstrip()
    in_str = False
    escaped = False
    for ch in fixed:
        if escaped:
            escaped = False; continue
        if ch == '\\':
            escaped = True; continue
        if ch == '"':
            in_str = not in_str
    if in_str:
        fixed += '"'
    stack = []
    in_str = False; escaped = False
    for ch in fixed:
        if escaped:
            escaped = False; continue
        if ch == '\\':
            escaped = True; continue
        if ch == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{': stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[': stack.pop()
    closed = fixed
    for ch in reversed(stack):
        closed += '}' if ch == '{' else ']'
    try:
        result = json.loads(closed)
        print("WARNING: JSON truncated, repaired by closing constructs")
        return result
    except json.JSONDecodeError:
        pass

    stripped = fixed.rstrip()
    if stripped.endswith(','):
        stripped = stripped[:-1].strip()
        closed2 = stripped
        for ch in reversed(stack):
            closed2 += '}' if ch == '{' else ']'
        try:
            result = json.loads(closed2)
            print("WARNING: JSON truncated, repaired by stripping trailing comma")
            return result
        except json.JSONDecodeError:
            pass

    def _close_constructs(s):
        s = s.rstrip()
        in_str = False; escaped = False
        for ch in s:
            if escaped: escaped = False; continue
            if ch == '\\': escaped = True; continue
            if ch == '"': in_str = not in_str
        if in_str:
            s += '"'
        stack = []
        in_str = False; escaped = False
        for ch in s:
            if escaped: escaped = False; continue
            if ch == '\\': escaped = True; continue
            if ch == '"': in_str = not in_str; continue
            if in_str: continue
            if ch in '{[': stack.append(ch)
            elif ch == '}':
                if stack and stack[-1] == '{': stack.pop()
            elif ch == ']':
                if stack and stack[-1] == '[': stack.pop()
        for ch in reversed(stack):
            s += '}' if ch == '{' else ']'
        return s

    for closer in ('}', ']'):
        pos = len(text)
        while True:
            pos = text.rfind(closer, 0, pos)
            if pos == -1:
                break
            candidate = text[:pos + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
            try:
                result = json.loads(_close_constructs(candidate))
                print(f"WARNING: JSON truncated, recovered at char {pos + 1}")
                return result
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("无法修复的 JSON 截断", text, 0)


def run():
    init_paths()

    combined = json.loads(COMBINED_PATH.read_text(encoding="utf-8"))
    segments = load_jsonl(SEGMENTS_PATH)

    print(f"articles: {len(combined.get('articles',[]))}, segments: {len(segments)}")
    print(f"entities: {len(combined.get('entities',[]))}, claims: {len(combined.get('claims',[]))}, relations: {len(combined.get('relations',[]))}")

    # 分批：每批 10 段，前后重叠 3 段防止边界断连
    BATCH_SIZE = 10
    OVERLAP = 3
    batches = []
    i = 0
    while i < len(segments):
        end = min(i + BATCH_SIZE, len(segments))
        batches.append(segments[i:end])
        i += BATCH_SIZE - OVERLAP
    total_batches = len(batches)
    print(f"\n分段较多，分批处理：{total_batches} 批，每批 ≤{BATCH_SIZE} 段（重叠={OVERLAP}）\n")

    all_fixes = {
        "cross_segment_links": [], "normalization_updates": [],
        "missing_bridge_nodes": [], "direction_corrections": [],
        "claim_version_links": [], "uncertainties": [],
    }

    for b, batch_segs in enumerate(batches):
        seg_ids = [s.get("segment_id","")[-6:] for s in batch_segs]
        prompt = build_prompt(combined, batch_segs)
        prompt_len = len(prompt)
        print(f"[{b+1}/{total_batches}] {seg_ids[0]}..{seg_ids[-1]} prompt: {prompt_len} chars ... ", end="", flush=True)

        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": "你是一个严谨的学术文本关系补全助手。只输出严格JSON，不要任何其他文字。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=32768,
                    timeout=300,
                )
                content = resp.choices[0].message.content
                print(f"response: {len(content)} chars")
                content = content.strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*", "", content)
                    content = re.sub(r"\s*```$", "", content)
                fixes = _try_parse_json(content)
                for k in all_fixes:
                    all_fixes[k].extend(fixes.get(k, []))
                print(f"  cross_seg_links={len(fixes.get('cross_segment_links',[]))}, "
                      f"normalization={len(fixes.get('normalization_updates',[]))}, "
                      f"version_links={len(fixes.get('claim_version_links',[]))}")
                break
            except Exception as e:
                if attempt == 0:
                    print(f"retry 1/1 ... ", end="", flush=True)
                    time.sleep(5)
                else:
                    print(f"SKIP ({e})")

    print(f"\n总计: cross_segment_links={len(all_fixes['cross_segment_links'])}, "
          f"normalization_updates={len(all_fixes['normalization_updates'])}, "
          f"missing_bridge_nodes={len(all_fixes['missing_bridge_nodes'])}, "
          f"direction_corrections={len(all_fixes['direction_corrections'])}, "
          f"claim_version_links={len(all_fixes['claim_version_links'])}, "
          f"uncertainties={len(all_fixes['uncertainties'])}")

    combined = apply_fixes(combined, all_fixes, segments)

    out_path = RUN_DIR / "combined_extract.json"
    out_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out_path}")

    for nu in all_fixes.get("normalization_updates", []):
        print(f"  normalized: {nu['surface_forms']} -> {nu['canonical_form']} ({nu.get('reason','')})")

    for cl in all_fixes.get("cross_segment_links", []):
        print(f"  link: {cl['source']} --[{cl['relation']}]--> {cl['target']} ({cl.get('reason','')[:60]})")

    print("\n跨段关系补全完成。接下来运行 run_check.py 做最终质量检查 + 生成 Neo4j CSV。")


if __name__ == "__main__":
    print("正在运行跨段关系补全...")
    if not API_KEY:
        raise RuntimeError("SILICONFLOW_API_KEY not set")
    run()
