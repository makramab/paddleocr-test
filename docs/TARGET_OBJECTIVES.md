# Invoice Extraction Pipeline: PDF → Markdown → Structured JSON

## What This Document Is For

This document describes how we currently extract structured data from PDF invoices. The goal is to give you a clear picture of the overall process — what goes in, what comes out, and what happens at each step — so you can build an alternative approach without needing access to our codebase.

You have full freedom in how you implement this. What matters is the **final output format** (documented at the end).

---

## The Big Picture

```
PDF file  ──►  Text/Markdown  ──►  3 LLM calls  ──►  Structured JSON
```

1. A PDF (usually an invoice) is converted into markdown text
2. An LLM classifies the document type (invoice, quote, statement, etc.)
3. An LLM extracts vendor and shipping information
4. An LLM extracts line items (the rows in the invoice table)

All three LLM calls receive the markdown text as input and return structured JSON.

---

## Step 1: Convert PDF to Text

### What Happens

The PDF is sent to a document parsing service (we use [MinerU](https://github.com/opendatalab/MinerU)) which converts it into markdown. The key characteristic of this markdown is that **tables are preserved as HTML `<table>` elements**, which makes them easy for an LLM to read.

### Example Output

Given a typical invoice PDF, the markdown looks something like this:

```markdown
# ACME SUPPLIES
123 Main Street, Anytown, CA 90210
Phone: 555-123-4567

## Invoice #INV-2024-001
Date: 2024-02-15

Ship To:
456 Oak Avenue
Brooklyn, NY 11201

<table>
<tr><th>Item</th><th>SKU</th><th>Qty</th><th>Unit</th><th>Price</th><th>Total</th></tr>
<tr><td>Widget A</td><td>WID-001</td><td>100</td><td>EA</td><td>15.50</td><td>1,550.00</td></tr>
<tr><td>Widget B</td><td>WID-002</td><td>50</td><td>EA</td><td>22.00</td><td>1,100.00</td></tr>
</table>

Subtotal: $2,650.00
Tax: $212.00
Total: $2,862.00
```

### Why This Matters

The most important thing about the PDF-to-text step is that **table structure must be preserved**. The LLM needs to understand which values belong to which columns. HTML tables, CSV, or structured markdown tables all work. Raw text with whitespace-aligned columns does not work reliably — LLM tokenization can break the alignment.

### Alternatives Worth Considering

| Approach | Notes |
|---|---|
| [MinerU](https://github.com/opendatalab/MinerU) | What we use. GPU-intensive, self-hosted. Good table preservation. |
| [Docling](https://github.com/DS4SD/docling) | IBM's document parser. Good table support, runs on CPU. |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | Python library. Good table extraction. No GPU needed. |
| [PyMuPDF / fitz](https://pymupdf.readthedocs.io/) | Fast text extraction. Tables need extra work. |
| [unstructured.io](https://github.com/Unstructured-IO/unstructured) | General-purpose document parsing. Cloud or self-hosted. |
| Amazon Textract | Cloud API. Very good table extraction. Pay-per-page. |
| Google Document AI | Cloud API. Strong table support. Pay-per-page. |

---

## Step 2: Classify the Document Type

### What Happens

The first LLM call looks at the beginning of the markdown (roughly the first 2000 characters — just the headers and top section) and classifies the document into one of these types:

| Type | Description |
|---|---|
| `invoice` | Standard invoice requesting payment for goods/services |
| `quote` | Estimate or proposal for future work |
| `statement` | Account statement listing multiple invoices |
| `credit_bill` | Credit memo or credit note reducing amount owed |
| `other` | Anything that doesn't fit the above |

### Why This Matters

The document type affects how line items are extracted in Step 4. For example, a **statement** lists invoice references (each row is an invoice number + amount), while a regular **invoice** lists individual products/services. The extraction prompt changes based on this classification.

### Output

A single string: `"invoice"`, `"quote"`, `"statement"`, `"credit_bill"`, or `"other"`.

If classification fails or returns something unexpected, it defaults to `"invoice"`.

---

## Step 3: Extract Vendor and Shipping Info

### What Happens

The second LLM call receives the **full markdown text** and extracts information about who sent the invoice and where it was shipped.

### What Gets Extracted

**Vendor (from the header/letterhead area):**

| Field | Required | Format | Example |
|---|---|---|---|
| `vendor_name` | Yes | Company name | `"ACME SUPPLIES"` |
| `vendor_address` | No | Street only, capitalized | `"123 MAIN STREET"` |
| `vendor_city` | No | Capitalized | `"ANYTOWN"` |
| `vendor_state` | No | 2-letter abbreviation | `"CA"` |
| `vendor_postal_code` | No | ZIP code | `"90210"` |
| `vendor_phone` | No | XXX-XXX-XXXX | `"555-123-4567"` |
| `vendor_email` | No | Email address | `"sales@acme.com"` |

**Shipping (from "Ship To" / "Deliver To" sections):**

| Field | Required | Format | Example |
|---|---|---|---|
| `shipping_address` | No | Street only, capitalized | `"456 OAK AVENUE"` |
| `shipping_city` | No | Capitalized | `"BROOKLYN"` |
| `shipping_state` | No | 2-letter abbreviation | `"NY"` |
| `shipping_postal_code` | No | ZIP code | `"11201"` |

**Meta:**

| Field | Required | Description |
|---|---|---|
| `field_notes` | Yes | Notes about any issues the LLM encountered |

### Key Details

- Street addresses should contain **only** the street portion (no city/state/ZIP). The individual parts go in separate fields.
- Street type abbreviations are expanded: ST → STREET, AVE → AVENUE, BLVD → BOULEVARD, etc.
- All address text is capitalized.
- We also assemble two convenience fields: `vendor_address_full` and `shipping_address_full` by joining street + city + state + postal code.

### Output Example

```json
{
  "vendor_name": "ACME SUPPLIES",
  "vendor_address": "123 MAIN STREET",
  "vendor_city": "ANYTOWN",
  "vendor_state": "CA",
  "vendor_postal_code": "90210",
  "vendor_phone": "555-123-4567",
  "vendor_email": "sales@acme.com",
  "vendor_address_full": "123 MAIN STREET, ANYTOWN, CA 90210",
  "shipping_address": "456 OAK AVENUE",
  "shipping_city": "BROOKLYN",
  "shipping_state": "NY",
  "shipping_postal_code": "11201",
  "shipping_address_full": "456 OAK AVENUE, BROOKLYN, NY 11201",
  "field_notes": "All fields extracted successfully"
}
```

---

## Step 4: Extract Line Items

### What Happens

The third LLM call receives the **full markdown text** and extracts every line item from the invoice table.

The prompt changes depending on the document type from Step 2:

- **Statements**: Each row represents a referenced invoice (quantity is always 1, description is the invoice number)
- **Everything else**: Standard product/service line items from the table

### What Gets Extracted Per Line Item

| Field | Required | Description | Example |
|---|---|---|---|
| `description` | Yes | Full description of the item or service | `"Widget A"` |
| `quantity` | Yes | Numeric quantity (defaults to 1) | `100` |
| `unit_price` | Yes | Price per unit (defaults to 0.0) | `15.50` |
| `total_price` | Yes | Total for this line (defaults to 0.0) | `1550.00` |
| `units` | No | Unit type | `"EA"`, `"PCS"`, `"FT"` |
| `sku` | No | SKU or item number | `"WID-001"` |
| `sort_order` | No | Position in the original document | `1` |
| `purchase_type` | No | Category | `"materials"`, `"service"`, or `"other"` |
| `length_feet` | No | Length in feet (construction invoices) | `12.0` |
| `length_inches` | No | Length in inches (construction invoices) | `6.0` |
| `referenced_invoice_number` | No | For statement line items only | `"619581"` |

### Summary Block

Along with the line items, a summary is computed:

| Field | Description |
|---|---|
| `total_line_items` | Count of extracted line items |
| `line_items_total` | Sum of all `total_price` values |
| `invoice_total` | The total shown on the invoice itself |
| `tax_amount` | Tax amount if present |

### Output Example

```json
{
  "line_items": [
    {
      "description": "Widget A",
      "quantity": 100,
      "units": "EA",
      "sku": "WID-001",
      "unit_price": 15.50,
      "total_price": 1550.00,
      "sort_order": 1,
      "purchase_type": "materials"
    },
    {
      "description": "Widget B",
      "quantity": 50,
      "units": "EA",
      "sku": "WID-002",
      "unit_price": 22.00,
      "total_price": 1100.00,
      "sort_order": 2,
      "purchase_type": "materials"
    }
  ],
  "extraction_notes": "Successfully extracted 2 line items from table",
  "summary": {
    "total_line_items": 2,
    "line_items_total": 2650.00,
    "invoice_total": 2862.00,
    "tax_amount": 212.00
  }
}
```

---

## The Final Output

After all steps complete, the results are combined into a single JSON object. **This is what your implementation should ultimately produce.**

```json
{
  "document_type": "invoice",
  "vendor_info": {
    "vendor_name": "ACME SUPPLIES",
    "vendor_address": "123 MAIN STREET",
    "vendor_city": "ANYTOWN",
    "vendor_state": "CA",
    "vendor_postal_code": "90210",
    "vendor_phone": "555-123-4567",
    "vendor_email": "sales@acme.com",
    "vendor_address_full": "123 MAIN STREET, ANYTOWN, CA 90210",
    "shipping_address": "456 OAK AVENUE",
    "shipping_city": "BROOKLYN",
    "shipping_state": "NY",
    "shipping_postal_code": "11201",
    "shipping_address_full": "456 OAK AVENUE, BROOKLYN, NY 11201",
    "field_notes": "All fields extracted successfully"
  },
  "table_data": {
    "line_items": [
      {
        "description": "Widget A",
        "quantity": 100,
        "units": "EA",
        "sku": "WID-001",
        "unit_price": 15.50,
        "total_price": 1550.00,
        "sort_order": 1,
        "purchase_type": "materials"
      },
      {
        "description": "Widget B",
        "quantity": 50,
        "units": "EA",
        "sku": "WID-002",
        "unit_price": 22.00,
        "total_price": 1100.00,
        "sort_order": 2,
        "purchase_type": "materials"
      }
    ],
    "extraction_notes": "Successfully extracted 2 line items from table",
    "summary": {
      "total_line_items": 2,
      "line_items_total": 2650.00,
      "invoice_total": 2862.00,
      "tax_amount": 212.00
    }
  }
}
```

The raw markdown from Step 1 is also kept separately for debugging purposes.

---

## Current Approach Summary

| Aspect | What We Currently Use |
|---|---|
| PDF parsing | MinerU (self-hosted, GPU, produces markdown with HTML tables) |
| LLM | GPT-4o (`gpt-4o-2024-08-06`), temperature 0.1 |
| Structured output | OpenAI JSON schema mode (`response_format`) |
| Number of LLM calls | 3 per document (classify → vendor → line items) |
| Processing time | 30–120 seconds per invoice end-to-end |

---

## Guidance for Building an Alternative

### You have freedom in

- **PDF parsing method** — Any tool/library/API that converts PDF to text. The only hard requirement is that table structure is preserved (rows and columns must be distinguishable).
- **LLM choice** — Any model that can return structured JSON. Claude, Gemini, open-source models, etc.
- **Number of LLM calls** — You could combine classification + vendor + line items into fewer calls if your model handles it well. Or split further if needed.
- **Language and framework** — Use whatever you're comfortable with. Python, TypeScript, Go — doesn't matter.
- **Prompt design** — The prompts described above are a starting point. Adapt them to your model and approach.

### What must stay the same

- **The final JSON output structure** — The downstream system expects the shape shown in "The Final Output" section above. The key fields are:
  - `document_type` (string)
  - `vendor_info` with the address fields listed
  - `table_data.line_items` as an array of objects with `description`, `quantity`, `unit_price`, `total_price` at minimum
  - `table_data.summary` with totals

### Common pitfalls

- **Table parsing is the hardest part.** Most extraction failures come from the LLM misreading table structure — wrong values in wrong columns, merged cells, multi-line descriptions, or tables that span multiple pages. Focus your testing here.
- **Construction invoices are messy.** Real-world invoices (especially in construction) have inconsistent formatting, handwritten annotations, faded text, and non-standard table layouts. Test with real samples, not just clean PDFs.
- **Statements vs invoices.** Account statements look like invoices but the "line items" are actually references to other invoices. The classification step exists specifically to handle this distinction.
- **Totals don't always match.** The sum of extracted line items won't always match the invoice total (due to discounts, fees, rounding). The `summary` block captures both values so the discrepancy is visible.
