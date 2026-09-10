"""支持中英文、缩写和数字的项目内 BM25。"""

import math
import re
from collections import Counter

from .schemas import RetrievalCandidate


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9_.+-]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]", text.lower())


class BM25Index:
    def __init__(self, store, k1=1.5, b=0.75):
        self.store, self.k1, self.b = store, k1, b

    async def search(self, queries, project_id, document_ids, top_k, access_scope="project"):
        chunks = self.store.searchable_chunks(project_id, document_ids, access_scope)
        if not chunks:
            return []
        docs = [tokenize(chunk["content"]) for chunk in chunks]
        avg = sum(map(len, docs)) / len(docs) or 1
        df = Counter(token for tokens in docs for token in set(tokens))
        query_tokens = set(token for query in queries for token in tokenize(query))
        scored = []
        for raw, tokens in zip(chunks, docs, strict=True):
            tf = Counter(tokens)
            score = 0.0
            for token in query_tokens:
                freq = tf[token]
                if not freq:
                    continue
                idf = math.log(1 + (len(docs) - df[token] + 0.5) / (df[token] + 0.5))
                score += idf * freq * (self.k1 + 1) / (freq + self.k1 * (1 - self.b + self.b * len(tokens) / avg))
            if score > 0:
                scored.append((score, raw))
        scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        return [RetrievalCandidate(chunk=self.store.chunk_model(raw), retrieval_sources=["bm25"], source_ranks={"bm25": rank}) for rank, (_, raw) in enumerate(scored[:top_k], 1)]

