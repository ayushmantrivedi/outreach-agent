"""
test_all.py — Full connectivity smoke test (ASCII-safe output)
Run with: python test_all.py
"""
import sys, os
# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, ".")

def ok(msg):  print(f"    [PASS] {msg}")
def fail(msg): print(f"    [FAIL] {msg}")
def warn(msg): print(f"    [WARN] {msg}")

print("=" * 55)
print(" AI Outreach Agent -- Connectivity Test")
print("=" * 55)

# 1. Environment
from ai_outreach_agent.utils import load_env
env_path = load_env()
print(f"\n[1] .env loaded from: {env_path}")
ok(str(env_path))

# 2. PostgreSQL
print("\n[2] Testing PostgreSQL connection ...")
try:
    from ai_outreach_agent.database.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM companies;")
            count = cur.fetchone()[0]
    ok(f"Connected! companies table has {count} rows.")
except Exception as e:
    fail(f"DB error: {e}")

# 3. Ollama
print("\n[3] Testing Ollama (phi3:mini) ...")
try:
    import requests as req
    r = req.get("http://localhost:11434/api/tags", timeout=5)
    models = [m["name"] for m in r.json().get("models", [])]
    if any("phi3" in m for m in models):
        ok(f"Ollama running. phi3:mini found.")
    else:
        warn(f"Ollama running but phi3:mini not listed. Models: {models}")
except Exception as e:
    fail(f"Ollama not reachable: {e}\n        Start Ollama from the system tray or run: ollama serve")

# 4. SMTP
print("\n[4] Testing Gmail SMTP ...")
try:
    import smtplib, ssl
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", 587))
    user = os.getenv("SMTP_USER", "")
    pwd  = os.getenv("SMTP_PASS", "")
    ctx  = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=15) as s:
        s.ehlo(); s.starttls(context=ctx); s.login(user, pwd)
    ok(f"Gmail SMTP working ({user})")
except Exception as e:
    fail(f"SMTP error: {e}")

# 5. Sentence-transformers
print("\n[5] Testing sentence-transformers ...")
try:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("all-MiniLM-L6-v2")
    vec = m.encode(["test"], show_progress_bar=False)
    ok(f"all-MiniLM-L6-v2 loaded. Vector dim: {vec.shape[1]}")
except Exception as e:
    fail(f"Error: {e}")

# 6. ChromaDB
print("\n[6] Testing ChromaDB ...")
try:
    from chromadb import PersistentClient
    client = PersistentClient(path="./chroma_store")
    col = client.get_or_create_collection("smoke_test")
    ok("ChromaDB working.")
    client.delete_collection("smoke_test")
except Exception as e:
    fail(f"ChromaDB error: {e}")

print("\n" + "=" * 55)
print(" Done! Fix any [FAIL] items before running the agent.")
print("=" * 55)
