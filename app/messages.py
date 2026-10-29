from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from . import db
from .mailer import notify
from .models import Conversation, JobRequest, MasterProfile, Message, _now
from .security import confirmed_required, rate_limit
from .utils import check_clean, save_image

bp = Blueprint("messages", __name__, url_prefix="/messages")

MAX_LEN = 2000


def unread_count(user_id):
    return (
        db.session.query(func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .join(MasterProfile, Conversation.master_id == MasterProfile.id)
        .filter(
            Message.sender_id != user_id,
            Message.read_at.is_(None),
            or_(Conversation.customer_id == user_id, MasterProfile.user_id == user_id),
        )
        .scalar()
    )


def _conversation(conv_id):
    conv = db.get_or_404(Conversation, conv_id)
    if not conv.has(current_user):
        abort(404)
    return conv


def _open(customer_id, master, job=None):
    conv = Conversation.query.filter_by(customer_id=customer_id, master_id=master.id).first()
    if not conv:
        conv = Conversation(customer_id=customer_id, master_id=master.id, job_id=job.id if job else None)
        db.session.add(conv)
        db.session.commit()
    return redirect(url_for("messages.thread", conv_id=conv.id))


@bp.route("/")
@login_required
def index():
    convs = (
        Conversation.query.join(MasterProfile, Conversation.master_id == MasterProfile.id)
        .filter(
            or_(Conversation.customer_id == current_user.id, MasterProfile.user_id == current_user.id),
            Conversation.messages.any(),
        )
        .order_by(Conversation.last_message_at.desc())
        .all()
    )
    return render_template("messages/index.html", convs=convs)


@bp.route("/start/<int:master_id>")
@confirmed_required
def start(master_id):
    m = db.get_or_404(MasterProfile, master_id)
    if m.user_id == current_user.id or not (m.user.is_master and m.is_published) or m.user.is_blocked:
        abort(404)
    return _open(current_user.id, m)


@bp.route("/job/<int:job_id>")
@confirmed_required
def from_job(job_id):
    """Майстер пише замовнику із сторінки заявки."""
    job = db.get_or_404(JobRequest, job_id)
    if not current_user.is_master or not current_user.master or job.customer_id == current_user.id:
        abort(404)
    return _open(job.customer_id, current_user.master, job)


@bp.route("/job/<int:job_id>/master/<int:master_id>")
@confirmed_required
def to_responder(job_id, master_id):
    """Замовник пише майстру, що відгукнувся на його заявку."""
    job = db.get_or_404(JobRequest, job_id)
    if job.customer_id != current_user.id or not any(r.master_id == master_id for r in job.responses):
        abort(404)
    m = db.get_or_404(MasterProfile, master_id)
    return _open(current_user.id, m, job)


def _payload(msg):
    return {
        "id": msg.id,
        "text": msg.text or "",
        "photo": url_for("static", filename="uploads/messages/" + msg.photo) if msg.photo else None,
        "time": current_app.jinja_env.filters["local_dt"](msg.created_at, "%d.%m %H:%M"),
    }


def _mark_read(conv):
    now = _now()
    changed = False
    for m in conv.messages:
        if m.sender_id != current_user.id and m.read_at is None:
            m.read_at = now
            changed = True
    if changed:
        db.session.commit()


@bp.route("/<int:conv_id>", methods=["GET", "POST"])
@rate_limit("message", 30, 60)
@confirmed_required
def thread(conv_id):
    conv = _conversation(conv_id)
    other = conv.other(current_user)

    if request.method == "POST":
        text = (request.form.get("text") or "").strip()
        file = request.files.get("photo")
        has_file = bool(file and file.filename)
        error = None
        if not text and not has_file:
            error = "Напишіть повідомлення або додайте фото."
        elif len(text) > MAX_LEN:
            error = f"Повідомлення задовге (максимум {MAX_LEN} символів)."
        elif other.is_blocked:
            error = "Цей користувач недоступний."
        else:
            error = check_clean(text)
        photo = None
        if not error and has_file:
            photo = save_image(file, "messages", 1400)
            if not photo:
                error = "Не вдалося обробити фото."
        if error:
            flash(error, "error")
            return redirect(url_for("messages.thread", conv_id=conv.id))

        # лист надсилаємо лише на перше непрочитане повідомлення, щоб не спамити
        had_unread = (
            Message.query.filter_by(conversation_id=conv.id, sender_id=current_user.id, read_at=None).first()
            is not None
        )
        db.session.add(Message(conversation_id=conv.id, sender_id=current_user.id, text=text or None, photo=photo))
        conv.last_message_at = _now()
        db.session.commit()
        if not had_unread:
            notify(
                other,
                f"Нове повідомлення від {current_user.first_name} — Santimanos",
                f"{current_user.first_name} написав(ла) вам на Santimanos.\n\nВідповісти: "
                + url_for("messages.thread", conv_id=conv.id, _external=True),
            )
        return redirect(url_for("messages.thread", conv_id=conv.id))

    _mark_read(conv)
    last_id = conv.messages[-1].id if conv.messages else 0
    return render_template("messages/thread.html", conv=conv, other=other, last_id=last_id)


@bp.route("/<int:conv_id>/poll")
@login_required
def poll(conv_id):
    conv = _conversation(conv_id)
    after = request.args.get("after", 0, type=int)
    fresh = [m for m in conv.messages if m.id > after and m.sender_id != current_user.id]
    _mark_read(conv)
    return jsonify([_payload(m) for m in fresh])
