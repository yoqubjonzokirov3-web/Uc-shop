import asyncio, hashlib, hmac, json, os, re, sqlite3, time
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunparse, urlunsplit

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo
from aiohttp import web

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
# Render o'zi RENDER_EXTERNAL_URL beradi, qo'shimcha sozlash shart emas
API_BASE = (os.environ.get("API_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
# Doimiy baza (Neon/Supabase): postgresql://... Bo'sh bo'lsa vaqtinchalik SQLite ishlatiladi
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_PATH = os.environ.get("DB_PATH", "shop.db")
# To'lov kartasi (mijozga ko'rsatiladi). Render'da CARD_NUMBER / CARD_OWNER bilan almashtirsa bo'ladi
CARD_NUMBER = os.environ.get("CARD_NUMBER", "5614682113746525").strip()
CARD_OWNER = os.environ.get("CARD_OWNER", "ZOKIROV YOQUBJON").strip()
SUPPORT = os.environ.get("SUPPORT", "believerr88").lstrip("@")
TZ = timezone(timedelta(hours=5))  # O'zbekiston vaqti

_u = urlparse(WEBAPP_URL)
ORIGIN = f"{_u.scheme}://{_u.netloc}"

# Narxlar so'mda. index.html dagi SHOP bilan BIR XIL bo'lsin
SHOP = {
    "pubg": {"name": "PUBG MOBILE", "items": {
        "uc60": ("60 UC", 13000),
        "uc120": ("120 UC", 26000),
        "uc180": ("180 UC", 39000),
        "uc240": ("240 UC", 52000),
        "uc325": ("325 UC", 60000),
        "uc385": ("385 UC", 73000),
        "uc660": ("660 UC", 120000),
        "uc720": ("720 UC", 133000),
        "uc1800": ("1800 UC", 305000),
        "uc2460": ("2460 UC", 425000),
        "uc5650": ("5650 UC", 885000),
        "uc8100": ("8100 UC", 1200000),
    }},
}
# Eski (Stars davridagi) buyurtmalar tarixda to'g'ri ko'rinishi uchun
LEGACY = {"uc3850": "3850 UC"}

# Mijozga ketadigan xabarlar
MSG = {
    "uz": {
        "order": "✅ <b>Mini App orqali buyurtma qabul qilindi!</b>\n\n"
                 "📦 Paket: <b>{item} — {sum} so'm</b>\n🆔 PUBG ID: <code>{pid}</code>\n👑 Nickname: {nick}\n\n"
                 "💳 <b>To'lov uchun karta:</b>\n<code>{card}</code>\n👤 Egasi: <b>{owner}</b>\n\n"
                 "To'lovni amalga oshirgach, <b>to'lov chekini (skrinshot) shu yerga yuboring:</b>",
        "received": "✅ <b>Chek qabul qilindi!</b>\n{code}\nAdmin tekshirib chiqadi. Tasdiqlangach UC hisobingizga tushiriladi.",
        "extra": "✅ Qo'shimcha chek adminga yuborildi.",
        "again": "Chekingiz allaqachon yuborilgan, admin tekshirmoqda. Iltimos, kuting 🙏",
        "need_order": "Avval do'kon orqali buyurtma bering 👇",
        "need_receipt": "Iltimos, to'lov chekini <b>skrinshot (rasm)</b> ko'rinishida yuboring.",
        "fail": "❌ Chekni adminga yetkazib bo'lmadi. Qaytadan yuboring.",
        "done": "✅ <b>Buyurtmangiz bajarildi!</b>\n{code}\n<b>{game} — {item}</b>\nUC hisobingizga tushdi. Rahmat! 🙏",
        "cancel": "❌ <b>Buyurtmangiz bekor qilindi.</b>\n{code}\nSavollar bo'lsa: @{support}",
        "cancel_refund": "❌ <b>Buyurtmangiz bekor qilindi.</b>\n{code}\n⭐ {stars} Stars hisobingizga qaytarildi.",
        "welcome": "Xush kelibsiz! Do'konni ochish uchun tugmani bosing 👇",
        "open": "🛒 Do'konni ochish",
    },
    "ru": {
        "order": "✅ <b>Заказ из Mini App принят!</b>\n\n"
                 "📦 Пакет: <b>{item} — {sum} сум</b>\n🆔 PUBG ID: <code>{pid}</code>\n👑 Ник: {nick}\n\n"
                 "💳 <b>Карта для оплаты:</b>\n<code>{card}</code>\n👤 Владелец: <b>{owner}</b>\n\n"
                 "После оплаты <b>отправьте сюда чек (скриншот):</b>",
        "received": "✅ <b>Чек получен!</b>\n{code}\nАдминистратор проверит оплату. После подтверждения UC будут зачислены.",
        "extra": "✅ Дополнительный чек отправлен админу.",
        "again": "Чек уже отправлен, администратор проверяет. Пожалуйста, подождите 🙏",
        "need_order": "Сначала оформите заказ в магазине 👇",
        "need_receipt": "Пожалуйста, отправьте чек в виде <b>скриншота (картинки)</b>.",
        "fail": "❌ Не удалось передать чек админу. Отправьте ещё раз.",
        "done": "✅ <b>Ваш заказ выполнен!</b>\n{code}\n<b>{game} — {item}</b>\nUC зачислены на аккаунт. Спасибо! 🙏",
        "cancel": "❌ <b>Ваш заказ отменён.</b>\n{code}\nЕсли есть вопросы: @{support}",
        "cancel_refund": "❌ <b>Ваш заказ отменён.</b>\n{code}\n⭐ {stars} Stars возвращены на ваш счёт.",
        "welcome": "Добро пожаловать! Нажмите кнопку, чтобы открыть магазин 👇",
        "open": "🛒 Открыть магазин",
    },
}

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def fmt(n) -> str:
    return f"{int(n):,}"


def item_name(game: str, item: str) -> str:
    it = SHOP.get(game, {}).get("items", {}).get(item)
    return it[0] if it else LEGACY.get(item, item)


def game_name(game: str) -> str:
    return SHOP.get(game, {}).get("name", "PUBG MOBILE")


# ---------- Baza (Postgres yoki SQLite) ----------
_pool = None


def _pg_sql(sql: str) -> str:
    n, out = 0, []
    for ch in sql:
        if ch == "?":
            n += 1
            out.append(f"${n}")
        else:
            out.append(ch)
    return "".join(out)


def _clean_dsn(url: str) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k == "sslmode"]
    return urlunsplit(p._replace(query=urlencode(q)))


def _sqlite_run(mode, sql, args):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, args)
        if mode == "all":
            res = [dict(r) for r in cur.fetchall()]
        elif mode == "one":
            r = cur.fetchone()
            res = dict(r) if r else None
        elif mode == "insert":
            res = cur.lastrowid
        else:
            res = cur.rowcount
        con.commit()
        return res
    finally:
        con.close()


async def _run(mode, sql, *args):
    if _pool is None:
        return await asyncio.to_thread(_sqlite_run, mode, sql, args)
    sql = _pg_sql(sql)
    async with _pool.acquire() as c:
        if mode == "all":
            return [dict(r) for r in await c.fetch(sql, *args)]
        if mode == "one":
            r = await c.fetchrow(sql, *args)
            return dict(r) if r else None
        if mode == "insert":
            return await c.fetchval(sql + " RETURNING id", *args)
        status = await c.execute(sql, *args)
        try:
            return int(status.split()[-1])
        except Exception:
            return 0


def q_all(sql, *a): return _run("all", sql, *a)
def q_one(sql, *a): return _run("one", sql, *a)
def q_exec(sql, *a): return _run("exec", sql, *a)
def q_insert(sql, *a): return _run("insert", sql, *a)


async def db_init():
    """Bazani tayyorlaydi. Postgres ulanmasa, SQLite'ga o'tadi va ogohlantirish matnini qaytaradi."""
    global _pool
    warn = None
    auto = "INTEGER PRIMARY KEY AUTOINCREMENT"
    if DATABASE_URL:
        try:
            import asyncpg
            _pool = await asyncpg.create_pool(
                _clean_dsn(DATABASE_URL), min_size=1, max_size=3, statement_cache_size=0)
            auto = "SERIAL PRIMARY KEY"
        except Exception as e:
            _pool = None
            warn = f"DATABASE_URL ishlamadi, vaqtinchalik baza ishlatilmoqda: {str(e)[:200]}"
            print(warn)
    await q_exec(
        "CREATE TABLE IF NOT EXISTS users("
        "user_id BIGINT PRIMARY KEY, first_name TEXT, username TEXT, "
        "notify INTEGER NOT NULL DEFAULT 1, lang TEXT NOT NULL DEFAULT 'uz', created_at BIGINT NOT NULL)")
    await q_exec(
        f"CREATE TABLE IF NOT EXISTS orders(id {auto}, code TEXT, day TEXT, seq INTEGER, "
        "user_id BIGINT NOT NULL, game TEXT, item TEXT, pid TEXT, nick TEXT, "
        "stars INTEGER, list_stars INTEGER, status TEXT NOT NULL DEFAULT 'new', "
        "charge_id TEXT, ts BIGINT NOT NULL, paid_ts BIGINT)")
    try:
        await q_exec("ALTER TABLE orders ADD COLUMN uzs BIGINT")
    except Exception:
        pass  # ustun allaqachon bor
    await q_exec("CREATE UNIQUE INDEX IF NOT EXISTS orders_code_u ON orders(code)")
    await q_exec("CREATE INDEX IF NOT EXISTS orders_user_i ON orders(user_id)")
    return warn


async def upsert_user(u: dict):
    lang = "ru" if str(u.get("language_code") or "").startswith("ru") else "uz"
    await q_exec(
        "INSERT INTO users(user_id, first_name, username, notify, lang, created_at) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO NOTHING",
        u["id"], u.get("first_name") or "", u.get("username") or "", 1, lang, int(time.time()))
    await q_exec("UPDATE users SET first_name=?, username=? WHERE user_id=?",
                 u.get("first_name") or "", u.get("username") or "", u["id"])


def get_user(uid):
    return q_one("SELECT * FROM users WHERE user_id=?", uid)


async def user_lang(uid) -> str:
    r = await get_user(uid)
    return r["lang"] if r and r["lang"] in MSG else "uz"


async def user_orders_count(uid) -> int:
    r = await q_one("SELECT COUNT(*) AS n FROM orders WHERE user_id=? AND status IN ('pending','done')", uid)
    return int(r["n"])


async def new_order(uid, g, i, pid, nick, uzs) -> int:
    """Buyurtma yaratadi va unga kunlik raqam beradi: #YAQUB-20261102-001.
    Mijozning avvalgi to'lanmagan buyurtmasi va 24 soatdan eskilari o'chiriladi."""
    now = int(time.time())
    await q_exec("DELETE FROM orders WHERE status='new' AND (user_id=? OR ts < ?)", uid, now - 86400)
    day = datetime.now(TZ).strftime("%Y%m%d")
    for _ in range(5):
        r = await q_one("SELECT COALESCE(MAX(seq),0) AS m FROM orders WHERE day=?", day)
        seq = int(r["m"]) + 1
        code = f"#YAQUB-{day}-{seq:03d}"
        try:
            return await q_insert(
                "INSERT INTO orders(user_id, game, item, pid, nick, uzs, status, ts, code, day, seq) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", uid, g, i, pid, nick, uzs, "new", now, code, day, seq)
        except Exception:
            await asyncio.sleep(0.05)
    raise RuntimeError("order code")


# ---------- Mini App autentifikatsiyasi ----------
def verify_init_data(init_data: str, max_age: int = 3 * 86400):
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received = data.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received):
            return None
        if max_age and time.time() - int(data.get("auth_date", 0)) > max_age:
            return None
        return json.loads(data["user"])
    except Exception:
        return None


def webapp_url() -> str:
    u = urlparse(WEBAPP_URL)
    q = dict(parse_qsl(u.query))
    if API_BASE:
        q["api"] = API_BASE
    return urlunparse(u._replace(query=urlencode(q)))


def parse_order(d: dict):
    """Buyurtmani tekshiradi. Narx faqat serverdagi SHOP dan olinadi."""
    game = SHOP[d["g"]]
    name, price = game["items"][d["i"]]
    pid = str(d["p"]).strip()
    if not re.fullmatch(r"\d{5,15}", pid):
        raise ValueError("pid")
    nick = re.sub(r"[\s\x00-\x1f\x7f]+", " ", str(d["n"])).strip()
    if not (1 <= len(nick) <= 20):
        raise ValueError("nick")
    return d["g"], d["i"], game, name, price, pid, nick


def admin_kb(oid: int, confirm: bool = False) -> InlineKeyboardMarkup:
    if confirm:
        row = [InlineKeyboardButton(text="❌ Ha, bekor qilish", callback_data=f"ord:cx:{oid}"),
               InlineKeyboardButton(text="↩️ Yo'q", callback_data=f"ord:back:{oid}")]
    else:
        row = [InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"ord:done:{oid}"),
               InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"ord:cancel:{oid}")]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def price_text(o) -> str:
    return f"{fmt(o['uzs'])} so'm" if o.get("uzs") is not None else f"⭐ {o['stars']}"


def admin_text(o, u, status: str) -> str:
    name = escape((u or {}).get("first_name") or "—")
    un = (u or {}).get("username")
    who = f"{name} (@{escape(un)})" if un else name
    return (f"🔔 <b>Yangi buyurtma!</b> {o['code'] or ''}\n\n"
            f"👤 Xaridor: <b>{who}</b>\n"
            f"🆔 Telegram ID: <code>{o['user_id']}</code>\n"
            f"📦 Paket: <b>{item_name(o['game'], o['item'])} — {price_text(o)}</b>\n"
            f"🎮 PUBG ID: <code>{o['pid']}</code>\n"
            f"👑 Nickname: {escape(o['nick'] or '')}\n\n{status}")


def open_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=MSG[lang]["open"], web_app=WebAppInfo(url=webapp_url()))]])


# ---------- Bot ----------
@dp.message(CommandStart())
async def start(m: types.Message):
    await upsert_user({"id": m.from_user.id, "first_name": m.from_user.first_name,
                       "username": m.from_user.username, "language_code": m.from_user.language_code})
    lang = await user_lang(m.from_user.id)
    await m.answer(MSG[lang]["welcome"], reply_markup=open_kb(lang))


def is_receipt(m: types.Message) -> bool:
    if m.photo:
        return True
    d = m.document
    return bool(d and (d.mime_type or "").startswith(("image/", "application/pdf")))


@dp.message(F.photo | F.document)
async def receipt(m: types.Message):
    uid = m.from_user.id
    lang = await user_lang(uid)
    if not is_receipt(m):
        return await m.answer(MSG[lang]["need_receipt"], parse_mode="HTML")
    o = await q_one("SELECT * FROM orders WHERE user_id=? AND status='new' ORDER BY id DESC LIMIT 1", uid)
    if not o:
        p = await q_one("SELECT * FROM orders WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1", uid)
        if p and int(time.time()) - int(p["paid_ts"] or 0) < 900:
            try:  # qo'shimcha chek (masalan, 2-sahifa) — adminga o'tkaziladi
                await bot.copy_message(ADMIN_ID, m.chat.id, m.message_id)
                await bot.send_message(ADMIN_ID, f"➕ {p['code']} uchun qo'shimcha chek")
                return await m.answer(MSG[lang]["extra"])
            except Exception:
                pass
        if p:
            return await m.answer(MSG[lang]["again"])
        return await m.answer(MSG[lang]["need_order"], reply_markup=open_kb(lang))
    if not await q_exec("UPDATE orders SET status='pending', paid_ts=? WHERE id=? AND status='new'",
                        int(time.time()), o["id"]):
        return await m.answer(MSG[lang]["again"])
    await upsert_user({"id": uid, "first_name": m.from_user.first_name,
                       "username": m.from_user.username, "language_code": m.from_user.language_code})
    u = await get_user(uid)
    try:
        await bot.copy_message(ADMIN_ID, m.chat.id, m.message_id)
        await bot.send_message(ADMIN_ID, admin_text(o, u, "⏳ HOLAT: KUTILMOQDA"),
                               parse_mode="HTML", reply_markup=admin_kb(o["id"]))
    except Exception as e:
        print("Adminga yuborishda xato:", e)
        await q_exec("UPDATE orders SET status='new', paid_ts=NULL WHERE id=?", o["id"])
        return await m.answer(MSG[lang]["fail"])
    await m.answer(MSG[lang]["received"].format(code=o["code"]), parse_mode="HTML")


@dp.message(F.text)
async def any_text(m: types.Message):
    lang = await user_lang(m.from_user.id)
    o = await q_one("SELECT id FROM orders WHERE user_id=? AND status='new' LIMIT 1", m.from_user.id)
    if o:
        return await m.answer(MSG[lang]["need_receipt"], parse_mode="HTML")
    await m.answer(MSG[lang]["welcome"], reply_markup=open_kb(lang))


@dp.callback_query(F.data.startswith("ord:"))
async def order_action(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return await cb.answer("Ruxsat yo'q", show_alert=True)
    try:
        _, act, sid = cb.data.split(":")
        oid = int(sid)
    except Exception:
        return await cb.answer()
    o = await q_one("SELECT * FROM orders WHERE id=?", oid)
    if not o:
        return await cb.answer("Buyurtma topilmadi", show_alert=True)
    if act in ("done", "cancel", "cx") and o["status"] != "pending":
        return await cb.answer("Bu buyurtmaning holati allaqachon o'zgargan", show_alert=True)

    lang = await user_lang(o["user_id"])
    u = await get_user(o["user_id"])

    if act == "cancel":  # tasdiqlash so'raladi
        await cb.message.edit_reply_markup(reply_markup=admin_kb(oid, confirm=True))
        return await cb.answer("Rostdan bekor qilasizmi?")
    if act == "back":
        await cb.message.edit_reply_markup(reply_markup=admin_kb(oid))
        return await cb.answer()

    async def finish(status_line: str, text: str, label: str):
        """Avval mijozga xabar yuboradi, keyin admin xabarini yangilaydi. Xato bo'lsa, adminga ko'rsatadi."""
        err = None
        try:
            await bot.send_message(o["user_id"], text, parse_mode="HTML")
        except Exception as e:
            err = str(e)[:150]
            print("Mijozga xabar yuborilmadi:", o["user_id"], e)
        try:
            warn = f"\n\n⚠️ Mijozga xabar yuborilmadi: {escape(err)}" if err else ""
            await cb.message.edit_text(admin_text(o, u, status_line) + warn, parse_mode="HTML", reply_markup=None)
        except Exception as e:
            print("Admin xabarini yangilab bo'lmadi:", e)
        if err:
            return await cb.answer(f"{label}, lekin mijozga xabar yuborilmadi: {err}"[:190], show_alert=True)
        return await cb.answer(label)

    if act == "done":
        if not await q_exec("UPDATE orders SET status='done' WHERE id=? AND status='pending'", oid):
            return await cb.answer("Holat allaqachon o'zgargan", show_alert=True)
        txt = MSG[lang]["done"].format(code=o["code"], game=game_name(o["game"]), item=item_name(o["game"], o["item"]))
        return await finish("✅ HOLAT: BAJARILDI", txt, "Bajarildi")

    if act == "cx":
        if not await q_exec("UPDATE orders SET status='cancelled' WHERE id=? AND status='pending'", oid):
            return await cb.answer("Holat allaqachon o'zgargan", show_alert=True)
        refunded = False
        if o.get("charge_id"):  # eski Stars buyurtmasi: pulni qaytaramiz
            try:
                await bot.refund_star_payment(user_id=o["user_id"], telegram_payment_charge_id=o["charge_id"])
                refunded = True
            except Exception as e:
                await q_exec("UPDATE orders SET status='pending' WHERE id=?", oid)
                await cb.message.edit_reply_markup(reply_markup=admin_kb(oid))
                return await cb.answer(f"Stars qaytarilmadi: {str(e)[:150]}", show_alert=True)
        if refunded:
            txt = MSG[lang]["cancel_refund"].format(code=o["code"], stars=o["stars"])
        else:
            txt = MSG[lang]["cancel"].format(code=o["code"], support=SUPPORT)
        return await finish("❌ HOLAT: BEKOR QILINDI" + (" (⭐ qaytarildi)" if refunded else ""), txt, "Bekor qilindi")
    await cb.answer()


# ---------- Veb-server (Render uchun + Mini App API'si) ----------
@web.middleware
async def cors(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "X-Init-Data, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def auth(request):
    return verify_init_data(request.headers.get("X-Init-Data", ""))


def deny():
    return web.json_response({"error": "auth"}, status=403)


async def health(request):
    return web.Response(text="ok")


async def me_api(request):
    u = auth(request)
    if not u:
        return deny()
    await upsert_user(u)
    row = await get_user(u["id"])
    return web.json_response({
        "notify": bool(row["notify"]), "lang": row["lang"], "orders": await user_orders_count(u["id"])})


async def orders_api(request):
    u = auth(request)
    if not u:
        return deny()
    rows = await q_all(
        "SELECT id, code, game, item, pid, nick, stars, uzs, status, paid_ts, ts FROM orders "
        "WHERE user_id=? ORDER BY id DESC LIMIT 50", u["id"])
    return web.json_response({"orders": [
        {"id": r["id"], "c": r["code"], "g": r["game"], "i": r["item"], "p": r["pid"], "n": r["nick"],
         "s": r["uzs"] if r["uzs"] is not None else r["stars"], "cur": "uzs" if r["uzs"] is not None else "xtr",
         "st": r["status"], "t": r["paid_ts"] or r["ts"]} for r in rows]})


async def order_api(request):
    u = auth(request)
    if not u:
        return deny()
    try:
        oid = int(request.match_info["id"])
    except Exception:
        return web.json_response({"error": "bad"}, status=400)
    r = await q_one("SELECT status, code FROM orders WHERE id=? AND user_id=?", oid, u["id"])
    if not r:
        return web.json_response({"error": "none"}, status=404)
    return web.json_response({"status": r["status"], "code": r["code"]})


async def settings_api(request):
    u = auth(request)
    if not u:
        return deny()
    try:
        d = await request.json()
    except Exception:
        return web.json_response({"error": "bad"}, status=400)
    await upsert_user(u)
    if "notify" in d:
        await q_exec("UPDATE users SET notify=? WHERE user_id=?", 1 if d["notify"] else 0, u["id"])
    if d.get("lang") in ("uz", "ru"):
        await q_exec("UPDATE users SET lang=? WHERE user_id=?", d["lang"], u["id"])
    return web.json_response({"ok": True})


async def place_api(request):
    """Mini App'dan buyurtma: bazaga yoziladi, mijozga botdan karta ma'lumoti yuboriladi."""
    u = auth(request)
    if not u:
        return deny()
    try:
        d = await request.json()
        g, i, game, name, price, pid, nick = parse_order(d)
    except Exception:
        return web.json_response({"error": "bad"}, status=400)
    await upsert_user(u)
    oid = await new_order(u["id"], g, i, pid, nick, price)
    lang = await user_lang(u["id"])
    try:
        await bot.send_message(u["id"], MSG[lang]["order"].format(
            item=name, sum=fmt(price), pid=pid, nick=escape(nick), card=escape(CARD_NUMBER), owner=escape(CARD_OWNER)),
            parse_mode="HTML")
    except Exception as e:
        print("Mijozga xabar yuborib bo'lmadi:", e)
        await q_exec("DELETE FROM orders WHERE id=?", oid)
        return web.json_response({"error": "nobot"}, status=409)
    return web.json_response({"ok": True, "id": oid})


async def main():
    warn = await db_init()
    app = web.Application(middlewares=[cors])
    app.router.add_get("/", health)
    app.router.add_get("/api/me", me_api)
    app.router.add_get("/api/orders", orders_api)
    app.router.add_get("/api/order/{id}", order_api)
    app.router.add_post("/api/settings", settings_api)
    app.router.add_post("/api/place", place_api)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000))).start()
    try:  # chatning pastki chap "Menu" tugmasi ham do'konni ochadi
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="🛒 Do'kon", web_app=WebAppInfo(url=webapp_url())))
    except Exception as e:
        print("Menu tugmasini o'rnatib bo'lmadi:", e)
    if warn:
        try:
            await bot.send_message(ADMIN_ID, "⚠️ " + warn)
        except Exception:
            pass
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
