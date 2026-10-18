"""Purchase history ingest (6.3). Plan B is active: no purchase history, so this is a stub (not run)."""
from __future__ import annotations

from pydantic import BaseModel


class PurchaseLine(BaseModel):
    shop_id: str = ""
    date: str = ""
    gtin: str = ""
    item: str = ""
    qty: float = 0
    unit_price_paise: int = 0
    supplier_name: str = ""
    bill_image_url: str = ""
    extracted_by: str = "gemini"
    confidence: float = 0.0


def extract_bill(image_bytes: bytes, bill_image_url: str = "") -> list[PurchaseLine]:
    """Gemini vision bill -> lines. Not implemented under Plan B (no real shop bills)."""
    raise NotImplementedError("Plan B: no purchase history; seed.py --bills is not available tonight")


def last_paid(shop_id: str, gtin: str) -> int | None:
    """Last paid unit price in paise. Plan B: always None (no purchase history)."""
    return None
