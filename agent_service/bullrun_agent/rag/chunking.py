"""Section-aware chunking for 10-K / 10-Q text.

Plain fixed-size chunking mixes "Risk Factors" text into "MD&A" chunks and
loses the most useful metadata. Instead we:
  1. split the filing on its "Item N." headings (skipping the table of contents),
  2. drop boilerplate sections (exhibits, signatures),
  3. window each section into ~1,200-char chunks on paragraph boundaries with
     ~200 chars of overlap, prefixing each chunk with a context header so the
     chunk is self-describing for both BM25 and embeddings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ITEM_RE = re.compile(r"^\s*(?:PART\s+[IV]+\s*[-–—,.]?\s*)?ITEM\s+(\d{1,2}[A-C]?)\s*[.:\-–—]?\s*(.{0,120})$",
                     re.IGNORECASE | re.MULTILINE)

SECTION_NAMES = {
    "1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments", "1C": "Cybersecurity",
    "2": "Properties", "3": "Legal Proceedings", "5": "Market for Equity",
    "7": "Management's Discussion and Analysis", "7A": "Market Risk Disclosures",
    "8": "Financial Statements",
}
SKIP_ITEMS = {"4", "6", "9", "9A", "9B", "9C", "10", "11", "12", "13", "14", "15", "16"}


@dataclass
class Chunk:
    id: str
    text: str
    meta: dict = field(default_factory=dict)


def split_sections(text: str) -> list[tuple[str, str]]:
    """Return [(item_code, section_text)] using the *last* run of Item headings.

    10-Ks list every Item twice: once in the table of contents, once as the real
    heading. We keep, for each item, the occurrence followed by the most text.
    """
    hits = [(m.start(), m.group(1).upper()) for m in ITEM_RE.finditer(text)]
    if not hits:
        return [("FULL", text)]
    best: dict[str, tuple[int, int]] = {}
    for i, (start, code) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        if end - start > best.get(code, (0, 0))[1] - best.get(code, (0, 0))[0]:
            best[code] = (start, end)
    ordered = sorted(best.items(), key=lambda kv: kv[1][0])
    # TOC entries are a single line; a real section has at least a few sentences.
    return [(code, text[s:e].strip()) for code, (s, e) in ordered if e - s > 150]


def _tail(text: str, n: int) -> str:
    """Last ~n chars of text, starting on a word boundary (overlap carried to the next chunk)."""
    if len(text) <= n:
        return text
    tail = text[-n:]
    cut = tail.find(" ")
    return tail[cut + 1:] if cut != -1 else tail


def window(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 30]
    chunks, cur = [], ""
    for p in paras:
        if len(p) > size:  # very long paragraph: hard split on sentences
            for sent in re.split(r"(?<=[.!?])\s+", p):
                if len(cur) + len(sent) > size and cur:
                    chunks.append(cur)
                    cur = _tail(cur, overlap)
                cur += " " + sent
            continue
        if len(cur) + len(p) > size and cur:
            chunks.append(cur)
            cur = _tail(cur, overlap)
        cur += "\n" + p
    if cur.strip():
        chunks.append(cur)
    return [c.strip() for c in chunks]


def chunk_filing(text: str, base_meta: dict, size: int = 1200, overlap: int = 200) -> list[Chunk]:
    out: list[Chunk] = []
    for code, body in split_sections(text):
        if code in SKIP_ITEMS:
            continue
        section = SECTION_NAMES.get(code, f"Item {code}") if code != "FULL" else "Full text"
        header = f"[{base_meta.get('ticker')} {base_meta.get('form')} filed {base_meta.get('filed')} | {section}]"
        for j, piece in enumerate(window(body, size, overlap)):
            meta = {**base_meta, "item": code, "section": section, "chunk": j}
            cid = f"{base_meta.get('ticker')}-{base_meta.get('form')}-{base_meta.get('filed')}-{code}-{j}"
            out.append(Chunk(id=cid, text=f"{header}\n{piece}", meta=meta))
    return out
