"""Env-driven settings and lazily created shared GCP clients (no network at import time)."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from functools import lru_cache

try:  # local dev convenience; Cloud Run uses real env vars
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:  # pragma: no cover
    pass

MODEL_ARMOR_ENDPOINT = "modelarmor.us-central1.rep.googleapis.com"


@dataclass(frozen=True)
class Settings:
    project: str
    location: str
    kms_key_name: str
    kms_key_version: str
    model_armor_template: str
    demo_shop_id: str
    private_bucket: str
    model_armor_timeout_s: float = 5.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        project=e("GOOGLE_CLOUD_PROJECT", ""),
        location=e("GOOGLE_CLOUD_LOCATION", "asia-south1"),
        kms_key_name=e(
            "KMS_KEY_NAME",
            f"projects/{e('GOOGLE_CLOUD_PROJECT', '')}/locations/global/keyRings/sauda/cryptoKeys/sauda-mandates",
        ),
        kms_key_version=e("KMS_KEY_VERSION", "1"),
        model_armor_template=e(
            "MODEL_ARMOR_TEMPLATE",
            f"projects/{e('GOOGLE_CLOUD_PROJECT', '')}/locations/us-central1/templates/sauda-guard",
        ),
        demo_shop_id=e("DEMO_SHOP_ID", "demo"),
        private_bucket=e("PRIVATE_BUCKET", f"{e('GOOGLE_CLOUD_PROJECT', '')}-sauda-private"),
        model_armor_timeout_s=float(e("MODEL_ARMOR_TIMEOUT_S", "5")),
    )


_lock = threading.Lock()
_clients: dict[str, object] = {}


def _lazy(name, factory):
    c = _clients.get(name)
    if c is None:
        with _lock:
            c = _clients.get(name)
            if c is None:
                c = factory()
                _clients[name] = c
    return c


def firestore_client():
    def make():
        from google.cloud import firestore

        return firestore.Client(project=get_settings().project)

    return _lazy("firestore", make)


def kms_client():
    def make():
        from google.cloud import kms

        return kms.KeyManagementServiceClient()

    return _lazy("kms", make)


def modelarmor_client():
    def make():
        from google.api_core.client_options import ClientOptions
        from google.cloud import modelarmor_v1

        return modelarmor_v1.ModelArmorClient(
            transport="rest", client_options=ClientOptions(api_endpoint=MODEL_ARMOR_ENDPOINT)
        )

    return _lazy("modelarmor", make)


def set_client(name: str, client: object | None) -> None:
    """Inject/override a shared client ('firestore', 'kms', 'modelarmor'); None clears it."""
    with _lock:
        if client is None:
            _clients.pop(name, None)
        else:
            _clients[name] = client
