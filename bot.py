import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from database import (
    init_db,
    add_holding,
    get_holdings,
    remove_holding,
    clear_portfolio,
    set_cash,
    get_cash,
)
from prices import get_price, get_prices_bulk

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
ASK_TICKER, ASK_QUANTITY, ASK_PRICE, ASK_CASH = range(4)

# ─────────────────────────────────────────────
#  Sahip kontrolü
# ─────────────────────────────────────────────
# Railway'de OWNER_ID değişkenini kendi Telegram ID'nle ayarla.
# ID'ni öğrenmek için @userinfobot'a yaz.
# OWNER_ID=0 ise kısıtlama yok (herkes ekleyip çıkarabilir).
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

# Portföyü görüntülerken hangi kullanıcının verisini göster
# Gruptaki !portföy, her zaman SAHİBİN portföyünü gösterir
def owner_id() -> int:
    return OWNER_ID if OWNER_ID else 0

def is_owner(user_id: int) -> bool:
    return OWNER_ID == 0 or user_id == OWNER_ID

async def deny(update: Update) -> None:
    """Yetkisiz işlem uyarısı."""
    if update.callback_query:
        await update.callback_query.answer(
            "⛔ Bu işlemi sadece portföy sahibi yapabilir.", show_alert=True
        )
    else:
        await update.message.reply_text("⛔ Bu işlemi sadece portföy sahibi yapabilir.")


# ─────────────────────────────────────────────
#  Ana Menü
# ─────────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Portföy Göster", callback_data="portfoy"),
            InlineKeyboardButton("➕ Hisse Ekle",     callback_data="ekle"),
        ],
        [
            InlineKeyboardButton("💵 Nakit Güncelle", callback_data="nakit"),
            InlineKeyboardButton("🗑 Hisse Sil",      callback_data="sil_menu"),
        ],
        [
            InlineKeyboardButton("📋 Listele",            callback_data="liste"),
            InlineKeyboardButton("🧹 Portföyü Temizle",   callback_data="temizle_onay"),
        ],
    ])


async def send_main_menu(update: Update, text: str = None) -> None:
    msg = text or "👋 *BIST Portföy Botu*\n\nAşağıdaki menüden işlem seçin:"
    kb = main_menu_keyboard()
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(update)


# ─────────────────────────────────────────────
#  Portföy hesaplama yardımcısı
# ─────────────────────────────────────────────
def build_portfolio_text(holdings, prices, cash: float) -> str:
    lines = []
    total_cost = 0
    total_value = 0

    for ticker, quantity, avg_cost in holdings:
        price = prices.get(ticker)
        if price is None:
            lines.append((None, 0, f"⚠️ *{ticker}*: Fiyat alınamadı"))
            continue
        cost = quantity * avg_cost
        value = quantity * price
        pnl = value - cost
        pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
        emoji = "🟢" if pnl >= 0 else "🔴"
        total_cost += cost
        total_value += value
        lines.append((value, ticker, emoji, quantity, avg_cost, price, pnl, pnl_pct, cost))

    grand_total = total_value + cash  # hisse + nakit

    # Satırları formatla
    formatted = []
    for item in lines:
        if item[0] is None:
            formatted.append(item[2])  # hata satırı
            continue
        value, ticker, emoji, quantity, avg_cost, price, pnl, pnl_pct, cost = item
        alloc = (value / grand_total * 100) if grand_total > 0 else 0
        formatted.append(
            f"{emoji} *{ticker}* — %{alloc:.1f}\n"
            f"  {quantity:,.0f} adet | {avg_cost:.2f}₺ → {price:.2f}₺\n"
            f"  K/Z: {pnl:+,.2f}₺ ({pnl_pct:+.2f}%)"
        )

    # Nakit satırı
    if cash > 0:
        cash_alloc = (cash / grand_total * 100) if grand_total > 0 else 0
        formatted.append(f"💵 *Nakit* — %{cash_alloc:.1f}\n  {cash:,.2f} ₺")

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    total_emoji = "🟢" if total_pnl >= 0 else "🔴"

    text = (
        "📊 *BIST Portföy Durumu*\n"
        + "─" * 28 + "\n"
        + "\n\n".join(formatted)
        + "\n\n" + "─" * 28 + "\n"
        f"💼 *Hisse Yatırımı:* {total_cost:,.2f} ₺\n"
        f"📈 *Hisse Değeri:* {total_value:,.2f} ₺\n"
    )
    if cash > 0:
        text += f"💵 *Nakit:* {cash:,.2f} ₺\n"
    text += (
        f"🏦 *Toplam Portföy:* {grand_total:,.2f} ₺\n"
        f"{total_emoji} *Hisse K/Z:* {total_pnl:+,.2f} ₺ ({total_pnl_pct:+.2f}%)"
    )
    return text


# ─────────────────────────────────────────────
#  Callback: Portföy Göster
# ─────────────────────────────────────────────
async def cb_portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    holdings = get_holdings(user_id)
    cash = get_cash(user_id)

    if not holdings and cash == 0:
        await query.edit_message_text(
            "📂 Portföyünüz boş.\n\nHisse eklemek için ➕, nakit için 💵 butonunu kullanın.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
            ]])
        )
        return

    await query.edit_message_text("⏳ Fiyatlar alınıyor...")

    tickers = [row[0] for row in holdings]
    prices = get_prices_bulk(tickers) if tickers else {}

    text = build_portfolio_text(holdings, prices, cash)

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Yenile",    callback_data="portfoy"),
            InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu"),
        ]])
    )


# ─────────────────────────────────────────────
#  Callback: Nakit Güncelle
# ─────────────────────────────────────────────
async def cb_nakit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    mevcut = get_cash(user_id)
    await query.edit_message_text(
        f"💵 *Nakit Güncelle*\n\n"
        f"Mevcut nakit: *{mevcut:,.2f} ₺*\n\n"
        f"Yeni nakit bakiyenizi girin:\n_(Örnek: 12500 veya 12500.50)_\n\n"
        f"İptal için /iptal yazın.",
        parse_mode="Markdown",
    )
    return ASK_CASH


async def save_cash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", ".")
    try:
        amount = float(text)
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Geçersiz tutar. Sıfır veya pozitif bir sayı girin.")
        return ASK_CASH

    set_cash(update.effective_user.id, amount)
    await update.message.reply_text(
        f"✅ Nakit bakiye *{amount:,.2f} ₺* olarak güncellendi.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Callback: Listele
# ─────────────────────────────────────────────
async def cb_liste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    holdings = get_holdings(user_id)
    cash = get_cash(user_id)

    if not holdings and cash == 0:
        await query.edit_message_text(
            "📂 Portföyünüz boş.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
            ]])
        )
        return

    lines = ["📋 *Portföyünüzdeki Pozisyonlar:*\n"]
    for i, (ticker, quantity, avg_cost) in enumerate(holdings, 1):
        lines.append(f"{i}. *{ticker}* — {quantity:,.0f} adet @ {avg_cost:.2f} ₺")
    if cash > 0:
        lines.append(f"\n💵 *Nakit:* {cash:,.2f} ₺")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
        ]])
    )


# ─────────────────────────────────────────────
#  Callback: Sil Menüsü
# ─────────────────────────────────────────────
async def cb_sil_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    await query.answer()
    user_id = update.effective_user.id
    holdings = get_holdings(user_id)

    if not holdings:
        await query.edit_message_text(
            "📂 Portföyünüzde hisse yok.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
            ]])
        )
        return

    buttons = [
        [InlineKeyboardButton(f"🗑 {ticker} ({quantity:,.0f} adet)", callback_data=f"sil_{ticker}")]
        for ticker, quantity, _ in holdings
    ]
    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")])

    await query.edit_message_text(
        "🗑 *Hangi hisseyi silmek istiyorsunuz?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cb_sil_hisse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    await query.answer()
    user_id = update.effective_user.id
    ticker = query.data.replace("sil_", "")
    removed = remove_holding(user_id, ticker)
    msg = f"✅ *{ticker}* portföyden silindi." if removed else f"❌ *{ticker}* bulunamadı."
    await query.edit_message_text(
        msg,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
        ]])
    )


# ─────────────────────────────────────────────
#  Callback: Temizle
# ─────────────────────────────────────────────
async def cb_temizle_onay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    await query.answer()
    await query.edit_message_text(
        "⚠️ *Tüm portföyü ve nakiti silmek istediğinizden emin misiniz?*\n"
        "Bu işlem geri alınamaz!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Evet, Temizle", callback_data="temizle_evet"),
            InlineKeyboardButton("❌ İptal",         callback_data="menu"),
        ]])
    )


async def cb_temizle_evet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    clear_portfolio(update.effective_user.id)
    await query.edit_message_text(
        "🧹 Portföyünüz ve nakitiniz temizlendi.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
        ]])
    )


# ─────────────────────────────────────────────
#  Hisse Ekleme — ConversationHandler
# ─────────────────────────────────────────────
async def cb_ekle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text(
        "➕ *Hisse Ekleme*\n\n"
        "Hangi hisseyi eklemek istiyorsunuz?\n"
        "_(Örnek: GARAN, THYAO, EREGL)_\n\n"
        "İptal için /iptal yazın.",
        parse_mode="Markdown",
    )
    return ASK_TICKER


async def ekle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        await deny(update)
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ *Hisse Ekleme*\n\n"
        "Hangi hisseyi eklemek istiyorsunuz?\n"
        "_(Örnek: GARAN, THYAO, EREGL)_\n\n"
        "İptal için /iptal yazın.",
        parse_mode="Markdown",
    )
    return ASK_TICKER


async def ask_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ticker = update.message.text.strip().upper()
    if not ticker.isalpha() or len(ticker) > 8:
        await update.message.reply_text("❌ Geçersiz kod. Sadece harf girin (ör: GARAN).")
        return ASK_TICKER

    msg = await update.message.reply_text(f"🔍 *{ticker}* kontrol ediliyor...", parse_mode="Markdown")
    price = get_price(ticker)

    if price is None:
        await msg.edit_text(
            f"❌ *{ticker}* bulunamadı. Hisse kodunu kontrol edip tekrar deneyin.",
            parse_mode="Markdown",
        )
        return ASK_TICKER

    context.user_data["ticker"] = ticker
    context.user_data["current_price"] = price
    await msg.edit_text(
        f"✅ *{ticker}* bulundu! Güncel fiyat: *{price:.2f} ₺*\n\nKaç adet aldınız?",
        parse_mode="Markdown",
    )
    return ASK_QUANTITY


async def ask_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", ".")
    try:
        quantity = float(text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Geçersiz adet. Pozitif bir sayı girin.")
        return ASK_QUANTITY

    context.user_data["quantity"] = quantity
    await update.message.reply_text(
        "💰 Ortalama alış fiyatınız kaç TL?\n_(Örnek: 45.50)_",
        parse_mode="Markdown",
    )
    return ASK_PRICE


async def save_holding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", ".")
    try:
        avg_cost = float(text)
        if avg_cost <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Geçersiz fiyat. Pozitif bir sayı girin.")
        return ASK_PRICE

    user_id = update.effective_user.id
    ticker = context.user_data["ticker"]
    quantity = context.user_data["quantity"]
    current_price = context.user_data["current_price"]

    add_holding(user_id, ticker, quantity, avg_cost)

    cost = quantity * avg_cost
    value = quantity * current_price
    pnl = value - cost
    pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
    emoji = "🟢" if pnl >= 0 else "🔴"
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ *{ticker}* portföye eklendi!\n\n"
        f"📦 Adet: {quantity:,.0f}\n"
        f"💵 Maliyet: {avg_cost:.2f} ₺\n"
        f"📈 Güncel: {current_price:.2f} ₺\n"
        f"{emoji} K/Z: {pnl:+,.2f} ₺ ({pnl_pct:+.2f}%)",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ İşlem iptal edildi.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  !portföy grup tetikleyicisi
# ─────────────────────────────────────────────
async def message_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if "!portföy" in text.lower() or "!portfoy" in text.lower():
        # Grupta her zaman SAHİBİN portföyünü göster
        # OWNER_ID ayarlanmamışsa mesajı yazan kişinin portföyünü göster
        view_id = OWNER_ID if OWNER_ID else update.effective_user.id
        holdings = get_holdings(view_id)
        cash = get_cash(view_id)

        if not holdings and cash == 0:
            await update.message.reply_text("📂 Portföyünüz boş.")
            return

        msg = await update.message.reply_text("⏳ Fiyatlar alınıyor...")
        tickers = [row[0] for row in holdings]
        prices = get_prices_bulk(tickers) if tickers else {}

        text_out = build_portfolio_text(holdings, prices, cash)
        await msg.edit_text(text_out, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  Ana uygulama
# ─────────────────────────────────────────────
def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set!")

    init_db()
    app = Application.builder().token(token).build()

    # Hisse ekleme + nakit güncelleme ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("ekle", ekle_start),
            CallbackQueryHandler(cb_ekle,   pattern="^ekle$"),
            CallbackQueryHandler(cb_nakit,  pattern="^nakit$"),
        ],
        states={
            ASK_TICKER:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_quantity)],
            ASK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_price)],
            ASK_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, save_holding)],
            ASK_CASH:     [MessageHandler(filters.TEXT & ~filters.COMMAND, save_cash)],
        },
        fallbacks=[CommandHandler("iptal", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu",  start))
    app.add_handler(conv_handler)

    app.add_handler(CallbackQueryHandler(send_main_menu,  pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(cb_portfoy,      pattern="^portfoy$"))
    app.add_handler(CallbackQueryHandler(cb_liste,        pattern="^liste$"))
    app.add_handler(CallbackQueryHandler(cb_sil_menu,     pattern="^sil_menu$"))
    app.add_handler(CallbackQueryHandler(cb_sil_hisse,    pattern="^sil_[A-Z]+$"))
    app.add_handler(CallbackQueryHandler(cb_temizle_onay, pattern="^temizle_onay$"))
    app.add_handler(CallbackQueryHandler(cb_temizle_evet, pattern="^temizle_evet$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_trigger))

    logger.info("Bot başlatıldı...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
