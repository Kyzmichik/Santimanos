import os
import sqlite3
from datetime import timezone
from zoneinfo import ZoneInfo

import click

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Увійдіть, щоб побачити цю сторінку."
login_manager.login_message_category = "error"
csrf = CSRFProtect()


@event.listens_for(Engine, "connect")
def _sqlite_unicode_lower(dbapi_con, _record):
    """SQLite вміє lower() лише для латиниці — підміняємо, щоб пошук
    працював без урахування регістру і для кирилиці."""
    if isinstance(dbapi_con, sqlite3.Connection):
        dbapi_con.create_function(
            "lower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True
        )


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    for sub in ("avatars", "portfolio", "requests", "reviews", "messages"):
        os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], sub), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth import bp as auth_bp
    from .account import bp as account_bp
    from .catalog import bp as catalog_bp
    from .jobs import bp as jobs_bp
    from .reviews import bp as reviews_bp
    from .messages import bp as messages_bp, unread_count
    from .admin import bp as admin_bp
    from .models import District, User

    app.register_blueprint(auth_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(admin_bp)

    from .scenes import scene_for

    app.jinja_env.globals["scene_for"] = scene_for
    app.jinja_env.globals["district_names"] = lambda: [
        d.name for d in District.query.order_by(District.name)
    ]

    @app.before_request
    def reject_blocked_users():
        if current_user.is_authenticated and current_user.is_blocked:
            logout_user()
            flash("Ваш акаунт заблоковано адміністратором.", "error")
            return redirect(url_for("catalog.index"))

    @app.cli.command("send-digest")
    def send_digest():
        """Надіслати денні дайджести нових заявок майстрам (запускайте раз на день за розкладом)."""
        from .notifications import send_daily_digests

        click.echo(f"Надіслано дайджестів: {send_daily_digests()}")

    @app.cli.command("make-admin")
    @click.argument("email")
    def make_admin(email):
        """Призначити користувача адміністратором: flask --app run make-admin email@example.com"""
        user = User.query.filter_by(email=email.lower().strip()).first()
        if not user:
            raise click.ClickException("Користувача з таким email не знайдено.")
        user.is_admin = True
        db.session.commit()
        click.echo(f"{user.email} тепер адміністратор.")

    @app.context_processor
    def inject_globals():
        unread = unread_count(current_user.id) if current_user.is_authenticated else 0
        return {"currency": app.config["CURRENCY"], "unread_messages": unread}

    @app.template_filter("money")
    def money(value):
        if value is None:
            return ""
        return f"{value:,.0f}".replace(",", " ") if float(value).is_integer() else f"{value:,.2f}"

    @app.template_filter("uk_date")
    def uk_date(value):
        return value.strftime("%d.%m.%Y") if value else ""

    @app.template_filter("local_dt")
    def local_dt(value, fmt="%d.%m.%Y %H:%M"):
        """Час у БД зберігається в UTC; показуємо в часовому поясі з конфігурації."""
        if not value:
            return ""
        try:
            tz = ZoneInfo(app.config["TIMEZONE"])
        except Exception:
            tz = timezone.utc
        return value.replace(tzinfo=timezone.utc).astimezone(tz).strftime(fmt)

    @app.template_filter("review_word")
    def review_word(n):
        n = abs(int(n))
        if 11 <= n % 100 <= 14:
            return "відгуків"
        if n % 10 == 1:
            return "відгук"
        if 2 <= n % 10 <= 4:
            return "відгуки"
        return "відгуків"

    @app.errorhandler(404)
    def not_found(_):
        return render_template("404.html"), 404

    @app.errorhandler(429)
    def too_many(_):
        return render_template("429.html"), 429

    @app.errorhandler(413)
    def too_large(_):
        flash("Файл завеликий. Максимум — 8 МБ.", "error")
        return redirect(request.referrer or url_for("catalog.index"))

    with app.app_context():
        from .seed import seed_defaults

        from .dbupgrade import upgrade_schema

        db.create_all()
        upgrade_schema()
        seed_defaults()

    return app
