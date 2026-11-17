#!/usr/bin/env python3
"""从仓库 evidence/ 中的真实评测记录生成图表数据（docs/tech-report/data/*.dat）。

图表中的每个数字都由本脚本从原始证据文件计算，不手工填写：
  evidence/review-upgrade/retrieval-nemotron-all-rerank.json   80 题 × 4 种检索配置（23,185 片段）
  evidence/review-upgrade/retrieval-qwen-core.json             Qwen3-Embedding-8B 核心 50 题对照
用法：python3 docs/tech-report/tools/make_figdata.py
"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(exist_ok=True)
METHODS = ["sparse", "dense", "hybrid", "reranked"]


def load(name):
    return json.loads((ROOT / "evidence/review-upgrade" / name).read_text())


def ranks(cases, method):
    """每道有答案题中首个标准证据块的名次；未进入候选记为 None。"""
    return [c["metrics"][method]["first_gold_rank"] for c in cases if c["answerable"] and method in c["metrics"]]


def hit_at(rs, k):
    return 100.0 * sum(1 for r in rs if r is not None and r <= k) / len(rs)


def mrr(rs):
    return sum(1.0 / r for r in rs if r is not None) / len(rs)


nem = load("retrieval-nemotron-all-rerank.json")
qwen = load("retrieval-qwen-core.json")
summary = {}

# 1) Hit@K 曲线（K=1..20），核心 / 拓展 / 合计
for scope in ("core", "expansion", "all"):
    cases = [c for c in nem["cases"] if scope == "all" or c["group"] == scope]
    table = {m: ranks(cases, m) for m in METHODS}
    lines = ["k " + " ".join(METHODS)]
    for k in range(1, 21):
        lines.append(f"{k} " + " ".join(f"{hit_at(table[m], k):.2f}" for m in METHODS))
    (OUT / f"hitk_{scope}.dat").write_text("\n".join(lines) + "\n")
    summary[scope] = {m: {"n": len(table[m]), "hit1": hit_at(table[m], 1), "hit5": hit_at(table[m], 5),
                          "hit10": hit_at(table[m], 10), "hit20": hit_at(table[m], 20), "mrr": mrr(table[m])}
                      for m in METHODS}

# 2) 题型 × 检索配置 的 Hit@5 热力图
groups = [
    ("事实问答（核心）", lambda c: c["group"] == "core" and c["category"] == "fact"),
    ("541 页长文档", lambda c: c["category"] == "long_document"),
    ("扫描件与表格", lambda c: c["category"] == "structured_scan_table"),
    ("错误前提", lambda c: c["category"] == "false_premise"),
    ("作者 / 版本 / 比较", lambda c: c["category"] in ("authors", "version_sensitive", "comparison")),
    ("事实问答（拓展 35 篇）", lambda c: c["group"] == "expansion"),
    ("中文提问", lambda c: c["language"] == "zh"),
    ("英文提问", lambda c: c["language"] == "en"),
]
rows = ["x y value n label"]
heat = []
for yi, (label, pred) in enumerate(groups):
    cases = [c for c in nem["cases"] if c["answerable"] and pred(c)]
    row = {"label": label, "n": len(cases)}
    for xi, m in enumerate(METHODS):
        v = hit_at(ranks(cases, m), 5)
        row[m] = v
        rows.append(f"{xi} {yi} {v:.1f} {len(cases)} {{{label}}}")
    heat.append(row)
(OUT / "heat_hit5.dat").write_text("\n".join(rows) + "\n")
summary["heat_hit5"] = heat

# 2b) 直接生成热力图的 TikZ 单元格（顺序单色，数值写在格内）
cells = []
for yi, row in enumerate(heat):
    y = -yi * 6.6
    cells.append(f"\\node[anchor=east,font=\\footnotesize]at(-1.5,{y:.1f}){{{row['label']}}};")
    cells.append(f"\\node[anchor=west,font=\\scriptsize,text=rtmuted]at(60.5,{y:.1f}){{$n={row['n']}$}};")
    for xi, m in enumerate(METHODS):
        v = row[m]
        shade = 6 + 0.86 * v
        ink = "white" if v >= 62 else "rtink"
        cells.append(f"\\node[fill=dvA!{shade:.0f}!white,minimum width=14.4mm,minimum height=6mm,inner sep=0pt,"
                     f"font=\\footnotesize,text={ink}]at({xi * 15 + 7.5:.1f},{y:.1f}){{{v:.0f}}};")
(OUT / "heat_hit5.tex").write_text("\n".join(cells) + "\n")

# 3) 嵌入模型对照（核心 45 题，同一切分与题集）
core = [c for c in nem["cases"] if c["group"] == "core"]
cmp_rows = ["k nemotron qwen bm25"]
rn, rq, rs = ranks(core, "dense"), ranks(qwen["cases"], "dense"), ranks(core, "sparse")
for k in range(1, 21):
    cmp_rows.append(f"{k} {hit_at(rn, k):.2f} {hit_at(rq, k):.2f} {hit_at(rs, k):.2f}")
(OUT / "embed_compare.dat").write_text("\n".join(cmp_rows) + "\n")
summary["embed_compare"] = {"nemotron": {"hit5": hit_at(rn, 5), "hit20": hit_at(rn, 20), "mrr": mrr(rn)},
                            "qwen": {"hit5": hit_at(rq, 5), "hit20": hit_at(rq, 20), "mrr": mrr(rq)},
                            "qwen_hybrid_mrr": mrr(ranks(qwen["cases"], "hybrid"))}

# 4) 首个标准证据的名次分布（用于名次箱线 / 抖动图）
dist = ["method rank"]
for mi, m in enumerate(METHODS):
    for r in ranks([c for c in nem["cases"]], m):
        dist.append(f"{mi} {r if r is not None else 60}")
(OUT / "rank_dist.dat").write_text("\n".join(dist) + "\n")

secs = [c["seconds"] for c in nem["cases"] if "seconds" in c]
summary["rerank_seconds"] = {"median": statistics.median(secs), "p90": sorted(secs)[int(0.9 * len(secs))], "n": len(secs)}
summary["aggregates"] = nem["aggregates"]
summary["source"] = {"generation": nem["source_generation"], "vectors": nem["document_vectors"]["count"],
                     "embedder": nem["descriptor"]["model_id"], "dimension": nem["descriptor"]["dimension"]}
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
print(json.dumps(summary, ensure_ascii=False, indent=1))
