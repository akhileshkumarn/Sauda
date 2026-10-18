"""Format check + manual registry task for identifiers whose official verify page needs a CAPTCHA."""
from __future__ import annotations

import re

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers._common import consent_denied, mode, not_consented
from sauda_verify.providers._registry import manual_task
from sauda_verify.providers.base import ProviderResult


class FormatAndManualProvider:
    name: str
    dims: list[Dim]
    consent_key: str
    attr: str                 # Business attribute holding the identifier
    label: str                # human label, e.g. "Udyam registration number"
    pattern: re.Pattern
    portal_url: str
    portal_name: str
    reviewer_fields: list[str]

    def normalise(self, v: str) -> str:
        return re.sub(r"\s", "", v or "").upper()

    def describe(self, v: str) -> str:
        return ""

    def applicable(self, biz: Business) -> bool:
        return bool((getattr(biz, self.attr) or "").strip())

    def format_result(self, biz: Business) -> ProviderResult:
        v = self.normalise(getattr(biz, self.attr))
        ok = bool(self.pattern.match(v))
        base = dict(source_kind=SourceKind.preliminary_validation, source_name=f"{self.label} format check (offline)",
                    dim=self.dims[0], check_type=f"{self.name}_format",
                    fields=[FieldCompare(field=self.attr, declared=v, observed="valid format" if ok else "invalid format",
                                         match=ok)])
        if not ok:
            return ProviderResult(status=CheckStatus.failed, **base,
                                  summary=f"The {self.label} format is invalid; likely a typo.")
        extra = self.describe(v)
        return ProviderResult(status=CheckStatus.partially_verified, **base, observed={"detail": extra} if extra else {},
                              summary=(f"The {self.label} format looks valid{(' (' + extra + ')') if extra else ''}; "
                                       "not confirmed with the registry."))

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify":
            return []
        if consent_denied(ctx, self.consent_key):
            return [not_consented(self.name, self.dims[0], self.consent_key)]
        out = [self.format_result(biz)]
        # registry-like work never runs on demo fixtures (the seed writes labelled simulated checks instead)
        if out[0].status != CheckStatus.failed and not biz.is_fixture and not (ctx or {}).get("is_fixture"):
            out.append(manual_task(name=self.name, dim=self.dims[0], source_name=self.portal_name,
                                   source_url=self.portal_url, identifier=(self.attr, self.normalise(getattr(biz, self.attr))),
                                   reviewer_fields=self.reviewer_fields,
                                   extra="Uploading the certificate lets it be read and compared automatically"))
        return out
