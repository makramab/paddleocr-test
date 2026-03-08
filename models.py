from __future__ import annotations

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = Field(description="Full description of the item or service")
    quantity: float = Field(default=1, description="Numeric quantity")
    units: str | None = Field(default=None, description="Unit type (EA, PCS, FT, etc.)")
    sku: str | None = Field(default=None, description="SKU or item number")
    unit_price: float = Field(default=0.0, description="Price per unit")
    total_price: float = Field(default=0.0, description="Total for this line")
    sort_order: int | None = Field(default=None, description="Position in the original document")
    purchase_type: str | None = Field(
        default=None, description="Category: materials, service, or other"
    )


class ExtractionSummary(BaseModel):
    total_line_items: int = Field(description="Count of extracted line items")
    line_items_total: float = Field(description="Sum of all total_price values")
    invoice_total: float = Field(description="The total shown on the invoice itself")
    tax_amount: float = Field(default=0.0, description="Tax amount if present")


class TableData(BaseModel):
    line_items: list[LineItem] = Field(description="Extracted line items")
    extraction_notes: str = Field(default="", description="Notes about the extraction")
    summary: ExtractionSummary


class VendorInfo(BaseModel):
    vendor_name: str = Field(description="Company name")
    vendor_address: str | None = Field(default=None, description="Street address only, capitalized")
    vendor_city: str | None = Field(default=None, description="City, capitalized")
    vendor_state: str | None = Field(default=None, description="2-letter state abbreviation")
    vendor_postal_code: str | None = Field(default=None, description="ZIP code")
    vendor_phone: str | None = Field(default=None, description="Phone number")
    vendor_email: str | None = Field(default=None, description="Email address")
    vendor_address_full: str | None = Field(
        default=None, description="Full vendor address: street, city, state, zip"
    )
    shipping_address: str | None = Field(default=None, description="Shipping street address")
    shipping_city: str | None = Field(default=None, description="Shipping city")
    shipping_state: str | None = Field(default=None, description="Shipping state abbreviation")
    shipping_postal_code: str | None = Field(default=None, description="Shipping ZIP code")
    shipping_address_full: str | None = Field(
        default=None, description="Full shipping address"
    )
    field_notes: str = Field(default="", description="Notes about extraction issues")


class InvoiceExtractionResult(BaseModel):
    document_type: str = Field(description="Document type: invoice, quote, statement, credit_bill, or other")
    vendor_info: VendorInfo
    table_data: TableData
