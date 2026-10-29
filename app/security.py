import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required

_hits = defaultdict(deque)  # у пам'яті процесу; для кількох серверів потрібен Redis


def confirmed_required(view):
    """Вхід + підтверджений email (якщо це вимагається конфігурацією)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_app.config["REQUIRE_EMAIL_CONFIRMATION"] and not current_user.email_confirmed:
            flash("Підтвердіть email, щоб користуватись цією функцією. Лист ми вже надсилали.", "error")
            return redirect(url_for("account.profile"))
        return view(*args, **kwargs)

    return login_required(wrapper)


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(404)
        return view(*args, **kwargs)

    return login_required(wrapper)


def rate_limit(name, limit, seconds):
    """Обмежує кількість POST-запитів: не більше `limit` за `seconds` секунд."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if request.method == "POST" and current_app.config["RATELIMIT_ENABLED"]:
                ident = current_user.get_id() if current_user.is_authenticated else request.remote_addr
                hits, now = _hits[(name, ident)], time.monotonic()
                while hits and now - hits[0] > seconds:
                    hits.popleft()
                if len(hits) >= limit:
                    abort(429)
                hits.append(now)
            return view(*args, **kwargs)

        return wrapper

    return decorator
