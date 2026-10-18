"""Verification providers.

REGISTRY is ordered: offline checks first, then official data, then authorised/manual registry checks,
then contact/payment, then the evidence readers. Callers do, for each provider p:

    if p.applicable(biz): rows = p.run(biz, ctx)

ctx:
  mode       "verify" (default) | "evidence" | "location"; a provider returns [] for modes that are not its own
  consents   dict[str, bool]; a check whose consent key is present and False returns a pending "not consented" row
             (keys: gst, address, mca, udyam, fssai)
  is_fixture bool; registry-like providers never run on fixtures
  now        ISO timestamp
  evidence   (mode "evidence") {eid, type, mime, size, data: bytes}; providers "documents" and "photo"
  location   (mode "location") {lat, lng, accuracy_m, captured_at, consent}; provider "geocode"
Test hooks (optional): geocode_fn, gemini_extract, screen.

Which run in which mode:
  verify:   gstin_format, pincode_directory, geocode (declared address), mca, gst_registry, udyam, fssai,
            contact, bank
  evidence: documents (certificates, letters), photo (storefront)
  location: geocode (device distance vs the geocoded address)

Simulated fixtures: `simulated.SimulatedRegistryProvider` / `simulated.fixture_results(biz)` (fixtures only,
source_kind simulated_fixture). Not in REGISTRY; the seed calls it directly.
"""
from __future__ import annotations

from sauda_verify.providers.bank import BankProvider
from sauda_verify.providers.base import Provider, ProviderResult
from sauda_verify.providers.contact import ContactProvider
from sauda_verify.providers.documents import DocumentsProvider
from sauda_verify.providers.fssai import FssaiProvider
from sauda_verify.providers.geocode import GeocodeProvider
from sauda_verify.providers.gst_registry import GstRegistryProvider
from sauda_verify.providers.gstin import GstinFormatProvider
from sauda_verify.providers.mca import McaProvider
from sauda_verify.providers.photo import PhotoProvider
from sauda_verify.providers.pincode import PincodeProvider
from sauda_verify.providers.simulated import SimulatedRegistryProvider
from sauda_verify.providers.udyam import UdyamProvider

REGISTRY: list[Provider] = [
    GstinFormatProvider(),   # gstin declared
    PincodeProvider(),       # PIN declared
    GeocodeProvider(),       # address declared (verify: address; location: device distance)
    McaProvider(),           # CIN/LLPIN declared, not fixture
    GstRegistryProvider(),   # GSTIN declared, not fixture
    UdyamProvider(),         # Udyam number declared
    FssaiProvider(),         # FSSAI number declared
    ContactProvider(),       # always (representative authority; contact OTP if a contact is declared)
    BankProvider(),          # sellers only
    DocumentsProvider(),     # evidence mode only
    PhotoProvider(),         # evidence mode only (storefront photo)
]

SIMULATED = SimulatedRegistryProvider()


def get(name: str) -> Provider | None:
    return next((p for p in REGISTRY if p.name == name), None)


__all__ = ["REGISTRY", "SIMULATED", "Provider", "ProviderResult", "get"]
