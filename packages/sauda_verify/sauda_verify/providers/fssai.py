"""FSSAI licence/registration: offline format check + guided manual check on FoSCoS (no public API).
The licence can be uploaded and read by documents.py."""
from __future__ import annotations

import re

from sauda_verify.models import Business, Dim
from sauda_verify.providers._formatreg import FormatAndManualProvider

FOOD_HINTS = ("food", "grocery", "kirana", "rice", "oil", "edible", "dal", "atta", "flour", "spice", "sugar",
              "snack", "beverage", "dairy", "staple", "fmcg", "general store")


class FssaiProvider(FormatAndManualProvider):
    name = "fssai"
    dims = [Dim.product_compliance]
    consent_key = "fssai"
    attr = "fssai"
    label = "FSSAI licence/registration number"
    pattern = re.compile(r"^[12]\d{13}$")
    portal_url = "https://foscos.fssai.gov.in/"
    portal_name = "FSSAI FoSCoS FBO search (manual)"
    reviewer_fields = ["fbo_name", "licence_or_registration", "kind_of_business", "premises_address",
                       "valid_upto", "status"]

    def normalise(self, v: str) -> str:
        return re.sub(r"\D", "", v or "")

    def describe(self, v: str) -> str:
        return "licence" if v[0] == "1" else "registration"

    def applicable(self, biz: Business) -> bool:
        return bool((biz.fssai or "").strip())


def deals_in_food(biz: Business) -> bool:
    hay = " ".join([biz.category or "", *biz.products, biz.display_name]).lower()
    return any(h in hay for h in FOOD_HINTS)
