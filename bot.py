import os
import json
import asyncio
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
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
CARD_NUMBER = os.getenv("CARD_NUMBER", "8600 0000 0000 0000")
CARD_HOLDER = os.getenv("CARD_HOLDER", "ISM FAMILIYA")
ADMIN_USER = os.getenv("ADMIN_USER", "@admin_username")


UC_PACKAGES = {
    "60": "60 UC — 13,000 so'm",
    "325": "325 UC — 62,000 so'm",
    "660": "660 UC — 122,000 so'm",
    "1800": "1800 UC — 300,000 so'm",
    "3850": "3850 UC — 590,000 so'm",
    "8100": "8100 UC — 1,180,000 so'm"
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Mini App orqali kelgan buyurtmalarni vaqtincha saqlash
pending_orders = {}

# ================= HOLATLAR (FSM) =================
class OrderState(StatesGroup):
    waiting_for_id = State()
    waiting_for_receipt = State()

# ================= TUGMALAR =================
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Mini App (UC Do'kon)", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton(text="🛒 Oddiy xarid"), KeyboardButton(text="📋 Narxlar")],
        [KeyboardButton(text="👨‍💻 Admin bilan aloqa")]
    ],
    resize_keyboard=True
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Bekor qilish")]],
    resize_keyboard=True
)

def get_uc_inline_kb():
    buttons = [
        [InlineKeyboardButton(text="🌐 Mini App orqali ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
    ]
    for key, text in UC_PACKAGES.items():
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"buy_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_inline_kb(user_id: int, pubg_id: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm_ok_{user_id}_{pubg_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_no_{user_id}_{pubg_id}")
            ]
        ]
    )

# ================= HANDLERLAR =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    pending_orders.pop(message.from_user.id, None)
    await message.answer(
        f"Salom, <b>{message.from_user.full_name}</b>!\n"
        f"UC Shop botimizga xush kelibsiz.\n\n"
        f"Pastdagi <b>«🌐 Mini App (UC Do'kon)»</b> tugmasi orqali saytdan yoki oddiy menyudan xarid qilishingiz mumkin:",
        reply_markup=main_kb,
        parse_mode="HTML"
    )

@dp.message(F.text == "🔙 Bekor qilish")
async def cancel_order(message: Message, state: FSMContext):
    await state.clear()
    pending_orders.pop(message.from_user.id, None)
    await message.answer("Buyurtma bekor qilindi. Asosiy menyudasiz:", reply_markup=main_kb)

@dp.message(F.text == "📋 Narxlar")
async def show_prices(message: Message):
    text = "<b>💎 Aktual UC narxlarimiz:</b>\n\n"
    for val in UC_PACKAGES.values():
        text += f"• {val}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "👨‍💻 Admin bilan aloqa")
async def contact_admin(message: Message):
    await message.answer(f"Savol va muammolar bo'yicha adminga yozing: {ADMIN_USER}")

@dp.message(F.text == "🛒 Oddiy xarid")
async def start_buying(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Kerakli UC miqdorini tanlang:", reply_markup=get_uc_inline_kb())

# Mini App (ReplyKeyboard) dan ma'lumot kelganda
@dp.message(F.web_app_data)
async def handle_webapp_data(message: Message, state: FSMContext):
    data = json.loads(message.web_app_data.data)
    package = data.get("package")
    pubg_id = data.get("pubg_id")

    pending_orders[message.from_user.id] = {"package": package, "pubg_id": pubg_id}
    await state.set_state(OrderState.waiting_for_receipt)

    await message.answer(
        f"✅ <b>Mini App orqali buyurtma qabul qilindi!</b>\n\n"
        f"📦 Paket: <b>{package}</b>\n"
        f"🆔 PUBG ID: <code>{pubg_id}</code>\n\n"
        f"💳 <b>To'lov uchun karta:</b>\n"
        f"<code>{CARD_NUMBER}</code>\n"
        f"👤 Egasi: <b>{CARD_HOLDER}</b>\n\n"
        f"To'lovni amalga oshirgach, <b>to'lov chekini (skrinshot)</b> shu yerga yuboring:",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("buy_"))
async def package_selected(callback: CallbackQuery, state: FSMContext):
    uc_key = callback.data.split("_")[1]
    package_name = UC_PACKAGES.get(uc_key)

    await state.update_data(package=package_name)
    await state.set_state(OrderState.waiting_for_id)

    await callback.message.delete()
    await callback.message.answer(
        f"Siz tanladingiz: <b>{package_name}</b>\n\n"
        f"Endi <b>PUBG Mobile ID</b> raqamingizni yuboring (faqat raqam):",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )

@dp.message(OrderState.waiting_for_id)
async def process_pubg_id(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or len(message.text) < 8:
        await message.answer("❗️ Iltimos, to'g'ri PUBG ID kiriting (kamida 8 ta raqam):")
        return

    data = await state.get_data()
    pending_orders[message.from_user.id] = {"package": data["package"], "pubg_id": message.text}
    await state.set_state(OrderState.waiting_for_receipt)

    await message.answer(
        f"📌 <b>Buyurtma ma'lumotlari:</b>\n"
        f"📦 Paket: {data['package']}\n"
        f"🆔 PUBG ID: <code>{message.text}</code>\n\n"
        f"💳 <b>To'lov uchun karta:</b>\n"
        f"<code>{CARD_NUMBER}</code>\n"
        f"👤 Egasi: <b>{CARD_HOLDER}</b>\n\n"
        f"To'lovni amalga oshirgach, <b>to'lov chekini (skrinshot)</b> shu yerga yuboring:",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )

# To'lov chekini (rasm) qabul qilish (ham Mini App, ham oddiy xarid uchun)
@dp.message(F.photo)
async def process_receipt(message: Message, state: FSMContext):
    order = pending_orders.get(message.from_user.id)
    if not order:
        return

    photo_id = message.photo[-1].file_id
    user = message.from_user
    username = f"@{user.username}" if user.username else "Mavjud emas"

    admin_text = (
        f"🔔 <b>Yangi buyurtma!</b>\n\n"
        f"👤 Xaridor: {user.full_name} ({username})\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n"
        f"📦 Paket: <b>{order['package']}</b>\n"
        f"🎮 PUBG ID: <code>{order['pubg_id']}</code>"
    )

    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_id,
        caption=admin_text,
        reply_markup=get_admin_inline_kb(user.id, order['pubg_id']),
        parse_mode="HTML"
    )

    pending_orders.pop(message.from_user.id, None)
    await state.clear()
    await message.answer(
        "✅ <b>To'lov cheki adminga yuborildi!</b>\n"
        "Tekshiruvdan so'ng UC hisobingizga tushiriladi.",
        reply_markup=main_kb,
        parse_mode="HTML"
    )

@dp.message(OrderState.waiting_for_receipt)
async def invalid_receipt(message: Message):
    await message.answer("❗️ Iltimos, to'lov chekini <b>rasm (skrinshot)</b> ko'rinishida yuboring!", parse_mode="HTML")

@dp.callback_query(F.data.startswith("adm_"))
async def admin_decision(callback: CallbackQuery):
    _, action, user_id, pubg_id = callback.data.split("_")
    user_id = int(user_id)

    if action == "ok":
        await bot.send_message(
            chat_id=user_id,
            text=f"🎉 <b>Buyurtmangiz bajarildi!</b>\n"
                 f"🆔 <code>{pubg_id}</code> hisobingizga UC tushirildi. Xaridingiz uchun rahmat!",
            parse_mode="HTML"
        )
        status_text = "\n\n✅ <b>HOLAT: TASDIQLANDI</b>"
    else:
        await bot.send_message(
            chat_id=user_id,
            text=f"❌ <b>Buyurtmangiz rad etildi!</b>\n"
                 f"Chek xato yoki ID noto'g'ri. Admin: {ADMIN_USER}",
            parse_mode="HTML"
        )
        status_text = "\n\n❌ <b>HOLAT: RAD ETILDI</b>"

    await callback.message.edit_caption(
        caption=callback.message.caption + status_text,
        parse_mode="HTML",
        reply_markup=None
    )
    await callback.answer("Bajarildi!")

# ================= RENDER WEB SERVER VA API =================
async def handle_index(request):
    return web.FileResponse("index.html")

async def handle_api_order(request):
    data = await request.json()
    user_id = int(data.get("user_id"))
    package = data.get("package")
    pubg_id = data.get("pubg_id")

    pending_orders[user_id] = {"package": package, "pubg_id": pubg_id}

    await bot.send_message(
        chat_id=user_id,
        text=(
            f"✅ <b>Mini App orqali buyurtma qabul qilindi!</b>\n\n"
            f"📦 Paket: <b>{package}</b>\n"
            f"🆔 PUBG ID: <code>{pubg_id}</code>\n\n"
            f"💳 <b>To'lov uchun karta:</b>\n"
            f"<code>{CARD_NUMBER}</code>\n"
            f"👤 Egasi: <b>{CARD_HOLDER}</b>\n\n"
            f"To'lovni amalga oshirgach, <b>to'lov chekini (skrinshot)</b> shu yerga yuboring:"
        ),
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    return web.json_response({"ok": True})

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/order", handle_api_order)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    print("UC Shop + Mini App ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
  
