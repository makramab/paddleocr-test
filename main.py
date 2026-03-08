import argparse
import asyncio
import json
import time
from pathlib import Path

from kreuzberg import ExtractionConfig, OcrConfig, extract_file
from openai import OpenAI

from models import InvoiceExtractionResult

INVOICE_PATH = "./invoices/PH_10_021826_22478997_2026_02_18_211133.PDF"

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


async def main() -> None:
    parser = argparse.ArgumentParser(description="OCR-based invoice extraction pipeline")
    parser.add_argument(
        "--backend",
        choices=list(BACKENDS.keys()),
        default="default",
        help="OCR backend to use (default: PDF text extraction without OCR)",
    )
    args = parser.parse_args()
    backend = args.backend

    output_json = f"./outputs/extraction_result_{backend}.json"
    output_raw = f"./outputs/raw_text_{backend}.txt"

    t_start = time.monotonic()

    # Step 1: Extract text from PDF with Kreuzberg
    print(f"Step 1: Extracting text from PDF with Kreuzberg (backend={backend})...")
    config = BACKENDS[backend]()
    result = await extract_file(INVOICE_PATH, config=config)
    text = result.content

    t_ocr = time.monotonic() - t_start

    print(f"  Extracted {len(text)} characters of text")

    # Save raw extracted text for debugging
    raw_path = Path(output_raw)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(text)
    print(f"  Raw text saved to {output_raw}")

    # Step 2: Send to OpenAI for structured extraction
    print("Step 2: Sending text to OpenAI for structured extraction...")
    t_api_start = time.monotonic()
    client = OpenAI()
    completion = client.beta.chat.completions.parse(
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

    print(f"  Extracted {len(extraction.table_data.line_items)} line items")

    # Step 3: Save result to JSON
    print("Step 3: Saving result...")
    output_data = extraction.model_dump()
    output_data["_meta"] = {
        "backend": backend,
        "ocr_seconds": round(t_ocr, 2),
        "api_seconds": round(t_api, 2),
        "total_seconds": round(t_total, 2),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    json_path = Path(output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"  Saved to {output_json}")

    # Quick summary
    summary = extraction.table_data.summary
    print(f"\nSummary:")
    print(f"  Backend: {backend}")
    print(f"  Document type: {extraction.document_type}")
    print(f"  Vendor: {extraction.vendor_info.vendor_name}")
    print(f"  Line items: {summary.total_line_items}")
    print(f"  Line items total: ${summary.line_items_total:.2f}")
    print(f"  Invoice total: ${summary.invoice_total:.2f}")
    print(f"  Tax: ${summary.tax_amount:.2f}")
    print(f"\nBenchmark:")
    print(f"  OCR extraction: {t_ocr:.2f}s")
    print(f"  API call:       {t_api:.2f}s")
    print(f"  Total:          {t_total:.2f}s")
    print(f"  Tokens: {prompt_tokens} in / {completion_tokens} out / {total_tokens} total")


asyncio.run(main())
