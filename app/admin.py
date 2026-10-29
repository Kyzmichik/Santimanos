from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from . import db
from .models import (
    REQUEST_STATUS, Category, District, JobRequest, MasterProfile, Message, ProfileReport,
    Report, Review, User, _now,
)
from .security import admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _back(endpoint):
    return redirect(url_for(endpoint))


def _back_param(default_endpoint):
    """Повертає на адресу з форми, але лише всередині /admin (захист від open redirect)."""
    target = request.form.get("back", "")
    if target.startswith("/admin") and "//" not in target:
        return redirect(target)
    return redirect(url_for(default_endpoint))


@bp.route("/")
@admin_required
def dashboard():
    week = _now() - timedelta(days=7)
    month = _now() - timedelta(days=30)
    stats = {
        "Користувачів": User.query.count(),
        "Майстрів": User.query.filter_by(is_master=True).count(),
        "Підтверджених майстрів": User.query.filter_by(is_master=True, is_verified=True).count(),
        "Заблокованих": User.query.filter_by(is_blocked=True).count(),
        "Реєстрацій за 7 днів": User.query.filter(User.created_at >= week).count(),
        "Реєстрацій за 30 днів": User.query.filter(User.created_at >= month).count(),
        "Заявок усього": JobRequest.query.count(),
        "Заявок за 7 днів": JobRequest.query.filter(JobRequest.created_at >= week).count(),
        "Відгуків": Review.query.count(),
        "Прихованих відгуків": Review.query.filter_by(is_hidden=True).count(),
        "Повідомлень": Message.query.count(),
    }
    by_status = {label: JobRequest.query.filter_by(status=key).count() for key, label in REQUEST_STATUS.items()}
    open_reports = (
        Report.query.filter_by(status="open").count()
        + ProfileReport.query.filter_by(status="open").count()
    )
    return render_template("admin/dashboard.html", stats=stats, by_status=by_status, open_reports=open_reports)


# --------------------------------------------------------------------------
# Користувачі
# --------------------------------------------------------------------------

@bp.route("/users")
@admin_required
def users():
    q = request.args.get("q", "").strip()
    flt = request.args.get("f", "")
    page = request.args.get("page", 1, type=int)
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(User.email.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like))
        )
    if flt == "blocked":
        query = query.filter(User.is_blocked.is_(True))
    elif flt == "masters":
        query = query.filter(User.is_master.is_(True))
    elif flt == "unverified":
        query = query.filter(User.is_master.is_(True), User.is_verified.is_(False))
    pagination = query.order_by(User.id.desc()).paginate(page=page, per_page=25, error_out=False)
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template("admin/users.html", pagination=pagination, q=q, flt=flt, args=args)


@bp.route("/users/<int:user_id>/block", methods=["POST"])
@admin_required
def toggle_block(user_id):
    user = db.get_or_404(User, user_id)
    if user.is_admin:
        flash("Адміністратора заблокувати не можна.", "error")
    else:
        user.is_blocked = not user.is_blocked
        db.session.commit()
        flash("Користувача заблоковано." if user.is_blocked else "Користувача розблоковано.", "success")
    return _back_param("admin.users")


@bp.route("/users/<int:user_id>/verify", methods=["POST"])
@admin_required
def toggle_verify(user_id):
    user = db.get_or_404(User, user_id)
    user.is_verified = not user.is_verified
    db.session.commit()
    flash("Особу підтверджено." if user.is_verified else "Підтвердження знято.", "success")
    return _back_param("admin.users")


# --------------------------------------------------------------------------
# Скарги
# --------------------------------------------------------------------------

@bp.route("/reports")
@admin_required
def reports():
    grouped = {}
    for r in Report.query.filter_by(status="open").order_by(Report.id).all():
        grouped.setdefault(r.review, []).append(r)
    return render_template(
        "admin/reports.html",
        grouped=grouped,
        profile_reports=ProfileReport.query.filter_by(status="open").order_by(ProfileReport.id).all(),
        hidden=Review.query.filter_by(is_hidden=True).order_by(Review.id.desc()).all(),
    )


def _resolve_review_reports(review):
    for r in review.reports:
        r.status = "resolved"


@bp.route("/reviews/<int:review_id>/hide", methods=["POST"])
@admin_required
def hide_review(review_id):
    rv = db.get_or_404(Review, review_id)
    rv.is_hidden = True
    _resolve_review_reports(rv)
    db.session.commit()
    flash("Відгук приховано з профілю майстра.", "success")
    return _back("admin.reports")


@bp.route("/reviews/<int:review_id>/restore", methods=["POST"])
@admin_required
def restore_review(review_id):
    rv = db.get_or_404(Review, review_id)
    rv.is_hidden = False
    db.session.commit()
    flash("Відгук повернуто в профіль.", "success")
    return _back("admin.reports")


@bp.route("/reviews/<int:review_id>/dismiss", methods=["POST"])
@admin_required
def dismiss_review_reports(review_id):
    _resolve_review_reports(db.get_or_404(Review, review_id))
    db.session.commit()
    flash("Скарги відхилено, відгук залишено.", "success")
    return _back("admin.reports")


@bp.route("/profile-reports/<int:report_id>/resolve", methods=["POST"])
@admin_required
def resolve_profile_report(report_id):
    rep = db.get_or_404(ProfileReport, report_id)
    rep.status = "resolved"
    db.session.commit()
    flash("Скаргу закрито.", "success")
    return _back("admin.reports")


# --------------------------------------------------------------------------
# Категорії
# --------------------------------------------------------------------------

@bp.route("/categories")
@admin_required
def categories():
    parents = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    return render_template("admin/categories.html", parents=parents)


@bp.route("/categories/add", methods=["POST"])
@admin_required
def category_add():
    name = request.form.get("name", "").strip()[:80]
    parent_id = request.form.get("parent_id", type=int)
    parent = db.session.get(Category, parent_id) if parent_id else None
    if not name:
        flash("Вкажіть назву категорії.", "error")
    elif parent and parent.parent_id:
        flash("Підкатегорія не може мати власних підкатегорій.", "error")
    elif Category.query.filter(
        db.func.lower(Category.name) == name.lower(), Category.parent_id == (parent.id if parent else None)
    ).first():
        flash("Така категорія вже існує.", "error")
    else:
        db.session.add(Category(name=name, parent_id=parent.id if parent else None))
        db.session.commit()
        flash("Категорію додано.", "success")
    return _back("admin.categories")


@bp.route("/categories/<int:cat_id>/rename", methods=["POST"])
@admin_required
def category_rename(cat_id):
    cat = db.get_or_404(Category, cat_id)
    name = request.form.get("name", "").strip()[:80]
    if not name:
        flash("Назва не може бути порожньою.", "error")
    else:
        cat.name = name
        cat.hint = request.form.get("hint", "").strip()[:500] or None
        db.session.commit()
        flash("Категорію оновлено.", "success")
    return _back("admin.categories")


@bp.route("/categories/<int:cat_id>/delete", methods=["POST"])
@admin_required
def category_delete(cat_id):
    cat = db.get_or_404(Category, cat_id)
    used = (
        JobRequest.query.filter_by(category_id=cat.id).first()
        or MasterProfile.query.filter(MasterProfile.categories.any(Category.id == cat.id)).first()
    )
    if cat.children:
        flash("Спочатку видаліть підкатегорії.", "error")
    elif used:
        flash("Категорію використовують заявки або майстри — видалити не можна. Перейменуйте її.", "error")
    else:
        db.session.delete(cat)
        db.session.commit()
        flash("Категорію видалено.", "success")
    return _back("admin.categories")


# --------------------------------------------------------------------------
# Райони
# --------------------------------------------------------------------------

@bp.route("/districts")
@admin_required
def districts():
    return render_template("admin/districts.html", districts=District.query.order_by(District.name).all())


@bp.route("/districts/add", methods=["POST"])
@admin_required
def district_add():
    names = [n.strip()[:80] for n in request.form.get("names", "").replace("\n", ",").split(",")]
    added = 0
    for name in filter(None, names):
        if not District.query.filter(db.func.lower(District.name) == name.lower()).first():
            db.session.add(District(name=name))
            db.session.flush()
            added += 1
    db.session.commit()
    flash(f"Додано районів: {added}." if added else "Нічого не додано (порожньо або вже є).", "success" if added else "error")
    return _back("admin.districts")


@bp.route("/districts/<int:district_id>/delete", methods=["POST"])
@admin_required
def district_delete(district_id):
    db.session.delete(db.get_or_404(District, district_id))
    db.session.commit()
    flash("Район видалено.", "success")
    return _back("admin.districts")
