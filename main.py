import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# Token va Admin ID ni shu yerga yozing (yoki Environment variable sifatida bering)
TOKEN = "8638320387:AAGWDfPWGDi7_isrf4BhQIiMA7EsELhEWrA"
ADMIN_ID = 8595373987  # O'z Telegram ID raqamingizni yozing

logging.basicConfig(level=logging.INFO)
router = Router()

# --- DATABASE (MA'LUMOTLAR BAZASI) ---
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT,
    vip_expire TEXT DEFAULT '0'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS movies (
    code TEXT PRIMARY KEY,
    title TEXT,
    file_id TEXT,
    parts TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
conn.commit()


# Boshlang'ich sozlamalar
def get_setting(key, default=""):
  cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
  res = cursor.fetchone()
  return res[0] if res else default


def set_setting(key, value):
  cursor.execute(
      "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
  )
  conn.commit()


# --- FSM STATES (HOLATLAR) ---
class AdminState(StatesGroup):
  waiting_for_movie_code = State()
  waiting_for_movie_title = State()
  waiting_for_movie_file = State()
  waiting_for_channel = State()
  waiting_for_card = State()
  waiting_for_broadcast = State()
  waiting_for_vip_user = State()


# --- MAJBURIY OBUNA VA VIP TEKSHIRUV ---
async def check_subscription(bot: Bot, user_id: int) -> bool:
  if user_id == ADMIN_ID:
    return True

  # VIP tekshiruvi
  cursor.execute("SELECT vip_expire FROM users WHERE user_id = ?", (user_id,))
  res = cursor.fetchone()
  if res and res[0] != "0":
    import time

    if float(res[0]) > time.time():
      return True  # VIP muddati tugamagan, majburiy obuna shart emas!

  channel = get_setting("required_channel")
  if not channel:
    return True

  try:
    member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
    if member.status in ["member", "administrator", "creator"]:
      return True
  except Exception:
    pass
  return False


# --- START VA ASOSIY MENU ---
@router.message(Command("start"))
async def cmd_start(message: Message):
  user_id = message.from_user.id
  cursor.execute(
      "INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?)",
      (user_id, message.from_user.full_name),
  )
  conn.commit()

  # Majburiy obunani tekshirish
  if not await check_subscription(message.bot, user_id):
    channel = get_setting("required_channel")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga a'zo bo'lish", url=f"https://t.me/{channel.replace('@', '')}")],
            [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")],
        ]
    )
    await message.answer(
        "⚠️ Botdan foydalanish uchun quyidagi kanalga obuna bo'lishingiz kerak:",
        reply_markup=keyboard,
    )
    return

  args = message.text.split()
  if len(args) > 1:
    movie_code = args[1]
    await send_movie(message, movie_code)
    return

  keyboard_buttons = [
      [InlineKeyboardButton(text="🎬 Kino qidirish (Kod orqali)", callback_data="search_movie")],
      [InlineKeyboardButton(text="💎 VIP Sotib olish", callback_data="buy_vip")],
      [InlineKeyboardButton(text="👤 Kabinetim", callback_data="cabinet")],
  ]
  if user_id == ADMIN_ID:
    keyboard_buttons.append([InlineKeyboardButton(text="👑 Admin Panel", callback_data="admin_panel")])

  markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
  await message.answer(
      "✨ Salom! Kino botga xush kelibsiz. Kino kodini yuboring yoki quyidagi tugmalardan foydalaning:",
      reply_markup=markup,
  )


@router.callback_query(F.data == "check_sub")
async def callback_check_sub(callback: CallbackQuery):
  if await check_subscription(callback.bot, callback.from_user.id):
    await callback.message.delete()
    await callback.message.answer("Rahmat! Obuna tasdiqlandi. /start buyrug'ini bosing.")
  else:
    await callback.answer("⚠️ Hali kanalga obuna bo'lmadingiz!", show_alert=True)


# --- KINO QIDIRISH VA YUBORISH ---
@router.callback_query(F.data == "search_movie")
async def search_movie_handler(callback: CallbackQuery):
  await callback.message.answer("Iltimos, kinoning **kodini** yuboring:")


async def send_movie(message: Message, code: str):
  if not await check_subscription(message.bot, message.from_user.id):
    await message.answer("⚠️ Avval homiy kanalga obuna bo'ling!")
    return

  cursor.execute("SELECT title, file_id, parts FROM movies WHERE code = ?", (code,))
  movie = cursor.fetchone()

  if not movie:
    await message.answer("❌ Bunday kodli kino topilmadi.")
    return

  title, file_id, parts = movie
  if parts:  # Agar ko'p qismli bo'lsa
    part_list = parts.split(",")
    buttons = [
        [InlineKeyboardButton(text=f"{i+1}-qism", callback_data=f"getpart_{code}_{i}")]
        for i in range(len(part_list))
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(f"🎬 <b>{title}</b>\n\nQismni tanlang:", reply_markup=markup, parse_mode="HTML")
  else:
    await message.bot.send_video(chat_id=message.chat.id, video=file_id, caption=f"🎬 {title}")


@router.callback_query(F.data.startswith("getpart_"))
async def get_movie_part(callback: CallbackQuery):
  _, code, part_idx = callback.data.split("_")
  cursor.execute("SELECT title, parts FROM movies WHERE code = ?", (code,))
  movie = cursor.fetchone()
  if movie:
    title, parts = movie
    part_list = parts.split(",")
    file_id = part_list[int(part_idx)]
    await callback.bot.send_video(
        chat_id=callback.message.chat.id,
        video=file_id,
        caption=f"🎬 {title} ({int(part_idx)+1}-qism)",
    )
  await callback.answer()


@router.message(F.text & ~F.text.startswith("/"))
async def text_movie_search(message: Message):
  code = message.text.strip()
  await send_movie(message, code)


# --- VIP SOTIB OLISH ---
@router.callback_query(F.data == "buy_vip")
async def buy_vip_handler(callback: CallbackQuery):
  card = get_setting("bank_card", "Karta kiritilmagan")
  text = (
      f"💎 **VIP Statusni sotib olish**\n\n"
      f"VIP foydalanuvchilar majburiy obunalardan ozod qilinadi va bot **2x tezroq** ishlaydi!\n\n"
      f"💳 **To'lov uchun karta:** `{card}`\n"
      f"To'lov qilgandan so'ng chekni adminga yuboring.\n\n"
      f"Quyidagi muddatlardan birini tanlang:"
  )
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="1 oylik - 10,000 so'm", callback_data="vip_1")],
          [InlineKeyboardButton(text="2 oylik - 18,000 so'm", callback_data="vip_2")],
          [InlineKeyboardButton(text="3 oylik - 25,000 so'm", callback_data="vip_3")],
          [InlineKeyboardButton(text="6 oylik - 45,000 so'm", callback_data="vip_6")],
          [InlineKeyboardButton(text="12 oylik - 80,000 so'm", callback_data="vip_12")],
          [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_home")],
      ]
  )
  await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("vip_"))
async def select_vip_period(callback: CallbackQuery):
  months = callback.data.split("_")[1]
  admin_username = get_setting("admin_username", "@Admin")
  await callback.message.answer(
      f"Siz {months} oylik VIP obunani tanladingiz.\nTo'lovni amalga oshirgach, chekni admin {admin_username} ga yuboring."
  )
  await callback.answer()


# --- KABINET ---
@router.callback_query(F.data == "cabinet")
async def cabinet_handler(callback: CallbackQuery):
  user_id = callback.from_user.id
  cursor.execute("SELECT vip_expire FROM users WHERE user_id = ?", (user_id,))
  res = cursor.fetchone()
  import time

  vip_status = "❌ Yo'q"
  if res and res[0] != "0":
    if float(res[0]) > time.time():
      vip_status = "💎 Faol VIP"

  text = f"👤 **Sizning ma'lumotlaringiz:**\n\n🆔 ID: `{user_id}`\n💎 VIP Status: {vip_status}"
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_home")]]
  )
  await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "back_home")
async def back_home_handler(callback: CallbackQuery):
  await callback.message.delete()
  await cmd_start(callback.message)


# --- ADMIN PANEL ---
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
  if callback.from_user.id != ADMIN_ID:
    await callback.answer("Siz admin emassiz!", show_alert=True)
    return

  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="adm_add_movie")],
          [InlineKeyboardButton(text="📢 Majburiy obuna sozlash", callback_data="adm_channel")],
          [InlineKeyboardButton(text="💳 Karta qo'shish/o'zgartirish", callback_data="adm_card")],
          [InlineKeyboardButton(text="💎 Foydalanuvchiga VIP berish", callback_data="adm_give_vip")],
          [InlineKeyboardButton(text="📢 Reklama tarqatish", callback_data="adm_broadcast")],
          [InlineKeyboardButton(text="🔗 Post yaratish (Generator)", callback_data="adm_post_gen")],
          [InlineKeyboardButton(text="🔙 Chiqish", callback_data="back_home")],
      ]
  )
  await callback.message.edit_text("👑 **Admin Paneliga xush kelibsiz:**", reply_markup=keyboard, parse_mode="Markdown")


# 1. Kino qo'shish jarayoni
@router.callback_query(F.data == "adm_add_movie")
async def adm_add_movie(callback: CallbackQuery, state: FSMContext):
  await callback.message.answer("Kinoning kodini yuboring (masalan: 101):")
  await state.set_state(AdminState.waiting_for_movie_code)


@router.message(AdminState.waiting_for_movie_code)
async def process_movie_code(message: Message, state: FSMContext):
  await state.update_data(code=message.text.strip())
  await message.answer("Kinoning nomini yuboring:")
  await state.set_state(AdminState.waiting_for_movie_title)


@router.message(AdminState.waiting_for_movie_title)
async def process_movie_title(message: Message, state: FSMContext):
  await state.update_data(title=message.text.strip())
  await message.answer("Kino videosini yuboring (agar ko'p qismli bo'lsa, qismlarni ketma-ket video qilib yuboring va oxirida /done yuboring):")
  await state.set_state(AdminState.waiting_for_movie_file)
  await state.update_data(parts=[])


@router.message(AdminState.waiting_for_movie_file, F.video)
async def process_movie_file(message: Message, state: FSMContext):
  data = await state.get_data()
  parts = data.get("parts")
  parts.append(message.video.file_id)
  await state.update_data(parts=parts)
  await message.answer(f"✅ {len(parts)}-qism qo'shildi. Yana qism qo'shishingiz yoki /done ni bosing.")


@router.message(AdminState.waiting_for_movie_file, Command("done"))
async def process_movie_done(message: Message, state: FSMContext):
  data = await state.get_data()
  code = data["code"]
  title = data["title"]
  parts = ",".join(data["parts"])
  file_id = data["parts"][0] if data["parts"] else ""

  cursor.execute(
      "INSERT OR REPLACE INTO movies (code, title, file_id, parts) VALUES (?, ?, ?, ?)",
      (code, title, file_id, parts),
  )
  conn.commit()
  await message.answer(f"🎉 Kino muvaffaqiyatli saqlandi! Kod: <code>{code}</code>", parse_mode="HTML")
  await state.clear()


# 2. Majburiy obuna kanalini sozlash
@router.callback_query(F.data == "adm_channel")
async def adm_channel(callback: CallbackQuery, state: FSMContext):
  await callback.message.answer("Majburiy kanalusernamini yuboring (masalan: @KinoBaza_kanal):")
  await state.set_state(AdminState.waiting_for_channel)


@router.message(AdminState.waiting_for_channel)
async def save_channel(message: Message, state: FSMContext):
  set_setting("required_channel", message.text.strip())
  await message.answer("✅ Majburiy obuna kanali saqlandi!")
  await state.clear()


# 3. Bank karta qo'shish
@router.callback_query(F.data == "adm_card")
async def adm_card(callback: CallbackQuery, state: FSMContext):
  await callback.message.answer("Yangi bank karta raqamini va egasini yuboring:")
  await state.set_state(AdminState.waiting_for_card)


@router.message(AdminState.waiting_for_card)
async def save_card(message: Message, state: FSMContext):
  set_setting("bank_card", message.text.strip())
  await message.answer("✅ Bank karta muvaffaqiyatli yangilandi!")
  await state.clear()


# 4. VIP berish
@router.callback_query(F.data == "adm_give_vip")
async def adm_give_vip(callback: CallbackQuery, state: FSMContext):
  await callback.message.answer("VIP bermoqchi bo'lgan foydalanuvchi ID raqamini va oylar sonini yuboring (Masalan: `123456789 1`):")
  await state.set_state(AdminState.waiting_for_vip_user)


@router.message(AdminState.waiting_for_vip_user)
async def process_give_vip(message: Message, state: FSMContext):
  try:
    uid, months = message.text.split()
    import time

    expire_time = time.time() + (int(months) * 30 * 24 * 3600)
    cursor.execute(
        "UPDATE users SET vip_expire = ? WHERE user_id = ?",
        (str(expire_time), int(uid)),
    )
    conn.commit()
    await message.answer(f"✅ Foydalanuvchi ({uid}) ga {months} oylik VIP berildi!")
  except Exception:
    await message.answer("❌ Xato format! Qaytadan urinib ko'ring (Masalan: `123456789 1`)")
  await state.clear()


# 5. Post yaratish tugmasi (Siz so'ragan formatda)
@router.callback_query(F.data == "adm_post_gen")
async def adm_post_generator(callback: CallbackQuery):
  bot_username = (await callback.bot.get_me()).username
  text = (
      f"📌 **Post namunasi (uni nusxalab kanalingizga tashlashingiz mumkin):**\n\n"
      f"💎 yuklab olish 💎 - https://t.me/{bot_username}?start=KOD\n"
      f"📷 Instagram - https://instagram.com/kino_baza_rasmiy"
  )
  await callback.message.answer(text, parse_mode="Markdown")


# --- BOTNI ISHGA TUSHIRISH ---
async def main():
  bot = Bot(token=TOKEN)
  dp = Dispatcher()
  dp.include_router(router)
  await bot.delete_webhook(drop_pending_updates=True)
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
