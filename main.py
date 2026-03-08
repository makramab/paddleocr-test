import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from kreuzberg import ExtractionConfig, OcrConfig, extract_file
from openai import AsyncOpenAI, OpenAI
from pypdf import PdfReader, PdfWriter

from models import InvoiceExtractionResult

INVOICE_PATH_DEFAULT = "./invoices/PH_10_021826_22478997_2026_02_18_211133.PDF"
INVOICE_PATH_LONG = "./invoices/inorder/11_PH_10_021826_22464262_2026_02_18_211136.PDF"

SYSTEM_PROMPT = """\
You are an expert invoice data extractor. You will receive raw text extracted from a PDF invoice \
via OCR. The text may have imperfect formatting — columns may not align, descriptions may wrap \
across multiple lines, and sections may run together. Your job is to extract all structured data \
and return it as JSON.

## Identifying the Vendor vs the Customer

The VENDOR is the company that ISSUED the invoice (the seller). The CUSTOMER is who it was \
sold/shipped to. These are different entities.

Clues to identify the vendor:
- The company name in the page header or letterhead (often at the very top)
- Domain names or URLs in the footer (e.g., www.acme.com/terms → vendor is likely "ACME")
- Email addresses like sales@company.com
- Phone/fax numbers near the header or footer
- The entity that sets the payment terms

The "Sold To" or "Bill To" address is the CUSTOMER, not the vendor. Do not confuse them.

If the vendor's full address, phone, or email are not explicitly present in the text, set those \
fields to null rather than guessing or using the customer's information.

## Address Formatting

- Capitalize all address fields (street, city, etc.)
- Expand common street abbreviations: ST → STREET, AVE → AVENUE, DR → DRIVE, BLVD → BOULEVARD, \
RD → ROAD, LN → LANE, CT → COURT, PL → PLACE, RT → ROUTE
- vendor_address_full and shipping_address_full should be assembled from their components, \
joined by ", " (e.g., "123 MAIN STREET, ANYTOWN, CA 90210"). If some components are null, \
only include the parts that exist.

## Identifying Sold To vs Ship To

Invoices often have separate "Sold To" and "Ship To" sections. The shipping_address fields \
should come from the "Ship To" section only. If both addresses appear on the same line or are \
ambiguous, look for contextual clues like column headers. The "Sold To" address is the billing \
address and should NOT be used for shipping fields.

## Extracting Line Items

The text is OCR output, so table rows may not be neatly formatted. Each line item typically \
has: line number, quantity, SKU/product number, description, unit of measure, unit price, \
and extension (total price).

- The SKU/product number is a separate field from the description. Do NOT include the SKU \
in the description field.
- Descriptions may wrap across multiple lines. Concatenate continuation lines into a single \
description, joining with a space.
- Use the QNTY SHIP column (not QNTY ORD) for the quantity field.
- The EXTENSION column is the total_price for each line.
- sort_order should match the line number (LN) column.
- purchase_type: use "materials" for physical goods/products, "service" for labor/services, \
"other" if unclear.

## Summary

- total_line_items: count of extracted line items
- line_items_total: sum of all line item total_price values (the merchandise subtotal)
- invoice_total: the final total shown on the invoice (after tax, freight, etc.)
- tax_amount: the tax amount if shown, otherwise 0.0

## General Rules

- If a field is not present in the invoice, use null.
- Be precise with numbers — do not round or approximate. Use the exact values from the text.
- Only extract data that is explicitly present. Do not infer or fabricate values.
"""

BACKENDS = {
    "default": lambda: ExtractionConfig(),
    "easyocr": lambda: ExtractionConfig(
        force_ocr=True, ocr=OcrConfig(backend="easyocr", language="en")
    ),
    "tesseract": lambda: ExtractionConfig(
        force_ocr=True, ocr=OcrConfig(backend="tesseract", language="eng")
    ),
    "paddleocr": lambda: ExtractionConfig(
        force_ocr=True, ocr=OcrConfig(backend="paddleocr", language="en")
    ),
}


async def extract_with_page_split(invoice_path: str, config: ExtractionConfig, label: str) -> str:
    """Split PDF into single pages and OCR each one sequentially to limit peak memory."""
    reader = PdfReader(invoice_path)
    total_pages = len(reader.pages)
    print(f"{label}  Splitting PDF into {total_pages} pages for sequential OCR...")

    all_text = []
    for i, page in enumerate(reader.pages):
        page_num = i + 1
        writer = PdfWriter()
        writer.add_page(page)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            writer.write(tmp)
            tmp_path = tmp.name

        try:
            result = await extract_file(tmp_path, config=config)
            all_text.append(result.content)
            print(f"{label}  Page {page_num}/{total_pages}: {len(result.content)} chars")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return "\n".join(all_text)


async def run_single(
    backend: str,
    invoice_path: str = INVOICE_PATH_DEFAULT,
    run_id: int | None = None,
    client: AsyncOpenAI | None = None,
    page_split: bool = False,
) -> dict:
    """Run a single extraction pipeline. Returns timing/token metadata."""
    label = f"[run {run_id}] " if run_id is not None else ""
    suffix = f"_run{run_id}" if run_id is not None else ""

    output_json = f"./outputs/extraction_result_{backend}{suffix}.json"
    output_raw = f"./outputs/raw_text_{backend}{suffix}.txt"

    t_start = time.monotonic()

    # Step 1: Extract text from PDF with Kreuzberg
    print(f"{label}Step 1: Extracting text from PDF with Kreuzberg (backend={backend})...")
    config = BACKENDS[backend]()

    if page_split and invoice_path.lower().endswith(".pdf"):
        text = await extract_with_page_split(invoice_path, config, label)
    else:
        result = await extract_file(invoice_path, config=config)
        text = result.content

    t_ocr = time.monotonic() - t_start

    print(f"{label}  Extracted {len(text)} characters of text")

    # Save raw extracted text for debugging
    raw_path = Path(output_raw)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(text)
    print(f"{label}  Raw text saved to {output_raw}")

    # Step 2: Send to OpenAI for structured extraction
    print(f"{label}Step 2: Sending text to OpenAI for structured extraction...")
    t_api_start = time.monotonic()
    if client is None:
        client = AsyncOpenAI()
    completion = await client.beta.chat.completions.parse(
        model="gpt-5.1-2025-11-13",
        reasoning_effort="none",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format=InvoiceExtractionResult,
    )
    extraction = completion.choices[0].message.parsed

    t_api = time.monotonic() - t_api_start
    t_total = time.monotonic() - t_start

    usage = completion.usage
    prompt_tokens = usage.prompt_tokens
    completion_tokens = usage.completion_tokens
    total_tokens = usage.total_tokens

    print(f"{label}  Extracted {len(extraction.table_data.line_items)} line items")

    # Step 3: Save result to JSON
    print(f"{label}Step 3: Saving result...")
    output_data = extraction.model_dump()
    meta = {
        "backend": backend,
        "run_id": run_id,
        "ocr_seconds": round(t_ocr, 2),
        "api_seconds": round(t_api, 2),
        "total_seconds": round(t_total, 2),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    output_data["_meta"] = meta
    json_path = Path(output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"{label}  Saved to {output_json}")

    # Quick summary
    summary = extraction.table_data.summary
    print(f"\n{label}Summary:")
    print(f"{label}  Backend: {backend}")
    print(f"{label}  Document type: {extraction.document_type}")
    print(f"{label}  Vendor: {extraction.vendor_info.vendor_name}")
    print(f"{label}  Line items: {summary.total_line_items}")
    print(f"{label}  Line items total: ${summary.line_items_total:.2f}")
    print(f"{label}  Invoice total: ${summary.invoice_total:.2f}")
    print(f"{label}  Tax: ${summary.tax_amount:.2f}")
    print(f"\n{label}Benchmark:")
    print(f"{label}  OCR extraction: {t_ocr:.2f}s")
    print(f"{label}  API call:       {t_api:.2f}s")
    print(f"{label}  Total:          {t_total:.2f}s")
    print(f"{label}  Tokens: {prompt_tokens} in / {completion_tokens} out / {total_tokens} total")

    return meta


async def main() -> None:
    parser = argparse.ArgumentParser(description="OCR-based invoice extraction pipeline")
    parser.add_argument(
        "--backend",
        choices=list(BACKENDS.keys()),
        default="default",
        help="OCR backend to use (default: PDF text extraction without OCR)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Run N extractions in parallel for stress testing (default: 1)",
    )
    parser.add_argument(
        "--long",
        action="store_true",
        help="Use the long invoice (77 line items) instead of the default sample",
    )
    parser.add_argument(
        "--page-split",
        action="store_true",
        help="Split PDF into single pages and OCR each sequentially to reduce peak memory",
    )
    args = parser.parse_args()
    backend = args.backend
    parallel = args.parallel
    page_split = args.page_split
    invoice_path = INVOICE_PATH_LONG if args.long else INVOICE_PATH_DEFAULT

    if parallel <= 1:
        await run_single(backend, invoice_path=invoice_path, page_split=page_split)
        return

    # Stress test mode
    print(f"Stress test: launching {parallel} parallel runs with backend={backend}\n")
    t_wall_start = time.monotonic()
    client = AsyncOpenAI()
    tasks = [run_single(backend, invoice_path=invoice_path, run_id=i, client=client, page_split=page_split) for i in range(1, parallel + 1)]
    results = await asyncio.gather(*tasks)
    t_wall = time.monotonic() - t_wall_start

    # Print stress test summary
    print("\n" + "=" * 70)
    print(f"STRESS TEST SUMMARY ({parallel} parallel runs, backend={backend})")
    print("=" * 70)
    print(f"{'Run':<6} {'OCR':>8} {'API':>8} {'Total':>8} {'Tokens':>8}")
    print("-" * 42)
    for r in results:
        print(f"  {r['run_id']:<4} {r['ocr_seconds']:>7.2f}s {r['api_seconds']:>7.2f}s "
              f"{r['total_seconds']:>7.2f}s {r['total_tokens']:>7}")

    ocr_times = [r["ocr_seconds"] for r in results]
    api_times = [r["api_seconds"] for r in results]
    total_times = [r["total_seconds"] for r in results]
    total_tokens = sum(r["total_tokens"] for r in results)

    print("-" * 42)
    print(f"  {'Avg':<4} {sum(ocr_times)/len(ocr_times):>7.2f}s {sum(api_times)/len(api_times):>7.2f}s "
          f"{sum(total_times)/len(total_times):>7.2f}s {total_tokens//parallel:>7}")
    print(f"\n  Wall clock:    {t_wall:.2f}s")
    print(f"  Total tokens:  {total_tokens}")
    print(f"  Throughput:    {parallel / t_wall:.2f} invoices/sec")


asyncio.run(main())
