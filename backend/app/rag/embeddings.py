"""Embedding 可替换边界与本地实现。"""

import hashlib
import math
import re
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    model_name: str
    version: str

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...


class DeterministicEmbedding(EmbeddingProvider):
    """仅供测试和显式开发配置使用，不需要网络或模型下载。"""

    def __init__(self, dimensions=64, model_name="deterministic-hash", version="1"):
        self.dimensions, self.model_name, self.version = dimensions, model_name, version

    def _one(self, text):
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[a-zA-Z0-9_.+-]+|[\u4e00-\u9fff]", text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1 if digest[4] & 1 else -1
        norm = math.sqrt(sum(value * value for value in vector)) or 1
        return [value / norm for value in vector]

    async def embed_documents(self, texts):
        if any(not text.strip() for text in texts):
            raise ValueError("空文本不能进入 Embedding")
        return [self._one(text) for text in texts]

    async def embed_query(self, text):
        if not text.strip():
            raise ValueError("查询不能为空")
        return self._one(text)


class SentenceTransformerEmbedding(EmbeddingProvider):
    def __init__(self, model_name, version="1", batch_size=32):
        self.model_name, self.version, self.batch_size = model_name, version, batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    async def embed_documents(self, texts):
        import asyncio

        if any(not text.strip() for text in texts):
            raise ValueError("空文本不能进入 Embedding")
        model = self._load()
        values = await asyncio.to_thread(model.encode_document, texts, batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True)
        return values.tolist()

    async def embed_query(self, text):
        import asyncio

        model = self._load()
        value = await asyncio.to_thread(model.encode_query, text, normalize_embeddings=True, convert_to_numpy=True)
        return value.tolist()


def create_embedding(settings):
    if settings.embedding_provider == "deterministic":
        return DeterministicEmbedding(model_name=settings.embedding_model, version=settings.embedding_version)
    if settings.embedding_provider == "sentence_transformers":
        return SentenceTransformerEmbedding(settings.embedding_model, settings.embedding_version, settings.embedding_batch_size)
    raise ValueError("不支持的 EMBEDDING_PROVIDER")

