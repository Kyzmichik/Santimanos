from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import db
from .forms import ForgotForm, LoginForm, RegisterForm, ResetForm
from .mailer import make_token, read_token, send_email
from .models import MasterProfile, User
from .security import rate_limit

bp = Blueprint("auth", __name__)

CONFIRM_MAX_AGE = 3 * 24 * 3600
RESET_MAX_AGE = 3600


def _safe_next(target):
    """Дозволяє перенаправлення лише на внутрішні адреси."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


def _send_confirmation(user):
    token = make_token({"id": user.id, "email": user.email}, "confirm")
    link = url_for("auth.confirm", token=token, _external=True)
    send_email(
        user.email,
        "Підтвердіть email у Santimanos",
        f"Вітаємо, {user.first_name}!\n\nПідтвердіть адресу за посиланням (діє 3 дні):\n{link}\n",
    )


@bp.route("/register", methods=["GET", "POST"])
@rate_limit("register", 10, 3600)
def register():
    if current_user.is_authenticated:
        return redirect(url_for("account.profile"))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            email=form.email.data.lower().strip(),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            is_master=form.is_master.data,
        )
        user.set_password(form.password.data)
        if user.is_master:
            user.master = MasterProfile()
        db.session.add(user)
        db.session.commit()
        login_user(user)
        _send_confirmation(user)
        flash("Вітаємо в Santimanos! Ми надіслали лист для підтвердження email.", "success")
        return redirect(url_for("account.master" if user.is_master else "account.profile"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
@rate_limit("login", 10, 60)
def login():
    if current_user.is_authenticated:
        return redirect(url_for("account.profile"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            if user.is_blocked:
                flash("Акаунт заблоковано адміністратором.", "error")
            else:
                login_user(user, remember=form.remember.data)
                return redirect(_safe_next(request.args.get("next")) or url_for("account.profile"))
        else:
            flash("Невірний email або пароль.", "error")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Ви вийшли з акаунта.", "success")
    return redirect(url_for("catalog.index"))


# --------------------------------------------------------------------------
# Підтвердження email
# --------------------------------------------------------------------------

@bp.route("/confirm/<token>")
def confirm(token):
    data = read_token(token, "confirm", CONFIRM_MAX_AGE)
    user = db.session.get(User, data["id"]) if data else None
    if not user or user.email != data["email"]:
        flash("Посилання недійсне або застаріло. Надішліть лист ще раз із кабінету.", "error")
        return redirect(url_for("catalog.index"))
    user.email_confirmed = True
    db.session.commit()
    flash("Email підтверджено. Дякуємо!", "success")
    return redirect(url_for("account.profile" if current_user.is_authenticated else "auth.login"))


@bp.route("/confirm/resend", methods=["POST"])
@rate_limit("resend", 3, 3600)
@login_required
def resend_confirmation():
    if current_user.email_confirmed:
        flash("Email уже підтверджено.", "success")
    else:
        _send_confirmation(current_user)
        flash("Лист надіслано повторно.", "success")
    return redirect(url_for("account.profile"))


# --------------------------------------------------------------------------
# Відновлення пароля
# --------------------------------------------------------------------------

@bp.route("/forgot", methods=["GET", "POST"])
@rate_limit("forgot", 5, 3600)
def forgot():
    form = ForgotForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and not user.is_blocked:
            # частина хешу пароля робить посилання одноразовим: після зміни пароля воно перестає діяти
            token = make_token({"id": user.id, "h": user.password_hash[-12:]}, "reset")
            link = url_for("auth.reset", token=token, _external=True)
            send_email(
                user.email,
                "Відновлення пароля Santimanos",
                f"Щоб задати новий пароль, перейдіть за посиланням (діє 1 годину):\n{link}\n\n"
                "Якщо ви не робили цього запиту, просто проігноруйте лист.",
            )
        flash("Якщо такий email зареєстровано, ми надіслали лист із посиланням для відновлення.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    data = read_token(token, "reset", RESET_MAX_AGE)
    user = db.session.get(User, data["id"]) if data else None
    if not user or user.password_hash[-12:] != data["h"]:
        flash("Посилання недійсне або застаріло. Запросіть нове.", "error")
        return redirect(url_for("auth.forgot"))
    form = ResetForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Пароль змінено. Тепер можна увійти.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form)
