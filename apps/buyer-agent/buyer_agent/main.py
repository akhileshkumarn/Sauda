"""Sauda buyer-agent service (S2): FastAPI routes per SPEC appendix API contracts."""
from __future__ import annotations

from .services.demand import display_name as _display_name
import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import store, trust
from .deps import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("buyer_agent")

app = FastAPI(title="Sauda buyer agent", version="0.1.0")
_origins = [o.strip() for o in settings().owner_app_origin.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])


# ---------------------------------------------------------------- auth
_fb_app = None


def _verify_firebase(token: str) -> str:
    global _fb_app
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if _fb_app is None:
        try:
            _fb_app = firebase_admin.get_app()
        except ValueError:
            _fb_app = firebase_admin.initialize_app(options={"projectId": settings().project})
    return fb_auth.verify_id_token(token, app=_fb_app)["uid"]


def owner_uid(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    # Operator token (server-side secret, never shipped to the browser in firebase mode): e2e and reset scripts.
    if settings().demo_owner_token and token == settings().demo_owner_token:
        return "demo-owner"
    if settings().auth_mode == "demo":
        raise HTTPException(401, "invalid demo token")
    try:
        return _verify_firebase(token)
    except Exception:
        raise HTTPException(401, "invalid Firebase ID token")


def check_shop_owner(shop_id: str, uid: str) -> dict:
    shop = store.shop(shop_id)
    owner = shop.get("owner_uid")
    if uid == "demo-owner" and shop_id == settings().demo_shop_id:
        return shop
    if owner and owner == uid:
        return shop
    if not owner and shop_id == settings().demo_shop_id:
        return shop  # demo shop not yet claimed
    raise HTTPException(403, "not the owner of this shop")


def check_record_owner(shop_id: str, record_owner: str | None, uid: str) -> None:
    """Shop ownership AND record ownership: on the shared demo shop every signed-in user passes the shop
    check, so negotiations, mandates, confirmations and orders are also bound to the uid that created them."""
    check_shop_owner(shop_id, uid)
    if record_owner and record_owner != uid:
        raise HTTPException(403, "this belongs to another owner")


def check_negotiation_owner(nid: str, uid: str) -> dict:
    n = store.negotiation(nid)
    if not n:
        raise HTTPException(404, "negotiation not found")
    check_record_owner(n["shop_id"], n.get("owner_uid"), uid)
    return n


def check_order_owner(order_id: str, uid: str) -> dict:
    o = store.order(order_id)
    if not o:
        raise HTTPException(404, "order not found")
    owner = o.get("owner_uid") or (store.negotiation(o.get("negotiation_id", "")) or {}).get("owner_uid")
    check_record_owner(o["shop_id"], owner, uid)
    return o


_owner_hits: dict[str, deque] = defaultdict(deque)
OWNER_CALLS_PER_MIN = 20


def owner_rate_limit(uid: str, what: str) -> None:
    """Per-owner cap on model-backed routes (any signed-in Google account can use the demo shop)."""
    hits, now = _owner_hits[f"{what}:{uid}"], time.time()
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= OWNER_CALLS_PER_MIN:
        raise HTTPException(429, f"{what}: {OWNER_CALLS_PER_MIN} calls per minute")
    hits.append(now)


FINISHED = ("ordered", "cancelled", "failed")
SHOP_LOCK_MIN = 15


def claim_shop(shop_id: str, uid: str, shop: dict) -> None:
    """One active negotiation per shop. Another owner's unfinished negotiation blocks (409) unless it has had
    no activity for 15 minutes, in which case it is released and this owner starts fresh."""
    from datetime import timedelta

    nid = shop.get("active_negotiation_id")
    n = store.negotiation(nid) if nid else None
    if not n or n.get("status") in FINISHED or not n.get("owner_uid") or n["owner_uid"] == uid:
        return
    last = n.get("updated_at") or n.get("started_at") or ""
    if last and last < store.iso(store.now() - timedelta(minutes=SHOP_LOCK_MIN)):
        store.update_shop(shop_id, active_negotiation_id=None)
        return
    raise HTTPException(409, "Another owner is negotiating for this shop right now; try again in a minute")


def judge_negotiation(nid: str) -> None:
    demo = settings().demo_shop_id
    if nid == f"attack-{demo}":
        return
    n = store.negotiation(nid)
    if not n or n.get("shop_id") != demo:
        raise HTTPException(404, "only the demo shop is public")


# ---------------------------------------------------------------- models
class ChatIn(BaseModel):
    shop_id: str
    message: str = Field(max_length=4000)
    preferred_supplier_id: str | None = None
    session_id: str | None = None
    mandate_id: str | None = None


class MandateIn(BaseModel):
    kind: str = "intent"
    body: dict
    negotiation_id: str | None = None


class ConfirmIn(BaseModel):
    confirmation_id: str
    approved: bool


class ProofIn(BaseModel):
    utr: str
    amount_paise: int
    payee_vpa: str | None = None


class AttackIn(BaseModel):
    message: str = Field(max_length=4000)
    supplier_id: str = "quickstock"


class VerifyIn(BaseModel):
    events: list[dict]


# ---------------------------------------------------------------- routes
@app.get("/health")
def health():
    return {"status": "ok", "service": "buyer-agent", "auth_mode": settings().auth_mode, "agent_mode": settings().agent_mode,
            "model": settings().gemini_model, "suppliers": settings().supplier_urls}


@app.post("/chat")
async def chat(body: ChatIn, uid: str = Depends(owner_uid)):
    claim_shop(body.shop_id, uid, check_shop_owner(body.shop_id, uid))
    owner_rate_limit(uid, "chat")
    from .services import chat as chat_svc

    async def gen():
        async for ev in chat_svc.stream(body.shop_id, uid, body.message, body.session_id, body.preferred_supplier_id, body.mandate_id):
            yield {"event": ev["event"], "data": json.dumps(ev["data"], default=str, ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=10)


@app.post("/mandates")
async def create_mandate(body: MandateIn, uid: str = Depends(owner_uid)):
    if body.kind != "intent":
        raise HTTPException(400, "only intent mandates are signed through this route")
    b = dict(body.body)
    shop_id = b.get("shop_id")
    if not shop_id:
        raise HTTPException(400, "body.shop_id required")
    shop = check_shop_owner(shop_id, uid)
    claim_shop(shop_id, uid, shop)
    if not isinstance(b.get("allowed_supplier_ids"), list) or len(b["allowed_supplier_ids"]) > 3:
        raise HTTPException(422, "allowed_supplier_ids: at most 3 suppliers per mandate")
    from .services import demand

    b["autonomy_tier"] = 2  # every order needs the owner's approval in this build (forced server-side)
    try:
        await asyncio.to_thread(demand.validate_intent, b, lambda sid: trust.supplier(sid) is not None)
    except demand.MandateInvalid as e:
        raise HTTPException(422, str(e))
    cap = shop.get("monthly_purchase_paise")
    if cap and int(b["budget_paise"]) > 2 * int(cap):
        raise HTTPException(422, "budget exceeds 2x monthly purchase volume")
    b["owner_uid"] = uid
    b.pop("mandate_id", None)
    nid = body.negotiation_id or shop.get("active_negotiation_id")
    n = store.negotiation(nid) if nid else None
    # only this owner's own, still-unsigned negotiation on this shop may receive the mandate
    if (not n or n.get("status") not in ("created",) or n.get("shop_id") != shop_id
            or (n.get("owner_uid") and n["owner_uid"] != uid) or n.get("intent_mandate_id")):
        n = store.create_negotiation(shop_id, uid, draft=(n or {}).get("draft") if n and n.get("shop_id") == shop_id
                                     and n.get("owner_uid") in (None, uid) else None)
        nid = n["negotiation_id"]
    try:
        m = await asyncio.to_thread(trust.create_mandate, "intent", b, uid)
    except Exception as e:
        log.exception("mandate signing failed")
        raise HTTPException(400, f"mandate rejected: {type(e).__name__}")
    store.update_negotiation(nid, intent_mandate_id=m.mandate_id, owner_uid=uid)
    store.update_shop(shop_id, active_negotiation_id=nid)
    try:  # keep a restock session that prepared this negotiation linked (never blocks signing)
        from .services import sessions
        await asyncio.to_thread(sessions.on_mandate_signed, body.negotiation_id, nid, m.mandate_id, uid)
    except Exception:
        log.exception("restock session link failed")
    await asyncio.to_thread(trust.ledger_append, nid, "mandate.signed", "owner",
                            {"mandate_id": m.mandate_id, "kind": "intent", "body_hash": m.body_hash,
                             "kms_key_version": m.kms_key_version, "body": m.body})
    return {"mandate_id": m.mandate_id, "body_hash": m.body_hash, "signature": m.signature,
            "kms_key_version": m.kms_key_version, "negotiation_id": nid, "status": m.status}


@app.get("/mandates/{mandate_id}")
def get_mandate(mandate_id: str, uid: str = Depends(owner_uid)):
    m = trust.get_mandate(mandate_id)
    if not m:
        raise HTTPException(404, "mandate not found")
    check_record_owner(m.shop_id, m.owner_uid, uid)
    return {**m.model_dump(), "signature_valid": m.signature_valid()}


@app.post("/mandates/{mandate_id}/revoke")
def revoke_mandate(mandate_id: str, uid: str = Depends(owner_uid)):
    m = trust.get_mandate(mandate_id)
    if not m:
        raise HTTPException(404, "mandate not found")
    check_record_owner(m.shop_id, m.owner_uid, uid)
    trust.mark_mandate(mandate_id, "revoked")
    for n in store.negotiations_for_shop(m.shop_id):
        if n.get("intent_mandate_id") == mandate_id:
            trust.ledger_append(n["negotiation_id"], "mandate.revoked", "owner", {"mandate_id": mandate_id})
            if n.get("status") not in ("ordered", "cancelled", "failed"):
                store.update_negotiation(n["negotiation_id"], status="cancelled", ended_at=store.iso())
    return {"status": "revoked", "mandate_id": mandate_id}


@app.post("/confirm")
async def post_confirm(body: ConfirmIn, uid: str = Depends(owner_uid)):
    from .services import confirm

    c = store.confirmation(body.confirmation_id)
    if not c:
        raise HTTPException(404, "confirmation not found")
    check_record_owner(c["shop_id"], c.get("owner_uid"), uid)
    try:
        return await confirm.answer(body.confirmation_id, uid, body.approved)
    except confirm.ConfirmError as e:
        raise HTTPException(e.status, {"code": e.code, "message": e.message})


@app.get("/confirm/{confirmation_id}")
def get_confirm(confirmation_id: str, uid: str = Depends(owner_uid)):
    from .services import confirm

    try:
        v = confirm.view(confirmation_id)
    except confirm.ConfirmError as e:
        raise HTTPException(e.status, e.message)
    check_record_owner(v["confirmation"]["shop_id"], v["confirmation"].get("owner_uid"), uid)
    return v


@app.get("/negotiations/{nid}")
def get_negotiation(nid: str, uid: str = Depends(owner_uid)):
    n = check_negotiation_owner(nid, uid)
    cart = store.cart_draft(n["cart_draft_id"]) if n.get("cart_draft_id") else None
    return {"negotiation": n, "cart": cart, "orders": store.orders_for(nid)}


@app.get("/orders/{order_id}")
def get_order(order_id: str, uid: str = Depends(owner_uid)):
    from .services import orders

    o = check_order_owner(order_id, uid)
    return orders.payment_view(o)


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, uid: str = Depends(owner_uid)):
    from .services import orders

    check_order_owner(order_id, uid)
    return orders.cancel(order_id)


@app.post("/payments/{order_id}/proof")
def payment_proof(order_id: str, body: ProofIn, uid: str = Depends(owner_uid)):
    from .services import orders

    check_order_owner(order_id, uid)
    return orders.submit_proof(order_id, body.utr, body.amount_paise, body.payee_vpa)


# ---------------------------------------------------------------- judge routes (demo shop only)
@app.get("/verify/{negotiation_id}")
def verify(negotiation_id: str):
    judge_negotiation(negotiation_id)
    checks = trust.verify_chain(negotiation_id)
    d = checks.to_dict()
    d["negotiation_id"] = negotiation_id
    return d


VERIFY_MAX_EVENTS = 2000
VERIFY_MAX_BYTES = 1_000_000


@app.post("/verify")
async def verify_copy(request: Request):
    """Tamper demo: verify an edited client-side copy of a chain (never touches the stored ledger).
    At most 2000 events / 1 MB (413 otherwise); the body is read with a cap, never buffered unbounded."""
    from pydantic import ValidationError

    if int(request.headers.get("content-length") or 0) > VERIFY_MAX_BYTES:
        raise HTTPException(413, "verify: body over 1 MB")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > VERIFY_MAX_BYTES:
            raise HTTPException(413, "verify: body over 1 MB")
    try:
        body = VerifyIn.model_validate_json(bytes(raw))
    except ValidationError as e:
        raise HTTPException(422, f"events must be a list of objects ({e.error_count()} errors)")
    if len(body.events) > VERIFY_MAX_EVENTS:
        raise HTTPException(413, f"verify: at most {VERIFY_MAX_EVENTS} events")
    try:
        return await asyncio.to_thread(lambda: trust.verify_chain(body.events).to_dict())
    except (TypeError, ValueError, AttributeError) as e:
        raise HTTPException(400, f"malformed events: {type(e).__name__}")


@app.get("/events")
def events(negotiation: str = Query(...)):
    judge_negotiation(negotiation)
    n = store.negotiation(negotiation) or {}
    from sauda_trust.registry import mask_payload

    # events are returned verbatim (payees were masked when written, so hashes still verify); offers are not
    # hashed and are masked here
    return {"negotiation_id": negotiation, "status": n.get("status"), "events": store.ledger_events(negotiation),
            "offers": mask_payload(store.offers_for(negotiation)) if n else []}


@app.get("/pubkey", response_class=PlainTextResponse)
def pubkey():
    from sauda_trust import kms

    return kms.get_signer().public_key_pem()


@app.get("/metrics/{shop_id}")
def metrics(shop_id: str):
    if shop_id != settings().demo_shop_id:
        raise HTTPException(404, "only the demo shop is public")
    from .services import metrics as m

    return m.compute(shop_id)


_attack_hits: dict[str, deque] = defaultdict(deque)
VPA_RE = re.compile(r"\b[\w.\-]{2,64}@[a-zA-Z]{2,32}\b")
ADV_RE = re.compile(r"(\d{1,3})\s*%\s*(?:of\s+the\s+\w+\s+)?(?:advance|upfront|prepay)", re.I)


def _attack_mandate():
    demo = settings().demo_shop_id
    shop = store.shop(demo)
    mid = shop.get("attack_mandate_id")
    m = trust.get_mandate(mid) if mid else None
    if m and m.status == "active":
        return m
    prods = list(store.products().values())[:5]
    body = {"kind": "intent", "shop_id": demo, "budget_paise": 2500000, "allowed_supplier_ids": ["metro", "sharma", "quickstock"],
            "lines": [{"gtin": p["gtin"], "qty": 10, "ceiling_paise": int(p.get("mrp_paise") or 10000), "ceiling_source": "mrp"} for p in prods],
            "max_advance_pct": 20, "deliver_by": "2026-11-07", "autonomy_tier": 2, "expires_at": "2026-12-31T23:59:00+05:30",
            "purpose": "attack-box fixed demo mandate"}
    m = trust.create_mandate("intent", body, "attack-box")
    store.update_shop(demo, attack_mandate_id=m.mandate_id)
    return m


ATTACK_PER_IP_MIN = 10
ATTACK_GLOBAL_MIN = 60
ATTACK_MSG_MAX = 500


def attack_rate_limit(request: Request) -> None:
    """10/min per client and 60/min overall. The client is the LAST X-Forwarded-For hop: Cloud Run appends the
    address it saw, while earlier entries are whatever the caller chose to send."""
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[-1].strip() if fwd else (request.client.host if request.client else "?")
    now = time.time()
    for key, cap in ((f"ip:{ip}", ATTACK_PER_IP_MIN), ("*", ATTACK_GLOBAL_MIN)):
        hits = _attack_hits[key]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= cap:
            raise HTTPException(429, f"attack box: {cap} calls per minute" + (" (all visitors)" if key == "*" else ""))
    _attack_hits[f"ip:{ip}"].append(now)
    _attack_hits["*"].append(now)


@app.post("/attack")
def attack(body: AttackIn, request: Request):
    attack_rate_limit(request)
    demo = settings().demo_shop_id
    chain = f"attack-{demo}"
    m = _attack_mandate()
    verdict = trust.screen(body.message, "inbound", max_advance_pct=float(m.body["max_advance_pct"]))
    vd = trust.verdict_dict(verdict)
    adv = max([float(x) for x in ADV_RE.findall(body.message)] or [0.0])
    vpa = (VPA_RE.findall(body.message) or [None])[0]
    rec = trust.supplier(body.supplier_id)
    fps = {body.supplier_id: rec.fingerprint} if rec else {}
    ctx = trust.build_ctx(m, card_fingerprints=fps, guard_verdicts={body.supplier_id: vd})
    # The attack box tests the message itself: a quarantine left by a demo negotiation must not make every
    # message (even a benign one) fail R2. Fingerprint and payee checks still run against the registry.
    if body.supplier_id in ctx.suppliers:
        ctx.suppliers[body.supplier_id] = {**dict(ctx.suppliers[body.supplier_id]), "status": "allowlisted"}
    action = {"kind": "offer", "negotiation_id": chain, "supplier_id": body.supplier_id, "lines": [],
              "advance_pct": adv, "payout_vpa": vpa, "delivery_days": 2}
    from sauda_trust.policy_gate import evaluate

    rep = evaluate(action, m.intent(), ctx, rules=["R2", "R5", "R8", "R9", "R12"])
    blocked = verdict.blocked or rep.verdict == "DENY"
    ev = trust.ledger_append(chain, "attack.tested", "judge", {"message": body.message[:ATTACK_MSG_MAX], "supplier_id": body.supplier_id,
                                                             "extracted": {"advance_pct": adv, "payout_vpa": vpa},
                                                             "guard_verdict": vd, "gate_report": rep.to_dict(), "blocked": blocked})
    from sauda_trust.registry import mask_payload

    return mask_payload({"guard_verdict": vd, "gate_report": rep.to_dict(), "ledger_seq": getattr(ev, "seq", None),
                         "blocked": blocked, "negotiation_id": chain})


@app.get("/attack/scenarios")
def attack_scenarios():
    from .services import attack as atk

    return {"scenarios": atk.SCENARIOS}


@app.post("/attack/scenarios/{scenario_id}")
def attack_scenario(scenario_id: str, request: Request):
    from .services import attack as atk

    if scenario_id not in atk.BY_ID:
        raise HTTPException(404, "unknown scenario")
    attack_rate_limit(request)
    from sauda_trust.registry import mask_payload

    return mask_payload(atk.run(scenario_id, _attack_mandate(), settings().demo_shop_id))


# ---------------------------------------------------------------- catalogue + overview (owner auth)
@app.get("/products")
def products(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50), uid: str = Depends(owner_uid)):
    from .services import demand

    words = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if w]
    out = []
    for g, p in store.products().items():
        hay = f"{p.get('name', '')} {p.get('brand', '')} {p.get('category', '')} {p.get('pack_size', '')} {g}".lower()
        if words and not all(w in hay for w in words):
            continue
        c = demand._ceiling({**p, "gtin": g})
        out.append({"gtin": g, "name": _display_name(p), "brand": p.get("brand"), "pack_size": p.get("pack_size"),
                    "category": p.get("category"), "mrp_paise": p.get("mrp_paise"), "ceiling_paise": int(c["ceiling_paise"]),
                    "ceiling_source": c.get("ceiling_source"), "ceiling_as_of": c.get("as_of") or ""})
        if len(out) >= limit:
            break
    return {"products": out}


class KillSwitchIn(BaseModel):
    on: bool


@app.post("/shops/{shop_id}/kill-switch")
def kill_switch(shop_id: str, body: KillSwitchIn, uid: str = Depends(owner_uid)):
    """Owner's kill switch: while on, R12 denies every gated action for the shop (negotiation rounds, orders,
    payment mandates). On the shared demo shop only the operator may flip it, so one visitor cannot stop others."""
    shop = check_shop_owner(shop_id, uid)
    if not shop.get("owner_uid") and uid != "demo-owner":
        raise HTTPException(403, "only the shop owner can use the kill switch")
    store.update_shop(shop_id, kill_switch=body.on)
    nid = shop.get("active_negotiation_id")
    if nid:
        trust.ledger_append(nid, "kill_switch.set", "owner", {"on": body.on})
    return {"shop_id": shop_id, "kill_switch": body.on}


@app.get("/shops/{shop_id}/overview")
def shop_overview(shop_id: str, uid: str = Depends(owner_uid)):
    from .services import orders as orders_svc

    shop = check_shop_owner(shop_id, uid)
    nid = shop.get("active_negotiation_id")
    n = store.negotiation(nid) if nid else None
    active, pending = None, None
    if n and n.get("owner_uid") in (None, uid) and n.get("status") not in FINISHED:
        active = {k: n.get(k) for k in ("negotiation_id", "status", "round", "intent_mandate_id", "cart_draft_id", "started_at")}
        c = store.confirmation(n["confirmation_id"]) if n.get("confirmation_id") else None
        pending = c["confirmation_id"] if c and c.get("status") == "requested" and c.get("expires_at", "") > store.iso() else None
    owners: dict[str, str | None] = {}

    def owner_of(o):
        if o.get("owner_uid"):
            return o["owner_uid"]
        k = o.get("negotiation_id", "")
        if k not in owners:
            owners[k] = (store.negotiation(k) or {}).get("owner_uid")
        return owners[k]

    mine = [o for o in store.orders_for_shop(shop_id) if owner_of(o) in (None, uid)]
    mine.sort(key=lambda o: o.get("created_at") or "", reverse=True)
    recent = [{"order_id": o["order_id"], "negotiation_id": o.get("negotiation_id"), "supplier_id": o.get("supplier_id"),
               "supplier_name": o.get("supplier_name"), "total_paise": o.get("total_paise"),
               "status": orders_svc.order_status(o), "payment_status": orders_svc.payment_status(o),
               "po_ack": (o.get("po_ack") or {}).get("status") if isinstance(o.get("po_ack"), dict) else o.get("po_ack"),
               "created_at": o.get("created_at")} for o in mine[:10]]
    return {"shop": {"shop_id": shop_id, "name": shop.get("name"), "kill_switch": bool(shop.get("kill_switch"))}, "active_negotiation": active,
            "pending_confirmation_id": pending, "recent_orders": recent}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": "unexpected server error"})

from .voice_routes import router as voice_router  # noqa: E402  (voice agent: POST /voice/parse)
app.include_router(voice_router)
from .session_routes import router as session_router  # noqa: E402  (restock sessions: /restock/sessions*)
app.include_router(session_router)
from .trust_network_routes import router as tn_router  # noqa: E402  (Trust Network: /tn/*, /review/*)
app.include_router(tn_router)
from .onboarding_routes import router as onboarding_router  # noqa: E402  (voice onboarding: /tn/onboarding*)
app.include_router(onboarding_router)
