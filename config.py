import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ВАЖЛИВО: на реальному сервері задайте SECRET_KEY через змінну оточення.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "santimanos.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 МБ на запит
    CURRENCY = "€"
    SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:5000")  # для посилань у листах
    TIMEZONE = os.environ.get("TIMEZONE", "UTC")  # напр. Europe/Madrid, Europe/Kyiv

    # Пошта. Без MAIL_SERVER листи лише виводяться в консоль (режим розробки).
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_FROM = os.environ.get("MAIL_FROM", "Santimanos <no-reply@santimanos.local>")

    # На реальному сайті встановіть REQUIRE_EMAIL_CONFIRMATION=1
    REQUIRE_EMAIL_CONFIRMATION = os.environ.get("REQUIRE_EMAIL_CONFIRMATION", "0") == "1"
    RATELIMIT_ENABLED = True
    MAX_PORTFOLIO_PHOTOS = 20
