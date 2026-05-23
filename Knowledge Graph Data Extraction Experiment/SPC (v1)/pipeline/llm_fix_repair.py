import json, os, sys, argparse
from pathlib import Path
from openai import OpenAI

parser = argparse.ArgumentParser(description="LLM 修复 knowledge graph extraction JSON")
parser.add_argument("input_file", help="Path to combined_extract.json or similar to repair")
parser.add_argument("-o", "--output", default=None, help="Output file path (default: <input>_fixed.json)")
args = parser.parse_args()

API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
if not API_KEY:
    api_file = Path(__file__).parent.parent / "API.txt"
    if api_file.exists():
        API_KEY = api_file.read_text(encoding="utf-8").strip().split("\n")[0].strip()

client = OpenAI(api_key=API_KEY, base_url="https://api.siliconflow.cn/v1")
MODEL = "deepseek-ai/DeepSeek-V4-Flash"

with open(args.input_file, "r", encoding="utf-8") as f:
    old_data = json.load(f)

prompt = f"""你是一个知识图谱数据修复专家。请修复以下 combined_extract.json 数据，严格按照下面的规则操作。

规则：
1. entity type 规范（中文→英文）：
   - 观点/Viewpoint → Concept
   - 派别/Faction → School  
   - 问题/Question → Concept
   - 其他/Other → Concept
   - 方法/Method → Method (保留)
   - 如果 entity type = "Claim"，将该实体从 entities 数组移到 claims 数组（按 claims 格式转换：fields: id, content, confidence, evidence, segment_id, local_id, article_id, source_author）
   - 所有 entity type 必须来自: Person, Work, Organization, Location, Event, Theory, Principle, Argument, Method, Concept, Date, Law, School, Discipline, Stage

2. relation type 规范（中文→英文）：
   - 包含 → CONTAINS
   - 批判 → CRITICIZES
   - 作为论据支持 → EVIDENCE_FOR
   - 支持 → SUPPORTS
   - 作为例证 → EVIDENCE_FOR (与作为论据支持合并)
   - 接触 → CONTACT
   - 区分 → DISTINGUISHES
   - 依赖 → DEPENDS_ON
   - 受益于 → BENEFITS_FROM
   - 涉及 → RELATED_TO
   - 对立 → OPPOSES
   - 基础 → FOUNDATION
   - 反对 → OPPOSES
   - 其他中文类型请自行推断对应英文

3. 所有 relation 必须填写 relation_subtype 字段（基于 evidence 文本推断）：
   可取值：直接影响, 间接影响, 因果关系, 包含关系, 部分整体, 相似关系, 对比关系, 先后顺序, 同步关系, 条件关系, 目的关系, 方式方法, 理论依据, 事实依据, 数据支撑, 逻辑推导, 归纳总结, 演绎推理, 假设推测, 定义解释, 分类列举, 举例说明, 引用权威, 历史溯源, 跨文化比较, 实证验证
   如果无法推断，用 "事实依据"

4. 删除所有 tail 为空的 relation

5. 确保每个 relation 的 head 和 tail 字段非空

6. 保持其他字段不变（id, head_type, tail_type, polarity, evidence, confidence 等）

7. 返回完整的修复后的 JSON（不要省略任何字段）

原始数据：
{json.dumps(old_data, ensure_ascii=False, indent=2)}"""

print("Sending to LLM for repair...")
resp = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": prompt}],
    temperature=0.1,
    max_tokens=32000
)

reply = resp.choices[0].message.content
# extract JSON from response
import re
m = re.search(r'```(?:json)?\s*([\s\S]*?)```', reply)
if m:
    json_str = m.group(1)
else:
    json_str = reply.strip()
    # try to find first { and last }
    start = json_str.find('{')
    end = json_str.rfind('}')
    if start >= 0 and end > start:
        json_str = json_str[start:end+1]

fixed = json.loads(json_str)
output_path = args.output or args.input_file.replace(".json", "_fixed.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(fixed, f, ensure_ascii=False, indent=2)

# stats
print(f"entities: {len(fixed.get('entities',[]))}")
print(f"relations: {len(fixed.get('relations',[]))}")
print(f"claims: {len(fixed.get('claims',[]))}")
from collections import Counter
et = Counter(e.get('type','') for e in fixed.get('entities',[]))
print(f"entity types: {dict(et)}")
rt = Counter(r.get('relation','') for r in fixed.get('relations',[]))
print(f"relation types: {dict(rt)}")
cn = sum(1 for r in fixed.get('relations',[]) if any(ord(c)>127 for c in (r.get('relation','') or '')))
print(f"Chinese relations remaining: {cn}")
st_missing = sum(1 for r in fixed.get('relations',[]) if not r.get('relation_subtype'))
print(f"missing relation_subtype: {st_missing}")
empty_tail = sum(1 for r in fixed.get('relations',[]) if not r.get('tail'))
print(f"empty tail: {empty_tail}")
claim_ents = sum(1 for e in fixed.get('entities',[]) if e.get('type')=='Claim')
print(f"entity=Claim: {claim_ents}")
print("Saved to llm_fixed.json")
