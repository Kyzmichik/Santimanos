import smtplib
import threading
from email.message import EmailMessage

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _smtp_send(config, to, subject, body):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config["MAIL_FROM"], to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=15) as smtp:
            if config["MAIL_USE_TLS"]:
                smtp.starttls()
            if config["MAIL_USERNAME"]:
                smtp.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
            smtp.send_message(msg)
    except Exception as exc:  # пошта не повинна валити сайт
        print(f"[MAIL ERROR] {to}: {exc}")


def send_email(to, subject, body):
    app = current_app._get_current_object()
    outbox = app.extensions.setdefault("outbox", [])
    outbox.append({"to": to, "subject": subject, "body": body})
    del outbox[:-100]
    if not app.config.get("MAIL_SERVER"):
        if not app.config.get("TESTING"):
            print(f"\n[DEV EMAIL] to={to}\nsubject: {subject}\n{body}\n")
        return
    config = {k: app.config[k] for k in app.config if k.startswith("MAIL_")}
    threading.Thread(target=_smtp_send, args=(config, to, subject, body), daemon=True).start()


def notify(user, subject, body):
    """Сповіщення на email і в Telegram; кожен канал користувач вимикає в кабінеті."""
    if not user:
        return
    if user.notify_email and user.email:
        send_email(user.email, subject, body)
    if user.telegram_chat_id and user.notify_telegram:
        from .telegram import send_message

        send_message(user.telegram_chat_id, f"{subject}\n\n{body}")


def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def make_token(data, salt):
    return _serializer(salt).dumps(data)


def read_token(token, salt, max_age):
    try:
        return _serializer(salt).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
