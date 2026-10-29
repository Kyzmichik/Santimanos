"""PWA: сайт можна встановити на телефон як застосунок.

Service worker віддається з кореня (/sw.js), щоб керувати всім сайтом.
Він кешує лише статику (стилі, скрипти, іконки) і сторінку «Немає з'єднання» —
особисті сторінки (чат, кабінет) не кешуються.
"""
import hashlib
import os

from flask import Blueprint, current_app, render_template, url_for

bp = Blueprint("pwa", __name__)

PRECACHE = ("style.css", "ui.js", "icons/icon-192.png", "icons/favicon.svg")


@bp.route("/manifest.webmanifest")
def manifest():
    def icon(name):
        return url_for("static", filename=f"icons/{name}")

    data = {
        "name": "Santimanos — майстри поруч",
        "short_name": "Santimanos",
        "description": "Знайдіть майстра для ремонту, саду, прибирання та інших робіт.",
        "lang": "uk",
        "start_url": url_for("catalog.index") + "?source=pwa",
        "scope": url_for("catalog.index"),
        "display": "standalone",
        "background_color": "#F5F7FB",
        "theme_color": "#2B59C3",
        "icons": [
            {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": icon("icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Створити заявку", "url": url_for("jobs.new")},
            {"name": "Майстри", "url": url_for("catalog.masters")},
            {"name": "Повідомлення", "url": url_for("messages.index")},
        ],
    }
    return current_app.response_class(current_app.json.dumps(data), mimetype="application/manifest+json")


def _static_version():
    """Версія кешу змінюється разом зі статикою — старий кеш видаляється автоматично."""
    h = hashlib.sha1()
    for name in PRECACHE:
        path = os.path.join(current_app.static_folder, name)
        if os.path.exists(path):
            h.update(f"{name}:{os.path.getmtime(path)}".encode())
    return h.hexdigest()[:10]


@bp.route("/sw.js")
def service_worker():
    js = render_template(
        "pwa/sw.js",
        version=_static_version(),
        precache=[url_for("pwa.offline")] + [url_for("static", filename=n) for n in PRECACHE],
    )
    resp = current_app.response_class(js, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/offline")
def offline():
    return render_template("pwa/offline.html")
