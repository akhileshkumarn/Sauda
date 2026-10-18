"""Fetch real Indian FMCG products from Open Food Facts and read MRP from pack images with Gemini.

Output: data/products.csv with columns
gtin,name,brand,pack_size,category,mrp_paise,mrp_source,mrp_source_url,image_url

Products whose MRP is not readable on any pack image are dropped (no invented prices).
Product data: Open Food Facts (ODbL). Images CC BY-SA on Open Food Facts.

Usage: uv run python scripts/fetch_products.py [--per-category 5] [--candidates 14]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "sauda_data"))
from sauda_data.products import (
    CSV_COLUMNS,
    OFF_BASE,
    USER_AGENT,
    normalize_pack_size,
)

# SPEC category -> Open Food Facts tags to try (first that yields enough wins)
CATEGORIES: dict[str, list[str]] = {
    "rice": ["en:rices", "en:basmati-rices"],
    "atta": ["en:wheat-flours", "en:flours"],
    "dal": ["en:lentils", "en:pulses", "en:legumes"],
    "sugar": ["en:sugars", "en:granulated-sugars", "en:jaggery"],
    "oil": ["en:vegetable-oils", "en:sunflower-oils", "en:mustard-oils"],
    "tea": ["en:teas", "en:black-teas"],
    "biscuits": ["en:biscuits"],
    "noodles": ["en:instant-noodles", "en:noodles"],
    "salt": ["en:salts", "en:table-salts"],
    "spices": ["en:spices", "en:spice-mixes", "en:masalas"],
    "ghee": ["en:ghee", "en:clarified-butters"],
    "soaps": ["en:soaps", "en:bar-soaps", "en:toilet-soaps"],
}
# names that OFF tags into a category but a kirana would not stock under it
EXCLUDE = {
    "rice": r"khichdi|murmura|kurmura|poha|fried|flakes|puffed",
    "atta": r"horlicks|malt|bournvita|noodle",
    "sugar": r"candy|mazelo|toffee|chocolate",
    "tea": r"instant|premix",
    "spices": r"choc|bakarwadi|namkeen|biscuit",
    "soaps": r"\bvim\b|dish|detergent|bar\b.*wash",
    "noodles": r"sauce",
}
OBF_BASE = "https://world.openbeautyfacts.org"  # soaps live on Open Beauty Facts
BASE_FOR = {"soaps": OBF_BASE}
CACHE = ROOT / "data" / "raw" / "cache"  # gitignored
SEARCH_GAP_S = 6.5  # OFF search is rate limited (~10 req/min)
FIELDS = "code,product_name,product_name_en,brands,quantity,image_front_url,image_url,selected_images,categories_tags"


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


async def off_get(client: httpx.AsyncClient, url: str, params: dict | None = None, tries: int = 5) -> dict | None:
    for i in range(tries):
        try:
            r = await client.get(url, params=params, timeout=40)
            if r.status_code in (429, 502, 503, 504):
                await asyncio.sleep(3 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            await asyncio.sleep(1.5 * (i + 1))
    return None


def full_res(url: str) -> str:
    # front_en.11.400.jpg -> front_en.11.full.jpg (higher resolution for reading small MRP print)
    return re.sub(r"\.(\d+|200|400)\.jpg$", ".full.jpg", url) if url else url


def image_dir(code: str, base: str = OFF_BASE) -> str:
    host = "https://images.openbeautyfacts.org" if base == OBF_BASE else "https://images.openfoodfacts.org"
    path = f"{code[0:3]}/{code[3:6]}/{code[6:9]}/{code[9:]}" if len(code) > 8 else code
    return f"{host}/images/products/{path}"


def candidate_images(p: dict, max_images: int = 6) -> list[str]:
    """Front image first, then every raw uploaded image (back labels carry the MRP), newest first."""
    urls: list[str] = []
    front = p.get("image_front_url") or p.get("image_url")
    if front:
        urls.append(full_res(front))
    raw = sorted((k for k in (p.get("images") or {}) if k.isdigit()), key=int, reverse=True)
    d = image_dir(p["code"], p.get("_base", OFF_BASE))
    for k in raw:
        urls.append(f"{d}/{k}.jpg")
    sel = p.get("selected_images") or {}
    for kind in ("packaging", "ingredients", "nutrition"):
        for u in ((sel.get(kind) or {}).get("display") or {}).values():
            if u and full_res(u) not in urls:
                urls.append(full_res(u))
    return urls[:max_images]


class MrpRead(BaseModel):
    mrp_paise: int
    visible: bool
    confidence: float


PROMPT = (
    "This is a photo of an Indian retail product pack. Indian packs print the Maximum Retail Price as "
    "'MRP Rs. X' or 'MRP ₹X' (often 'incl. of all taxes'). Read the MRP printed on THIS pack. "
    "Return mrp_paise = MRP in paise (rupees × 100, integer). If no MRP is legibly printed, set visible=false "
    "and mrp_paise=0. Do not guess from brand knowledge; confidence reflects legibility of the printed digits. "
    "Ignore 'per unit' or 'per 100 g' prices; return the pack MRP."
)


GEMINI_CACHE: dict[str, dict | None] = {}


async def read_mrp(genai_client, model: str, http: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> MrpRead | None:
    if url in GEMINI_CACHE:
        c = GEMINI_CACHE[url]
        return MrpRead(**c) if c else None
    res = await _read_mrp(genai_client, model, http, url, sem)
    GEMINI_CACHE[url] = res.model_dump() if res else None
    return res


async def _read_mrp(genai_client, model: str, http: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> MrpRead | None:
    from google.genai import types

    async with sem:
        try:
            r = await http.get(url, timeout=40)
            if r.status_code != 200 and url.endswith(".full.jpg"):
                url400 = url.replace(".full.jpg", ".400.jpg")
                r = await http.get(url400, timeout=40)
            if r.status_code != 200:
                return None
            mime = r.headers.get("content-type", "image/jpeg").split(";")[0]
            resp = await genai_client.aio.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=r.content, mime_type=mime), PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=MrpRead, temperature=0
                ),
            )
            return resp.parsed if isinstance(resp.parsed, MrpRead) else MrpRead.model_validate_json(resp.text)
        except Exception as e:  # noqa: BLE001
            print(f"  gemini error {url}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            return None


async def mrp_for_product(genai_client, model, http, p: dict, sem, psem) -> tuple[int, str] | None:
    if "images" not in p:
        async with psem:
            data = await off_get(http, f"{p.get('_base', OFF_BASE)}/api/v2/product/{p['code']}.json",
                                 {"fields": "images,selected_images"})
        prod = (data or {}).get("product") or {}
        p["images"] = prod.get("images") or {}
        p.setdefault("selected_images", prod.get("selected_images"))
    for url in candidate_images(p):
        res = await read_mrp(genai_client, model, http, url, sem)
        if res and res.visible and res.confidence >= 0.7 and 100 <= res.mrp_paise <= 500000:
            return res.mrp_paise, url
    return None


SAL_URL = "https://search.openfoodfacts.org/search"  # search-a-licious; used when /api/v2/search 503s


def _from_sal_hit(h: dict) -> dict:
    """Map a search-a-licious hit to the /api/v2/search product shape."""
    p = {"code": h.get("code", ""), "product_name": h.get("product_name") or "",
         "quantity": h.get("quantity") or "", "images": h.get("images") or {}}
    b = h.get("brands")
    p["brands"] = ", ".join(b) if isinstance(b, list) else (b or "")
    fronts = [k for k in p["images"] if k.startswith("front_")]
    if fronts:
        k = "front_en" if "front_en" in fronts else fronts[0]
        rev = p["images"][k].get("rev")
        if rev:
            p["image_front_url"] = f"{image_dir(p['code'])}/{k}.{rev}.400.jpg"
    return p


async def search_tag(http: httpx.AsyncClient, base: str, tag: str) -> list[dict] | None:
    cf = CACHE / f"search_{base.split('//')[1].split('.')[1]}_{tag.replace(':', '_')}.json"
    if cf.exists():
        return json.loads(cf.read_text())
    prods = None
    data = await off_get(http, f"{base}/api/v2/search",
                         {"countries_tags": "en:india", "categories_tags": tag, "fields": FIELDS,
                          "page_size": 100, "sort_by": "unique_scans_n"}, tries=2)
    if data is not None:
        prods = data.get("products", [])
    elif base == OFF_BASE:
        data = await off_get(http, SAL_URL, {
            "q": f'categories_tags:"{tag}" AND countries_tags:"en:india"', "page_size": 100,
            "fields": "code,product_name,brands,quantity,images"}, tries=3)
        if data is not None:
            prods = [_from_sal_hit(h) for h in data.get("hits", [])]
    if prods is None:
        return None
    cf.write_text(json.dumps(prods))
    return prods


async def search_category(http: httpx.AsyncClient, cat: str, tags: list[str], want: int, seen: set[str]) -> list[dict]:
    out: list[dict] = []
    base = BASE_FOR.get(cat, OFF_BASE)
    for tag in tags:
        prods = await search_tag(http, base, tag)
        for p in prods or []:
            code = p.get("code", "")
            name = (p.get("product_name") or p.get("product_name_en") or "").strip()
            qty = normalize_pack_size(p.get("quantity") or "")
            if not (code.isdigit() and len(code) in (8, 12, 13, 14) and name and qty and p.get("image_front_url")):
                continue
            if code in seen:
                continue
            seen.add(code)
            p["_name"], p["_qty"], p["_base"] = name, qty, base
            out.append(p)
            if len(out) >= want:
                return out
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=5)
    ap.add_argument("--candidates", type=int, default=22)
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--out", default=str(ROOT / "data" / "products.csv"))
    args = ap.parse_args()
    load_env()

    from google import genai

    gclient = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1"),
    )
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    sem = asyncio.Semaphore(args.concurrency)
    psem = asyncio.Semaphore(4)
    CACHE.mkdir(parents=True, exist_ok=True)
    gc = CACHE / "gemini_mrp.json"
    if gc.exists():
        GEMINI_CACHE.update(json.loads(gc.read_text()))
    t0 = time.time()
    seen: set[str] = set()
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as http:
        cands: dict[str, list[dict]] = {}
        for cat, tags in CATEGORIES.items():
            cands[cat] = await search_category(http, cat, tags, args.candidates, seen)
            print(f"search {cat:9s} candidates={len(cands[cat])}  ({time.time()-t0:.0f}s)")

        tasks, keys = [], []
        for cat, ps in cands.items():
            for p in ps:
                tasks.append(mrp_for_product(gclient, model, http, p, sem, psem))
                keys.append((cat, p))
        try:
            results = await asyncio.gather(*tasks)
        finally:
            gc.write_text(json.dumps(GEMINI_CACHE))

    rows, tried, readable = [], Counter(), Counter()
    per_cat = Counter()
    for (cat, p), res in zip(keys, results):
        tried[cat] += 1
        if not res:
            continue
        readable[cat] += 1
        if cat in EXCLUDE and re.search(EXCLUDE[cat], f"{p.get('brands') or ''} {p['_name']}", re.IGNORECASE):
            continue
        if per_cat[cat] >= args.per_category:
            continue
        per_cat[cat] += 1
        mrp, src_url = res
        rows.append({
            "gtin": p["code"],
            "name": p["_name"],
            "brand": (p.get("brands") or "").split(",")[0].strip(),
            "pack_size": p["_qty"],
            "category": cat,
            "mrp_paise": mrp,
            "mrp_source": "pack_image_gemini",
            "mrp_source_url": src_url,
            "image_url": p.get("image_front_url") or "",
        })

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'category':10s} {'tried':>6s} {'readable':>9s} {'kept':>5s}")
    for cat in CATEGORIES:
        print(f"{cat:10s} {tried[cat]:6d} {readable[cat]:9d} {per_cat[cat]:5d}")
    tot_t, tot_r = sum(tried.values()), sum(readable.values())
    print(f"{'TOTAL':10s} {tot_t:6d} {tot_r:9d} {len(rows):5d}   MRP readable rate {tot_r/max(tot_t,1):.0%}")
    print(f"wrote {len(rows)} rows -> {args.out} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
