from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, logout_user

from . import db
from .forms import (
    AvatarForm, ChangePasswordForm, DeleteAccountForm, MasterForm, PhotoForm, ProfileForm,
    ServiceForm,
)
from .models import Category, JobRequest, MasterProfile, PortfolioPhoto, Service
from .utils import delete_image, save_image

bp = Blueprint("account", __name__, url_prefix="/account")


def master_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_master or not current_user.master:
            flash("Спочатку увімкніть режим майстра.", "error")
            return redirect(url_for("account.profile"))
        return view(*args, **kwargs)

    return login_required(wrapper)


def flash_errors(form):
    for errors in form.errors.values():
        for e in errors:
            flash(e, "error")


# --------------------------------------------------------------------------
# Особисті дані та аватарка
# --------------------------------------------------------------------------

@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        form.populate_obj(current_user)
        current_user.phone = (current_user.phone or "").strip() or None
        db.session.commit()
        flash("Дані збережено.", "success")
        return redirect(url_for("account.profile"))
    return render_template(
        "account/profile.html",
        form=form,
        avatar_form=AvatarForm(),
        delete_form=DeleteAccountForm(),
        password_form=ChangePasswordForm(),
    )


@bp.route("/password", methods=["POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if not form.validate_on_submit():
        flash_errors(form)
    elif not current_user.check_password(form.current_password.data):
        flash("Поточний пароль невірний.", "error")
    else:
        current_user.set_password(form.password.data)
        db.session.commit()
        flash("Пароль змінено.", "success")
    return redirect(url_for("account.profile"))


@bp.route("/avatar", methods=["POST"])
@login_required
def upload_avatar():
    form = AvatarForm()
    if not form.validate_on_submit():
        flash_errors(form)
        return redirect(url_for("account.profile"))
    name = save_image(form.avatar.data, "avatars", 400, square=True)
    if not name:
        flash("Не вдалося обробити зображення. Спробуйте інший файл.", "error")
        return redirect(url_for("account.profile"))
    delete_image("avatars", current_user.avatar)
    current_user.avatar = name
    db.session.commit()
    flash("Аватарку оновлено.", "success")
    return redirect(url_for("account.profile"))


@bp.route("/avatar/delete", methods=["POST"])
@login_required
def delete_avatar():
    delete_image("avatars", current_user.avatar)
    current_user.avatar = None
    db.session.commit()
    flash("Аватарку видалено.", "success")
    return redirect(url_for("account.profile"))


def _purge_files(user):
    """Видаляє з диска всі файли, що зникнуть разом з акаунтом."""
    delete_image("avatars", user.avatar)
    for job in user.requests:
        for p in job.photos:
            delete_image("requests", p.filename)
        if job.review:
            delete_image("reviews", job.review.photo)
    for rv in user.reviews_written:
        delete_image("reviews", rv.photo)
    if user.master:
        for p in user.master.photos:
            delete_image("portfolio", p.filename)
        for rv in user.master.reviews:
            delete_image("reviews", rv.photo)
    conversations = list(user.conversations) + (list(user.master.conversations) if user.master else [])
    for conv in conversations:
        for msg in conv.messages:
            delete_image("messages", msg.photo)


@bp.route("/delete", methods=["POST"])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if not form.validate_on_submit() or not current_user.check_password(form.password.data):
        flash("Невірний пароль. Акаунт не видалено.", "error")
        return redirect(url_for("account.profile"))
    user = current_user._get_current_object()
    _purge_files(user)
    if user.master:
        # заявки, де цього майстра було обрано виконавцем і які ще в роботі, скасовуються
        JobRequest.query.filter(
            JobRequest.chosen_master_id == user.master.id, JobRequest.status == "in_progress"
        ).update({"status": "cancelled"})
    logout_user()
    db.session.delete(user)
    db.session.commit()
    flash("Акаунт видалено.", "success")
    return redirect(url_for("catalog.index"))


# --------------------------------------------------------------------------
# Резюме майстра
# --------------------------------------------------------------------------

@bp.route("/master/toggle", methods=["POST"])
@login_required
def toggle_master():
    if current_user.is_master:
        current_user.is_master = False
        flash("Режим майстра вимкнено. Ваше резюме приховано з каталогу.", "success")
        db.session.commit()
        return redirect(url_for("account.profile"))
    current_user.is_master = True
    if not current_user.master:
        current_user.master = MasterProfile()
    db.session.commit()
    flash("Режим майстра увімкнено. Заповніть резюме.", "success")
    return redirect(url_for("account.master"))


@bp.route("/master", methods=["GET", "POST"])
@master_required
def master():
    m = current_user.master
    form = MasterForm(obj=m)
    all_categories = Category.query.order_by(Category.name).all()
    form.categories.choices = [(c.id, c.name) for c in all_categories]
    if not form.is_submitted():
        form.categories.data = [c.id for c in m.categories]
        form.notify_new_requests.data = current_user.notify_new_requests

    if form.validate_on_submit():
        m.headline = (form.headline.data or "").strip() or None
        m.description = (form.description.data or "").strip() or None
        m.experience_years = form.experience_years.data
        m.schedule = (form.schedule.data or "").strip() or None
        m.districts = (form.districts.data or "").strip() or None
        m.is_published = form.is_published.data
        current_user.notify_new_requests = form.notify_new_requests.data
        m.categories = [c for c in all_categories if c.id in form.categories.data]
        db.session.commit()
        flash("Резюме збережено.", "success")
        return redirect(url_for("account.master"))

    parents = [c for c in all_categories if c.parent_id is None]
    return render_template(
        "account/master.html",
        form=form,
        parents=parents,
        service_form=ServiceForm(),
        photo_form=PhotoForm(),
    )


@bp.route("/master/services", methods=["POST"])
@master_required
def add_service():
    form = ServiceForm()
    if form.validate_on_submit():
        db.session.add(
            Service(
                master_id=current_user.master.id,
                title=form.title.data.strip(),
                price=form.price.data,
                unit=form.unit.data,
            )
        )
        db.session.commit()
        flash("Послугу додано.", "success")
    else:
        flash_errors(form)
    return redirect(url_for("account.master") + "#services")


@bp.route("/master/services/<int:service_id>/delete", methods=["POST"])
@master_required
def delete_service(service_id):
    s = db.session.get(Service, service_id)
    if not s or s.master_id != current_user.master.id:
        abort(404)
    db.session.delete(s)
    db.session.commit()
    flash("Послугу видалено.", "success")
    return redirect(url_for("account.master") + "#services")


@bp.route("/master/photos", methods=["POST"])
@master_required
def add_photo():
    from flask import current_app

    m = current_user.master
    if len(m.photos) >= current_app.config["MAX_PORTFOLIO_PHOTOS"]:
        flash(f"Максимум {current_app.config['MAX_PORTFOLIO_PHOTOS']} фото в портфоліо.", "error")
        return redirect(url_for("account.master") + "#portfolio")
    form = PhotoForm()
    if not form.validate_on_submit():
        flash_errors(form)
        return redirect(url_for("account.master") + "#portfolio")
    name = save_image(form.photo.data, "portfolio", 1400)
    if not name:
        flash("Не вдалося обробити зображення. Спробуйте інший файл.", "error")
    else:
        db.session.add(
            PortfolioPhoto(master_id=m.id, filename=name, caption=(form.caption.data or "").strip() or None)
        )
        db.session.commit()
        flash("Фото додано.", "success")
    return redirect(url_for("account.master") + "#portfolio")


@bp.route("/master/photos/<int:photo_id>/delete", methods=["POST"])
@master_required
def delete_photo(photo_id):
    p = db.session.get(PortfolioPhoto, photo_id)
    if not p or p.master_id != current_user.master.id:
        abort(404)
    delete_image("portfolio", p.filename)
    db.session.delete(p)
    db.session.commit()
    flash("Фото видалено.", "success")
    return redirect(url_for("account.master") + "#portfolio")


# --------------------------------------------------------------------------
# Обране
# --------------------------------------------------------------------------

@bp.route("/favorites")
@login_required
def favorites():
    masters = [
        f.master
        for f in sorted(current_user.favorites, key=lambda f: f.created_at, reverse=True)
        if f.master.user.is_master and f.master.is_published and not f.master.user.is_blocked
    ]
    return render_template("account/favorites.html", masters=masters)
