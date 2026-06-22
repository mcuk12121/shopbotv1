@@
-from handlers import user_handlers, admin_handlers, payment_handlers, admin_conversations, dispute_handlers
+from handlers import user_handlers, admin_handlers, payment_handlers, admin_conversations, dispute_handlers, cart_handlers
@@
     application.add_handler(CallbackQueryHandler(user_handlers.products_callback, pattern="^products"))
@@
     application.add_handler(CallbackQueryHandler(user_handlers.user_order_detail_callback, pattern="^user_order_detail_"))
+
+    # Cart handlers
+    application.add_handler(CallbackQueryHandler(cart_handlers.add_to_cart_callback, pattern="^add_to_cart_"))
+    application.add_handler(CallbackQueryHandler(cart_handlers.view_cart_callback, pattern="^view_cart$"))
+    application.add_handler(CallbackQueryHandler(cart_handlers.clear_cart_callback, pattern="^clear_cart$"))
+    application.add_handler(CallbackQueryHandler(cart_handlers.checkout_callback, pattern="^checkout_"))
+    application.add_handler(CallbackQueryHandler(cart_handlers.cancel_order_callback, pattern="^cancel_order_"))
*** End Patch
