# AI Outreach Agent

An autonomous, fully open-source system that discovers AI companies, scores their relevance to your projects using a **local LLM** (Ollama), generates personalised outreach emails, sends them, monitors for replies, and notifies you via Telegram — all orchestrated by a daily Prefect pipeline.

---

## 🗂 Project Structure

```
agent3/
├── ai_outreach_agent/
│   ├── agents/               # Core autonomous agents
│   ├── scrapers/             # Company discovery scrapers
│   ├── database/             # PostgreSQL schema & helpers
│   ├── models/               # LLM & embedding model wrappers
│   ├── pipelines/            # Prefect daily pipeline
│   ├── notifications/        # Telegram notifier
│   └── config/
│       └── settings.yaml     # 👈 Edit THIS to switch projects
├── tests/                    # Smoke tests (no real services needed)
├── main.py                   # CLI entry point
├── requirements.txt
└── .env.example              # Copy to .env and fill in credentials
```

---

## ⚙️ Prerequisites — What You Need to Install

### 1. Python 3.10+
Download from [python.org](https://www.python.org/downloads/)

### 2. PostgreSQL
- **Windows**: Download from [postgresql.org/download/windows](https://www.postgresql.org/download/windows/)
- After install, open **pgAdmin** or **psql** and create the database:
```sql
CREATE DATABASE outreach_db;
```

### 3. Ollama (Local LLM)
- Download from [ollama.ai](https://ollama.ai)
- After install, pull a model:
```bash
ollama pull llama3
# or
ollama pull mistral
```
- Start the server (runs automatically on Windows after install):
```bash
ollama serve
```

### 4. Playwright Browsers
After installing Python dependencies:
```bash
playwright install chromium
```

---

## 🚀 Setup & First Run

### Step 1 — Install Python dependencies
```bash
cd c:\Users\ayush\OneDrive\Desktop\agent3
pip install -r requirements.txt
playwright install chromium
```

### Step 2 — Set up environment variables
```bash
copy ai_outreach_agent\.env.example ai_outreach_agent\.env
# Then edit .env with your credentials
```

Required credentials:
| Variable | Where to get it |
|---|---|
| `DATABASE_URL` | Your local PostgreSQL connection string |
| `SMTP_USER` / `SMTP_PASS` | Gmail + [App Password](https://myaccount.google.com/apppasswords) |
| `IMAP_USER` / `IMAP_PASS` | Same Gmail account |
| `TELEGRAM_BOT_TOKEN` | Create bot at [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Message [@userinfobot](https://t.me/userinfobot) |

### Step 3 — Apply the database schema
```bash
python main.py --mode schema
```

### Step 4 — Edit your project config
Open `ai_outreach_agent/config/settings.yaml` and fill in:
- `project_name`, `github_repo`, `project_description`
- `developer_name`, `developer_title`, `developer_linkedin`
- `email_template` (`engineering_role` | `research` | `showcase`)

### Step 5 — Ingest your project knowledge
```bash
python main.py --mode ingest
```

### Step 6 — Run the full pipeline
```bash
python main.py --mode pipeline
```

---

## 🕹 CLI Commands

| Command | Description |
|---|---|
| `python main.py --mode pipeline` | Run full daily pipeline |
| `python main.py --mode discover` | Scrape new companies only |
| `python main.py --mode rank` | Score companies with LLM |
| `python main.py --mode ingest` | Embed project into ChromaDB |
| `python main.py --mode send` | Generate + send emails |
| `python main.py --mode monitor` | Watch inbox continuously |
| `python main.py --mode schema` | Apply/update DB schema |
| `python main.py --mode status` | Show stats dashboard |

---

## 🧪 Running Tests
```bash
pytest tests/ -v
```
Tests are mocked — no real DB, Ollama, or SMTP needed.

---

## 🔄 Switching Projects

Edit `ai_outreach_agent/config/settings.yaml`:
```yaml
project_name: "My New Project"
github_repo: "https://github.com/you/new-repo"
project_description: "..."
email_template: "showcase"
```

Then re-run ingest to update the knowledge base:
```bash
python main.py --mode ingest
```

---

## 🗓 Scheduling the Pipeline

To run the pipeline automatically every day using Prefect:

```bash
# Start Prefect server (one-time setup)
prefect server start

# In a new terminal, deploy the flow
prefect deploy ai_outreach_agent/pipelines/daily_outreach_pipeline.py:daily_outreach_pipeline \
  --name local --interval 86400

# Start the worker
prefect worker start --pool default-agent-pool
```

---

## 📊 Data Sources

| Source | Method |
|---|---|
| **Y Combinator** | Public Algolia API (no key needed) |
| **GitHub Orgs** | GitHub REST API (token optional) |
| **There's An AI For That** | BeautifulSoup HTML scraping |
| **Greenhouse / Lever** | Public job board APIs |
