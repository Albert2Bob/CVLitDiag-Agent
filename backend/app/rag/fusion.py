"""RRF 排名融合和受控近重复去除。"""

import re


def _signature(text):
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower()))


def _similar(left, right, threshold=0.92):
    a, b = _signature(left), _signature(right)
    return bool(a and b and len(a & b) / len(a | b) >= threshold)


def rrf_fuse(result_lists, k=60):
    merged = {}
    for results in result_lists:
        for fallback_rank, candidate in enumerate(results, 1):
            chunk_id = candidate.chunk.chunk_id
            current = merged.get(chunk_id)
            if current is None:
                current = candidate.model_copy(deep=True)
                current.retrieval_sources = []
                current.source_ranks = {}
                current.fused_score = 0
                merged[chunk_id] = current
            for source in candidate.retrieval_sources:
                rank = candidate.source_ranks.get(source, fallback_rank)
                if source not in current.source_ranks or rank < current.source_ranks[source]:
                    current.source_ranks[source] = rank
                if source not in current.retrieval_sources:
                    current.retrieval_sources.append(source)
    for candidate in merged.values():
        candidate.fused_score = sum(1 / (k + rank) for rank in candidate.source_ranks.values())
    ordered = sorted(merged.values(), key=lambda item: (-item.fused_score, item.chunk.chunk_id))
    unique = []
    for candidate in ordered:
        if any(
            candidate.chunk.document_id == kept.chunk.document_id
            and _similar(candidate.chunk.content, kept.chunk.content)
            for kept in unique
        ):
            continue
        unique.append(candidate)
    return [item.model_copy(update={"fused_rank": rank}) for rank, item in enumerate(unique, 1)]
