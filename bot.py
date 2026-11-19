import asyncio
import os
import re
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# ---------------- CONFIG ----------------
API_ID = int(os.environ.get("API_ID", "37601205"))
API_HASH = os.environ.get("API_HASH", "6d73743bfe27-47bf3c06ed90be7d8b34")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "9183544168:AAF6XZIUDObQiPQvbSuUqoGs2GcoyrdSWFs")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://r3921768_db_user:<db_password>@rajveer.ttckgz3.mongodb.net/")
DB_CHANNEL = int(os.environ.get("DB_CHANNEL", "-1003867813389"))
ADMINS = [
    int(x)
    for x in os.environ.get("ADMINS", "7297365703").split(",")
    if x.strip().isdigit()
]

DELETE_AFTER_SECONDS = 300  # 5 મિનિટ
# ----------------------------------------

app = Client(
    "smart_filter_bot_v1",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["smart_media_bot_v1"]
media_col = db["files"]


def normalize_season(text: str):
    """S1, s01, Season 1 -> S01"""
    m = re.search(r"(?:\bs|season\s*)0?(\d{1,2})\b", text, re.IGNORECASE)
    if m:
        return f"S{int(m.group(1)):02d}"
    return None


def extract_year(text: str):
    """2025, 2026 -> 2025/2026"""
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return m.group(1) if m else None


def extract_quality(text: str):
    """480p, 720p, 1080p, 2160p / 4K"""
    m = re.search(r"\b(480p|720p|1080p|2160p|4k)\b", text, re.IGNORECASE)
    if m:
        q = m.group(1).lower()
        return "4K" if q == "4k" else q
    return "Default"


def clean_title(text: str):
    """નામમાંથી વર્ષ, સિઝન અને ક્વોલિટી દૂર કરીને મૂળ ટાઈટલ કાઢે"""
    t = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", text)
    t = re.sub(r"(?:\bs|season\s*)0?\d{1,2}\b", " ", t, flags=re.IGNORECASE)
    t = re.sub(
        r"\b(480p|720p|1080p|2160p|4k|web-?dl|bluray|hdrip|hevc|x264|x265|mkv|mp4)\b",
        " ",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"[._\-\[\]()]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


async def delete_later(client: Client, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


async def save_media_message(msg):
    """મેસેજમાંથી ફાઈલની વિગતો લઈને MongoDB માં સેવ કરે"""
    if not msg or not (msg.document or msg.video):
        return False, "આ મેસેજમાં કોઈ Document કે Video ફાઈલ નથી."

    media = msg.document or msg.video
    raw_name = media.file_name or msg.caption or "untitled"
    combined = f"{raw_name} {msg.caption or ''}"

    title = clean_title(combined)
    season = normalize_season(combined)
    year = extract_year(combined)
    quality = extract_quality(combined)

    if not title:
        return False, "ફાઈલનું નામ ઓળખી શકાયું નથી."

    doc = {
        "chat_id": msg.chat.id,
        "message_id": msg.id,
        "file_name": raw_name,
        "title": title,
        "season": season,
        "year": year,
        "quality": quality,
    }

    await media_col.update_one(
        {"chat_id": msg.chat.id, "message_id": msg.id},
        {"$set": doc},
        upsert=True,
    )
    return (
        True,
        f"✅ **Saved!**\n🎬 Title: `{title}`\n📺 Season: `{season or 'N/A'}` | 📅 Year: `{year or 'N/A'}` | 🎞 Quality: `{quality}`",
    )


@app.on_message(filters.chat(DB_CHANNEL) & (filters.document | filters.video))
async def index_channel_file(client, message):
    await save_media_message(message)


@app.on_message(filters.command("msave") & filters.user(ADMINS))
async def manual_save_cmd(client, message):
    target_msg = None

    if message.reply_to_message:
        target_msg = message.reply_to_message
    elif len(message.command) > 1 and message.command[1].isdigit():
        msg_id = int(message.command[1])
        try:
            target_msg = await client.get_messages(DB_CHANNEL, msg_id)
        except Exception:
            target_msg = None

    if not target_msg:
        await message.reply_text(
            "⚠️ ઉપયોગ:\n"
            "• ફાઈલ પર **Reply** કરીને `/msave` લખો, અથવા\n"
            "• `/msave <message_id>` લખો."
        )
        return

    _, status_msg = await save_media_message(target_msg)
    await message.reply_text(status_msg)


@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    if len(message.command) > 1 and message.command[1].startswith("get_"):
        doc_id = message.command[1].replace("get_", "")
        try:
            item = await media_col.find_one({"_id": ObjectId(doc_id)})
        except Exception:
            item = None

        if not item:
            await message.reply_text("❌ ફાઈલ મળી નથી.")
            return

        sent = await client.copy_message(
            chat_id=message.chat.id,
            from_chat_id=item["chat_id"],
            message_id=item["message_id"],
            caption=f"🎬 **{item['file_name']}**\n\n⏳ આ મેસેજ **5 મિનિટ** પછી ઓટોમેટિક ડિલીટ થઈ જશે.",
        )
        asyncio.create_task(
            delete_later(client, message.chat.id, sent.id, DELETE_AFTER_SECONDS)
        )
        return

    await message.reply_text(
        "👋 નમસ્તે! મૂવી કે સીરીઝનું નામ (Season/Year સાથે) લખીને સર્ચ કરો."
    )


@app.on_message(filters.text & ~filters.command(["start", "msave"]))
async def search_media(client, message):
    query = message.text.strip()
    if len(query) < 2:
        return

    req_season = normalize_season(query)
    req_year = extract_year(query)
    req_title = clean_title(query)

    if not req_title:
        return

    mongo_query = {"title": {"$regex": re.escape(req_title), "$options": "i"}}
    if req_season:
        mongo_query["season"] = req_season
    if req_year:
        mongo_query["year"] = req_year

    results = await media_col.find(mongo_query).to_list(length=50)
    if not results:
        return

    options = []
    seen = set()
    for r in results:
        if req_season and req_year:
            label = f"{r['title'].title()} [{r['season']} | {r['year'] or 'N/A'}]"
        elif not req_season and any(x.get("season") for x in results):
            label = r.get("season") or "Other"
        elif not req_year and any(x.get("year") for x in results):
            label = r.get("year") or "Other"
        else:
            label = r["file_name"][:35]

        if label not in seen:
            seen.add(label)
            options.append(label)

    buttons = []
    row = []
    for idx, opt in enumerate(options[:12]):
        cb_data = f"opt_v1|{req_title[:20]}|{req_season or 'ALL'}|{req_year or 'ALL'}|{idx}"
        row.append(InlineKeyboardButton(opt, callback_data=cb_data))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await message.reply_text(
        f"🔎 **Results for:** `{query}`\nતમારો ઓપ્શન પસંદ કરો:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@app.on_callback_query(filters.regex(r"^opt_v1\|"))
async def show_qualities(client, callback):
    _, t_part, s_part, y_part, idx_str = callback.data.split("|")
    idx = int(idx_str)

    mongo_query = {"title": {"$regex": re.escape(t_part), "$options": "i"}}
    if s_part != "ALL":
        mongo_query["season"] = s_part
    if y_part != "ALL":
        mongo_query["year"] = y_part

    results = await media_col.find(mongo_query).to_list(length=50)
    if not results:
        await callback.answer("કોઈ ફાઈલ મળી નથી.", show_alert=True)
        return

    options = []
    seen = set()
    for r in results:
        if s_part != "ALL" and y_part != "ALL":
            label = f"{r['title'].title()} [{r['season']} | {r['year'] or 'N/A'}]"
        elif s_part == "ALL" and any(x.get("season") for x in results):
            label = r.get("season") or "Other"
        elif y_part == "ALL" and any(x.get("year") for x in results):
            label = r.get("year") or "Other"
        else:
            label = r["file_name"][:35]
        if label not in seen:
            seen.add(label)
            options.append(label)

    chosen_opt = options[idx] if idx < len(options) else None
    filtered_files = []
    for r in results:
        if s_part != "ALL" and y_part != "ALL":
            lbl = f"{r['title'].title()} [{r['season']} | {r['year'] or 'N/A'}]"
        elif s_part == "ALL" and any(x.get("season") for x in results):
            lbl = r.get("season") or "Other"
        elif y_part == "ALL" and any(x.get("year") for x in results):
            lbl = r.get("year") or "Other"
        else:
            lbl = r["file_name"][:35]
        if lbl == chosen_opt:
            filtered_files.append(r)

    q_buttons = []
    for f in filtered_files:
        q_label = f"{f['quality']} ({f['file_name'][:20]})"
        q_buttons.append(
            [InlineKeyboardButton(q_label, callback_data=f"send_v1|{str(f['_id'])}")]
        )

    await callback.message.edit_text(
        f"🎞 **Selected:** `{chosen_opt}`\nક્વોલિટી પસંદ કરો:",
        reply_markup=InlineKeyboardMarkup(q_buttons),
    )


@app.on_callback_query(filters.regex(r"^send_v1\|"))
async def send_to_pm(client, callback):
    doc_id = callback.data.split("|")[1]
    try:
        item = await media_col.find_one({"_id": ObjectId(doc_id)})
    except Exception:
        item = None

    if not item:
        await callback.answer("ફાઈલ ઉપલબ્ધ નથી.", show_alert=True)
        return

    try:
        sent = await client.copy_message(
            chat_id=callback.from_user.id,
            from_chat_id=item["chat_id"],
            message_id=item["message_id"],
            caption=f"🎬 **{item['file_name']}**\n\n⏳ આ મેસેજ **5 મિનિટ** પછી ઓટોમેટિક ડિલીટ થઈ જશે.",
        )
        asyncio.create_task(
            delete_later(client, callback.from_user.id, sent.id, DELETE_AFTER_SECONDS)
        )
        await callback.answer(
            "તમારી Personal Chat માં ફાઈલ મોકલી દીધી છે!", show_alert=True
        )
    except Exception:
        bot_info = await client.get_me()
        link = f"https://t.me/{bot_info.username}?start=get_{doc_id}"
        await callback.message.edit_text(
            "📩 Personal Chat માં ફાઈલ મેળવવા નીચેના બટન પર ક્લિક કરો:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Get File in PM", url=link)]]
            ),
        )
import asyncio

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

app.run()


app.run()

