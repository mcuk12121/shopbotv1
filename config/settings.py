# Added callback URL setting for payment provider webhooks
    # CryptoExpress (new provider)
    CRYPTO_EXPRESS_API_KEY = os.getenv('CRYPTO_EXPRESS_API_KEY', '')
    PAYMENT_PROVIDER = os.getenv('PAYMENT_PROVIDER', 'cryptobot')
    CRYPTO_EXPRESS_WEBHOOK_SECRET = os.getenv('CRYPTO_EXPRESS_WEBHOOK_SECRET', '')
+    # Publicly-accessible callback URL for KryptoExpress to POST webhooks to
+    CRYPTO_EXPRESS_CALLBACK_URL = os.getenv('CRYPTO_EXPRESS_CALLBACK_URL', '')
