"""
科学玄学论战知识图谱抽取 Workflow
本地版 — 适用于 Windows 环境
"""

# ============================================================
# 1. Imports
# ============================================================

import os
import re
import csv
import json
import time
import shutil
import hashlib
import traceback
import sys
from pathlib import Path
from datetime import datetime
from getpass import getpass
from typing import Any, Dict, List, Tuple, Optional

try:
    from tqdm.auto import tqdm
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    from openai import OpenAI
    from json_repair import repair_json
    import networkx as nx
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请运行: pip install -r requirements.txt")
    sys.exit(1)


# ============================================================
# 2. 全局配置（从 config.py 读取，可覆盖）
# ============================================================

from config import (
    WORKSPACE_DIR, INPUT_DIR, RUN_ROOT,
    API_KEY_ENV_NAME, BASE_URL, MODEL,
    TEMPERATURE, MAX_TOKENS, REQUEST_TIMEOUT_SECONDS, MAX_API_RETRY, REQUEST_SLEEP_SECONDS,
    SEGMENT_MAX_CHARS, SEGMENT_OVERLAP,
    FORCE_RERUN_SUCCESS, RERUN_FAILED_AFTER_MAIN, FAILED_RERUN_PASSES,
    STRICT_EVIDENCE_CHECK, DROP_UNSUPPORTED_EVIDENCE,
    PROJECT_NAME, SCHEMA_VERSION, PROMPT_VERSION, PROMPT_VARIANT,
    get_extract_prompt,
    ARTICLE_METADATA_OVERRIDES,
)

# 本地运行无需/不可用 Colab 功能
AUTO_UPLOAD_IN_COLAB = False
SKIP_CODE_LIKE_TXT = True
AUTO_SPLIT_BY_TITLE_AUTHOR = True
INPUT_FILES: List[str] = []
ARTICLE_SIMILARITY_MIN = 0.05


# ============================================================
# 3. 路径初始化
# ============================================================

# 占位，文件收集后更新
run_dir = None
raw_dir = None
parsed_dir = None
logs_dir = None
neo4j_dir = None


# ============================================================
# 4. 工具函数
# ============================================================

def clean_placeholder(x: Any) -> str:
    x = "" if x is None else str(x).strip()
    if x.startswith("{{") and x.endswith("}}"):
        return ""
    return x


def safe_filename(s: str, max_len: int = 80) -> str:
    s = clean_placeholder(s)
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:max_len] or "untitled"


def stable_hash(s: str, n: int = 10) -> str:
    return hashlib.sha1(str(s).encode("utf-8", errors="ignore")).hexdigest()[:n]


def normalize_newlines(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def read_text_guess_encoding(path: Path, max_chars: Optional[int] = None) -> str:
    data = path.read_bytes()
    for enc in ["utf-8", "utf-8-sig", "gb18030", "big5"]:
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    text = normalize_newlines(text)
    if max_chars is not None:
        return text[:max_chars]
    return text


def looks_like_code_txt(text: str) -> bool:
    head = text[:4000]
    markers = ["!pip", "from openai import", "OpenAI(", "client.chat.completions",
               "json_repair", "BASE_URL", "def ", "import os", "import json", "ARTICLE_TEXT_PATH"]
    score = sum(1 for m in markers if m in head)
    return score >= 3


def atomic_write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_json(path: Path, obj: Dict[str, Any], indent: int = 2):
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=indent))


def append_jsonl(path: Path, row: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_error_log(msg: str):
    log_path = logs_dir / "errors.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def log_event(event: Dict[str, Any]):
    event = dict(event)
    event.setdefault("logged_at", datetime.now().isoformat(timespec="seconds"))
    append_jsonl(logs_dir / "worklog.jsonl", event)


def _s(x: Any) -> str:
    return "" if x is None else str(x)


def _conf(x: Any, default: float = 0.80) -> float:
    try:
        v = float(x)
        if v < 0:
            return 0.0
        if v > 1:
            return 1.0
        return v
    except Exception:
        return default


# ============================================================
# 5. 收集输入文件
# ============================================================

def collect_input_txt_files() -> List[Path]:
    candidates: List[Path] = []
    for f in INPUT_FILES:
        p = Path(f)
        if p.exists() and p.is_file() and p.suffix.lower() == ".txt":
            candidates.append(p)
        else:
            print("警告：指定文件不存在或不是 txt:", f)
    if not candidates:
        input_dir = Path(INPUT_DIR)
        input_dir.mkdir(parents=True, exist_ok=True)
        candidates.extend(sorted(input_dir.glob("*.txt")))
    if not candidates:
        search_dirs = [INPUT_DIR, WORKSPACE_DIR]
        for d in search_dirs:
            if d.exists():
                for p in sorted(d.glob("*.txt")):
                    if str(Path(RUN_ROOT)) in str(p):
                        continue
                    candidates.append(p)
    unique = []
    seen = set()
    for p in candidates:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    valid = []
    for p in unique:
        try:
            head = read_text_guess_encoding(p, max_chars=5000)
        except Exception as e:
            print("无法读取，跳过:", p, repr(e))
            continue
        if SKIP_CODE_LIKE_TXT and looks_like_code_txt(head):
            print("跳过疑似代码文件:", p)
            continue
        valid.append(p)
    if not valid:
        raise FileNotFoundError(
            "没有找到有效 txt 文件。请把文章 txt 放到 INPUT_DIR，"
            "或在 INPUT_FILES 中显式指定文件路径。"
        )
    return valid


# ============================================================
# 6. 解析文章元数据
# ============================================================

def get_metadata_override(path: Path) -> Dict[str, str]:
    return (
        ARTICLE_METADATA_OVERRIDES.get(path.name)
        or ARTICLE_METADATA_OVERRIDES.get(path.stem)
        or {}
    )


def detect_metadata_value(text: str, key: str) -> str:
    pattern = rf"(?m)^\s*{re.escape(key)}[：:]\s*(.+?)\s*$"
    m = re.search(pattern, text)
    if m:
        return m.group(1).strip()
    return ""


def remove_leading_metadata_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*(标题|作者)[：:]", line):
            continue
        if re.match(r"^\s*=+\s*$", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


TITLE_AUTHOR_MAP = {
    "东荪按": "张东荪", "独秀按": "陈独秀", "适之按": "胡适",
    "在君按": "丁文江", "君劢按": "张君劢", "伏园按": "孙伏园",
    "宰平按": "林宰平",
}

def _infer_author_from_title(title: str) -> str:
    clean = title.rstrip(":：").strip()
    return TITLE_AUTHOR_MAP.get(clean, "")


def parse_articles_from_file(path: Path) -> List[Dict[str, Any]]:
    raw_text = read_text_guess_encoding(path)
    raw_text = normalize_newlines(raw_text).strip()
    if not raw_text:
        return []
    override = get_metadata_override(path)
    title_matches = []
    if AUTO_SPLIT_BY_TITLE_AUTHOR:
        title_matches = list(re.finditer(r"(?m)^\s*标题[：:]\s*(.+?)\s*$", raw_text))
    articles = []
    if title_matches:
        for idx, m in enumerate(title_matches):
            start = m.start()
            end = title_matches[idx + 1].start() if idx + 1 < len(title_matches) else len(raw_text)
            section = raw_text[start:end].strip()
            detected_title = m.group(1).strip()
            detected_author = detect_metadata_value(section, "作者") or _infer_author_from_title(detected_title)
            title = clean_placeholder(override.get("title") or detected_title or path.stem)
            author = clean_placeholder(override.get("author") or detected_author)
            content = remove_leading_metadata_lines(section)
            if not content.strip():
                continue
            article_id = f"{safe_filename(path.stem, 30)}_{idx:03d}_{stable_hash(title + author + content[:500], 8)}"
            articles.append({
                "article_id": article_id,
                "article_title": title,
                "source_author": author,
                "source_file": str(path),
                "article_index_in_file": idx,
                "text": content,
            })
    else:
        detected_title = detect_metadata_value(raw_text, "标题")
        detected_author = detect_metadata_value(raw_text, "作者") or _infer_author_from_title(detected_title)
        title = clean_placeholder(override.get("title") or detected_title or path.stem)
        author = clean_placeholder(override.get("author") or detected_author)
        content = remove_leading_metadata_lines(raw_text) if (detected_title or detected_author) else raw_text
        article_id = f"{safe_filename(path.stem, 30)}_000_{stable_hash(title + author + content[:500], 8)}"
        articles.append({
            "article_id": article_id,
            "article_title": title,
            "source_author": author,
            "source_file": str(path),
            "article_index_in_file": 0,
            "text": content,
        })
    return articles


# ============================================================
# 7. 分段（含 section 检测）
# ============================================================

def _detect_sections(text: str) -> list[dict]:
    """检测文章内的子段落：东荪按、独秀按等"""
    sections = []
    pattern = r"(?m)^\s*[\[【]?(.+?)[\]】]?(?:按|附记|附注)[：:\s]*"
    matches = list(re.finditer(pattern, text))
    if not matches:
        return [{"section_title": "", "section_author": "", "start": 0, "end": len(text)}]
    for i, m in enumerate(matches):
        author = m.group(1).strip()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({
            "section_title": f"{author}按",
            "section_author": author,
            "start": start,
            "end": end,
        })
    return sections


def _find_section(sections: list[dict], char_pos: int) -> dict:
    for sec in sections:
        if sec["start"] <= char_pos < sec["end"]:
            return sec
    return sections[-1] if sections else {"section_title": "", "section_author": "", "start": 0, "end": 0}


def split_text_by_chars(
    text: str,
    max_chars: int = 900,
    overlap: int = 80,
    min_cut_ratio: float = 0.55,
) -> List[Dict[str, Any]]:
    text = normalize_newlines(text)
    n = len(text)
    max_chars = max(200, int(max_chars))
    overlap = max(0, min(int(overlap), max_chars // 3))
    cut_marks = "。！？；\n"
    segments = []
    start = 0
    guard = 0
    while start < n:
        guard += 1
        if guard > 100000:
            raise RuntimeError("split_text_by_chars 出现异常循环")
        tentative = min(start + max_chars, n)
        end = tentative
        if tentative < n:
            min_cut = start + max(100, int(max_chars * min_cut_ratio))
            min_cut = min(min_cut, tentative)
            window = text[min_cut:tentative]
            best = -1
            for ch in cut_marks:
                best = max(best, window.rfind(ch))
            if best >= 0:
                end = min_cut + best + 1
        raw = text[start:end]
        left_trim = len(raw) - len(raw.lstrip())
        right_trim = len(raw) - len(raw.rstrip())
        seg_start = start + left_trim
        seg_end = end - right_trim
        seg_text = text[seg_start:seg_end]
        if seg_text.strip():
            segments.append({
                "char_start": seg_start,
                "char_end": seg_end,
                "text": seg_text,
            })
        if end >= n:
            break
        next_start = max(end - overlap, start + 1)
        if next_start <= start:
            next_start = end
        start = next_start
    return segments


def build_segments_for_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    all_segments = []
    for article in articles:
        raw_segments = split_text_by_chars(
            article["text"],
            max_chars=SEGMENT_MAX_CHARS,
            overlap=SEGMENT_OVERLAP,
        )
        sections = _detect_sections(article["text"])
        for i, seg in enumerate(raw_segments):
            segment_id = f"{article['article_id']}_s{i:04d}"
            sec = _find_section(sections, seg["char_start"])
            all_segments.append({
                "article_id": article["article_id"],
                "article_title": article["article_title"],
                "source_author": article.get("source_author", ""),
                "section_title": sec["section_title"],
                "section_author": sec["section_author"],
                "source_file": article.get("source_file", ""),
                "segment_id": segment_id,
                "segment_index": i,
                "char_start": seg["char_start"],
                "char_end": seg["char_end"],
                "text": seg["text"],
            })
    return all_segments


# ============================================================
# 8. Prompt
# ============================================================

EXTRACT_SYSTEM_PROMPT = get_extract_prompt()




def make_extract_messages(seg: Dict[str, Any]) -> List[Dict[str, str]]:
    source_author = clean_placeholder(seg.get("source_author", ""))
    section_author = clean_placeholder(seg.get("section_author", ""))
    segment_text = seg.get("text", "")
    assert segment_text.strip(), f"{seg.get('segment_id')}: segment_text 为空"

    meta = {
        "schema_version": SCHEMA_VERSION,
        "article_id": clean_placeholder(seg.get("article_id", "")),
        "article_title": clean_placeholder(seg.get("article_title", "")),
        "source_author": source_author,
        "section_title": clean_placeholder(seg.get("section_title", "")),
        "section_author": section_author,
        "segment_id": clean_placeholder(seg.get("segment_id", "")),
        "segment_index": int(seg.get("segment_index", 0)),
        "source_file": clean_placeholder(seg.get("source_file", "")),
    }

    user_prompt = f"""
【元数据 JSON】
{json.dumps(meta, ensure_ascii=False, indent=2)}

【当前文本片段】
<<<TEXT
{segment_text}
TEXT>>>

请只根据【当前文本片段】抽取信息，并把【元数据 JSON】中的值原样填入 metadata。
"""

    return [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# ============================================================
# 9. API Client
# ============================================================

def _prompt_api_key() -> str:
    print("请输入 SiliconFlow API Key。")
    print("提示：也可先在上一 cell 运行 import os; os.environ['SILICONFLOW_API_KEY']='你的Key' 再执行本 cell")
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
        "无法获取有效的 API Key。请设置环境变量:\n"
        "  set SILICONFLOW_API_KEY=sk-你的Key\n"
        "或修改 config.py 后重新运行。"
    )

API_KEY = os.getenv(API_KEY_ENV_NAME, "").strip()
if not API_KEY:
    API_KEY = _prompt_api_key()
    os.environ[API_KEY_ENV_NAME] = API_KEY

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    timeout=REQUEST_TIMEOUT_SECONDS,
    max_retries=0,
)


@retry(
    stop=stop_after_attempt(MAX_API_RETRY),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def call_llm(messages: List[Dict[str, str]]) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    content = resp.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("模型返回空内容")
    return content


# ============================================================
# 10. JSON 解析与 schema 标准化
# ============================================================

TOP_LEVEL_FIELDS = [
    "metadata", "entities", "claims", "relations", "definitions",
    "citations", "rhetorical_devices", "uncertainties",
]

POLARITY_MAP = {
    "正面": "positive", "肯定": "positive", "赞同": "positive", "支持": "positive",
    "+": "positive", "+1": "positive", "positive": "positive",
    "负面": "negative", "否定": "negative", "反对": "negative", "批评": "negative",
    "贬抑": "negative", "-": "negative", "-1": "negative", "negative": "negative",
    "中性": "neutral", "描述": "neutral", "neutral": "neutral", "0": "neutral",
    "复杂": "mixed", "混合": "mixed", "mixed": "mixed",
    "未知": "unknown", "不明": "unknown", "无法判断": "unknown", "unknown": "unknown", "": "unknown",
}

# CN variations → standard CN type (identity + normalization)
ENTITY_TYPE_MAP = {
    "人物": "人物", "人名": "人物", "作者": "人物",
    "概念": "概念", "术语": "概念", "思想": "概念",
    "阵营": "阵营/群体", "阵营/群体": "阵营/群体", "群体": "阵营/群体",
    "主义": "主义/学说/理论", "主义/学说/理论": "主义/学说/理论", "学说": "主义/学说/理论", "理论": "主义/学说/理论",
    "方法": "方法", "方法论": "方法",
    "方法论原则": "方法论原则",
    "著作": "著作", "作品": "著作", "书籍": "著作",
    "文章": "文章", "论文": "文章",
    "组织": "组织", "机构": "组织",
    "地点": "地点", "位置": "地点",
    "事件": "历史事件", "历史事件": "历史事件",
    "观点": "观点", "立场": "观点",
    "论据": "论据", "前提": "论据",
    "结论": "结论",
    "评价": "评价",
    "比喻": "比喻/类比", "比喻/类比": "比喻/类比", "类比": "比喻/类比",
    "问题": "问题",
    "阶段": "阶段",
    "例证": "例证",
    "": "概念",
}

# EN → CN reverse mapping (LLM often outputs English despite CN prompt)
EN_TO_CN_TYPE = {
    "Person": "人物", "Faction": "阵营/群体", "Concept": "概念",
    "Theory": "主义/学说/理论", "Method": "方法", "Principle": "方法论原则",
    "Book": "著作", "Article": "文章", "Event": "历史事件",
    "Viewpoint": "观点", "Argument": "论据", "Conclusion": "结论",
    "Evaluation": "评价", "Metaphor": "比喻/类比", "Question": "问题",
    "Phase": "阶段", "Example": "例证",
    "Organization": "组织", "Location": "地点", "Work": "著作",
    "Discipline": "概念", "Other": "概念", "unknown": "概念",
    # lowercase variants for robustness
    "person": "人物", "faction": "阵营/群体", "concept": "概念",
    "theory": "主义/学说/理论", "method": "方法", "principle": "方法论原则",
    "book": "著作", "article": "文章", "event": "历史事件",
    "viewpoint": "观点", "argument": "论据", "conclusion": "结论",
    "evaluation": "评价", "metaphor": "比喻/类比", "question": "问题",
    "phase": "阶段", "example": "例证",
    "organization": "组织", "location": "地点", "work": "著作",
    "discipline": "概念", "other": "概念",
}

# CN variations → standard CN relation (identity + normalization)
RELATION_MAP = {
    "提到": "引用", "涉及": "引用",
    "支持": "支持", "赞同": "支持",
    "反对": "反对", "否定": "反对", "挑战": "反对",
    "批评": "批评", "攻击": "批评",
    "肯定": "支持",
    "定义": "定义", "重新定义": "定义",
    "回应": "回应", "再回应": "回应",
    "比较": "对比", "对比": "对比", "类比": "类比",
    "导致": "导致", "造成": "导致", "支配": "导致",
    "属于": "属于", "包含": "包含",
    "相关": "相关", "关联": "相关",
    "质疑": "质疑",
    "反驳": "反驳",
    "解释": "解释",
    "证明": "证明", "推出": "推出",
    "归谬": "归谬",
    "归因于": "归因于", "源自": "源自",
    "影响": "影响",
    "区分": "区分",
    "混淆": "混淆",
    "作为论据支持": "作为论据支持",
    "作为理由反驳": "作为理由反驳",
    "作为反例反驳": "作为反例反驳",
    "继承": "继承",
    "发展": "发展",
    "转化": "转化",
    "修正": "修正",
    "自相矛盾": "自相矛盾",
    "承接": "承接",
    "转折": "转折",
    "主张": "主张",
    "": "相关",
}

# EN → CN reverse (LLM often outputs English relation types)
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
    "OTHER": "相关",
}


def coerce_polarity(x: Any) -> str:
    x = clean_placeholder(x)
    return POLARITY_MAP.get(x, POLARITY_MAP.get(x.lower(), "unknown"))


def coerce_entity_type(x: Any) -> str:
    x = clean_placeholder(x)
    if not x:
        return "概念"
    cn = ENTITY_TYPE_MAP.get(x) or ENTITY_TYPE_MAP.get(x.lower())
    if cn:
        return cn
    result = EN_TO_CN_TYPE.get(x) or EN_TO_CN_TYPE.get(x.lower())
    return result if result else "概念"


def coerce_relation(x: Any) -> str:
    x = clean_placeholder(x)
    if not x:
        return "相关"
    cn = RELATION_MAP.get(x) or RELATION_MAP.get(x.lower())
    if cn:
        return cn
    result = EN_TO_CN_RELATION.get(x) or EN_TO_CN_RELATION.get(x.upper())
    return result if result else "相关"


def strip_markdown_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json|JSON)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def extract_first_json_object(s: str) -> str:
    s = strip_markdown_fence(s)
    try:
        json.loads(s)
        return s
    except Exception:
        pass
    start = s.find("{")
    if start < 0:
        raise ValueError("模型输出中找不到 JSON 对象起始符 {")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
    raise ValueError("模型输出中 JSON 对象括号不完整")


def parse_model_json(raw_text: str) -> Dict[str, Any]:
    candidate = extract_first_json_object(raw_text)
    try:
        obj = json.loads(candidate)
    except Exception:
        repaired = repair_json(candidate)
        obj = json.loads(repaired)
    if not isinstance(obj, dict):
        raise ValueError("模型输出不是 JSON object")
    return obj


def empty_extract_result(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "article_id": clean_placeholder(meta.get("article_id", "")),
            "article_title": clean_placeholder(meta.get("article_title", "")),
            "source_author": clean_placeholder(meta.get("source_author", "")),
            "section_title": clean_placeholder(meta.get("section_title", "")),
            "section_author": clean_placeholder(meta.get("section_author", "")),
            "segment_id": clean_placeholder(meta.get("segment_id", "")),
            "segment_index": int(meta.get("segment_index", 0) or 0),
            "source_file": clean_placeholder(meta.get("source_file", "")),
        },
        "entities": [], "claims": [], "relations": [], "definitions": [],
        "citations": [], "rhetorical_devices": [], "uncertainties": [],
    }


def normalize_extract_schema(obj: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        obj = {}
    out = empty_extract_result(meta)

    for i, x in enumerate(obj.get("entities") or [], 1):
        if not isinstance(x, dict):
            continue
        name = _s(x.get("name") or x.get("entity") or x.get("text") or "").strip()
        evidence = _s(x.get("evidence") or "").strip()
        if not name and not evidence:
            continue
        canonical_name = _s(x.get("canonical_name") or x.get("normalized_name") or name).strip()
        out["entities"].append({
            "id": _s(x.get("id") or f"e{i}"),
            "name": name, "canonical_name": canonical_name,
            "type": coerce_entity_type(x.get("type") or x.get("entity_type") or ""),
            "evidence": evidence, "confidence": _conf(x.get("confidence")),
        })

    for i, x in enumerate(obj.get("claims") or [], 1):
        if not isinstance(x, dict):
            continue
        claim = _s(x.get("claim") or x.get("content") or x.get("text") or "").strip()
        evidence = _s(x.get("evidence") or "").strip()
        if not claim and not evidence:
            continue
        out["claims"].append({
            "id": _s(x.get("id") or f"c{i}"),
            "speaker": _s(x.get("speaker") or x.get("subject") or x.get("author") or "").strip(),
            "claim": claim,
            "target": _s(x.get("target") or "").strip(),
            "claim_type": _s(x.get("claim_type") or "").strip(),
            "claim_status": _s(x.get("claim_status") or "").strip(),
            "polarity": coerce_polarity(x.get("polarity")),
            "evidence": evidence, "confidence": _conf(x.get("confidence")),
        })

    for i, x in enumerate(obj.get("relations") or [], 1):
        if not isinstance(x, dict):
            continue
        relation = coerce_relation(x.get("relation") or x.get("type") or "")
        evidence = _s(x.get("evidence") or "").strip()
        head = _s(x.get("head") or x.get("from_entity") or x.get("source_entity") or x.get("source") or x.get("from") or "").strip()
        tail = _s(x.get("tail") or x.get("to_entity") or x.get("target_entity") or x.get("target") or x.get("to") or "").strip()
        if not relation and not evidence:
            continue
        out["relations"].append({
            "id": _s(x.get("id") or f"r{i}"),
            "head": head, "head_type": coerce_entity_type(x.get("head_type") or ""),
            "relation": relation,
            "tail": tail, "tail_type": coerce_entity_type(x.get("tail_type") or ""),
            "polarity": coerce_polarity(x.get("polarity")),
            "evidence": evidence, "confidence": _conf(x.get("confidence")),
        })

    for i, x in enumerate(obj.get("definitions") or [], 1):
        if not isinstance(x, dict):
            continue
        term = _s(x.get("term") or "").strip()
        definition = _s(x.get("definition") or x.get("content") or "").strip()
        evidence = _s(x.get("evidence") or "").strip()
        if not term and not definition and not evidence:
            continue
        out["definitions"].append({
            "id": _s(x.get("id") or f"def{i}"),
            "term": term, "definition": definition,
            "evidence": evidence, "confidence": _conf(x.get("confidence")),
        })

    for i, x in enumerate(obj.get("citations") or [], 1):
        if not isinstance(x, dict):
            continue
        quoted_claim = _s(x.get("quoted_claim") or x.get("content") or x.get("claim") or "").strip()
        evidence = _s(x.get("evidence") or "").strip()
        if not quoted_claim and not evidence:
            continue
        out["citations"].append({
            "id": _s(x.get("id") or f"cit{i}"),
            "citer": _s(x.get("citer") or "").strip(),
            "quoted_author": _s(x.get("quoted_author") or x.get("source") or "").strip(),
            "quoted_work": _s(x.get("quoted_work") or "").strip(),
            "quoted_claim": quoted_claim,
            "function": _s(x.get("function") or "").strip(),
            "evidence": evidence, "confidence": _conf(x.get("confidence")),
        })

    for i, x in enumerate(obj.get("rhetorical_devices") or [], 1):
        if not isinstance(x, dict):
            continue
        expression = _s(x.get("expression") or x.get("content") or "").strip()
        evidence = _s(x.get("evidence") or "").strip()
        if not expression and not evidence:
            continue
        out["rhetorical_devices"].append({
            "id": _s(x.get("id") or f"rh{i}"),
            "expression": expression,
            "device_type": _s(x.get("device_type") or x.get("type") or "").strip(),
            "literal_target": _s(x.get("literal_target") or "").strip(),
            "function": _s(x.get("function") or "").strip(),
            "evidence": evidence, "confidence": _conf(x.get("confidence")),
        })

    for x in obj.get("uncertainties") or []:
        if not isinstance(x, dict):
            continue
        item = _s(x.get("item") or x.get("content") or "").strip()
        reason = _s(x.get("reason") or x.get("evidence") or "").strip()
        if not item and not reason:
            continue
        out["uncertainties"].append({"item": item, "reason": reason})

    return out


# ============================================================
# 11. 话语主体修复与 evidence 严格过滤
# ============================================================

def has_first_person(s: str) -> bool:
    s = s or ""
    return bool(re.search(r"(我|我们|吾|余|笔者|本文作者|作者)", s))


def postprocess_discourse_roles(out: Dict[str, Any], segment_text: str) -> Dict[str, Any]:
    source_author = clean_placeholder(out["metadata"].get("source_author", ""))
    section_author = clean_placeholder(out["metadata"].get("section_author", ""))

    # 优先使用 section_author
    primary_author = section_author or source_author

    for c in out.get("claims", []):
        ev = c.get("evidence", "")
        sp = clean_placeholder(c.get("speaker", ""))
        if primary_author:
            if sp in {"", "我", "我们", "吾", "余", "作者", "本文作者", "笔者"}:
                sp = primary_author
        else:
            if sp and sp not in {"我", "我们", "吾", "余", "作者", "本文作者", "笔者"}:
                if sp not in ev and sp not in segment_text:
                    sp = "我" if has_first_person(ev) else "作者"
            elif not sp:
                sp = "我" if has_first_person(ev) else "作者"
        c["speaker"] = sp

    for q in out.get("citations", []):
        ev = q.get("evidence", "")
        citer = clean_placeholder(q.get("citer", ""))
        if primary_author:
            if citer in {"", "我", "我们", "吾", "余", "作者", "本文作者", "笔者"}:
                citer = primary_author
        else:
            if not citer:
                citer = "我" if has_first_person(ev) else "作者"
        q["citer"] = citer

    likely_author_relations = {
        "CRITICIZES", "AFFIRMS", "SUPPORTS", "OPPOSES", "CITES", "RESPONDS_TO",
        "认为", "批评", "评价", "质疑", "反驳", "赞同", "引用", "主张", "指出",
    }
    for r in out.get("relations", []):
        ev = r.get("evidence", "")
        rel = r.get("relation", "")
        head = clean_placeholder(r.get("head", ""))
        if primary_author:
            if head in {"", "我", "我们", "吾", "余", "作者", "本文作者", "笔者"}:
                head = primary_author
        else:
            if head and head not in {"我", "我们", "吾", "余", "作者", "本文作者", "笔者"}:
                if head not in ev and head not in segment_text and rel in likely_author_relations:
                    head = "作者"
            elif not head and rel in likely_author_relations:
                head = "我" if has_first_person(ev) else "作者"
        r["head"] = head

    return out


def evidence_supported(evidence: str, segment_text: str) -> bool:
    evidence = (evidence or "").strip()
    segment_text = segment_text or ""
    if not evidence:
        return False
    if evidence in segment_text:
        return True
    ev_compact = re.sub(r"\s+", "", evidence)
    text_compact = re.sub(r"\s+", "", segment_text)
    return bool(ev_compact and ev_compact in text_compact)


def is_claim_id(x: str) -> bool:
    return bool(re.fullmatch(r"c\d+", x or ""))


def endpoint_supported(endpoint: str, evidence: str, source_author: str, section_author: str = "") -> bool:
    endpoint = clean_placeholder(endpoint)
    evidence = evidence or ""
    source_author = clean_placeholder(source_author)
    section_author = clean_placeholder(section_author)
    if not endpoint:
        return False
    if is_claim_id(endpoint):
        return False
    primary_author = section_author or source_author
    if primary_author and endpoint == primary_author:
        return True
    if endpoint in {"我", "我们", "吾", "余", "作者", "本文作者", "笔者"}:
        return True
    return endpoint in evidence


def strict_filter_extract_result(out: Dict[str, Any], segment_text: str) -> Dict[str, Any]:
    source_author = clean_placeholder(out["metadata"].get("source_author", ""))
    section_author = clean_placeholder(out["metadata"].get("section_author", ""))

    kept = []
    for item in out.get("entities", []):
        name = clean_placeholder(item.get("name", ""))
        ev = _s(item.get("evidence", "")).strip()
        if not name or not ev:
            continue
        if not evidence_supported(ev, segment_text):
            continue
        if name not in ev:
            continue
        kept.append(item)
    out["entities"] = kept

    kept = []
    for item in out.get("claims", []):
        ev = _s(item.get("evidence", "")).strip()
        claim = _s(item.get("claim", "")).strip()
        if not claim or not ev:
            continue
        if not evidence_supported(ev, segment_text):
            continue
        kept.append(item)
    out["claims"] = kept

    kept = []
    for item in out.get("relations", []):
        ev = _s(item.get("evidence", "")).strip()
        head = clean_placeholder(item.get("head", ""))
        tail = clean_placeholder(item.get("tail", ""))
        relation = clean_placeholder(item.get("relation", ""))
        if not relation or not ev or not head or not tail:
            continue
        if not evidence_supported(ev, segment_text):
            continue
        if not endpoint_supported(head, ev, source_author, section_author):
            continue
        if not endpoint_supported(tail, ev, source_author, section_author):
            continue
        kept.append(item)
    out["relations"] = kept

    kept = []
    for item in out.get("definitions", []):
        term = clean_placeholder(item.get("term", ""))
        definition = clean_placeholder(item.get("definition", ""))
        ev = _s(item.get("evidence", "")).strip()
        if not term or not definition or not ev:
            continue
        if not evidence_supported(ev, segment_text):
            continue
        if term not in ev:
            continue
        kept.append(item)
    out["definitions"] = kept

    kept = []
    for item in out.get("citations", []):
        quoted_claim = clean_placeholder(item.get("quoted_claim", ""))
        ev = _s(item.get("evidence", "")).strip()
        if not quoted_claim or not ev:
            continue
        if not evidence_supported(ev, segment_text):
            continue
        if quoted_claim not in ev:
            continue
        kept.append(item)
    out["citations"] = kept

    kept = []
    for item in out.get("rhetorical_devices", []):
        expression = clean_placeholder(item.get("expression", ""))
        ev = _s(item.get("evidence", "")).strip()
        if not expression or not ev:
            continue
        if not evidence_supported(ev, segment_text):
            continue
        if expression not in ev:
            continue
        kept.append(item)
    out["rhetorical_devices"] = kept

    kept = []
    for item in out.get("uncertainties", []):
        u = {"item": clean_placeholder(item.get("item", "")), "reason": clean_placeholder(item.get("reason", ""))}
        if u["item"] or u["reason"]:
            kept.append(u)
    out["uncertainties"] = kept

    return out


def renumber_extract_ids(out: Dict[str, Any]) -> Dict[str, Any]:
    prefixes = {"entities": "e", "claims": "c", "relations": "r", "definitions": "def", "citations": "cit", "rhetorical_devices": "rh"}
    for field, prefix in prefixes.items():
        for i, item in enumerate(out.get(field, []), 1):
            item["id"] = f"{prefix}{i}"
    return out


# ============================================================
# 12. 单段处理、失败检测、失败重跑
# ============================================================

def segment_paths(segment_id: str) -> Tuple[Path, Path]:
    raw_path = raw_dir / f"{segment_id}.txt"
    parsed_path = parsed_dir / f"{segment_id}.json"
    return raw_path, parsed_path


def is_success_result(obj: Dict[str, Any]) -> bool:
    if not isinstance(obj, dict):
        return False
    meta = obj.get("_meta", {})
    return (meta.get("status") == "success"
            and meta.get("model") == MODEL
            and meta.get("prompt_version") == PROMPT_VERSION
            and meta.get("schema_version") == SCHEMA_VERSION)


def is_success_parsed_file(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return is_success_result(obj)


def process_one_segment(seg: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    segment_id = seg["segment_id"]
    raw_path, parsed_path = segment_paths(segment_id)

    meta = {
        "article_id": seg["article_id"],
        "article_title": seg["article_title"],
        "source_author": seg.get("source_author", ""),
        "section_title": seg.get("section_title", ""),
        "section_author": seg.get("section_author", ""),
        "source_file": seg.get("source_file", ""),
        "segment_id": seg["segment_id"],
        "segment_index": seg["segment_index"],
    }

    if parsed_path.exists() and not force and not FORCE_RERUN_SUCCESS:
        try:
            old = json.loads(parsed_path.read_text(encoding="utf-8"))
            if is_success_result(old):
                return old
        except Exception:
            pass

    raw_text = ""
    started_at = datetime.now().isoformat(timespec="seconds")
    t0 = time.time()

    try:
        messages = make_extract_messages(seg)
        raw_text = call_llm(messages)
        atomic_write_text(raw_path, raw_text)

        parsed = parse_model_json(raw_text)
        out = normalize_extract_schema(parsed, meta)
        out = postprocess_discourse_roles(out, seg["text"])

        if STRICT_EVIDENCE_CHECK and DROP_UNSUPPORTED_EVIDENCE:
            out = strict_filter_extract_result(out, seg["text"])

        out = renumber_extract_ids(out)

        elapsed = round(time.time() - t0, 3)

        out["_meta"] = {
            "status": "success",
            "stage": "extract",
            "model": MODEL,
            "base_url": BASE_URL,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "segment_id": segment_id,
            "article_id": seg["article_id"],
            "char_start": seg["char_start"],
            "char_end": seg["char_end"],
            "raw_path": str(raw_path),
            "parsed_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": started_at,
            "elapsed_seconds": elapsed,
            "strict_evidence_check": STRICT_EVIDENCE_CHECK,
            "drop_unsupported_evidence": DROP_UNSUPPORTED_EVIDENCE,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        }

        atomic_write_json(parsed_path, out)

        log_event({
            "event": "segment_success",
            "segment_id": segment_id,
            "article_id": seg["article_id"],
            "elapsed_seconds": elapsed,
            "parsed_path": str(parsed_path),
        })

        return out

    except Exception as e:
        elapsed = round(time.time() - t0, 3)
        err_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 处理失败：stage=extract, segment={segment_id}, error={repr(e)}"
        print(err_msg)
        append_error_log(err_msg)
        append_error_log(traceback.format_exc())

        if raw_text:
            try:
                atomic_write_text(raw_path, raw_text)
            except Exception:
                pass

        failed = empty_extract_result(meta)
        failed["_meta"] = {
            "status": "failed",
            "stage": "extract",
            "model": MODEL,
            "base_url": BASE_URL,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "segment_id": segment_id,
            "article_id": seg["article_id"],
            "char_start": seg["char_start"],
            "char_end": seg["char_end"],
            "raw_path": str(raw_path),
            "parsed_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": started_at,
            "elapsed_seconds": elapsed,
            "error": repr(e),
            "traceback": traceback.format_exc(),
            "strict_evidence_check": STRICT_EVIDENCE_CHECK,
            "drop_unsupported_evidence": DROP_UNSUPPORTED_EVIDENCE,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        }

        atomic_write_json(parsed_path, failed)

        log_event({
            "event": "segment_failed",
            "segment_id": segment_id,
            "article_id": seg["article_id"],
            "elapsed_seconds": elapsed,
            "error": repr(e),
            "parsed_path": str(parsed_path),
        })

        return failed


def find_failed_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    failed = []
    for seg in segments:
        _, parsed_path = segment_paths(seg["segment_id"])
        if not is_success_parsed_file(parsed_path):
            failed.append(seg)
    return failed


def run_segments_once(segments_to_run: List[Dict[str, Any]], desc: str, force: bool = False) -> List[Dict[str, Any]]:
    results = []
    for seg in tqdm(segments_to_run, desc=desc):
        result = process_one_segment(seg, force=force)
        results.append(result)
        if REQUEST_SLEEP_SECONDS:
            time.sleep(REQUEST_SLEEP_SECONDS)
    return results


def run_extraction_with_failed_reruns(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    print(f"开始抽取，总段数：{len(segments)}")
    run_segments_once(segments, desc="extract-main", force=False)

    if RERUN_FAILED_AFTER_MAIN:
        for pass_idx in range(1, FAILED_RERUN_PASSES + 1):
            failed = find_failed_segments(segments)
            if not failed:
                print("没有失败段，跳过失败重跑。")
                break
            print(f"第 {pass_idx} 轮失败重跑，失败段数：{len(failed)}")
            run_segments_once(failed, desc=f"rerun-failed-pass-{pass_idx}", force=True)

    final_failed = find_failed_segments(segments)
    failed_report_path = logs_dir / "failed_segments.jsonl"
    if failed_report_path.exists():
        failed_report_path.unlink()
    for seg in final_failed:
        _, parsed_path = segment_paths(seg["segment_id"])
        err = ""
        if parsed_path.exists():
            try:
                obj = json.loads(parsed_path.read_text(encoding="utf-8"))
                err = obj.get("_meta", {}).get("error", "")
            except Exception as e:
                err = repr(e)
        append_jsonl(failed_report_path, {
            "segment_id": seg["segment_id"], "article_id": seg["article_id"],
            "article_title": seg["article_title"], "parsed_path": str(parsed_path), "error": err,
        })
    print(f"最终失败段数：{len(final_failed)}")
    print("失败段报告:", failed_report_path)

    all_results = []
    for seg in segments:
        _, parsed_path = segment_paths(seg["segment_id"])
        if parsed_path.exists():
            try:
                all_results.append(json.loads(parsed_path.read_text(encoding="utf-8")))
            except Exception:
                failed = empty_extract_result(seg)
                failed["_meta"] = {"status": "failed", "error": "parsed json cannot be loaded", "segment_id": seg["segment_id"]}
                all_results.append(failed)
        else:
            missing = empty_extract_result(seg)
            missing["_meta"] = {"status": "failed", "error": "parsed json missing", "segment_id": seg["segment_id"]}
            all_results.append(missing)
    return all_results


# ============================================================
# 13. 合并结果
# ============================================================

COMBINE_FIELDS = ["entities", "claims", "relations", "definitions", "citations", "rhetorical_devices", "uncertainties"]


def dedupe_items(items: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        k = tuple(_s(item.get(x, "")).strip() for x in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def combine_segment_outputs(results: List[Dict[str, Any]], segments: List[Dict[str, Any]], articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    seg_lookup = {seg["segment_id"]: seg for seg in segments}

    combined = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "project_name": PROJECT_NAME,
            "run_dir": str(run_dir),
            "combined_at": datetime.now().isoformat(timespec="seconds"),
            "article_count": len(articles),
            "segment_count": len(segments),
            "model": MODEL,
            "base_url": BASE_URL,
        },
        "counts": {},
        "articles": [
            {
                "article_id": a["article_id"],
                "article_title": a["article_title"],
                "source_author": a.get("source_author", ""),
                "source_file": a.get("source_file", ""),
                "article_index_in_file": a.get("article_index_in_file", 0),
                "text_length": len(a.get("text", "")),
            }
            for a in articles
        ],
        "entities": [], "claims": [], "relations": [], "definitions": [],
        "citations": [], "rhetorical_devices": [], "uncertainties": [],
    }

    for result in results:
        seg_meta = result.get("metadata", {})
        seg_id = seg_meta.get("segment_id", "")
        seg = seg_lookup.get(seg_id, {})

        for field in COMBINE_FIELDS:
            for local_idx, item in enumerate(result.get(field, []) or [], 1):
                item2 = dict(item)
                local_id = item2.get("id") or f"{field}_{local_idx}"
                item2["segment_id"] = seg_id
                item2["local_id"] = local_id
                item2["id"] = f"{seg_id}:{local_id}"
                item2["article_id"] = seg.get("article_id", seg_meta.get("article_id", ""))
                item2["article_title"] = seg.get("article_title", seg_meta.get("article_title", ""))
                item2["source_author"] = seg.get("source_author", seg_meta.get("source_author", ""))
                item2["source_file"] = seg.get("source_file", seg_meta.get("source_file", ""))
                combined[field].append(item2)

    combined["entities"] = dedupe_items(combined["entities"], ["article_id", "name", "type", "evidence"])
    combined["claims"] = dedupe_items(combined["claims"], ["article_id", "speaker", "claim", "evidence"])
    combined["relations"] = dedupe_items(combined["relations"], ["article_id", "head", "relation", "tail", "evidence"])
    combined["definitions"] = dedupe_items(combined["definitions"], ["article_id", "term", "definition", "evidence"])
    combined["citations"] = dedupe_items(combined["citations"], ["article_id", "quoted_author", "quoted_claim", "evidence"])
    combined["rhetorical_devices"] = dedupe_items(combined["rhetorical_devices"], ["article_id", "expression", "device_type", "evidence"])
    combined["uncertainties"] = dedupe_items(combined["uncertainties"], ["article_id", "item", "reason"])

    for field in COMBINE_FIELDS:
        combined["counts"][field] = len(combined[field])
    combined["counts"]["articles"] = len(combined["articles"])
    combined["counts"]["segments"] = len(segments)
    failed_count = sum(1 for r in results if not is_success_result(r))
    combined["counts"]["failed_segments"] = failed_count

    return combined


def save_combined_outputs(combined: Dict[str, Any]):
    combined_path = run_dir / "combined_extract.json"
    atomic_write_json(combined_path, combined)

    combined_jsonl_path = run_dir / "combined_extract_items.jsonl"
    if combined_jsonl_path.exists():
        combined_jsonl_path.unlink()
    with combined_jsonl_path.open("w", encoding="utf-8") as f:
        for field in COMBINE_FIELDS:
            for item in combined[field]:
                row = dict(item)
                row["_field"] = field
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("合并完成")
    print("combined_extract.json:", combined_path)
    print("combined_extract_items.jsonl:", combined_jsonl_path)
    print(json.dumps(combined["counts"], ensure_ascii=False, indent=2))


# ============================================================
# 14. 文章相似度与简单社区
# ============================================================

def compute_article_features(combined: Dict[str, Any]) -> Dict[str, set]:
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


def compute_article_similarity(combined: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = compute_article_features(combined)
    article_info = {a["article_id"]: a for a in combined.get("articles", [])}
    aids = list(features.keys())
    sims = []
    for i in range(len(aids)):
        for j in range(i + 1, len(aids)):
            a = aids[i]
            b = aids[j]
            fa = features[a]
            fb = features[b]
            union = fa | fb
            inter = fa & fb
            if not union:
                score = 0.0
            else:
                score = len(inter) / len(union)
            if score >= ARTICLE_SIMILARITY_MIN:
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


def save_article_similarity_and_communities(combined: Dict[str, Any]) -> List[Dict[str, Any]]:
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


# ============================================================
# 15. Neo4j CSV 导出
# ============================================================

def csv_value(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        return json.dumps(x, ensure_ascii=False)
    return str(x)


def write_csv_rows(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_value(row.get(k, "")) for k in fieldnames})


def make_node_id(prefix: str, key: str) -> str:
    return f"{prefix}_{stable_hash(key, 16)}"


def export_neo4j_csv(combined: Dict[str, Any], segments: List[Dict[str, Any]], article_sims: List[Dict[str, Any]]):
    nodes: Dict[str, Dict[str, Any]] = {}
    rels: List[Dict[str, Any]] = []

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
        aid_a = s.get("article_id_a", "")
        aid_b = s.get("article_id_b", "")
        node_a = article_node_ids.get(aid_a)
        node_b = article_node_ids.get(aid_b)
        if node_a and node_b:
            add_rel(node_a, node_b, "SIMILAR_TO", "JACCARD_SIMILARITY", polarity="neutral",
                    evidence=f"jaccard={s.get('jaccard', '')}; shared={s.get('shared_feature_count', '')}",
                    confidence=s.get("jaccard", ""), article_id="", segment_id="")

    node_rows = list(nodes.values())
    node_cols = ["node_id", "labels", "name", "node_type", "article_id", "segment_id", "title", "text"]
    rel_cols = ["source_id", "target_id", "type", "relation", "polarity", "evidence", "confidence", "article_id", "segment_id"]
    nodes_path = neo4j_dir / "nodes.csv"
    rels_path = neo4j_dir / "relationships.csv"
    write_csv_rows(nodes_path, node_rows, node_cols)
    write_csv_rows(rels_path, rels, rel_cols)

    guide = f"""// Neo4j 导入示例
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (n:KGNode {{id: row.node_id}})
SET n.labels = row.labels, n.name = row.name, n.node_type = row.node_type,
    n.article_id = row.article_id, n.segment_id = row.segment_id, n.title = row.title, n.text = row.text;

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS row
MATCH (s:KGNode {{id: row.source_id}})
MATCH (t:KGNode {{id: row.target_id}})
MERGE (s)-[r:KG_RELATION {{type: row.type, relation: row.relation, segment_id: row.segment_id, evidence: row.evidence}}]->(t)
SET r.polarity = row.polarity, r.confidence = row.confidence, r.article_id = row.article_id;
"""
    atomic_write_text(neo4j_dir / "neo4j_load_guide.cypher", guide.strip())
    print("Neo4j CSV 已输出:", nodes_path, rels_path)


# ============================================================
# 16. 主流程 + 后处理
# ============================================================

def write_source_info(combined, run_dir):
    """从 combined 中提取源文件信息，写入 TXT 方便识别作者"""
    articles = combined.get("articles", [])
    if not articles:
        return
    source_files = sorted(set(a.get("source_file", "") for a in articles if a.get("source_file")))
    authors = sorted(set(a.get("source_author", "") for a in articles if a.get("source_author")))
    titles = [(a.get("article_title", ""), a.get("source_author", ""), a.get("source_file", "")) for a in articles]
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
    for i, (title, author, sf) in enumerate(titles, 1):
        lines.append(f"  {i}. {title}  (作者={author}, 文件={sf})")
    info_path = run_dir / "source_info.txt"
    info_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"source_info.txt: {info_path}")


def main():
    # 1. 收集输入文件
    input_files = collect_input_txt_files()
    print("\n检测到输入文件：")
    for p in input_files:
        print(" -", p)

    # 根据 txt 文件名设定输出目录
    global run_dir, raw_dir, parsed_dir, logs_dir, neo4j_dir
    stems = []
    for f in input_files:
        s = f.stem
        if s not in stems:
            stems.append(s)
    run_name = "_".join(stems[:2]) if len(stems) <= 2 else f"{stems[0]}_等{len(stems)}篇"
    run_name = f"{run_name}_{PROMPT_VARIANT}"
    run_dir = Path(RUN_ROOT) / run_name
    raw_dir = run_dir / "raw_outputs" / "extract"
    parsed_dir = run_dir / "parsed_outputs" / "extract"
    logs_dir = run_dir / "logs"
    neo4j_dir = run_dir / "neo4j"
    for d in [raw_dir, parsed_dir, logs_dir, neo4j_dir]:
        d.mkdir(parents=True, exist_ok=True)
    print("输出目录:", run_dir)

    # 2. 解析文章
    articles: List[Dict[str, Any]] = []
    for p in input_files:
        file_articles = parse_articles_from_file(p)
        articles.extend(file_articles)

    if not articles:
        raise RuntimeError("没有解析出任何文章。请检查 txt 内容。")

    manifest_path = run_dir / "articles_manifest.jsonl"
    if manifest_path.exists():
        manifest_path.unlink()
    for a in articles:
        append_jsonl(manifest_path, {
            "article_id": a["article_id"], "article_title": a["article_title"],
            "source_author": a.get("source_author", ""), "source_file": a.get("source_file", ""),
            "article_index_in_file": a.get("article_index_in_file", 0), "text_length": len(a.get("text", "")),
        })
    print("\n解析出的文章：")
    for a in articles:
        print(f"- article_id={a['article_id']} | title={a['article_title']} | author={a.get('source_author', '') or '[空]'} | len={len(a.get('text', ''))}")
    print("articles_manifest:", manifest_path)

    # 3. 分段
    segments = build_segments_for_articles(articles)
    segments_path = run_dir / "segments.jsonl"
    if segments_path.exists():
        segments_path.unlink()
    for seg in segments:
        append_jsonl(segments_path, seg)
    seg_count = len(segments)
    print("\n分段数:", seg_count)
    print("segments.jsonl:", segments_path)
    est_min = round(seg_count * 0.2, 1)
    est_max = round(seg_count * 0.5, 1)
    print(f"预估抽取时间: {est_min}~{est_max} 分钟（按每段 12~30 秒估算）")

    # 4. 抽取，含失败自动重跑
    parsed_results = run_extraction_with_failed_reruns(segments)

    # 5. 合并
    combined = combine_segment_outputs(parsed_results, segments, articles)

    # ★ 后处理（本地导入 post_process.py）
    try:
        import importlib
        import post_process
        importlib.reload(post_process)
        combined = post_process.post_process_all(combined, segments)
        print("后处理完成")
    except ImportError as _e:
        print(f"警告：post_process.py 未找到 ({_e})，跳过")

    save_combined_outputs(combined)

    # 输出来源信息 TXT
    write_source_info(combined, run_dir)

    print("\n全部流程完成。")
    print("run_dir:", run_dir)


if __name__ == "__main__":
    main()
