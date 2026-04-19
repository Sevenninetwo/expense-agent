# Personal AI Expense Agent

A personal AI agent built from scratch — no engineering background — that automates daily expense tracking through natural language over Telegram, powered by Claude, and connected to Google Sheets.

Built in a single afternoon. Fully operational.

---

## The Problem

I track every expense manually in a Google Sheet. It works, but the friction is real: open laptop, navigate to the sheet, find the right tab, enter five fields, close. Do that 3–5 times a day and it becomes a chore you start skipping.

The question I asked: *can I reduce this to a single message on my phone?*

---

## What It Does

Message the bot in Telegram. It understands natural language, confirms the action, and writes directly to the sheet.

```
You:  Add $12 for lunch today
Bot:  Add this entry?
      📅 04/18 April
      💵 SGD 12.00
      🏷 Grocery
      🏪 Lunch
      Reply yes to confirm or no to cancel.
You:  yes
Bot:  ✅ Added!
```

**Supported commands:**
- Add an expense — `"Spent $45 at NTUC, grocery"`
- View recent entries — `"Show last 5 entries"`
- Check monthly spend — `"How much did I spend in April?"`
- Edit an entry — `"Edit last entry, change amount to $10"`
- Delete an entry — `"Delete last entry"` (always confirms first)

---

## Architecture

```
Telegram (interface)
      ↓
Python bot (local machine)
      ↓
Claude API (intent parsing + NLP)
      ↓
Google Sheets API (read / write)
      ↑
Service Account (auth)
```

**Why each tool:**

| Tool | Why |
|---|---|
| Telegram | Already on my phone. No app to build. Free. Bot API is simple. |
| Python | Lightweight. Fast to iterate. Runs on Mac with no server needed. |
| Claude API | Superior natural language understanding. Handles ambiguous inputs gracefully. Returns structured JSON. |
| Google Sheets | My data is already there. No migration. Formula-based summaries continue working. |
| Service Account | Secure write access to Sheets without exposing personal Google credentials. |

---

## Constraints I Faced

These are the real ones — not sanitised for a portfolio.

**1. CORS blocked direct browser-to-Sheets writes**
The first version was an HTML file that called the Sheets API directly. Read worked. Write failed with a CORS error. Moved to a Python backend to proxy the calls.

**2. Tab names with spaces break the Sheets API range syntax**
My sheet tab is called `2026 Expenses`. The API range `2026 Expenses!A:E` kept returning a 400 error until I identified the exact tab name from the sheet metadata.

**3. `append` wrote to the wrong columns**
The Google Sheets `append` method finds the last row with *any* data — but my sheet has summary tables in columns F–J that sit further down than the expense rows. The API was appending at row 215 in column C instead of column A. Fixed by reading the last row in column A specifically and using `update` to write to the exact next row.

**4. Multiple bot instances caused Telegram conflicts**
Restarting the script without killing the previous process caused a `409 Conflict` error from Telegram. Every restart required `pkill -f expense_bot.py` first.

**5. Launch agent failed silently on macOS**
Using `launchctl` to auto-start the bot on login returned `Error 5: Input/output error` with no useful detail. The fix was switching to a shell script registered as a Login Item in System Settings — simpler and more transparent.

**6. Environment variables don't persist across Terminal sessions**
The Anthropic API key set with `export` disappears when Terminal closes. Solved by storing it in `~/.zshrc` and referencing it in the startup script.

**7. Making it work 24/7 was harder than making it work once**
Getting the bot running was straightforward. Keeping it running permanently — surviving Terminal closes, Mac restarts, and crashes — was a separate engineering problem entirely. See the section below.

---

## Making It 24/7: The Decisions

From the start, the goal wasn't just to build something that works — it was to build something that works *all the time*, without babysitting it.

A bot you have to manually restart every morning isn't a tool. It's a chore.

**The options I evaluated:**

| Approach | Pros | Cons | Decision |
|---|---|---|---|
| Run manually in Terminal | Simple | Dies when Terminal closes | ❌ Rejected |
| `nohup` background process | Survives Terminal close | Dies on Mac restart | ❌ Partial |
| macOS Launch Agent (`launchctl`) | Native, auto-restarts | Failed silently with Error 5, no useful debug output | ❌ Abandoned |
| Login Item + shell script | Simple, transparent, survives restarts | Requires Mac to be logged in | ✅ Chosen |

**What I landed on:**

A shell script (`start.sh`) that loads the API key from the environment and starts the bot, registered as a macOS Login Item via System Settings → General → Login Items. macOS runs it automatically on every login.

The bot also runs with `KeepAlive` intent — if the process crashes, the Login Item restarts it on next login. Not perfect uptime, but good enough for a personal tool on a machine that's always on.

**What I'd do differently at scale:**

For a production deployment serving multiple users, the right answer is a cloud VM (e.g. a $6/month DigitalOcean droplet) running the bot as a `systemd` service. That gives true 24/7 uptime independent of any personal machine, with proper restart-on-crash behaviour and remote log access. The Python code is identical — only the deployment environment changes.

---

## Learnings

**1. Start with the interface, not the backend**
I wasted time on the backend before confirming the interface was right. Telegram turned out to be a better choice than a web UI — it's already installed, it handles notifications natively, and I don't need to maintain it.

**2. LLMs handle ambiguity better than regex**
The first attempt used regex to parse messages like "add $12 for lunch." Edge cases broke it constantly — no dollar sign, different date formats, typos. Routing through Claude and asking it to return structured JSON handled all of this cleanly with a fraction of the code.

**3. The Sheets API is finicky about ranges**
Documentation makes it look simple. In practice: tab names with spaces, columns with mixed data, and the difference between `append` and `update` all create subtle bugs that only surface at runtime.

**4. Security hygiene matters even for personal projects**
API keys were shared in a chat session during development. The right pattern: store secrets in environment variables, never in code, never in chat. Rotate credentials after any accidental exposure.

**5. Deployment is a product decision, not just an engineering one**
The choice of *where* and *how* to run the bot is as important as the bot itself. Running locally keeps costs at zero and setup simple, but introduces single-machine dependency. The decision to use a Login Item over a cloud server was a deliberate tradeoff — right for a personal tool, wrong for a product. Knowing the difference matters.

**6. Non-engineers can ship working AI agents**
This was built without a software engineering background. The real skill wasn't coding — it was knowing what to build, how to frame the problem, and how to debug systematically when things broke.

---

## What This Could Become

This is a personal tool solving a personal problem. But the pattern is reusable.

**For individuals:** The same architecture works for any Google Sheet workflow — workout logs, habit tracking, time tracking, inventory. Swap the sheet and the categories, the bot works the same way.

**For small teams:** A shared Telegram group + shared sheet means a whole team can log expenses, tasks, or data points through natural language. No app, no new tool to learn.

**For businesses:** The core pattern — *natural language in, structured data out, existing system as the database* — applies to CRMs, project management tools, inventory systems. The real opportunity is replacing low-value data entry workflows that nobody wants to do but everyone has to.

**Next logical features:**
- Receipt photo parsing — send a photo, bot extracts amount and vendor automatically
- Weekly/monthly spend summaries pushed proactively every Sunday
- Budget alerts — notify when a category exceeds a set threshold
- Multi-user support with per-user sheet rows
- Voice note input via Telegram audio messages

---

## Security & Privacy

Building with AI APIs means handling credentials, personal data, and third-party services. These are the risks, the recommended approach for each, and the reasoning.

| Concern | Risk | Recommended Approach | Why |
|---|---|---|---|
| API keys hardcoded in source code | Keys get pushed to GitHub and become publicly accessible, allowing anyone to use your accounts and incur charges | Store all secrets in a `.env` file, load via `python-dotenv`, add `.env` to `.gitignore` | `.gitignore` prevents the file from ever being committed. Environment variables keep secrets out of the codebase entirely |
| Service account JSON committed to repo | Full read/write access to your Google Sheet exposed publicly | Store as a separate `service_account.json` file, listed in `.gitignore`, never hardcoded | The JSON contains a private key that grants permanent access to your sheet until manually revoked |
| Bot responding to any Telegram user | Anyone who finds your bot username can interact with it and read or write your financial data | Whitelist a single `ALLOWED_USER_ID` — all other users get silently rejected | Telegram bot usernames are discoverable. Without a user whitelist, the bot is publicly accessible |
| Expense data sent to Claude API | Your spending details leave your machine and are processed by a third-party model | Anthropic does not train on API data by default. Only send the minimum needed — amounts, categories, vendors | Review Anthropic's data usage policy. Avoid sending full names, account numbers, or sensitive personal identifiers |
| Credentials shared in chat during development | Keys pasted into a chat session are stored in conversation history and visible to the AI provider | Rotate all credentials immediately after any accidental exposure. Treat any shared secret as compromised | This happened during the build of this project. All keys were rotated after the session |
| Service account has broad sheet access | A compromised service account could read or modify your entire spreadsheet history | Scope the service account to Editor access on one specific sheet only, not the entire Google Drive | Principle of least privilege — limit blast radius if credentials are ever leaked |
| Secrets in startup scripts | `start.sh` or `.zshrc` storing API keys in plaintext on disk | Acceptable for personal local use. For production, use a secrets manager (e.g. AWS Secrets Manager, HashiCorp Vault) | Local plaintext is a reasonable tradeoff for a single-user personal tool. It becomes unacceptable the moment other people or systems are involved |
| No HTTPS / encryption in transit | Data intercepted between bot and APIs | All API calls (Telegram, Anthropic, Google) use HTTPS by default via their official SDKs | Verify you are always using official SDK methods, not raw HTTP calls without TLS |

### What This Repo Does Correctly

- All secrets loaded from environment variables via `.env`
- `.env` and `service_account.json` listed in `.gitignore`
- Single authorised user ID — bot rejects all other Telegram users
- Service account scoped to one sheet with Editor access only
- No personal identifiers sent to Claude beyond what the user types

### What You Should Do Before Pushing to GitHub

1. Confirm `.env` and `service_account.json` are in `.gitignore`
2. Run `git status` — neither file should appear
3. Rotate any credentials that were previously hardcoded or shared in chat
4. Scan commit history with [git-secrets](https://github.com/awslabs/git-secrets) or [trufflehog](https://github.com/trufflesecurity/trufflehog) to ensure no keys were ever committed

---

---

## Setup

### Prerequisites
- Python 3.10+
- A Google Cloud project with Sheets API enabled
- A service account with Editor access to your sheet
- A Telegram bot token from [@BotFather](https://t.me/botfather)
- An Anthropic API key from [console.anthropic.com](https://console.anthropic.com)

### Installation

```bash
git clone https://github.com/yourusername/expense-agent
cd expense-agent
pip install -r requirements.txt
```

### Configuration

Copy the example environment file and fill in your values:
```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_TOKEN=your_telegram_bot_token
ALLOWED_USER_ID=your_telegram_user_id
ANTHROPIC_API_KEY=your_anthropic_api_key
SHEET_ID=your_google_sheet_id
SHEET_TAB=2026 Expenses
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
```

Save your Google service account JSON file as `service_account.json` in the project root. Never commit this file — it is already listed in `.gitignore`.

### Running

```bash
python3 expense_bot.py
```

To run in the background:
```bash
nohup python3 expense_bot.py > bot.log 2>&1 &
```

---

## Project Structure

```
expense-agent/
├── expense_bot.py      # Main bot logic
├── requirements.txt    # Python dependencies
├── start.sh            # Startup script for background running
├── bot.log             # Runtime logs (auto-generated)
└── README.md
```

---

## Dependencies

```
python-telegram-bot==20.7
anthropic
google-auth
google-api-python-client
```

---

*Built by Francis Foo — April 2026*
