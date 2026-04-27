from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
import sqlite3 as sq
from functools import wraps
from contextlib import closing
import json, random, os

app = Flask(__name__)
app.secret_key = "02002020002henglish_t9290Roll"
ADMIN_USERNAME = "t3Roll"
ADMIN_PASSWORD = "08070909Koch"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR = os.path.dirname(BASE_DIR)
API_JSON = os.path.join(MAIN_DIR, "api.json")
with open(API_JSON, "r") as js:
    data = json.load(js)
DB_PODS  = os.path.join(BASE_DIR, f"{data['DB2']}")
DB_USERS = os.path.join(BASE_DIR, f"{data['DB']}")
TXT_FILE = os.path.join(MAIN_DIR, f"{data['file']}")


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
        conn.commit()


def get_pods_db():
    conn = sq.connect(DB_PODS)
    conn.row_factory = sq.Row
    return conn


def get_users_db():
    conn = sq.connect(DB_USERS)
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


def transced(line):
    if "[" in line:
        transc = line[line.index('['):line.index(']') + 1]
    else:
        transc = "[отсутствует]"
    return transc


def transled(line):
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
        session["user"] = user_data # Сохраняем в сессию
        flash(f"Привет, {user_data['first_name']}!", "success")
        with closing(get_users_db()) as conn:
            tag = conn.execute("""SELECT username FROM users WHERE id=?""", (user_data["id"], )).fetchone()
        if not tag:
            add_user(user_data["id"], user_data["first_name"], user_data["username"])
    return redirect(url_for("main"))

# 2. Обновите маршрут выхода
@app.route("/auth/logout")
def auth_logout():
    session.pop("user", None)
    return redirect(url_for("main"))

# 3. Убедитесь, что главная страница видит сессию
@app.route("/")
def main():
    user_data = session.get("user") # Если нет пользователя, будет None
    with closing(get_users_db()) as conn:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return render_template("main.html", tg_user=user_data, user_count=user_count)


@app.route("/api/data", methods=["POST"])
def submit():
    if request.is_json:
        data = request.get_json()
        email = data.get("email")
        message = data.get("message")
    else:
        email = request.form.get("email")
        message = request.form.get("message")
    if not email or not message:
        return jsonify({"status": "error", "message": "Email и сообщение обязательны"}), 400
    with closing(get_pods_db()) as conn:
        conn.execute("INSERT INTO pods (email, message) VALUES (?, ?)", (email, message))
        conn.commit()
    return jsonify({"status": "success"})


@app.route("/admin", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
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
    return render_template("admin.html", messages=messages)


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
            "SELECT quiz, name, username FROM users ORDER BY quiz DESC"
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
    if not user_data:
        flash("Пожалуйста, войдите, чтобы просмотреть свои слова", "error")
        return redirect(url_for("main"))
    words, transc, transl = [], [], []
    with closing(get_users_db()) as conn:
        words_indexes_str = conn.execute("""SELECT words FROM users WHERE id=?""", (user_data["id"], )).fetchone()
    if words_indexes_str and words_indexes_str["words"]:
        words_indexes = result(words_indexes_str)
        try:
            with open(TXT_FILE, "r") as f:
                all_words = f.readlines()
            for i in words_indexes:
                if 0 <= i < len(all_words):
                    line = all_words[i]
                    words.append(worded(line))
                    transc.append(transced(line))
                    transl.append(transled(line))
        except FileNotFoundError:
            flash("нет файла", "error")
    return render_template("words.html", words=words, transc=transc, transl=transl, tg_user=user_data)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)