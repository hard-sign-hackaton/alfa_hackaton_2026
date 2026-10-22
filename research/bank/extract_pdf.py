"""PDF -> JSON extraction of text and tables for the bank research materials.

Charts are intentionally not recognized: the vision-LLM pass was dropped.
"""

import argparse
import hashlib
import importlib.metadata
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    OcrMode,
    PdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import DoclingDocument
from PIL import Image, ImageOps
from pypdfium2 import PdfDocument

TESSERACT_LANGS = "rus+eng"
OCR_TIMEOUT = 90
SCHEMA_VERSION = "bank-extraction-v2"
PAGE_BREAK_PLACEHOLDER = "<!-- page break -->"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
PAGE_MARKER_RES = (
    re.compile(r"^<!--\s*pagebreak\s*-->$"),
    re.compile(r"^<!--\s*page\s*break\s*-->$"),
    re.compile(r"^<!--\s*page\s*(\d+)\s*-->$"),
)
IMAGE_PLACEHOLDER_RE = re.compile(r"^<!--\s*image\s*-->$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def page_marker(line: str):
    stripped = line.strip()
    return next((match for match in (r.match(stripped) for r in PAGE_MARKER_RES) if match), None)


def content_line(line: str) -> bool:
    """True when a line carries document content (not blank, image or page marker)."""
    stripped = line.strip()
    return bool(stripped) and not IMAGE_PLACEHOLDER_RE.match(stripped) and page_marker(stripped) is None


def document_structure(markdown: str) -> tuple[str | None, str | None, list[dict]]:
    """Extract title, subtitle and heading locations from exported Markdown.

    Docling writes all headings in these materials as level-2 headings, so the
    hierarchy cannot be reconstructed from levels alone.  The first heading is
    the document title.  The second one is a subtitle only when there is no
    content between the two headings; otherwise it is a normal section.
    """
    lines = markdown.splitlines()
    has_page_markers = any(page_marker(line) for line in lines)
    page = 1 if has_page_markers else None
    headings: list[dict] = []

    for index, line in enumerate(lines):
        marker = page_marker(line)
        if marker is not None:
            if marker.groups():
                page = int(marker.group(1))
            elif page is not None:
                page += 1
            continue

        match = HEADING_RE.match(line.strip())
        if match:
            headings.append(
                {
                    "level": len(match.group(1)),
                    "text": match.group(2).strip(),
                    "page": page,
                    "_line": index,
                }
            )

    title = headings[0]["text"] if headings else None
    subtitle = None
    if len(headings) > 1:
        between = lines[headings[0]["_line"] + 1 : headings[1]["_line"]]
        if not any(content_line(line) for line in between):
            subtitle = headings[1]["text"]

    return title, subtitle, [
        {key: value for key, value in heading.items() if key != "_line"}
        for heading in headings
    ]


def page_count(pdf: Path) -> int:
    """Number of pages in the PDF, without rendering them."""
    with PdfDocument(str(pdf)) as document:
        return len(document)


def position(item):
    """Source location in Docling PDF coordinates."""
    if not item.prov:
        return {"page": None, "bbox": None}
    provenance = item.prov[0]
    return {"page": provenance.page_no, "bbox": provenance.bbox.model_dump(mode="json")}


def bbox_pixels(bbox, page):
    """Convert PDF bbox into pixel coordinates of the rendered page image."""
    if bbox is None or page is None or page.image is None or page.size is None:
        return None
    pil_image = page.image.pil_image
    if pil_image is None:
        return None
    b = bbox.to_top_left_origin(page_height=page.size.height)
    sx = pil_image.width / page.size.width
    sy = pil_image.height / page.size.height
    return (float(b.l * sx), float(b.t * sy), float(b.r * sx), float(b.b * sy))


def crop_cell(page, box):
    """Crop one table cell and prepare it for OCR."""
    if box is None:
        return None
    img = page.image.pil_image
    if img is None:
        return None
    # Trim possible ruled borders, but do not crop text aggressively.
    left = max(0, int(round(box[0])) + 1)
    top = max(0, int(round(box[1])) + 1)
    right = min(img.width, int(round(box[2])) - 1)
    bottom = min(img.height, int(round(box[3])) - 1)
    if right <= left + 3 or bottom <= top + 3:
        return None
    crop = img.crop((left, top, right, bottom)).convert("L")
    crop = ImageOps.autocontrast(crop, cutoff=1)
    # Upsampling does not add missing detail, but can improve segmentation.
    if crop.height < 150:
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    return ImageOps.expand(crop, border=16, fill=255)


def ocr_cell(image):
    """Run tesseract on a single cell image."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    proc = subprocess.run(
        [
            "tesseract",
            "stdin",
            "stdout",
            "-l",
            TESSERACT_LANGS,
            "--oem",
            "1",
            "--psm",
            "6",
        ],
        input=buffer.getvalue(),
        capture_output=True,
        timeout=OCR_TIMEOUT,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
    return "\n".join(
        line.strip()
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    )


def extract_tables(
    doc: DoclingDocument, warnings: list[str], use_cell_ocr: bool = True
) -> list[dict]:
    tables = []

    for index, table in enumerate(doc.tables, 1):
        data = table.data
        nrows, ncols = data.num_rows, data.num_cols
        rows = [[""] * ncols for _ in range(nrows)]
        table_warnings: list[str] = []

        page_no = table.prov[0].page_no if table.prov else None
        page = doc.pages.get(page_no) if page_no is not None else None

        failed_cells = 0
        last_error = None

        for cell in data.table_cells:
            row, col = cell.start_row_offset_idx, cell.start_col_offset_idx
            if not (0 <= row < nrows and 0 <= col < ncols):
                table_warnings.append(
                    f"table-{index}: cell ({row}, {col}) is outside the table grid"
                )
                continue

            text = cell.text or ""

            if use_cell_ocr and page is not None:
                cell_image = crop_cell(page, bbox_pixels(cell.bbox, page))
                if cell_image is not None:
                    try:
                        ocr = ocr_cell(cell_image)
                    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                        failed_cells += 1
                        last_error = exc
                    else:
                        if ocr:
                            text = ocr

            rows[row][col] = text

        if failed_cells:
            table_warnings.append(
                f"table-{index}: cell OCR failed for {failed_cells} cells "
                f"(text from the document layer is kept): {last_error}"
            )

        warnings.extend(table_warnings)
        tables.append(
            {
                "id": f"table-{index}",
                "source": position(table),
                "nrows": nrows,
                "ncols": ncols,
                "rows": rows,
                "warnings": table_warnings,
            }
        )

    return tables


def main():
    parser = argparse.ArgumentParser(
        description="Extract text and tables from a PDF into JSON"
    )
    parser.add_argument("pdf", type=Path, help="Input PDF")
    parser.add_argument("json", type=Path, help="Output JSON path")
    parser.add_argument(
        "--no-cell-ocr",
        action="store_true",
        help="Do not re-OCR table cells with tesseract; use the document text layer",
    )
    parser.add_argument(
        "--keep-last-page",
        action="store_true",
        help="Also process the last page; it is skipped by default",
    )
    parser.add_argument(
        "--no-page-markers",
        action="store_true",
        help="Do not insert <!-- page break --> markers into Markdown",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="Store source_pdf relative to this directory instead of as passed",
    )
    args = parser.parse_args()

    source = args.pdf.expanduser()
    if not source.is_file():
        parser.error(f"PDF not found: {source}")

    source_pdf = str(args.pdf)
    if args.source_root is not None:
        try:
            source_pdf = source.resolve().relative_to(
                args.source_root.expanduser().resolve()
            ).as_posix()
        except ValueError:
            parser.error(f"PDF is outside --source-root: {source}")

    options = PdfPipelineOptions()
    options.enable_remote_services = False
    options.do_ocr = True
    options.ocr_options = EasyOcrOptions(
        lang=["ru", "en"],
        mode=OcrMode.FULL_PAGE,
    )
    options.do_table_structure = True
    options.generate_page_images = True
    options.images_scale = 3.0

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )

    total_pages = page_count(source)
    last_page = total_pages if args.keep_last_page else total_pages - 1

    warnings: list[str] = []
    markdown = ""
    tables: list[dict] = []
    cell_ocr_used = False

    if last_page < 1:
        warnings.append(
            f"document has {total_pages} page(s); the last page is skipped, nothing to process"
        )
        print("Nothing to process: the only page is the last one")
    else:
        print(f"Start PDF converting: {source} (pages 1-{last_page} of {total_pages})")
        doc = converter.convert(source, page_range=(1, last_page)).document
        markdown = doc.export_to_markdown(
            page_break_placeholder=(
                None if args.no_page_markers else PAGE_BREAK_PLACEHOLDER
            )
        )

        use_cell_ocr = not args.no_cell_ocr
        if use_cell_ocr and shutil.which("tesseract") is None:
            warnings.append(
                "tesseract not found in PATH; table cells are taken from the document text layer"
            )
            use_cell_ocr = False
        cell_ocr_used = use_cell_ocr

        print("Start table extraction")
        tables = extract_tables(doc, warnings, use_cell_ocr=use_cell_ocr)

        if not args.no_page_markers:
            expected_markers = max(last_page - 1, 0)
            actual_markers = markdown.count(PAGE_BREAK_PLACEHOLDER)
            if actual_markers != expected_markers:
                warnings.append(
                    f"expected {expected_markers} page markers, found {actual_markers}"
                )

    title, subtitle, headings = document_structure(markdown)
    output = {
        "schema_version": SCHEMA_VERSION,
        "source_pdf": source_pdf,
        "source_name": args.pdf.name,
        "source_sha256": file_sha256(source),
        "source_bytes": source.stat().st_size,
        "page_count": total_pages,
        "pages_processed": list(range(1, last_page + 1)) if last_page >= 1 else [],
        "skipped_pages": list(range(last_page + 1, total_pages + 1)),
        "title": title,
        "subtitle": subtitle,
        "headings": headings,
        "markdown": markdown,
        "tables": tables,
        "warnings": warnings,
        "extractor": {
            "name": "docling",
            "version": package_version("docling"),
            "core_version": package_version("docling-core"),
            "ocr": "easyocr(ru,en)",
            "cell_ocr": f"tesseract({TESSERACT_LANGS})" if cell_ocr_used else None,
            "page_markers": not args.no_page_markers,
        },
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Written {args.json} | pages={last_page if last_page >= 1 else 0}/{total_pages} "
        f"tables={len(tables)} warnings={len(warnings)}"
    )


if __name__ == "__main__":
    main()
