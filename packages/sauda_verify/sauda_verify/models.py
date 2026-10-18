"""Data models for the Sauda Trust Network.

Everything here is plain data. Status decisions live in policy.py and are
deterministic: no probabilities, no hidden scores.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Dim(StrEnum):
    identity = "identity"
    registration = "registration"
    address = "address"
    operational = "operational"
    representative = "representative"
    product_compliance = "product_compliance"
    distribution_authority = "distribution_authority"
    trading_references = "trading_references"
    payment_details = "payment_details"
    operational_capability = "operational_capability"


class CheckStatus(StrEnum):
    verified = "verified"
    partially_verified = "partially_verified"
    self_declared = "self_declared"
    pending = "pending"
    inconclusive = "inconclusive"
    stale = "stale"
    conflict = "conflict"
    failed = "failed"
    not_applicable = "not_applicable"


class SourceKind(StrEnum):
    official_registry = "official_registry"
    authorised_provider = "authorised_provider"
    uploaded_evidence = "uploaded_evidence"
    human_review = "human_review"
    self_declared = "self_declared"
    preliminary_validation = "preliminary_validation"
    simulated_fixture = "simulated_fixture"
    device_signal = "device_signal"


class Category(StrEnum):
    identity_confirmed = "identity_confirmed"
    evidence_reviewed = "evidence_reviewed"
    ready_for_counterparty_review = "ready_for_counterparty_review"
    additional_review_required = "additional_review_required"
    verification_unsuccessful = "verification_unsuccessful"


class AuthorityStatus(StrEnum):
    unknown = "unknown"
    self_declared = "self_declared"
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class RelState(StrEnum):
    requested = "requested"  # a buyer asked to connect from supplier discovery
    invited = "invited"
    accepted = "accepted"
    onboarding = "onboarding"
    under_review = "under_review"
    approved_for_trading = "approved_for_trading"
    declined = "declined"
    paused = "paused"


class FieldCompare(BaseModel):
    field: str
    declared: str | None = None
    observed: str | None = None
    match: bool | None = None


class Address(BaseModel):
    line: str = ""
    city: str = ""
    state: str = ""
    pin: str = ""


class Geo(BaseModel):
    lat: float
    lng: float
    accuracy_m: float | None = None
    captured_at: str | None = None
    consent: bool = True


class Contact(BaseModel):
    phone_masked: str | None = None
    email_masked: str | None = None


class Representative(BaseModel):
    name: str = ""
    role: str = ""
    authority_status: AuthorityStatus = AuthorityStatus.unknown


class Business(BaseModel):
    bid: str
    roles: list[Literal["buyer", "seller"]] = Field(default_factory=list)
    display_name: str
    legal_name: str | None = None
    constitution: str | None = None
    category: str | None = None
    products: list[str] = Field(default_factory=list)
    gstin: str | None = None
    udyam: str | None = None
    fssai: str | None = None
    cin_llpin: str | None = None
    address: Address = Field(default_factory=Address)
    geo: Geo | None = None
    contact: Contact = Field(default_factory=Contact)
    representative: Representative = Field(default_factory=Representative)
    brand_claims: list[str] = Field(default_factory=list)
    owner_uid: str = ""
    members: list[str] = Field(default_factory=list)
    is_fixture: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    version: int = 1


class ReviewerStamp(BaseModel):
    uid_hash: str
    decision: str
    reason: str
    at: str


class Check(BaseModel):
    check_id: str
    business_id: str
    case_id: str
    dim: Dim
    check_type: str
    source_kind: SourceKind
    source_name: str
    source_url: str | None = None
    status: CheckStatus
    summary: str
    fields: list[FieldCompare] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    checked_at: str
    expires_at: str | None = None
    provider_ref: str | None = None
    available: bool = True
    observed: dict[str, Any] = Field(default_factory=dict)
    reviewer: ReviewerStamp | None = None


class DimensionSummary(BaseModel):
    dim: Dim
    status: CheckStatus
    source_kind: SourceKind | None = None
    summary: str
    checked_at: str | None = None


class Summary(BaseModel):
    category: Category
    category_label: str
    dimensions: list[DimensionSummary]
    outstanding: list[str]
    limitations: list[str]
    next_step: str
    review_reasons: list[str] = Field(default_factory=list)


class Readiness(BaseModel):
    tier: str
    ready: bool
    missing: list[str]
    requires_human_review: bool = False
    note: str = ""
