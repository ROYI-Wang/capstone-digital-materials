使用说明 — 本地版 KG 抽取流水线
====================================

1. 安装依赖
-----------
打开 cmd 或 PowerShell，进入此目录，运行：
  pip install -r requirements.txt

2. 配置 API Key
---------------
方式 A（推荐）：设置环境变量
  set SILICONFLOW_API_KEY=sk-你的Key

方式 B：首次运行时会提示输入，输入一次即可

3. 放入输入文件
---------------
在 input_texts/ 目录下放入 .txt 文件（同一目录下可放多篇）。
如果没有 input_texts 目录，运行脚本时它会自动创建。

4. 运行流水线
---------------
按顺序运行：

  第1步：python workflow_complete.py     ← 核心抽取（耗时最长）
  第2步：python fix_combined_json.py      ← 清理 JSON 问题
  第3步：python cross_segment_fix.py      ← 跨段关系补全（需 API）
  第4步：python run_check.py              ← 质量检查 + Neo4j CSV 导出
  第5步：python analyze_centrality.py     ← 中心性分析（可选）

输出目录：kg_runs/<作者名>/

注意：第 1 步和第 3 步需调用 SiliconFlow API，
      确保 API Key 余额充足。
