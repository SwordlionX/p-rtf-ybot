import os
import logging
from datetime import date as date_type, datetime
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
    sell_holding,
    clear_portfolio,
    set_cash,
    get_cash,
    get_realized_pnl,
    get_trade_history,
    set_starting_capital,
    get_starting_info,
)
from prices import get_price, get_prices_bulk, is_fund

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
ASK_TICKER, ASK_QUANTITY, ASK_PRICE, ASK_CASH, ASK_CAPITAL, ASK_CAPITAL_DATE = range(6)
SAT_TICKER, SAT_QUANTITY, SAT_PRICE = range(6, 9)

# ─────────────────────────────────────────────
#  Sahip kontrolü
# ─────────────────────────────────────────────
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

def is_owner(user_id: int) -> bool:
    return OWNER_ID == 0 or user_id == OWNER_ID

async def deny(update: Update) -> None:
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
            InlineKeyboardButton("📤 Hisse Sat",      callback_data="sat_menu"),
            InlineKeyboardButton("🗑 Pozisyon Sil",   callback_data="sil_menu"),
        ],
        [
            InlineKeyboardButton("💵 Nakit Güncelle",     callback_data="nakit"),
            InlineKeyboardButton("🏦 Başlangıç Sermayesi", callback_data="sermaye"),
        ],
        [
            InlineKeyboardButton("📜 Satış Geçmişi", callback_data="gecmis"),
            InlineKeyboardButton("📋 Listele",        callback_data="liste"),
        ],
        [
            InlineKeyboardButton("🧹 Portföyü Temizle", callback_data="temizle_onay"),
        ],
    ])


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE = None, text: str = None) -> None:
    if update.callback_query:
        await update.callback_query.answer()
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
#  Portföy metni oluştur
# ─────────────────────────────────────────────
def _performance_block(grand_total: float, start_info: dict) -> str:
    """Başlangıçtan bu yana getiri, aylık ve yıllık öngörü."""
    capital = start_info.get("capital", 0)
    start_date_str = start_info.get("date")
    if not capital or not start_date_str:
        return ""

    try:
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        return ""

    today = date_type.today()
    days = (today - start_dt).days
    if days <= 0:
        return ""

    net_pnl = grand_total - capital
    net_pct = (net_pnl / capital) * 100

    # Bileşik getiri oranı (günlük)
    daily_rate = (grand_total / capital) ** (1 / days) - 1
    monthly_pct = ((1 + daily_rate) ** 30 - 1) * 100
    annual_pct  = ((1 + daily_rate) ** 365 - 1) * 100

    net_emoji = "🟢" if net_pnl >= 0 else "🔴"

    # Süreyi oku
    months = days // 30
    rem_days = days % 30
    if months > 0:
        sure = f"{months} ay {rem_days} gün" if rem_days else f"{months} ay"
    else:
        sure = f"{days} gün"

    return (
        f"\n{'─' * 28}\n"
        f"🏦 *Başlangıç:* {capital:,.2f} ₺  _{start_date_str}_\n"
        f"⏱ *Süre:* {sure}\n"
        f"{net_emoji} *Toplam Getiri:* {net_pnl:+,.2f} ₺ ({net_pct:+.2f}%)\n"
        f"📅 *Aylık Getiri:* %{monthly_pct:+.2f}\n"
        f"📆 *Yıllık Öngörü:* %{annual_pct:+.2f}"
    )


def build_portfolio_text(holdings, prices, cash: float, realized_pnl: float = 0.0, start_info: dict = None) -> str:
    stock_items = []   # (value, ticker, emoji, quantity, avg_cost, price, pnl, pnl_pct)
    fund_items  = []   # same tuple, for TEFAS funds
    errors      = []   # error strings

    stock_cost  = 0
    stock_value = 0
    fund_cost   = 0
    fund_value  = 0

    for ticker, quantity, avg_cost in holdings:
        price = prices.get(ticker)
        if price is None:
            errors.append(f"⚠️ *{ticker}*: Fiyat alınamadı")
            continue
        cost  = quantity * avg_cost
        value = quantity * price
        pnl   = value - cost
        pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
        emoji = "🟢" if pnl >= 0 else "🔴"
        row   = (value, ticker, emoji, quantity, avg_cost, price, pnl, pnl_pct)
        if is_fund(ticker):
            fund_cost  += cost
            fund_value += value
            fund_items.append(row)
        else:
            stock_cost  += cost
            stock_value += value
            stock_items.append(row)

    total_value  = stock_value + fund_value
    grand_total  = total_value + cash
    liquid_value = fund_value + cash   # fon + nakit = "likit"

    # ── Hisseler bölümü ──────────────────────────────────────
    stock_lines = []
    for value, ticker, emoji, quantity, avg_cost, price, pnl, pnl_pct in stock_items:
        stock_lines.append(
            f"{emoji} *{ticker}*\n"
            f"  {quantity:,.0f} adet | {avg_cost:.2f}₺ → {price:.2f}₺\n"
            f"  K/Z: {pnl:+,.2f}₺ ({pnl_pct:+.2f}%)"
        )

    # ── Yatırım Fonu bölümü ───────────────────────────────────
    fund_lines = []
    for value, ticker, emoji, quantity, avg_cost, price, pnl, pnl_pct in fund_items:
        fund_lines.append(
            f"{emoji} *{ticker}* (fon)\n"
            f"  {quantity:,.2f} pay | {avg_cost:.6f}₺ → {price:.6f}₺\n"
            f"  Değer: {value:,.2f}₺  K/Z: {pnl:+,.2f}₺ ({pnl_pct:+.2f}%)"
        )

    # ── Metni birleştir ───────────────────────────────────────
    text = "📊 *BIST Portföy Durumu*\n" + "─" * 28 + "\n"

    if errors:
        text += "\n".join(errors) + "\n\n"

    if stock_lines:
        text += "📈 *Hisseler*\n" + "\n\n".join(stock_lines)
    else:
        text += "_(Hisse yok)_"

    if fund_lines or cash > 0:
        text += "\n\n" + "─" * 28 + "\n"
        text += "💵 *Yatırım Fonu / Nakit*\n"
        if fund_lines:
            text += "\n\n".join(fund_lines)
        if cash > 0:
            cash_alloc = (cash / grand_total * 100) if grand_total > 0 else 0
            if fund_lines:
                text += "\n\n"
            text += f"💵 *Nakit:* {cash:,.2f} ₺"

    # ── Özet ─────────────────────────────────────────────────
    total_pnl     = (stock_value + fund_value) - (stock_cost + fund_cost)
    total_cost_all = stock_cost + fund_cost
    total_pnl_pct  = (total_pnl / total_cost_all * 100) if total_cost_all > 0 else 0
    total_emoji    = "🟢" if total_pnl >= 0 else "🔴"
    real_emoji     = "🟢" if realized_pnl >= 0 else "🔴"

    liquid_alloc = (liquid_value / grand_total * 100) if grand_total > 0 else 0
    stock_alloc  = (stock_value  / grand_total * 100) if grand_total > 0 else 0

    text += "\n\n" + "─" * 28 + "\n"
    text += (
        f"📈 *Hisse Değeri:* {stock_value:,.2f} ₺ (%{stock_alloc:.1f})\n"
        f"💵 *Fon + Nakit:* {liquid_value:,.2f} ₺ (%{liquid_alloc:.1f})\n"
        f"🏦 *Toplam Portföy:* {grand_total:,.2f} ₺\n"
        f"{total_emoji} *Anlık K/Z:* {total_pnl:+,.2f} ₺ ({total_pnl_pct:+.2f}%)"
    )
    if realized_pnl != 0:
        text += f"\n{real_emoji} *Gerçekleşen K/Z:* {realized_pnl:+,.2f} ₺"

    if start_info:
        text += _performance_block(grand_total, start_info)

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
    realized = get_realized_pnl(user_id)
    start_info = get_starting_info(user_id)
    text = build_portfolio_text(holdings, prices, cash, realized, start_info)

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Yenile",    callback_data="portfoy"),
            InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu"),
        ]])
    )


# ─────────────────────────────────────────────
#  Callback: Satış Geçmişi
# ─────────────────────────────────────────────
async def cb_gecmis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    trades = get_trade_history(user_id, limit=15)
    realized = get_realized_pnl(user_id)

    if not trades:
        await query.edit_message_text(
            "📜 Henüz satış işlemi yok.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
            ]])
        )
        return

    lines = ["📜 *Son Satışlar:*\n"]
    for ticker, qty, avg_cost, sell_price, pnl, sold_at in trades:
        emoji = "🟢" if pnl >= 0 else "🔴"
        date = sold_at[:10] if sold_at else "?"
        lines.append(
            f"{emoji} *{ticker}* — {date}\n"
            f"  {qty:,.0f} adet | {avg_cost:.2f}₺ → {sell_price:.2f}₺\n"
            f"  K/Z: {pnl:+,.2f} ₺"
        )

    total_emoji = "🟢" if realized >= 0 else "🔴"
    lines.append(f"\n{total_emoji} *Toplam Gerçekleşen K/Z: {realized:+,.2f} ₺*")

    await query.edit_message_text(
        "\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
        ]])
    )


# ─────────────────────────────────────────────
#  Hisse Satma — ConversationHandler
# ─────────────────────────────────────────────
async def cb_sat_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return ConversationHandler.END
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
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(f"📤 {ticker} ({qty:,.0f} adet)", callback_data=f"satx_{ticker}")]
        for ticker, qty, _ in holdings
    ]
    buttons.append([InlineKeyboardButton("⬅️ İptal", callback_data="menu")])

    await query.edit_message_text(
        "📤 *Hangi hisseyi satmak istiyorsunuz?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return SAT_TICKER


async def sat_ticker_secildi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    ticker = query.data.replace("satx_", "")
    user_id = update.effective_user.id

    holdings = {t: (q, c) for t, q, c in get_holdings(user_id)}
    if ticker not in holdings:
        await query.edit_message_text("❌ Hisse bulunamadı.")
        return ConversationHandler.END

    qty, avg_cost = holdings[ticker]
    context.user_data["sat_ticker"] = ticker
    context.user_data["sat_max_qty"] = qty
    context.user_data["sat_avg_cost"] = avg_cost

    await query.edit_message_text(
        f"📤 *{ticker}* satışı\n\n"
        f"Eldeki adet: *{qty:,.0f}*\n"
        f"Ortalama maliyet: *{avg_cost:.2f} ₺*\n\n"
        f"Kaç adet satmak istiyorsunuz?\n"
        f"_(Tamamı için {qty:,.0f} yazın)_\n\n"
        f"İptal için /iptal yazın.",
        parse_mode="Markdown",
    )
    return SAT_QUANTITY


async def sat_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", ".")
    try:
        qty = float(text)
        max_qty = context.user_data["sat_max_qty"]
        if qty <= 0 or qty > max_qty:
            raise ValueError
    except (ValueError, KeyError):
        await update.message.reply_text(
            f"❌ Geçersiz adet. 0 ile {context.user_data.get('sat_max_qty', '?'):,.0f} arasında girin."
        )
        return SAT_QUANTITY

    context.user_data["sat_quantity"] = qty
    ticker = context.user_data["sat_ticker"]
    await update.message.reply_text(
        f"💰 *{ticker}* için satış fiyatı kaç TL?\n_(Örnek: 58.75)_",
        parse_mode="Markdown",
    )
    return SAT_PRICE


async def sat_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", ".")
    try:
        sell_price = float(text)
        if sell_price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Geçersiz fiyat. Pozitif bir sayı girin.")
        return SAT_PRICE

    user_id = update.effective_user.id
    ticker = context.user_data["sat_ticker"]
    qty = context.user_data["sat_quantity"]
    avg_cost = context.user_data["sat_avg_cost"]

    result = sell_holding(user_id, ticker, qty, sell_price)
    context.user_data.clear()

    if result is None:
        await update.message.reply_text("❌ Satış yapılamadı. Hisse bulunamadı.")
        return ConversationHandler.END

    pnl = result["realized_pnl"]
    remaining = result["remaining"]
    sold_qty = result["sold_qty"]
    pnl_pct = (pnl / (avg_cost * sold_qty) * 100) if avg_cost > 0 else 0
    emoji = "🟢" if pnl >= 0 else "🔴"

    total_realized = get_realized_pnl(user_id)
    total_emoji = "🟢" if total_realized >= 0 else "🔴"

    kalan_txt = f"📦 Kalan: {remaining:,.0f} adet" if remaining > 0.001 else "📦 Pozisyon tamamen kapatıldı"

    await update.message.reply_text(
        f"✅ *{ticker}* satışı gerçekleşti!\n\n"
        f"📤 Satılan: {sold_qty:,.0f} adet @ {sell_price:.2f} ₺\n"
        f"💵 Maliyet: {avg_cost:.2f} ₺\n"
        f"{kalan_txt}\n\n"
        f"{emoji} *Bu satış K/Z:* {pnl:+,.2f} ₺ ({pnl_pct:+.2f}%)\n"
        f"{total_emoji} *Toplam Gerçekleşen K/Z:* {total_realized:+,.2f} ₺",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Callback: Nakit Güncelle
# ─────────────────────────────────────────────
async def cb_nakit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return ConversationHandler.END
    await query.answer()
    mevcut = get_cash(update.effective_user.id)
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
#  Callback: Sil Menüsü (K/Z kaydı olmadan siler)
# ─────────────────────────────────────────────
async def cb_sil_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    await query.answer()
    holdings = get_holdings(update.effective_user.id)

    if not holdings:
        await query.edit_message_text(
            "📂 Portföyünüzde hisse yok.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
            ]])
        )
        return

    buttons = [
        [InlineKeyboardButton(f"🗑 {ticker} ({qty:,.0f} adet)", callback_data=f"sil_{ticker}")]
        for ticker, qty, _ in holdings
    ]
    buttons.append([InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")])

    await query.edit_message_text(
        "🗑 *Hangi pozisyonu silmek istiyorsunuz?*\n_(K/Z kaydı tutulmaz — satış için 📤 Sat kullanın)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cb_sil_hisse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    await query.answer()
    ticker = query.data.replace("sil_", "")
    removed = remove_holding(update.effective_user.id, ticker)
    msg = f"✅ *{ticker}* portföyden silindi." if removed else f"❌ *{ticker}* bulunamadı."
    await query.edit_message_text(
        msg, parse_mode="Markdown",
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
        "⚠️ *Tüm portföyü, nakiti ve satış geçmişini silmek istediğinizden emin misiniz?*\n"
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
        "🧹 Portföy, nakit ve satış geçmişi temizlendi.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Ana Menü", callback_data="menu")
        ]])
    )


# ─────────────────────────────────────────────
#  Tek seferlik toplu yükleme — /yukle
# ─────────────────────────────────────────────
SEED_DATA = [
    ("AAGYO",  145,    21.10),
    ("AKBNK",  38,     77.21),
    ("ALVES",  1415,   3.32),
    ("CIMSA",  44,     48.79),
    ("EKGYO",  324,    21.39),
    ("GARAN",  30,     133.31),
    ("GRSEL",  16,     310.28),
    ("SELEC",  144,    80.53),
    ("YKBNK",  77,     38.50),
    ("NSP",    50324,  1.442022),
]

async def cmd_yukle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id):
        await deny(update)
        return
    user_id = update.effective_user.id
    msg = await update.message.reply_text("⏳ Portföy yükleniyor...")
    lines = []
    for ticker, qty, cost in SEED_DATA:
        add_holding(user_id, ticker, qty, cost)
        lines.append(f"✅ {ticker}: {qty:,.0f} adet @ {cost} ₺")
    lines.append(f"\n🎉 *{len(SEED_DATA)} pozisyon yüklendi!*")
    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  Başlangıç Sermayesi
# ─────────────────────────────────────────────
async def cb_sermaye(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return ConversationHandler.END
    await query.answer()
    info = get_starting_info(update.effective_user.id)
    if info["capital"] > 0:
        mevcut_txt = f"*{info['capital']:,.2f} ₺*  _{info['date']}_"
    else:
        mevcut_txt = "_henüz ayarlanmamış_"
    await query.edit_message_text(
        f"🏦 *Başlangıç Sermayesi*\n\n"
        f"Mevcut: {mevcut_txt}\n\n"
        f"Portföyü başlattığınızda sahip olduğunuz *toplam tutarı* girin.\n"
        f"_(Örnek: 100000)_\n\n"
        f"İptal için /iptal yazın.",
        parse_mode="Markdown",
    )
    return ASK_CAPITAL


async def save_capital(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Geçersiz tutar. Pozitif bir sayı girin.")
        return ASK_CAPITAL

    context.user_data["start_capital"] = amount
    await update.message.reply_text(
        f"📅 Portföyü başlattığınız *tarihi* girin:\n"
        f"_(Örnek: 01.01.2025 veya 2025-01-01)_\n\n"
        f"İptal için /iptal yazın.",
        parse_mode="Markdown",
    )
    return ASK_CAPITAL_DATE


async def save_capital_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    # Hem GG.AA.YYYY hem YYYY-MM-DD formatını kabul et
    parsed = None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue

    if parsed is None or parsed > date_type.today():
        await update.message.reply_text(
            "❌ Geçersiz tarih. Geçmiş bir tarih girin.\n_(Örnek: 01.01.2025)_",
            parse_mode="Markdown",
        )
        return ASK_CAPITAL_DATE

    amount = context.user_data.pop("start_capital")
    date_str = parsed.strftime("%Y-%m-%d")
    set_starting_capital(update.effective_user.id, amount, date_str)

    days = (date_type.today() - parsed).days
    months = days // 30
    sure = f"{months} ay {days % 30} gün" if months else f"{days} gün"

    await update.message.reply_text(
        f"✅ Kaydedildi!\n\n"
        f"🏦 Başlangıç: *{amount:,.2f} ₺*\n"
        f"📅 Tarih: *{parsed.strftime('%d.%m.%Y')}*\n"
        f"⏱ Geçen süre: *{sure}*\n\n"
        f"Artık portföy ekranında toplam getiri, aylık ve yıllık öngörü görünecek.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Hisse Ekleme
# ─────────────────────────────────────────────
async def cb_ekle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await deny(update)
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text(
        "➕ *Hisse Ekleme*\n\nHangi hisseyi eklemek istiyorsunuz?\n"
        "_(Örnek: GARAN, THYAO, NSP)_\n\nİptal için /iptal yazın.",
        parse_mode="Markdown",
    )
    return ASK_TICKER


async def ekle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        await deny(update)
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ *Hisse Ekleme*\n\nHangi hisseyi eklemek istiyorsunuz?\n"
        "_(Örnek: GARAN, THYAO, NSP)_\n\nİptal için /iptal yazın.",
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
        view_id = OWNER_ID if OWNER_ID else update.effective_user.id
        holdings = get_holdings(view_id)
        cash = get_cash(view_id)

        if not holdings and cash == 0:
            await update.message.reply_text("📂 Portföy boş.")
            return

        msg = await update.message.reply_text("⏳ Fiyatlar alınıyor...")
        tickers = [row[0] for row in holdings]
        prices = get_prices_bulk(tickers) if tickers else {}
        realized = get_realized_pnl(view_id)
        start_info = get_starting_info(view_id)
        text_out = build_portfolio_text(holdings, prices, cash, realized, start_info)
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

    # Hisse ekleme konuşması
    ekle_conv = ConversationHandler(
        entry_points=[
            CommandHandler("ekle", ekle_start),
            CallbackQueryHandler(cb_ekle, pattern="^ekle$"),
        ],
        states={
            ASK_TICKER:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_quantity)],
            ASK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_price)],
            ASK_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, save_holding)],
        },
        fallbacks=[CommandHandler("iptal", cancel)],
    )

    # Hisse satma konuşması
    sat_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_sat_menu, pattern="^sat_menu$"),
        ],
        states={
            SAT_TICKER:   [CallbackQueryHandler(sat_ticker_secildi, pattern="^satx_")],
            SAT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, sat_quantity)],
            SAT_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, sat_price)],
        },
        fallbacks=[CommandHandler("iptal", cancel)],
    )

    # Nakit güncelleme konuşması
    nakit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_nakit, pattern="^nakit$")],
        states={
            ASK_CASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_cash)],
        },
        fallbacks=[CommandHandler("iptal", cancel)],
    )

    # Başlangıç sermayesi konuşması
    sermaye_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_sermaye, pattern="^sermaye$")],
        states={
            ASK_CAPITAL:      [MessageHandler(filters.TEXT & ~filters.COMMAND, save_capital)],
            ASK_CAPITAL_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_capital_date)],
        },
        fallbacks=[CommandHandler("iptal", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu",  start))
    app.add_handler(CommandHandler("yukle", cmd_yukle))
    app.add_handler(ekle_conv)
    app.add_handler(sat_conv)
    app.add_handler(nakit_conv)
    app.add_handler(sermaye_conv)

    app.add_handler(CallbackQueryHandler(send_main_menu,  pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(cb_portfoy,      pattern="^portfoy$"))
    app.add_handler(CallbackQueryHandler(cb_gecmis,       pattern="^gecmis$"))
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
