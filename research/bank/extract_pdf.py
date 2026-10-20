import argparse
import io
import json
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


def position(item):
    """Source location in Docling PDF coordinates."""
    if not item.prov:
        return {"page": None, "bbox": None}
    provenance = item.prov[0]
    return {"page": provenance.page_no, "bbox": provenance.bbox.model_dump(mode="json")}


def bbox_pixels(bbox, page):
    if bbox is None or page is None or page.image is None or page.size is None:
        return None
    img = page.image.pil_image
    b = bbox.to_top_left_origin(page_height=page.size.height)
    sx = img.width / page.size.width
    sy = img.height / page.size.height
    return (float(b.l * sx), float(b.t * sy), float(b.r * sx), float(b.b * sy))


def crop_cell(page, box):
    img = page.image.pil_image
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
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    proc = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "rus+eng", "--oem", "1", "--psm", "6"],
        input=buffer.getvalue(),
        capture_output=True,
        timeout=90,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip())
    return "\n".join(
        line.strip()
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    )


def extract_tables(doc: DoclingDocument, warnings):
    tables = []

    for index, table in enumerate(doc.tables, 1):
        nrows, ncols = table.data.num_rows, table.data.num_cols
        rows = [[""] * ncols for _ in range(nrows)]

        page_no = table.prov[0].page_no if table.prov else None
        page = doc.pages.get(page_no) if page_no is not None else None

        for cell in table.data.table_cells:
            row, col = cell.start_row_offset_idx, cell.start_col_offset_idx
            raw = cell.text or ""
            text = raw

            crop_box = bbox_pixels(cell.bbox, page)

            if page and crop_box:
                cell_img = crop_cell(page, crop_box)
                try:
                    ocr = ocr_cell(cell_img)
                    if ocr:
                        text = ocr
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    warnings.append(f"table-{index} cell ({row}, {col}): {exc}")

            rows[cell.start_row_offset_idx][cell.start_col_offset_idx] = text

        tables.append({"id": f"table-{index}", "source": position(table), "rows": rows})

    return tables


def main():
    parser = argparse.ArgumentParser(
        description="Extract text, tables and charts from PDF"
    )
    parser.add_argument("pdf", type=Path, help="Input PDF")
    parser.add_argument("json", type=Path, help="Output JSON path")
    parser.add_argument(
        "--model", default="qwen3-vl:8b", help="Local Ollama vision model"
    )
    args = parser.parse_args()

    options = PdfPipelineOptions()
    options.enable_remote_services = False
    options.do_ocr = True
    options.ocr_options = EasyOcrOptions(
        lang=["ru", "en"],
        mode=OcrMode.FULL_PAGE,
    )
    options.do_table_structure = True
    options.generate_page_images = True
    options.generate_picture_images = True
    options.images_scale = 3.0

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )

    print("Start PDF converting")
    result = converter.convert(args.pdf)
    doc = result.document

    print("Start table extraction")
    warnings = []
    tables = extract_tables(doc, warnings)

    result = {
        "source_pdf": str(args.pdf.resolve()),
        "markdown": doc.export_to_markdown(),
        "tables": tables,
        # "charts": charts,
        # "figures": figures,
        # "warnings": warnings,
        # "document": doc.export_to_dict(),
    }
    args.json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Written {args.json} | tables={len(tables)}")


if __name__ == "__main__":
    main()
