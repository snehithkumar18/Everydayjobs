"""Send the digest over SMTP. Gmail: use an App Password, not your login."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def send(subject: str, html_body: str, attachments: list[str] | None = None) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.getenv("MAIL_TO", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content("This digest is HTML. Open it in an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    if attachments:
        for fpath in attachments:
            if not fpath or not os.path.exists(fpath):
                continue
            fname = os.path.basename(fpath)
            try:
                with open(fpath, "rb") as f:
                    file_data = f.read()
                maintype = "application"
                subtype = "pdf" if fname.endswith(".pdf") else "octet-stream"
                msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=fname)
            except Exception as e:
                print(f"  ! failed attaching {fname}: {e}")

    import time
    last_err = None
    for attempt in range(1, 4):
        try:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(user, password)
                s.send_message(msg)
            print(f"  mailed -> {to_addr} (with {len(attachments or [])} attachments)")
            return
        except Exception as e:
            last_err = e
            print(f"  ! SMTP attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                time.sleep(3.0)

    raise last_err
