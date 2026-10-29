from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from . import db
from .forms import ReplyForm, ReportForm, ReviewForm
from .mailer import notify
from .models import JobRequest, Report, Review, ReviewEdit, _now
from .security import confirmed_required
from .utils import save_image

bp = Blueprint("reviews", __name__)


def _to_master_reviews(master_id):
    return redirect(url_for("catalog.master_detail", master_id=master_id) + "#reviews")


@bp.route("/requests/<int:job_id>/review", methods=["GET", "POST"])
@confirmed_required
def create(job_id):
    job = db.get_or_404(JobRequest, job_id)
    if job.customer_id != current_user.id:
        abort(404)
    if job.status != "done" or not job.chosen_master_id:
        flash("Відгук можна залишити після виконання заявки.", "error")
        return redirect(url_for("jobs.detail", job_id=job.id))
    if job.review:
        flash("Ви вже залишили відгук за цією заявкою.", "error")
        return redirect(url_for("jobs.detail", job_id=job.id))

    form = ReviewForm()
    if form.validate_on_submit():
        photo = None
        if form.photo.data and form.photo.data.filename:
            photo = save_image(form.photo.data, "reviews", 1400)
            if not photo:
                flash("Не вдалося обробити фото. Відгук не збережено.", "error")
                return render_template("reviews/form.html", form=form, job=job, editing=False)
        db.session.add(
            Review(
                request_id=job.id,
                author_id=current_user.id,
                master_id=job.chosen_master_id,
                rating=form.rating.data,
                kind=form.kind.data,
                text=form.text.data.strip(),
                photo=photo,
            )
        )
        db.session.commit()
        flash("Дякуємо! Відгук опубліковано.", "success")
        notify(
            job.chosen_master.user,
            "Новий відгук у вашому профілі — Santimanos",
            "Замовник залишив відгук про вашу роботу.\n\nПереглянути й відповісти: "
            + url_for("reviews.mine", _external=True),
        )
        return _to_master_reviews(job.chosen_master_id)
    return render_template("reviews/form.html", form=form, job=job, editing=False)


@bp.route("/reviews/<int:review_id>/edit", methods=["GET", "POST"])
@login_required
def edit(review_id):
    rv = db.get_or_404(Review, review_id)
    if rv.author_id != current_user.id:
        abort(404)
    if not rv.can_edit:
        flash("Час редагування відгуку (48 годин) минув.", "error")
        return _to_master_reviews(rv.master_id)

    form = ReviewForm(obj=rv)
    del form.photo
    if form.validate_on_submit():
        db.session.add(
            ReviewEdit(review_id=rv.id, old_rating=rv.rating, old_kind=rv.kind, old_text=rv.text)
        )
        rv.rating = form.rating.data
        rv.kind = form.kind.data
        rv.text = form.text.data.strip()
        rv.updated_at = _now()
        db.session.commit()
        flash("Відгук оновлено.", "success")
        return _to_master_reviews(rv.master_id)
    return render_template("reviews/form.html", form=form, job=rv.request, editing=True, rv=rv)


@bp.route("/reviews/<int:review_id>/reply", methods=["POST"])
@login_required
def reply(review_id):
    rv = db.get_or_404(Review, review_id)
    if not current_user.master or rv.master_id != current_user.master.id:
        abort(404)
    if rv.reply_text:
        flash("Ви вже відповіли на цей відгук.", "error")
        return redirect(url_for("reviews.mine"))
    form = ReplyForm()
    if form.validate_on_submit():
        rv.reply_text = form.text.data.strip()
        rv.reply_at = _now()
        db.session.commit()
        flash("Відповідь опубліковано.", "success")
    else:
        for errors in form.errors.values():
            for e in errors:
                flash(e, "error")
    return redirect(url_for("reviews.mine"))


@bp.route("/reviews/<int:review_id>/report", methods=["GET", "POST"])
@login_required
def report(review_id):
    rv = db.get_or_404(Review, review_id)
    if rv.author_id == current_user.id or rv.is_hidden:
        abort(404)
    if Report.query.filter_by(review_id=rv.id, reporter_id=current_user.id).first():
        flash("Ви вже надсилали скаргу на цей відгук.", "error")
        return _to_master_reviews(rv.master_id)
    form = ReportForm()
    if form.validate_on_submit():
        db.session.add(
            Report(
                review_id=rv.id,
                reporter_id=current_user.id,
                reason=form.reason.data,
                comment=(form.comment.data or "").strip() or None,
            )
        )
        db.session.commit()
        flash("Скаргу надіслано на модерацію.", "success")
        return _to_master_reviews(rv.master_id)
    return render_template("reviews/report.html", form=form, rv=rv)


@bp.route("/account/reviews")
@login_required
def mine():
    received = current_user.master.public_reviews if current_user.master else []
    written = sorted(current_user.reviews_written, key=lambda r: r.created_at, reverse=True)
    return render_template("account/reviews.html", received=received, written=written)
