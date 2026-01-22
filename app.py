powershell -Command @'
from flask import Flask, request
import requests, os, sys
from dotenv import load_dotenv
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

# ================= BASIC SETUP =================
load_dotenv()
app = Flask(__name__)

VERIFY_TOKEN = "mytoken123"
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_PHONE = os.getenv("ADMIN_PHONE")

LOG_FILE = "bot.log"

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ================= ENV CHECK =================
if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
    log("❌ ENV ERROR: WhatsApp token / phone missing")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
log("✅ ENV loaded")

# ================= GOOGLE SHEETS =================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS = Credentials.from_service_account_file("google_key.json", scopes=SCOPES)
GS = gspread.authorize(CREDS)

SPREADSHEET_ID = "1JOsJqxy_wfD6vNlWhJlzPD3fSsVoohQtD_4YbAXOFwk"
SHEET = GS.open_by_key(SPREADSHEET_ID)
LEADS = SHEET.sheet1
SESSIONS = SHEET.worksheet("sessions")

log("✅ Google Sheets connected")

# ================= SESSION HELPERS =================
def get_session(phone):
    for r in SESSIONS.get_all_records():
        if str(r["phone"]) == str(phone):
            return r
    return None

def save_session(phone, stage, website_type="", pages="", budget="", price=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = get_session(phone)

    data = [phone, stage, website_type, pages, budget, price, now]

    if row:
        cell = SESSIONS.find(str(phone))
        SESSIONS.update(f"A{cell.row}:G{cell.row}", [data])
    else:
        SESSIONS.append_row(data)

def clear_session(phone):
    try:
        cell = SESSIONS.find(str(phone))
        SESSIONS.delete_rows(cell.row)
    except:
        pass

# ================= PRICE LOGIC =================
def calculate_price(site_type, pages_text):
    pages = len(pages_text.split(","))
    site_type = site_type.lower()

    if "business" in site_type:
        return 7000 if pages <= 5 else 10000
    if "ecommerce" in site_type:
        return 15000 if pages <= 5 else 25000
    if "portfolio" in site_type:
        return 5000
    return 8000

# ================= AI FALLBACK =================
def ai_reply(text):
    if not client:
        return "Type *website* to continue 🙂"

    prompt = f"""
You are a WhatsApp sales assistant.
Tone: Hinglish, friendly, short.
Ask only ONE question.

User message: {text}
"""
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120
        )
        return r.choices[0].message.content.strip()
    except:
        return "Type *website* to continue 🙂"

# ================= SEND WHATSAPP =================
def send_whatsapp(to, text):
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=payload)

def notify_admin(msg):
    if ADMIN_PHONE:
        send_whatsapp(ADMIN_PHONE, msg)

# ================= WEBHOOK =================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Invalid", 403

    data = request.json
    value = data["entry"][0]["changes"][0]["value"]

    if "messages" not in value:
        return "OK", 200

    msg = value["messages"][0]
    if msg.get("type") != "text":
        return "OK", 200

    user = msg["from"]
    text = msg["text"]["body"].strip().lower()

    session = get_session(user)
    stage = session["stage"] if session else "start"

    log(f"{user} | {text} | stage={stage}")

    if text in ["hi", "hello"]:
        save_session(user, "start")
        reply = "👋 Hi! Welcome to *Zenvy Services*\nType *website* to continue."

    elif text == "website":
        save_session(user, "type")
        reply = "🌐 Website type?\n• Business\n• E-commerce\n• Portfolio"

    elif stage == "type":
        save_session(user, "pages", website_type=text)
        reply = "📄 Pages needed? (Home, About, Contact)"

    elif stage == "pages":
        save_session(user, "budget", session["website_type"], pages=text)
        reply = "💰 Budget range?\n• 5-10\n• 10-20\n• 20+"

    elif stage == "budget":
        price = calculate_price(session["website_type"], session["pages"])
        save_session(user, "payment", session["website_type"], session["pages"], text, price)

        notify_admin(f"🆕 NEW LEAD\nPhone: {user}\nPrice: ₹{price}")

        reply = (
            f"💻 *Quotation*\n"
            f"Type: {session['website_type']}\n"
            f"Pages: {session['pages']}\n"
            f"💰 Price: ₹{price}\n\n"
            "1️⃣ Pay via UPI\n2️⃣ Talk to human"
        )

    elif stage == "payment":
        if "1" in text:
            reply = "📲 UPI: yourupi@bank\nPayment ke baad *PAID* likhein."
        elif "2" in text:
            notify_admin(f"📞 CALL REQUEST: {user}")
            reply = "📞 Executive will call you shortly."
        elif "paid" in text:
            LEADS.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user,
                session["website_type"],
                session["pages"],
                session["budget"],
                session["price"],
                "PAID"
            ])
            clear_session(user)
            reply = "🎉 Payment received! Thank you."
        else:
            reply = "Reply 1️⃣ or 2️⃣"

    else:
        reply = ai_reply(text)

    send_whatsapp(user, reply)
    return "OK", 200

# ================= RUN =================
if __name__ == "__main__":
    log("🚀 BOT STARTED – RAILWAY READY")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
'@ | Out-File -Encoding utf8 app.py
