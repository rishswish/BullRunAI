"""Section-aware chunking for 10-K / 10-Q / 8-K text.

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


# 8-K items worth searching ("2.02" = quarterly results). 9.01 is just the exhibit list.
EIGHT_K = {
    "1.01": "Material agreement", "1.02": "Agreement ended", "1.05": "Cybersecurity incident",
    "2.01": "Acquisition or sale", "2.02": "Earnings results", "2.03": "New debt", "2.05": "Restructuring",
    "2.06": "Impairment", "3.01": "Listing notice", "4.01": "Auditor change", "4.02": "Restatement",
    "5.01": "Change in control", "5.02": "Executive or board change", "5.03": "Bylaws change",
    "5.07": "Shareholder vote", "7.01": "Regulation FD disclosure", "8.01": "Other events",
}
EIGHT_K_SKIP = {"9.01"}
EIGHT_K_ITEM_RE = re.compile(r"^\s*ITEM\s+(\d\.\d{2})\b", re.IGNORECASE | re.MULTILINE)
EXHIBIT_RE = re.compile(r"^\[\[EXHIBIT (99(?:\.\d+)?)\]\]$", re.MULTILINE)
# Legal "forward-looking statements" boilerplate in press releases reads like a risk list
# and would crowd out the real Risk Factors on "what are the risks" questions.
BOILERPLATE_RE = re.compile(r"forward[- ]looking statement|safe harbor", re.IGNORECASE)


def useful_8k(items: str) -> bool:
    """Skip 8-Ks that only attach exhibits or report a shareholder vote tally."""
    codes = {c.strip() for c in (items or "").split(",") if c.strip()}
    return bool(codes - {"9.01", "5.07"})


def split_8k(text: str, items: str = "") -> list[tuple[str, str]]:
    """Sections of an 8-K: each reported item, then each EX-99 exhibit appended by edgar.fetch_text."""
    marks = sorted([(m.start(), "item", m.group(1)) for m in EIGHT_K_ITEM_RE.finditer(text)]
                   + [(m.start(), "exhibit", m.group(1)) for m in EXHIBIT_RE.finditer(text)])
    earnings = "2.02" in (items or "")
    out: list[tuple[str, str]] = []
    for i, (start, kind, code) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[start:end]
        if kind == "item":
            if code in EIGHT_K_SKIP:
                continue
            name = f"{EIGHT_K.get(code, 'Item')} (Item {code})"
        else:
            body = EXHIBIT_RE.sub("", body)
            body = "\n\n".join(p for p in re.split(r"\n\s*\n", body) if not BOILERPLATE_RE.search(p))
            name = f"{'Earnings release' if earnings else 'Press release'} (Ex. {code})"
        body = body.strip()
        if len(body) > 80:
            out.append((name, body))
    return out or ([("Full text", text)] if len(text.strip()) > 80 else [])


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
    eight_k = form.upper() == "8-K"
    sections = split_8k(text, base_meta.get("items", "")) if eight_k else split_sections(text, form)
    # a company can file two 8-Ks on one day, so those ids also carry the accession number
    tag = f"-{base_meta.get('accession', '')[-6:]}" if eight_k else ""
    out: list[Chunk] = []
    for s_idx, (section, body) in enumerate(sections):
        header = f"[{base_meta.get('ticker')} {form} filed {base_meta.get('filed')} | {section}]"
        for j, piece in enumerate(window(body, size, overlap)):
            cid = f"{base_meta.get('ticker')}-{form}-{base_meta.get('filed')}{tag}-{s_idx}-{j}"
            out.append(Chunk(id=cid, text=f"{header}\n{piece}", meta={**base_meta, "section": section, "chunk": j}))
    return out
