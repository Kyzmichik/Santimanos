"""Сторінки для пошукових систем: категорії, міста, їх поєднання, sitemap.xml і robots.txt.

Адреси людинозрозумілі: /services/12-plytka, /city/madrid, /services/12-plytka/madrid.
Число в адресі категорії — її id, тож перейменування в адмінці не ламає посилання
(стара адреса перенаправляє на нову з кодом 301).
"""
import re
import unicodedata
from collections import Counter, defaultdict

from flask import Blueprint, Response, abort, current_app, g, redirect, render_template, request, url_for

from . import db
from .catalog import _visible_masters, latest_reviews, main_categories, ranked
from .models import Category, MasterProfile, Service, User

bp = Blueprint("seo", __name__)

PER_PAGE = 12

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh",
    "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "'": "", "ʼ": "", "’": "",
    "ы": "y", "э": "e", "ё": "io", "ъ": "",
}


def slugify(text):
    """«Комп'ютери і мережі» → «kompiutery-i-merezhi», «Málaga» → «malaga»."""
    s = "".join(_TRANSLIT.get(ch, ch) for ch in (text or "").lower())
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "c"


def category_ids(cat):
    return [cat.id] + [c.id for c in cat.children]


def category_url(cat, city_slug=None, **kw):
    if city_slug:
        return url_for("seo.category_city", cat_id=cat.id, slug=slugify(cat.name), city_slug=city_slug, **kw)
    return url_for("seo.category", cat_id=cat.id, slug=slugify(cat.name), **kw)


def city_url(city, **kw):
    return url_for("seo.city", city_slug=city["slug"], **kw)


def cities(query=None):
    """Міста, де є видимі майстри: {slug: {slug, name, names, count}}.

    Місто користувач вводить вручну, тому «Мадрид», «мадрид » і «МАДРИД» групуються за slug,
    а назвою стає найчастіший варіант написання.
    """
    if query is None and "seo_cities" in g:
        return g.seo_cities
    base = _visible_masters() if query is None else query
    rows = base.filter(User.city.isnot(None)).with_entities(User.city).all()
    spellings = defaultdict(Counter)
    for (raw,) in rows:
        name = raw.strip()
        if name:
            spellings[slugify(name)][name] += 1
    result = {}
    for slug, counter in spellings.items():
        result[slug] = {
            "slug": slug,
            "name": counter.most_common(1)[0][0],
            # точні значення з БД — для фільтра User.city.in_(...)
            "names": sorted({raw for (raw,) in rows if raw.strip() in counter}),
            "count": sum(counter.values()),
        }
    result = dict(sorted(result.items(), key=lambda kv: (-kv[1]["count"], kv[1]["name"])))
    if query is None:
        g.seo_cities = result
    return result


def category_counts(query):
    """Скільки видимих майстрів у кожній категорії (головна категорія враховує підкатегорії)."""
    rows = query.join(MasterProfile.categories).with_entities(
        Category.id, Category.parent_id, MasterProfile.id
    )
    masters = defaultdict(set)
    for cid, pid, mid in rows:
        masters[cid].add(mid)
        if pid:
            masters[pid].add(mid)
    return {cid: len(ids) for cid, ids in masters.items()}


def _min_price(query):
    ids = query.with_entities(MasterProfile.id).scalar_subquery()
    return db.session.query(db.func.min(Service.price)).filter(Service.master_id.in_(ids)).scalar()


def _page():
    return max(request.args.get("page", 1, type=int), 1)


# --------------------------------------------------------------------------
# Сторінки
# --------------------------------------------------------------------------

@bp.route("/services")
def services():
    counts = category_counts(_visible_masters())
    return render_template("seo/services.html", parents=main_categories(), counts=counts, city_list=cities())


@bp.route("/services/<int:cat_id>-<slug>")
def category(cat_id, slug):
    return _category_page(cat_id, slug)


@bp.route("/services/<int:cat_id>-<slug>/<city_slug>")
def category_city(cat_id, slug, city_slug):
    return _category_page(cat_id, slug, city_slug)


def _category_page(cat_id, slug, city_slug=None):
    cat = db.get_or_404(Category, cat_id)
    if slug != slugify(cat.name):
        return redirect(category_url(cat, city_slug), 301)
    city = None
    if city_slug:
        city = cities().get(city_slug)
        if not city:
            abort(404)

    ids = category_ids(cat)
    in_category = _visible_masters().filter(MasterProfile.categories.any(Category.id.in_(ids)))
    query = in_category.filter(User.city.in_(city["names"])) if city else in_category
    pagination = ranked(query).paginate(page=_page(), per_page=PER_PAGE, error_out=False)
    siblings = cat.parent.children if cat.parent else cat.children
    return render_template(
        "seo/category.html",
        cat=cat,
        city=city,
        pagination=pagination,
        siblings=sorted(siblings, key=lambda c: c.id),
        counts=category_counts(query),
        city_list=list(cities(in_category).values())[:20],
        min_price=_min_price(query),
        reviews=latest_reviews(3, ids, city["names"] if city else None),
    )


@bp.route("/city/<city_slug>")
def city(city_slug):
    c = cities().get(city_slug)
    if not c:
        abort(404)
    query = _visible_masters().filter(User.city.in_(c["names"]))
    pagination = ranked(query).paginate(page=_page(), per_page=PER_PAGE, error_out=False)
    return render_template(
        "seo/city.html",
        city=c,
        pagination=pagination,
        parents=main_categories(),
        counts=category_counts(query),
        reviews=latest_reviews(3, city_names=c["names"]),
    )


# --------------------------------------------------------------------------
# Для роботів
# --------------------------------------------------------------------------

def _abs(path):
    return current_app.config["SITE_URL"].rstrip("/") + path


@bp.route("/sitemap.xml")
def sitemap():
    """Лише сторінки, де є майстри: порожні сторінки шкодять індексації."""
    paths = [url_for("catalog.index"), url_for("catalog.masters"), url_for("seo.services")]
    all_categories = Category.query.order_by(Category.id).all()
    counts = category_counts(_visible_masters())
    paths += [category_url(c) for c in all_categories if counts.get(c.id)]
    for c in cities().values():
        paths.append(city_url(c))
        in_city = category_counts(_visible_masters().filter(User.city.in_(c["names"])))
        paths += [category_url(cat, c["slug"]) for cat in all_categories if in_city.get(cat.id)]
    paths += [
        url_for("catalog.master_detail", master_id=mid)
        for (mid,) in _visible_masters().with_entities(MasterProfile.id).order_by(MasterProfile.id)
    ]
    xml = render_template("seo/sitemap.xml", urls=[_abs(p) for p in paths])
    return Response(xml, mimetype="application/xml")


ROBOTS_DISALLOW = (
    "/account", "/admin", "/messages", "/requests", "/reviews", "/login", "/register",
    "/forgot", "/reset", "/confirm", "/telegram",
)


@bp.route("/robots.txt")
def robots():
    lines = ["User-agent: *"] + [f"Disallow: {p}" for p in ROBOTS_DISALLOW]
    lines += ["", f"Sitemap: {_abs(url_for('seo.sitemap'))}", ""]
    return Response("\n".join(lines), mimetype="text/plain")
