"""Representative and business-contact checks.

The owner's Google sign-in email is verified by Firebase, which proves control of that account only. It does
not establish authority to act for the business. Control of the business phone/email needs an OTP sent by
an authorised messaging provider (DLT-registered SMS / email); none is configured, so these are pending.
OTPs are never stored by Sauda.
"""
from __future__ import annotations

from sauda_verify.models import (
    AuthorityStatus,
    Business,
    CheckStatus,
    Dim,
    FieldCompare,
    SourceKind,
)
from sauda_verify.providers._common import mode
from sauda_verify.providers._registry import env_present
from sauda_verify.providers.base import ProviderResult

OTP_ENV = ("OTP_PROVIDER", "OTP_PROVIDER_API_KEY")


class ContactProvider:
    name = "contact"
    dims = [Dim.representative]

    def applicable(self, biz: Business) -> bool:
        return True

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify":
            return []
        rep = biz.representative
        out = [ProviderResult(
            status=CheckStatus.pending if rep.authority_status != AuthorityStatus.verified else CheckStatus.verified,
            source_kind=SourceKind.self_declared if rep.authority_status != AuthorityStatus.verified
            else SourceKind.human_review,
            source_name="Firebase sign-in + declared representative", dim=Dim.representative,
            check_type="representative_authority", available=False,
            fields=[FieldCompare(field="representative", declared=" / ".join(x for x in (rep.name, rep.role) if x) or None,
                                 observed=None, match=None)],
            summary=("The owner's Google sign-in email is verified by Firebase, but that only proves control of the "
                     "account; it does not establish authority to act for this business. Authority needs evidence "
                     "(e.g. a partnership deed, board resolution or proprietor's declaration) reviewed by a person."),
        )]
        has_contact = bool(biz.contact.phone_masked or biz.contact.email_masked)
        if has_contact:
            configured = env_present(*OTP_ENV)
            out.append(ProviderResult(
                status=CheckStatus.pending, source_kind=SourceKind.self_declared,
                source_name="Business contact OTP (no provider configured)" if not configured
                else "Business contact OTP", dim=Dim.representative, check_type="business_contact_otp",
                available=False,
                fields=[FieldCompare(field="business_contact",
                                     declared=biz.contact.phone_masked or biz.contact.email_masked, match=None)],
                summary=("The business phone/email has not been confirmed: that needs a one-time code sent by an "
                         "authorised messaging provider, which is not configured. Even when confirmed, it shows "
                         "control of the channel, not identity or authority."),
            ))
        return out
