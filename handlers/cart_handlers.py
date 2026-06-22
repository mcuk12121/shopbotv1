from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_db_session, User, Cart, Product, Order, OrderItem, Transaction, TransactionStatus, PaymentMethod, OrderStatus
from utils import format_price, notify_admin, create_back_support_keyboard
from services.payment_provider import get_payment_service
from config.settings import settings as app_settings


def _get_or_create_user(session, telegram_id, username=None):
    user = session.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


async def add_to_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add product to user's cart (increment quantity by 1)."""
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[2])
    telegram_id = update.effective_user.id
    username = update.effective_user.username

    with get_db_session() as session:
        user = _get_or_create_user(session, telegram_id, username)
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            await query.edit_message_text("❌ Product not found.")
            return

        # Find cart item
        cart_item = session.query(Cart).filter_by(user_id=user.id, product_id=product.id).first()
        if cart_item:
            cart_item.quantity += 1
        else:
            cart_item = Cart(user_id=user.id, product_id=product.id, quantity=1)
            session.add(cart_item)
        session.commit()

    await query.edit_message_text(f"✅ Added {product.name} to your cart.", reply_markup=create_back_support_keyboard())


async def view_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id

    with get_db_session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            await query.edit_message_text("🛒 Your cart is empty.", reply_markup=create_back_support_keyboard())
            return

        cart_items = session.query(Cart).filter_by(user_id=user.id).all()

        if not cart_items:
            await query.edit_message_text("🛒 Your cart is empty.", reply_markup=create_back_support_keyboard())
            return

        lines = []
        total = 0.0
        for item in cart_items:
            prod = session.query(Product).filter_by(id=item.product_id).first()
            if not prod:
                continue
            line_total = prod.price * item.quantity
            total += line_total
            lines.append(f"• {prod.name} x{item.quantity} — {format_price(line_total)}")

    text = "🛒 Your Cart:\n\n" + "\n".join(lines) + f"\n\nTotal: {format_price(total)}"

    keyboard = [
        [InlineKeyboardButton("⚡ Checkout BTC", callback_data="checkout_BTC") , InlineKeyboardButton("⚡ Checkout LTC", callback_data="checkout_LTC")],
        [InlineKeyboardButton("🗑 Clear Cart", callback_data="clear_cart")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def clear_cart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id

    with get_db_session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            await query.edit_message_text("🛒 Your cart is already empty.", reply_markup=create_back_support_keyboard())
            return

        session.query(Cart).filter_by(user_id=user.id).delete()
        session.commit()

    await query.edit_message_text("🗑 Cart cleared.", reply_markup=create_back_support_keyboard())


async def checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create an order and payment transaction, generate provider invoice and show pay button."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("checkout_"):
        await query.edit_message_text("❌ Invalid checkout request.")
        return

    currency = data.split("_")[1]
    telegram_id = update.effective_user.id
    username = update.effective_user.username

    with get_db_session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            await query.edit_message_text("❌ No user found. Please /start to create your account.")
            return

        cart_items = session.query(Cart).filter_by(user_id=user.id).all()
        if not cart_items:
            await query.edit_message_text("🛒 Your cart is empty.")
            return

        # Calculate total and create order (status PROCESSING)
        total = 0.0
        order = Order(user_id=user.id, total_amount=0.0, status=OrderStatus.PROCESSING)
        session.add(order)
        session.commit()
        session.refresh(order)

        for item in cart_items:
            prod = session.query(Product).filter_by(id=item.product_id).first()
            if not prod:
                continue
            line_total = prod.price * item.quantity
            total += line_total
            order_item = OrderItem(order_id=order.id, product_id=prod.id, quantity=item.quantity, price=prod.price)
            session.add(order_item)

        order.total_amount = total
        session.commit()

        # Create transaction tied to this order. We'll encode order id into crypto_address after invoice created.
        transaction = Transaction(
            user_id=user.id,
            amount=total,
            payment_method=PaymentMethod.CRYPTO_WALLET,
            status=TransactionStatus.PENDING,
            expires_at=None
        )
        session.add(transaction)
        session.commit()
        session.refresh(transaction)

        # Generate provider invoice (pass currency if supported)
        crypto_service = get_payment_service()
        payment_address = crypto_service.generate_payment_address(total, transaction.id, currency=currency)

        if not payment_address:
            transaction.status = TransactionStatus.FAILED
            session.commit()
            await query.edit_message_text("❌ Failed to generate payment. Please try again or contact support.")
            return

        # Append order reference to crypto_address so payment processor handlers can find the order
        transaction.crypto_address = f"{payment_address}|order_{order.id}"
        session.commit()

        # Build payment message and keyboard
        if "|" in payment_address:
            invoice_id, pay_url = payment_address.split("|", 1)
        else:
            invoice_id = ""
            pay_url = payment_address

        message = f"💬 Checkout\n\n🧾 Order ID: #{order.id}\n💰 Amount: {format_price(total)} {currency}\n\nClick below to pay with {currency}."

        keyboard = [
            [InlineKeyboardButton(f"💳 Pay with {currency}", url=pay_url)],
            [InlineKeyboardButton("❌ Cancel Order", callback_data=f"cancel_order_{order.id}")]
        ]

    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))


async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    # expected format cancel_order_{order_id}
    try:
        order_id = int(data.split("_")[2])
    except Exception:
        await query.edit_message_text("❌ Invalid cancel request.")
        return

    with get_db_session() as session:
        order = session.query(Order).filter_by(id=order_id).first()
        if not order:
            await query.edit_message_text("❌ Order not found.")
            return

        # Remove cart items for this user as well
        session.query(Cart).filter_by(user_id=order.user_id).delete()
        # Mark order cancelled
        order.status = OrderStatus.CANCELLED
        session.commit()

    await query.edit_message_text(f"❌ Order #{order_id} cancelled.", reply_markup=create_back_support_keyboard())

