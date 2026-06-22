"""
CryptoExpress payment service adapter.

Replace the endpoint URLs and request/response parsing with the real CryptoExpress API.
This adapter exposes the same interface used in handlers (generate_payment_address, check_payment_status).
"""

import requests
from config.settings import settings

class CryptoExpressService:
    def __init__(self):
        self.api_key = settings.CRYPTO_EXPRESS_API_KEY
        # TODO: replace base_url with your provider's base URL
        self.base_url = "https://api.cryptoexpress.example"
        # Paths for invoice creation and retrieval — adjust as required by the real API
        self.create_invoice_path = "/v1/invoices"
        self.get_invoice_path = "/v1/invoices"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def generate_payment_address(self, amount: float, transaction_id: int, **kwargs) -> str:
        """
        Create an invoice on CryptoExpress and return "invoice_id|pay_url".
        """
        if not self.api_key:
            # Development fallback (non-secure)
            return f"{transaction_id}|https://example.com/pay/{transaction_id}"

        payload = {
            "amount": str(amount),
            "currency": "USD",
            "external_id": f"txn_{transaction_id}",
            "description": f"Wallet top-up #{transaction_id}",
            # If your provider supports passing a webhook URL for callbacks, include it here:
            # "webhook_url": "https://your-domain/webhook/cryptoexpress"
        }

        try:
            url = f"{self.base_url}{self.create_invoice_path}"
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # Parse response — adapt to your provider's schema
            invoice_id = data.get("id") or data.get("invoice_id")
            pay_url = data.get("pay_url") or data.get("payment_url") or data.get("url")

            if invoice_id and pay_url:
                return f"{invoice_id}|{pay_url}"
            else:
                print("CryptoExpress: missing invoice_id or pay_url in create response:", data)
                return None

        except Exception as e:
            print("Error creating CryptoExpress invoice:", e)
            return None

    def check_payment_status(self, crypto_address: str, expected_amount: float) -> bool:
        """
        Poll the provider for invoice status. crypto_address expected format: 'invoice_id|pay_url'
        Returns True when the invoice is confirmed/paid.
        """
        if not self.api_key:
            return False

        invoice_id = crypto_address.split("|", 1)[0] if "|" in crypto_address else crypto_address

        if not invoice_id:
            return False

        try:
            url = f"{self.base_url}{self.get_invoice_path}/{invoice_id}"
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # Adapt parsing to the real response
            status = data.get("status")
            paid_amount = data.get("paid_amount") or data.get("amount_paid")

            if status == "paid":
                return True

            if paid_amount:
                try:
                    paid_val = float(paid_amount)
                    if paid_val >= float(expected_amount):
                        return True
                except Exception:
                    pass

            return False

        except Exception as e:
            print("Error checking CryptoExpress invoice status:", e)
            return False
