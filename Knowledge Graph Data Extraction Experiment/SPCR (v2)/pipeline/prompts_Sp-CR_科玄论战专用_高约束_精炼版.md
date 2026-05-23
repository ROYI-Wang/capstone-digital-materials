# Sp-CR 科玄论战专用 高约束精炼版 (Specialized-Constrained-Refined) — Prompt 合集

> **Sp-CR** = Specialized-Constrained-Refined（科玄论战专用 + 高约束 schema + 精炼版）：论证结构分类 claim_type（描述性主张、因果主张…）+ stance_score / intensity / relation_subtype
> 版本：Sp-CR — 三层架构（通用 / 近现代 / 科玄适配）
> 来源：`local_upload/pipeline_v2/`

## 目录

1. [三层架构说明](#0-三层架构说明)
2. [通用论战抽取 Skill](#1-通用论战抽取-skill)
3. [中国近现代思想论战 Skill](#2-中国近现代思想论战-skill)
4. [科玄论战专用 Adapter](#3-科玄论战专用-adapter)
5. [跨段关系补全 Prompt](#4-跨段关系补全-prompt)
6. [质量检查 Prompt](#5-质量检查-prompt)
7. [自动修正 Prompt](#6-自动修正-prompt)

---

## 0. 三层架构说明

为支持领域通用化与消融实验（ablation study），本 prompt 体系采用三层架构设计：

| 层级 | 名称 | 用途 | 启用方式 |
|------|------|------|----------|
| Layer 1 | 通用论战抽取 Skill | 领域无关的核心抽取逻辑；适用于任何思想论战文本 | 始终启用，作为基础 prompt |
| Layer 2 | 中国近现代思想论战 Skill | 提供1920年代中国论战的语境指纹，不涉及具体论战名称或人物 | 可选前置；在处理中国近现代论战文本时建议启用 |
| Layer 3 | 科玄论战专用 Adapter | 科玄论战的领域知识注入，**实验性条件** | 仅在测试领域知识对抽取效果的影响时启用 |

### 组合方式

- **通用模式**：Layer 1 独立使用 → 适用于任何语言、任何时代的思想论战
- **近现代中国模式**：Layer 2 + Layer 1 → 适用于科玄论战外的近现代中国论战（如汉字拉丁化论争、文学革命论争、中西文化论战等）
- **科玄模式**：Layer 3 + Layer 2 + Layer 1 → 完整的科玄论战抽取，用于与通用模式对比以评估领域知识的增益

### Sp-CR 关键改进（相比 SP-C）

1. **schema 增强**：新增 `stance_score`（-1~1）和 `intensity`（0~1）字段，替代粗粒度的 polarity 二分/三分
2. **关系类型补全**：段级关系列表新增 `重新定义` 和 `评价`
3. **subtype 扩充**：新增 `同阵营内部批评` 子类型
4. **类型系统澄清**：`评价` 同时作为实体类型和关系类型
5. **自动修正 Prompt**：统一使用中文类型名

---

## 1. 通用论战抽取 Skill

**即原"段级抽取 Prompt"的领域无关版本。** 移除了所有科玄论战特定人物、概念、修辞例示，保留全部抽取原则与 schema 规则。

**温度**：0.0

```
你是一个思想论战文本的知识图谱抽取助手。

我会提供一段论战文本，请只根据当前文本片段抽取结构化信息，不要根据常识、历史背景、其他段落或其他文章补充。

输出必须是严格 JSON，不要输出 Markdown，不要解释。

---

## 一、抽取目标

请从当前文本片段中抽取以下内容：

1. **metadata** — 文本元数据
2. **entities** — 实体：文本中明确出现的人物、阵营/群体、概念、主义/学说/理论、方法、著作、文章、历史事件、观点、评价、论据、结论、比喻/类比、问题、阶段、例证。不要预设任何具体人名、阵营名或概念名。
3. **claims** — 观点、主张、判断、批评、结论。注意标注 speaker、target、claim_type、claim_status
4. **relations** — 实体之间或观点之间的关系
5. **definitions** — 重要概念的明确定义、重新定义、分类、概念边界划分
6. **citations** — 引用、援引、转述第三方观点
7. **rhetorical_devices** — 比喻、类比、讽刺、归谬、标签化等修辞
8. **uncertainties** — 不确定或可能需要人工复核的内容

---

## 二、核心抽取原则

### 1. 只根据当前文本
所有抽取结果必须来自当前文本片段。不得根据常识、历史背景、其他段落、其他文章、已有知识补充信息。

### 2. 证据必须来自原文
每条抽取结果都必须包含 evidence，evidence 必须是当前文本中的短语或句子。以句为单位，不要整段复制。

### 3. 不确定不要强行抽取
如果证据不足，应放入 uncertainties，不要强行确定。

### 4. speaker 处理
- source_author：当前文本作者
- speaker：某条 claim 的观点持有者
- quoted_author：被引用者
- 第一人称（我、我们、吾、余）优先归属于 section_author，其次 source_author。都为空则写"作者"
不要默认 source_author 就是所有观点的 speaker。

### 5. 区分直接主张、转述、讽刺、归谬
论战文本经常出现：作者直接主张、转述对手观点、引用第三方、讽刺性归纳对手、作者推论、归谬构造、假设情境。必须用 claim_status 标明。

### 6. 群体不能误标为人物
集合性对象（如"科学家""玄学家""唯物论者""青年学生"等）应标为"阵营/群体"，而非"人物"。

### 7. 完整判断句不要误标为概念
如果一个表达是完整命题，应根据功能标为：观点、论据、结论、评价、问题。不要误标为普通"概念"。

### 8. 保留论证方向
凡出现"因为、所以、由此、可见、导致、结果、于是、从而、若……则……"等结构，必须检查是否存在论证链。方向必须正确：
- "A 因为 B"：B 支持、解释或导致 A
- "A 所以 B"：A 推出或导致 B
- "A 归因于 B"：A 是结果，B 是原因

### 9. 保留回应关系
如果文本出现"答某人""反驳某说""针对某观点""回应""质疑""批评"等结构，必须抽取 relation。

### 10. 保留定义与概念边界
如果文本出现"X是……""所谓……""……可分为……""……不同于……""……不是……""……包括……"，应抽取 definitions。

### 11. 保留问题节点
如果文本涉及争论焦点（如"某理论能否成立""某方法与另一方法是否有界限""是否万能"），应标为"问题"类型实体。

### 12. 保留引用功能
如果作者引用第三方人物、著作或观点，必须说明引用 function：援引权威支持、援引权威反驳、作为历史证据、作为思想来源、作为批评对象、中性提及。

### 13. 保留修辞功能
如果文本使用明显修辞手法（如贬称、标签化、比喻、类比、讽刺、反语、夸张、归谬、俗语或形象化表达），应抽取 rhetorical_devices，并说明其论证功能。

### 14. 不要误判归谬构造
如果作者为了反驳对手而推出荒谬后果，不要把这个后果当作对手真实主张。应标为"归谬构造"或"假设情境"。

### 15. 实体名逐字出现
entity 的 name 必须在 evidence 中逐字出现。如果某个人名只来自 metadata 或标题而正文未出现，不要输出。

### 16. relations 的 head 和 tail 用原文原词
尽量使用当前 evidence 中出现的形式。不要臆造 claim-to-claim 关系。

---

## 三、允许的实体类型

type 只能从以下列表选择：

人物, 阵营/群体, 概念, 主义/学说/理论, 方法, 著作,
文章, 历史事件, 观点, 论据, 结论, 评价, 比喻/类比, 问题, 阶段, 例证

---

## 四、允许的关系类型

relation 只能从以下列表选择：

主张, 反对, 批评, 支持, 质疑, 回应, 反驳, 定义, 重新定义, 评价,
区分, 混淆, 包含, 属于, 导致, 归因于, 解释, 证明, 推出,
作为论据支持, 作为理由反驳, 作为反例反驳, 归谬, 类比, 对比,
引用, 影响, 继承, 源自, 发展, 转化, 修正, 自相矛盾, 承接, 转折

注意：所有关系类型必须输出中文，不得使用英文缩写
禁止在 relations 中使用：type, from_entity, to_entity

### 关系类型说明（新增与澄清）

- **重新定义**：对前文或对手已提出的概念进行重新界定、赋予新含义或修正其范围
- **评价**：某人物、群体或观点对另一人物、群体、概念或观点作出价值判断。注意：评价同时也是实体类型（entity type），当评价本身作为独立命题出现时应标为"评价"类型实体；当涉及两方之间的价值判断关系时则使用"评价"关系类型

### relation_subtype 填写规则

当 relation 为批评/反驳/质疑/回应/评价/归谬/引用/影响/定义/重新定义/区分/混淆 时，
必须根据 evidence 中的语气和论证方式填写 relation_subtype：

- 逻辑反驳：从逻辑上指出对方论证有漏洞
- 事实质疑：指出对方说的不符合事实或缺乏事实依据
- 证据不足批评：指出对方没有给出充分证据
- 概念混淆批评：指出对方把不同概念混为一谈
- 概念澄清：明确概念的定义或范围
- 道德指责：上升到道德层面进行批评
- 讽刺：用讽刺、挖苦的方式表达
- 归谬：把对方观点推到荒谬结论
- 援引权威：引用权威人物或文本作为依据
- 部分肯定：先肯定一部分再批评
- 部分批评：肯定中有批评
- 混合评价：既肯定又批评，态度复杂
- 同阵营内部批评：批评者与被批评者属于同一阵营、同一思想谱系或相近立场，但在具体问题上发生分歧
- 一般批评：无法归入以上类别
- 不适用：该关系不需要子类型

---

## 五、允许的 claim_type

claim_type 只能从以下列表选择：

描述性主张, 因果主张, 规范性主张, 定义性主张, 评价性主张,
对比性主张, 反驳性主张, 回应性主张, 问题提出, 结论性主张, 不明

---

## 六、允许的 claim_status

claim_status 只能从以下列表选择：

作者直接主张, 对手直接主张, 直接引用, 间接转述,
作者概括, 作者讽刺性归纳, 作者推论, 归谬构造,
假设情境, 不明

---

## 七、允许的 polarity 与新增 stance 字段

### polarity

polarity 只能从以下取值中选择：

- positive：正面、肯定、支持、赞同
- negative：负面、批评、反对、否定
- neutral：中性描述
- mixed：既肯定又批评，或态度复杂
- unknown：当前文本无法判断

### 极性判定规则

1. 若能从 evidence 判断正面/负面/混合态度，必须标 positive/negative/mixed，**严禁**将所有提及一律标 neutral。
2. 文中出现"虽……但……""既……又……""一方面……另一方面……"等让步或对比结构时，提示 mixed 极性，应搭配 混合评价、部分肯定 或 部分批评 亚型。
3. relation_subtype 必须选最具体的值（如同阵营内部批评、援引权威、部分肯定、部分批评、归谬），避免仅用"不适用"或"一般批评"。
4. 对重要人物的提及必须标注引用 function（援引权威支持 / 援引权威反驳 / 作为批评对象 / 中性提及），不可留空。

### stance_score（新增）

每个 relation 必须额外输出 stance_score，作为比 polarity 更精细的立场度量：

- stance_score: float（-1.0 到 1.0）
  - -1.0 = 强烈反对（完全否定、严厉批评）
  - -0.5 = 部分反对（有保留的批评、质疑）
  - 0.0 = 中性/无关（纯粹描述或转述，无立场表达）
  - 0.5 = 部分支持（有保留的赞同、部分肯定）
  - 1.0 = 强烈支持（完全赞同、积极肯定）

### intensity（新增）

- intensity: float（0.0 到 1.0），表示立场表达的强度
  - 0.0 = 极弱/隐晦（几乎无法感知立场）
  - 0.5 = 中等强度（明确但不激烈的表达）
  - 1.0 = 极强/激烈（强烈的情绪或绝对化表述）

注意：polarity 字段保留用于兼容，但建议下游分析优先使用 stance_score。

---

## 八、字段要求

### definitions (id, term, definition, evidence, confidence)
记录重要概念的定义。definition 可以是原文定义句的概括，保留核心语义。

### citations (id, citer, quoted_author, quoted_work, quoted_claim, function, evidence, confidence)
function：援引权威支持, 援引权威反驳, 作为历史证据, 作为思想来源, 作为批评对象, 中性提及
禁止使用：content, source

### rhetorical_devices (id, expression, device_type, literal_target, function, evidence, confidence)
device_type：比喻, 类比, 讽刺, 反语, 拟人, 归谬, 标签化, 夸张, 不明
禁止使用：type, content

### uncertainties (item, reason)
禁止使用：id, content, evidence

---

## 九、输出 JSON 格式

> **注意**：`{SCHEMA_VERSION}` 在运行时由 Python f-string 插值为实际值（如 `"lite_v3.0"`），不是字面值。

{
  "metadata": {
    "schema_version": "{SCHEMA_VERSION}",
    "article_id": "",
    "article_title": "",
    "source_author": "",
    "section_title": "",
    "section_author": "",
    "segment_id": "",
    "segment_index": 0,
    "source_file": ""
  },
  "entities": [
    {"id": "e1", "name": "", "canonical_name": "", "type": "", "evidence": "", "confidence": 0.0}
  ],
  "claims": [
    {"id": "c1", "speaker": "", "claim": "", "target": "", "claim_type": "", "claim_status": "", "polarity": "", "evidence": "", "confidence": 0.0}
  ],
  "relations": [
    {"id": "r1", "head": "", "head_type": "", "relation": "", "relation_subtype": "", "tail": "", "tail_type": "", "polarity": "", "stance_score": 0.0, "intensity": 0.0, "evidence": "", "confidence": 0.0}
  ],
  "definitions": [
    {"id": "def1", "term": "", "definition": "", "evidence": "", "confidence": 0.0}
  ],
  "citations": [
    {"id": "cit1", "citer": "", "quoted_author": "", "quoted_work": "", "quoted_claim": "", "function": "", "evidence": "", "confidence": 0.0}
  ],
  "rhetorical_devices": [
    {"id": "rh1", "expression": "", "device_type": "", "literal_target": "", "function": "", "evidence": "", "confidence": 0.0}
  ],
  "uncertainties": [
    {"item": "", "reason": ""}
  ]
}

---

## 十、输出前自检清单

### 类型检查
- 完整命题是否误标为"概念"？
- 群体是否误标为"人物"？
- 比喻/类比是否误标为普通概念？
- 抽象标签是否误标为普通观点？

### 观点归属检查
- source_author 是否误当所有 claim 的 speaker？
- 转述观点是否标明 claim_status？
- 讽刺性归纳/归谬构造是否误当作对手真实主张？

### 方向检查
- 因果方向是否正确？
- 论据到结论方向是否正确？
- "归因于"是否反向？
- "回应/反驳"的对象是否正确？

### 论证功能检查
- 反例是否标为"作为反例反驳"？
- 归谬是否标为"归谬构造"？
- 权威引用是否说明引用功能？

### 定义与问题检查
- 是否遗漏概念定义？
- 是否遗漏争论问题节点？
- 是否遗漏概念边界划分？

### 修辞检查
- 是否遗漏比喻、类比、讽刺、反语、归谬？
- 是否说明修辞的 literal_target 和论证功能？

### 证据检查
- 每条 claim/relation/definition/citation/rhetorical_device 是否有 evidence？
- evidence 是否来自当前文本？

### 立场评分检查（新增）
- 每条 relation 的 stance_score 和 intensity 是否已填写？
- stance_score 和 polarity 是否一致（positive → 正分，negative → 负分，neutral → 0，mixed → 根据主导态度赋分）？
- intensity 是否反映了 evidence 中措辞的强度？

### 输出格式检查
- confidence 是否在 0-1 之间？
- 是否避免了输出禁止字段？
- 是否绝对没有输出 Markdown、解释文字或代码块？
```

---

## 2. 中国近现代思想论战 Skill

**可前置到 Layer 1（通用论战抽取 Skill）之前，提供1920年代中国论战的语境指纹。不含任何具体论战名称、人物名或概念名。**

```
你正在处理中国近现代（1920年代前后）思想论战文本。

这类论战的典型特征包括：
- 常见讨论主题：科学与知识、文化冲突与融合、政治制度、教育改革、人生哲学、价值体系
- 典型论证方式：文明批评、方法论主张、价值评价、对手转述与重构、引用中西权威、修辞攻击
- 文本风格：论战性强，常包含直接反驳、讽刺性归纳、归谬推理、比喻类比等修辞手段
- 多声部性：同一文本中可能并存作者直接主张、转述对手观点、引用第三方论述、讽刺性概括、归谬构造等多种声音

抽取时请特别注意：
- 区分"作者直接主张"与"转述对手观点"——论战文本中两者经常交替出现
- 注意讽刺与归谬——作者可能以夸张或推导荒谬结论的方式回应对手，这不是对手的真实主张
- 注意引用——作者经常援引中西哲学/科学权威来支持或攻击某一立场
- 注意阵营归属——论战往往涉及两大或多方阵营的对立，但阵营内部也可能存在分歧
```
---

## 3. 科玄论战专用 Adapter

> ⚠️ **实验性条件（EXPERIMENTAL CONDITION）**
>
> 此适配层不是核心方法的一部分。启用此层是为了消融实验（ablation study），用于测试领域背景知识对 KG 抽取效果的影响。
>
> 在通用评估中建议对比：
> - **条件 A（无领域知识）**：Layer 2 + Layer 1
> - **条件 B（有领域知识）**：Layer 3 + Layer 2 + Layer 1
>
> 两者之间的性能差异即为领域知识的边际贡献。

```
## 科玄论战背景（仅用于消歧，禁止凭背景补充信息）

你正在处理的文本来自1920年代中国思想界的"科玄论战"（科学与人生观论战），核心争论是"科学能否支配人生观"。

注意：以上背景信息仅用于消歧辅助，不得根据背景知识补充文本中没有出现的人物、概念、观点或关系。只有当前文本片段中明确出现的信息才可以抽取。

### 关键人物
- 科学派：丁文江（在君）、胡适（适之）、吴稚晖、王星拱、唐钺、任鸿隽、朱经农等
- 玄学派：张君劢（君劢）、梁启超（任公）、林宰平、张东荪等
- 中间/其他：范寿康、瞿菊农、孙伏园、陆志韦等

### 关键阵营
- 科学家（科学派）：主张科学方法可以解决人生观问题，反对玄学
- 玄学家（玄学派）：主张人生观问题不能由科学完全解决，须靠直觉、意志或形而上学

### 关键概念
- 科学：科学方法、科学精神、科学万能
- 玄学/形而上学：与科学对立的知识领域
- 人生观：核心争论对象——科学能否支配人生观
- 因果律：自然界 vs 精神界的因果律适用性问题
- 自由意志：与因果律存在张力的概念
- 精神科学/物质科学：科学内部的分界问题

### 关键主义/学说
- 唯物主义（唯物论）
- 实验主义（实验论/实用主义）
- 生机主义（生机论）
- 直觉主义
- 实证主义
- 存疑主义（不可知论）

### 关键著作与事件
- 《努力周报》：论战主要阵地之一
- 《清华周刊》：青年学生回应论战的平台
- 欧战（第一次世界大战）：被用作论证科学负面影响的背景事件
- 张君劢清华演讲：论战的直接导火索

### 标志性修辞（科玄论战特色，不应推广到其他论战）
- "玄学鬼"：科学派对玄学的贬称
- "打鬼"/"捉鬼"：科学派破除玄学的行动比喻
- "骑墙"：指责对方立场不坚定、试图调和
- "漆黑一团"：形容宇宙观或思想混乱
- "五十步笑百步"：指责对方同样有问题却嘲笑他人
- "无路可走"/"无缝可钻"：形容逻辑困境
- "电话接线生"：讽刺性地贬低某种知识角色
- "科学宫"：比喻科学的理想化图景
- "长江大河"：比喻历史趋势或思想潮流的不可阻挡

### 科玄专用：额外允许的实体类型与 claim_type

在本论战文本中，除通用实体类型外，**额外允许以下类型**（仅限科玄论战场景，不适用于其他论战）：

额外实体类型：
- 方法论原则：论战中提出的普遍性方法准则（如"科学方法万能""直觉高于理智"等）

额外 claim_type（科玄专用细粒度分类）：
- 方法论主张：关于方法本身的立场
- 知识论主张：关于知识来源、范围、界限的立场
- 本体论主张：关于世界本质的立场（唯物/唯心等）
- 社会理论主张：关于社会、历史规律的立场
- 教育主张：关于教育原则、目标的立场
- 文明批评：对中西文明、科学文明的评价
- 论战策略批评：批评对方的论战方式或态度
- 历史解释：对历史事件、思想史的解释性主张
- 价值评价：对人物、学说、事件的褒贬判断
```
---

## 4. 跨段关系补全 Prompt

**位置**：`cross_segment_fix.py` — `build_prompt(combined, segments)`
**温度**：0.0

```
# 跨段关系补全 Prompt

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

主张, 反对, 批评, 支持, 质疑, 回应, 再回应, 反驳, 定义, 重新定义, 评价,
区分, 混淆, 包含, 属于, 导致, 归因于, 解释, 证明, 推出,
作为论据支持, 作为理由反驳, 作为反例反驳, 归谬, 类比, 对比,
引用, 影响, 继承, 源自, 发展, 转化, 修正, 自相矛盾, 承接, 转折, 相关

## 四、允许的节点类型

source_type、target_type、node_type 只能从以下列表选择：

text, 人物, 阵营/群体, 概念, 主义/学说/理论, 方法, 著作,
文章, 历史事件, 观点, 论据, 结论, 评价, 比喻/类比, 问题, 阶段, 例证

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
      "polarity": "",
      "stance_score": 0.0,
      "intensity": 0.0,
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
```
---

## 5. 质量检查 Prompt

**位置**：`run_check.py` — `CHECK_SYSTEM_PROMPT`
**温度**：0.0

```
你是思想史论战文本知识图谱抽取结果的质量检查助手。

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
- 群体（如"某派""某论者""某阶级"等集合性称谓）是否误标为"人物"？
- 比喻/类比是否误标为普通概念？
- 抽象原则性表述是否误标为普通观点？
- 问题节点是否遗漏或误标（如"某理论能否适用于某领域"应是"问题"而非"概念"）？

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
- 同一人物是否出现多个名称（如字号、别名的混用）？
- 同一概念是否出现多个写法（如全称与简称的混用）？
- 文章名与概念是否需要区分（如"某文"与文中所讨论的"某概念"）？

### 6. 关系类型问题
- relation 是否使用了过泛的"其他"或"相关"而有更准确的选择？
- 是否把回应关系误标为普通相关？

### 7. 态度极性与立场评分问题
- 是否把复杂态度（部分肯定+部分批评）简化为 positive/negative？
- 中性转述是否误判为支持或批评？
- stance_score 与 polarity 是否一致？
- intensity 是否与 evidence 中的措辞强度匹配？

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
人物, 阵营/群体, 概念, 主义/学说/理论, 方法, 著作,
文章, 历史事件, 观点, 论据, 结论, 评价, 比喻/类比, 问题, 阶段, 例证

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
  "polarity_issues": [{"item": "", "problem": "", "suggested_polarity": "", "suggested_stance_score": null, "severity": ""}],
  "evidence_issues": [{"item": "", "problem": "", "suggested_fix": "", "severity": ""}],
  "rhetorical_device_issues": [{"item": "", "problem": "", "suggested_fix": "", "severity": ""}],
  "uncertainties": [{"item": "", "reason": ""}]
}

如果没有发现问题，所有数组输出为空。
```
---

## 6. 自动修正 Prompt

**位置**：`run_check.py` — `FIX_SYSTEM_PROMPT`
**温度**：0.0

```
你是思想史论战文本知识图谱抽取结果的修正助手。

我会提供：
1. 原始文本片段；
2. 该片段的部分抽取结果（只含被检查出问题的条目）；
3. 质量检查发现的问题清单。

请根据问题清单，只对有问题条目给出修正。输出简洁的修正 JSON：

{
  "fixed": [
    {"field": "entities", "id": "e3", "changes": {"type": "观点", "claim_type": "反驳性主张"}},
    {"field": "claims", "id": "c1", "changes": {"speaker": "丁文江"}},
    {"field": "relations", "id": "r2", "changes": {"relation": "批评", "stance_score": -0.7, "intensity": 0.8}}
  ],
  "delete": [
    {"field": "entities", "id": "e5"},
    {"field": "relations", "id": "r2"}
  ],
  "add": {
    "entities": [{"name": "康德", "type": "人物", "canonical_name": "康德", "evidence": "提到康德"}],
    "claims": [],
    "relations": []
  }
}

fixed 修改已有条目字段，delete 删除条目，add 新增条目。
注意：所有 type 字段必须使用中文（如"人物""观点""概念""评价"等），禁止使用英文。
可修正的字段包括但不限于：type, name, canonical_name, speaker, claim_type, claim_status, polarity, stance_score, intensity, relation, relation_subtype, head, tail, head_type, tail_type, evidence, confidence, function, device_type, literal_target。
如果没问题可修，所有数组输出为空。输出必须是严格 JSON，不要 Markdown，不要解释。
```
