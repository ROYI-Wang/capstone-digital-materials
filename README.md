# Capstone Digital Materials

Digital materials accompanying the capstone project **"Knowledge Graph Construction of the Science-Metaphysics Debate Based on Large Language Models"** (DHG601, MA in Digital History in Global Asia, Lingnan University).

All knowledge graph extraction was conducted using **DeepSeek-V4-Flash** via the **SiliconFlow API** (temperature=0.0). The Neo4j graph database import and downstream graph algorithm analysis (community detection, centrality calculation, etc.) have not yet been performed and remain for future work.

## Repository Structure

```
├── Original Materials/
│   ├── Original PDFs/            # Scanned source PDFs of the Science-Metaphysics Debate
│   └── Modified Articles/        # Cleaned and segmented .txt articles of 22 authors
│
├── Knowledge Graph Data Extraction Experiment/
│   ├── SPC (v1)/                 # Full-text KG extraction (Specialized Prompt, Constrained, v1)
│   │   ├── input_texts/          # Input text segments
│   │   ├── kg_runs/              # Extraction results (JSON)
│   │   ├── pipeline/             # Extraction pipeline scripts
│   │   └── 对比SPC和AI的抽取（ai提取）/  # Comparison between human and AI extraction
│   └── SPCR (v2)/                # Full-text KG extraction (Specialized Prompt, Constrained, Refined, v2)
│       ├── input_texts/
│       ├── kg_runs/
│       └── pipeline/
│
└── Six Prompt Variants Comparison Experiment/
    ├── pip/                      # Pipeline scripts and dependencies
    │   ├── prompt_variants/      # 6 prompt variants in .txt format (pipeline-ready)
    │   ├── README.txt            # Usage instructions (Chinese)
    │   ├── requirements.txt      # Python dependencies
    │   └── *.py                  # Pipeline scripts (workflow, post-processing, analysis)
    ├── pro/                      # 6 prompt designs in .md format (human-readable)
    │   ├── Sp-C / Sp-F           # Domain-specific (Science-Metaphysics), high/low constraint
    │   ├── Ge-C / Ge-F           # General debate, high/low constraint
    │   └── Do-C / Do-F           # Domain-specific w/out example, high/low constraint
    └── kgrun/                    # Per-author KG extraction results across all 6 variants
```

## How to Reproduce

See `Six Prompt Variants Comparison Experiment/pip/README.txt` for detailed setup and usage instructions.

### Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r "Six Prompt Variants Comparison Experiment/pip/requirements.txt"
   ```

2. **Set API key:**
   ```bash
   set SILICONFLOW_API_KEY=sk-your-key
   ```

3. **Run extraction pipeline** (in order):
   ```bash
   cd "Six Prompt Variants Comparison Experiment/pip"
   python workflow_complete.py       # Core KG extraction (most time-consuming)
   python fix_combined_json.py        # Clean JSON output
   python cross_segment_fix.py        # Cross-segment relation completion (requires API)
   python run_check.py                # Quality check + Neo4j CSV export
   python analyze_centrality.py       # Centrality analysis (optional)
   ```

## Output Formats

- **Extraction results:** JSON (entity-relation triplets with evidence anchoring to source text)
- **Graph data:** CSV (nodes and edges, compatible with Neo4j import)
- **Statistics:** JSON (per-author and cross-variant comparison metrics)

## Technical Requirements

- **Model:** DeepSeek-V4-Flash (via SiliconFlow API)
- **Python:** 3.8+
- **Neo4j:** 5.x (for graph analysis — not yet performed)
- **API:** SiliconFlow (or compatible OpenAI endpoint)

## License

This project is submitted in partial fulfillment of the requirements for the Master of Arts in Digital History in Global Asia at Lingnan University.
