"""Webhook server for receiving CryptoBot and KryptoExpress payment notifications.

This server receives real-time payment notifications from payment providers
and processes them to complete transactions and orders.

Setup:
1. Install Flask and requests: pip install flask requests
2. For local testing, use ngrok: ngrok http 5000
3. Configure webhook in KryptoExpress or other provider to POST to
   https://your-domain.com/webhook/cryptoexpress
4. For production, deploy this on a server with HTTPS
"""

from flask import Flask, request, jsonify
import hmac
import hashlib
import json
from datetime import datetime
import requests as http_requests
from database.db import get_db_session
from database.models import (
    Transaction, TransactionStatus, User, Order, OrderItem, Product,
    ProductType, OrderStatus, Cart
)
from config.settings import settings
from handlers.payment_handlers import assign_product_keys

app = Flask(__name__)


# ------------------------------- CryptoBot (existing) -------------------------------

def verify_cryptobot_signature(body: bytes, signature: str) -> bool:
    """
    Verify CryptoBot webhook signature (existing implementation).
    """
    secret_key = hashlib.sha256(settings.CRYPTO_BOT_API_KEY.encode()).digest()
    calculated_signature = hmac.new(secret_key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated_signature, signature)


def process_invoice_paid(invoice_data: dict):
    """Process a paid invoice notification from CryptoBot (existing).

    Note: this function credits the user's wallet (not used for order-based payments).
    """
    try:
        invoice_id = invoice_data.get('invoice_id')
        status = invoice_data.get('status')
        paid_at = invoice_data.get('paid_at')

        print(f"📩 Webhook received: Invoice #{invoice_id}, status={status}, paid_at={paid_at}")

        if status != 'paid':
            print(f"⚠️ Invoice {invoice_id} not in 'paid' status, ignoring")
            return

        # Find transaction by invoice_id in crypto_address field (format: "invoice_id|pay_url")
        with get_db_session() as session:
            transactions = session.query(Transaction).filter(
                Transaction.payment_method.in_(['crypto_wallet']),
                Transaction.status == TransactionStatus.PENDING
            ).all()

            transaction = None
            for txn in transactions:
                if txn.crypto_address and txn.crypto_address.startswith(f"{invoice_id}|"):
                    transaction = txn
                    break

            if not transaction:
                print(f"❌ No pending transaction found for invoice {invoice_id}")
                return

            user = session.query(User).filter_by(id=transaction.user_id).first()
            if not user:
                print(f"❌ User not found for transaction {transaction.id}")
                return

            # Mark transaction as completed and credit user's wallet
            transaction.status = TransactionStatus.COMPLETED
            transaction.completed_at = datetime.utcnow()
            user.wallet_balance += transaction.amount
            session.commit()

            print(f"✅ Payment processed via webhook!")
            print(f"   Transaction #{transaction.id}")
            print(f"   User: @{user.username}")
            print(f"   Amount: ${transaction.amount:.2f}")
            print(f"   New balance: ${user.wallet_balance:.2f}")

    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        import traceback
        traceback.print_exc()


@app.route('/webhook/cryptobot', methods=['POST'])
def cryptobot_webhook():
    try:
        signature = request.headers.get('crypto-pay-api-signature')
        if not signature:
            print("❌ No signature in webhook request")
            return jsonify({'error': 'No signature'}), 401

        body = request.get_data()
        if not verify_cryptobot_signature(body, signature):
            print("❌ Invalid webhook signature")
            return jsonify({'error': 'Invalid signature'}), 401

        data = request.get_json()
        print(f"📩 CryptoBot Webhook received:")
        print(json.dumps(data, indent=2))

        update_type = data.get('update_type')
        payload = data.get('payload')

        if update_type != 'invoice_paid':
            print(f"⚠️ Unknown update type: {update_type}")
            return jsonify({'ok': True}), 200

        process_invoice_paid(payload)
        return jsonify({'ok': True}), 200

    except Exception as e:
        print(f"❌ Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ----------------------------- KryptoExpress webhook -------------------------------


def verify_kryptoexpress_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verify KryptoExpress HMAC-SHA512 signature.

    KryptoExpress signs the compact JSON (no whitespace) with HMAC-SHA512 using
    the callbackSecret. Header name: X-Signature
    """
    try:
        compact = json.dumps(json.loads(raw_body.decode('utf-8')), separators=(',', ':'))
    except Exception:
        # If body is not JSON or invalid, fail verification
        return False

    expected = hmac.new(secret.encode(), compact.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def _send_telegram_message(chat_id: int, text: str):
    """Send a simple message via Telegram Bot API (no SDK needed).

    This is used by the webhook server (separate process) to notify admin and users.
    """
    try:
        bot_token = settings.BOT_TOKEN
        if not bot_token:
            print("No BOT_TOKEN configured; cannot send Telegram message")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        resp = http_requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send Telegram message to {chat_id}: {e}")
        return False


def process_kryptoexpress_callback(payload: dict):
    """Process a KryptoExpress payment callback payload.

    Expected payload contains at least: 'hash', 'isPaid' (bool) or 'paidAt',
    and optionally 'txIdList', 'cryptoAmount', 'cryptoCurrency'.
    """
    try:
        payment_hash = payload.get('hash') or payload.get('id')
        is_paid = payload.get('isPaid')
        paid_at = payload.get('paidAt')

        print(f"📩 KryptoExpress callback: hash={payment_hash}, isPaid={is_paid}, paidAt={paid_at}")

        if not payment_hash:
            print("❌ No payment hash in callback payload")
            return

        # Treat either explicit isPaid True or presence of paidAt as payment
        if not is_paid and not paid_at:
            print(f"⚠️ Payment {payment_hash} not paid yet; ignoring")
            return

        with get_db_session() as session:
            # Find pending transaction where crypto_address starts with hash
            txn = session.query(Transaction).filter(
                Transaction.status == TransactionStatus.PENDING,
                Transaction.payment_method == Transaction.payment_method.__class__.CRYPTO_WALLET
            ).filter(Transaction.crypto_address.like(f"{payment_hash}%")).first()

            # The above filter uses an Enum comparison that may not work in all DB backends;
            # as a safer fallback, fetch by LIKE and then check status in Python if None
            if not txn:
                # Try a looser search (any PENDING transaction with crypto_address starting with hash)
                transactions = session.query(Transaction).filter(Transaction.status == TransactionStatus.PENDING).all()
                for t in transactions:
                    if t.crypto_address and t.crypto_address.startswith(str(payment_hash)):
                        txn = t
                        break

            if not txn:
                print(f"❌ No pending transaction found for payment hash {payment_hash}")
                return

            # Idempotency: if already completed, nothing to do
            if txn.status == TransactionStatus.COMPLETED:
                print(f"ℹ️ Transaction #{txn.id} already completed")
                return

            # Attempt to extract order id from transaction.crypto_address
            order_id = None
            parts = txn.crypto_address.split('|') if txn.crypto_address else []
            for p in parts:
                if p.startswith('order_'):
                    try:
                        order_id = int(p.split('order_')[1])
                    except Exception:
                        order_id = None
                    break

            # If order_id not embedded, try to find order by matching user & recent ORDER with same amount
            order = None
            if order_id:
                order = session.query(Order).filter_by(id=order_id).first()

            if not order:
                # Fallback: find the most recent PROCESSING order for this user with same amount
                candidate = session.query(Order).filter_by(user_id=txn.user_id, status=OrderStatus.PROCESSING).order_by(Order.created_at.desc()).first()
                if candidate and abs(candidate.total_amount - txn.amount) < 0.001:
                    order = candidate

            if not order:
                print(f"❌ Order not found for transaction {txn.id}; aborting completion")
                return

            # Fulfill the order atomically
            # Assign keys or download links, decrement stock, update order and transaction
            order_items = session.query(OrderItem).filter_by(order_id=order.id).all()

            delivered_text_parts = []
            for item in order_items:
                prod = session.query(Product).filter_by(id=item.product_id).first()
                if not prod:
                    continue

                if prod.product_type.name == 'KEY':
                    # Assign keys using the shared handler helper
                    try:
                        keys = assign_product_keys(session, prod.id, item.quantity, order.id)
                        item.delivered_asset = "\n".join(keys)
                        delivered_text_parts.append(f"{prod.name} (x{item.quantity}) - Keys assigned")
                    except Exception as e:
                        print(f"Error assigning keys for product {prod.id}: {e}")
                        item.delivered_asset = ""
                elif prod.product_type.name == 'FILE':
                    item.delivered_asset = prod.download_link
                    delivered_text_parts.append(f"{prod.name} - Download link provided")

                # Update stock
                try:
                    prod.stock_count = max(0, prod.stock_count - item.quantity)
                except Exception:
                    pass

            # Mark transaction and order completed
            txn.status = TransactionStatus.COMPLETED
            txn.completed_at = datetime.utcnow()

            order.status = OrderStatus.COMPLETED
            order.completed_at = datetime.utcnow()

            # Clear user's cart
            try:
                session.query(Cart).filter_by(user_id=order.user_id).delete()
            except Exception:
                pass

            session.commit()

            # Notify user and admin via Telegram Bot API
            user = session.query(User).filter_by(id=txn.user_id).first()
            admin_id = settings.ADMIN_TELEGRAM_ID

            user_msg = f"✅ Payment Confirmed!\n\n🧾 Order ID: #{order.id}\n💰 Amount: ${txn.amount:.2f}\n\nYour order has been completed and will be delivered below:\n\n"
            for item in order_items:
                if item.delivered_asset:
                    user_msg += f"📦 {item.product.name} (x{item.quantity})\n{item.delivered_asset}\n\n"

            user_msg += "Thank you for your purchase!"

            if user and user.telegram_id:
                _send_telegram_message(user.telegram_id, user_msg)

            admin_msg = f"💳 New Payment Confirmed\n\n👤 User ID: {user.telegram_id if user else 'unknown'}\n🧾 Order ID: #{order.id}\n💰 Amount: ${txn.amount:.2f}\n\nItems:\n"
            for it in order_items:
                admin_msg += f" - {it.product.name} x{it.quantity}\n"

            _send_telegram_message(admin_id, admin_msg)

            print(f"✅ Order #{order.id} completed and notifications sent")

    except Exception as e:
        print(f"❌ Error processing KryptoExpress callback: {e}")
        import traceback
        traceback.print_exc()


@app.route('/webhook/cryptoexpress', methods=['POST'])
def cryptoexpress_webhook():
    """Webhook endpoint for KryptoExpress payment notifications.

    KryptoExpress signs callbacks with HMAC-SHA512 using the callbackSecret. The
    signature is present in the X-Signature header. The request body must be
    verified using the compact JSON form before processing.
    """
    try:
        signature = request.headers.get('X-Signature')
        if not signature:
            print("❌ No X-Signature header in KryptoExpress webhook")
            return jsonify({'error': 'No signature'}), 401

        raw_body = request.get_data()

        callback_secret = getattr(settings, 'CRYPTO_EXPRESS_WEBHOOK_SECRET', '')
        if not callback_secret:
            print("❌ No CRYPTO_EXPRESS_WEBHOOK_SECRET configured; rejecting webhook")
            return jsonify({'error': 'Webhook secret not configured'}), 403

        if not verify_kryptoexpress_signature(raw_body, signature, callback_secret):
            print("❌ Invalid KryptoExpress webhook signature")
            return jsonify({'error': 'Invalid signature'}), 401

        data = request.get_json()
        print("📩 KryptoExpress Webhook received:")
        print(json.dumps(data, indent=2))

        # KryptoExpress provides payload similar to GET /payment response
        # Process the callback asynchronously if needed; here we handle inline.
        process_kryptoexpress_callback(data)

        return jsonify({'ok': True}), 200

    except Exception as e:
        print(f"❌ Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'service': 'Webhook Receiver',
        'timestamp': datetime.utcnow().isoformat()
    }), 200


@app.route('/', methods=['GET'])
def index():
    """Root endpoint with setup instructions."""
    return """
    <h1>Webhook Receiver</h1>
    <p>This server is running and ready to receive payment notifications.</p>

    <h2>Setup Instructions:</h2>
    <ol>
        <li>For KryptoExpress: Create a payment with callbackUrl set to https://your-domain.com/webhook/cryptoexpress and set a callbackSecret.</li>
        <li>For local testing, run: ngrok http 5000</li>
        <li>Set CRYPTO_EXPRESS_CALLBACK_URL to the public URL and CRYPTO_EXPRESS_WEBHOOK_SECRET to your secret in .env</li>
    </ol>

    <h2>Endpoints:</h2>
    <ul>
        <li><code>POST /webhook/cryptoexpress</code> - KryptoExpress webhook endpoint</li>
        <li><code>POST /webhook/cryptobot</code> - CryptoBot webhook endpoint</li>
        <li><code>GET /health</code> - Health check</li>
    </ul>

    <p><strong>Note:</strong> For local testing, use ngrok to create a public HTTPS URL.</p>
    """, 200


if __name__ == '__main__':
    print("=" * 60)
    print("Webhook Server")
    print("=" * 60)
    print(f"Server starting on http://0.0.0.0:5000")
    print(f"KryptoExpress webhook endpoint: /webhook/cryptoexpress")
    print()
    print("For local testing with ngrok:")
    print("  1. Run: ngrok http 5000")
    print("  2. Copy the HTTPS URL (e.g., https://abc123.ngrok.io)")
    print("  3. Set webhook in KryptoExpress to: https://abc123.ngrok.io/webhook/cryptoexpress")
    print()
    print("Waiting for webhooks...")
    print("=" * 60)

    # Run Flask server
    app.run(host='0.0.0.0', port=5000, debug=False)
