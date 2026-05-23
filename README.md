# Capstone Digital Materials

Digital materials accompanying the capstone project **"Knowledge Graph Construction of the Science-Metaphysics Debate Based on Large Language Models"** (DHG601, MA in Digital History in Global Asia, Lingnan University).

All knowledge graph extraction was conducted using **DeepSeek-V4-Flash** via the **SiliconFlow API** (temperature=0.0). The Neo4j graph database import and downstream graph algorithm analysis (community detection, centrality calculation, etc.) have not yet been performed and remain for future work.

## Repository Structure

```
├── Original Materials/
│   ├── Original PDFs/            # Scanned source PDFs of the Science-Metaphysics Debate
│   └── Modified Articles/        # Cleaned and segmented .txt articles of 22 authors
│
├── Knowledge Graph Data Extraction Experiment/   ← Full-text extraction (Chapter 6)
│   ├── SPC (v1)/                 # Specialized, Constrained — Schema v1
│   │   ├── input_texts/          # Input text segments
│   │   ├── kg_runs/              # Extraction results (JSON)
│   │   ├── pipeline/             # Extraction pipeline (Sp-C prompt)
│   │   └── 对比SPC和AI的抽取/    # Comparison between human and AI extraction
│   └── SPCR (v2)/                # Specialized, Constrained, Refined — Schema v2 (improved)
│       ├── input_texts/
│       ├── kg_runs/
│       └── pipeline/             # Extraction pipeline (Sp-CR prompt, refined)
│
└── Six Prompt Variants Comparison Experiment/   ← Benchmarking comparison (Chapter 5)
    ├── pip/                      # Pipeline scripts and dependencies
    │   ├── prompt_variants/      # 6 prompt variants in .txt format (pipeline-ready)
    │   ├── README.txt            # Usage instructions (Chinese)
    │   ├── requirements.txt      # Python dependencies
    │   └── *.py                  # Pipeline scripts (workflow, post-processing, analysis)
    ├── pro/                      # 6 prompt designs in .md format (human-readable)
    │   ├── README.md             # Variant explanation table (English)
    │   ├── Sp-C / Sp-F           # Domain-specific, high/low constraint
    │   ├── Ge-C / Ge-F           # General debate, high/low constraint
    │   └── Do-C / Do-F           # Domain-specific w/out example, high/low constraint
    └── kgrun/                    # Per-author KG extraction results across all 6 variants
```

## How to Reproduce

See the respective `README.txt` in each experiment's `pipeline/` directory for detailed setup and usage instructions.

### Quick Start (Six Prompt Variants Benchmarking)

```bash
cd "Six Prompt Variants Comparison Experiment/pip"
pip install -r requirements.txt
set SILICONFLOW_API_KEY=sk-your-key
python workflow_complete.py       # Core KG extraction
python fix_combined_json.py        # Clean JSON output
python cross_segment_fix.py        # Cross-segment relation completion (requires API)
python run_check.py                # Quality check + Neo4j CSV export
python analyze_centrality.py       # Centrality analysis (optional)
```

### Quick Start (Full-Text Extraction — SPC / SPCR)

Follow the same 5-step pipeline in `Knowledge Graph Data Extraction Experiment/SPC (v1)/pipeline/` or `SPCR (v2)/pipeline/`.

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
