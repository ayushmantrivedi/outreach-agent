"""Quick SMTP connection test — run with: python test_smtp.py"""
import smtplib, ssl, os, sys
sys.path.insert(0, ".")
from ai_outreach_agent.utils import load_env
load_env()

host = os.getenv("SMTP_HOST", "smtp.gmail.com")
port = int(os.getenv("SMTP_PORT", 587))
user = os.getenv("SMTP_USER", "")
pwd  = os.getenv("SMTP_PASS", "")

print(f"Connecting to {host}:{port} as {user} ...")
try:
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=15) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.login(user, pwd)
    print("✅  SMTP login successful! Gmail credentials are working.")
except smtplib.SMTPAuthenticationError as e:
    print(f"❌  Auth failed: {e}")
    print("    Check your App Password — it should be 16 chars with no spaces.")
except Exception as e:
    print(f"❌  Connection error: {e}")
