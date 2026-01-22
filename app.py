from flask import Flask, request
import requests, os, sys, json
from dotenv import load_dotenv
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

# ================= BASIC SETUP =================
load_dotenv()
app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "mytoken123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_PHONE = os.getenv("ADMIN_PHONE")
GOOGLE_KEY_JSON = os.getenv("GOOGLE_KEY_JSON")

LOG_FILE = "bot.log"

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ================= ENV CHECK =================
missing = []
if not WHATSAPP_TOKEN: missing.append("WHATSAPP_TOKEN")
if not PHONE_NUMBER_ID: missing.append("PHONE_NUMBER_ID")
if not GOOGLE_KEY_JSON: missing.append("GOOGLE_KEY_JSON")

if missing:
    log(f"❌ ENV MISSING: {', '.join(missing)}")
    sys.exit(1)

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
log("✅ ENV loaded")

# ================= GOOGLE SHEETS (ENV SAFE) =================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

try:
    key_dict = json.loads(GOOGLE_KEY_JSON)
    CREDS = Credentials.from_service_account_info(key_dict, scopes=SCOPES)
    GS = gspread.authorize(CREDS)
except Exception as e:
    log(f"❌ GOOGLE AUTH ERROR: {e}")
    sys.exit(1)

SPREADSHEET_ID = "1JOsJqxy_wfD6vNlWhJlzPD3fSsVoohQtD_4YbAXOFwk"
SHEET = GS.open_by_key(SPREADSHEET_ID)

def get_or_create(title, headers):
    try:
        ws = SHEET.worksheet(title)
    except:
        ws = SHEET.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws

LEADS = get_or_create(
    "LEADS",
    ["time", "phone", "website_type", "pages", "budget", "price", "invoice", "status", "note"]
)

SESSIONS = get_or_create(
    "sessions",
    ["phone", "stage", "website_type", "pages", "budget", "price", "updated_at"]
)

log("✅ Google Sheets ready")

# ================= HELPERS =================
def generate_invoice_id():
    return "INV-" + datetime.now().strftime("%m%d%H%M")

def get_session(phone):
    for r in SESSIONS.get_all_records():
        if str(r.get("phone")) == str(phone):
            return r
    return None

def save_session(phone, stage, website_type="", pages="", budget="", price=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = [phone, stage, website_type, pages, budget, price, now]
    row = get_session(phone)

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
    pages = len([p for p in pages_text.split(",") if p.strip()])
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
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Hinglish sales assistant. Ask ONE short question.\nUser: {text}"
            }],
            max_tokens=120
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        log(f"AI ERROR: {e}")
        return "Type *website* to continue 🙂"

# ================= WHATSAPP =================
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

    data = request.json or {}
    try:
        value = data["entry"][0]["changes"][0]["value"]
    except:
        return "OK", 200

    if "messages" not in value:
        return "OK", 200

    msg = value["messages"][0]
    user = msg.get("from")

    if msg.get("type") == "image":
        notify_admin(f"📸 PAYMENT SCREENSHOT\nPhone: {user}")
        send_whatsapp(user, "📸 Screenshot received! Verification in progress.")
        return "OK", 200

    if msg.get("type") != "text":
        return "OK", 200

    text = msg["text"]["body"].strip().lower()
    session = get_session(user)
    stage = session["stage"] if session else "start"

    log(f"{user} | {text} | {stage}")

    if text in ["hi", "hello"]:
        save_session(user, "start")
        reply = "👋 Hi! Welcome to *Zenvy Services*\nType *website* to continue."

    elif text == "website":
        save_session(user, "type")
        reply = "🌐 Website type?\n• Business\n• E-commerce\n• Portfolio"

    elif stage == "type":
        save_session(user, "pages", website_type=text)
        reply = "📄 Pages? (Home, About, Contact)"

    elif stage == "pages":
        save_session(user, "budget", session["website_type"], pages=text)
        reply = "💰 Budget?\n• 5-10\n• 10-20\n• 20+"

    elif stage == "budget":
        price = calculate_price(session["website_type"], session["pages"])
        save_session(user, "payment", session["website_type"], session["pages"], text, price)

        notify_admin(f"🆕 LEAD {user} ₹{price}")

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
            notify_admin(f"📞 CALL REQUEST {user}")
            reply = "📞 Executive will call you shortly."
        elif "paid" in text:
            invoice = generate_invoice_id()
            LEADS.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user,
                session["website_type"],
                session["pages"],
                session["budget"],
                session["price"],
                invoice,
                "PAID_PENDING",
                ""
            ])
            clear_session(user)
            notify_admin(f"✅ PAID {user} {invoice}")
            reply = "🎉 Payment received! Verification in progress."
        else:
            reply = "Reply 1️⃣ or 2️⃣"

    else:
        reply = ai_reply(text)

    send_whatsapp(user, reply)
    return "OK", 200

# ================= RUN =================
if __name__ == "__main__":
    log("🚀 BOT STARTED – STABLE PRODUCTION")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
