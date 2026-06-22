"""KryptoExpress integration for cryptocurrency payments.

Uses the KryptoExpress REST API documented at https://kryptoexpress.pro/api

This adapter creates PAYMENT records (exact fiat -> crypto conversion) and polls the
public GET /payment?hash=... endpoint to check payment status. It also supports
providing a callbackUrl and callbackSecret so KryptoExpress signs callbacks.
"""

import requests
from config.settings import settings


class CryptoExpressService:
    def __init__(self):
        self.api_key = settings.CRYPTO_EXPRESS_API_KEY
        self.base_url = "https://kryptoexpress.pro/api"
        # Public payment page base (used to build a clickable link)
        self.public_base = "https://kryptoexpress.pro"

    def _headers(self, protected: bool = True):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if protected and self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    def generate_payment_address(self, amount: float, transaction_id: int, currency: str = "BTC", **kwargs) -> str:
        """
        Create a PAYMENT record for the exact fiat amount and return a string
        in the format: "{hash}|{pay_url}|{address?}" where pay_url is a public
        lookup URL and address is the deposit address (if present).

        Args:
            amount: fiat amount in USD
            transaction_id: local transaction id (used as external reference)
            currency: crypto currency code (BTC or LTC)
        """
        # If API key not configured, return a safe sample fallback
        if not self.api_key:
            sample_hash = f"sample_{transaction_id}"
            pay_url = f"{self.public_base}/payment?hash={sample_hash}"
            sample_address = "testaddress"
            return f"{sample_hash}|{pay_url}|{sample_address}"

        payload = {
            "fiatCurrency": "USD",
            "paymentType": "PAYMENT",
            "fiatAmount": float(amount),
            "cryptoCurrency": currency,
        }

        # Include callback URL and secret if configured
        callback_url = getattr(settings, 'CRYPTO_EXPRESS_CALLBACK_URL', '')
        callback_secret = getattr(settings, 'CRYPTO_EXPRESS_WEBHOOK_SECRET', '')
        if callback_url:
            payload["callbackUrl"] = callback_url
        if callback_secret:
            payload["callbackSecret"] = callback_secret

        try:
            url = f"{self.base_url}/payment"
            resp = requests.post(url, json=payload, headers=self._headers(protected=True), timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # Expected: response contains fields like 'hash' and 'address'
            invoice_hash = data.get("hash")
            address = data.get("address")

            # Construct a public pay URL the user can open
            pay_url = f"{self.public_base}/payment?hash={invoice_hash}"

            if invoice_hash:
                # Return hash|pay_url|address (address optional)
                if address:
                    return f"{invoice_hash}|{pay_url}|{address}"
                return f"{invoice_hash}|{pay_url}"

            return None

        except Exception as e:
            print(f"Error creating KryptoExpress payment: {e}")
            try:
                # debug print body if available
                print(resp.text)
            except Exception:
                pass
            return None

    def check_payment_status(self, crypto_address: str, expected_amount: float) -> bool:
        """
        Check payment status using the public GET /payment?hash=... endpoint.
        crypto_address is expected to start with the hash (the first segment).
        Returns True if payment is confirmed (isPaid == true or paidAt present).
        """
        try:
            if not crypto_address:
                return False

            # crypto_address may be of format: hash|pay_url|address or hash|pay_url
            invoice_hash = crypto_address.split("|")[0]
            if not invoice_hash:
                return False

            url = f"{self.base_url}/payment"
            params = {"hash": str(invoice_hash)}

            resp = requests.get(url, params=params, headers=self._headers(protected=False), timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # data contains isPaid and paidAt according to docs
            is_paid = data.get("isPaid")
            paid_at = data.get("paidAt")

            if is_paid:
                return True
            if paid_at:
                return True

            return False

        except Exception as e:
            print(f"Error checking KryptoExpress payment status: {e}")
            try:
                print(resp.text)
            except Exception:
                pass
            return False
