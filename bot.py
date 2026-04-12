import os
import logging
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
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
)
from prices import get_price, get_prices_bulk

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
ASK_TICKER, ASK_QUANTITY, ASK_PRICE = range(3)

# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *BIST Portföy Botu'na hoş geldiniz!*\n\n"
        "📌 *Komutlar:*\n"
        "• `/ekle` — Yeni hisse ekle\n"
        "• `/portfoy` veya `!portföy` — Portföyü göster\n"
        "• `/sil GARAN` — Belirli hisseyi sil\n"
        "• `/temizle` — Tüm portföyü temizle\n"
        "• `/liste` — Hisselerimi listele\n\n"
        "💡 Grup sohbetlerinde `!portföy` yazarak portföyü görebilirsiniz."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  /ekle — Adım adım hisse ekleme
# ─────────────────────────────────────────────
async def ekle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📊 *Hisse Ekleme*\n\nHangi hisseyi eklemek istiyorsunuz?\n"
        "_(Örnek: GARAN, THYAO, EREGL)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_TICKER


async def ask_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ticker = update.message.text.strip().upper()

    # Basit doğrulama
    if not ticker.isalpha() or len(ticker) > 8:
        await update.message.reply_text(
            "❌ Geçersiz hisse kodu. Lütfen sadece harf içeren bir kod girin (ör: GARAN)."
        )
        return ASK_TICKER

    # Fiyat kontrolü
    await update.message.reply_text(f"🔍 *{ticker}* kontrol ediliyor...", parse_mode="Markdown")
    price = get_price(ticker)
    if price is None:
        await update.message.reply_text(
            f"❌ *{ticker}* bulunamadı. Hisse kodunu kontrol edip tekrar deneyin.",
            parse_mode="Markdown",
        )
        return ASK_TICKER

    context.user_data["ticker"] = ticker
    context.user_data["current_price"] = price

    await update.message.reply_text(
        f"✅ *{ticker}* bulundu! Güncel fiyat: *{price:.2f} ₺*\n\n"
        f"Kaç adet aldınız?",
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
        await update.message.reply_text("❌ Geçersiz adet. Lütfen pozitif bir sayı girin.")
        return ASK_QUANTITY

    context.user_data["quantity"] = quantity

    await update.message.reply_text(
        f"💰 Kaç TL'den (ortalama maliyet) aldınız?\n"
        f"_(Örnek: 45.50)_",
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
        await update.message.reply_text("❌ Geçersiz fiyat. Lütfen pozitif bir sayı girin.")
        return ASK_PRICE

    user_id = update.effective_user.id
    ticker = context.user_data["ticker"]
    quantity = context.user_data["quantity"]
    current_price = context.user_data["current_price"]

    add_holding(user_id, ticker, quantity, avg_cost)

    total_cost = quantity * avg_cost
    total_value = quantity * current_price
    pnl = total_value - total_cost
    pnl_pct = (pnl / total_cost) * 100 if total_cost > 0 else 0
    emoji = "🟢" if pnl >= 0 else "🔴"

    await update.message.reply_text(
        f"✅ *{ticker}* portföye eklendi!\n\n"
        f"📦 Adet: {quantity:,.0f}\n"
        f"💵 Maliyet: {avg_cost:.2f} ₺\n"
        f"📈 Güncel Fiyat: {current_price:.2f} ₺\n"
        f"{emoji} K/Z: {pnl:+,.2f} ₺ ({pnl_pct:+.2f}%)\n"
        f"💼 Toplam Değer: {total_value:,.2f} ₺",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ İşlem iptal edildi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  !portföy / /portfoy — Portföy özeti
# ─────────────────────────────────────────────
async def show_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    holdings = get_holdings(user_id)

    if not holdings:
        await update.message.reply_text(
            "📂 Portföyünüz boş. `/ekle` komutuyla hisse ekleyin.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("⏳ Fiyatlar alınıyor...")

    tickers = [row[0] for row in holdings]
    prices = get_prices_bulk(tickers)

    lines = []
    total_cost = 0
    total_value = 0

    for row in holdings:
        ticker, quantity, avg_cost = row
        price = prices.get(ticker)
        if price is None:
            lines.append(f"⚠️ *{ticker}*: Fiyat alınamadı")
            continue

        cost = quantity * avg_cost
        value = quantity * price
        pnl = value - cost
        pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
        emoji = "🟢" if pnl >= 0 else "🔴"

        total_cost += cost
        total_value += value

        lines.append(
            f"{emoji} *{ticker}*\n"
            f"  Adet: {quantity:,.0f} | Maliyet: {avg_cost:.2f}₺ | Fiyat: {price:.2f}₺\n"
            f"  K/Z: {pnl:+,.2f}₺ ({pnl_pct:+.2f}%)"
        )

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost) * 100 if total_cost > 0 else 0
    total_emoji = "🟢" if total_pnl >= 0 else "🔴"

    header = "📊 *BIST Portföy Durumu*\n" + "─" * 28 + "\n"
    body = "\n\n".join(lines)
    footer = (
        "\n\n" + "─" * 28 + "\n"
        f"💼 *Toplam Yatırım:* {total_cost:,.2f} ₺\n"
        f"💰 *Güncel Değer:* {total_value:,.2f} ₺\n"
        f"{total_emoji} *Toplam K/Z:* {total_pnl:+,.2f} ₺ ({total_pnl_pct:+.2f}%)"
    )

    await update.message.reply_text(header + body + footer, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  /sil GARAN
# ─────────────────────────────────────────────
async def sil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Kullanım: `/sil GARAN`", parse_mode="Markdown")
        return

    ticker = context.args[0].upper()
    removed = remove_holding(user_id, ticker)
    if removed:
        await update.message.reply_text(f"🗑 *{ticker}* portföyden silindi.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"❌ *{ticker}* portföyünüzde bulunamadı.", parse_mode="Markdown"
        )


# ─────────────────────────────────────────────
#  /temizle
# ─────────────────────────────────────────────
async def temizle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    clear_portfolio(user_id)
    await update.message.reply_text("🗑 Portföyünüz temizlendi.")


# ─────────────────────────────────────────────
#  /liste
# ─────────────────────────────────────────────
async def liste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    holdings = get_holdings(user_id)

    if not holdings:
        await update.message.reply_text(
            "📂 Portföyünüz boş. `/ekle` komutuyla hisse ekleyin.", parse_mode="Markdown"
        )
        return

    lines = ["📋 *Portföyünüzdeki Hisseler:*\n"]
    for i, (ticker, quantity, avg_cost) in enumerate(holdings, 1):
        lines.append(f"{i}. *{ticker}* — {quantity:,.0f} adet @ {avg_cost:.2f} ₺")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  !portföy mesaj tetikleyicisi (grup)
# ─────────────────────────────────────────────
async def message_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if "!portföy" in text.lower() or "!portfoy" in text.lower():
        await show_portfolio(update, context)


# ─────────────────────────────────────────────
#  Ana uygulama
# ─────────────────────────────────────────────
def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set!")

    init_db()

    app = Application.builder().token(token).build()

    # Hisse ekleme konuşması
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("ekle", ekle_start)],
        states={
            ASK_TICKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_quantity)],
            ASK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_price)],
            ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_holding)],
        },
        fallbacks=[CommandHandler("iptal", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yardim", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("portfoy", show_portfolio))
    app.add_handler(CommandHandler("sil", sil))
    app.add_handler(CommandHandler("temizle", temizle))
    app.add_handler(CommandHandler("liste", liste))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_trigger))

    logger.info("Bot başlatıldı...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
