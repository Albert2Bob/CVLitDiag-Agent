"""阶段 4 固定离线评测指标。"""

import argparse
import json
from pathlib import Path


def recall_at(retrieved, relevant, k):
    relevant = set(relevant)
    return len(set(retrieved[:k]) & relevant) / len(relevant) if relevant else 1.0


def evaluate(cases, predictions):
    by_id = {item["case_id"]: item for item in predictions}
    details = []
    for case in cases:
        prediction = by_id.get(case["case_id"], {})
        retrieved = prediction.get("retrieved_chunk_ids", [])
        cited = prediction.get("cited_evidence", [])
        allowed = set(prediction.get("available_evidence", []))
        required = set(case["required_evidence"])
        valid = sum(item in allowed for item in cited) / len(cited) if cited else (1.0 if not required else 0.0)
        supported = sum(item in required for item in cited) / len(required) if required else (1.0 if not cited else 0.0)
        details.append({"case_id": case["case_id"], "recall_at_5": recall_at(retrieved, case["relevant_chunk_ids"], 5), "recall_at_10": recall_at(retrieved, case["relevant_chunk_ids"], 10), "citation_validity": valid, "citation_support": supported, "status_match": prediction.get("status") == case["expected_status"]})
    keys = ("recall_at_5", "recall_at_10", "citation_validity", "citation_support", "status_match")
    summary = {key: sum(float(row[key]) for row in details) / len(details) for key in keys}
    return {"config": {"embedding": "deterministic-hash-v1", "bm25": "unicode-token-v1", "rrf_k": 60, "reranker": "deterministic-overlap-v1", "chunking": "paragraph-char-v1"}, "results": details, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description="运行阶段 4 固定离线检索评测")
    parser.add_argument("--dataset", default="evals/phase4/cases.json")
    parser.add_argument("--predictions", default="evals/phase4/predictions.json")
    parser.add_argument("--output", default="evals/phase4/report.json")
    args = parser.parse_args()
    report = evaluate(json.loads(Path(args.dataset).read_text(encoding="utf-8")), json.loads(Path(args.predictions).read_text(encoding="utf-8")))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
