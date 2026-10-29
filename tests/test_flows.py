"""Наскрізні перевірки сайту. Запуск з папки проєкту:  python tests/test_flows.py"""
import io, json, os, re, sqlite3, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

import config

tmp = tempfile.mkdtemp()
config.Config.SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(tmp, "t.db")
config.Config.UPLOAD_FOLDER = os.path.join(tmp, "up")

from app import create_app, db
from app.models import Category, Conversation, Favorite, JobRequest, Message, Report, Review, User

app = create_app({"WTF_CSRF_ENABLED": False, "TESTING": True, "RATELIMIT_ENABLED": False})


def img():
    b = io.BytesIO(); Image.new("RGB", (700, 500), "navy").save(b, "PNG"); b.seek(0); return b


def ok(r, code=(200, 302), msg=""):
    assert r.status_code in code, (msg, r.status_code, r.get_data(as_text=True)[:600]); return r


def text(r): return r.get_data(as_text=True)


def reg(c, first, email, master=False):
    d = dict(first_name=first, last_name="Тест", email=email, password="password1", password2="password1")
    if master: d["is_master"] = "y"
    ok(c.post("/register", data=d))


def mails(to=None, subj=None):
    return [m for m in app.extensions.get("outbox", []) if (not to or m["to"] == to) and (not subj or subj in m["subject"])]


def user_id(email):
    with app.app_context(): return User.query.filter_by(email=email).one().id


def master_id(email):
    with app.app_context(): return User.query.filter_by(email=email).one().master.id


# =====================================================================================
# Частина 1. Основні сценарії (кабінет, заявки, відгуки, чат, адмінка)
# =====================================================================================
cc, mc, oc, ac, anon = (app.test_client() for _ in range(5))
reg(cc, "Олена", "c@x.com"); reg(mc, "Максим", "m@x.com", True); reg(oc, "Інна", "o@x.com"); reg(ac, "Адмін", "a@x.com")
with app.app_context():
    tile = Category.query.filter_by(name="Плитка").one().id
    User.query.filter_by(email="a@x.com").one().is_admin = True; db.session.commit()

ok(mc.post("/account/avatar", data={"avatar": (img(), "a.png")}, content_type="multipart/form-data"))
ok(mc.post("/account/avatar", data={"avatar": (io.BytesIO(b"not an image"), "a.png")}, content_type="multipart/form-data"))
ok(mc.post("/account/profile", data=dict(first_name="Максим", last_name="Тест", phone="+34 611 222 333",
   phone_visibility="dialog", last_name_visibility="auth", notify_email="y")))
ok(mc.post("/account/master", data=dict(headline="Плиточник", experience_years="5", categories=[str(tile)],
   is_published="y", notify_new_requests="instant")))
ok(mc.post("/account/master/services", data=dict(title="Плитка", price="20", unit="hour")))
ok(mc.post("/account/master/photos", data={"photo": (img(), "w.png"), "caption": "Ванна"}, content_type="multipart/form-data"))
mid = master_id("m@x.com")
assert "Максим Т." in text(ok(anon.get("/masters"))), "приватність прізвища"
assert "+34 611" not in text(ok(anon.get(f"/masters/{mid}")))

# заявка → пропозиція → вибір → виконання → відгук
ok(cc.post("/requests/new", data=dict(category_id=str(tile), title="Плитка у ванній", description="Покласти плитку 6 м2",
   photos=[(img(), "a.png")]), content_type="multipart/form-data"))
ok(oc.get("/requests/1"), (404,)); ok(mc.get("/requests/1"))
ok(mc.post("/requests/1/respond", data=dict(price="280")))
with app.app_context(): rid = db.session.get(JobRequest, 1).responses[0].id
ok(cc.post(f"/requests/1/choose/{rid}")); ok(cc.get("/requests/1/review"), (302,))
ok(cc.post("/requests/1/complete"))
for bad in (dict(text="Дзвоніть +34 600 111 222 швидко"), dict(text="Дивіться https://x.com тут"),
            dict(text="Це повний мудак, жах просто"), dict(rating="5", kind="complaint")):
    d = dict(rating="5", kind="praise", text="Чудова робота, усе вчасно і якісно"); d.update(bad)
    ok(cc.post("/requests/1/review", data=d), (200,))
ok(cc.post("/requests/1/review", data=dict(rating="4", kind="praise", text="Добре, але трохи затягнули")))
ok(cc.post("/requests/1/review", data=dict(rating="4", kind="praise", text="Повторний відгук неможливий")), (302,))
with app.app_context(): assert Review.query.count() == 1
ok(mc.post("/reviews/1/reply", data=dict(text="Дякую за довіру!")))
ok(mc.post("/reviews/1/reply", data=dict(text="Друга відповідь")))
ok(oc.post("/reviews/1/report", data=dict(reason="false", comment="неправда")))
ok(cc.post("/reviews/1/edit", data=dict(rating="5", kind="praise", text="Усе чудово, дякую майстру")))
t = text(ok(anon.get(f"/masters/{mid}")))
assert "Дякую за довіру" in t and "5.0" in t and "Поскаржитись" not in t

# чат і телефон «після діалогу»
thread = ok(cc.get(f"/messages/start/{mid}")).headers["Location"]
ok(cc.post(thread, data=dict(text="Доброго дня!", photo=(img(), "p.png")), content_type="multipart/form-data"))
assert "+34 611 222 333" in text(ok(cc.get(f"/masters/{mid}")))
ok(oc.get(thread), (404,))
ok(mc.post(thread, data=dict(text="Вітаю!")))
assert [d["text"] for d in json.loads(text(ok(cc.get(thread + "/poll?after=0"))))] == ["Вітаю!"]

# адмін: скарги, приховування, блокування
for p in ("/admin/", "/admin/users", "/admin/reports", "/admin/categories", "/admin/districts"):
    ok(cc.get(p), (404,)); ok(ac.get(p), (200,), p)
assert "Усе чудово" in text(ok(ac.get("/admin/reports")))
ok(ac.post("/admin/reviews/1/hide"))
assert "Відгуків ще немає" in text(ok(anon.get(f"/masters/{mid}")))
ok(ac.post("/admin/reviews/1/restore"))
ok(ac.post(f"/admin/users/{user_id('m@x.com')}/verify"))
assert "✓ Підтверджено" in text(ok(anon.get("/masters")))

# відновлення пароля
ok(anon.post("/forgot", data=dict(email="o@x.com")))
rl = re.search(r"/reset/\S+", mails("o@x.com", "Відновлення")[-1]["body"]).group(0)
ok(anon.post(rl, data=dict(password="newpassword9", password2="newpassword9"))); ok(anon.get(rl), (302,))
ok(app.test_client().post("/login", data=dict(email="o@x.com", password="newpassword9")))

# =====================================================================================
# Частина 2. MVP-4A: сповіщення, запрошення, підказки, обране, «замовити ще раз»
# =====================================================================================
names = ["m1", "m2", "m3", "m4"]
cl = {n: app.test_client() for n in names}
for n in names: reg(cl[n], n.upper(), f"{n}@x.com", True)
mid = {}
for n, cat, mode in [("m1", tile, "instant"), ("m2", tile, "daily"),
                     ("m3", None, "instant"), ("m4", tile, "off")]:
    if n == "m3":
        with app.app_context(): cat = Category.query.filter_by(name="Стрижка газону").one().id
    ok(cl[n].post("/account/master", data=dict(headline=n, categories=[str(cat)], is_published="y", notify_new_requests=mode)))
    mid[n] = master_id(f"{n}@x.com")
    with app.app_context(): assert User.query.filter_by(email=f"{n}@x.com").one().notify_new_requests == mode
assert 'selected value="daily"' in text(ok(cl["m2"].get("/account/master")))

t = text(ok(cc.get("/requests/new")))
hints = json.loads(re.search(r"var hints = (\{.*?\});", t, re.S).group(1))
assert "Вкажіть площу в м²" in hints[str(tile)] and 'id="cat-hint"' in t

n_before = len(mails("m1@x.com", "Нова заявка"))
ok(cc.post("/requests/new", data=dict(category_id=str(tile), title="Нова плитка", description="Потрібно покласти плитку")))
assert len(mails("m1@x.com", "Нова заявка")) == n_before + 1
for who in ("m2@x.com", "m3@x.com", "m4@x.com", "c@x.com"): assert not mails(who, "Нова заявка"), who

r = app.test_cli_runner().invoke(args=["send-digest"]); assert "1" in r.output, r.output
assert len(mails("m2@x.com", "Нові заявки")) == 1 and not mails("m1@x.com", "Нові заявки")
app.test_cli_runner().invoke(args=["send-digest"]); assert len(mails("m2@x.com", "Нові заявки")) == 1

assert "Особиста заявка для майстра" in text(ok(cc.get(f"/requests/new?master={mid['m3']}")))
ok(cc.post(f"/requests/new?master={mid['m3']}", data=dict(category_id=str(tile), title="Особисто для M3", description="Потрібна консультація з плитки")))
with app.app_context():
    j = JobRequest.query.filter_by(title="Особисто для M3").one(); jid = j.id; assert j.is_private
assert mails("m3@x.com", "Вас запросили")
feed = text(ok(cl["m3"].get("/requests/"))); assert "Особисто для M3" in feed and "Запрошення для вас" in feed
assert "Особисто для M3" not in text(ok(cl["m1"].get("/requests/?all=1")))
ok(cl["m1"].get(f"/requests/{jid}"), (404,)); ok(cl["m1"].post(f"/requests/{jid}/respond", data=dict(price="5")), (404,))
ok(cl["m1"].post(f"/requests/{jid}/decline"), (404,))
assert "Відхилити запрошення" in text(ok(cl["m3"].get(f"/requests/{jid}")))
ok(cl["m3"].post(f"/requests/new?master={mid['m3']}", data=dict(category_id=str(tile), title="Сам собі", description="Заявка сам собі тут")))
with app.app_context(): assert not JobRequest.query.filter_by(title="Сам собі").one().is_private
n1 = len(mails("m1@x.com", "Нова заявка"))
ok(cl["m3"].post(f"/requests/{jid}/decline"))
with app.app_context(): assert not db.session.get(JobRequest, jid).is_private
assert mails("c@x.com", "відхилив") and len(mails("m1@x.com", "Нова заявка")) == n1 + 1
ok(cl["m1"].get(f"/requests/{jid}"))

# «замовити ще раз»: заявка №1 уже виконана
t = text(ok(cc.get("/requests/1"))); assert "Замовити ще раз" in t and "у цього майстра" in t
t = text(ok(cc.get("/requests/new?copy=1"))); assert "Плитка у ванній" in t and "Покласти плитку 6 м2" in t
assert "Особиста заявка для майстра" in text(ok(cc.get(f"/requests/new?copy=1&master={mid['m1']}")))
assert "Плитка у ванній" not in text(ok(cl["m2"].get("/requests/new?copy=1")))

# обране
ok(anon.post(f"/masters/{mid['m1']}/favorite"), (302,)); ok(cl["m1"].post(f"/masters/{mid['m1']}/favorite"), (404,))
ok(cc.post(f"/masters/{mid['m1']}/favorite")); ok(cc.post(f"/masters/{mid['m2']}/favorite"))
assert "★ В обраному" in text(ok(cc.get(f"/masters/{mid['m1']}")))
ok(ac.post(f"/admin/users/{user_id('m2@x.com')}/block"))
t = text(ok(cc.get("/account/favorites"))); assert "M2 Тест" not in t and "M1 Тест" in t
ok(cc.post(f"/masters/{mid['m1']}/favorite"))
with app.app_context(): assert Favorite.query.filter_by(master_id=mid["m1"]).count() == 0

# адмін змінює підказку
ok(ac.post(f"/admin/categories/{tile}/rename", data=dict(name="Плитка", hint="New tile hint")))
assert "New tile hint" in text(ok(cc.get("/requests/new")))

# видалення акаунтів: каскади й файли
ok(cc.post(f"/masters/{mid['m1']}/favorite"))
ok(cl["m1"].post("/account/delete", data=dict(password="password1")))
with app.app_context(): assert Favorite.query.filter_by(master_id=mid["m1"]).count() == 0
ok(cc.post("/account/delete", data=dict(password="password1")))
with app.app_context():
    assert Conversation.query.count() == 0 and Message.query.count() == 0 and Report.query.count() == 0
up = os.path.join(tmp, "up")
for sub in ("messages", "requests", "reviews"): assert not os.listdir(os.path.join(up, sub)), sub

# =====================================================================================
# Частина 3. Дизайн: світла тема за замовчуванням, хедер, категорії, ілюстрації
# =====================================================================================
from app.scenes import SCENE_BY_CATEGORY
from app.seed import CATEGORIES, seed_defaults

html = text(ok(anon.get("/")))
assert 'data-theme="light"' in html and 'id="theme-toggle"' in html and "ui.js" in html
assert 'class="wrap bar"' not in html and "topbar-inner" in html, "клас хедера не збігається з .bar рейтингу"
css = text(ok(anon.get("/static/style.css")))
assert "prefers-color-scheme" not in css, "тема не повинна залежати від системної"
assert '[data-theme="dark"]' in css and ".topbar-inner" in css
parents = re.findall(r'<li class="cat[^"]*" data-scene="(\w+)" data-id="(\d+)"', html)
assert len(parents) == len(CATEGORIES) == 11, parents
scenes = set(re.findall(r'<svg class="scene" data-scene="(\w+)"', html))
assert scenes >= set(SCENE_BY_CATEGORY.values()) | {"default"}, scenes
assert all(k in scenes for k, _ in parents), "кожна категорія має ілюстрацію"
assert set(SCENE_BY_CATEGORY) == set(CATEGORIES), "кожній головній категорії відповідає сцена"
with app.app_context():
    cat = Category.query.filter_by(name="Ремонт техніки", parent_id=None).one()
    assert {c.name for c in cat.children} >= {"Пральні машини", "Холодильники"}
    assert Category.query.filter_by(parent_id=None).count() == 11 and Category.query.count() == 59
    # одноразовий сид: видалена адміном категорія не повертається після перезапуску
    victim = Category.query.filter_by(name="Вивіз сміття").one()
    db.session.delete(victim); db.session.commit()
    seed_defaults()
    assert Category.query.filter_by(name="Вивіз сміття").count() == 0

# оновлення старої бази (схема MVP-3)
old = os.path.join(tmp, "old.db")
con = sqlite3.connect(old)
con.execute("CREATE TABLE categories (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL, parent_id INTEGER)")
con.execute("INSERT INTO categories (id,name) VALUES (1,'Стара категорія')")
con.execute("CREATE TABLE job_requests (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, category_id INTEGER NOT NULL, title VARCHAR(120) NOT NULL, description TEXT NOT NULL, status VARCHAR(12) NOT NULL, created_at DATETIME)")
con.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(120) NOT NULL, password_hash VARCHAR(256) NOT NULL,
 first_name VARCHAR(60) NOT NULL, last_name VARCHAR(60) NOT NULL, phone VARCHAR(30), city VARCHAR(80), district VARCHAR(80),
 about TEXT, avatar VARCHAR(100), is_master BOOLEAN NOT NULL, is_admin BOOLEAN NOT NULL, phone_visibility VARCHAR(10) NOT NULL,
 last_name_visibility VARCHAR(10) NOT NULL, created_at DATETIME)""")
con.execute("INSERT INTO users (id,email,password_hash,first_name,last_name,is_master,is_admin,phone_visibility,last_name_visibility) VALUES (1,'old@x.com','x','Старий','Юзер',0,0,'auth','all')")
con.commit(); con.close()
config.Config.SQLALCHEMY_DATABASE_URI = "sqlite:///" + old
app2 = create_app({"TESTING": True})
with app2.app_context():
    cols = lambda t: {r[1] for r in db.session.execute(db.text(f"PRAGMA table_info({t})"))}
    assert "invited_master_id" in cols("job_requests") and "hint" in cols("categories")
    assert {"notify_new_requests", "email_confirmed", "is_blocked"} <= cols("users")
    u = User.query.filter_by(email="old@x.com").one()
    assert u.email_confirmed and u.notify_new_requests == "instant"
    assert Category.query.filter_by(name="Стара категорія").one().hint is None
    assert Category.query.filter_by(name="Ремонт техніки").count() == 1, "нові категорії додано до старої бази"
print("ALL FLOWS OK")
