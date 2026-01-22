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

# ================= CHECK ENV =================
if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
    log("❌ ENV ERROR")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
log("✅ ENV loaded")

# ================= GOOGLE SHEETS =================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS = Credentials.from_service_account_file("google_key.json", scopes=SCOPES)
GS = gspread.authorize(CREDS)

SPREADSHEET_ID = "1JOsJqxy_wfD6vNlWhJlzPD3fSsVoohQtD_4YbAXOFwk"
LEADS = GS.open_by_key(SPREADSHEET_ID).sheet1
SESSIONS = GS.open_by_key(SPREADSHEET_ID).worksheet("sessions")

log("✅ Google Sheets connected")

# ================= SESSION HELPERS =================
def get_session(phone):
    for row in SESSIONS.get_all_records():
        if str(row["phone"]) == str(phone):
            return row
    return None

def save_session(phone, stage, website_type="", pages="", budget="", price=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cell = SESSIONS.find(str(phone)) if get_session(phone) else None

    if cell:
        row = cell.row
        SESSIONS.update(
            f"A{row}:H{row}",
            [[phone, stage, website_type, pages, budget, price, now, now]]
        )
    else:
        SESSIONS.append_row([phone, stage, website_type, pages, budget, price, now, now])

def clear_session(phone):
    cell = SESSIONS.find(str(phone))
    SESSIONS.delete_rows(cell.row)

# ================= PRICE LOGIC =================
def calculate_price(site_type, pages_text):
    pages = len(pages_text.split(","))

    if "business" in site_type:
        return 7000 if pages <= 5 else 10000
    if "ecommerce" in site_type or "e-commerce" in site_type:
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
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120
        )
        return res.choices[0].message.content.strip()
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
    r = requests.post(url, headers=headers, json=payload)
    log(f"📤 SEND {r.status_code}")

def notify_admin(msg):
    if ADMIN_PHONE:
        send_whatsapp(ADMIN_PHONE, msg)

# ================= AUTO FOLLOW-UP =================
def auto_followup():
    rows = SESSIONS.get_all_records()
    now = datetime.now()
    for r in rows:
        last = datetime.strptime(r["last_message_at"], "%Y-%m-%d %H:%M:%S")
        if (now - last) > timedelta(hours=24):
            if r["stage"] in ["budget", "payment"]:
                send_whatsapp(
                    r["phone"],
                    "👋 Hi! Just checking—shall we continue your website discussion?"
                )
                save_session(
                    r["phone"],
                    r["stage"],
                    r["website_type"],
                    r["pages"],
                    r["budget"],
                    r["price"]
                )

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

    # ================= FLOW =================
    if text in ["hi", "hello"]:
        save_session(user, "start")
        reply = "👋 Hi! Welcome to *Zenvy Services*\nType *website* to continue."

    elif text == "website":
        save_session(user, "type")
        reply = "🌐 What type of website?\n• Business\n• E-commerce\n• Portfolio"

    elif stage == "type":
        save_session(user, "pages", website_type=text)
        reply = "📄 Pages needed? (Home, About, Contact)"

    elif stage == "pages":
        save_session(user, "budget", session["website_type"], pages=text)
        reply = "💰 Budget range?\n• 5-10\n• 10-20\n• 20+"

    elif stage == "budget":
        price = calculate_price(session["website_type"], session["pages"])
        save_session(user, "payment", session["website_type"], session["pages"], text, price)

        notify_admin(
            f"🆕 New Lead\nPhone: {user}\nType: {session['website_type']}\nPages: {session['pages']}\nBudget: {text}\nPrice: ₹{price}"
        )

        reply = (
            f"💻 *Website Quotation*\n\n"
            f"Type: {session['website_type']}\n"
            f"Pages: {session['pages']}\n"
            f"💰 Price: ₹{price}\n\n"
            "Choose payment option:\n"
            "1️⃣ UPI\n"
            "2️⃣ Talk to executive"
        )

    elif stage == "payment":
        if "1" in text or "upi" in text:
            reply = "📲 Pay via UPI: yourupi@bank\nPayment ke baad *PAID* likhein."

        elif "2" in text:
            reply = "📞 Our executive will contact you shortly."

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
            notify_admin(f"✅ PAYMENT RECEIVED\nPhone: {user}\nAmount: ₹{session['price']}")
            clear_session(user)
            reply = "🎉 Payment received! Thank you."

        else:
            reply = "Please reply 1️⃣ or 2️⃣"

    else:
        reply = ai_reply(text)

    send_whatsapp(user, reply)
    return "OK", 200

# ================= RUN =================
if __name__ == "__main__":
    log("🚀 BOT STARTED – FULL POWER MODE")
    app.run(port=5000)
