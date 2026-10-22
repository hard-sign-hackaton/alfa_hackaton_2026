"""Prepare extracted bank PDFs (extract_pdf.py JSON) for embedding.

One analytical material usually mixes several loosely related topics, so the
document is split into semantic chunks:

1. headings define sections (the heading path becomes the chunk context);
2. paragraphs, lists and tables stay together inside their section;
3. a section that is too long is split at sentence boundaries;
4. long tables are split by rows and repeat the header row;
5. duplicate boilerplate (footers, disclaimers) is dropped.

Budgets are measured in characters by default, so the script needs no model.
With ``--max-tokens 384`` the E5 tokenizer is used instead: that guarantees the
chunk fits the 512-token input limit of intfloat/multilingual-e5-small.

Output is JSONL: one JSON object per chunk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = "bank-chunks-v1"
DEFAULT_MAX_CHARS = 1000
DEFAULT_MIN_CHARS = 200
DEFAULT_OVERLAP_CHARS = 120

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|")
LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
IMAGE_RE = re.compile(r"^<!--\s*image\s*-->$")
PAGE_BREAK_RES = (
    re.compile(r"^<!--\s*pagebreak\s*-->$"),
    re.compile(r"^<!--\s*page\s*break\s*-->$"),
    re.compile(r"^<!--\s*page\s*(\d+)\s*-->$"),
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+(?=[«\"„(\[]?[0-9A-ZА-ЯЁ])")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
LABEL_HEADING_RE = re.compile(r".+:\s*$")
LABEL_MAX_CHARS = 40
SOURCE_CAPTION_RE = re.compile(
    r"^\s*(источник|ист[оa]чн[иu]к|исmочн|source)\b", re.IGNORECASE
)

DISCLAIMER_SECTION_RE = re.compile(
    r"дисклеймер|disclaimer|правовая информация|раскрытие информации", re.IGNORECASE
)
# OCR of footers/disclaimers is unstable, so match several tolerant patterns
# and require more than one hit before dropping a block.
BOILERPLATE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"генеральн\w*\s+л[иu]ценз",
        r"права\s+защ",
        r"исключительн\w*\s+собственност",
        r"несанкционированн\w*\s+коп",
        r"инвестиционн\w*\s+рекомендац",
        r"не\s+являет\w*\s+индивидуальн",
        r"настоящ\w*\s+(отч[её]т|материал|публикац)",
        r"распространени\w*\s+данного\s+материала",
        r"маркет[\s-]?мейкер",
    )
)

# Period-terminated tokens that must not end a sentence.
ABBREVIATIONS = {
    "г", "гг", "в", "вв", "д", "др", "т", "тт", "пр", "см", "стр", "рис",
    "табл", "млн", "млрд", "тыс", "руб", "коп", "проц", "п", "пп", "им",
    "ул", "пер", "обл", "респ", "англ", "рус", "напр", "долл", "евр",
}

Measure = Callable[[str], int]


@dataclass
class Block:
    kind: str  # heading | text | list | table
    text: str
    page: int | None = None
    level: int = 0
    table_id: str | None = None
    part_index: int = 0
    part_total: int = 1


@dataclass
class Draft:
    section: tuple[str, ...]
    blocks: list[Block] = field(default_factory=list)

    def size(self, measure: Measure) -> int:
        return sum(measure(block.text) for block in self.blocks)

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)

    def tables(self) -> list[dict]:
        result = []
        for block in self.blocks:
            if block.kind != "table":
                continue
            table = {"id": block.table_id, "page": block.page}
            if block.part_total > 1:
                table["part"] = block.part_index
                table["parts"] = block.part_total
            result.append(table)
        return result

    def pages(self) -> list[int]:
        return sorted({block.page for block in self.blocks if block.page is not None})


def parse_blocks(markdown: str) -> list[Block]:
    """Parse markdown into headings, paragraphs, lists and tables."""
    lines = markdown.splitlines()
    has_page_markers = any(
        r.match(line.strip()) for line in lines for r in PAGE_BREAK_RES
    )
    blocks: list[Block] = []
    page: int | None = 1 if has_page_markers else None
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        buffer.clear()
        if text:
            blocks.append(Block("text", text, page=page))

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush()
            index += 1
            continue

        page_break = next(
            (match for match in (r.match(stripped) for r in PAGE_BREAK_RES) if match),
            None,
        )
        if page_break is not None:
            flush()
            if page_break.groups():
                page = int(page_break.group(1))
            elif page is not None:
                page += 1
            index += 1
            continue

        if IMAGE_RE.match(stripped):
            flush()
            index += 1
            continue

        heading = HEADING_RE.match(stripped)
        if heading:
            flush()
            title = heading.group(2).strip()
            if len(title) <= LABEL_MAX_CHARS and LABEL_HEADING_RE.match(title):
                # Short "label:" headings mark the next paragraph, not a topic.
                buffer.append(title)
                index += 1
                continue
            blocks.append(Block("heading", title, page=page, level=len(heading.group(1))))
            index += 1
            continue

        if TABLE_ROW_RE.match(stripped):
            flush()
            table_page = page
            rows = []
            while index < len(lines) and TABLE_ROW_RE.match(lines[index].strip()):
                rows.append(lines[index].rstrip())
                index += 1
            blocks.append(Block("table", "\n".join(rows), page=table_page))
            continue

        if LIST_ITEM_RE.match(line):
            flush()
            items = []
            while index < len(lines):
                current = lines[index]
                current_stripped = current.strip()
                if not current_stripped:
                    break
                if (
                    HEADING_RE.match(current_stripped)
                    or TABLE_ROW_RE.match(current_stripped)
                    or IMAGE_RE.match(current_stripped)
                    or any(r.match(current_stripped) for r in PAGE_BREAK_RES)
                ):
                    break
                items.append(current.rstrip())
                index += 1
            blocks.append(Block("list", "\n".join(items), page=page))
            continue

        buffer.append(line.rstrip())
        index += 1

    flush()
    return blocks


def _is_abbreviation(word: str) -> bool:
    token = word.lower().strip("«»\"'()[]").rstrip(".")
    if not token:
        return True
    if token in ABBREVIATIONS:
        return True
    if re.fullmatch(r"[а-яёa-z]", token):  # initials: "А.", "J."
        return True
    if re.fullmatch(r"\d+", token):  # "2026." is not a sentence end here
        return True
    return False


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    start = 0
    for match in SENTENCE_SPLIT_RE.finditer(text):
        head = text[start : match.start()]
        words = head.rstrip().split()
        if words and _is_abbreviation(words[-1]):
            continue
        sentence = head.strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences or [text.strip()]


def split_words(
    text: str, limit: int, measure: Measure, overlap_chars: int
) -> list[str]:
    """Hard split for OCR blobs without reliable sentence boundaries."""
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = " ".join(current + [word])
        if current and measure(candidate) > limit:
            pieces.append(" ".join(current))
            tail: list[str] = []
            if overlap_chars:
                for previous in reversed(current):
                    addition = " ".join([previous] + tail)
                    if len(addition) > overlap_chars:
                        break
                    tail.insert(0, previous)
            while tail and measure(" ".join(tail + [word])) > limit:
                tail.pop(0)
            current = tail
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def split_text(
    text: str, limit: int, measure: Measure, overlap_chars: int
) -> list[str]:
    if measure(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in split_sentences(text):
        if measure(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(split_words(sentence, limit, measure, overlap_chars))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if measure(candidate) <= limit:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def split_table(text: str, limit: int, measure: Measure) -> list[str]:
    """Split a wide/long markdown table by rows, repeating the header row."""
    lines = text.splitlines()
    if len(lines) <= 2:
        return [text]
    header = lines[:2] if TABLE_SEPARATOR_RE.match(lines[1]) else lines[:1]
    rows = lines[len(header) :]
    header_text = "\n".join(header)
    if not rows:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    for row in rows:
        candidate = "\n".join(header + current + [row])
        if current and measure(candidate) > limit:
            pieces.append("\n".join(header + current))
            current = []
        current.append(row)
    if current:
        pieces.append("\n".join(header + current))
    return pieces or [text]


def make_drafts(
    blocks: list[Block],
    limit: int,
    measure: Measure,
    overlap_chars: int,
    title: str,
    ignore_headings: frozenset[str],
) -> list[Draft]:
    """Group blocks into heading-scoped chunks with a size budget."""
    drafts: list[Draft] = []
    stack: list[tuple[int, str]] = []
    current: Draft | None = None

    def close() -> None:
        nonlocal current
        if current is not None and current.blocks:
            drafts.append(current)
        current = None

    def ensure() -> Draft:
        nonlocal current
        if current is None:
            current = Draft(tuple(title for _, title in stack))
        return current

    def fits(block_text: str) -> bool:
        return current is None or current.size(measure) + measure(block_text) <= limit

    for block in blocks:
        if block.kind == "heading":
            # The document title is metadata, not a section.  Repeated running
            # headers (e.g. "Центр макроэкономического анализа") are configured
            # by the caller because they are indistinguishable from sections.
            if block.text == title or block.text in ignore_headings:
                continue
            close()
            if stack and stack[-1] == (block.level, block.text):
                continue  # repeated slide title
            while stack and stack[-1][0] >= block.level:
                stack.pop()
            stack.append((block.level, block.text))
            continue

        if block.kind == "table":
            parts = split_table(block.text, limit, measure)
            for part_index, part in enumerate(parts, 1):
                if not fits(part):
                    close()
                ensure().blocks.append(
                    Block(
                        "table",
                        part,
                        page=block.page,
                        table_id=block.table_id,
                        part_index=part_index,
                        part_total=len(parts),
                    )
                )
            continue

        for piece in split_text(block.text, limit, measure, overlap_chars):
            if not fits(piece):
                close()
            ensure().blocks.append(Block(block.kind, piece, page=block.page))

    close()
    return drafts


def merge_small(
    drafts: list[Draft],
    limit: int,
    measure: Measure,
    min_size: int,
) -> list[Draft]:
    """Merge tiny chunks into a neighbour inside the same section."""
    merged: list[Draft] = []
    index = 0
    while index < len(drafts):
        draft = drafts[index]
        previous = merged[-1] if merged else None
        if (
            draft.size(measure) < min_size
            and previous is not None
            and previous.section == draft.section
            and previous.size(measure) + draft.size(measure) <= limit
        ):
            previous.blocks.extend(draft.blocks)
            index += 1
            continue
        upcoming = drafts[index + 1] if index + 1 < len(drafts) else None
        if (
            draft.size(measure) < min_size
            and upcoming is not None
            and upcoming.section == draft.section
            and draft.size(measure) + upcoming.size(measure) <= limit
        ):
            draft.blocks.extend(upcoming.blocks)
            merged.append(draft)
            index += 2
            continue
        merged.append(draft)
        index += 1
    return merged


def attach_table_ids(blocks: list[Block], tables: list[dict]) -> None:
    table_blocks = [block for block in blocks if block.kind == "table"]
    for block, table in zip(table_blocks, tables):
        block.table_id = table.get("id")
        page = (table.get("source") or {}).get("page")
        if page is not None:
            block.page = int(page)


def doc_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            return match.group(2).strip()
    return fallback


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_boilerplate(text: str, threshold: int = 2) -> bool:
    hits = sum(1 for pattern in BOILERPLATE_PATTERNS if pattern.search(text))
    return hits >= threshold


def is_disclaimer(draft: Draft) -> bool:
    section = " > ".join(draft.section)
    if section and DISCLAIMER_SECTION_RE.search(section):
        return True
    return is_boilerplate(draft.text)


def build_chunks(
    document: dict,
    *,
    limit: int,
    measure: Measure,
    min_size: int,
    overlap_chars: int,
    keep_disclaimers: bool,
    noise_limit: int,
    ignore_headings: frozenset[str] = frozenset(),
) -> list[dict]:
    markdown = document.get("markdown") or ""
    source_pdf = document.get("source_pdf") or document.get("source_name") or ""
    source_name = document.get("source_name") or (
        Path(source_pdf).name if source_pdf else ""
    )
    doc_id = Path(source_name).stem if source_name else "document"
    title = document.get("title") or doc_title(markdown, doc_id)

    blocks = [
        block
        for block in parse_blocks(markdown)
        if block.kind == "table" or not is_boilerplate(block.text)
    ]
    attach_table_ids(blocks, document.get("tables") or [])
    drafts = merge_small(
        make_drafts(blocks, limit, measure, overlap_chars, title, ignore_headings),
        limit,
        measure,
        min_size,
    )

    chunks: list[dict] = []
    seen: set[str] = set()
    for draft in drafts:
        body = draft.text
        if not keep_disclaimers and is_disclaimer(draft):
            continue
        # Drop OCR noise such as a lone caption or a bare source line.
        if not draft.tables():
            if measure(body) < noise_limit:
                continue
            if not re.search(r"[^\W\d_]", body):
                continue
            if measure(body) < 40 and SOURCE_CAPTION_RE.match(body):
                continue
        body_hash = content_hash(body)
        if body_hash in seen:
            continue  # repeated footer or duplicated slide text
        seen.add(body_hash)

        section = list(draft.section)
        context = [f"Документ: {title}"]
        if section:
            context.append("Раздел: " + " > ".join(section))
        embedding_text = "\n".join(context) + "\n\n" + body
        kinds = {block.kind for block in draft.blocks}
        if "table" in kinds:
            kind = "table" if kinds == {"table"} else "mixed"
        else:
            kind = "text"
        chunks.append(
            {
                "id": f"{doc_id}#{len(chunks) + 1:04d}",
                "doc_id": doc_id,
                "doc_title": title,
                "source_pdf": source_pdf,
                "source_name": source_name,
                "section_path": section,
                "kind": kind,
                "text": body,
                "embedding_text": embedding_text,
                "chars": len(body),
                "size": measure(body),
                "tables": draft.tables(),
                "pages": draft.pages(),
                "content_hash": body_hash[:32],
                "oversized": any(measure(block.text) > limit for block in draft.blocks),
            }
        )
    return chunks


def _char_measure(text: str) -> int:
    return len(text)


def load_documents(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(sorted(item.glob("*.json")))
        elif item.suffix.lower() == ".json":
            files.append(item)
        else:
            raise SystemExit(f"Expected a directory or a JSON file: {item}")
    if not files:
        raise SystemExit("No JSON documents found")
    return files


def make_measure(max_tokens: int, tokenizer_name: str) -> tuple[Measure, int]:
    """Return (measure, min_size) for the token budget mode."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)

    @lru_cache(maxsize=200_000)
    def measure(text: str) -> int:
        return len(
            tokenizer.encode(text, add_special_tokens=False, verbose=False)
        )

    return measure, max(20, max_tokens // 5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split extracted bank PDFs into semantic chunks for embedding"
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Directory with extract_pdf.py JSON files, or individual JSON files",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output JSONL path (default: <input dir>/chunks.jsonl)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help="Character budget per chunk (default mode)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Token budget per chunk; loads the E5 tokenizer (best fit for 512-token E5)",
    )
    parser.add_argument(
        "--tokenizer",
        default="intfloat/multilingual-e5-small",
        help="Tokenizer used with --max-tokens",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=DEFAULT_MIN_CHARS,
        help="Merge chunks smaller than this into a neighbour in the same section",
    )
    parser.add_argument("--overlap-chars", type=int, default=DEFAULT_OVERLAP_CHARS)
    parser.add_argument(
        "--ignore-heading",
        action="append",
        default=[],
        help="Heading text to ignore (repeatable), e.g. a running page header",
    )
    parser.add_argument(
        "--keep-disclaimers",
        action="store_true",
        help="Do not drop disclaimer/legal sections and repeated boilerplate",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write one JSON array instead of JSONL",
    )
    args = parser.parse_args()

    if args.max_tokens is not None:
        if args.max_tokens <= 0:
            raise SystemExit("--max-tokens must be positive")
        measure, min_size = make_measure(args.max_tokens, args.tokenizer)
        limit = args.max_tokens
        noise_limit = 20
        budget = f"{args.max_tokens} tokens"
    else:
        if args.max_chars <= 0:
            raise SystemExit("--max-chars must be positive")
        measure, limit, min_size = _char_measure, args.max_chars, args.min_chars
        noise_limit = 60
        budget = f"{args.max_chars} chars"

    files = load_documents(args.inputs)
    output = args.output
    if output is None:
        base = args.inputs[0] if args.inputs[0].is_dir() else args.inputs[0].parent
        output = base / "chunks.jsonl"

    all_chunks: list[dict] = []
    stats: list[tuple[str, int, int]] = []
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        chunks = build_chunks(
            document,
            limit=limit,
            measure=measure,
            min_size=min_size,
            overlap_chars=args.overlap_chars,
            keep_disclaimers=args.keep_disclaimers,
            noise_limit=noise_limit,
            ignore_headings=frozenset(args.ignore_heading),
        )
        all_chunks.extend(chunks)
        stats.append((path.name, len(chunks), sum(chunk["chars"] for chunk in chunks)))

    output.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        output.write_text(
            json.dumps(all_chunks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        output.write_text(
            "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in all_chunks)
            + "\n",
            encoding="utf-8",
        )

    print(f"{'document':<52}{'chunks':>8}{'chars':>10}")
    for name, count, chars in stats:
        print(f"{name:<52}{count:>8}{chars:>10}")
    sizes = [chunk["size"] for chunk in all_chunks]
    oversized = sum(1 for chunk in all_chunks if chunk["oversized"])
    print(
        f"total: docs={len(files)} chunks={len(all_chunks)} budget={budget} "
        f"size(min/avg/max)={min(sizes, default=0)}/"
        f"{sum(sizes) // max(len(sizes), 1)}/{max(sizes, default=0)} "
        f"oversized={oversized} -> {output}"
    )


if __name__ == "__main__":
    main()
