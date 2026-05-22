"""
run_check.py — 最终质量检查 + Neo4j CSV 生成
功能：
1. 自动找到最新运行目录
2. 结构性质量检查（非 LLM，快速）
3. LLM 质量检查（基于 promote检查.md，采样运行）
4. 生成 Neo4j CSV 作为最终输出
5. 写 source_info.txt

用法：在 cross_segment_fix.py 跑完后运行
    python run_check.py
"""

import os, re, json, csv, hashlib
from pathlib import Path
from getpass import getpass
from openai import OpenAI
import networkx as nx

from config import RUN_ROOT, API_KEY_ENV_NAME, BASE_URL, MODEL

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

# ============================================================
# 1. 工具函数
# ============================================================

def clean_placeholder(x):
    x = "" if x is None else str(x).strip()
    if x.startswith("{{") and x.endswith("}}"):
        return ""
    return x

def stable_hash(s, n=10):
    return hashlib.sha1(str(s).encode("utf-8", errors="ignore")).hexdigest()[:n]

def atomic_write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

def atomic_write_json(path, obj, indent=2):
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=indent))

def load_jsonl(path):
    rows = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows

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
        raise FileNotFoundError("未找到包含 combined_extract.json 的目录")
    return dirs[0]

# ============================================================
# 2. 结构性检查（非 LLM，快速）
# ============================================================

def structural_check(combined):
    issues = []
    entities = combined.get("entities", [])
    claims_data = combined.get("claims", [])
    relations = combined.get("relations", [])
    cs_rels = [r for r in relations if r.get("id", "").startswith("cross_seg_")]

    print("\n" + "=" * 60)
    print("结构性检查")
    print("=" * 60)
    print(f"  实体: {len(entities)}, 主张: {len(claims_data)}, 关系: {len(relations)} (跨段: {len(cs_rels)})")

    # 1. speaker/head 污染检查
    polluted = []
    for c in claims_data:
        speaker = c.get("speaker", "")
        if len(speaker) > 100:
            polluted.append(("speaker过长", c.get("id", ""), speaker[:60] + "..."))
        target = c.get("target", "")
        if len(target) > 200:
            polluted.append(("target过长", c.get("id", ""), target[:60] + "..."))
    for r in relations:
        for k in ("head", "tail"):
            val = r.get(k, "")
            if len(val) > 100:
                polluted.append((f"{k}过长", r.get("id", ""), val[:60] + "..."))
    if polluted:
        issues.append(f"evidence/实体疑似污染: {len(polluted)} 条")
        for kind, rid, sample in polluted[:5]:
            print(f"  ⚠ [{kind}] {rid}: {sample}")

    # 2. 空 evidence
    empty_claims = sum(1 for c in claims_data if not (c.get("evidence") or "").strip())
    empty_rels = sum(1 for r in relations if not (r.get("evidence") or "").strip())
    if empty_claims:
        issues.append(f"空 evidence 的 claim: {empty_claims}")
        print(f"  ⚠ 空 evidence claim: {empty_claims}")
    if empty_rels:
        issues.append(f"空 evidence 的 relation: {empty_rels}")
        print(f"  ⚠ 空 evidence relation: {empty_rels}")

    # 3. entity name 异常
    single_char = [e.get("name","") for e in entities if len(e.get("name","")) == 1 and e.get("type") in ("人物", "Person")]
    if single_char:
        issues.append(f"单字人物实体: {len(single_char)} ({', '.join(single_char[:10])})")
        print(f"  ⚠ 单字人物: {single_char}")

    # 4. claim 无 target
    no_target = sum(1 for c in claims_data if not (c.get("target") or "").strip())
    if no_target:
        issues.append(f"未指定 target 的 claim: {no_target}")
        print(f"  ⚠ 无 target claim: {no_target}")

    # 5. entity type 不在白名单
    KNOWN_TYPES = {"人物", "阵营/群体", "概念", "主义/学说/理论", "方法",
                   "方法论原则", "著作", "文章", "组织", "地点", "历史事件",
                   "观点", "论据", "结论", "评价",
                   "比喻/类比", "问题", "阶段", "例证"}
    unknown_types = set()
    for e in entities:
        t = e.get("type", "")
        if t and t not in KNOWN_TYPES:
            unknown_types.add(t)
    if unknown_types:
        issues.append(f"未知实体类型: {unknown_types}")
        print(f"  ⚠ 未知实体类型: {unknown_types}")

    # 6. relation head/tail 是否指向已知 entity
    entity_names = {e.get("name","") for e in entities if e.get("name")}
    entity_names.update(e.get("canonical_name","") for e in entities if e.get("canonical_name"))
    dangling = []
    for r in relations:
        h = r.get("head", "")
        t = r.get("tail", "")
        if h and h not in entity_names:
            dangling.append(("head未匹配实体", r.get("id", ""), h))
        if t and t not in entity_names:
            dangling.append(("tail未匹配实体", r.get("id", ""), t))
    if dangling:
        issues.append(f"relation 端点未匹配实体: {len(dangling)} 条")
        for kind, rid, name in dangling[:5]:
            print(f"  ⚠ [{kind}] {rid}: {name}")

    if not issues:
        print("  ✅ 全部通过")
    else:
        print(f"\n  共发现 {len(issues)} 类问题:")
        for i in issues:
            print(f"    - {i}")
    print()
    return issues

# ============================================================
# 3. LLM 质量检查（基于 promote检查.md）
# ============================================================

CHECK_SYSTEM_PROMPT = """你是思想史论战文本知识图谱抽取结果的质量检查助手。

我会提供：
1. 原始文本片段；
2. 对该文本片段的 JSON 抽取结果。

你的任务不是重新抽取全部内容，而是检查已有 JSON 抽取结果是否存在问题。
请只输出需要修改、补充或警惕的地方。不要重写完整 JSON。
输出必须是严格 JSON。不要输出 Markdown。不要输出解释文字。

---

## 一、检查重点

### 1. 类型错误
- 完整命题（含"是""不是""可以""不能"）是否误标为"概念"？
- 群体（"科学家""玄学家""唯物论者""青年学生"）是否误标为"人物"？
- 比喻/类比是否误标为普通概念？
- 方法论原则是否误标为普通观点？
- 问题节点是否遗漏或误标（如"科学能支配人生观吗"应是"问题"而非"概念"）？

### 2. 观点归属错误
- 转述观点（"某人认为""某人主张"）是否误判为作者直接主张？
- 讽刺性归纳是否误判为对手真实主张？
- 归谬构造是否误判为对手真实主张？
- 假设情境是否误判为事实主张？

### 3. 方向错误
- 因果方向是否反了？
- 支持/反驳方向是否反了？
- "归因于"是否反向？
- "影响/继承/源自"方向是否正确？

### 4. 缺失节点与关系
- 是否遗漏概念定义或重新定义？
- 是否遗漏争论问题节点？
- 是否遗漏比喻/类比节点？
- 是否遗漏"包含/区分"等关系？

### 5. 标准化问题
- 同一人物是否出现多个名称（如"胡适之/胡适"）？
- 同一概念是否出现多个写法（如"科学方法/科学的方法"）？
- "人生观/《人生观》"是否需要区分文章与概念？

### 6. 关系类型问题
- relation 是否使用了过泛的"其他"或"相关"而有更准确的选择？
- 是否把回应关系误标为普通相关？

### 7. 态度极性问题
- 是否把复杂态度（部分肯定+部分批评）简化为 positive/negative？
- 中性转述是否误判为支持或批评？

### 8. 证据问题
- claim/relation/definition 是否缺少 evidence？
- evidence 是否不是当前文本原文？

### 9. 修辞问题
- 是否遗漏比喻、类比、讽刺、归谬、标签化？
- 是否说明修辞的 literal_target 和论证功能？
- 是否把修辞表达误当作普通事实描述？

---

## 二、严重程度
每条问题都要给出 severity：
- high：会严重影响图谱正确性，必须修改
- medium：会影响分析质量，建议修改
- low：轻微问题，可视情况修改

---

## 三、允许的实体类型（参考）
人物, 阵营/群体, 概念, 主义/学说/理论, 方法, 方法论原则,
著作, 文章, 历史事件, 观点, 论据, 结论, 评价, 比喻/类比, 问题, 阶段, 例证

---

## 四、输出 JSON 格式

{
  "type_errors": [{"item": "", "problem": "", "suggested_fix": "", "severity": ""}],
  "attribution_errors": [{"item": "", "problem": "", "suggested_fix": "", "severity": ""}],
  "direction_errors": [{"item": "", "problem": "", "suggested_fix": "", "severity": ""}],
  "missing_nodes": [{"node": "", "node_type": "", "reason": "", "severity": ""}],
  "missing_links": [{"source": "", "relation": "", "target": "", "reason": "", "severity": ""}],
  "normalization_issues": [{"surface_forms": [], "suggested_canonical": "", "reason": "", "severity": ""}],
  "relation_type_issues": [{"item": "", "problem": "", "suggested_relation": "", "severity": ""}],
  "polarity_issues": [{"item": "", "problem": "", "suggested_polarity": "", "severity": ""}],
  "evidence_issues": [{"item": "", "problem": "", "suggested_fix": "", "severity": ""}],
  "rhetorical_device_issues": [{"item": "", "problem": "", "suggested_fix": "", "severity": ""}],
  "uncertainties": [{"item": "", "reason": ""}]
}

如果没有发现问题，所有数组输出为空。"""


def get_segment_data(combined, segment_id):
    """从 combined 中提取某个 segment 的所有抽取结果"""
    data = {"entities": [], "claims": [], "relations": [],
            "definitions": [], "citations": [], "rhetorical_devices": []}
    for field in data:
        for item in combined.get(field, []):
            if item.get("segment_id") == segment_id:
                data[field].append(item)
    return data


def check_one_segment(seg, seg_data):
    """对单个 segment 运行 LLM 质量检查"""
    seg_text = seg.get("text", "")
    seg_data_json = json.dumps(seg_data, ensure_ascii=False, indent=2)
    user_prompt = f"""原始文本：
{seg_text[:1200]}

抽取结果：
{seg_data_json[:2500]}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": CHECK_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=4096,
            timeout=60,
        )
        content = resp.choices[0].message.content
        if not content:
            return {"uncertainties": [{"item": "LLM 返回空内容", "reason": ""}]}

        # JSON 恢复
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        # 尝试闭合截断的 JSON
        try:
            result = json.loads(content)
            return result
        except json.JSONDecodeError:
            # 修复：补未闭合引号
            fixed = content.rstrip()
            in_str = False; escaped = False
            for ch in fixed:
                if escaped: escaped = False; continue
                if ch == '\\': escaped = True; continue
                if ch == '"': in_str = not in_str
            if in_str:
                fixed += '"'
            # 修复：补未闭合括号
            stack = []
            in_str = False; escaped = False
            for ch in fixed:
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
                fixed += '}' if ch == '{' else ']'
            # 去尾部逗号后再试
            fixed2 = fixed.rstrip()
            if fixed2.endswith(','):
                fixed2 = fixed2[:-1].rstrip()
                stack2 = []
                in_str = False; escaped = False
                for ch in fixed2:
                    if escaped: escaped = False; continue
                    if ch == '\\': escaped = True; continue
                    if ch == '"': in_str = not in_str; continue
                    if in_str: continue
                    if ch in '{[': stack2.append(ch)
                    elif ch == '}':
                        if stack2 and stack2[-1] == '{': stack2.pop()
                    elif ch == ']':
                        if stack2 and stack2[-1] == '[': stack2.pop()
                for ch in reversed(stack2):
                    fixed2 += '}' if ch == '{' else ']'
                try:
                    return json.loads(fixed2)
                except json.JSONDecodeError:
                    pass
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                return {"uncertainties": [{"item": f"LLM 返回无法解析的 JSON: {content[:100]}", "reason": ""}]}
    except Exception as e:
        return {"uncertainties": [{"item": f"LLM check 失败: {str(e)[:100]}", "reason": ""}]}


def llm_check_sample(combined, segments, sample_rate=5, check_results_path=None):
    """对采样的 segment 运行 LLM 质量检查，保存详细结果"""
    sample = segments[::sample_rate]
    print("=" * 60)
    print(f"LLM 质量检查（采样 {len(sample)}/{len(segments)} 段，步长={sample_rate}）")
    print("=" * 60)

    total_high = 0
    total_medium = 0
    total_low = 0
    all_check_results = []

    CHECK_CATEGORIES = ["type_errors", "attribution_errors", "direction_errors",
                         "missing_nodes", "missing_links", "normalization_issues",
                         "relation_type_issues", "polarity_issues", "evidence_issues",
                         "rhetorical_device_issues"]

    for i, seg in enumerate(sample):
        sid = seg.get("segment_id", "")
        seg_data = get_segment_data(combined, sid)
        print(f"  [{i+1}/{len(sample)}] 检查 {sid} ... ", end="", flush=True)

        result = check_one_segment(seg, seg_data)
        high = medium = low = 0
        for cat in CHECK_CATEGORIES:
            for issue in result.get(cat, []):
                sev = issue.get("severity", "low")
                if sev == "high":
                    high += 1
                elif sev == "medium":
                    medium += 1
                else:
                    low += 1
        total_high += high; total_medium += medium; total_low += low
        print(f"high={high} medium={medium} low={low}")

        all_check_results.append({
            "segment_id": sid,
            "high": high, "medium": medium, "low": low,
            "issues": {k: v for k, v in result.items() if k in CHECK_CATEGORIES},
        })

    print()
    print(f"  汇总: high={total_high}, medium={total_medium}, low={total_low}")

    if total_high:
        print(f"  ⚠ 发现 {total_high} 个高危问题")
        if check_results_path:
            atomic_write_json(check_results_path, {"check_results": all_check_results, "total_high": total_high})
            print(f"  详细结果已保存: {check_results_path}")
    elif total_medium:
        print(f"  ⚡ 发现 {total_medium} 个中等问题，建议确认")
    else:
        print(f"  ✅ 未发现明显质量问题")

    return all_check_results


FIX_SYSTEM_PROMPT = """你是思想史论战文本知识图谱抽取结果的修正助手。

我会提供：
1. 原始文本片段；
2. 该片段的部分抽取结果（只含被检查出问题的条目）；
3. 质量检查发现的问题清单。

请根据问题清单，只对有问题条目给出修正。输出简洁的修正 JSON：

{
  "fixed": [
    {"field": "entities", "id": "e3", "changes": {"type": "观点", "claim_type": "反驳性主张"}},
    {"field": "claims", "id": "c1", "changes": {"speaker": "丁文江"}}
  ],
  "delete": [
    {"field": "entities", "id": "e5"},
    {"field": "relations", "id": "r2"}
  ],
  "add": {
    "entities": [{"name": "康德", "type": "Person", "canonical_name": "康德", "evidence": "提到康德"}],
    "claims": [],
    "relations": []
  }
}

fixed 修改已有条目字段，delete 删除条目，add 新增条目。
如果没问题可修，所有数组输出为空。输出必须是严格 JSON，不要 Markdown，不要解释。"""


def fix_one_segment(seg, seg_data, issues_summary):
    seg_text = seg.get("text", "")
    seg_data_json = json.dumps(seg_data, ensure_ascii=False, indent=2)

    issues_text = ""
    for cat_name, cat_issues in issues_summary.items():
        for issue in cat_issues:
            sev = issue.get("severity", "low")
            item = issue.get("item", "")
            suggestion = issue.get("suggestion", "")
            issues_text += f"[{sev}] {cat_name}: {item}"
            if suggestion:
                issues_text += f" (建议: {suggestion})"
            issues_text += "\n"

    user_prompt = f"""原始文本：
{seg_text[:1200]}

当前抽取结果（共 {sum(len(v) for v in seg_data.values())} 条）：
{seg_data_json[:1500]}

检查发现的问题：
{issues_text[:1500]}

请修正以上问题，只输出修正清单 JSON。"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": FIX_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=4096,
            timeout=120,
        )
        content = resp.choices[0].message.content
        if not content:
            return None
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        fixed = content.rstrip()
        in_str = False; escaped = False
        for ch in fixed:
            if escaped: escaped = False; continue
            if ch == '\\': escaped = True; continue
            if ch == '"': in_str = not in_str
        if in_str:
            fixed += '"'
        stack = []
        in_str = False; escaped = False
        for ch in fixed:
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
            fixed += '}' if ch == '{' else ']'
        fixed2 = fixed.rstrip()
        if fixed2.endswith(','):
            fixed2 = fixed2[:-1].rstrip()
            stack2 = []
            in_str = False; escaped = False
            for ch in fixed2:
                if escaped: escaped = False; continue
                if ch == '\\': escaped = True; continue
                if ch == '"': in_str = not in_str; continue
                if in_str: continue
                if ch in '{[': stack2.append(ch)
                elif ch == '}':
                    if stack2 and stack2[-1] == '{': stack2.pop()
                elif ch == ']':
                    if stack2 and stack2[-1] == '[': stack2.pop()
            for ch in reversed(stack2):
                fixed2 += '}' if ch == '{' else ']'
            try:
                return json.loads(fixed2)
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None
    except Exception:
        return None


def auto_fix_issues(combined, segments, check_results, run_dir):
    print("\n" + "=" * 60)
    print("自动修复高危问题")
    print("=" * 60)

    fixed_count = 0
    for cr in check_results:
        sid = cr["segment_id"]
        if cr["high"] == 0:
            continue
        seg = next((s for s in segments if s.get("segment_id") == sid), None)
        if not seg:
            continue
        print(f"  修复 {sid} (high={cr['high']}) ... ", end="", flush=True)
        patch = fix_one_segment(seg, get_segment_data(combined, sid), cr["issues"])
        if patch:
            applied = 0
            for fix in patch.get("fixed", []):
                field = fix.get("field", "")
                item_id = fix.get("id", "")
                changes = fix.get("changes", {})
                if field in combined and item_id:
                    for item in combined[field]:
                        if item.get("id") == item_id:
                            item.update(changes)
                            applied += 1
            for d in patch.get("delete", []):
                field = d.get("field", "")
                item_id = d.get("id", "")
                if field in combined:
                    before = len(combined[field])
                    combined[field] = [it for it in combined[field] if it.get("id") != item_id]
                    if len(combined[field]) < before:
                        applied += 1
            for field in ["entities", "claims", "relations"]:
                for new_item in patch.get("add", {}).get(field, []):
                    combined[field].append(dict(new_item, **{
                        "segment_id": sid, "article_id": seg.get("article_id", ""),
                    }))
                    applied += 1
            fixed_count += 1
            print(f"✓ ({applied} 条修正)")
        else:
            print("✗ (LLM 返回无法解析)")

    if fixed_count:
        combined_path = run_dir / "combined_extract.json"
        atomic_write_json(combined_path, combined)
        print(f"  ✅ 已修复 {fixed_count} 个 segment，更新 {combined_path}")
    else:
        print("  无需修复或无可修复段")
    return fixed_count


def clean_unfixable(combined):
    """删除无法修复的结构性硬伤：仅删空 evidence+低置信、speaker 污染、单字且低置信实体"""
    entities = combined.get("entities", [])
    claims = combined.get("claims", [])
    relations = combined.get("relations", [])
    articles = combined.get("articles", [])

    author_names = {a.get("source_author", "") for a in articles if a.get("source_author")}
    author_names.update(a.get("article_title", "") for a in articles if a.get("article_title"))

    deleted_e = 0
    for e in list(entities):
        name = (e.get("name") or "").strip()
        if len(name) <= 1 and e.get("type") in ("人物", "Person") and float(e.get("confidence", 0.9)) < 0.7:
            entities.remove(e)
            deleted_e += 1

    deleted_r = 0
    for r in list(relations):
        ev = (r.get("evidence") or "").strip()
        conf = float(r.get("confidence", 0.9))
        if r.get("id", "").startswith("cross_seg_"):
            continue
        if not ev and conf < 0.5:
            relations.remove(r)
            deleted_r += 1

    deleted_c = 0
    for c in list(claims):
        ev = (c.get("evidence") or "").strip()
        conf = float(c.get("confidence", 0.9))
        speaker = c.get("speaker", "")
        if (not ev and conf < 0.5) or len(speaker) > 100:
            claims.remove(c)
            deleted_c += 1

    total = deleted_e + deleted_r + deleted_c
    if total:
        print(f"  清理不可修复条目: 实体 {deleted_e} / 关系 {deleted_r} / 主张 {deleted_c}")
    return total


# ============================================================
# 4. Neo4j CSV 导出
# ============================================================

def csv_value(x):
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        return json.dumps(x, ensure_ascii=False)
    return str(x)


def write_csv_rows(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_value(row.get(k, "")) for k in fieldnames})


def make_node_id(prefix, key):
    return f"{prefix}_{stable_hash(key, 16)}"


def compute_article_features(combined):
    features = {a["article_id"]: set() for a in combined.get("articles", [])}
    for e in combined.get("entities", []):
        aid = e.get("article_id", "")
        if aid not in features:
            features[aid] = set()
        name = e.get("canonical_name") or e.get("name")
        typ = e.get("type", "Other")
        if name:
            features[aid].add(f"ENTITY|{typ}|{name}")
    for r in combined.get("relations", []):
        aid = r.get("article_id", "")
        if aid not in features:
            features[aid] = set()
        rel = r.get("relation", "")
        tail = r.get("tail", "")
        pol = r.get("polarity", "unknown")
        if rel and tail:
            features[aid].add(f"REL|{rel}|{tail}|{pol}")
    for c in combined.get("citations", []):
        aid = c.get("article_id", "")
        if aid not in features:
            features[aid] = set()
        qa = c.get("quoted_author", "")
        qw = c.get("quoted_work", "")
        if qa or qw:
            features[aid].add(f"CITE|{qa}|{qw}")
    for cl in combined.get("claims", []):
        aid = cl.get("article_id", "")
        if aid not in features:
            features[aid] = set()
        target = cl.get("target", "")
        pol = cl.get("polarity", "unknown")
        if target:
            features[aid].add(f"CLAIM_TARGET|{target}|{pol}")
    return features


def compute_article_similarity(combined, min_jaccard=0.05):
    features = compute_article_features(combined)
    article_info = {a["article_id"]: a for a in combined.get("articles", [])}
    aids = list(features.keys())
    sims = []
    for i in range(len(aids)):
        for j in range(i + 1, len(aids)):
            a, b = aids[i], aids[j]
            fa, fb = features[a], features[b]
            union = fa | fb
            inter = fa & fb
            score = len(inter) / len(union) if union else 0.0
            if score >= min_jaccard:
                sims.append({
                    "article_id_a": a, "article_title_a": article_info.get(a, {}).get("article_title", ""),
                    "source_author_a": article_info.get(a, {}).get("source_author", ""),
                    "article_id_b": b, "article_title_b": article_info.get(b, {}).get("article_title", ""),
                    "source_author_b": article_info.get(b, {}).get("source_author", ""),
                    "jaccard": round(score, 6), "shared_feature_count": len(inter),
                    "union_feature_count": len(union), "shared_features": sorted(list(inter))[:50],
                })
    sims = sorted(sims, key=lambda x: x["jaccard"], reverse=True)
    return sims


def save_article_similarity_and_communities(combined, neo4j_dir):
    sims = compute_article_similarity(combined)
    sim_json_path = neo4j_dir / "article_similarity.json"
    atomic_write_json(sim_json_path, {"similarities": sims})
    sim_csv_path = neo4j_dir / "article_similarity.csv"
    with sim_csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["article_id_a", "article_title_a", "source_author_a", "article_id_b", "article_title_b",
                       "source_author_b", "jaccard", "shared_feature_count", "union_feature_count"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sims:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    G = nx.Graph()
    for a in combined.get("articles", []):
        G.add_node(a["article_id"], title=a.get("article_title", ""), author=a.get("source_author", ""))
    for s in sims:
        G.add_edge(s["article_id_a"], s["article_id_b"], weight=s["jaccard"])
    communities = []
    if G.number_of_nodes() > 0 and G.number_of_edges() > 0:
        comms = list(nx.algorithms.community.greedy_modularity_communities(G, weight="weight"))
        for cid, comm in enumerate(comms, 1):
            for aid in comm:
                node_data = G.nodes[aid]
                communities.append({"community_id": cid, "article_id": aid, "article_title": node_data.get("title", ""), "source_author": node_data.get("author", "")})
    else:
        for cid, aid in enumerate(G.nodes(), 1):
            node_data = G.nodes[aid]
            communities.append({"community_id": cid, "article_id": aid, "article_title": node_data.get("title", ""), "source_author": node_data.get("author", "")})
    comm_csv_path = neo4j_dir / "article_communities.csv"
    with comm_csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["community_id", "article_id", "article_title", "source_author"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in communities:
            writer.writerow(row)
    print("文章相似度已输出:", sim_csv_path)
    print("文章社区已输出:", comm_csv_path)
    return sims


def export_neo4j_csv(combined, segments, article_sims, neo4j_dir):
    nodes: dict = {}
    rels: list = []

    def add_node(node_id, labels, name="", node_type="", article_id="", segment_id="", title="", text=""):
        if node_id not in nodes:
            nodes[node_id] = {"node_id": node_id, "labels": labels, "name": name, "node_type": node_type,
                              "article_id": article_id, "segment_id": segment_id, "title": title, "text": text}
        else:
            for k, v in {"labels": labels, "name": name, "node_type": node_type, "article_id": article_id,
                          "segment_id": segment_id, "title": title, "text": text}.items():
                if v and not nodes[node_id].get(k):
                    nodes[node_id][k] = v

    def add_rel(source_id, target_id, rel_type, relation="", polarity="", evidence="", confidence="", article_id="", segment_id=""):
        if not source_id or not target_id:
            return
        rels.append({"source_id": source_id, "target_id": target_id, "type": rel_type, "relation": relation,
                      "polarity": polarity, "evidence": evidence, "confidence": confidence,
                      "article_id": article_id, "segment_id": segment_id})

    article_node_ids = {}
    author_node_ids = {}
    for a in combined.get("articles", []):
        aid = a["article_id"]
        article_node_id = make_node_id("article", aid)
        article_node_ids[aid] = article_node_id
        add_node(article_node_id, "Article", name=a.get("article_title", ""), node_type="Article", article_id=aid, title=a.get("article_title", ""))
        author = clean_placeholder(a.get("source_author", ""))
        if author:
            author_node_id = make_node_id("author", author)
            author_node_ids[author] = author_node_id
            add_node(author_node_id, "Author", name=author, node_type="Author")
            add_rel(author_node_id, article_node_id, "WROTE", "WROTE", polarity="neutral", article_id=aid)

    segment_node_ids = {}
    for seg in segments:
        sid = seg["segment_id"]
        aid = seg["article_id"]
        seg_node_id = make_node_id("segment", sid)
        segment_node_ids[sid] = seg_node_id
        add_node(seg_node_id, "Segment", name=sid, node_type="Segment", article_id=aid, segment_id=sid, text=seg.get("text", ""))
        article_node_id = article_node_ids.get(aid)
        if article_node_id:
            add_rel(article_node_id, seg_node_id, "HAS_SEGMENT", "HAS_SEGMENT", polarity="neutral", article_id=aid, segment_id=sid)

    entity_name_to_node = {}
    for e in combined.get("entities", []):
        name = e.get("name", "")
        canonical = e.get("canonical_name") or name
        typ = e.get("type", "Other")
        aid = e.get("article_id", "")
        sid = e.get("segment_id", "")
        if not canonical:
            continue
        ent_node_id = make_node_id("entity", f"{typ}|{canonical}")
        add_node(ent_node_id, typ if typ else "Entity", name=canonical, node_type=typ)
        if name:
            entity_name_to_node[name] = ent_node_id
        if canonical:
            entity_name_to_node[canonical] = ent_node_id
        seg_node_id = segment_node_ids.get(sid)
        if seg_node_id:
            add_rel(seg_node_id, ent_node_id, "MENTIONS", "MENTIONS", polarity="neutral", evidence=e.get("evidence", ""), confidence=e.get("confidence", ""), article_id=aid, segment_id=sid)

    def get_or_create_term_node(name, typ="Term"):
        name = clean_placeholder(name)
        typ = clean_placeholder(typ) or "Term"
        if not name:
            return ""
        if name in entity_name_to_node:
            return entity_name_to_node[name]
        node_id = make_node_id("term", f"{typ}|{name}")
        add_node(node_id, typ if typ else "Term", name=name, node_type=typ)
        entity_name_to_node[name] = node_id
        return node_id

    for c in combined.get("claims", []):
        claim = c.get("claim", "")
        aid = c.get("article_id", "")
        sid = c.get("segment_id", "")
        if not claim:
            continue
        claim_node_id = make_node_id("claim", f"{aid}|{claim}")
        add_node(claim_node_id, "Claim", name=claim[:80], node_type="Claim", article_id=aid, text=claim)
        seg_node_id = segment_node_ids.get(sid)
        if seg_node_id:
            add_rel(seg_node_id, claim_node_id, "MAKES_CLAIM", "MAKES_CLAIM", polarity=c.get("polarity", "unknown"),
                    evidence=c.get("evidence", ""), confidence=c.get("confidence", ""), article_id=aid, segment_id=sid)

    for r in combined.get("relations", []):
        head = r.get("head", "")
        tail = r.get("tail", "")
        aid = r.get("article_id", "")
        sid = r.get("segment_id", "")
        if not head or not tail:
            continue
        head_node = get_or_create_term_node(head, r.get("head_type", "Term"))
        tail_node = get_or_create_term_node(tail, r.get("tail_type", "Term"))
        add_rel(head_node, tail_node, "RELATES_TO", relation=r.get("relation", ""), polarity=r.get("polarity", "unknown"),
                evidence=r.get("evidence", ""), confidence=r.get("confidence", ""), article_id=aid, segment_id=sid)
        seg_node_id = segment_node_ids.get(sid)
        if seg_node_id:
            add_rel(seg_node_id, head_node, "MENTIONS", "MENTIONS_RELATION_HEAD", polarity="neutral",
                    evidence=r.get("evidence", ""), confidence=r.get("confidence", ""), article_id=aid, segment_id=sid)
            add_rel(seg_node_id, tail_node, "MENTIONS", "MENTIONS_RELATION_TAIL", polarity="neutral",
                    evidence=r.get("evidence", ""), confidence=r.get("confidence", ""), article_id=aid, segment_id=sid)

    for c in combined.get("citations", []):
        aid = c.get("article_id", "")
        sid = c.get("segment_id", "")
        quoted_author = c.get("quoted_author", "")
        quoted_work = c.get("quoted_work", "")
        seg_node_id = segment_node_ids.get(sid)
        if quoted_author:
            qa_node = get_or_create_term_node(quoted_author, "人物")
            if seg_node_id:
                add_rel(seg_node_id, qa_node, "CITES", "CITES_AUTHOR", polarity="neutral",
                        evidence=c.get("evidence", ""), confidence=c.get("confidence", ""), article_id=aid, segment_id=sid)
        if quoted_work:
            qw_node = get_or_create_term_node(quoted_work, "Work")
            if seg_node_id:
                add_rel(seg_node_id, qw_node, "CITES", "CITES_WORK", polarity="neutral",
                        evidence=c.get("evidence", ""), confidence=c.get("confidence", ""), article_id=aid, segment_id=sid)

    for s in article_sims:
        node_a = article_node_ids.get(s.get("article_id_a", ""))
        node_b = article_node_ids.get(s.get("article_id_b", ""))
        if node_a and node_b:
            add_rel(node_a, node_b, "SIMILAR_TO", "JACCARD_SIMILARITY", polarity="neutral",
                    evidence=f"jaccard={s.get('jaccard','')}; shared={s.get('shared_feature_count','')}",
                    confidence=s.get("jaccard", ""))

    node_rows = list(nodes.values())
    node_cols = ["node_id", "labels", "name", "node_type", "article_id", "segment_id", "title", "text"]
    rel_cols = ["source_id", "target_id", "type", "relation", "polarity", "evidence", "confidence", "article_id", "segment_id"]
    nodes_path = neo4j_dir / "nodes.csv"
    rels_path = neo4j_dir / "relationships.csv"
    write_csv_rows(nodes_path, node_rows, node_cols)
    write_csv_rows(rels_path, rels, rel_cols)

    guide = """// Neo4j 导入示例
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (n:KGNode {id: row.node_id})
SET n.labels = row.labels, n.name = row.name, n.node_type = row.node_type,
    n.article_id = row.article_id, n.segment_id = row.segment_id, n.title = row.title, n.text = row.text;

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
MATCH (s:KGNode {id: row.source_id})
MATCH (t:KGNode {id: row.target_id})
MERGE (s)-[r:KG_RELATION {type: row.type, relation: row.relation, segment_id: row.segment_id, evidence: row.evidence}]->(t)
SET r.polarity = row.polarity, r.confidence = row.confidence, r.article_id = row.article_id;
"""
    atomic_write_text(neo4j_dir / "neo4j_load_guide.cypher", guide.strip())
    print("Neo4j CSV 已输出:", nodes_path, rels_path)


def write_source_info(combined, run_dir):
    articles = combined.get("articles", [])
    if not articles:
        return
    source_files = sorted(set(a.get("source_file", "") for a in articles if a.get("source_file")))
    authors = sorted(set(a.get("source_author", "") for a in articles if a.get("source_author")))
    lines = []
    if source_files:
        lines.append("源文件：")
        for s in source_files:
            lines.append(f"  {s}")
    if authors:
        lines.append("作者：")
        for a in authors:
            lines.append(f"  {a}")
    lines.append("")
    lines.append("文章清单：")
    for i, a in enumerate(articles, 1):
        lines.append(f"  {i}. {a.get('article_title','')}  (作者={a.get('source_author','')}, 文件={a.get('source_file','')})")
    info_path = run_dir / "source_info.txt"
    info_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"source_info.txt: {info_path}")


# ============================================================
# 5. 主函数
# ============================================================

def run():
    run_dir = find_run_dir()
    neo4j_dir = run_dir / "neo4j"
    neo4j_dir.mkdir(parents=True, exist_ok=True)

    print(f"运行目录: {run_dir}")

    combined_path = run_dir / "combined_extract.json"
    combined = json.loads(combined_path.read_text(encoding="utf-8"))
    segments_path = run_dir / "segments.jsonl"
    segments = load_jsonl(segments_path)

    # 1. 结构性检查
    structural_check(combined)

    # 2. LLM 检查（采样）
    check_results = []
    if API_KEY and not os.environ.get("KG_SKIP_LLM_CHECK", ""):
        sample_rate = max(1, len(segments) // 10) if len(segments) > 20 else 1
        check_results_path = run_dir / "check_results.json"
        check_results = llm_check_sample(combined, segments, sample_rate=sample_rate,
                                          check_results_path=check_results_path)
    else:
        print("跳过 LLM 检查")

    # 2.5 自动修复高危问题
    if check_results:
        auto_fix_issues(combined, segments, check_results, run_dir)
        # 修复后清理不可修复的硬伤
        clean_unfixable(combined)
        # 重新写入清理后的数据
        atomic_write_json(run_dir / "combined_extract.json", combined)

    # 3. 生成 Neo4j CSV
    print("\n" + "=" * 60)
    print("生成 Neo4j CSV")
    print("=" * 60)
    article_sims = save_article_similarity_and_communities(combined, neo4j_dir)
    export_neo4j_csv(combined, segments, article_sims, neo4j_dir)

    # 4. 写 source_info.txt
    write_source_info(combined, run_dir)

    print("\n✅ 最终检查 + Neo4j CSV 全部完成")


if __name__ == "__main__":
    print("正在运行最终质量检查 + Neo4j CSV 生成")
    run()
