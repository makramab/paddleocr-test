"""Run PaddleOCR + GPT extraction on a batch of 10 invoices."""

import asyncio
import json
import time
from pathlib import Path

from kreuzberg import ExtractionConfig, OcrConfig, extract_file
from openai import OpenAI

from models import InvoiceExtractionResult

SYSTEM_PROMPT = Path("main.py").read_text().split('SYSTEM_PROMPT = """\\\n')[1].split('\n"""')[0]

# Re-import the prompt from main.py to stay DRY
exec_ns = {}
exec(compile(Path("main.py").read_text(), "main.py", "exec"), exec_ns)
SYSTEM_PROMPT = exec_ns["SYSTEM_PROMPT"]

INVOICES = [
    {"id": "01_pyramid_22478997", "path": "./invoices/PH_10_021826_22478997_2026_02_18_211133.PDF"},
    {"id": "02_pyramid_22421611", "path": "./invoices/PH_3_021626_22421611_2026_02_17_213618.PDF"},
    {"id": "03_pyramid_22464776", "path": "./invoices/PH_21_022626_22464776_2026_02_26_185611.PDF"},
    {"id": "04_epsco_S8407088", "path": "./invoices/simons-hardware_406661_20260219_31764086_14917892346_2026_02_19_173816.pdf"},
    {"id": "05_apco_4349", "path": "./invoices/Invoice_4349_from_APCO_FIRE_SPECIALTY_PRODUCTS_2026_02_17_214119.pdf"},
    {"id": "06_flowmark_I0014915", "path": "./invoices/Invoice_I-0014915_2026_02_25_193006.pdf"},
    {"id": "07_ocs_156704", "path": "./invoices/Invoice 156704_2026_02_18_211126.pdf"},
    {"id": "08_lion_2158900", "path": "./invoices/Sales Invoice 2158900 (Order", "mime_type": "application/pdf"},
    {"id": "09_rockland_080927", "path": "./invoices/20260219_080927_2026_02_19_175334.pdf"},
    {"id": "10_beckerle_200930", "path": "./invoices/2602-200930_2026_02_24_190316.pdf"},
]


async def process_invoice(inv: dict, client: OpenAI) -> dict:
    inv_id = inv["id"]
    inv_path = inv["path"]
    mime_type = inv.get("mime_type")

    print(f"\n[{inv_id}] Starting...")

    t_start = time.monotonic()

    # Step 1: OCR
    config = ExtractionConfig(
        force_ocr=True,
        ocr=OcrConfig(backend="paddleocr", language="en"),
    )
    kwargs = {"config": config}
    if mime_type:
        kwargs["mime_type"] = mime_type
    result = await extract_file(inv_path, **kwargs)
    text = result.content
    print(f"[{inv_id}] OCR done — {len(text)} chars")

    # Save raw text
    raw_path = Path(f"./outputs/raw_text_paddleocr_{inv_id}.txt")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(text)

    # Step 2: GPT structured extraction
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
    elapsed = time.monotonic() - t_start

    usage = completion.usage
    output_data = extraction.model_dump()
    output_data["_meta"] = {
        "invoice_id": inv_id,
        "backend": "paddleocr",
        "elapsed_seconds": round(elapsed, 2),
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }

    # Save JSON
    json_path = Path(f"./outputs/extraction_result_paddleocr_{inv_id}.json")
    json_path.write_text(json.dumps(output_data, indent=2, ensure_ascii=False) + "\n")

    vi = extraction.vendor_info
    summary = extraction.table_data.summary
    print(f"[{inv_id}] Done in {elapsed:.1f}s — {vi.vendor_name} — "
          f"{summary.total_line_items} items, ${summary.invoice_total:.2f} — "
          f"{usage.total_tokens} tokens")

    return output_data


async def main():
    client = OpenAI()

    # Process sequentially to avoid rate limits and keep output readable
    results = []
    for inv in INVOICES:
        result = await process_invoice(inv, client)
        results.append(result)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'ID':<28} {'Vendor':<30} {'Items':>5} {'Total':>10} {'Time':>6} {'Tokens':>7}")
    print("-" * 95)
    for r in results:
        m = r["_meta"]
        vi = r["vendor_info"]
        s = r["table_data"]["summary"]
        print(f"{m['invoice_id']:<28} {(vi['vendor_name'] or '?')[:30]:<30} "
              f"{s['total_line_items']:>5} {s['invoice_total']:>10.2f} "
              f"{m['elapsed_seconds']:>5.1f}s {m['total_tokens']:>7}")


asyncio.run(main())
