"""Payment details: bank account / UPI ownership needs an authorised provider (penny drop or reverse penny
drop with name match, e.g. Cashfree or RazorpayX). None is configured, so the check is pending. Sauda never
stores bank credentials and never claims a payout account is verified without such a provider."""
from __future__ import annotations

from sauda_verify.models import Business, CheckStatus, Dim, SourceKind
from sauda_verify.providers._common import mode
from sauda_verify.providers._registry import env_present
from sauda_verify.providers.base import ProviderResult


class BankProvider:
    name = "bank"
    dims = [Dim.payment_details]

    def applicable(self, biz: Business) -> bool:
        return "seller" in biz.roles

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify":
            return []
        configured = env_present("CASHFREE_CLIENT_ID", "CASHFREE_CLIENT_SECRET") or \
            env_present("RAZORPAYX_KEY_ID", "RAZORPAYX_KEY_SECRET")
        return [ProviderResult(
            status=CheckStatus.pending, source_kind=SourceKind.authorised_provider, available=False,
            source_name="Bank account validation (penny drop / name match)", dim=Dim.payment_details,
            check_type="bank_account_validation",
            summary=("Payout account not verified: a penny drop or account-name match needs an authorised "
                     "provider" + (" (credentials present but the adapter is not enabled)" if configured
                                   else ", and none is configured") + ". Until then payment details are unconfirmed."),
        )]
