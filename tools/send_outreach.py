"""Send the outreach emails in outbox.json from shaw@bconz.com via GoDaddy (secureserver.net).

Run it yourself in a terminal:
    python send_outreach.py                   every email in outbox.json
    python send_outreach.py --draft <code>    one draft, from DIA's "Copy send command"
- Your mailbox password is typed at a hidden prompt; it is never stored or written anywhere.
- Each email is shown in full and sent only if you type "y".
- Sent emails are recorded in sent_log.csv and skipped on later runs, so nobody gets it twice.
- Recipients listed in do_not_contact.txt (one address per line) are always skipped.
- A copy of each sent email is saved to your Sent folder over IMAP.
"""
import argparse
import base64
import csv
import getpass
import imaplib
import json
import re
import smtplib
import ssl
import time
import webbrowser
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

SENDER = "shaw@bconz.com"
SENDER_NAME = "Shaw | BCONZ"
SMTP_HOST, SMTP_PORT = "smtpout.secureserver.net", 465
IMAP_HOST, IMAP_PORT = "imap.secureserver.net", 993

HERE = Path(__file__).parent
OUTBOX, LOG, DNC = HERE / "outbox.json", HERE / "sent_log.csv", HERE / "do_not_contact.txt"


def already_sent() -> set[str]:
    if not LOG.exists():
        return set()
    with LOG.open(encoding="utf-8", newline="") as f:
        return {row["to"].lower() for row in csv.DictReader(f)}


def do_not_contact() -> set[str]:
    if not DNC.exists():
        return set()
    return {l.strip().lower() for l in DNC.read_text(encoding="utf-8").splitlines() if l.strip()}


def build(m: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{SENDER_NAME} <{SENDER}>"
    msg["To"] = m["to"]
    msg["Subject"] = m["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="bconz.com")
    msg["List-Unsubscribe"] = f"<mailto:{SENDER}?subject=unsubscribe>"
    msg.set_content(m["body"])
    return msg


def save_to_sent(msg: EmailMessage, password: str) -> None:
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(SENDER, password)
            folder = next((f for f in ("Sent", "Sent Items", "INBOX.Sent")
                           if imap.select(f'"{f}"')[0] == "OK"), None)
            if folder:
                imap.append(f'"{folder}"', r"(\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
                return
        print("   (couldn't find a Sent folder; the email was sent but no copy was saved)")
    except Exception as e:  # sending succeeded; a missing copy isn't fatal
        print(f"   (email sent, but saving a copy to Sent failed: {e})")


EMAIL_OK = re.compile(r"^[\w.+'-]+@[\w-]+(\.[\w-]+)+$")
WHERE_PLACEHOLDER = "[where you found it]"


def log_sent(m: dict, msg: EmailMessage) -> None:
    new = not LOG.exists()
    with LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["sent_at_utc", "to", "subject", "message_id"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), m["to"], m["subject"], msg["Message-ID"]])


def review_and_send(todo: list[dict]) -> list[dict]:
    """Show each email, send the ones confirmed with "y". Returns those sent."""
    password = getpass.getpass(f"Password for {SENDER} (hidden): ")
    sent = []
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=30) as smtp:
        smtp.login(SENDER, password)
        for m in todo:
            print("\n" + "=" * 72 + f"\nTo:      {m['to']}\nSubject: {m['subject']}\n" + "-" * 72)
            print(m["body"])
            if input("Send this one? [y/N] ").strip().lower() != "y":
                print("   skipped")
                continue
            msg = build(m)
            smtp.send_message(msg)
            print("   sent")
            save_to_sent(msg, password)
            log_sent(m, msg)
            sent.append(m)
            time.sleep(5)
    del password
    return sent


def from_draft(code: str) -> None:
    """One draft copied from DIA ("Copy send command"): the draft travels in
    the command itself, so no API token is needed on this machine."""
    pad = "=" * (-len(code) % 4)
    m = json.loads(base64.urlsafe_b64decode(code + pad).decode("utf-8"))
    to = (m.get("to") or "").strip()
    while not EMAIL_OK.match(to):
        to = input("Recipient email: ").strip()
    m["to"] = to
    if WHERE_PLACEHOLDER in m["body"]:
        where = ""
        while not where:
            where = input("Where did you find this address? (e.g. company.com/contact): ").strip()
        m["body"] = m["body"].replace(WHERE_PLACEHOLDER, where)
    if to.lower() in do_not_contact():
        print(f"{to} is on do_not_contact.txt: not sent.")
        return
    if to.lower() in already_sent():
        if input(f"You've already emailed {to}. Send anyway (a follow-up)? [y/N] ").strip().lower() != "y":
            return
    if review_and_send([m]) and m.get("mark_sent_url"):
        print("Marking it as sent in DIA (opens your browser)…")
        webbrowser.open(m["mark_sent_url"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--draft", help="one draft, as copied from DIA's 'Copy send command'")
    ap.add_argument("outbox", nargs="?", default=str(OUTBOX), help="outbox JSON (default: outbox.json here)")
    args = ap.parse_args()
    if args.draft:
        from_draft(args.draft)
        return
    queue = json.loads(Path(args.outbox).read_text(encoding="utf-8"))
    skip = already_sent() | do_not_contact()
    todo = [m for m in queue if m["to"].lower() not in skip]
    print(f"{len(queue)} in outbox, {len(queue) - len(todo)} skipped (already sent or do-not-contact), {len(todo)} to review.")
    if todo:
        review_and_send(todo)


if __name__ == "__main__":
    main()
