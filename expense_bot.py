import os
import json
import logging
import anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ── CONFIG ──────────────────────────────────────────────────────────────────
# All secrets are loaded from a .env file — never hardcoded here.
# Copy .env.example to .env and fill in your values before running.

load_dotenv()

TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_ID   = int(os.environ["ALLOWED_USER_ID"])
SHEET_ID          = os.environ["SHEET_ID"]
SHEET_TAB         = os.environ.get("SHEET_TAB", "2026 Expenses")
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Load service account from environment variable (Railway) or file (local)
if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
    SERVICE_ACCOUNT_INFO = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
else:
    SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    with open(SERVICE_ACCOUNT_FILE, "r") as f:
        SERVICE_ACCOUNT_INFO = json.load(f)

CATEGORIES = ["Personal Joy", "Grocery", "Puppy Needs", "Health", "Travel", "Others", "Medical", "Housing", "Transport", "Claude"]

# ── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── GOOGLE SHEETS ────────────────────────────────────────────────────────────

def get_sheets_service():
    creds = service_account.Credentials.from_service_account_info(
        SERVICE_ACCOUNT_INFO,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

def read_all_rows():
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_TAB}!A:E"
    ).execute()
    return result.get("values", [])

def append_row(row):
    service = get_sheets_service()
    # Read column A to find the next truly empty row
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_TAB}!A:A"
    ).execute()
    existing = result.get("values", [])
    next_row = len(existing) + 1
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_TAB}!A{next_row}:E{next_row}",
        valueInputOption="USER_ENTERED",
        body={"values": [row]}
    ).execute()

def update_row(row_index, row):
    service = get_sheets_service()
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_TAB}!A{row_index}:E{row_index}",
        valueInputOption="USER_ENTERED",
        body={"values": [row]}
    ).execute()

def delete_row(row_index, sheet_gid=2090691921):
    service = get_sheets_service()
    service.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_gid,
                    "dimension": "ROWS",
                    "startIndex": row_index - 1,
                    "endIndex": row_index
                }
            }
        }]}
    ).execute()


def get_monthly_spend(month):
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_TAB}!A:D"
    ).execute()
    rows = result.get("values", [])
    search = f"Spend to date ({month})"
    for row in rows:
        for i, cell in enumerate(row):
            if search.lower() in str(cell).lower():
                if i + 1 < len(row):
                    return row[i + 1]
    return None

# ── CLAUDE ───────────────────────────────────────────────────────────────────

def ask_claude(user_message, rows):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    from datetime import date
    today = date.today()
    months = ["January","February","March","April","May","June",
              "July","August","September","October","November","December"]
    today_str = f"{str(today.month).zfill(2)}/{str(today.day).zfill(2)}"
    today_month = months[today.month - 1]

    recent_rows = [r for r in rows if len(r) >= 3 and r[0] and r[1] and r[2]][-20:]
    rows_text = "\n".join([f"ROW {i+1}: {' | '.join(r[:5])}" for i, r in enumerate(recent_rows)])

    system = f"""You are an expense tracking assistant managing a Google Sheet.

Sheet columns: Month, Date (MM/DD), Amount (SGD), Category, Vendor
Categories: {', '.join(CATEGORIES)}
Today: {today_month}, {today_str}

Recent rows (last 20):
{rows_text}

Parse the user's message and return ONLY a JSON object — no explanation, no markdown, no backticks.

For ADD:
{{"intent": "add", "month": "April", "date": "04/18", "amount": 12.5, "category": "Grocery", "vendor": "Lunch"}}

For VIEW:
{{"intent": "view", "filter": "april" | "last5" | "all" | "category:Grocery", "summary": false}}

For DELETE:
{{"intent": "delete", "description": "last entry" | "04/18 $340 Grocery"}}

For EDIT:
{{"intent": "edit", "description": "last entry", "changes": {{"amount": 280}}}}

For SPEND/TOTAL queries ("how much did I spend", "what's my April total", "spending this month"):
{{"intent": "spend", "month": "April"}}

For UNKNOWN:
{{"intent": "unknown"}}

Rules:
- Default date to today if not specified
- Default category to Grocery for food/meals
- Vendor: use the place name or meal type (Lunch, Dinner, etc.)
- Amount must be a number, not a string
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": user_message}]
    )

    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

# ── PENDING CONFIRMATIONS ────────────────────────────────────────────────────

pending = {}

# ── HANDLERS ─────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("Not authorised.")
        return

    # Handle confirmations
    if user_id in pending:
        action = pending[user_id]
        if text.lower() in ["yes", "y", "confirm", "ok", "yep", "yeah"]:
            del pending[user_id]
            await execute_action(update, action)
        elif text.lower() in ["no", "n", "cancel", "nope"]:
            del pending[user_id]
            await update.message.reply_text("Cancelled. Nothing changed.")
        else:
            await update.message.reply_text("Reply yes to confirm or no to cancel.")
        return

    await update.message.reply_text("Thinking...")

    try:
        rows = read_all_rows()
        parsed = ask_claude(text, rows)
        intent = parsed.get("intent")

        if intent == "add":
            row = [
                parsed["month"],
                parsed["date"],
                parsed["amount"],
                parsed["category"],
                parsed.get("vendor", "")
            ]
            pending[user_id] = {"type": "add", "row": row}
            await update.message.reply_text(
                f"Add this entry?\n\n"
                f"📅 {parsed['date']} {parsed['month']}\n"
                f"💵 SGD {parsed['amount']}\n"
                f"🏷 {parsed['category']}\n"
                f"🏪 {parsed.get('vendor', '—')}\n\n"
                f"Reply yes to confirm or no to cancel."
            )

        elif intent == "view":
            f = parsed.get("filter", "last5")
            data = [r for r in rows if len(r) >= 3 and r[0] and r[1] and r[2] and r[2].replace('.','').isdigit()]

            if "april" in f: data = [r for r in data if r[0] == "April"]
            elif "march" in f: data = [r for r in data if r[0] == "March"]
            elif "category:" in f:
                cat = f.split(":")[1]
                data = [r for r in data if len(r) > 3 and cat.lower() in r[3].lower()]
            elif "last" in f:
                n = int(''.join(filter(str.isdigit, f)) or 5)
                data = data[-n:]

            if not data:
                await update.message.reply_text("No entries found.")
                return

            total = sum(float(r[2]) for r in data)
            lines = [f"{r[1]} | SGD {float(r[2]):.2f} | {r[3]} | {r[4] if len(r)>4 else ''}" for r in data[-15:]]
            msg = "\n".join(lines)
            msg += f"\n\nTotal: SGD {total:.2f} ({len(data)} entries)"
            await update.message.reply_text(f"📊\n{msg}")

        elif intent == "delete":
            data_rows = [(i+1, r) for i, r in enumerate(rows) if len(r) >= 3 and r[0] and r[1] and r[2] and r[2].replace('.','').isdigit()]
            if not data_rows:
                await update.message.reply_text("No entries found.")
                return
            idx, row = data_rows[-1]
            pending[user_id] = {"type": "delete", "row_index": idx, "row": row}
            await update.message.reply_text(
                f"Delete this entry?\n\n"
                f"📅 {row[1]}\n"
                f"💵 SGD {float(row[2]):.2f}\n"
                f"🏷 {row[3]}\n"
                f"🏪 {row[4] if len(row)>4 else '—'}\n\n"
                f"Reply yes to confirm or no to cancel."
            )

        elif intent == "edit":
            data_rows = [(i+1, r) for i, r in enumerate(rows) if len(r) >= 3 and r[0] and r[1] and r[2] and r[2].replace('.','').isdigit()]
            if not data_rows:
                await update.message.reply_text("No entries found.")
                return
            idx, row = data_rows[-1]
            changes = parsed.get("changes", {})
            updated = list(row) + [""] * (5 - len(row))
            if "amount" in changes: updated[2] = changes["amount"]
            if "category" in changes: updated[3] = changes["category"]
            if "vendor" in changes: updated[4] = changes["vendor"]
            pending[user_id] = {"type": "edit", "row_index": idx, "row": updated}
            await update.message.reply_text(
                f"Update this entry?\n\n"
                f"Before: {row[1]} | SGD {float(row[2]):.2f} | {row[3]}\n"
                f"After:  {updated[1]} | SGD {float(updated[2]):.2f} | {updated[3]}\n\n"
                f"Reply yes to confirm or no to cancel."
            )

        elif intent == "spend":
            month = parsed.get("month", "April")
            amount = get_monthly_spend(month)
            if amount:
                await update.message.reply_text(f"📊 {month} spend to date: SGD {amount}")
            else:
                await update.message.reply_text(f"Couldn't find spend data for {month}.")

        else:
            await update.message.reply_text(
                "I can help you:\n\n"
                "➕ Add — \"Add $12 for lunch today\"\n"
                "📊 Spend — \"How much did I spend in April?\"\n"
                "📋 View — \"Show last 5 entries\"\n"
                "✏️ Edit — \"Edit last entry, change amount to $10\"\n"
                "🗑 Delete — \"Delete last entry\""
            )

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Something went wrong: {str(e)}")

async def execute_action(update, action):
    try:
        if action["type"] == "add":
            append_row(action["row"])
            r = action["row"]
            await update.message.reply_text(
                f"✅ Added!\n\n"
                f"📅 {r[1]} {r[0]}\n"
                f"💵 SGD {float(r[2]):.2f}\n"
                f"🏷 {r[3]}\n"
                f"🏪 {r[4] or '—'}"
            )
        elif action["type"] == "delete":
            delete_row(action["row_index"])
            r = action["row"]
            await update.message.reply_text(f"🗑 Deleted — {r[1]} · SGD {float(r[2]):.2f} · {r[3]}")
        elif action["type"] == "edit":
            update_row(action["row_index"], action["row"])
            r = action["row"]
            await update.message.reply_text(f"✅ Updated — {r[1]} · SGD {float(r[2]):.2f} · {r[3]}")
    except Exception as e:
        await update.message.reply_text(f"Action failed: {str(e)}")

# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not ANTHROPIC_API_KEY:
        raise ValueError("Set your ANTHROPIC_API_KEY environment variable")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
