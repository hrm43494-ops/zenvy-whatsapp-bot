import json 
from google.oauth2.service_account import Credentials 
import gspread, os 
from dotenv import load_dotenv 
load_dotenv() 
key = json.loads(os.getenv("GOOGLE_KEY_JSON")) 
creds = Credentials.from_service_account_info(key, scopes=["https://www.googleapis.com/auth/spreadsheets"]) 
gc = gspread.authorize(creds) 
sh = gc.open_by_key("1JOsJqxy_wfD6vNlWhJlzPD3fSsVoohQtD_4YbAXOFwk") 
sheets = [ws.title for ws in sh.worksheets()] 
if "LEADS" not in sheets: sh.add_worksheet("LEADS", 1000, 10) 
if "sessions" not in sheets: sh.add_worksheet("sessions", 1000, 10) 
print("Sheets OK") 
