"""文档摘要先路由文档，再在候选文档内召回真实分块。"""

from .keyword_index import tokenize


def build_summary(chunks, limit=3000):
    title = next((c.title for c in chunks if c.title), "")
    sections = list(dict.fromkeys(c.section for c in chunks if c.section))[:20]
    samples = " ".join(c.content[:500] for c in chunks[:5])
    return "\n".join(part for part in [title, "；".join(sections), samples] if part)[:limit]


class SummaryIndex:
    def __init__(self, store, bm25_index):
        self.store, self.bm25_index = store, bm25_index

    async def search(self, queries, project_id, document_ids, top_k, access_scope="project"):
        summaries = self.store.searchable_summaries(project_id, document_ids, access_scope)
        query_tokens = set(token for query in queries for token in tokenize(query))
        routed = []
        for row in summaries:
            tokens = tokenize(row["summary"])
            score = sum(tokens.count(token) for token in query_tokens)
            if score:
                routed.append((score, row["document_id"]))
        routed.sort(key=lambda item: (-item[0], item[1]))
        candidate_docs = [document_id for _, document_id in routed[: max(1, min(5, top_k))]]
        if not candidate_docs:
            return []
        candidates = await self.bm25_index.search(queries, project_id, candidate_docs, top_k, access_scope)
        return [candidate.model_copy(update={"retrieval_sources": ["summary"], "source_ranks": {"summary": rank}}) for rank, candidate in enumerate(candidates, 1)]

