 def create_product_detail_keyboard(product_id, back_callback="back"):
     """Create keyboard for product details view with Buy Now button."""
-    keyboard = [
-        [InlineKeyboardButton("🛒 Buy Now", callback_data=f"buy_{product_id}")],
-        [
-            InlineKeyboardButton("🔙 Back", callback_data=back_callback),
-            InlineKeyboardButton("☎️ Support", callback_data="support")
-        ]
-    ]
+    keyboard = [
+        [InlineKeyboardButton("➕ Add to Cart", callback_data=f"add_to_cart_{product_id}"), InlineKeyboardButton("🛒 Buy Now", callback_data=f"buy_{product_id}")],
+        [
+            InlineKeyboardButton("🔙 Back", callback_data=back_callback),
+            InlineKeyboardButton("☎️ Support", callback_data="support")
+        ]
+    ]
     return InlineKeyboardMarkup(keyboard)
