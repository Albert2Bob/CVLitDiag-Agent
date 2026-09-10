"""受限文本提取器；上传内容始终按不可信数据处理。"""

import csv
import io
import json
import math
import re
from collections import Counter
from pathlib import Path

from .schemas import ExtractedUnit, ExtractionResult


class ExtractionError(ValueError):
    def __init__(self, code: str, message: str, *, unsupported: bool = False):
        super().__init__(message)
        self.code, self.safe_message, self.unsupported = code, message, unsupported


def _decode(data: bytes) -> str:
    if b"\x00" in data:
        raise ExtractionError("UNSAFE_TEXT_ENCODING", "文件不是可安全解码的文本。")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ExtractionError("UNSAFE_TEXT_ENCODING", "文件必须使用 UTF-8 编码。")


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def extract_pdf(path: Path, *, max_pages: int, max_chars: int) -> ExtractionResult:
    try:
        import pymupdf
    except ImportError as exc:
        raise ExtractionError("PDF_EXTRACTOR_UNAVAILABLE", "PDF 文本提取组件未安装。") from exc
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ExtractionError("INVALID_PDF", "PDF 文件损坏或格式不合法。") from exc
    try:
        if not doc.is_pdf or doc.page_count < 1:
            raise ExtractionError("INVALID_PDF", "文件不是有效 PDF。")
        if doc.page_count > max_pages:
            raise ExtractionError("PDF_PAGE_LIMIT", "PDF 页数超过系统限制。")
        pages = [_clean(page.get_text("text", sort=True)) for page in doc]
        boundary_lines: Counter[str] = Counter()
        if len(pages) >= 3:
            for text in pages:
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if lines:
                    boundary_lines.update({lines[0], lines[-1]})
        repeated = {
            line
            for line, count in boundary_lines.items()
            if len(line) <= 120 and count >= max(3, math.ceil(len(pages) * 0.6))
        }
        units, empty, total, current_section = [], 0, 0, ""
        heading_pattern = re.compile(
            r"^(?:\d+(?:\.\d+)*[.)、\s]+|摘要\b|引言\b|方法\b|实验\b|结果\b|讨论\b|结论\b|参考文献\b|abstract\b|introduction\b|methods?\b|experiments?\b|results?\b|discussion\b|conclusion\b)",
            re.IGNORECASE,
        )
        for index, raw_text in enumerate(pages):
            lines = [line for line in raw_text.splitlines() if line.strip() not in repeated]
            text = _clean("\n".join(lines))
            if not text:
                empty += 1
                continue
            for line in lines[:10]:
                candidate = line.strip()
                if 2 <= len(candidate) <= 120 and (
                    heading_pattern.match(candidate)
                    or (candidate.isupper() and any(char.isalpha() for char in candidate))
                ):
                    current_section = candidate[:1000]
                    break
            total += len(text)
            if total > max_chars:
                raise ExtractionError("TEXT_LIMIT", "文档可提取文本超过系统限制。")
            units.append(
                ExtractedUnit(
                    content=text,
                    section=current_section,
                    page_start=index + 1,
                    page_end=index + 1,
                )
            )
        if not units or empty / doc.page_count > 0.8 or total / doc.page_count < 5:
            raise ExtractionError("SCANNED_PDF_UNSUPPORTED", "PDF 缺少可检索文本，当前不支持扫描件 OCR。", unsupported=True)
        ratio = empty / doc.page_count
        quality = "high" if ratio < 0.1 else "medium" if ratio < 0.4 else "limited"
        notes = ["复杂公式仅保留提取器返回的可见文本。"] if quality != "high" else []
        return ExtractionResult(units=units, page_count=doc.page_count, parse_quality=quality, extractor_name="PyMuPDF", extractor_version=pymupdf.__version__, quality_notes=notes)
    finally:
        doc.close()


def extract_markdown(data: bytes, *, max_chars: int) -> ExtractionResult:
    text = _clean(_decode(data))
    if not text or len(text) > max_chars:
        raise ExtractionError("EMPTY_OR_OVERSIZED_TEXT", "Markdown 为空或文本超过系统限制。")
    units, headings, buffer = [], [], []

    def flush():
        content = _clean("\n".join(buffer))
        if content:
            units.append(ExtractedUnit(content=content, title=headings[0] if headings else "", section=" > ".join(headings)))
        buffer.clear()

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            level, heading = len(match[1]), match[2][:1000]
            headings[:] = headings[: level - 1]
            headings.append(heading)
        else:
            buffer.append(line)
    flush()
    return ExtractionResult(units=units, parse_quality="high", extractor_name="markdown-heading", extractor_version="1")


def extract_text(data: bytes, *, max_chars: int) -> ExtractionResult:
    text = _clean(_decode(data))
    if not text or len(text) > max_chars:
        raise ExtractionError("EMPTY_OR_OVERSIZED_TEXT", "文本为空或超过系统限制。")
    return ExtractionResult(units=[ExtractedUnit(content=text)], parse_quality="high", extractor_name="plain-text", extractor_version="1")


def extract_csv(data: bytes, *, max_chars: int, max_rows: int = 20000, max_columns: int = 200, max_cell: int = 10000) -> ExtractionResult:
    text = _decode(data)
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise ExtractionError("INVALID_CSV", "CSV 结构不合法。") from exc
    if not rows or len(rows) > max_rows or max(map(len, rows), default=0) > max_columns:
        raise ExtractionError("CSV_LIMIT", "CSV 为空或行列数超过系统限制。")
    header = rows[0]
    units, total = [], 0
    for start in range(1, len(rows), 50):
        batch = rows[start : start + 50]
        lines = []
        for offset, row in enumerate(batch, start=start + 1):
            cells = []
            for index, value in enumerate(row):
                if len(value) > max_cell:
                    raise ExtractionError("CSV_CELL_LIMIT", "CSV 单元格超过系统限制。")
                cells.append(f"{header[index] if index < len(header) and header[index] else f'column_{index + 1}'}={value}")
            lines.append(f"row {offset}: " + "; ".join(cells))
        content = "\n".join(lines)
        total += len(content)
        if total > max_chars:
            raise ExtractionError("TEXT_LIMIT", "CSV 展开文本超过系统限制。")
        if content:
            units.append(ExtractedUnit(content=content, section="CSV 数据", locator=f"rows {start + 1}-{start + len(batch)}"))
    return ExtractionResult(units=units, parse_quality="high", extractor_name="python-csv", extractor_version="1")


def extract_json(data: bytes, *, max_chars: int, max_depth: int = 20, max_nodes: int = 50000, max_field: int = 10000) -> ExtractionResult:
    try:
        value = json.loads(_decode(data))
    except (ValueError, RecursionError) as exc:
        raise ExtractionError("INVALID_JSON", "JSON 内容不合法。") from exc
    units, count, total = [], 0, 0

    def walk(node, path="$", depth=0):
        nonlocal count, total
        count += 1
        if depth > max_depth or count > max_nodes:
            raise ExtractionError("JSON_LIMIT", "JSON 深度或节点数超过系统限制。")
        if isinstance(node, dict):
            for key, item in node.items():
                safe_key = str(key)[:300]
                walk(item, f"{path}.{safe_key}", depth + 1)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]", depth + 1)
        else:
            rendered = json.dumps(node, ensure_ascii=False)
            if len(rendered) > max_field:
                raise ExtractionError("JSON_FIELD_LIMIT", "JSON 单字段超过系统限制。")
            content = f"{path}: {rendered}"
            total += len(content)
            if total > max_chars:
                raise ExtractionError("TEXT_LIMIT", "JSON 展开文本超过系统限制。")
            units.append(ExtractedUnit(content=content, section="JSON 数据", locator=path))
    walk(value)
    if not units:
        raise ExtractionError("EMPTY_JSON", "JSON 中没有可检索的值。")
    return ExtractionResult(units=units, parse_quality="high", extractor_name="python-json", extractor_version="1")


def extract(path: Path, file_type: str, settings) -> ExtractionResult:
    if file_type == "pdf":
        return extract_pdf(path, max_pages=settings.max_pdf_pages, max_chars=settings.max_extracted_chars)
    data = path.read_bytes()
    kwargs = {"max_chars": settings.max_extracted_chars}
    return {"md": extract_markdown, "txt": extract_text, "csv": extract_csv, "json": extract_json}[file_type](data, **kwargs)
