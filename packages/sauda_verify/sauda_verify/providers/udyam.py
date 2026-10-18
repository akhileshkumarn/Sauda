"""Udyam (MSME) registration: offline format check + guided manual check on the official verify page
(CAPTCHA, no public API). The certificate can be uploaded and read by documents.py."""
from __future__ import annotations

import re

from sauda_verify.models import Dim
from sauda_verify.providers._formatreg import FormatAndManualProvider


class UdyamProvider(FormatAndManualProvider):
    name = "udyam"
    dims = [Dim.registration]
    consent_key = "udyam"
    attr = "udyam"
    label = "Udyam registration number"
    pattern = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")
    portal_url = "https://udyamregistration.gov.in/Udyam_Verify.aspx"
    portal_name = "Udyam Registration portal, Verify Udyam Registration Number (manual)"
    reviewer_fields = ["enterprise_name", "type_of_enterprise", "major_activity", "date_of_registration",
                       "state", "district"]

    def describe(self, v: str) -> str:
        return f"state code {v[6:8]}, district {v[9:11]}"
