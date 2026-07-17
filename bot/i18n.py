"""Lightweight per-user bilingual strings for the bot.

Bot messages key off each user's stored language (TelegramUser.language), not a request
locale, so a plain dict + t(key, lang) is simpler and adequate here (vs. Django gettext).
Use ``t(key, lang, **kwargs)`` — the result is .format(**kwargs)-ed.
"""

STRINGS = {
    # --- generic ---
    "app.title": {"fa": "🏬 بات انبار", "en": "🏬 Anbar Bot"},
    "btn.back": {"fa": "◀️ بازگشت", "en": "◀️ Back"},
    "btn.main_menu": {"fa": "🏠 منوی اصلی", "en": "🏠 Main menu"},
    "btn.cancel": {"fa": "✖️ لغو", "en": "✖️ Cancel"},
    "btn.confirm": {"fa": "✅ تأیید", "en": "✅ Confirm"},
    "common.cancelled": {"fa": "لغو شد.", "en": "Cancelled."},
    "common.not_found": {"fa": "چیزی پیدا نشد.", "en": "Nothing found."},
    "common.choose": {"fa": "یک گزینه را انتخاب کنید:", "en": "Choose an option:"},

    # --- auth ---
    "auth.welcome_pending": {
        "fa": "درخواست شما ثبت شد. پس از تأیید مدیر می‌توانید استفاده کنید. ⏳",
        "en": "Your request was recorded. You can use the bot once an admin approves you. ⏳",
    },
    "auth.welcome_admin": {
        "fa": "خوش آمدید مدیر گرامی! 👑",
        "en": "Welcome, admin! 👑",
    },
    "auth.not_registered": {
        "fa": "شما مجاز نیستید. لطفاً /start را بزنید و منتظر تأیید بمانید.",
        "en": "You are not authorized. Send /start and wait for approval.",
    },
    "auth.no_permission": {
        "fa": "⛔️ شما دسترسی لازم برای این کار را ندارید.",
        "en": "⛔️ You don't have permission for this action.",
    },
    "auth.new_user_notice": {
        "fa": "👤 کاربر جدید در انتظار تأیید:\n{name} (کد: {id})",
        "en": "👤 New user awaiting approval:\n{name} (id: {id})",
    },

    # --- language ---
    "lang.choose": {"fa": "زبان را انتخاب کنید:", "en": "Choose your language:"},
    "lang.set": {"fa": "زبان روی فارسی تنظیم شد. ✅", "en": "Language set to English. ✅"},

    # --- main menu ---
    "menu.title": {"fa": "منوی اصلی — یک گزینه را انتخاب کنید:", "en": "Main menu — pick an option:"},
    "menu.products": {"fa": "📦 محصولات", "en": "📦 Products"},
    "menu.search": {"fa": "🔍 جستجو", "en": "🔍 Search"},
    "menu.reports": {"fa": "📊 گزارش‌ها", "en": "📊 Reports"},
    "menu.help": {"fa": "❓ راهنما", "en": "❓ Help"},
    "menu.stock_in": {"fa": "➕ ورود کالا", "en": "➕ Stock In"},
    "menu.stock_out": {"fa": "➖ خروج کالا", "en": "➖ Stock Out"},
    "menu.add_product": {"fa": "➕ افزودن محصول", "en": "➕ Add Product"},
    "menu.manage_users": {"fa": "👥 مدیریت کاربران", "en": "👥 Manage Users"},
    "menu.language": {"fa": "🌐 زبان", "en": "🌐 Language"},

    # --- help ---
    "help.text": {
        "fa": (
            "🏬 <b>راهنمای بات انبار</b>\n\n"
            "🔍 <b>جستجو</b> — جستجوی محصول با نام یا کد دیجی‌کالا (DKP)\n"
            "📦 <b>محصولات</b> — مرور آخرین محصولات\n"
            "📊 <b>گزارش‌ها</b> — خلاصه موجودی و اقلام کم‌موجودی\n"
            "➕ <b>ورود کالا</b> / ➖ <b>خروج کالا</b> — ثبت تغییر موجودی (کارمند)\n"
            "🛠 <b>مدیریت محصولات</b> — افزودن محصول و تنوع (مدیر)\n"
            "👥 <b>مدیریت کاربران</b> — تأیید و تعیین نقش کاربران (مدیر)\n"
            "🌐 <b>زبان</b> — تغییر زبان\n\n"
            "با /menu هر زمان به منوی اصلی برگردید."
        ),
        "en": (
            "🏬 <b>Anbar Bot — Help</b>\n\n"
            "🔍 <b>Search</b> — find a product by name or DigiKala code (DKP)\n"
            "📦 <b>Products</b> — browse the latest products\n"
            "📊 <b>Reports</b> — stock summary and low-stock items\n"
            "➕ <b>Stock In</b> / ➖ <b>Stock Out</b> — record stock changes (staff)\n"
            "🛠 <b>Manage Products</b> — add products and variants (admin)\n"
            "👥 <b>Manage Users</b> — approve and set user roles (admin)\n"
            "🌐 <b>Language</b> — switch language\n\n"
            "Send /menu any time to return to the main menu."
        ),
    },

    # --- search ---
    "search.prompt": {
        "fa": "نام محصول یا کد دیجی‌کالا (DKP) را بفرستید:",
        "en": "Send a product name or DigiKala code (DKP):",
    },
    "search.results": {"fa": "محصولات یافت‌شده:", "en": "Matching products:"},
    "list.pick_product": {"fa": "یک محصول را انتخاب کنید:", "en": "Choose a product:"},
    "product.variants_of": {"fa": "🧸 <b>{name}</b> — تنوع‌ها:", "en": "🧸 <b>{name}</b> — variants:"},

    # --- inline search ---
    "inline.not_registered": {
        "fa": "برای استفاده از جستجو ابتدا در ربات ثبت‌نام کنید.",
        "en": "Register in the bot first to use search.",
    },
    "inline.not_registered_desc": {
        "fa": "روی این پیام بزنید تا ربات باز شود.",
        "en": "Tap to open the bot.",
    },
    "list.show_inline": {"fa": "🔽 نمایش به صورت کشویی", "en": "🔽 Show as dropdown"},
    "inline.variant_count": {"fa": "{n} تنوع", "en": "{n} variants"},

    # --- variant card ---
    "card.stock": {"fa": "موجودی", "en": "Stock"},
    "card.low_stock": {"fa": "⚠️ زیر حد آستانه ({n})", "en": "⚠️ below threshold ({n})"},
    "card.buy": {"fa": "خرید", "en": "Buy"},
    "card.sell": {"fa": "فروش", "en": "Sell"},
    "card.dkp": {"fa": "کد دیجی‌کالا", "en": "DKP"},
    "card.no_variant": {"fa": "بدون تنوع", "en": "default"},
    "card.more_lots": {"fa": "(+{n} دستهٔ دیگر)", "en": "(+{n} more)"},
    "card.btn_in": {"fa": "➕ ورود", "en": "➕ In"},
    "card.btn_out": {"fa": "➖ خروج", "en": "➖ Out"},
    "card.btn_add_variant": {"fa": "➕ افزودن تنوع", "en": "➕ Add variant"},

    # --- stock flow ---
    "stock.pick_product": {"fa": "کدام محصول؟ (جستجو کنید)", "en": "Which product? (search)"},
    "stock.choose_product": {"fa": "محصول را انتخاب کنید:", "en": "Choose a product:"},
    "stock.pick_variant": {"fa": "کدام تنوع؟", "en": "Which variant?"},
    "stock.enter_qty_in": {"fa": "چه تعداد وارد شد؟", "en": "How many came in?"},
    "stock.enter_qty_out": {"fa": "چه تعداد خارج شد؟", "en": "How many went out?"},
    "stock.enter_buy": {
        "fa": "قیمت خرید این دسته؟ (فعلی: {price} — «-» برای حفظ)",
        "en": "Buy price for this batch? (current: {price} — send \"-\" to keep)",
    },
    "stock.enter_sell": {
        "fa": "قیمت فروش این دسته؟ (فعلی: {price} — «-» برای حفظ)",
        "en": "Sell price for this batch? (current: {price} — send \"-\" to keep)",
    },
    "stock.bad_qty": {"fa": "لطفاً یک عدد مثبت بفرستید.", "en": "Please send a positive number."},
    "stock.insufficient":  {
        "fa": "موجودی کافی نیست. موجودی فعلی: {available}",
        "en": "Not enough stock. Currently available: {available}",
    },
    "stock.done_in": {
        "fa": "✅ ثبت شد. موجودی جدید: {qty}",
        "en": "✅ Recorded. New stock: {qty}",
    },
    "stock.done_out": {
        "fa": "✅ ثبت شد. موجودی جدید: {qty}",
        "en": "✅ Recorded. New stock: {qty}",
    },
    "stock.low_alert": {
        "fa": "⚠️ هشدار کمبود موجودی:\n{name}\nموجودی: {qty} (حد آستانه: {threshold})",
        "en": "⚠️ Low-stock alert:\n{name}\nStock: {qty} (threshold: {threshold})",
    },

    # --- reports ---
    "report.title": {"fa": "📊 خلاصه گزارش", "en": "📊 Report summary"},
    "report.variants": {"fa": "تعداد تنوع‌ها", "en": "Variants"},
    "report.units": {"fa": "مجموع موجودی", "en": "Total units"},
    "report.purchase_value": {"fa": "ارزش خرید", "en": "Purchase value"},
    "report.sale_value": {"fa": "ارزش فروش", "en": "Sale value"},
    "report.low_stock": {"fa": "اقلام کم‌موجودی", "en": "Low-stock items"},
    "report.low_stock_none": {"fa": "همه اقلام کافی هستند. ✅", "en": "All items are sufficiently stocked. ✅"},

    # --- batch (purchase lot) editor ---
    "btn.edit_batches": {"fa": "📦 دسته‌های خرید", "en": "📦 Batches"},
    "batch.list_title": {"fa": "📦 دسته‌های خرید — {name}", "en": "📦 Purchase batches — {name}"},
    "batch.none": {"fa": "هیچ دسته‌ای با موجودی وجود ندارد.", "en": "No in-stock batches."},
    "batch.line": {
        "fa": "{i}. موجودی {remaining} — خرید {buy} / فروش {sell}",
        "en": "{i}. {remaining} left — buy {buy} / sell {sell}",
    },
    "batch.btn_delete": {"fa": "🗑 حذف", "en": "🗑 Delete"},
    "batch.edit_buy": {
        "fa": "قیمت خرید جدید؟ (فعلی: {price} — «-» برای حفظ)",
        "en": "New buy price? (current: {price} — send \"-\" to keep)",
    },
    "batch.edit_sell": {
        "fa": "قیمت فروش جدید؟ (فعلی: {price} — «-» برای حفظ)",
        "en": "New sell price? (current: {price} — send \"-\" to keep)",
    },
    "batch.bad_num": {"fa": "لطفاً یک عدد بفرستید یا «-».", "en": "Please send a number, or \"-\"."},
    "batch.updated": {"fa": "✅ قیمت‌های دسته بروزرسانی شد.", "en": "✅ Batch prices updated."},
    "batch.confirm_delete": {
        "fa": "حذف این دسته، {n} واحد باقی‌مانده را از موجودی کم می‌کند. مطمئنید؟",
        "en": "Deleting this batch writes off its {n} remaining unit(s). Are you sure?",
    },
    "batch.confirm_delete_yes": {"fa": "بله، حذف کن", "en": "Yes, delete"},
    "batch.deleted": {"fa": "✅ دسته حذف شد (موجودی نوشته‌شد).", "en": "✅ Batch written off."},

    # --- users ---
    "users.title": {"fa": "👥 کاربران", "en": "👥 Users"},
    "users.pending": {"fa": "در انتظار تأیید", "en": "Pending approval"},
    "users.approve": {"fa": "✅ تأیید", "en": "✅ Approve"},
    "users.set_staff": {"fa": "کارمند", "en": "Staff"},
    "users.set_viewer": {"fa": "بازدیدکننده", "en": "Viewer"},
    "users.set_admin": {"fa": "مدیر", "en": "Admin"},
    "users.updated": {"fa": "کاربر بروزرسانی شد. ✅", "en": "User updated. ✅"},
    "users.no_self_deactivate": {
        "fa": "نمی‌توانید حساب خودتان را غیرفعال کنید.",
        "en": "You can't deactivate your own account.",
    },
}


def t(key, lang="fa", **kwargs):
    entry = STRINGS.get(key)
    if entry is None:
        return key   # surface missing keys instead of crashing
    text = entry.get(lang) or entry.get("fa") or key
    return text.format(**kwargs) if kwargs else text
