import asyncio
from kreuzberg import extract_file, ExtractionConfig, OcrConfig, TesseractConfig

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
            if hasattr(table, 'markdown') and table.markdown:
                print(f"  Markdown:\n{table.markdown[:800]}")
            if hasattr(table, 'cells') and table.cells:
                print(f"  Cells count: {len(table.cells)}")
                for j, cell in enumerate(table.cells[:10]):
                    print(f"    Cell {j}: {repr(cell)}")

    print(f"\n--- Content (first 2000 chars) ---")
    print(result.content[:2000])


async def main() -> None:
    # Tesseract with table detection
    await run_experiment(
        "Force OCR - Tesseract + Table Detection (psm=6)",
        ExtractionConfig(
            force_ocr=True,
            ocr=OcrConfig(
                backend="tesseract",
                language="eng",
                tesseract_config=TesseractConfig(psm=6, enable_table_detection=True),
            ),
        ),
    )

    # Also try: default extraction but with markdown + HTML output
    await run_experiment(
        "Default + HTML output",
        ExtractionConfig(output_format="html"),
    )


asyncio.run(main())
