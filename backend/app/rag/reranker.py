"""Cross-Encoder 重排边界及失败回退。"""

from abc import ABC, abstractmethod


class Reranker(ABC):
    model_name: str
    version: str

    @abstractmethod
    async def score(self, query: str, texts: list[str]) -> list[float]: ...


class DeterministicReranker(Reranker):
    """测试替身按查询词覆盖率打分。"""

    model_name = "deterministic-overlap"
    version = "1"

    async def score(self, query, texts):
        from .keyword_index import tokenize

        terms = set(tokenize(query))
        return [len(terms & set(tokenize(text))) / max(1, len(terms)) for text in texts]


class SentenceTransformerReranker(Reranker):
    def __init__(self, model_name, version="1"):
        self.model_name, self.version, self._model = model_name, version, None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    async def score(self, query, texts):
        import asyncio

        values = await asyncio.to_thread(self._load().predict, [(query, text) for text in texts])
        return [float(value) for value in values]


def create_reranker(settings):
    if settings.reranker_provider == "deterministic":
        return DeterministicReranker()
    if settings.reranker_provider == "sentence_transformers":
        return SentenceTransformerReranker(settings.reranker_model, settings.reranker_version)
    raise ValueError("不支持的 RERANKER_PROVIDER")


async def rerank(query, candidates, reranker, top_n, timeout):
    import asyncio

    head, tail = candidates[:top_n], candidates[top_n:]
    try:
        async with asyncio.timeout(timeout):
            scores = await reranker.score(query, [item.chunk.content for item in head])
        if len(scores) != len(head):
            raise ValueError("重排结果数量不一致")
        ranked = [item.model_copy(update={"rerank_score": score}) for item, score in zip(head, scores, strict=True)]
        ranked.sort(key=lambda item: (-item.rerank_score, item.fused_rank, item.chunk.chunk_id))
        return ranked + tail, False
    except Exception:
        return candidates, True

