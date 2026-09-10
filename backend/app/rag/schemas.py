"""RAG 领域契约。"""

from typing import Annotated, Literal

from pydantic import Field

from ..schemas import Contract, ResourceId

ShortText = Annotated[str, Field(min_length=1, max_length=1000)]
LongText = Annotated[str, Field(min_length=1, max_length=50000)]


class ExtractedUnit(Contract):
    content: LongText
    title: str = Field(default="", max_length=1000)
    section: str = Field(default="", max_length=1000)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    locator: str | None = Field(default=None, max_length=1000)


class ExtractionResult(Contract):
    units: list[ExtractedUnit] = Field(max_length=10000)
    page_count: int | None = Field(default=None, ge=1)
    parse_quality: Literal["high", "medium", "limited"]
    extractor_name: str = Field(min_length=1, max_length=100)
    extractor_version: str = Field(min_length=1, max_length=40)
    quality_notes: list[str] = Field(default_factory=list, max_length=20)


class DocumentChunk(Contract):
    chunk_id: ResourceId
    document_id: ResourceId
    document_version: int = Field(ge=1)
    project_id: ResourceId
    title: str = Field(default="", max_length=1000)
    section: str = Field(default="", max_length=1000)
    page_number: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    locator: str | None = Field(default=None, max_length=1000)
    chunk_index: int = Field(ge=0)
    content: LongText
    content_hash: str = Field(min_length=64, max_length=64)
    access_scope: str = Field(default="project", min_length=1, max_length=100)
    token_count: int = Field(ge=1)
    created_at: str


class RetrievalCandidate(Contract):
    chunk: DocumentChunk
    retrieval_sources: list[Literal["bm25", "vector", "summary", "adjacent"]] = Field(default_factory=list)
    source_ranks: dict[str, int] = Field(default_factory=dict)
    fused_score: float = 0
    fused_rank: int = Field(default=0, ge=0)
    rerank_score: float | None = None


class Evidence(Contract):
    evidence_id: ResourceId
    run_id: ResourceId
    project_id: ResourceId
    document_id: ResourceId
    document_version: int = Field(ge=1)
    chunk_id: ResourceId
    document_name: ShortText
    section: str = Field(default="", max_length=1000)
    page_number: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    locator: str | None = Field(default=None, max_length=1000)
    snippet: LongText
    retrieval_sources: list[str] = Field(default_factory=list, max_length=3)
    fused_rank: int = Field(ge=1)
    rerank_score: float | None = None


class SearchArguments(Contract):
    query: Annotated[str, Field(min_length=1, max_length=4000)]
    project_id: ResourceId
    document_ids: list[ResourceId] | None = Field(default=None, max_length=50)
    top_k: int = Field(default=8, ge=1, le=30)
    comparison_mode: bool = False
    missing_information: list[ShortText] = Field(default_factory=list, max_length=10)


class SearchResult(Contract):
    query: str
    normalized_queries: list[str] = Field(max_length=20)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)
    retrieval_summary: dict
    degraded_sources: list[str] = Field(default_factory=list, max_length=3)
    has_more: bool = False
