"""按章节、段落和页面边界生成稳定文本块。"""

import hashlib
import re

from ..storage import now
from .schemas import DocumentChunk, ExtractionResult


def _stable_id(document_id: str, version: int, index: int, content_hash: str, strategy: str) -> str:
    raw = f"{document_id}\0{version}\0{index}\0{content_hash}\0{strategy}".encode()
    return "chunk_" + hashlib.sha256(raw).hexdigest()[:32]


def _pieces(text: str, size: int, overlap: int):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                yield current
                current = ""
            step = max(1, size - overlap)
            for start in range(0, len(paragraph), step):
                piece = paragraph[start : start + size].strip()
                if piece:
                    yield piece
                if start + size >= len(paragraph):
                    break
        elif not current or len(current) + 2 + len(paragraph) <= size:
            current = f"{current}\n\n{paragraph}".strip()
        else:
            yield current
            prefix = current[-overlap:] if overlap else ""
            current = f"{prefix}\n\n{paragraph}".strip()
    if current:
        yield current


def chunk_document(result: ExtractionResult, *, document_id: str, document_version: int, project_id: str, access_scope: str, size: int, overlap: int, max_chunks: int) -> list[DocumentChunk]:
    if overlap >= size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")
    chunks = []
    strategy = f"paragraph-char-v1:{size}:{overlap}"
    for unit in result.units:
        for content in _pieces(unit.content, size, overlap):
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            index = len(chunks)
            chunks.append(DocumentChunk(chunk_id=_stable_id(document_id, document_version, index, content_hash, strategy), document_id=document_id, document_version=document_version, project_id=project_id, title=unit.title, section=unit.section, page_number=unit.page_start, page_end=unit.page_end, locator=unit.locator, chunk_index=index, content=content, content_hash=content_hash, access_scope=access_scope, token_count=max(1, len(re.findall(r"[\w]+|[\u4e00-\u9fff]", content))), created_at=now()))
            if len(chunks) > max_chunks:
                raise ValueError("文档分块数量超过系统限制")
    if not chunks:
        raise ValueError("文档没有可索引文本")
    return chunks
