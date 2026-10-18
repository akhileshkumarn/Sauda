"""Provider interface. Adapters implement Provider and return ProviderResult rows;
the API layer turns them into Check records. Providers never decide the overall
category: that is policy.py's job."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind


class ProviderResult(BaseModel):
    status: CheckStatus
    source_kind: SourceKind
    source_name: str
    source_url: str | None = None
    summary: str
    fields: list[FieldCompare] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)
    provider_ref: str | None = None
    available: bool = True
    # Optional extras (compatible with the agreed shape): which dimension this row
    # evidences when a provider covers several dims, and a finer check type label.
    # When omitted the caller uses provider.dims[0] and provider.name.
    dim: Dim | None = None
    check_type: str | None = None
    expires_at: str | None = None


@runtime_checkable
class Provider(Protocol):
    name: str
    dims: list[Dim]

    def applicable(self, biz: Business) -> bool: ...

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]: ...
