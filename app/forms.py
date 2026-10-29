from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField, FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import (
    DataRequired, Email, EqualTo, Length, NumberRange, Optional, ValidationError,
)

from .models import UNIT_LABELS, User

IMAGES = ["jpg", "jpeg", "png", "webp"]
PHONE_VIS = [
    ("all", "Усім"),
    ("auth", "Лише зареєстрованим"),
    ("dialog", "Після того, як мені напишуть"),
    ("hidden", "Нікому"),
]
NAME_VIS = [("all", "Повне прізвище всім"), ("auth", "Гостям — лише перша літера")]


class RegisterForm(FlaskForm):
    first_name = StringField("Ім'я", validators=[DataRequired("Вкажіть ім'я"), Length(max=60)])
    last_name = StringField("Прізвище", validators=[DataRequired("Вкажіть прізвище"), Length(max=60)])
    email = StringField(
        "Email", validators=[DataRequired("Вкажіть email"), Email("Некоректний email"), Length(max=120)]
    )
    password = PasswordField(
        "Пароль", validators=[DataRequired("Вкажіть пароль"), Length(min=8, message="Мінімум 8 символів")]
    )
    password2 = PasswordField(
        "Повторіть пароль", validators=[DataRequired(), EqualTo("password", "Паролі не збігаються")]
    )
    is_master = BooleanField("Я майстер і хочу пропонувати послуги")

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower().strip()).first():
            raise ValidationError("Цей email уже зареєстровано")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired("Вкажіть email")])
    password = PasswordField("Пароль", validators=[DataRequired("Вкажіть пароль")])
    remember = BooleanField("Запам'ятати мене")


class ProfileForm(FlaskForm):
    first_name = StringField("Ім'я", validators=[DataRequired("Вкажіть ім'я"), Length(max=60)])
    last_name = StringField("Прізвище", validators=[DataRequired("Вкажіть прізвище"), Length(max=60)])
    phone = StringField("Телефон", validators=[Optional(), Length(max=30)])
    city = StringField("Місто", validators=[Optional(), Length(max=80)])
    district = StringField("Район", validators=[Optional(), Length(max=80)])
    about = TextAreaField("Про себе", validators=[Optional(), Length(max=1000)])
    phone_visibility = SelectField("Хто бачить мій телефон", choices=PHONE_VIS)
    last_name_visibility = SelectField("Як показувати прізвище", choices=NAME_VIS)
    notify_email = BooleanField("Отримувати сповіщення на email (повідомлення, відгуки, пропозиції)")


class AvatarForm(FlaskForm):
    avatar = FileField(
        "Фото профілю",
        validators=[FileRequired("Оберіть файл"), FileAllowed(IMAGES, "Дозволені формати: JPG, PNG, WEBP")],
    )


class MasterForm(FlaskForm):
    headline = StringField("Заголовок резюме", validators=[Optional(), Length(max=120)])
    description = TextAreaField("Опис і досвід", validators=[Optional(), Length(max=3000)])
    experience_years = IntegerField(
        "Досвід, років", validators=[Optional(), NumberRange(0, 70, "Від 0 до 70")]
    )
    schedule = StringField("Графік роботи", validators=[Optional(), Length(max=120)])
    districts = StringField("Райони, де працюєте", validators=[Optional(), Length(max=200)])
    categories = SelectMultipleField("Категорії", coerce=int)
    notify_new_requests = SelectField(
        "Сповіщення про нові заявки",
        choices=[("instant", "Одразу на email"), ("daily", "Раз на день (дайджест)"), ("off", "Не надсилати")],
    )
    is_published = BooleanField("Показувати резюме в каталозі")


class ServiceForm(FlaskForm):
    title = StringField("Послуга", validators=[DataRequired("Вкажіть назву послуги"), Length(max=120)])
    price = FloatField("Ціна", validators=[DataRequired("Вкажіть ціну"), NumberRange(0, 1_000_000)])
    unit = SelectField("Тип ціни", choices=list(UNIT_LABELS.items()))


class PhotoForm(FlaskForm):
    photo = FileField(
        "Фото роботи",
        validators=[FileRequired("Оберіть файл"), FileAllowed(IMAGES, "Дозволені формати: JPG, PNG, WEBP")],
    )
    caption = StringField("Підпис", validators=[Optional(), Length(max=150)])


class DeleteAccountForm(FlaskForm):
    password = PasswordField("Пароль для підтвердження", validators=[DataRequired("Вкажіть пароль")])


# --------------------------------------------------------------------------
# MVP-2: заявки, відгуки, скарги
# --------------------------------------------------------------------------

from datetime import date  # noqa: E402

from flask_wtf.file import MultipleFileField  # noqa: E402
from wtforms import DateField, RadioField  # noqa: E402

from .models import REPORT_REASONS, REVIEW_KINDS  # noqa: E402
from .utils import check_clean, check_public_text  # noqa: E402


def clean_text(form, field):
    msg = check_clean(field.data or "")
    if msg:
        raise ValidationError(msg)


def public_text(form, field):
    msg = check_public_text(field.data or "")
    if msg:
        raise ValidationError(msg)


class RequestForm(FlaskForm):
    category_id = SelectField("Категорія", coerce=int)
    title = StringField(
        "Що потрібно зробити",
        validators=[DataRequired("Вкажіть заголовок"), Length(5, 120, "Від 5 до 120 символів"), clean_text],
    )
    description = TextAreaField(
        "Опис",
        validators=[DataRequired("Опишіть завдання"), Length(10, 3000, "Від 10 до 3000 символів"), clean_text],
    )
    district = StringField("Район", validators=[Optional(), Length(max=80)])
    desired_date = DateField("Бажана дата", validators=[Optional()])
    budget = FloatField("Бюджет", validators=[Optional(), NumberRange(0, 1_000_000)])
    photos = MultipleFileField("Фото (до 5)", validators=[FileAllowed(IMAGES, "Дозволені формати: JPG, PNG, WEBP")])

    def validate_desired_date(self, field):
        if field.data and field.data < date.today():
            raise ValidationError("Дата не може бути в минулому")


class ResponseForm(FlaskForm):
    price = FloatField("Ваша ціна", validators=[DataRequired("Вкажіть ціну"), NumberRange(0, 1_000_000)])
    comment = TextAreaField("Коментар", validators=[Optional(), Length(max=1000), clean_text])


class ReviewForm(FlaskForm):
    rating = RadioField(
        "Оцінка",
        coerce=int,
        choices=[(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")],
        validators=[DataRequired("Оберіть оцінку")],
    )
    kind = RadioField(
        "Тип відгуку",
        choices=list(REVIEW_KINDS.items()),
        default="praise",
        validators=[DataRequired("Оберіть тип відгуку")],
    )
    text = TextAreaField(
        "Ваш відгук",
        validators=[DataRequired("Напишіть відгук"), Length(10, 2000, "Від 10 до 2000 символів"), public_text],
    )
    photo = FileField("Фото (необов'язково)", validators=[FileAllowed(IMAGES, "Дозволені формати: JPG, PNG, WEBP")])

    def validate_kind(self, field):
        rating = self.rating.data
        if rating is None:
            return
        if field.data == "praise" and rating < 3:
            raise ValidationError("Для похвали оцінка має бути від 3 до 5")
        if field.data == "complaint" and rating > 3:
            raise ValidationError("Для скарги оцінка має бути від 1 до 3")


class ReplyForm(FlaskForm):
    text = TextAreaField(
        "Ваша відповідь",
        validators=[DataRequired("Напишіть відповідь"), Length(5, 1000, "Від 5 до 1000 символів"), public_text],
    )


class ReportForm(FlaskForm):
    reason = SelectField("Причина", choices=list(REPORT_REASONS.items()))
    comment = TextAreaField("Пояснення (необов'язково)", validators=[Optional(), Length(max=500)])


# --------------------------------------------------------------------------
# MVP-3: відновлення пароля
# --------------------------------------------------------------------------

class ForgotForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired("Вкажіть email")])


class ResetForm(FlaskForm):
    password = PasswordField(
        "Новий пароль", validators=[DataRequired("Вкажіть пароль"), Length(min=8, message="Мінімум 8 символів")]
    )
    password2 = PasswordField(
        "Повторіть пароль", validators=[DataRequired(), EqualTo("password", "Паролі не збігаються")]
    )


class ChangePasswordForm(ResetForm):
    current_password = PasswordField("Поточний пароль", validators=[DataRequired("Вкажіть поточний пароль")])
