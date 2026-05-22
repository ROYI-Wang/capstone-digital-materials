"""
本地运行配置文件
使用方法：
  1. 安装依赖: pip install -r requirements.txt
  2. 将待提取的 .txt 文件放入 input_texts/ 目录
  3. 在运行前设置环境变量 SILICONFLOW_API_KEY
     或在首次运行时按提示输入 API Key
  4. 运行: python workflow_complete.py
"""

import os
from pathlib import Path

# ==================== 路径配置 ====================

# 工作区根目录（默认为脚本所在目录）
WORKSPACE_DIR = Path(__file__).parent.parent.resolve()

# 输入文件目录（放 .txt 文件）
# 可通过设置 KG_INPUT_DIR 环境变量覆盖（用于并行处理）
_input_override = os.environ.get("KG_INPUT_DIR", "").strip()
INPUT_DIR = Path(_input_override) if _input_override else (WORKSPACE_DIR / "input_texts")

# 输出根目录（KG 运行结果）
RUN_ROOT = WORKSPACE_DIR / "kg_runs"

# ==================== API 配置 ====================

API_KEY_ENV_NAME = "SILICONFLOW_API_KEY"
BASE_URL = "https://api.siliconflow.cn/v1"
MODEL = "deepseek-ai/DeepSeek-V4-Flash"

TEMPERATURE = 0.0
MAX_TOKENS = 32768
REQUEST_TIMEOUT_SECONDS = 180
MAX_API_RETRY = 5
REQUEST_SLEEP_SECONDS = 0.25

# ==================== 分段配置 ====================

SEGMENT_MAX_CHARS = 600
SEGMENT_OVERLAP = 80

# ==================== 抽取配置 ====================

FORCE_RERUN_SUCCESS = False
RERUN_FAILED_AFTER_MAIN = True
FAILED_RERUN_PASSES = 2

STRICT_EVIDENCE_CHECK = True
DROP_UNSUPPORTED_EVIDENCE = True

# ==================== Schema ====================

PROJECT_NAME = "科学玄学论战KG_lite"
SCHEMA_VERSION = "lite_v2.0"
PROMPT_VERSION = "SP-C"

# ==================== 文章元数据覆盖 ====================

ARTICLE_METADATA_OVERRIDES: dict = {}

# 示例：
# ARTICLE_METADATA_OVERRIDES = {
#     "张君劢.txt": {"source_author": "张君劢"},
#     "胡适.txt": {"source_author": "胡适"},
# }
