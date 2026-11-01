import asyncio, hashlib, hmac, json, os, re, sqlite3, time
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunparse, urlunsplit

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           LabeledPrice, ReplyKeyboardRemove, WebAppInfo)
from aiohttp import web

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
# Render o'zi RENDER_EXTERNAL_URL beradi, qo'shimcha sozlash shart emas
API_BASE = (os.environ.get("API_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
# Doimiy baza (Neon/Supabase): postgresql://... Bo'sh bo'lsa vaqtinchalik SQLite ishlatiladi
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_PATH = os.environ.get("DB_PATH", "shop.db")
# Birinchi buyurtmaga chegirma (foiz). 0 qilsangiz aksiya o'chadi
FIRST_ORDER_DISCOUNT = int(os.environ.get("FIRST_ORDER_DISCOUNT", "5"))
TZ = timezone(timedelta(hours=5))  # O'zbekiston vaqti

_u = urlparse(WEBAPP_URL)
ORIGIN = f"{_u.scheme}://{_u.netloc}"

# Narxlar yulduzda (⭐). index.html dagi SHOP bilan BIR XIL bo'lsin
SHOP = {
    "pubg": {"name": "PUBG MOBILE", "items": {
        "uc60": ("60 UC", 50),
        "uc325": ("325 UC", 250),
        "uc660": ("660 UC", 500),
        "uc1800": ("1800 UC", 1350),
        "uc3850": ("3850 UC", 2800),
        "uc8100": ("8100 UC", 5600),
    }},
}

# Mijozga ketadigan xabarlar
MSG = {
    "uz": {
        "paid": "✅ <b>To'lov qabul qilindi!</b>\n{code}\n<b>{game} — {item}</b>\n"
                "👤 <b>ID:</b> <code>{pid}</code>\n🎮 <b>Nickname:</b> {nick}\nUC tez orada tushadi.",
        "done": "✅ <b>Buyurtmangiz bajarildi!</b>\n{code}\n<b>{game} — {item}</b>\nUC hisobingizga tushdi. Rahmat! 🙏",
        "cancel": "❌ <b>Buyurtmangiz bekor qilindi.</b>\n{code}\n⭐ {stars} Stars hisobingizga qaytarildi.",
        "welcome": "Xush kelibsiz! Do'konni ochish uchun tugmani bosing 👇",
        "open": "🛒 Do'konni ochish",
    },
    "ru": {
        "paid": "✅ <b>Оплата принята!</b>\n{code}\n<b>{game} — {item}</b>\n"
                "👤 <b>ID:</b> <code>{pid}</code>\n🎮 <b>Ник:</b> {nick}\nUC скоро поступят.",
        "done": "✅ <b>Ваш заказ выполнен!</b>\n{code}\n<b>{game} — {item}</b>\nUC зачислены на аккаунт. Спасибо! 🙏",
        "cancel": "❌ <b>Ваш заказ отменён.</b>\n{code}\n⭐ {stars} Stars возвращены на ваш счёт.",
        "welcome": "Добро пожаловать! Нажмите кнопку, чтобы открыть магазин 👇",
        "open": "🛒 Открыть магазин",
    },
}

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def discounted(stars: int) -> int:
    return (stars * (100 - FIRST_ORDER_DISCOUNT) + 50) // 100


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


async def is_first_order(uid) -> bool:
    r = await q_one("SELECT COUNT(*) AS n FROM orders WHERE user_id=? AND status IN ('pending','done')", uid)
    return r["n"] == 0


async def user_stats(uid):
    r = await q_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(stars),0) AS s FROM orders "
        "WHERE user_id=? AND status IN ('pending','done')", uid)
    return {"n": int(r["n"]), "s": int(r["s"])}


async def new_order(uid, g, i, pid, nick, stars, list_stars) -> int:
    now = int(time.time())
    await q_exec("DELETE FROM orders WHERE status='new' AND ts < ?", now - 3600)
    return await q_insert(
        "INSERT INTO orders(user_id, game, item, pid, nick, stars, list_stars, status, ts) "
        "VALUES (?,?,?,?,?,?,?,?,?)", uid, g, i, pid, nick, stars, list_stars, "new", now)


async def mark_paid(oid: int, charge_id: str):
    """To'langan buyurtmaga kun bo'yicha raqam beradi: #YAQUB-20261101-001"""
    for _ in range(5):
        day = datetime.now(TZ).strftime("%Y%m%d")
        r = await q_one("SELECT COALESCE(MAX(seq),0) AS m FROM orders WHERE day=?", day)
        seq = int(r["m"]) + 1
        code = f"#YAQUB-{day}-{seq:03d}"
        try:
            n = await q_exec(
                "UPDATE orders SET status='pending', charge_id=?, code=?, day=?, seq=?, paid_ts=? "
                "WHERE id=? AND status='new'", charge_id, code, day, seq, int(time.time()), oid)
            return code if n else None
        except Exception:
            await asyncio.sleep(0.05)
    return None


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
    name, stars = game["items"][d["i"]]
    pid = str(d["p"]).strip()
    if not re.fullmatch(r"\d{5,15}", pid):
        raise ValueError("pid")
    nick = re.sub(r"[\s\x00-\x1f\x7f]+", " ", str(d["n"])).strip()
    if not (1 <= len(nick) <= 20):
        raise ValueError("nick")
    return d["g"], d["i"], game, name, stars, pid, nick


def admin_kb(oid: int, confirm: bool = False) -> InlineKeyboardMarkup:
    if confirm:
        row = [InlineKeyboardButton(text="⭐ Ha, qaytarish", callback_data=f"ord:cx:{oid}"),
               InlineKeyboardButton(text="↩️ Yo'q", callback_data=f"ord:back:{oid}")]
    else:
        row = [InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"ord:done:{oid}"),
               InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"ord:cancel:{oid}")]
    return InlineKeyboardMarkup(inline_keyboard=[row])


# ---------- Bot ----------
@dp.message(CommandStart())
async def start(m: types.Message):
    await upsert_user({"id": m.from_user.id, "first_name": m.from_user.first_name,
                       "username": m.from_user.username, "language_code": m.from_user.language_code})
    lang = await user_lang(m.from_user.id)
    # Eski pastki "Do'konni ochish" tugmasini olib tashlash
    try:
        tmp = await m.answer("⏳", reply_markup=ReplyKeyboardRemove())
        await tmp.delete()
    except Exception:
        pass
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=MSG[lang]["open"], web_app=WebAppInfo(url=webapp_url()))
    ]])
    await m.answer(MSG[lang]["welcome"], reply_markup=kb)


@dp.pre_checkout_query()
async def pre_checkout(q: types.PreCheckoutQuery):
    try:
        oid = int(q.invoice_payload[1:])
        o = await q_one("SELECT user_id, stars, list_stars, status FROM orders WHERE id=?", oid)
        if (not o or o["status"] != "new" or o["user_id"] != q.from_user.id
                or o["stars"] != q.total_amount or q.currency != "XTR"):
            return await q.answer(ok=False, error_message="Buyurtma topilmadi yoki allaqachon to'langan. Do'konni qayta oching.")
        if o["stars"] < o["list_stars"] and not await is_first_order(q.from_user.id):
            return await q.answer(ok=False, error_message="Chegirma faqat birinchi buyurtmaga amal qiladi. Do'konni qayta oching.")
    except Exception:
        return await q.answer(ok=False, error_message="Xatolik. Qayta urinib ko'ring.")
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def paid(m: types.Message):
    p = m.successful_payment
    try:
        oid = int(p.invoice_payload[1:])
    except Exception:
        oid = 0
    o = await q_one("SELECT * FROM orders WHERE id=?", oid)
    if not o:
        await bot.send_message(
            ADMIN_ID,
            f"⚠️ To'lov keldi, lekin buyurtma topilmadi.\nMijoz: <code>{m.from_user.id}</code>\n"
            f"⭐ {p.total_amount}\nCharge: <code>{escape(p.telegram_payment_charge_id)}</code>",
            parse_mode="HTML")
        return
    code = await mark_paid(oid, p.telegram_payment_charge_id)
    if not code:
        return  # allaqachon qayta ishlangan
    game = SHOP[o["game"]]
    name, _ = game["items"][o["item"]]
    lang = await user_lang(o["user_id"])
    await m.answer(
        MSG[lang]["paid"].format(code=code, game=game["name"], item=name, pid=o["pid"], nick=escape(o["nick"])),
        parse_mode="HTML")
    price = f"⭐ {p.total_amount}"
    if o["list_stars"] and o["list_stars"] != p.total_amount:
        price += f" (chegirma, asl narx ⭐ {o['list_stars']})"
    await bot.send_message(
        ADMIN_ID,
        f"💰 <b>Yangi buyurtma</b> {code}\n"
        f"👤 {escape(m.from_user.full_name)} (id: <code>{m.from_user.id}</code>)\n"
        f"🎮 <b>{game['name']} — {name}</b>\n"
        f"🆔 <b>ID:</b> <code>{o['pid']}</code>\n"
        f"🎮 <b>Nickname:</b> {escape(o['nick'])}\n"
        f"{price}",
        parse_mode="HTML", reply_markup=admin_kb(oid))


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

    game = SHOP[o["game"]]
    name, _ = game["items"][o["item"]]
    lang = await user_lang(o["user_id"])
    u = await get_user(o["user_id"])

    if act == "cancel":  # tasdiqlash so'raladi
        await cb.message.edit_reply_markup(reply_markup=admin_kb(oid, confirm=True))
        return await cb.answer("Bekor qilinsa, ⭐ mijozga qaytariladi")
    if act == "back":
        await cb.message.edit_reply_markup(reply_markup=admin_kb(oid))
        return await cb.answer()

    if act == "done":
        if not await q_exec("UPDATE orders SET status='done' WHERE id=? AND status='pending'", oid):
            return await cb.answer("Holat allaqachon o'zgargan", show_alert=True)
        await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Bajarildi</b>",
                                   parse_mode="HTML", reply_markup=None)
        if not u or u["notify"]:
            try:
                await bot.send_message(o["user_id"], MSG[lang]["done"].format(
                    code=o["code"], game=game["name"], item=name), parse_mode="HTML")
            except Exception:
                pass
        return await cb.answer("Bajarildi")

    if act == "cx":
        if not await q_exec("UPDATE orders SET status='cancelled' WHERE id=? AND status='pending'", oid):
            return await cb.answer("Holat allaqachon o'zgargan", show_alert=True)
        try:
            await bot.refund_star_payment(user_id=o["user_id"], telegram_payment_charge_id=o["charge_id"])
        except Exception as e:
            await q_exec("UPDATE orders SET status='pending' WHERE id=?", oid)
            await cb.message.edit_reply_markup(reply_markup=admin_kb(oid))
            return await cb.answer(f"Stars qaytarilmadi: {str(e)[:150]}", show_alert=True)
        await cb.message.edit_text(cb.message.html_text + f"\n\n❌ <b>Bekor qilindi</b>, ⭐ {o['stars']} qaytarildi",
                                   parse_mode="HTML", reply_markup=None)
        try:
            await bot.send_message(o["user_id"], MSG[lang]["cancel"].format(
                code=o["code"], stars=o["stars"]), parse_mode="HTML")
        except Exception:
            pass
        return await cb.answer("Bekor qilindi")
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
    st = await user_stats(u["id"])
    eligible = FIRST_ORDER_DISCOUNT > 0 and await is_first_order(u["id"])
    return web.json_response({
        "notify": bool(row["notify"]), "lang": row["lang"], "orders": st["n"], "spent": st["s"],
        "discount": {"pct": FIRST_ORDER_DISCOUNT, "eligible": bool(eligible)}})


async def orders_api(request):
    u = auth(request)
    if not u:
        return deny()
    rows = await q_all(
        "SELECT id, code, game, item, pid, nick, stars, list_stars, status, paid_ts FROM orders "
        "WHERE user_id=? AND status<>'new' ORDER BY id DESC LIMIT 50", u["id"])
    return web.json_response({"orders": [
        {"id": r["id"], "c": r["code"], "g": r["game"], "i": r["item"], "p": r["pid"], "n": r["nick"],
         "s": r["stars"], "st": r["status"], "t": r["paid_ts"]} for r in rows]})


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


async def invoice_api(request):
    u = auth(request)
    if not u:
        return deny()
    try:
        d = await request.json()
        g, i, game, name, stars, pid, nick = parse_order(d)
    except Exception:
        return web.json_response({"error": "bad"}, status=400)
    await upsert_user(u)
    list_stars = stars
    if FIRST_ORDER_DISCOUNT > 0 and await is_first_order(u["id"]):
        stars = discounted(list_stars)
    oid = await new_order(u["id"], g, i, pid, nick, stars, list_stars)
    try:
        link = await bot.create_invoice_link(
            title=f"{game['name']} — {name}",
            description=f"👤 ID: {pid}\n🎮 Nickname: {nick}",
            payload=f"o{oid}",
            currency="XTR",
            prices=[LabeledPrice(label=name, amount=stars)],
        )
    except Exception as e:
        print("Invoice yaratishda xato:", e)
        return web.json_response({"error": "invoice"}, status=500)
    return web.json_response({"link": link, "id": oid, "price": stars, "list": list_stars})


async def main():
    warn = await db_init()
    app = web.Application(middlewares=[cors])
    app.router.add_get("/", health)
    app.router.add_get("/api/me", me_api)
    app.router.add_get("/api/orders", orders_api)
    app.router.add_get("/api/order/{id}", order_api)
    app.router.add_post("/api/settings", settings_api)
    app.router.add_post("/api/invoice", invoice_api)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000))).start()
    if warn:
        try:
            await bot.send_message(ADMIN_ID, "⚠️ " + warn)
        except Exception:
            pass
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
