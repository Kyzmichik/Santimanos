import os
import re
import uuid

from flask import current_app
from PIL import Image, ImageOps


def save_image(file_storage, subfolder, max_side, square=False):
    """Перевіряє, зменшує й перезбережає зображення як JPEG.

    Перекодування прибирає з файлу все зайве (EXIF, вбудовані дані).
    Повертає ім'я файлу або None, якщо це не коректне зображення.
    """
    try:
        img = Image.open(file_storage.stream)
        img.load()
    except Exception:
        return None
    if img.format not in ("JPEG", "PNG", "WEBP"):
        return None

    img = ImageOps.exif_transpose(img).convert("RGB")
    if square:
        img = ImageOps.fit(img, (max_side, max_side), Image.LANCZOS)  # обрізання по центру
    else:
        img.thumbnail((max_side, max_side), Image.LANCZOS)

    name = uuid.uuid4().hex + ".jpg"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)
    img.save(os.path.join(folder, name), "JPEG", quality=85, optimize=True)
    return name


def delete_image(subfolder, filename):
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder, filename)
    if os.path.isfile(path):
        os.remove(path)


# --------------------------------------------------------------------------
# Перевірка текстів
# --------------------------------------------------------------------------

PHONE_RE = re.compile(r"(?:\d[\s\-().]*){7,}")
LINK_RE = re.compile(
    r"(https?://|www\.|t\.me|[\w-]+\.(?:com|net|org|ua|es|eu|info|me|io|ru|pl)\b|@\w{3,})", re.I
)
# Основи нецензурних слів (мінімальний список — розширюйте за потреби).
BAD_RE = re.compile(
    r"\b(хуй|хуя|хуї|хує|пізд|пизд|єба|їба|ебан|бляд|блят|сука|суки|мудак|підор|пидор|гандон)", re.I
)


def check_clean(text):
    """Повертає текст помилки, якщо у тексті є нецензурна лексика."""
    if BAD_RE.search(text or ""):
        return "Текст містить нецензурну лексику. Сформулюйте інакше."
    return None


def check_public_text(text):
    """Для відгуків і відповідей: без нецензурної лексики, телефонів і посилань."""
    msg = check_clean(text)
    if msg:
        return msg
    if PHONE_RE.search(text or ""):
        return "Не вказуйте номери телефонів у тексті."
    if LINK_RE.search(text or ""):
        return "Не додавайте посилання, email або імена акаунтів у тексті."
    return None
