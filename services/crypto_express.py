"""
KryptoExpress integration using the official SDK (with requests fallback).

This adapter prefers the official `kryptoexpress-sdk` Python package if available,
falling back to the previous requests-based implementation when the SDK is not
installed. It exposes the same interface used by the rest of the bot:

- generate_payment_address(amount, transaction_id, currency='BTC') -> str
  Returns a string in the format: "{hash}|{pay_url}|{address?}"

- check_payment_status(crypto_address, expected_amount) -> bool
  Accepts the stored crypto_address (which starts with the payment hash) and
  returns True when the payment is confirmed.
"""

import traceback
from config.settings import settings

# Try to import official SDK - if present we'll use it
_sdk_available = False
_sdk_client = None
try:
    # The PyPI package is `kryptoexpress-sdk`. The exact import path may vary
    # depending on the package version. Try a couple common names.
    try:
        from kryptoexpress_sdk import KryptoExpressClient as _KryptoExpressClient
    except Exception:
        from kryptoexpress import KryptoExpressClient as _KryptoExpressClient
    _sdk_available = True
except Exception:
    _sdk_available = False

# requests fallback
import requests


class CryptoExpressService:
    def __init__(self):
        self.api_key = settings.CRYPTO_EXPRESS_API_KEY
        self.base_url = "https://kryptoexpress.pro/api"
        self.public_base = "https://kryptoexpress.pro"

        self.sdk = None
        if _sdk_available and self.api_key:
            try:
                # instantiate SDK client
                self.sdk = _KryptoExpressClient(api_key=self.api_key)
            except Exception:
                # If SDK instantiation fails, keep None to fall back to requests
                print("Warning: failed to instantiate kryptoexpress SDK client; falling back to requests")
                traceback.print_exc()
                self.sdk = None

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
        Create a PAYMENT record and return a string: "hash|pay_url|address(optional)".

        Uses SDK if available; otherwise falls back to direct HTTP requests.
        """
        # SDK path
        if self.sdk:
            try:
                # Hypothetical SDK call - adapt if real SDK uses different method signature
                payload = {
                    "fiatCurrency": "USD",
                    "paymentType": "PAYMENT",
                    "fiatAmount": float(amount),
                    "cryptoCurrency": currency,
                }

                callback_url = getattr(settings, 'CRYPTO_EXPRESS_CALLBACK_URL', '')
                callback_secret = getattr(settings, 'CRYPTO_EXPRESS_WEBHOOK_SECRET', '')
                if callback_url:
                    payload["callbackUrl"] = callback_url
                if callback_secret:
                    payload["callbackSecret"] = callback_secret

                resp = self.sdk.create_payment(payload) if hasattr(self.sdk, 'create_payment') else self.sdk.payment.create(payload)

                # Normalize response dict
                invoice_hash = resp.get('hash') or str(resp.get('id'))
                address = resp.get('address')
                pay_url = f"{self.public_base}/payment?hash={invoice_hash}" if invoice_hash else None

                if invoice_hash:
                    return f"{invoice_hash}|{pay_url}|{address}" if address else f"{invoice_hash}|{pay_url}"

            except Exception as e:
                print(f"SDK create_payment error: {e}")
                traceback.print_exc()
                # fallback to requests approach below

        # Requests fallback
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

            invoice_hash = data.get("hash") or data.get("id")
            address = data.get("address")
            pay_url = f"{self.public_base}/payment?hash={invoice_hash}" if invoice_hash else None

            if invoice_hash:
                return f"{invoice_hash}|{pay_url}|{address}" if address else f"{invoice_hash}|{pay_url}"

            return None

        except Exception as e:
            print(f"Error creating KryptoExpress payment (requests): {e}")
            try:
                print(resp.text)
            except Exception:
                pass
            return None

    def check_payment_status(self, crypto_address: str, expected_amount: float) -> bool:
        """
        Check payment status using SDK if available, otherwise GET /payment?hash=...
        Returns True if payment is confirmed.
        """
        if not crypto_address:
            return False

        invoice_hash = str(crypto_address).split("|")[0]
        if not invoice_hash:
            return False

        # SDK path
        if self.sdk:
            try:
                # Hypothetical SDK method to get payment by hash
                resp = self.sdk.get_payment(hash=invoice_hash) if hasattr(self.sdk, 'get_payment') else self.sdk.payment.get(hash=invoice_hash)
                is_paid = resp.get('isPaid')
                paid_at = resp.get('paidAt')
                if is_paid or paid_at:
                    return True
                return False
            except Exception as e:
                print(f"SDK get_payment error: {e}")
                traceback.print_exc()
                # fallback to requests below

        try:
            url = f"{self.base_url}/payment"
            params = {"hash": str(invoice_hash)}
            resp = requests.get(url, params=params, headers=self._headers(protected=False), timeout=10)
            resp.raise_for_status()
            data = resp.json()

            is_paid = data.get("isPaid")
            paid_at = data.get("paidAt")

            if is_paid or paid_at:
                return True
            return False

        except Exception as e:
            print(f"Error checking KryptoExpress payment status (requests): {e}")
            try:
                print(resp.text)
            except Exception:
                pass
            return False
