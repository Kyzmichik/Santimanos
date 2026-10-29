from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from flask_login import current_user, login_required

from . import db
from .forms import RequestForm, ResponseForm
from .mailer import notify
from .models import Category, JobRequest, JobResponse, MasterProfile, RequestPhoto, _now
from .notifications import notify_new_request, site_url
from .security import confirmed_required
from .utils import save_image

bp = Blueprint("jobs", __name__, url_prefix="/requests")

MAX_REQUEST_PHOTOS = 5


def _category_choices():
    parents = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    return {
        p.name: [(p.id, f"Інше: {p.name}")] + [(c.id, c.name) for c in p.children] for p in parents
    }


def _my_master():
    return current_user.master if current_user.is_master else None


def _owned_job(job_id):
    job = db.get_or_404(JobRequest, job_id)
    if job.customer_id != current_user.id:
        abort(404)
    return job


def _back(job):
    return redirect(url_for("jobs.detail", job_id=job.id))


# --------------------------------------------------------------------------
# Замовник
# --------------------------------------------------------------------------

def _hints():
    return {c.id: c.hint for c in Category.query.filter(Category.hint.isnot(None)) if c.hint}


def _invited_master():
    """Майстер, якому адресовано заявку (?master=<id>); None, якщо не підходить."""
    mid = request.args.get("master", type=int)
    m = db.session.get(MasterProfile, mid) if mid else None
    if not m or m.user_id == current_user.id:
        return None
    if not (m.user.is_master and m.is_published) or m.user.is_blocked:
        return None
    return m


@bp.route("/new", methods=["GET", "POST"])
@confirmed_required
def new():
    form = RequestForm()
    form.category_id.choices = _category_choices()
    invited = _invited_master()
    if request.method == "GET":
        form.district.data = current_user.district
        src = db.session.get(JobRequest, request.args.get("copy", type=int) or 0)
        if src and src.customer_id == current_user.id:  # «замовити ще раз»
            form.category_id.data = src.category_id
            form.title.data = src.title
            form.description.data = src.description
            form.district.data = src.district
            form.budget.data = src.budget
        elif invited and invited.categories:
            form.category_id.data = invited.categories[0].id
        elif db.session.get(Category, request.args.get("category", type=int) or 0):  # зі сторінки категорії
            form.category_id.data = request.args.get("category", type=int)
    if form.validate_on_submit():
        files = [f for f in (form.photos.data or []) if f and f.filename]
        if len(files) > MAX_REQUEST_PHOTOS:
            flash(f"Можна додати не більше {MAX_REQUEST_PHOTOS} фото.", "error")
            return render_template("jobs/new.html", form=form, invited=invited, hints=_hints())
        job = JobRequest(
            customer_id=current_user.id,
            category_id=form.category_id.data,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            district=(form.district.data or "").strip() or None,
            desired_date=form.desired_date.data,
            budget=form.budget.data,
            invited_master_id=invited.id if invited else None,
        )
        db.session.add(job)
        db.session.flush()
        skipped = 0
        for f in files:
            name = save_image(f, "requests", 1400)
            if name:
                job.photos.append(RequestPhoto(filename=name))
            else:
                skipped += 1
        db.session.commit()
        if invited:
            flash(f"Заявку надіслано майстру {invited.user.public_name(True)}.", "success")
            notify(
                invited.user,
                f"Вас запросили до заявки: {job.title}",
                f"{current_user.first_name} надіслав(ла) вам особисту заявку.\n\n{job.title}\n\n"
                f"Переглянути: {site_url(f'/requests/{job.id}')}",
            )
        else:
            flash("Заявку створено. Майстри побачать її й запропонують ціну.", "success")
            notify_new_request(job)
        if skipped:
            flash(f"Не вдалося обробити фото: {skipped}.", "error")
        return _back(job)
    return render_template("jobs/new.html", form=form, invited=invited, hints=_hints())


@bp.route("/mine")
@login_required
def mine():
    jobs = (
        JobRequest.query.filter_by(customer_id=current_user.id).order_by(JobRequest.id.desc()).all()
    )
    return render_template("jobs/mine.html", jobs=jobs)


@bp.route("/<int:job_id>/choose/<int:response_id>", methods=["POST"])
@login_required
def choose(job_id, response_id):
    job = _owned_job(job_id)
    resp = db.session.get(JobResponse, response_id)
    if not job.is_open or not resp or resp.request_id != job.id:
        flash("Обрати виконавця неможливо.", "error")
        return _back(job)
    job.chosen_master_id = resp.master_id
    job.status = "in_progress"
    db.session.commit()
    flash("Виконавця обрано. Заявка в роботі.", "success")
    notify(
        resp.master.user,
        f"Вас обрано виконавцем: «{job.title}»",
        "Замовник обрав вас виконавцем.\n\nЗаявка: " + url_for("jobs.detail", job_id=job.id, _external=True),
    )
    return _back(job)


@bp.route("/<int:job_id>/complete", methods=["POST"])
@login_required
def complete(job_id):
    job = _owned_job(job_id)
    if job.status != "in_progress":
        flash("Позначити виконаною можна лише заявку «В роботі».", "error")
        return _back(job)
    job.status = "done"
    job.completed_at = _now()
    db.session.commit()
    flash("Заявку виконано. Тепер ви можете залишити відгук про майстра.", "success")
    return redirect(url_for("reviews.create", job_id=job.id))


@bp.route("/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel(job_id):
    job = _owned_job(job_id)
    if job.status in ("done", "cancelled"):
        flash("Цю заявку вже не можна скасувати.", "error")
        return _back(job)
    job.status = "cancelled"
    db.session.commit()
    flash("Заявку скасовано.", "success")
    return _back(job)


# --------------------------------------------------------------------------
# Майстер
# --------------------------------------------------------------------------

@bp.route("/")
@login_required
def feed():
    m = _my_master()
    if not m:
        flash("Стрічка заявок доступна майстрам. Увімкніть режим майстра в кабінеті.", "error")
        return redirect(url_for("account.profile"))

    show_all = request.args.get("all") == "1"
    category_id = request.args.get("category", type=int)
    page = request.args.get("page", 1, type=int)

    # особисті заявки бачить лише запрошений майстер; вони показуються незалежно від категорій
    invited_to_me = JobRequest.invited_master_id == m.id
    query = JobRequest.query.filter(
        JobRequest.status.in_(["new", "discussing"]),
        JobRequest.customer_id != current_user.id,
        or_(JobRequest.invited_master_id.is_(None), invited_to_me),
    )
    if category_id:
        cat = db.session.get(Category, category_id)
        if cat:
            ids = [cat.id] + [c.id for c in cat.children]
            query = query.filter(or_(invited_to_me, JobRequest.category_id.in_(ids)))
    elif not show_all and m.categories:
        ids = {c.id for c in m.categories} | {c.parent_id for c in m.categories if c.parent_id}
        query = query.filter(or_(invited_to_me, JobRequest.category_id.in_(ids)))

    pagination = query.order_by(JobRequest.id.desc()).paginate(page=page, per_page=10, error_out=False)
    parents = Category.query.filter_by(parent_id=None).order_by(Category.name).all()
    return render_template(
        "jobs/feed.html",
        pagination=pagination,
        parents=parents,
        show_all=show_all,
        category_id=category_id,
        responded={r.request_id for r in m.responses},
        has_categories=bool(m.categories),
    )


@bp.route("/<int:job_id>")
@login_required
def detail(job_id):
    job = db.get_or_404(JobRequest, job_id)
    is_owner = job.customer_id == current_user.id
    m = _my_master()
    if not is_owner and (not m or (job.invited_master_id and job.invited_master_id != m.id)):
        abort(404)
    my_response = next((r for r in job.responses if m and r.master_id == m.id), None)
    can_respond = bool(m) and not is_owner and job.is_open and my_response is None
    return render_template(
        "jobs/detail.html",
        job=job,
        is_owner=is_owner,
        my_response=my_response,
        can_respond=can_respond,
        is_invited=bool(m) and job.invited_master_id == m.id,
        form=ResponseForm(),
    )


@bp.route("/<int:job_id>/respond", methods=["POST"])
@confirmed_required
def respond(job_id):
    job = db.get_or_404(JobRequest, job_id)
    m = _my_master()
    if not m or job.customer_id == current_user.id:
        abort(404)
    if job.invited_master_id and job.invited_master_id != m.id:
        abort(404)
    if not job.is_open:
        flash("Заявка вже не приймає пропозицій.", "error")
        return _back(job)
    if any(r.master_id == m.id for r in job.responses):
        flash("Ви вже відгукнулись на цю заявку.", "error")
        return _back(job)
    form = ResponseForm()
    if form.validate_on_submit():
        db.session.add(
            JobResponse(
                request_id=job.id,
                master_id=m.id,
                price=form.price.data,
                comment=(form.comment.data or "").strip() or None,
            )
        )
        if job.status == "new":
            job.status = "discussing"
        db.session.commit()
        flash("Вашу пропозицію надіслано замовнику.", "success")
        notify(
            job.customer,
            f"Нова пропозиція до заявки «{job.title}»",
            f"Майстер {current_user.first_name} запропонував ціну {form.price.data:g}.\n\nПереглянути: "
            + url_for("jobs.detail", job_id=job.id, _external=True),
        )
    else:
        for errors in form.errors.values():
            for e in errors:
                flash(e, "error")
    return _back(job)


@bp.route("/<int:job_id>/responses/<int:response_id>/withdraw", methods=["POST"])
@login_required
def withdraw(job_id, response_id):
    job = db.get_or_404(JobRequest, job_id)
    resp = db.session.get(JobResponse, response_id)
    m = _my_master()
    if not m or not resp or resp.request_id != job.id or resp.master_id != m.id:
        abort(404)
    if job.chosen_master_id == m.id:
        flash("Вас уже обрано виконавцем. Звʼяжіться із замовником.", "error")
        return _back(job)
    db.session.delete(resp)
    db.session.flush()
    if job.status == "discussing" and not [r for r in job.responses if r.id != resp.id]:
        job.status = "new"
    db.session.commit()
    flash("Пропозицію відкликано.", "success")
    return _back(job)


@bp.route("/<int:job_id>/decline", methods=["POST"])
@login_required
def decline(job_id):
    """Запрошений майстер відхиляє особисту заявку — вона відкривається для інших майстрів."""
    job = db.get_or_404(JobRequest, job_id)
    m = _my_master()
    if not m or job.invited_master_id != m.id or not job.is_open or job.responses:
        abort(404)
    job.invited_master_id = None
    db.session.commit()
    notify(
        job.customer,
        f"Майстер відхилив заявку «{job.title}»",
        "Майстер не зможе виконати заявку, тож її відкрито для інших майстрів у категорії.\n\n"
        + site_url(f"/requests/{job.id}"),
    )
    notify_new_request(job, exclude_user_ids={current_user.id})
    flash("Ви відхилили запрошення. Заявка відкрита для інших майстрів.", "success")
    return redirect(url_for("jobs.feed"))
