"""Send the weekly report via Gmail SMTP (SSL).

Credentials come from environment variables (GitHub Secrets in CI):
  SUPERSTOCK_SMTP_USER  -> full Gmail address
  SUPERSTOCK_SMTP_PASS  -> 16-character Gmail *app password* (not your login password)
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def send(html: str, cfg: dict, attachment_name: str = "superstock-weekly.html") -> None:
    ecfg = cfg["email"]
    if not ecfg.get("enabled", False):
        print("[email] disabled in config; skipping send")
        return
    user = ecfg.get("username") or os.environ.get("SUPERSTOCK_SMTP_USER")
    pwd = ecfg.get("password") or os.environ.get("SUPERSTOCK_SMTP_PASS")
    if not user or not pwd:
        raise SystemExit("[email] missing credentials: set SUPERSTOCK_SMTP_USER / "
                         "SUPERSTOCK_SMTP_PASS (GitHub Secrets) or fill config.yaml")

    import datetime as dt
    msg = EmailMessage()
    msg["Subject"] = f"{ecfg.get('subject_prefix','Superstock Weekly')} \u2014 {dt.date.today():%d %b %Y}"
    msg["From"] = ecfg.get("from_addr") or user
    msg["To"] = ", ".join(ecfg["to_addrs"])
    msg.set_content("Your weekly Superstock screen is attached (HTML). "
                    "Open the attachment or view the HTML body.")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(html.encode("utf-8"), maintype="text", subtype="html",
                       filename=attachment_name)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(ecfg.get("smtp_host", "smtp.gmail.com"),
                          ecfg.get("smtp_port", 465), context=ctx) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"[email] sent to {msg['To']}")
