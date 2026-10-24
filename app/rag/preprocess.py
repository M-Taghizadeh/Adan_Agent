"""Meaningful document preprocessing before chunking/embedding."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class CleanedPage:
    document: str
    page: int
    text: str


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_headers_footers(text: str) -> str:
    """Remove repeated page chrome like 'Adan Retail — Internal' and page numbers."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if re.fullmatch(r"Adan Retail\s*[—\-]\s*Internal.*", stripped, re.IGNORECASE):
            continue
        if re.fullmatch(r"Confidential.*", stripped, re.IGNORECASE):
            continue
        if re.fullmatch(r"Page\s+\d+(\s+of\s+\d+)?", stripped, re.IGNORECASE):
            continue
        if re.fullmatch(r"\d+", stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def fix_hyphenation(text: str) -> str:
    """Join words split across lines by a trailing hyphen."""
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def unicode_normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def preprocess_page(document: str, page: int, raw_text: str) -> CleanedPage | None:
    text = unicode_normalize(raw_text or "")
    text = fix_hyphenation(text)
    text = strip_headers_footers(text)
    text = normalize_whitespace(text)
    if len(text) < 40:
        return None
    return CleanedPage(document=document, page=page, text=text)


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 80,
) -> list[str]:
    """Paragraph-aware character chunking with overlap."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size // 2))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            # Split long paragraphs by sentences roughly
            parts = re.split(r"(?<=[.!?])\s+", para)
            for part in parts:
                if not current:
                    current = part
                elif len(current) + 1 + len(part) <= chunk_size:
                    current = f"{current} {part}"
                else:
                    flush()
                    if chunks and overlap:
                        tail = chunks[-1][-overlap:]
                        current = f"{tail} {part}".strip()
                    else:
                        current = part
            continue

        if not current:
            current = para
        elif len(current) + 2 + len(para) <= chunk_size:
            current = f"{current}\n\n{para}"
        else:
            flush()
            if chunks and overlap:
                tail = chunks[-1][-overlap:]
                current = f"{tail}\n\n{para}".strip()
            else:
                current = para

    flush()
    return chunks
