"""
独立中心性分析脚本 — 基于已生成的 combined_extract.json 直接计算
无需 API Key，不调用 LLM。
输出: neo4j/centrality.csv

用法: python analyze_centrality.py
"""

import json, csv, traceback, sys
from pathlib import Path
import networkx as nx
from config import RUN_ROOT


def find_latest_run_dir():
    kg_root = Path(RUN_ROOT)
    if not kg_root.exists():
        raise FileNotFoundError(f"{RUN_ROOT} 目录不存在")
    dirs = sorted(
        [d for d in kg_root.iterdir()
         if d.is_dir() and (d / "combined_extract.json").exists()],
        key=lambda d: d.stat().st_mtime, reverse=True,
    )
    if not dirs:
        raise FileNotFoundError("未找到包含 combined_extract.json 的目录")
    return dirs[0]


def build_graph(combined):
    G = nx.DiGraph()
    for e in combined.get("entities", []):
        name = e.get("canonical_name") or e.get("name", "")
        if not name:
            continue
        G.add_node(name, entity_type=e.get("type", "Other"))

    for r in combined.get("relations", []):
        head = r.get("head", "")
        tail = r.get("tail", "")
        if not head or not tail:
            continue
        G.add_edge(head, tail,
                   relation=r.get("relation", ""),
                   polarity=r.get("polarity", ""),
                   confidence=float(r.get("confidence", 0.7)))
    return G


def compute_all_centrality(G):
    results = []

    metrics = {}
    for name, func in [
        ("degree_centrality", lambda: nx.degree_centrality(G)),
        ("in_degree_centrality", lambda: nx.in_degree_centrality(G)),
        ("out_degree_centrality", lambda: nx.out_degree_centrality(G)),
        ("pagerank", lambda: nx.pagerank(G, alpha=0.85)),
        ("betweenness_centrality", lambda: nx.betweenness_centrality(G, normalized=True)),
        ("closeness_centrality", lambda: nx.closeness_centrality(G)),
    ]:
        try:
            metrics[name] = func()
        except Exception as e:
            print(f"  [SKIP] {name}: {e}")
            metrics[name] = {}

    for node in G.nodes():
        results.append({
            "node": node,
            "entity_type": G.nodes[node].get("entity_type", ""),
            "degree_centrality": round(metrics["degree_centrality"].get(node, 0), 6),
            "in_degree_centrality": round(metrics["in_degree_centrality"].get(node, 0), 6),
            "out_degree_centrality": round(metrics["out_degree_centrality"].get(node, 0), 6),
            "pagerank": round(metrics["pagerank"].get(node, 0), 6),
            "betweenness_centrality": round(metrics["betweenness_centrality"].get(node, 0), 6),
            "closeness_centrality": round(metrics["closeness_centrality"].get(node, 0), 6),
        })
    return results


def print_top(results, col, label, n=20):
    top = sorted(results, key=lambda x: x[col], reverse=True)[:n]
    print(f"\n  {label} Top {n}:")
    for i, r in enumerate(top, 1):
        if r[col] > 0:
            print(f"    {i:2d}. {r['node']:<35s} ({r['entity_type']:<15s}) {r[col]:.6f}")


def save_csv(results, output_path):
    fieldnames = [
        "node", "entity_type",
        "degree_centrality", "in_degree_centrality", "out_degree_centrality",
        "pagerank", "betweenness_centrality", "closeness_centrality",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    print(f"\n中心性结果已保存: {output_path}")


def main():
    run_dir = find_latest_run_dir()
    combined_path = run_dir / "combined_extract.json"
    neo4j_dir = run_dir / "neo4j"
    neo4j_dir.mkdir(parents=True, exist_ok=True)

    print(f"数据源: {combined_path}")
    combined = json.loads(combined_path.read_text(encoding="utf-8"))
    print(f"实体数: {len(combined.get('entities', []))}, 关系数: {len(combined.get('relations', []))}")

    print("\n构建知识图谱...")
    G = build_graph(combined)
    print(f"图规模: {G.number_of_nodes()} 节点, {G.number_of_edges()} 边")

    if G.number_of_nodes() == 0:
        print("无节点，终止")
        return

    print("\n计算中心性指标...")
    results = compute_all_centrality(G)

    print("\n" + "=" * 60)
    print("中心性分析结果")
    print("=" * 60)

    for col, label in [
        ("degree_centrality", "Degree Centrality（被讨论最多的节点）"),
        ("pagerank", "PageRank（影响力最大）"),
        ("betweenness_centrality", "Betweenness Centrality（跨阵营桥梁）"),
        ("closeness_centrality", "Closeness Centrality（离所有节点最近）"),
    ]:
        print_top(results, col, label)

    save_csv(results, neo4j_dir / "centrality.csv")
    print("\n✅ 中心性分析完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"错误: {e}")
        traceback.print_exc()
