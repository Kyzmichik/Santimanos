from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from . import db
from .forms import ReportForm
from .seed import CATEGORY_ORDER
from .models import Category, Favorite, JobRequest, MasterProfile, ProfileReport, Review, Service, User

bp = Blueprint("catalog", __name__)

SORT_LABELS = {
    "new": "Спочатку нові",
    "rating": "За рейтингом",
    "reviews": "За кількістю відгуків",
    "exp": "Найбільший досвід",
    "price": "Найдешевші",
}


def _visible_masters():
    return MasterProfile.query.join(User).filter(
        User.is_master.is_(True), User.is_blocked.is_(False), MasterProfile.is_published.is_(True)
    )


def _review_stat(fn):
    """Скалярний підзапит (avg / count) по видимих відгуках майстра."""
    return (
        db.select(fn(Review.rating))
        .where(Review.master_id == MasterProfile.id, Review.is_hidden.is_(False))
        .correlate(MasterProfile)
        .scalar_subquery()
    )


# Рейтинг для «топу»: середня оцінка, «підтягнута» до PRIOR_MEAN, поки відгуків мало.
# Так один відгук на 5★ не обганяє 4.9 зі ста відгуків.
PRIOR_MEAN, PRIOR_WEIGHT = 4.0, 3


def ranked(query, with_reviews_only=False):
    """Сортування майстрів за зваженим рейтингом, далі — за кількістю відгуків."""
    total = db.func.coalesce(_review_stat(db.func.sum), 0)
    cnt = _review_stat(db.func.count)
    score = (total + PRIOR_MEAN * PRIOR_WEIGHT) / (cnt + PRIOR_WEIGHT)
    if with_reviews_only:
        query = query.filter(cnt > 0)
    return query.order_by(score.desc(), cnt.desc(), MasterProfile.id.desc())


def latest_reviews(limit=6, category_ids=None, city_names=None):
    """Свіжі позитивні відгуки про видимих майстрів (головна, сторінки категорій і міст)."""
    query = (
        Review.query.join(MasterProfile, Review.master_id == MasterProfile.id)
        .join(User, MasterProfile.user_id == User.id)
        .filter(
            Review.is_hidden.is_(False),
            Review.kind == "praise",
            Review.rating >= 4,
            User.is_master.is_(True),
            User.is_blocked.is_(False),
            MasterProfile.is_published.is_(True),
        )
    )
    if category_ids:
        query = query.join(JobRequest, Review.request_id == JobRequest.id).filter(
            JobRequest.category_id.in_(category_ids)
        )
    if city_names:
        query = query.filter(User.city.in_(city_names))
    return query.order_by(Review.id.desc()).limit(limit).all()


def main_categories():
    return sorted(
        Category.query.filter_by(parent_id=None).all(),
        key=lambda p: (CATEGORY_ORDER.get(p.name, 999), p.id),
    )


@bp.route("/")
def index():
    top = ranked(_visible_masters(), with_reviews_only=True).limit(6).all()
    latest = _visible_masters().order_by(MasterProfile.id.desc()).limit(6).all()
    return render_template(
        "index.html", parents=main_categories(), top=top, latest=latest, reviews=latest_reviews()
    )


@bp.route("/masters")
def masters():
    q = request.args.get("q", "").strip()
    district = request.args.get("district", "").strip()
    city = request.args.get("city", "").strip()
    category_id = request.args.get("category", type=int)
    max_price = request.args.get("max_price", type=float)
    min_rating = request.args.get("min_rating", type=float)
    sort = request.args.get("sort", "new")
    page = request.args.get("page", 1, type=int)

    query = _visible_masters()
    avg, cnt = _review_stat(db.func.avg), _review_stat(db.func.count)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                MasterProfile.headline.ilike(like),
                MasterProfile.description.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                MasterProfile.services.any(Service.title.ilike(like)),
            )
        )
    if district:
        like = f"%{district}%"
        query = query.filter(or_(User.district.ilike(like), MasterProfile.districts.ilike(like)))
    if city:
        query = query.filter(db.func.lower(db.func.trim(User.city)) == city.lower())
    if category_id:
        cat = db.session.get(Category, category_id)
        if cat:
            ids = [cat.id] + [c.id for c in cat.children]
            query = query.filter(MasterProfile.categories.any(Category.id.in_(ids)))
    if max_price is not None:
        query = query.filter(MasterProfile.services.any(Service.price <= max_price))
    if min_rating:
        query = query.filter(avg >= min_rating)

    if sort == "rating":
        query = query.order_by(avg.desc().nulls_last(), cnt.desc(), MasterProfile.id.desc())
    elif sort == "reviews":
        query = query.order_by(cnt.desc(), MasterProfile.id.desc())
    elif sort == "exp":
        query = query.order_by(MasterProfile.experience_years.desc().nulls_last())
    elif sort == "price":
        min_price = (
            db.select(db.func.min(Service.price))
            .where(Service.master_id == MasterProfile.id)
            .correlate(MasterProfile)
            .scalar_subquery()
        )
        query = query.order_by(min_price.asc().nulls_last())
    else:
        sort = "new"
        query = query.order_by(MasterProfile.id.desc())

    pagination = query.paginate(page=page, per_page=9, error_out=False)
    parents = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template(
        "catalog/masters.html",
        pagination=pagination,
        parents=parents,
        args=args,
        sorts=SORT_LABELS,
        f={
            "q": q,
            "district": district,
            "city": city,
            "category": category_id,
            "max_price": request.args.get("max_price", ""),
            "min_rating": request.args.get("min_rating", ""),
            "sort": sort,
        },
    )


@bp.route("/masters/<int:master_id>")
def master_detail(master_id):
    m = db.session.get(MasterProfile, master_id)
    if not m:
        abort(404)
    is_owner = current_user.is_authenticated and current_user.id == m.user_id
    if not is_owner and not (m.user.is_master and m.is_published and not m.user.is_blocked):
        abort(404)
    is_fav = (
        current_user.is_authenticated
        and Favorite.query.filter_by(user_id=current_user.id, master_id=m.id).first() is not None
    )
    return render_template("catalog/master.html", m=m, u=m.user, is_owner=is_owner, is_fav=is_fav)


@bp.route("/masters/<int:master_id>/report", methods=["GET", "POST"])
@login_required
def report_profile(master_id):
    m = db.get_or_404(MasterProfile, master_id)
    if m.user_id == current_user.id:
        abort(404)
    if ProfileReport.query.filter_by(user_id=m.user_id, reporter_id=current_user.id).first():
        flash("Ви вже надсилали скаргу на цей профіль.", "error")
        return redirect(url_for("catalog.master_detail", master_id=m.id))
    form = ReportForm()
    if form.validate_on_submit():
        db.session.add(
            ProfileReport(
                user_id=m.user_id,
                reporter_id=current_user.id,
                reason=form.reason.data,
                comment=(form.comment.data or "").strip() or None,
            )
        )
        db.session.commit()
        flash("Скаргу на профіль надіслано на модерацію.", "success")
        return redirect(url_for("catalog.master_detail", master_id=m.id))
    return render_template("catalog/report_profile.html", form=form, m=m)


@bp.route("/masters/<int:master_id>/favorite", methods=["POST"])
@login_required
def toggle_favorite(master_id):
    m = db.get_or_404(MasterProfile, master_id)
    if m.user_id == current_user.id or not (m.user.is_master and m.is_published and not m.user.is_blocked):
        abort(404)
    fav = Favorite.query.filter_by(user_id=current_user.id, master_id=m.id).first()
    if fav:
        db.session.delete(fav)
        flash("Майстра прибрано з обраного.", "success")
    else:
        db.session.add(Favorite(user_id=current_user.id, master_id=m.id))
        flash("Майстра додано в обране.", "success")
    db.session.commit()
    return redirect(url_for("catalog.master_detail", master_id=m.id))
