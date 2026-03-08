import asyncio
import json
from kreuzberg import extract_file, ExtractionConfig

INVOICE = "./invoices/PH_10_021826_22478997_2026_02_18_211133.PDF"
OUTPUT_DIR = "./outputs"


async def main() -> None:
    config = ExtractionConfig()
    result = await extract_file(INVOICE, config=config)

    # Save raw text content
    with open(f"{OUTPUT_DIR}/default_content.txt", "w") as f:
        f.write(result.content)

    # Save metadata
    with open(f"{OUTPUT_DIR}/default_metadata.json", "w") as f:
        json.dump(result.metadata, f, indent=2, default=str)

    # Save tables (even if empty, for reference)
    with open(f"{OUTPUT_DIR}/default_tables.json", "w") as f:
        tables_data = []
        for table in result.tables:
            tables_data.append({
                "markdown": getattr(table, "markdown", None),
                "cells": [repr(c) for c in getattr(table, "cells", [])],
            })
        json.dump(tables_data, f, indent=2)

    # Save full result summary
    with open(f"{OUTPUT_DIR}/default_summary.json", "w") as f:
        summary = {
            "content_length": len(result.content),
            "tables_count": len(result.tables),
            "metadata": result.metadata,
            "mime_type": result.mime_type,
        }
        json.dump(summary, f, indent=2, default=str)

    print(f"Content: {len(result.content)} chars -> outputs/default_content.txt")
    print(f"Metadata: outputs/default_metadata.json")
    print(f"Tables ({len(result.tables)}): outputs/default_tables.json")
    print(f"Summary: outputs/default_summary.json")


asyncio.run(main())
