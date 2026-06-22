import importlib
from config.settings import settings


def get_payment_service():
    """
    Return an instance of the configured payment service.
    PAYMENT_PROVIDER env var selects the provider string:
      - 'cryptobot' -> services.crypto_bot.CryptoBotService (existing)
      - 'cryptoexpress' -> services.crypto_express.CryptoExpressService (new)
    """
    provider = settings.PAYMENT_PROVIDER.lower() if settings.PAYMENT_PROVIDER else 'cryptobot'

    if provider == 'cryptoexpress':
        mod = importlib.import_module('services.crypto_express')
        return mod.CryptoExpressService()
    # fallback to existing cryptobot implementation
    mod = importlib.import_module('services.crypto_bot')
    return mod.CryptoBotService()
