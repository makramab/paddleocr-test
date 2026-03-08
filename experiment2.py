import asyncio
from kreuzberg import extract_file, ExtractionConfig, OcrConfig

INVOICE = "./invoices/PH_10_021826_22478997_2026_02_18_211133.PDF"


async def run_experiment(name: str, config: ExtractionConfig) -> None:
    print(f"\n{'='*80}")
    print(f"EXPERIMENT: {name}")
    print(f"{'='*80}")

    result = await extract_file(INVOICE, config=config)

    print(f"Content length: {len(result.content)} chars")
    print(f"Tables found: {len(result.tables)}")

    if result.tables:
        for i, table in enumerate(result.tables):
            print(f"\n--- Table {i+1} ---")
            print(f"  Attrs: {dir(table)}")
            if hasattr(table, 'markdown'):
                print(f"  Markdown preview:\n{table.markdown[:500] if table.markdown else 'None'}")
            if hasattr(table, 'cells'):
                print(f"  Cells count: {len(table.cells) if table.cells else 0}")

    print(f"\n--- Content (first 2000 chars) ---")
    print(result.content[:2000])


async def main() -> None:
    # 1. Force OCR + Tesseract (default)
    await run_experiment(
        "Force OCR - Tesseract (default)",
        ExtractionConfig(force_ocr=True),
    )

    # 2. Force OCR + EasyOCR (with correct language code "en")
    await run_experiment(
        "Force OCR - EasyOCR",
        ExtractionConfig(
            force_ocr=True,
            ocr=OcrConfig(backend="easyocr", language="en"),
        ),
    )

    # 3. Force OCR + PaddleOCR
    await run_experiment(
        "Force OCR - PaddleOCR",
        ExtractionConfig(
            force_ocr=True,
            ocr=OcrConfig(backend="paddleocr", language="en"),
        ),
    )

    # 4. Tesseract with table detection enabled
    from kreuzberg import TesseractConfig
    await run_experiment(
        "Force OCR - Tesseract + Table Detection",
        ExtractionConfig(
            force_ocr=True,
            ocr=OcrConfig(
                backend="tesseract",
                language="eng",
                tesseract_config=TesseractConfig(psm=6, enable_table_detection=True),
            ),
        ),
    )


asyncio.run(main())
