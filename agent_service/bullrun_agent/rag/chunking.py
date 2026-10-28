"""Section-aware chunking for 10-K / 10-Q text.

Each "Item N." heading starts a section; text is labelled with the most recent
heading, so repeated page headers or a table of contents never drop content.
Boilerplate items (exhibits, signatures, controls) are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ITEM_RE = re.compile(r"^\s*(?:PART\s+[IV]+\s*[-–—,.]?\s*)?ITEM\s+(\d{1,2}[A-C]?)\s*[.:\-–—]?\s*(.{0,120})$",
                     re.IGNORECASE | re.MULTILINE)
PART_RE = re.compile(r"^\s*PART\s+(I{1,2}|IV|III)\b", re.IGNORECASE | re.MULTILINE)

TEN_K = {
    "1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments", "1C": "Cybersecurity",
    "2": "Properties", "3": "Legal Proceedings", "5": "Market for Equity",
    "7": "Management's Discussion and Analysis", "7A": "Market Risk Disclosures", "8": "Financial Statements",
}
TEN_K_SKIP = {"4", "6", "9", "9A", "9B", "9C", "10", "11", "12", "13", "14", "15", "16"}

TEN_Q = {  # (part, item)
    ("I", "1"): "Financial Statements", ("I", "2"): "Management's Discussion and Analysis",
    ("I", "3"): "Market Risk Disclosures", ("II", "1"): "Legal Proceedings", ("II", "1A"): "Risk Factors",
    ("II", "5"): "Other Information",
}
TEN_Q_SKIP = {("I", "4"), ("II", "2"), ("II", "3"), ("II", "4"), ("II", "6")}


@dataclass
class Chunk:
    id: str
    text: str
    meta: dict = field(default_factory=dict)


def _label(form: str, part: str, code: str) -> str | None:
    """Section name, or None if the item is boilerplate we skip."""
    if form.upper().startswith("10-Q"):
        if (part, code) in TEN_Q_SKIP:
            return None
        return TEN_Q.get((part, code), f"Part {part} Item {code}")
    if code in TEN_K_SKIP:
        return None
    return TEN_K.get(code, f"Item {code}")


def split_sections(text: str, form: str = "10-K") -> list[tuple[str, str]]:
    """[(section_name, text)] in document order; consecutive same-name spans are merged."""
    parts = [(m.start(), m.group(1).upper()) for m in PART_RE.finditer(text)]
    hits = [(m.start(), m.group(1).upper()) for m in ITEM_RE.finditer(text)]
    if not hits:
        return [("Full text", text)]

    def part_at(pos: int) -> str:
        current = "I"
        for start, name in parts:
            if start > pos:
                break
            current = "II" if name == "II" else ("I" if name == "I" else current)
        return current

    out: list[tuple[str, str]] = []
    for i, (start, code) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        name = _label(form, part_at(start), code)
        body = text[start:end].strip()
        if name is None or not body:
            continue
        if out and out[-1][0] == name:
            out[-1] = (name, out[-1][1] + "\n\n" + body)
        else:
            out.append((name, body))
    return [(n, b) for n, b in out if len(b) > 80] or [("Full text", text)]


def _tail(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    tail = text[-n:]
    cut = tail.find(" ")
    return tail[cut + 1:] if cut != -1 else tail


def window(text: str, size: int = 1800, overlap: int = 200) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 30]
    chunks, cur = [], ""
    for p in paras:
        if len(p) > size:  # long paragraph: split on sentences
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


def chunk_filing(text: str, base_meta: dict, size: int = 1800, overlap: int = 200) -> list[Chunk]:
    form = str(base_meta.get("form", "10-K"))
    out: list[Chunk] = []
    for s_idx, (section, body) in enumerate(split_sections(text, form)):
        header = f"[{base_meta.get('ticker')} {form} filed {base_meta.get('filed')} | {section}]"
        for j, piece in enumerate(window(body, size, overlap)):
            cid = f"{base_meta.get('ticker')}-{form}-{base_meta.get('filed')}-{s_idx}-{j}"
            out.append(Chunk(id=cid, text=f"{header}\n{piece}", meta={**base_meta, "section": section, "chunk": j}))
    return out
