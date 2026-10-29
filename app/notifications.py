"""Сповіщення майстрам про нові заявки: одразу або щоденним дайджестом."""
from datetime import timedelta

from flask import current_app

from . import db
from .mailer import notify
from .models import Category, JobRequest, MasterProfile, User, _now

MAX_INSTANT = 50     # скільки листів максимум на одну заявку
MAX_DIGEST_JOBS = 20


def site_url(path):
    return current_app.config["SITE_URL"].rstrip("/") + path


def masters_for_category(category, exclude_user_ids=()):
    """Майстри, яким підходить заявка. Для заявки в головній категорії — майстри з будь-якої її підкатегорії."""
    ids = [category.id] + [c.id for c in category.children]
    query = MasterProfile.query.join(User).filter(
        User.is_master.is_(True),
        User.is_blocked.is_(False),
        MasterProfile.is_published.is_(True),
        MasterProfile.categories.any(Category.id.in_(ids)),
    )
    if exclude_user_ids:
        query = query.filter(~User.id.in_(list(exclude_user_ids)))
    return query.all()


def _summary(job):
    lines = [job.title, f"Категорія: {job.category.name}"]
    if job.district:
        lines.append(f"Район: {job.district}")
    if job.budget is not None:
        lines.append(f"Бюджет: {job.budget:g}")
    lines.append(job.description[:200] + ("…" if len(job.description) > 200 else ""))
    return "\n".join(lines)


def notify_new_request(job, exclude_user_ids=()):
    """Миттєві листи майстрам з режимом «одразу». Повертає кількість надісланих."""
    exclude = set(exclude_user_ids) | {job.customer_id}
    sent = 0
    for m in masters_for_category(job.category, exclude):
        if m.user.notify_new_requests != "instant":
            continue
        notify(
            m.user,
            f"Нова заявка: {job.title}",
            f"{_summary(job)}\n\nПереглянути й запропонувати ціну: {site_url(f'/requests/{job.id}')}",
        )
        sent += 1
        if sent >= MAX_INSTANT:
            break
    return sent


def send_daily_digests():
    """Один лист на день з усіма новими заявками у категоріях майстра."""
    now = _now()
    sent = 0
    users = User.query.filter(
        User.is_master.is_(True), User.is_blocked.is_(False), User.notify_new_requests == "daily"
    ).all()
    for u in users:
        m = u.master
        since = u.last_digest_at or (now - timedelta(days=1))
        ids = ({c.id for c in m.categories} | {c.parent_id for c in m.categories if c.parent_id}) if m else set()
        jobs = []
        if ids:
            jobs = (
                JobRequest.query.filter(
                    JobRequest.status.in_(["new", "discussing"]),
                    JobRequest.invited_master_id.is_(None),
                    JobRequest.customer_id != u.id,
                    JobRequest.created_at > since,
                    JobRequest.category_id.in_(ids),
                )
                .order_by(JobRequest.id.desc())
                .limit(MAX_DIGEST_JOBS)
                .all()
            )
        if jobs:
            body = "\n\n".join(f"{_summary(j)}\n{site_url(f'/requests/{j.id}')}" for j in jobs)
            notify(u, f"Нові заявки у ваших категоріях: {len(jobs)}", "Що зʼявилось за останній час:\n\n" + body)
            sent += 1
        u.last_digest_at = now
    db.session.commit()
    return sent
