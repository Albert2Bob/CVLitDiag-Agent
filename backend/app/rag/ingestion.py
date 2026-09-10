"""文档处理编排；只有全部必要索引成功后才切换为 ready。"""

import asyncio
from pathlib import Path

from .chunking import chunk_document
from .extractors import ExtractionError, extract


class DocumentProcessor:
    def __init__(self, store, storage_root, settings, embedding, vector_index):
        self.store, self.root, self.settings = store, Path(storage_root).resolve(), settings
        self.embedding, self.vector_index = embedding, vector_index
        self.tasks = {}

    def start(self, document_id):
        task = asyncio.create_task(self.process(document_id), name=f"document:{document_id}")
        self.tasks[document_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(document_id, None))

    async def cancel(self, document_id):
        if task := self.tasks.get(document_id):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def stop(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def process(self, document_id):
        try:
            doc = self.store.document(document_id, internal=True)
            path = (self.root / doc["storage_key"]).resolve()
            if self.root not in path.parents or path.is_symlink():
                raise ExtractionError("STORAGE_BOUNDARY", "文档存储位置不合法。")
            self.store.set_document_status(document_id, "parsing")
            self.store.append_document_event(document_id, "document_parsing_started", {})
            result = await asyncio.to_thread(extract, path, doc["file_type"], self.settings)
            self.store.append_document_event(
                document_id,
                "document_parsing_finished",
                {"page_count": result.page_count, "parse_quality": result.parse_quality},
            )
            produced = chunk_document(
                result,
                document_id=document_id,
                document_version=doc["document_version"],
                project_id=doc["project_id"],
                access_scope=doc["access_scope"],
                size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
                max_chunks=self.settings.max_chunks_per_document,
            )
            if len(produced) > self.settings.max_chunks_per_document:
                raise ExtractionError("CHUNK_LIMIT", "文档分块数量超过系统限制。")
            self.store.set_document_status(document_id, "indexing")
            self.store.append_document_event(
                document_id, "document_indexing_started", {"chunk_count": len(produced)}
            )
            vectors = []
            for start in range(0, len(produced), self.settings.embedding_batch_size):
                batch = produced[start : start + self.settings.embedding_batch_size]
                vectors.extend(await self.embedding.embed_documents([item.content for item in batch]))
            if len(vectors) != len(produced):
                raise RuntimeError("Embedding 数量不一致")
            self.store.commit_document(
                document_id,
                result,
                produced,
                vectors,
                self.embedding.model_name,
                self.embedding.version,
                f"chars-{self.settings.chunk_size}-{self.settings.chunk_overlap}-v1",
            )
            self.store.append_document_event(
                document_id, "document_indexing_finished", {"chunk_count": len(produced)}
            )
        except asyncio.CancelledError:
            raise
        except ExtractionError as exc:
            self.store.fail_document(document_id, exc.code, exc.safe_message, unsupported=exc.unsupported)
            self.store.append_document_event(
                document_id,
                "document_processing_failed",
                {"code": exc.code, "message": exc.safe_message},
            )
        except Exception:
            self.store.fail_document(document_id, "INDEXING_FAILED", "文档索引失败，请检查模型配置后重试。")
            self.store.append_document_event(
                document_id,
                "document_processing_failed",
                {"code": "INDEXING_FAILED", "message": "文档索引失败，请检查模型配置后重试。"},
            )
