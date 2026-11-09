"""Email Josh each new picks / results file the picks job writes (Josh, Nov 9, 2026: GitHub sends the emails, no Claude
tasks). One email per window:

  picks/YYYY-MM-DD.json              night-game picks (Thursday / Monday / Saturday night; Sunday's go in the Sunday email)
  picks/sunday/YYYY-MM-DD.json       Sunday picks, all slates (Saturday night)
  picks/headsup/YYYY-MM-DD-night.json  Sunday-night update, only when something changed
  picks/sunday/YYYY-MM-DD-results.json Sunday results, all slates (after the night game)
  picks/YYYY-MM-DD-results.json      night-game results (Friday / Tuesday morning; Sunday's are in the Sunday results)

Each file is sent once: sent paths are kept in picks/sent.json. On the very first run every file that already exists is
marked as sent without emailing, so turning this on doesn't resend old weeks. Uses Gmail SMTP with an app password
(secrets SMTP_USER, SMTP_PASS, EMAIL_TO); without them it does nothing.
"""
import json
import os
import re
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})(-results)?$")
FOOT = "For entertainment. 21+ · Gamble responsibly · 1-800-GAMBLER"
SETUP_EMAIL = {   # sent once, on the first run with the secrets
    "subject": "🏈 Mingus Picks emails are on",
    "text": "GitHub can send your picks emails now. From here on, each new picks or results file is emailed once, "
            f"straight from the picks job.\n\n{FOOT}",
    "html": "<p>GitHub can send your picks emails now. From here on, each new picks or results file is emailed once, "
            f'straight from the picks job.</p><p style="color:#666;font-size:13px">{FOOT}</p>',
}


def due(store):
    """Every file that gets an email, as (relative path, doc)."""
    picks = Path(store) / "picks"
    out = []
    for f in sorted(picks.glob("*.json")):
        m = DAY.match(f.stem)
        if m and date.fromisoformat(m.group(1)).weekday() != 6:   # Sunday's night game is in the Sunday emails
            out.append(f)
    out += sorted((picks / "sunday").glob("*.json"))
    out += sorted((picks / "headsup").glob("*-night.json"))
    docs = []
    for f in out:
        try:
            doc = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if (doc.get("email") or {}).get("subject"):
            docs.append((str(f.relative_to(store)), doc))
    return docs


def send_new(store, send, to):
    """Send every due file not in picks/sent.json; returns the paths sent. `send(to, email)` does the sending."""
    log = Path(store) / "picks" / "sent.json"
    files = due(store)
    if not log.exists():
        log.parent.mkdir(parents=True, exist_ok=True)
        send(to, SETUP_EMAIL)       # proves the Gmail secrets work, without resending old weeks
        log.write_text(json.dumps({"sent": [p for p, _ in files]}, indent=1))
        return ["setup check"]
    sent = set(json.loads(log.read_text()).get("sent", []))
    done = []
    for path, doc in files:
        if path in sent:
            continue
        send(to, doc["email"])
        sent.add(path)
        done.append(path)
        log.write_text(json.dumps({"sent": sorted(sent)}, indent=1))   # saved after each, so a failure never resends
    return done


def gmail(user, password):
    def send(to, email):
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = email["subject"], f"Mingus Picks <{user}>", to
        msg.set_content(email.get("text") or "")
        if email.get("html"):
            msg.add_alternative(email["html"], subtype="html")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    return send


def main(argv=None):
    store = (argv or sys.argv[1:] or ["store"])[0]
    user, password, to = (os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASS", "EMAIL_TO"))
    if not (user and password and to):
        print("Emails: SMTP_USER / SMTP_PASS / EMAIL_TO not set, nothing sent.")
        return
    done = send_new(store, gmail(user, password.replace(" ", "")), to)
    print("Emails sent: " + (", ".join(done) if done else "none new."))


if __name__ == "__main__":
    main()
