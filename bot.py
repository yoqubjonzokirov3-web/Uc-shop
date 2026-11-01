import os
import json
import asyncio
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= SOZLAMALAR =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "SIZNING_BOT_TOKENINGIZ")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
WEBAPP_URL = os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL", "https://SIZNING-SAYTINGIZ.onrender.com")
CARD_NUMBER = os.getenv("CARD_NUMBER", "5614 6821 1374 6525")
CARD_HOLDER = os.getenv("CARD_HOLDER", "YAQUB")
ADMIN_USER = os.getenv("ADMIN_USER", "@YAQUB_UC_Support")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Foydalanuvchining joriy va barcha buyurtmalari xotirasi
pending_orders = {}
user_orders_history = {}

class OrderState(StatesGroup):
    waiting_for_receipt = State()

# ================= TUGMALAR =================
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 YAQUB UC SHOP (Mini App)", web_app=WebAppInfo(url=WEBAPP_URL))]
    ],
    resize_keyboard=True
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
    resize_keyboard=True
)

def get_admin_inline_kb(user_id: int, order_id: str):
    clean_oid = order_id.replace("#", "")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash (Tushdi)", callback_data=f"adm_ok_{user_id}_{clean_oid}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_no_{user_id}_{clean_oid}")
            ]
        ]
    )

# ================= HANDLERLAR =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Salom, <b>{message.from_user.full_name}</b>!\n"
        f"<b>YAQUB UC SHOP — Premium Game Store</b> botiga xush kelibsiz!\n\n"
        f"💎 UC xarid qilish, buyurtmalar tarixini ko'rish va admin bilan bog'lanish uchun pastdagi <b>«🌐 YAQUB UC SHOP (Mini App)»</b> tugmasini bosing:",
        reply_markup=main_kb,
        parse_mode="HTML"
    )

@dp.message(F.text == "🔙 Bekor qilish")
async def cancel_order(message: Message, state: FSMContext):
    await state.clear()
    pending_orders.pop(message.from_user.id, None)
    await message.answer(
        "Buyurtma bekor qilindi. Xarid qilish uchun Mini App'ga kiring:",
        reply_markup=main_kb
    )

# To'lov chekini (skrinshot) qabul qilish
@dp.message(F.photo)
async def process_receipt(message: Message, state: FSMContext):
    order = pending_orders.get(message.from_user.id)
    if not order:
        await message.answer(
            "❗️ Avval <b>«🌐 YAQUB UC SHOP (Mini App)»</b> orqali UC paketni tanlab buyurtma bering!",
            reply_markup=main_kb,
            parse_mode="HTML"
        )
        return

    photo_id = message.photo[-1].file_id
    user = message.from_user
    username = f"@{user.username}" if user.username else "Mavjud emas"

    admin_text = (
        f"🔔 <b>Yangi buyurtma: {order['order_id']}</b>\n\n"
        f"👤 Xaridor: {user.full_name} ({username})\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n"
        f"📦 Paket: <b>{order['package']}</b>\n"
        f"🎮 Player ID: <code>{order['pubg_id']}</code>\n"
        f"👑 Nickname: <b>{order['nickname']}</b>\n"
        f"💳 To'lov usuli: {order['pay_method']}"
    )

    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_id,
        caption=admin_text,
        reply_markup=get_admin_inline_kb(user.id, order['order_id']),
        parse_mode="HTML"
    )

    pending_orders.pop(message.from_user.id, None)
    await state.clear()
    await message.answer(
        f"✅ <b>{order['order_id']} raqamli buyurtma cheki adminga yuborildi!</b>\n"
        f"Tekshiruvdan so'ng UC hisobingizga tushiriladi va sizga xabar beriladi.",
        reply_markup=main_kb,
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("adm_"))
async def admin_decision(callback: CallbackQuery):
    _, action, user_id_str, clean_oid = callback.data.split("_", 3)
    user_id = int(user_id_str)
    order_id = f"#{clean_oid}"

    # Mini App tarixi uchun holatni yangilash
    new_status = "Bajarilgan" if action == "ok" else "Bekor qilingan"
    for item in user_orders_history.get(user_id, []):
        if item.get("order_id") == order_id:
            item["status"] = new_status

    if action == "ok":
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 <b>Buyurtmangiz bajarildi! ({order_id})</b>\n"
                f"Hisobingizga UC muvaffaqiyatli tushirildi. Xaridingiz uchun rahmat! 🙏"
            ),
            parse_mode="HTML"
        )
        status_text = "\n\n✅ <b>HOLAT: BAJARILDI</b>"
    else:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"❌ <b>Buyurtmangiz rad etildi! ({order_id})</b>\n"
                f"To'lov cheki xato yoki ID noto'g'ri. Qo'shimcha ma'lumot uchun: {ADMIN_USER}"
            ),
            parse_mode="HTML"
        )
        status_text = "\n\n❌ <b>HOLAT: BEKOR QILINDI</b>"

    await callback.message.edit_caption(
        caption=callback.message.caption + status_text,
        parse_mode="HTML",
        reply_markup=None
    )
    await callback.answer("Holat yangilandi!")

# ================= RENDER WEB SERVER VA API =================
async def handle_index(request):
    return web.FileResponse("index.html")

async def handle_config(request):
    user_id = int(request.query.get("user_id", "0"))
    orders = user_orders_history.get(user_id, [])
    return web.json_response({
        "admin_user": ADMIN_USER,
        "orders": orders
    })

async def handle_api_order(request):
    data = await request.json()
    user_id = int(data.get("user_id"))
    order_info = {
        "order_id": data.get("order_id", "#YAQUB-001"),
        "amount": data.get("amount", ""),
        "price": data.get("price", ""),
        "rawPrice": data.get("rawPrice", 0),
        "package": data.get("package", ""),
        "pubg_id": data.get("pubg_id", ""),
        "nickname": data.get("nickname", "Kiritilmagan"),
        "pay_method": data.get("pay_method", "Click / UzCard"),
        "status": "Jarayonda",
        "date": data.get("date", datetime.now().strftime("%d.%m.%Y • %H:%M"))
    }

    pending_orders[user_id] = order_info
    user_orders_history.setdefault(user_id, []).insert(0, order_info)

    await bot.send_message(
        chat_id=user_id,
        text=(
            f"🧾 <b>Buyurtma raqami:</b> <code>{order_info['order_id']}</code>\n"
            f"📦 <b>Paket:</b> {order_info['package']}\n"
            f"🎮 <b>Player ID:</b> <code>{order_info['pubg_id']}</code>\n"
            f"👑 <b>Nickname:</b> {order_info['nickname']}\n"
            f"💳 <b>To'lov usuli:</b> {order_info['pay_method']}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💳 <b>To'lov uchun karta:</b>\n"
            f"<code>{CARD_NUMBER}</code>\n"
            f"👤 <b>Egasi:</b> {CARD_HOLDER}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"📸 Yuqoridagi kartaga to'lov qilgach, <b>to'lov chekini (skrinshot)</b> shu yerga yuboring:"
        ),
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    return web.json_response({"ok": True})

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/config", handle_config)
    app.router.add_post("/api/order", handle_api_order)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    print("YAQUB UC SHOP Mini App ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
