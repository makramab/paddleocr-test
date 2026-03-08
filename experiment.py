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
    print(f"Metadata keys: {list(result.metadata.keys()) if result.metadata else 'None'}")

    if result.tables:
        for i, table in enumerate(result.tables):
            print(f"\n--- Table {i+1} ---")
            print(f"  Type: {type(table)}")
            print(f"  Repr: {repr(table)[:500]}")

    print(f"\n--- Content (first 2000 chars) ---")
    print(result.content[:2000])
    print(f"\n--- Content (last 1000 chars) ---")
    print(result.content[-1000:])


async def main() -> None:
    # 1. Default config
    await run_experiment("Default", ExtractionConfig())

    # 2. Markdown output format
    await run_experiment("Markdown output", ExtractionConfig(output_format="markdown"))

    # 3. Force OCR with default (Tesseract)
    await run_experiment(
        "Force OCR (Tesseract)",
        ExtractionConfig(force_ocr=True),
    )

    # 4. Force OCR + Markdown
    await run_experiment(
        "Force OCR (Tesseract) + Markdown",
        ExtractionConfig(force_ocr=True, output_format="markdown"),
    )

    # 5. EasyOCR backend
    await run_experiment(
        "EasyOCR",
        ExtractionConfig(
            force_ocr=True,
            ocr=OcrConfig(backend="easyocr"),
        ),
    )

    # 6. PaddleOCR backend
    await run_experiment(
        "PaddleOCR",
        ExtractionConfig(
            force_ocr=True,
            ocr=OcrConfig(backend="paddleocr"),
        ),
    )


asyncio.run(main())
