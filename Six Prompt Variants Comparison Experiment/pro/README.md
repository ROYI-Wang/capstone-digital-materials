# Prompt Variants

Six prompt designs used in the Benchmarking comparison experiment (Chapter 5). All prompts are in Chinese as they operate on original Chinese historical texts.

## Variant Design Matrix

| Variant | Domain Knowledge | Constraint Level | Description |
|---------|-----------------|-----------------|-------------|
| **Sp-C** | Specialized (Science-Metaphysics Debate) | High | Domain-specific entity/relation types + strict formatting rules + self-check list |
| **Sp-F** | Specialized (Science-Metaphysics Debate) | Low | Domain-specific guidance but flexible output format |
| **Ge-C** | General (any Chinese debate) | High | Domain-agnostic entity/relation types + strict formatting rules + self-check list |
| **Ge-F** | General (any Chinese debate) | Low | Domain-agnostic guidance but flexible output format |
| **Do-C** | Specialized w/out examples | High | Same schema as Sp-C but without in-prompt example extracts |
| **Do-F** | Specialized w/out examples | Low | Same schema as Sp-F but without in-prompt example extracts |

### Abbreviations

- **Sp** = Specialized prompt (科玄论战专用 — tailored for the Science-Metaphysics Debate)
- **Ge** = General prompt (中文论战通用 — applicable to any Chinese intellectual debate)
- **Do** = Domain-specific without examples (same as Sp but omits example extractions)
- **C** = Constrained (高约束 — strict type whitelist, relation enumeration, formatting rules)
- **F** = Free (低约束 — loose guidance, flexible output)

All extracts were produced using **DeepSeek-V4-Flash** via **SiliconFlow API** (temperature=0.0). See the main thesis Chapter 5 for detailed analysis of variant performance.
