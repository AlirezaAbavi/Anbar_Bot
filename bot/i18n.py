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
    "common.error": {
        "fa": "⚠️ خطایی رخ داد و عملیات کامل نشد. لطفاً دوباره تلاش کنید.",
        "en": "⚠️ Something went wrong and the action didn't complete. Please try again.",
    },

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
    "page.prev": {"fa": "‹ قبلی", "en": "‹ Prev"},
    "page.next": {"fa": "بعدی ›", "en": "Next ›"},
    "page.indicator": {"fa": "صفحه {n}", "en": "Page {n}"},
    "inline.variant_count": {"fa": "{n} تنوع", "en": "{n} variants"},
    "inline.open": {"fa": "🧸 مشاهده ({n} تنوع)", "en": "🧸 View ({n} variants)"},

    # --- variant card ---
    "card.stock": {"fa": "موجودی", "en": "Stock"},
    "card.low_stock": {"fa": "⚠️ زیر حد آستانه ({n})", "en": "⚠️ below threshold ({n})"},
    "card.buy": {"fa": "خرید", "en": "Buy"},
    "card.sell": {"fa": "فروش", "en": "Sell"},
    "card.dkp": {"fa": "کد دیجی‌کالا", "en": "DKP"},
    "card.description": {"fa": "توضیحات", "en": "Description"},
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

    # --- team alerts (broadcast to other staff/admins after a procedure) ---
    "notify.stock_in": {
        "fa": "📥 ورود کالا: {name}\nتعداد: {qty} — موجودی جدید: {balance}\nتوسط: {by}",
        "en": "📥 Stock In: {name}\nQty: {qty} — new stock: {balance}\nby: {by}",
    },
    "notify.stock_out": {
        "fa": "📤 خروج کالا: {name}\nتعداد: {qty} — موجودی جدید: {balance}\nتوسط: {by}",
        "en": "📤 Stock Out: {name}\nQty: {qty} — new stock: {balance}\nby: {by}",
    },
    "notify.product_added": {
        "fa": "🆕 محصول جدید ثبت شد: {name}\nتوسط: {by}",
        "en": "🆕 New product added: {name}\nby: {by}",
    },
    "notify.variant_added": {
        "fa": "🆕 تنوع جدید به «{name}» اضافه شد.\nتوسط: {by}",
        "en": "🆕 New variant added to “{name}”.\nby: {by}",
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

    # --- catalog review / supervision walkthrough ---
    "menu.review": {"fa": "🛠 بازبینی محصولات", "en": "🛠 Review Catalog"},
    "review.header": {"fa": "🛠 بازبینی محصولات — {done} / {total}", "en": "🛠 Catalog review — {done} / {total}"},
    "review.card": {
        "fa": "{header}\n\n🧸 <b>{name_fa}</b>\nانگلیسی: {name_en}\nدسته: {category}\n\nتنوع‌ها:\n{variants}",
        "en": "{header}\n\n🧸 <b>{name_fa}</b>\nEN: {name_en}\nCategory: {category}\n\nVariants:\n{variants}",
    },
    "review.variant_line": {
        "fa": " • {label} — موجودی {qty} · خرید {buy} / فروش {sell} · آستانه {thr} · DKP: {dkp}",
        "en": " • {label} — qty {qty} · buy {buy} / sell {sell} · thr {thr} · DKP: {dkp}",
    },
    "review.no_variants": {"fa": " (بدون تنوع)", "en": " (no variants)"},
    "review.dash": {"fa": "—", "en": "—"},
    "review.btn_name_fa": {"fa": "✏️ نام فارسی", "en": "✏️ Name (FA)"},
    "review.btn_name_en": {"fa": "✏️ نام انگلیسی", "en": "✏️ Name (EN)"},
    "review.btn_save": {"fa": "💾 ذخیره و بعدی", "en": "💾 Save & next"},
    "review.btn_skip": {"fa": "⏭ رد کردن", "en": "⏭ Skip"},
    "review.vhub_title": {
        "fa": "🧸 <b>{name}</b> — {label}\nموجودی: {qty}  (از طریق ورود/خروج کالا)\nخرید {buy} / فروش {sell}\nحد آستانه کمبود: {thr}\nDKP: {dkp}",
        "en": "🧸 <b>{name}</b> — {label}\nStock: {qty}  (change via Stock In/Out)\nBuy {buy} / Sell {sell}\nLow-stock threshold: {thr}\nDKP: {dkp}",
    },
    "review.btn_color": {"fa": "✏️ رنگ", "en": "✏️ Color"},
    "review.btn_size": {"fa": "✏️ سایز", "en": "✏️ Size"},
    "review.btn_buy": {"fa": "✏️ قیمت خرید", "en": "✏️ Buy price"},
    "review.btn_sell": {"fa": "✏️ قیمت فروش", "en": "✏️ Sell price"},
    "review.btn_thr": {"fa": "✏️ حد آستانه", "en": "✏️ Threshold"},
    "review.btn_dkp": {"fa": "🏷 کدهای دیجی‌کالا", "en": "🏷 DigiKala codes"},
    "review.btn_back_product": {"fa": "◀️ بازگشت به محصول", "en": "◀️ Back to product"},
    "review.btn_back_variant": {"fa": "◀️ بازگشت به تنوع", "en": "◀️ Back to variant"},
    "review.dkp_title": {
        "fa": "🏷 کدهای دیجی‌کالای «{label}»:\nبرای حذف روی هر کد بزنید.",
        "en": "🏷 DigiKala codes for “{label}”:\nTap a code to remove it.",
    },
    "review.dkp_none": {"fa": "هنوز کدی ثبت نشده.", "en": "No codes yet."},
    "review.btn_dkp_add": {"fa": "➕ افزودن کد", "en": "➕ Add code"},
    "review.ask_name_fa": {"fa": "نام فارسی جدید:", "en": "New Persian name:"},
    "review.ask_name_en": {"fa": "نام انگلیسی جدید (یا «-» برای خالی کردن):", "en": "New English name (or \"-\" to clear):"},
    "review.ask_color": {"fa": "رنگ جدید (یا «-» برای خالی):", "en": "New color (or \"-\" for none):"},
    "review.ask_size": {"fa": "سایز جدید (یا «-» برای خالی):", "en": "New size (or \"-\" for none):"},
    "review.ask_buy": {"fa": "قیمت خرید پیش‌فرض جدید (تومان):", "en": "New default buy price (Toman):"},
    "review.ask_sell": {"fa": "قیمت فروش پیش‌فرض جدید (تومان):", "en": "New default sell price (Toman):"},
    "review.ask_thr": {"fa": "حد آستانه کمبود جدید (عدد):", "en": "New low-stock threshold (number):"},
    "review.ask_dkp": {"fa": "کد دیجی‌کالای جدید:", "en": "New DigiKala code:"},
    "review.saved": {"fa": "✅ ذخیره شد.", "en": "✅ Saved."},
    "review.bad_num": {"fa": "لطفاً یک عدد بفرستید.", "en": "Please send a number."},
    "review.err_name_blank": {"fa": "نام فارسی نمی‌تواند خالی باشد.", "en": "The Persian name can't be empty."},
    "review.err_name_taken": {"fa": "محصول دیگری همین نام فارسی را دارد.", "en": "Another product already has this Persian name."},
    "review.err_variant_dupe": {"fa": "این ترکیب رنگ/سایز برای این محصول تکراری است.", "en": "That color/size combo already exists for this product."},
    "review.err_dkp_blank": {"fa": "کد خالی است.", "en": "The code is empty."},
    "review.err_dkp_taken": {"fa": "این کد قبلاً برای تنوع دیگری ثبت شده.", "en": "That code is already used by another variant."},
    "review.done_all": {
        "fa": "🎉 همهٔ محصولات بازبینی شدند ({total} محصول).",
        "en": "🎉 Every product has been reviewed ({total} products).",
    },
    "review.done_pass": {
        "fa": "به انتهای فهرست رسیدید. {left} محصول هنوز بازبینی نشده (رد شده‌ها) — دفعهٔ بعد از همان‌جا ادامه می‌دهید.",
        "en": "Reached the end of the list. {left} product(s) still need review (the skipped ones) — starting again resumes there.",
    },
    "review.empty": {"fa": "هیچ محصولی در پایگاه داده نیست.", "en": "There are no products in the database."},
    "review.status": {
        "fa": "🛠 وضعیت بازبینی\nبازبینی‌شده: {done} / {total}\nباقی‌مانده: {left}\nمحصول بعدی: {next}",
        "en": "🛠 Review status\nReviewed: {done} / {total}\nRemaining: {left}\nNext up: {next}",
    },
    "review.status_none": {"fa": "— (همه بازبینی شده)", "en": "— (all reviewed)"},
    "review.btn_reset": {"fa": "🔄 شروع دوبارهٔ بازبینی", "en": "🔄 Restart the review"},
    "review.reset_confirm": {
        "fa": "پرچم بازبینی همهٔ محصولات پاک شود تا از اول شروع شود؟",
        "en": "Clear every product's reviewed flag and start the pass over?",
    },
    "review.btn_reset_yes": {"fa": "بله، از اول", "en": "Yes, start over"},
    "review.reset_done": {"fa": "🔄 بازبینی صفر شد ({n} محصول). دوباره «بازبینی محصولات» را بزنید.", "en": "🔄 Review reset ({n} products). Tap “Review Catalog” again."},

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
