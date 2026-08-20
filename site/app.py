from typing import LiteralString

from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
import sqlite3 as sq
from functools import wraps
from contextlib import closing
from datetime import timedelta
import json, random, os
from markupsafe import Markup
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR: LiteralString = os.path.dirname(BASE_DIR)
sys.path.insert(0, MAIN_DIR)
from bot_core import demo_reply

app = Flask(__name__)
app.secret_key = "02002020002henglish_t9290Roll"
app.permanent_session_lifetime = timedelta(days=30)



API_JSON = os.path.join(MAIN_DIR, "api.json")
with open(API_JSON, "r") as js:
    data = json.load(js)
ADMINS = data["ADMIN_PANEL"]
DB_PODS  = os.path.join(BASE_DIR, f"{data['DB2']}")
DB_USERS = os.path.join(BASE_DIR, f"{data['DB']}")
DB_RATES = os.path.join(BASE_DIR, f"{data['DB3']}")
TXT_FILE = os.path.join(MAIN_DIR, f"{data['file']}")

DEMO_CHAT_LIMIT = 5


def init_db():
    """Создаём таблицы один раз при старте."""
    with closing(sq.connect(DB_PODS)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pods("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "email TEXT, message TEXT)"
        )
        conn.commit()
    with closing(sq.connect(DB_USERS)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users("
            "id INTEGER, password_key TEXT, words TEXT, quiz TEXT, name TEXT, username TEXT)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS test_history(id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, test_date TEXT, score INT, total INT, difficultly TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS test_details(id INTEGER PRIMARY KEY AUTOINCREMENT,
             test_id INT, question TEXT, word TEXT, user_answer TEXT, correct_answer TEXT, is_correct INT,
             FOREIGN KEY(test_id) REFERENCES test_history(id))"""
        )
        conn.commit()
    with closing(sq.connect(DB_RATES)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS rates("
            "id INTEGER, interface INTEGER, speed INTEGER, helpness INTEGER, accuracy INTEGER, comment TEXT)"
        )
        conn.commit()


def get_pods_db():
    conn = sq.connect(DB_PODS)
    conn.row_factory = sq.Row
    return conn


def get_users_db():
    conn = sq.connect(DB_USERS)
    conn.row_factory = sq.Row
    return conn


def get_rates_db():
    conn = sq.connect(DB_RATES)
    conn.row_factory = sq.Row
    return conn


def result(res):
    if res:
        words_str = res[0]
        numbers_list = words_str.split(';')
        return [int(num.strip()) for num in numbers_list if num.strip().isdigit()]
    return None


def worded(line):
    if "[" in line:
        word = line.split("[")[0]
    else:
        word = line.split(" ")[0]
    return word


def transcribed(line):
    if "[" in line:
        trans = line[line.index('['):line.index(']') + 1]
    else:
        trans = "[отсутствует]"
    return trans


def translate(line):
    if "[" in line:
        transl = line[line.index(']') + 1:-1]
    else:
        transl = line.split(' ')[-1]
    return transl


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Не авторизован! Войдите в админку", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def add_user(id, name, tag):
    with closing(get_users_db()) as conn:
        password_k = str(id) + str(random.randint(1000, 1000000))
        conn.execute("""INSERT INTO users VALUES(?, ?, ?, ?, ?, ?)""", (id, password_k, "", 0, name, tag))
        conn.commit()

def c_and_update(id, name, tag):
    with closing(get_users_db()) as conn:
        res = conn.execute("""SELECT name, username FROM users WHERE id=?""", (id, )).fetchone()
        if name != res[0] or tag != res[1]:
            conn.execute("""UPDATE users SET name=?, username=? WHERE id=?""", (name, tag, id))
            conn.commit()


@app.template_global()
def render_stars(val):
    val = int(val or 0)
    stars = ''
    for i in range(1, 6):
        filled = i <= val
        color = '#f59e0b' if filled else 'none'
        stroke = '#f59e0b' if filled else '#6b7694'
        stars += f'<svg width="14" height="14" viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" fill="{color}" stroke="{stroke}" stroke-width="1.5"/></svg>'
    return Markup(f'<div class="stars-display">{stars}</div>')


# 1. Маршрут, куда Telegram вернет пользователя
@app.route("/auth/telegram")
def auth_telegram():
    # Собираем данные из URL, которые прислал виджет
    user_data = {
        "id": request.args.get("id"),
        "first_name": request.args.get("first_name"),
        "last_name": request.args.get("last_name"),
        "username": request.args.get("username"),
        "photo_url": request.args.get("photo_url")
    }

    if user_data["id"]:
        session["user"] = user_data  # Сохраняем в сессию
        session.pop("not_auth", None)
        flash(f"Привет, {user_data['first_name']}!", "success")
        with closing(get_users_db()) as conn:
            tag = conn.execute("""SELECT username FROM users WHERE id=?""", (user_data["id"], )).fetchone()
        if not tag:
            add_user(user_data["id"], user_data["first_name"], user_data["username"])
        else:
            c_and_update(user_data["id"], user_data["first_name"], user_data["username"])
    return redirect(url_for("main"))


@app.route("/auth/logout")
def auth_logout():
    session.pop("user", None)
    return redirect(url_for("main"))


@app.route("/")
def main():
    user_data = session.get("user")
    na = session.get("not_auth")
    with closing(get_users_db()) as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return render_template("main.html", tg_user=user_data, user_count=user_count,
                           not_auth=na['status'] if na else None, sec=na['sec'] if na else None)


@app.route("/api/data", methods=["POST"])
def submit():
    if request.is_json:
        data_js = request.get_json()
        email = data_js.get("email")
        message = data_js.get("message")
    else:
        email = request.form.get("email")
        message = request.form.get("message")
    if not email or not message:
        return jsonify({"status": "error", "message": "Email и сообщение обязательны"}), 400
    with closing(get_pods_db()) as conn:
        conn.execute("INSERT INTO pods (email, message) VALUES (?, ?)", (email, message))
        conn.commit()
    return jsonify({"status": "success"})


@app.route("/api/demo-chat", methods=["POST"])
def demo_chat():
    session.permanent = True
    count = session.get("demo_chat_count", 0)

    if count >= DEMO_CHAT_LIMIT:
        return jsonify({"status": "error", "error": "limit_reached",
                        "message": "Демо-лимит исчерпан. Продолжите в Telegram."}), 403

    payload = request.get_json(silent=True) or {}
    text = (payload.get("message") or "").strip()

    if not text:
        return jsonify({"status": "error", "message": "Пустое сообщение"}), 400

    if len(text) > 200:
        text = text[:200]

    user_data = session.get("user")
    real_user_id = user_data["id"] if user_data else None

    try:
        replies = demo_reply(text, user_id=real_user_id)
    except Exception as ex:
        print(f"[demo_chat] error: {ex}")
        replies = ["Не смог обработать это сообщение, попробуйте другое слово."]

    count += 1
    session["demo_chat_count"] = count

    return jsonify({
        "status": "success",
        "replies": replies,          # ← теперь массив вместо одной строки "reply"
        "count": count,
        "limit": DEMO_CHAT_LIMIT,
        "limit_reached": count >= DEMO_CHAT_LIMIT
    })


@app.route("/admin", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username in ADMINS.keys() and password == ADMINS[username]:
            session["logged_in"] = True
            flash("Успешный вход!", "success")
            return redirect(url_for("admin_panel"))
        flash("Неверный логин или пароль!", "error")
    return render_template("login.html")


@app.route("/admin_out")
def logout():
    session.pop("logged_in", None)
    flash("Выход выполнен", "info")
    return redirect(url_for("login"))


@app.route("/admin_panel", methods=["GET", "POST"])
@login_required
def admin_panel():
    if request.method == "POST":
        return redirect(url_for("admin_panel"))   # защита от случайного POST
    with closing(get_pods_db()) as conn:
        messages = conn.execute(
            "SELECT id, email, message FROM pods ORDER BY id DESC"
        ).fetchall()
    with closing(get_rates_db()) as conn:
        reviews = conn.execute(
            """SELECT * FROM rates"""
        ).fetchall()
    return render_template("admin.html", messages=messages, reviews=reviews)


@app.route("/delete_message", methods=["POST"])
@login_required
def delete_message():
    message_id = request.form.get("message_id", "")
    # Защита от SQL-инъекций: проверяем что это число
    if message_id.isdigit():
        with closing(get_pods_db()) as conn:
            conn.execute("DELETE FROM pods WHERE id = ?", (int(message_id),))
            conn.commit()
        flash("Сообщение удалено!", "success")
    else:
        flash("Ошибка: некорректный ID", "error")
    return redirect(url_for("admin_panel"))


@app.route("/ladder")
def laddered():
    user_data = session.get('user')
    with closing(get_users_db()) as conn:
        rows = conn.execute(
            "SELECT quiz, name, username FROM users ORDER BY CAST(quiz AS INTEGER) DESC"
        ).fetchall()
    names, quizzes, usernames = [], [], []
    for row in rows:
        try:
            quizzes.append(int(row["quiz"]))
        except (ValueError, TypeError):
            quizzes.append(0)
        names.append(row["name"] or "Гость")
        usernames.append(f"@{row['username']}" or "@")
    return render_template("ladder.html", names=names, quizzes=quizzes, tg_user=user_data, usernames=usernames)


@app.route("/words")
def words():
    user_data = session.get('user')
    trans, words_, transl = [], [], []

    if not user_data:
        not_data: dict[str, bool | str] = {"status": True, "sec": "Слова"}
        session["not_auth"] = not_data
        return redirect(url_for("main"))
    with closing(get_users_db()) as conn:
        words_indexes_str = conn.execute("""SELECT words FROM users WHERE id=?""", (user_data["id"], )).fetchone()
    if words_indexes_str and words_indexes_str["words"]:
        words_indexes = result(words_indexes_str)
        if not words_indexes:
            words_indexes = ""
        try:
            with open(TXT_FILE, "r") as f:
                all_words = f.readlines()
            for i in words_indexes:
                if 0 <= i < len(all_words):
                    line = all_words[i]
                    words_.append(worded(line))
                    trans.append(transcribed(line))
                    transl.append(translate(line))
        except FileNotFoundError:
            flash("нет файла", "error")
    return render_template("words.html", words=words_, transc=trans, transl=transl, tg_user=user_data)


@app.route("/review")
def review():
    user_data = session.get("user")

    if not user_data:
        not_data = {"status": True, "sec": "Оценка"}
        session["not_auth"] = not_data
        return redirect(url_for("main"))

    return render_template("site_rate.html", tg_user=user_data)


@app.route("/review/data", methods=["POST"])
def submit_2():
    try:
        user_data = session.get("user")
        data_rate = request.get_json()
        id = user_data["id"]
        interface = data_rate.get("interface")
        speed = data_rate.get("speed")
        helpness = data_rate.get("helpness")
        accuracy = data_rate.get("accuracy")
        comment = data_rate.get("comment", "")
        with closing(get_rates_db()) as conn:
            com = conn.execute("""SELECT comment FROM rates WHERE id=?""", (id, )).fetchone()
            if not com:
                conn.execute("""INSERT INTO rates VALUES(?, ?, ?, ?, ?, ?)""", (id, interface, speed, helpness, accuracy, comment))
            else:
                conn.execute("""UPDATE rates SET interface=?, speed=?, helpness=?, accuracy=?, comment=? WHERE id=?""", (interface, speed, helpness, accuracy, comment, id))
            conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/tests")
def tests():
    user_data = session.get("user")
    if not user_data:
        not_auth: dict[str, bool | str] = {"status": True, "sec": "Тесты"}
        session["not_auth"] = not_auth
        return redirect(url_for("main"))
    with closing(get_users_db()) as conn:
        tests_data = conn.execute("""SELECT * FROM test_history WHERE user_id=? ORDER BY test_date DESC""", (user_data["id"], )).fetchall()
    diff_map = {3: "easy", 2: "medium", 1: "hard"}
    tests = [{
            "id": i["id"],
            "name": i['test_date'],
            "difficulty": diff_map.get(int(i["difficultly"]), "medium"),
            "question_count": i["total"],
            "locked": False,
            "progress": round(i["score"] / i["total"] * 100) if i["total"] else 0
        }
        for i in tests_data
    ]
    return render_template("tests.html", tg_user=user_data, tests=tests)


@app.route("/api/test/<int:test_id>")
def api_test(test_id):
    if not session.get("user"):
        return {"error": "unauthorized"}, 401

    with closing(get_users_db()) as conn:
        details = conn.execute(
            "SELECT * FROM test_details WHERE test_id=?", (test_id,)
        ).fetchall()

    return {
        "questions": [
            {
                "id": d["id"],
                "text": d["question"],
                "word": d["word"],
                "user_answer": d["user_answer"],
                "correct_answer": d["correct_answer"],
                "is_correct": bool(d["is_correct"])
            }
            for d in details
        ]
    }


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
