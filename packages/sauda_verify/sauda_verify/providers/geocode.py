"""Address geocoding (Google Maps Geocoding API) and device-location consistency.

Two separate results:
- address_geocode: the declared address is geocoded (region=in) and the returned locality and postal
  code are compared with the declared city and PIN: match / partial / conflict.
- device_location: with a consented device location (lat, lng, accuracy), the distance to the geocoded
  point (dim=address as the API layer expects; it evidences operational presence only weakly). Within max(250 m, accuracy) is `partially_verified` (device_signal). Location consistency is not
  proof of operation or ownership.

Key: env MAPS_API_KEY (Secret Manager secret `maps-geocoding-key`, restricted to the Geocoding API).
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections.abc import Callable

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers._common import (
    compare_names,
    consent_denied,
    mode,
    not_consented,
)
from sauda_verify.providers.base import ProviderResult

log = logging.getLogger("sauda_verify.geocode")
logging.getLogger("httpx").setLevel(logging.WARNING)  # the key is a query parameter; never log URLs

API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
SOURCE_NAME = "Google Maps Geocoding API"
SOURCE_URL = "https://developers.google.com/maps/documentation/geocoding"
DEVICE_SOURCE = "Device location (owner-consented)"
MIN_RADIUS_M = 250.0
NOT_PROOF = "Location consistency is not proof of operation or ownership."

GeocodeFn = Callable[[str], dict | None]
_cache: dict[str, dict | None] = {}
_lock = threading.Lock()


def address_string(biz: Business) -> str:
    a = biz.address
    return ", ".join(x for x in (a.line, a.city, a.state, a.pin, "India") if x and x.strip())


def google_geocode(address: str, *, timeout: float = 8.0) -> dict | None:
    """Raw call. Returns {lat, lng, locality, sublocality, district, postal_code, state, formatted, location_type,
    partial_match, place_id} or None for zero results. Raises on transport/auth errors."""
    import httpx

    key = os.environ.get("MAPS_API_KEY")
    if not key:
        raise RuntimeError("MAPS_API_KEY not configured")
    r = httpx.get(API_URL, params={"address": address, "region": "in", "components": "country:IN", "key": key},
                  timeout=timeout)
    r.raise_for_status()
    d = r.json()
    status = d.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        raise RuntimeError(f"geocoding status {status}")
    return parse_result(d["results"][0])


def parse_result(res: dict) -> dict:
    comp: dict[str, str] = {}
    for c in res.get("address_components", []):
        for t in c.get("types", []):
            comp.setdefault(t, c.get("long_name", ""))
    loc = res.get("geometry", {}).get("location", {})
    return {
        "lat": loc.get("lat"), "lng": loc.get("lng"),
        "locality": comp.get("locality", ""),
        "sublocality": comp.get("sublocality_level_1") or comp.get("sublocality", ""),
        "district": comp.get("administrative_area_level_3") or comp.get("administrative_area_level_2", ""),
        "state": comp.get("administrative_area_level_1", ""),
        "postal_code": comp.get("postal_code", ""),
        "formatted": res.get("formatted_address", ""),
        "location_type": res.get("geometry", {}).get("location_type", ""),
        "partial_match": bool(res.get("partial_match")),
        "place_id": res.get("place_id"),
    }


def geocode(address: str, fn: GeocodeFn | None = None) -> dict | None:
    """Cached per process (same address string -> one API call)."""
    if fn is not None:
        return fn(address)
    with _lock:
        if address in _cache:
            return _cache[address]
    g = google_geocode(address)
    with _lock:
        if len(_cache) >= 1000:
            _cache.clear()
        _cache[address] = g
    return g


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _city_match(city: str, g: dict) -> bool | None:
    if not city:
        return None
    names = [g.get("locality"), g.get("sublocality"), g.get("district")]
    return any(n and compare_names(city, n) in ("exact", "near") for n in names) or \
        any(n and city.strip().lower() in n.lower() for n in names)


def compare_address(biz: Business, g: dict | None) -> ProviderResult:
    base = dict(source_kind=SourceKind.authorised_provider, source_name=SOURCE_NAME, source_url=SOURCE_URL,
                dim=Dim.address, check_type="address_geocode")
    if g is None:
        return ProviderResult(status=CheckStatus.inconclusive, **base, observed={"outcome": "no_result"},
                              summary="Google Maps could not find the declared address. This is not a negative "
                                      "finding; the address may simply be unmapped.")
    pin = re.sub(r"\D", "", biz.address.pin or "")
    pin_ok = (g["postal_code"] == pin) if (pin and g["postal_code"]) else None
    city_ok = _city_match(biz.address.city, g)
    fields = [FieldCompare(field="locality", declared=biz.address.city or None,
                           observed=g["locality"] or g["sublocality"] or None, match=city_ok),
              FieldCompare(field="postal_code", declared=pin or None, observed=g["postal_code"] or None, match=pin_ok)]
    observed = {k: g.get(k) for k in ("lat", "lng", "locality", "postal_code", "state", "location_type",
                                      "partial_match", "formatted")}
    precise = g.get("location_type") in ("ROOFTOP", "RANGE_INTERPOLATED") and not g.get("partial_match")
    if pin_ok is False and city_ok is False:
        outcome, status = "conflict", CheckStatus.conflict
        summary = (f"Google Maps places the declared address in {g['locality'] or 'another area'} "
                   f"({g['postal_code'] or 'no PIN'}), which matches neither the declared city nor the PIN.")
    elif pin_ok is False:
        outcome, status = "conflict", CheckStatus.conflict
        summary = (f"Google Maps resolves the address to PIN {g['postal_code']}, not the declared PIN {pin}.")
    elif pin_ok and city_ok:
        outcome, status = "match", CheckStatus.partially_verified
        summary = ("Google Maps resolves the declared address to the declared locality and PIN"
                   + ("" if precise else " (approximate location only)")
                   + ". This shows the address is real and consistent, not that the business operates there.")
    else:
        outcome, status = "partial", CheckStatus.inconclusive
        summary = ("Google Maps resolves the address, but only partly matches the declared locality/PIN "
                   "(one of them is missing or different). A reviewer may want to look at it.")
    observed["outcome"] = outcome
    return ProviderResult(status=status, fields=fields, observed=observed, summary=summary, **base)


def compare_device(g: dict, lat: float, lng: float, accuracy_m: float | None) -> ProviderResult:
    acc = float(accuracy_m or 0)
    radius = max(MIN_RADIUS_M, acc)
    d = haversine_m(lat, lng, g["lat"], g["lng"])
    base = dict(source_kind=SourceKind.device_signal, source_name=DEVICE_SOURCE, dim=Dim.address,
                check_type="device_location")
    observed = {"distance_m": round(d), "radius_m": round(radius), "accuracy_m": round(acc) if acc else None}
    fields = [FieldCompare(field="distance_to_declared_address_m", declared=f"<= {round(radius)}",
                           observed=str(round(d)), match=d <= radius)]
    if acc > 2000:
        return ProviderResult(status=CheckStatus.inconclusive, fields=fields, observed=observed, **base,
                              summary=f"The device location is too imprecise (±{round(acc)} m) to compare. {NOT_PROOF}")
    if d <= radius:
        return ProviderResult(status=CheckStatus.partially_verified, fields=fields, observed=observed, **base,
                              summary=(f"The device was about {round(d)} m from the geocoded address (within "
                                       f"{round(radius)} m). {NOT_PROOF}"))
    return ProviderResult(status=CheckStatus.inconclusive, fields=fields, observed=observed, **base,
                          summary=(f"The device was about {round(d)} m from the geocoded address, outside "
                                   f"{round(radius)} m. The owner may simply not have been at the shop; this is "
                                   f"not a negative finding. {NOT_PROOF}"))


def _unavailable(reason: str, m: str = "verify") -> ProviderResult:
    if m == "location":
        return ProviderResult(status=CheckStatus.inconclusive, source_kind=SourceKind.device_signal, available=False,
                              source_name=DEVICE_SOURCE, dim=Dim.address, check_type="device_location",
                              summary=f"The device location could not be compared ({reason}). {NOT_PROOF}")
    return ProviderResult(status=CheckStatus.inconclusive, source_kind=SourceKind.authorised_provider, available=False,
                          source_name=SOURCE_NAME, source_url=SOURCE_URL, dim=Dim.address, check_type="address_geocode",
                          summary=f"Address geocoding was not run ({reason}).")


def device_location_check(biz: Business, lat: float, lng: float, accuracy_m: float | None,
                          geocode_fn: GeocodeFn | None = None) -> list[ProviderResult]:
    """For POST /tn/businesses/{bid}/location. Returns [address_geocode, device_location] (device row only
    when the address geocodes)."""
    try:
        g = geocode(address_string(biz), geocode_fn)
    except Exception as e:  # noqa: BLE001
        log.warning("geocode failed: %s", type(e).__name__)
        return [_unavailable("geocoding service unavailable")]
    out = [compare_address(biz, g)]
    if g is not None and g.get("lat") is not None:
        out.append(compare_device(g, lat, lng, accuracy_m))
    return out


class GeocodeProvider:
    """mode "verify": declared-address geocode (address dim). mode "location": device distance (address dim,
    device_signal) against the geocoded address, from ctx["location"] = {lat, lng, accuracy_m, consent}."""
    name = "geocode"
    dims = [Dim.address]
    consent_key = "address"

    def __init__(self, geocode_fn: GeocodeFn | None = None):
        self.geocode_fn = geocode_fn

    def applicable(self, biz: Business) -> bool:
        a = biz.address
        return bool((a.line or a.city) and (a.pin or a.state))

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        m = mode(ctx)
        if m not in ("verify", "location"):
            return []
        if m == "verify" and consent_denied(ctx, self.consent_key):
            return [not_consented(self.name, Dim.address, self.consent_key)]
        loc = (ctx or {}).get("location") or {}
        if m == "location" and (not loc or loc.get("consent") is False):
            return [not_consented("device_location", Dim.address, "location")]
        fn = (ctx or {}).get("geocode_fn") or self.geocode_fn
        if fn is None and not os.environ.get("MAPS_API_KEY"):
            return [_unavailable("no Maps API key configured", m)]
        try:
            g = geocode(address_string(biz), fn)
        except Exception as e:  # noqa: BLE001
            log.warning("geocode failed: %s", type(e).__name__)
            return [_unavailable("geocoding service unavailable", m)]
        if m == "verify":
            return [compare_address(biz, g)]
        if g is None or g.get("lat") is None:
            return [ProviderResult(status=CheckStatus.inconclusive, source_kind=SourceKind.device_signal,
                                   source_name=DEVICE_SOURCE, dim=Dim.address, check_type="device_location",
                                   summary="The declared address could not be geocoded, so the device location "
                                           f"could not be compared. {NOT_PROOF}")]
        return [compare_device(g, float(loc["lat"]), float(loc["lng"]), loc.get("accuracy_m"))]
