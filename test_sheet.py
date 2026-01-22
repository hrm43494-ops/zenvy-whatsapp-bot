import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1JOsJqxy_wfD6vNlWhJlzPD3fSsVoohQtD_4YbAXOFwk"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

creds = Credentials.from_service_account_file(
    "google_key.json",
    scopes=SCOPES
)

client = gspread.authorize(creds)

sheet = client.open_by_key(SHEET_ID).sheet1

print("✅ Sheet Connected Successfully")
print(sheet.get_all_values())
