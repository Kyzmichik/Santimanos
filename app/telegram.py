"""Сповіщення в Telegram.

Як це працює:
1. У кабінеті користувач натискає «Підключити Telegram» → отримує посилання
   https://t.me/<бот>?start=<одноразовий код> (діє годину).
2. Telegram відкриває бота, користувач тисне «Start», бот отримує «/start <код>»
   і запам'ятовує chat_id цього користувача.
3. Далі mailer.notify() дублює кожне сповіщення в Telegram.

Оновлення від Telegram приходять на webhook (/telegram/webhook) — для сервера,
або командою `flask --app run telegram-poll` — для локальної розробки.
"""
import json
import secrets
import threading
import time
import urllib.request
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required

from . import csrf, db
from .models import User, _now

bp = Blueprint("telegram", __name__)

API = "https://api.telegram.org/bot{token}/{method}"
LINK_TTL = timedelta(hours=1)
MAX_TEXT = 4000  # Telegram приймає до 4096 символів


def enabled():
    cfg = current_app.config
    return bool(cfg.get("TELEGRAM_BOT_TOKEN") and cfg.get("TELEGRAM_BOT_NAME"))


def api_call(token, method, payload=None, timeout=15):
    req = urllib.request.Request(
        API.format(token=token, method=method),
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _send(token, chat_id, text):
    try:
        api_call(token, "sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    except Exception as exc:  # Telegram не повинен валити сайт
        print(f"[TELEGRAM ERROR] {chat_id}: {exc}")


def send_message(chat_id, text):
    app = current_app._get_current_object()
    text = text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"
    outbox = app.extensions.setdefault("tg_outbox", [])
    outbox.append({"chat_id": chat_id, "text": text})
    del outbox[:-100]
    token = app.config.get("TELEGRAM_BOT_TOKEN")
    if app.config.get("TESTING"):
        return
    if not token:
        print(f"\n[DEV TELEGRAM] chat={chat_id}\n{text}\n")
        return
    threading.Thread(target=_send, args=(token, chat_id, text), daemon=True).start()


# --------------------------------------------------------------------------
# Кабінет: підключення й налаштування
# --------------------------------------------------------------------------

@bp.route("/account/telegram/link", methods=["POST"])
@login_required
def link():
    if not enabled():
        abort(404)
    current_user.telegram_link_code = secrets.token_urlsafe(16)
    current_user.telegram_link_at = _now()
    db.session.commit()
    bot = current_app.config["TELEGRAM_BOT_NAME"].lstrip("@")
    return redirect(f"https://t.me/{bot}?start={current_user.telegram_link_code}")


@bp.route("/account/telegram/toggle", methods=["POST"])
@login_required
def toggle():
    current_user.notify_telegram = not current_user.notify_telegram
    db.session.commit()
    flash("Сповіщення в Telegram " + ("увімкнено." if current_user.notify_telegram else "вимкнено."), "success")
    return redirect(url_for("account.profile"))


@bp.route("/account/telegram/unlink", methods=["POST"])
@login_required
def unlink():
    current_user.telegram_chat_id = None
    db.session.commit()
    flash("Telegram відключено.", "success")
    return redirect(url_for("account.profile"))


# --------------------------------------------------------------------------
# Бот
# --------------------------------------------------------------------------

HELP = (
    "Це бот сповіщень Santimanos.\n\n"
    "Щоб отримувати тут повідомлення, відгуки й нові заявки, відкрийте кабінет на сайті "
    "і натисніть «Підключити Telegram».\n\n/stop — вимкнути сповіщення."
)


def handle_update(update):
    """Обробляє одне оновлення від Telegram. Відповідає лише в приватних чатах."""
    msg = update.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or not chat.get("id"):
        return
    chat_id = str(chat["id"])
    text = (msg.get("text") or "").strip()

    if text.startswith("/start"):
        code = text[len("/start"):].strip()
        if not code:
            return send_message(chat_id, HELP)
        user = User.query.filter_by(telegram_link_code=code).first()
        if not user or not user.telegram_link_at or _now() - user.telegram_link_at > LINK_TTL:
            return send_message(chat_id, "Посилання недійсне або застаріло. Натисніть «Підключити Telegram» у кабінеті ще раз.")
        # один чат — один акаунт
        User.query.filter(User.telegram_chat_id == chat_id, User.id != user.id).update(
            {User.telegram_chat_id: None}
        )
        user.telegram_chat_id = chat_id
        user.telegram_link_code = None
        user.notify_telegram = True
        db.session.commit()
        return send_message(chat_id, f"Готово, {user.first_name}! Сповіщення Santimanos тепер приходитимуть сюди.\n\n/stop — вимкнути.")

    if text == "/stop":
        changed = User.query.filter_by(telegram_chat_id=chat_id).update({User.telegram_chat_id: None})
        db.session.commit()
        return send_message(chat_id, "Сповіщення вимкнено." if changed else HELP)

    send_message(chat_id, HELP)


@bp.route("/telegram/webhook", methods=["POST"])
@csrf.exempt
def webhook():
    secret = current_app.config.get("TELEGRAM_WEBHOOK_SECRET")
    if not secret or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        abort(404)
    handle_update(request.get_json(silent=True) or {})
    return {"ok": True}


def set_webhook():
    cfg = current_app.config
    url = cfg["SITE_URL"].rstrip("/") + url_for("telegram.webhook")
    return api_call(
        cfg["TELEGRAM_BOT_TOKEN"],
        "setWebhook",
        {"url": url, "secret_token": cfg["TELEGRAM_WEBHOOK_SECRET"], "allowed_updates": ["message"]},
    )


def poll_forever(echo):
    """Long polling для локальної розробки (коли сайт недоступний з інтернету)."""
    token = current_app.config["TELEGRAM_BOT_TOKEN"]
    api_call(token, "deleteWebhook")
    offset = None
    echo("Слухаю Telegram… Ctrl+C — зупинити.")
    while True:
        try:
            data = api_call(token, "getUpdates", {"timeout": 30, "offset": offset}, timeout=40)
        except Exception as exc:
            echo(f"Помилка з'єднання: {exc}")
            time.sleep(5)
            continue
        for update in data.get("result", []):
            offset = update["update_id"] + 1
            handle_update(update)
