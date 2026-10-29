from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager

UNIT_LABELS = {
    "job": "за роботу",
    "hour": "за годину",
    "m2": "за м²",
    "from": "від",
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


REQUEST_STATUS = {
    "new": "Нова",
    "discussing": "В обговоренні",
    "in_progress": "В роботі",
    "done": "Виконана",
    "cancelled": "Скасована",
}
REVIEW_KINDS = {"praise": "Похвала", "complaint": "Скарга"}
REPORT_REASONS = {
    "insult": "Образи",
    "false": "Неправдива інформація",
    "spam": "Спам або реклама",
    "fraud": "Шахрайство",
    "other": "Інше",
}
REVIEW_EDIT_HOURS = 48
BADGE_MANY_JOBS = 5  # скільки виконаних робіт для бейджа «Багато виконаних робіт»


master_categories = db.Table(
    "master_categories",
    db.Column("master_id", db.ForeignKey("master_profiles.id"), primary_key=True),
    db.Column("category_id", db.ForeignKey("categories.id"), primary_key=True),
)


class User(UserMixin, db.Model):
    """Акаунт + особисті дані. Роль майстра — прапорець is_master."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)

    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    phone = db.Column(db.String(30))
    city = db.Column(db.String(80))
    district = db.Column(db.String(80))
    about = db.Column(db.Text)
    avatar = db.Column(db.String(100))

    is_master = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_blocked = db.Column(db.Boolean, default=False, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)   # особу підтверджено адміном
    email_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    notify_email = db.Column(db.Boolean, default=True, nullable=False)
    notify_new_requests = db.Column(db.String(10), default="instant", nullable=False)  # instant / daily / off
    last_digest_at = db.Column(db.DateTime)
    telegram_chat_id = db.Column(db.String(32), index=True)
    notify_telegram = db.Column(db.Boolean, default=True, nullable=False)
    telegram_link_code = db.Column(db.String(40), index=True)  # одноразовий код для /start
    telegram_link_at = db.Column(db.DateTime)

    # Приватність: all — усім, auth — лише зареєстрованим, hidden — нікому
    phone_visibility = db.Column(db.String(10), default="auth", nullable=False)
    last_name_visibility = db.Column(db.String(10), default="all", nullable=False)

    created_at = db.Column(db.DateTime, default=_now)

    master = db.relationship(
        "MasterProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    requests = db.relationship("JobRequest", back_populates="customer", cascade="all, delete")
    reviews_written = db.relationship(
        "Review", back_populates="author", foreign_keys="Review.author_id", cascade="all, delete"
    )
    reports = db.relationship("Report", back_populates="reporter", cascade="all, delete")
    conversations = db.relationship("Conversation", back_populates="customer", cascade="all, delete")
    favorites = db.relationship("Favorite", back_populates="user", cascade="all, delete")
    profile_reports_received = db.relationship(
        "ProfileReport", back_populates="user", foreign_keys="ProfileReport.user_id", cascade="all, delete"
    )
    profile_reports_made = db.relationship(
        "ProfileReport", back_populates="reporter", foreign_keys="ProfileReport.reporter_id",
        cascade="all, delete",
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def initials(self):
        return (self.first_name[:1] + self.last_name[:1]).upper()

    def public_name(self, viewer_authed):
        if self.last_name_visibility == "auth" and not viewer_authed:
            return f"{self.first_name} {self.last_name[:1]}."
        return f"{self.first_name} {self.last_name}"

    def has_dialog_with(self, other):
        """Чи писав `other` цьому користувачу (у будь-якому діалозі між ними)."""
        return (
            db.session.query(Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(MasterProfile, Conversation.master_id == MasterProfile.id)
            .filter(
                Message.sender_id == other.id,
                db.or_(
                    db.and_(Conversation.customer_id == self.id, MasterProfile.user_id == other.id),
                    db.and_(Conversation.customer_id == other.id, MasterProfile.user_id == self.id),
                ),
            )
            .first()
            is not None
        )

    def can_see_phone(self, viewer):
        """viewer — current_user (або AnonymousUser)."""
        if not self.phone:
            return False
        authed = getattr(viewer, "is_authenticated", False)
        if authed and viewer.id == self.id:
            return True
        if self.phone_visibility == "all":
            return True
        if self.phone_visibility == "auth":
            return authed
        if self.phone_visibility == "dialog":
            return authed and self.has_dialog_with(viewer)
        return False

    @property
    def location(self):
        return ", ".join(p for p in (self.city, self.district) if p)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    hint = db.Column(db.Text)  # підказка у формі заявки: що варто вказати

    children = db.relationship(
        "Category",
        backref=db.backref("parent", remote_side=[id]),
        order_by="Category.name",
    )


class MasterProfile(db.Model):
    """Резюме майстра."""

    __tablename__ = "master_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    headline = db.Column(db.String(120))          # «Майстер з ремонту квартир»
    description = db.Column(db.Text)
    experience_years = db.Column(db.Integer)
    schedule = db.Column(db.String(120))          # «Пн–Сб, 9:00–19:00»
    districts = db.Column(db.String(200))         # райони, де працює
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    user = db.relationship("User", back_populates="master")
    categories = db.relationship("Category", secondary=master_categories, lazy="selectin")
    services = db.relationship(
        "Service", back_populates="master", cascade="all, delete-orphan", order_by="Service.id"
    )
    photos = db.relationship(
        "PortfolioPhoto", back_populates="master", cascade="all, delete-orphan",
        order_by="PortfolioPhoto.id.desc()",
    )

    responses = db.relationship("JobResponse", back_populates="master", cascade="all, delete")
    conversations = db.relationship("Conversation", back_populates="master", cascade="all, delete")
    favorited_by = db.relationship("Favorite", back_populates="master", cascade="all, delete")
    invitations = db.relationship(
        "JobRequest", back_populates="invited_master", foreign_keys="JobRequest.invited_master_id"
    )
    jobs = db.relationship(
        "JobRequest", back_populates="chosen_master", foreign_keys="JobRequest.chosen_master_id"
    )
    reviews = db.relationship(
        "Review", back_populates="master", foreign_keys="Review.master_id", cascade="all, delete"
    )

    @property
    def min_price(self):
        prices = [s.price for s in self.services]
        return min(prices) if prices else None

    @property
    def public_reviews(self):
        rs = [r for r in self.reviews if not r.is_hidden]
        return sorted(rs, key=lambda r: r.created_at, reverse=True)

    @property
    def rating_count(self):
        return len(self.public_reviews)

    @property
    def rating_avg(self):
        rs = self.public_reviews
        return sum(r.rating for r in rs) / len(rs) if rs else None

    @property
    def rating_breakdown(self):
        counts = {i: 0 for i in range(5, 0, -1)}
        for r in self.public_reviews:
            counts[r.rating] += 1
        return counts

    @property
    def completed_jobs(self):
        return sum(1 for j in self.jobs if j.status == "done")

    @property
    def has_many_jobs_badge(self):
        return self.completed_jobs >= BADGE_MANY_JOBS


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(10), default="job", nullable=False)

    master = db.relationship("MasterProfile", back_populates="services")

    @property
    def unit_label(self):
        return UNIT_LABELS.get(self.unit, "")


class PortfolioPhoto(db.Model):
    __tablename__ = "portfolio_photos"

    id = db.Column(db.Integer, primary_key=True)
    master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"), nullable=False)
    filename = db.Column(db.String(100), nullable=False)
    caption = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=_now)

    master = db.relationship("MasterProfile", back_populates="photos")


class JobRequest(db.Model):
    """Заявка замовника. Статуси: new → discussing → in_progress → done / cancelled."""

    __tablename__ = "job_requests"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    district = db.Column(db.String(80))
    desired_date = db.Column(db.Date)
    budget = db.Column(db.Float)
    status = db.Column(db.String(12), default="new", nullable=False, index=True)
    chosen_master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"))
    invited_master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"))  # особиста заявка
    created_at = db.Column(db.DateTime, default=_now)
    completed_at = db.Column(db.DateTime)

    customer = db.relationship("User", back_populates="requests")
    category = db.relationship("Category")
    chosen_master = db.relationship(
        "MasterProfile", back_populates="jobs", foreign_keys=[chosen_master_id]
    )
    invited_master = db.relationship(
        "MasterProfile", back_populates="invitations", foreign_keys=[invited_master_id]
    )
    responses = db.relationship(
        "JobResponse", back_populates="request", cascade="all, delete", order_by="JobResponse.id"
    )
    photos = db.relationship(
        "RequestPhoto", back_populates="request", cascade="all, delete", order_by="RequestPhoto.id"
    )
    review = db.relationship("Review", back_populates="request", uselist=False, cascade="all, delete")
    conversations = db.relationship("Conversation", back_populates="job")

    @property
    def status_label(self):
        return REQUEST_STATUS.get(self.status, self.status)

    @property
    def is_open(self):
        return self.status in ("new", "discussing")

    @property
    def is_private(self):
        return self.invited_master_id is not None


class RequestPhoto(db.Model):
    __tablename__ = "request_photos"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("job_requests.id"), nullable=False)
    filename = db.Column(db.String(100), nullable=False)

    request = db.relationship("JobRequest", back_populates="photos")


class JobResponse(db.Model):
    """Відгук майстра на заявку (пропозиція з ціною). Один майстер — одна пропозиція."""

    __tablename__ = "job_responses"
    __table_args__ = (db.UniqueConstraint("request_id", "master_id"),)

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("job_requests.id"), nullable=False)
    master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"), nullable=False)
    price = db.Column(db.Float, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_now)

    request = db.relationship("JobRequest", back_populates="responses")
    master = db.relationship("MasterProfile", back_populates="responses")


class Review(db.Model):
    """Відгук замовника про майстра. Один відгук на одну виконану заявку."""

    __tablename__ = "reviews"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("job_requests.id"), unique=True, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(10), default="praise", nullable=False)  # praise / complaint
    text = db.Column(db.Text, nullable=False)
    photo = db.Column(db.String(100))
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)  # приховує модератор
    created_at = db.Column(db.DateTime, default=_now)
    updated_at = db.Column(db.DateTime)
    reply_text = db.Column(db.Text)  # одна публічна відповідь майстра
    reply_at = db.Column(db.DateTime)

    request = db.relationship("JobRequest", back_populates="review")
    author = db.relationship("User", back_populates="reviews_written", foreign_keys=[author_id])
    master = db.relationship("MasterProfile", back_populates="reviews", foreign_keys=[master_id])
    edits = db.relationship(
        "ReviewEdit", back_populates="review", cascade="all, delete", order_by="ReviewEdit.id"
    )
    reports = db.relationship("Report", back_populates="review", cascade="all, delete")

    @property
    def can_edit(self):
        return _now() - self.created_at < timedelta(hours=REVIEW_EDIT_HOURS)

    @property
    def kind_label(self):
        return REVIEW_KINDS.get(self.kind, "")


class ReviewEdit(db.Model):
    """Історія змін відгуку (бачить адміністратор)."""

    __tablename__ = "review_edits"

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id"), nullable=False)
    old_rating = db.Column(db.Integer, nullable=False)
    old_kind = db.Column(db.String(10), nullable=False)
    old_text = db.Column(db.Text, nullable=False)
    edited_at = db.Column(db.DateTime, default=_now)

    review = db.relationship("Review", back_populates="edits")


class Report(db.Model):
    """Скарга на відгук — потрапляє в чергу модерації."""

    __tablename__ = "reports"
    __table_args__ = (db.UniqueConstraint("review_id", "reporter_id"),)

    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("reviews.id"), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(10), nullable=False)
    comment = db.Column(db.String(500))
    status = db.Column(db.String(10), default="open", nullable=False)  # open / resolved
    created_at = db.Column(db.DateTime, default=_now)

    review = db.relationship("Review", back_populates="reports")
    reporter = db.relationship("User", back_populates="reports")

    @property
    def reason_label(self):
        return REPORT_REASONS.get(self.reason, self.reason)


class Conversation(db.Model):
    """Діалог замовник ↔ майстер (одна пара — один діалог)."""

    __tablename__ = "conversations"
    __table_args__ = (db.UniqueConstraint("customer_id", "master_id"),)

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"), nullable=False, index=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job_requests.id"))  # з якої заявки почалось
    created_at = db.Column(db.DateTime, default=_now)
    last_message_at = db.Column(db.DateTime, default=_now)

    customer = db.relationship("User", back_populates="conversations")
    master = db.relationship("MasterProfile", back_populates="conversations")
    job = db.relationship("JobRequest", back_populates="conversations")
    messages = db.relationship(
        "Message", back_populates="conversation", cascade="all, delete", order_by="Message.id"
    )

    def has(self, user):
        return user.id in (self.customer_id, self.master.user_id)

    def other(self, user):
        return self.master.user if user.id == self.customer_id else self.customer

    def unread_for(self, user):
        return sum(1 for m in self.messages if m.sender_id != user.id and m.read_at is None)


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    text = db.Column(db.Text)
    photo = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=_now)
    read_at = db.Column(db.DateTime)

    conversation = db.relationship("Conversation", back_populates="messages")
    sender = db.relationship("User")


class District(db.Model):
    """Довідник районів (підказки у формах; керується з адмін-панелі)."""

    __tablename__ = "districts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class ProfileReport(db.Model):
    """Скарга на профіль користувача."""

    __tablename__ = "profile_reports"
    __table_args__ = (db.UniqueConstraint("user_id", "reporter_id"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(10), nullable=False)
    comment = db.Column(db.String(500))
    status = db.Column(db.String(10), default="open", nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    user = db.relationship("User", back_populates="profile_reports_received", foreign_keys=[user_id])
    reporter = db.relationship("User", back_populates="profile_reports_made", foreign_keys=[reporter_id])

    @property
    def reason_label(self):
        return REPORT_REASONS.get(self.reason, self.reason)


class Favorite(db.Model):
    """Майстер в обраному у користувача."""

    __tablename__ = "favorites"
    __table_args__ = (db.UniqueConstraint("user_id", "master_id"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    master_id = db.Column(db.Integer, db.ForeignKey("master_profiles.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    user = db.relationship("User", back_populates="favorites")
    master = db.relationship("MasterProfile", back_populates="favorited_by")


class Meta(db.Model):
    """Службові значення (наприклад, версія початкових даних)."""

    __tablename__ = "meta"

    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.String(200), nullable=False)
