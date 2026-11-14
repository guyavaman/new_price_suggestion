"""Payment providers for deposits.

`PaymentProvider.checkout_url` returns where the customer pays; the provider later confirms
the payment (webhook for real providers, a button on the demo checkout page here).
Adding an Israeli processor (Grow/Meshulam, Tranzila, CardCom, PayPlus) means one class:
create the payment page through its API, and verify its webhook before calling
`CustomerPortal.confirm_payment`.
"""

from __future__ import annotations

from typing import Protocol

from app.business.settings import BusinessSettings
from app.crm.models import Payment


class PaymentProvider(Protocol):
    name: str

    def checkout_url(self, payment: Payment, quote_token: str,
                     rules: BusinessSettings) -> str: ...


class DemoProvider:
    """No money moves: a simulated checkout page in the web app confirms the payment."""

    name = "demo"

    def checkout_url(self, payment: Payment, quote_token: str, rules: BusinessSettings) -> str:
        return f"{rules.public_base_url.rstrip('/')}/pay/{payment.id}?t={quote_token}"


PROVIDERS: dict[str, PaymentProvider] = {"demo": DemoProvider()}


def get_provider(name: str) -> PaymentProvider:
    if name not in PROVIDERS:
        raise ValueError(f"Payment provider '{name}' is not configured")
    return PROVIDERS[name]
