# Импортируем необходимые библиотеки
import random, os, time
from typing import Any
from colorama import Fore, Style
import telebot as tg
from telebot import types, custom_filters
import sqlite3 as sq
import json, requests
from deep_translator import GoogleTranslator
import detectlanguage
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from contextlib import closing

job_stores = {
    "default": SQLAlchemyJobStore(url="sqlite:///jobs.sqlite")  # файл jobs.sqlite в текущей папке
}

scheduler = BackgroundScheduler(jobstores=job_stores)
scheduler.start()


def schedule_reminder(clock: str, day: int):
    """
    clock: строка вида '12:00'
    day: число месяца 1..31
    """
    hour, minute = map(int, clock.split(":"))

    scheduler.add_job(
        send_results,
        trigger="cron",
        day=day,
        hour=hour,
        minute=minute,
        id="monthly_results",  # фиксированный id, чтобы переопределять задачу
        replace_existing=True,  # если задача уже есть — заменить
    )


# Тут создается база данных и подключается уже созданный тг бот
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_JSON = os.path.join(BASE_DIR, 'api.json')
with open(API_JSON, "r") as js:
    data = json.load(js)
DB_USERS_DIR = os.path.join(BASE_DIR, 'site', f"{data['DB']}")
DB_PODS_DIR = os.path.join(BASE_DIR, 'site', f"{data['DB2']}")
bot = tg.TeleBot(data["API"])
bot.add_custom_filter(custom_filters.TextMatchFilter())


def init_db():
    with closing(sq.connect(DB_USERS_DIR)) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS users(id INT, password_key INT, words TEXT,
            quiz TEXT, name TEXT, username TEXT)"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS test_history(id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, test_date TEXT, score INT, total INT, difficultly TEXT)"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS test_details(id INTEGER PRIMARY KEY AUTOINCREMENT,
             test_id INT, question TEXT, word TEXT, user_answer TEXT, correct_answer TEXT, is_correct INT,
             FOREIGN KEY(test_id) REFERENCES test_history(id))"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS in_test(user_id INTEGER, is_testing INTEGER)"""
        )
        db.commit()
    with closing(sq.connect(DB_PODS_DIR)) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pods(id INTEGER PRIMARY KEY, email TEXT, message TEXT)""")
        db.commit()


def get_users_db():
    db = sq.connect(DB_USERS_DIR)
    db.row_factory = sq.Row
    return db


def get_pods_db():
    db = sq.connect(DB_PODS_DIR)
    db.row_factory = sq.Row
    return db


detectlanguage.configuration.api_key = data["D_API"]
API_URL = data["DICT"]
menu_state = ""
main_state = "MAIN"
test_state = "TEST"
user_tests: dict[int, dict[str, Any]] = {}
cancel_user_data: dict[int, dict[str]]= {}


def get_word_data(word: str):
    url = API_URL.format(word=word.lower().strip())
    resp = requests.get(url)
    d = resp.json()

    # Ошибка: слово не найдено
    if isinstance(d, dict) and d.get("title") == "No Definitions Found":
        return None

    entry = d[0]
    phonetics = entry.get("phonetics", [])
    meanings = entry.get("meanings", [])

    transcription = None
    audio_url = None
    if phonetics:
        transcription = phonetics[0].get("text")
        audio_url = phonetics[0].get("audio")

    part_of_speech = None
    part_of_speech_2 = None
    definition = None
    example = None
    definition2 = None
    if meanings:
        m0 = meanings[0]
        try:
            m1 = meanings[1]
        except IndexError:
            m1 = meanings[0]
        part_of_speech = m0.get("partOfSpeech")
        part_of_speech_2 = m1.get("partOfSpeech")
        defs = m0.get("definitions", [])
        defs2 = m1.get("definitions", [])
        if defs:
            definition = defs[0].get("definition")
            example = defs[0].get("example")
        if defs2:
            definition = defs2[0].get("definition")

    return {
        "word": entry.get("word"),
        "transcription": transcription,
        "audio": audio_url,
        "part_of_speech": part_of_speech,
        "definition": definition,
        "example": example,
        "definition2": definition2,
        "part_of_speech2": part_of_speech_2
    }


def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("Дай слово для изучения")
    btn2 = types.KeyboardButton("Дай слова для изучения")
    btn3 = types.KeyboardButton("Изученные мной слова")
    btn4 = types.KeyboardButton("Переведи слова")
    btn5 = types.KeyboardButton("Узнать о слове подробнее")
    btn6 = types.KeyboardButton("Пройти тест")
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    return markup


def test_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("Легкий тест")
    btn2 = types.KeyboardButton("Средний тест")
    btn3 = types.KeyboardButton("Сложный тест")
    btn4 = types.KeyboardButton("Назад🔙")
    markup.add(btn1, btn2, btn3, btn4)
    return markup


def switch_menu():
    global menu_state
    if menu_state == "MAIN":
        return main_menu()
    elif menu_state == "TEST":
        return test_menu()
    else:
        return main_menu()


# Функция для создания пользователя по тг айди и проверки на повторение
def add_user(id, user_name, tag):
    with closing(get_users_db()) as db:
        res = db.execute("""SELECT password_key FROM users WHERE id=?""", (int(id),)).fetchone()
        if not res:
            password_k = str(id) + str(random.randint(1000, 1000000))
            db.execute("""INSERT INTO users VALUES(?, ?, ?, ?, ?, ?)""", (id, password_k, "", 0, user_name, tag))
            print(f"{Fore.RED}{id} - {Fore.GREEN}{user_name}{Style.RESET_ALL} - зарегался")
        else:
            print(f"{Fore.RED}{id} - {Fore.GREEN}{user_name}{Style.RESET_ALL} зашел еще раз.")
            rev = db.execute("""SELECT name, username FROM users WHERE id=?""", (id,)).fetchone()
            old_name, old_tag = rev
            if not rev or old_name != user_name or old_tag != tag:
                db.execute("""UPDATE users SET name=?, username=? WHERE id=?""", (user_name, tag, id))
                print(f"Данные обновлены для {Fore.RED}{id}{Style.RESET_ALL}:")
                print(f"Новое имя: {Fore.GREEN}{user_name}{Style.RESET_ALL}, Тег: {Fore.BLUE}@{tag}{Style.RESET_ALL}")
        db.commit()


# Находит все изученные слова
def get_saves(id):
    strings = []
    with closing(get_users_db()) as db:
        res = db.execute("""SELECT words FROM users WHERE id=?""", (int(id),)).fetchone()
    words = result(res)
    if not words:
        words = []
    with open(data["file"], "r", encoding='utf-8') as f:
        lines = f.readlines()
    for i in words:
        strings.append(lines[int(i)])
    return strings


# Создание массива изученных слов
def result(res):
    if res:
        words_str = res[0]
        numbers_list = words_str.split(';')
        return [int(num.strip()) for num in numbers_list if num.strip().isdigit()]
    return None


# Функция для взятия всех пользователей и в дальнейшем рассылки
def get_ids():
    with closing(get_users_db()) as db:
        reuses = db.execute("""SELECT id FROM users""").fetchall()
        res = [row[0] for row in reuses]
    return res


# Функция для выдачи множества рандомных слов
def g_ws(message: types.Message):
    ct = message.text
    if ct:
        c = int(round(float(ct.replace(",", "."))))
    else:
        c = 1
    if message.from_user:
        name = message.from_user.first_name
    else:
        name = "Name"
    bot.reply_to(message, "These are your words(Это ваши слова):")
    print(f"{Fore.RED}{name}:{Style.RESET_ALL}")
    if c <= 30:
        for i in range(c):
            g_w(message, 2)
    else:
        for i in range(30):
            g_w(message, 2)


def g_w_check(db, id, is_tr):
    rand = random.randint(1, 9824)
    res = db.execute("""SELECT words
                        FROM users
                        WHERE id = ?""", (int(id),)).fetchone()
    numbers = result(res)
    if not numbers:
        numbers = []
    print(f"{Fore.YELLOW}Check {Style.RESET_ALL}{rand}")
    while not is_tr:
        for i in numbers:
            if i != rand:
                pass
            else:
                rand = random.randint(1, 9824)
        is_tr = True
    return rand, res


def g_w(message: types.Message, n):
    if message.from_user:
        id = message.from_user.id
        user = message.from_user.first_name
    else:
        id = "ID"
        user = "User"
    is_tr = False
    print(f"{Fore.RED}{user}:{Style.RESET_ALL}")
    with closing(get_users_db()) as db:
        try:
            # проверка на повторение слов и вывод слова, которое еще не было изучено.
            rand, res = g_w_check(db, id, is_tr)
            if n == 1:
                bot.reply_to(message=message, text="This is your random word to learn(Это твоё рандомное слово для "
                                                "изучения):")
            with open(data["file"], 'r', encoding='utf-8') as file:
                lines = file.readlines()
            bot.send_message(message.chat.id, text=lines[rand])
            words = f"{res[0] if res else ''}{rand};"
            db.execute("""UPDATE users SET words=? WHERE id=?""", (
                words, id))
            db.commit()
            print(f"{Fore.GREEN}Checked {Style.RESET_ALL}{rand}")
        except Exception as ex:
            print(f"{Fore.YELLOW}{ex}{Style.RESET_ALL}")


def translate_register(message: types.Message):
    text = message.text
    translate_process(message, text)


def translate_process(message: types.Message, text):
    if message.from_user:
        id = message.from_user.id
        name = message.from_user.first_name
    else:
        id = "ID"
        name = "Name"
    print(f"{Fore.RED}{name}{Style.RESET_ALL}" + " - запрашивает перевод:")
    print(f"{Fore.YELLOW}DETECT-LANG попытка...{Style.RESET_ALL}")
    try:
        dest = detectlanguage.detect_code(text)
        if dest == "ru":
            res = GoogleTranslator(source="ru", target="en").translate(text)
            print(f"{Fore.RED}{id}{Style.RESET_ALL} - получил перевод слов {Fore.BLUE}{text}")
            bot.reply_to(message, res)
        elif dest == "en":
            res = GoogleTranslator(source="en", target="ru").translate(text)
            print(f"{Fore.RED}{id}{Style.RESET_ALL} - получил перевод слов {Fore.BLUE}{text}")
            bot.reply_to(message, res)
        else:
            print(f"{Fore.RED}{id}{Style.RESET_ALL} - не получил перевод слов {Fore.BLUE}{text}")
            bot.reply_to(message, "Извините, но бот предназначен для изучения английского языка для русскоязычных "
                                  "пользователей!!!")
    except Exception as ex:
        print(f"{Fore.RED}{ex}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}LOGIC попытка...{Style.RESET_ALL}")
        res = GoogleTranslator(source="auto", target="en").translate(text)
        if res != text:
            print(f"{Fore.RED}{id}{Style.RESET_ALL} - получил перевод слов {Fore.BLUE}{text}")
            bot.reply_to(message, f"{text} -> {res}")
        else:
            print(f"{Fore.RED}{id}{Style.RESET_ALL} - получил перевод слов {Fore.BLUE}{text}")
            res = GoogleTranslator(source="auto", target="ru").translate(text)
            bot.reply_to(message, f"{text} -> {res}")


@bot.message_handler(text=["Дай слово для изучения"])
def give_w(message):
    g_w(message, 1)


@bot.message_handler(text=["Дай слова для изучения"])
def give_ws(message):
    bot.reply_to(message, "How many words you want to learn(как много слов ты хочешь изучить) [from 1 to 30]:")
    bot.register_next_step_handler(message, g_ws)


@bot.message_handler(text=["Изученные мной слова"])
def learned(message):
    bot.reply_to(message, "Вот ваши слова:")
    bot.send_message(message.chat.id, "https://t3roll.pythonanywhere.com/words")


@bot.message_handler(text=["Переведи слова"])
def translate_words(message):
    bot.reply_to(message, "Enter sentence to translate(введи предложение для перевода):")
    bot.register_next_step_handler(message, translate_register)


@bot.message_handler(text=["Пройти тест"])
def to_text_menu(message):
    global menu_state
    menu_state = test_state
    bot.reply_to(message, "Тесты по словам, которые вы прошли(По уровню сложности):",
                 reply_markup=test_menu())


@bot.message_handler(text="Назад🔙")
def back(message):
    with closing(get_users_db()) as db:
        is_testing = db.execute("""SELECT is_testing FROM in_test WHERE user_id=?""", (message.from_user.id, )).fetchone()
    if not bool(is_testing):
        global menu_state
        menu_state = main_state
        bot.reply_to(message, "Меню с основными командами:", reply_markup=main_menu())
    else:
        inline = cancel_markup()
        m = bot.reply_to(message, "Вы еще не закончили проходить тест!!!", reply_markup=inline)
        cancel_user_data[message.chat.id] = {
            "mes_id": m.message_id,
            "name": message.from_user.first_name,
            "mes_user": message.message_id
        }


def more_and_more(message: types.Message):
    text = message.text
    if message.from_user:
        f_name = message.from_user.first_name
    else:
        f_name = "First_name"
    if not text:
        text = ""
    info = get_word_data(text)
    print(f"{Fore.RED}{f_name}{Style.RESET_ALL} запросил подробности о слове {Fore.BLUE}{text}{Style.RESET_ALL}...")
    if not info:
        bot.reply_to(message, "О таком слове у нас нет информации!!!")
        return
    line = text.strip()
    line2 = "Части речи - "
    line3 = "Пример - "
    line4 = "Значение - "
    transcription = info["transcription"]
    audio = info["audio"]
    part = info["part_of_speech"]
    part2 = info["part_of_speech2"]
    example = info["example"]
    definition = info["definition"]
    definition2 = info["definition2"]

    if transcription:
        line += f" {transcription}"
    if audio and audio != "":
        audio_file = audio
    else:
        audio_file = None
    translation = GoogleTranslator(source="auto", target="ru").translate(text)
    if transcription != text:
        line += f" {translation}"
    else:
        transcription = ""
    if part and part2 and part != part2:
        line2 += f"{part}, {part2}"
    elif part:
        line2 += f"{part}"
    else:
        line2 += "отсутствует"
    if example:
        line3 += f"{example}"
    else:
        line3 += "отсутствует"

    if definition and text not in definition:
        tr_definition = GoogleTranslator(source="auto", target="ru").translate(definition)
        line4 += f"{tr_definition}"
    elif definition2:
        if transcription != "":
            tr_definition2 = GoogleTranslator(source="auto", target="ru").translate(definition2).replace(translation,
                                                                                                         text)
            line4 += f"{tr_definition2}"
        else:
            line4 += f"{definition2}"
    else:
        line4 += "отсутствует"
    bot.reply_to(message, line)
    bot.send_message(message.chat.id, line2)
    bot.send_message(message.chat.id, line3)
    bot.send_message(message.chat.id, line4)
    if audio_file:
        bot.send_audio(message.chat.id, audio_file)
    else:
        bot.send_message(message.chat.id, "Аудио - отсутствует")
    if message.from_user:
        print(f"{Fore.RED}{message.from_user.first_name}{Style.RESET_ALL} - получил подробности!!!")


@bot.message_handler(text=["Узнать о слове подробнее"])
def more(message):
    bot.reply_to(message, "Напиши слово, о котором хочешь получить информацию:")
    bot.register_next_step_handler(message, more_and_more)


# Наш сайт
@bot.message_handler(commands=["site"])
def site(message):
    bot.reply_to(message, "Наш сайт:")
    bot.send_message(message.chat.id, "https://t3roll.pythonanywhere.com")


# Начальная команда тг бота
@bot.message_handler(commands=["start", "go", "lets_go"])
def start(message):
    if not message.from_user:
        return
    id = message.from_user.id
    name = message.from_user.first_name
    tag = message.from_user.username
    bot.reply_to(message=message, text="Привет, это крутой бот для изучения английского!")
    bot.send_message(message.chat.id, text="На английском это звучало бы так -> Hi, this is cool bot to learn english!")
    bot.send_message(message.chat.id, "Вам может помочь команда /h или /help, если вы ничего не понимаете!",
                     reply_markup=switch_menu())
    add_user(id, name, tag)


# Помощь
@bot.message_handler(commands=["help", "h"])
def helping(message):
    if not message.from_user:
        return
    user = message.from_user.first_name
    id = message.from_user.id
    tag = message.from_user.username
    print(f"{Fore.RED}{user} {Style.RESET_ALL}need help!!")
    bot.reply_to(message,
                 "Чтобы пользоваться ботом просто нажмите на кнопки снизу или в меню(горит синим цветом слева снизу)"
                 "(To use bot you can touch a blue button in down corner or write commands yourself): ")
    bot.send_message(message.chat.id,
                     "После использования команды вам будет прислано сообщение , прочитав которое вы все поймете.(When you "
                     "use commands, you get a message and if you will read it, you understand all.)")
    bot.send_message(message.chat.id,
                     "Функционал пока маленький, но обновления не за горами!(Bot have not a lot of functions, "
                     "but updates will be soon!)", reply_markup=switch_menu())
    add_user(id, user, tag)


# Рассылка (команда bc)
@bot.message_handler(commands=['bc'])
def handle_broadcast(message):
    if not message.from_user:
        return
    admin_ids = [i for i in data["ADMIN"]]
    user_ids = get_ids()
    id = message.from_user.id
    name = message.from_user.first_name
    if id not in admin_ids:
        bot.reply_to(message, "У вас нет прав на выполнение этой команды.")
        print(f"{Fore.RED}{name} - {Style.RESET_ALL}пытался сделать рассылку!!!")
    else:
        print(f"{Fore.BLUE}***Админ начал рассылку***{Style.RESET_ALL}")
        msg_text = message.text[len('/bc '):]
        if not msg_text:
            print(
                f"{Fore.LIGHTRED_EX}$$${Fore.RED}Рассылка прервалась из-за ошибки запроса{Fore.LIGHTRED_EX}$$${Style.RESET_ALL}")
            bot.reply_to(message, "Пожалуйста, укажите сообщение для рассылки.")
        else:
            for user_id in user_ids:
                if user_id not in admin_ids:
                    try:
                        print(f"{Fore.RED}{user_id}: {Fore.GREEN}получил рассылку{Style.RESET_ALL}")
                        bot.send_message(user_id, msg_text)
                    except Exception as ex:
                        print(
                            f"Ошибка при отправке пользователю {Fore.RED}{user_id}: {Fore.YELLOW}{ex}{Style.RESET_ALL}")
                elif user_id == id:
                    print(f"{Fore.RED}{id}: {Fore.MAGENTA}отправил рассылку{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}{user_id}: {Fore.MAGENTA}является админом{Style.RESET_ALL}")
                    bot.send_message(user_id, f"{name} - произвел рассылку")
            bot.reply_to(message, "Рассылка завершена!")
            print(f"{Fore.BLUE}***Рассылка завершена***{Style.RESET_ALL}")


def send_results():
    print(f"{Fore.GREEN}***Рассылка начинается***{Style.RESET_ALL}")
    with closing(get_users_db()) as db:
        for i in get_ids():
            try:
                quiz = db.execute("""SELECT quiz FROM users WHERE id=?""", (i,)).fetchone()
                if quiz and quiz[0] not in ("", "0", 0):
                    bot.send_message(i, f"В этом месяце ты заработал {quiz[0]} баллов по нашей системе оценивания.")
                else:
                    bot.send_message(i, "Ты не решал тесты в этом месяце, уже пора начинать!!!")
                print(f"{Fore.RED}{i}{Style.RESET_ALL} - получил рассылку.")
            except Exception as ex:
                print(ex)
    print(f"{Fore.GREEN}***Рассылка завершена***{Style.RESET_ALL}")


@bot.message_handler(commands=['start_bct'])
def bc_time(message):
    admin_ids = [i for i in data["ADMIN"]]
    if not message.from_user or message.from_user.id not in admin_ids:
        bot.reply_to(message, "У вас нет прав на совершение данной команды!!!")
        return
    user_day = int((message.text or "").strip().split(" ")[1])
    clock = (message.text or "").strip().split(" ")[2]
    if user_day < 1 or user_day > 31:
        bot.reply_to(message, "Неверный день. Пожалуйста, введите день от 1 до 31.")
    else:
        try:
            bot.reply_to(message, f"Напоминание будет срабатывать каждый {user_day}-й день месяца в {clock}.")
            schedule_reminder(clock, user_day)
        except Exception as ex:
            print(ex)
            bot.reply_to(message, "Команда набрана неправильно!!!")


@bot.message_handler(commands=['end_bct'])
def end_bct(message):
    admin_ids = [i for i in data["ADMIN"]]
    if not message.from_user or message.from_user.id not in admin_ids:
        bot.reply_to(message, "У вас нет прав на совершение данной команды!!!")
        return
    try:
        scheduler.remove_job("monthly_results")
        bot.reply_to(message, "Все планированные рассылки отменены!!!")
    except Exception as ex:
        print(ex)
        bot.reply_to(message, "Нет назначенных рассылок!!!")


@bot.message_handler(commands=['ladder'])
def ladder(message):
    bot.reply_to(message, "Вот рейтинг:")
    bot.send_message(message.chat.id, "https://t3roll.pythonanywhere.com/ladder")


def worded(line):
    if "[" in line:
        word = line.split("[")[0]
    else:
        word = line.split(" ")[0]
    return word


def transcribed(line):
    if "[" in line:
        trans = line[line.index('['):line.index(']')]
    else:
        trans = "Отсутствует."
    return trans


def transited(line):
    if "[" in line:
        transl = line[line.index(']') + 1:]
    else:
        transl = line.split(' ')[-1]
    try:
        transl = transl.strip().split(' ')[0].strip().replace(',', '')
    except Exception:
        transl = transl
    return transl


def send_next_question(chat_id, name):
    state = user_tests.get(chat_id)
    if not state:
        return

    pos = state["pos"]
    word_indexes = state["word_indexes"]
    lines = state["lines"]
    amount = state["amount"]
    correct = state["count"]
    number = state["number"]
    with closing(get_users_db()) as db:

        quiz = db.execute("""SELECT quiz FROM users WHERE id=?""", (chat_id,)).fetchone()
        quiz_v = int(quiz[0]) if quiz else 0
        if pos >= len(word_indexes):
            db.execute("""DELETE FROM in_test WHERE user_id=?""", (chat_id, ))
            try:
                cancel_user_data.pop(chat_id)
            except Exception as e:
                print(e)
            cur = db.execute(
                """INSERT INTO test_history(user_id, test_date, score, total, difficultly)
                VALUES (?, datetime('now'), ?, ?, ?)""",
                (chat_id, correct, amount, number))
            test_id = cur.lastrowid
            data_to_insert = [
                (test_id, a["question"], a["word"], a["user_answer"], a["correct_answer"], a["is_correct"])
                for a in state["answers_to_save"]
            ]
            db.executemany("""INSERT INTO test_details(test_id, question, word, user_answer, correct_answer, is_correct)
            VALUES (?, ?, ?, ?, ?, ?)""", data_to_insert)
            bot.delete_message(chat_id, state['f_mes'])
            bot.delete_message(chat_id, state['s_mes'])
            if number != 1:
                bot.send_message(chat_id, f"Ты смог ответить верно {correct} из {amount}"
                                          f"(1/{number} из всех изученных тобой слов)")
            else:
                bot.send_message(chat_id, f"Ты смог ответить верно {correct} из {amount}"
                                          f"(все твои слова)")
            if correct <= amount // 3:
                bot.send_message(chat_id, "😢 Твой результат не такой красочный, какой мог быть.")
                bot.send_message(chat_id, "Тебе следует изучить заново слова!!!")
            elif amount // 3 < correct <= amount // 2:
                bot.send_message(chat_id, "😊Твой результат неплох.")
                bot.send_message(chat_id, "Но у тебя были ошибки, для закрепления повтори слова еще раз.")
                q_v_end = 1 if number == 3 else (2 if number == 2 else 3)
                db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + q_v_end, chat_id))
            else:
                bot.send_message(chat_id, "😎 Ты молодец!!!!")
                bot.send_message(chat_id, "Двигайся в том же направление 👆!!!")
                q_v_end = 2 if number == 3 else (3 if number == 2 else 4)
                db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + q_v_end, chat_id))
            db.commit()
            user_tests.pop(chat_id, None)
            print(f"{Fore.RED}{chat_id}{Style.RESET_ALL} завершил тест...")
            return
    word_index = word_indexes[pos]
    line = lines[word_index].strip().lower()
    word = worded(line)
    info = get_word_data(word)
    if not info:
        # пропускаем слово, двигаемся дальше
        state["pos"] += 1
        send_next_question(chat_id, state['name'])
        return

    r = random.randint(1, 4)
    r2 = random.randint(1, 3)
    inline, text, msg_id, true_word, four = cases_test(r, r2, info, word_index, word, chat_id, name)
    state["msg_id"] = msg_id
    state["true"] = true_word
    state["word"] = word
    word_id = bot.send_message(chat_id, text, reply_markup=inline)
    state["word_id"] = word_id.message_id
    state["question"] = text if four else ""


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_inline(buttons: list[tuple[str, str]]) -> types.InlineKeyboardMarkup:
    """Создаёт InlineKeyboardMarkup из списка (текст, callback_data)."""
    markup = types.InlineKeyboardMarkup()
    markup.add(*[types.InlineKeyboardButton(t, callback_data=c) for t, c in buttons])
    return markup


def _shuffled_buttons(correct_text: str, incorrect: list[str], position: int) -> list[tuple[str, str]]:
    """
    Возвращает список (текст, callback) с правильной кнопкой на позиции 1/2/3.
    position — число 1..3.
    """
    wrongs = [(t, t) for t in incorrect[:2]]
    correct = (correct_text, "true")
    pos = position - 1  # 0-based
    wrongs.insert(pos, correct)
    return wrongs


# ─── callback handler ────────────────────────────────────────────────────────

RESULT_EMOJI = {True: "✅", False: "❌"}
RESULT_TEXT  = {True: "ВЕРНО!",  False: "НЕВЕРНО."}

def _progress_bar(current: int, total: int, width: int = 10) -> str:
    filled = round(width * current / total) if total else 0
    return "█" * filled + "░" * (width - filled)


@bot.callback_query_handler(func=lambda c: c.data in ("canc", "con"))
def test_procces(call):
    id = call.message.chat.id
    can_con = cancel_user_data.get(id)
    state = user_tests.get(id)
    try:
        if call.data == "canc":
            bot.delete_message(id, can_con["mes_user"])
            bot.delete_message(id, can_con["mes_id"])
            try:
                bot.delete_message(id, state['f_mes'])
                bot.delete_message(id, state['s_mes'])
                bot.delete_message(id, state['word_id'])
                bot.delete_message(id, state['msg_id'])
                bot.delete_message(id, state['user_mes'])
            except Exception as e:
                print(e)
            bot.send_message(id, "💢Вы закончили тест досрочно!!!")
            print(f"{Fore.RED}{can_con['name']}{Style.RESET_ALL}: закончил тест досрочно!")
            with closing(get_users_db()) as db:
                db.execute("""DELETE FROM in_test WHERE user_id=?""", (id, ))
                db.commit()
            cancel_user_data.pop(id)
            user_tests.pop(id)
        if call.data == "con":
            cancel_user_data.pop(id)
            bot.delete_message(id, can_con["mes_user"])
            bot.delete_message(id, can_con["mes_id"])
    except Exception as e:
        print(e)


@bot.callback_query_handler(func=lambda c: c.data)
def test_answer(call):
    chat_id = call.message.chat.id
    state   = user_tests.get(chat_id)

    if not state:
        bot.answer_callback_query(call.id, "⏳ Этот вопрос уже неактивен.")
        return

    is_right   = (call.data == "true")
    word_chosen = str(state["true"] if is_right else (call.data or ""))
    emoji  = RESULT_EMOJI[is_right]
    res_text = RESULT_TEXT[is_right]

    if is_right:
        state["count"] += 1

    state["answers_to_save"].append({
        "question":       state["question"],
        "word":           state["word"],
        "user_answer":    word_chosen,
        "correct_answer": state["true"],
        "is_correct":     1 if is_right else 0,
    })

    # прогресс
    pos = state["pos"] + 1          # текущий (1-based)
    total = state.get("amount")
    bar = _progress_bar(pos, total) if isinstance(total, int) else ""

    print(f"{Fore.RED}{state['name']}{Style.RESET_ALL}: опрос удален.")
    print(
        f"{Fore.YELLOW}Результат опроса{Style.RESET_ALL}({Fore.RED}{state['name']}{Style.RESET_ALL}): Надо было -{Fore.GREEN}{state['true']}{Style.RESET_ALL}, выбрано -{Fore.BLUE}{word_chosen}{Style.RESET_ALL}, это {Fore.GREEN if is_right else Fore.RED}{'ВЕРНО!' if is_right else 'НЕВЕРНО.'}{Style.RESET_ALL}")
    try:
        bot.delete_message(chat_id, state["msg_id"])
        bot.delete_message(chat_id, state["word_id"])

        feedback = (
            f"{emoji} <b>{res_text}</b>\n\n"
            f"🔤 Слово: <b>{state['word']}</b>\n"
            f"✔️ Правильно: <b>{state['true']}</b>\n"
            f"👆 Выбрано: <b>{word_chosen}</b>\n\n"
            f"📊 Прогресс: {bar} {pos}/{total}\n"
            f"⭐ Счёт: {state['count']}"
        )
        tmp = bot.send_message(chat_id, feedback, parse_mode="HTML")
        # короткая пауза — пользователь успевает прочитать
        time.sleep(1.5)
        bot.delete_message(chat_id, tmp.message_id)
    except Exception:
        pass

    state["pos"] += 1
    send_next_question(chat_id, state["name"])


# ─── cases_test (рефакторинг) ─────────────────────────────────────────────────

def cases_test(r, r2, info, word_index, word, chat_id, name):
    r_ind = random.randint(4, 10)
    four: bool = False
    with open(data["file"], "r", encoding="utf-8") as f:
        lines = f.readlines()
    # ── тип 1: часть речи ────────────────────────────────────────────────────
    if r == 1:
        part  = info["part_of_speech"] or ""
        part2 = info["part_of_speech2"] or ""
        parts = ["noun","verb","adjective","pronoun","adverb","preposition","conjunction","interjection"]
        others = [p for p in parts if p != part and p != part2]
        random.shuffle(others)

        prompt = "🔤 Выбери правильную <b>часть речи</b> слова:"
        correct_text = random.choice([part, part2])
        incorrect = others[:2]
        returned_w1, returned_w2 = word, correct_text
        print(
            f"{Fore.RED}{name}{Style.RESET_ALL}: выбирает часть речи слова {Fore.BLUE}{returned_w1}{Style.RESET_ALL}, правильный ответ - {Fore.GREEN}{returned_w2}{Style.RESET_ALL}.")

    # ── тип 2: перевод ───────────────────────────────────────────────────────
    elif r == 2:
        incorrect = [transited(lines[word_index + r_ind]),
                    transited(lines[word_index + r_ind * 2])]
        correct_text = transited(lines[word_index])

        prompt = "🌍 Выбери правильный <b>перевод</b> слова:"
        returned_w1, returned_w2 = word, correct_text
        print(
            f"{Fore.RED}{name}{Style.RESET_ALL}: выбирает перевод слова {Fore.BLUE}{returned_w1}{Style.RESET_ALL}, правильный ответ - {Fore.GREEN}{returned_w2}{Style.RESET_ALL}.")

    # ── тип 3: транскрипция ──────────────────────────────────────────────────
    elif r == 3:
        transcript = info.get("transcription")
        if not transcript:
            return cases_test(random.choice([1, 2, 4]), r2, info, word_index, word, chat_id, name)

        transcript = f"[{transcript.replace('/', '')}]"
        w2 = get_word_data(worded(lines[word_index + r_ind].strip()))
        w3 = get_word_data(worded(lines[word_index + r_ind * 2].strip()))

        if not w2 or not w3 or not w2["transcription"] or not w3["transcription"]:
            return cases_test(random.choice([1, 2, 4]), r2, info, word_index, word, chat_id, name)

        correct_text = transcript
        incorrect = [f"[{w2['transcription'].replace('/', '')}]",
                        f"[{w3['transcription'].replace('/', '')}]"]
        prompt = "🔊 Выбери правильную <b>транскрипцию</b> к слову:"
        returned_w1, returned_w2 = word, correct_text
        print(
            f"{Fore.RED}{name}{Style.RESET_ALL}: выбирает транскрипцию слова {Fore.BLUE}{returned_w1}{Style.RESET_ALL}, правильный ответ - {Fore.GREEN}{returned_w2}{Style.RESET_ALL}.")

    # ── тип 4: пропуск / определение ────────────────────────────────────────
    else:
        text = info.get("example")
        is_def = False
        if text and word in text:
            tr_text = text.replace(word, "___")
        else:
            is_def = True
            tr_text = info.get("definition")

            if not tr_text or word in tr_text:
                tr_text = info.get("definition2")
                if not tr_text or word in tr_text:
                    return cases_test(random.randint(1, 3), r2, info, word_index, word, chat_id, name)

        correct_text = word
        incorrect    = [worded(lines[word_index + r_ind].strip()),
                        worded(lines[word_index + r_ind * 2].strip())]
        prompt = ("📝 Выбери слово, которое подходит вместо ___:"
                  if not is_def else
                  "📖 Выбери слово, которое подходит по <b>определению</b>:")
        returned_w1, returned_w2 = tr_text, correct_text
        four = True
        if not is_def:
            print(
                f"{Fore.RED}{name}{Style.RESET_ALL}: выбирает подходящее слово для в пропуск, правильный ответ - {Fore.GREEN}{returned_w2}{Style.RESET_ALL}.")
        else:
            print(
                f"{Fore.RED}{name}{Style.RESET_ALL}: выбирает слово по обозначению, правильный ответ - {Fore.GREEN}{returned_w2}{Style.RESET_ALL}.")
    # ── собираем клавиатуру ──────────────────────────────────────────────────
    buttons = _shuffled_buttons(correct_text, incorrect, r2)
    inline  = _make_inline(buttons)

    msg_id = bot.send_message(chat_id, prompt, parse_mode="HTML")
    return inline, returned_w1, msg_id.message_id, returned_w2, four


def cancel_markup():
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("Закончить", callback_data="canc")
    btn2 = types.InlineKeyboardButton("Продолжить", callback_data="con")
    markup.add(btn1, btn2)
    return markup


@bot.message_handler(text=["Легкий тест"])
def easy_test(message):
    name = message.from_user.first_name if message.from_user else "?"
    with closing(get_users_db()) as db:
        is_testing = db.execute("""SELECT is_testing FROM in_test  WHERE user_id=?""", (message.from_user.id, )).fetchone()
    if not bool(is_testing):
        print(f"{Fore.RED}{name}{Style.RESET_ALL}: хочет пройти легкий тест...")
        test(message, 3)
    else:
        inline = cancel_markup()
        m = bot.reply_to(message, "Вы еще не закончили проходить тест!!!", reply_markup=inline)
        cancel_user_data[message.chat.id] = {
            "mes_id": m.message_id,
            "name": name,
            "mes_user": message.message_id
        }




@bot.message_handler(text=["Средний тест"])
def middle_test(message):
    name = message.from_user.first_name if message.from_user else "?"
    with closing(get_users_db()) as db:
        is_testing = db.execute("""SELECT is_testing FROM in_test  WHERE user_id=?""", (message.from_user.id, )).fetchone()
    if not bool(is_testing):
        print(f"{Fore.RED}{name}{Style.RESET_ALL}: хочет пройти средний тест...")
        test(message, 2)
    else:
        inline = cancel_markup()
        m = bot.reply_to(message, "Вы еще не закончили проходить тест!!!", reply_markup=inline)
        cancel_user_data[message.chat.id] = {
            "mes_id": m.message_id,
            "name": name,
            "mes_user": message.message_id
        }


@bot.message_handler(text=["Сложный тест"])
def hard_test(message):
    name = message.from_user.first_name if message.from_user else "?"
    with closing(get_users_db()) as db:
        is_testing = db.execute("""SELECT is_testing FROM in_test  WHERE user_id=?""", (message.from_user.id, )).fetchone()
    if not bool(is_testing):
        print(f"{Fore.RED}{name}{Style.RESET_ALL}: хочет пройти сложный тест...")
        test(message, 1)
    else:
        inline = cancel_markup()
        m = bot.reply_to(message, "Вы еще не закончили проходить тест!!!", reply_markup=inline)
        cancel_user_data[message.chat.id] = {
            "mes_id": m.message_id,
            "name": name,
            "mes_user": message.message_id
        }



def test(message, number):
    if not message.from_user:
        return
    with closing(get_users_db()) as db:
        res: object = db.execute(
            """SELECT words FROM users WHERE id=?""",
            (int(message.from_user.id),)
        ).fetchone()
        db.execute("""INSERT INTO in_test VALUES(?, ?)""", (message.from_user.id, 1))
        db.commit()
    user = message.from_user.first_name
    chat_id = message.chat.id
    res_w = result(res)
    if not res or not res_w or len(res_w) < 20:
        bot.reply_to(message, "Недостаточно слов для теста (нужно ≥20)")
        print(
            f"{Fore.RED}{user}{Style.RESET_ALL}: закончил тест досрочно({Fore.RED}недостаточно слов для теста{Style.RESET_ALL})...")
        return

    with open(data["file"], "r", encoding="utf-8") as f:
        lines = f.readlines()

    words_ind = result(res)  # список индексов слов
    if words_ind:
        random.shuffle(words_ind)
        amount = len(words_ind) // number  # сколько вопросов хочешь
        f_mes = bot.reply_to(message, "Тест по ранее вами изученным словам"
                                      "(могут быть сложности с определением частей речи, "
                                      "даже зная перевод, т.к. бот может брать сведения из нестандартных случаев).")
        s_mes = bot.send_message(chat_id,
                                 "Вам будет представлено три варианта и условие, вам надо выбрать один из них и вы узнаете правильно вы ответили или нет:")
        user_tests[chat_id] = {
            "word_indexes": words_ind[:amount],
            "pos": 0,
            "lines": lines,
            "amount": amount,
            "count": 0,
            "number": number,
            "msg_id": "",
            "word_id": "",
            "true": "",
            "word": "",
            "f_mes": f_mes.message_id,
            "s_mes": s_mes.message_id,
            "name": user,
            "question": "",
            "answers_to_save": [],
            "user_mes": message.message_id
        }

    send_next_question(chat_id, user)


@bot.message_handler(commands=["add_ad", "a_a"])
def add_admin(message):
    if not message.from_user:
        return
    admin_ids = [i for i in data["ADMIN"]]
    user = message.from_user.id
    name = message.from_user.first_name
    if user in admin_ids:
        bot.reply_to(message, "Введите его id:")
        bot.register_next_step_handler(message, add_ad)
    else:
        bot.reply_to(message, "У вас нет прав на выполнение этой команды.")
        print(f"{Fore.RED}{name} - {Style.RESET_ALL}пытался создать админа!!!")


@bot.message_handler(commands=["del"])
def delete(message):
    if not message.from_user:
        return
    id = message.text[len('/del '):] if message.text else ""
    admin_ids = [i for i in data["ADMIN"]]
    id2 = message.from_user.id
    with closing(get_pods_db()) as db:
        res = db.execute("""SELECT email FROM pods WHERE id=?""", (id,)).fetchone()
        if id2 not in admin_ids:
            bot.reply_to(message, "У вас нет прав на выполнение этой команды.")
        else:
            if res:
                try:
                    db.execute("""DELETE FROM pods WHERE id=?""", (id,))
                    db.commit()
                    print(f"{Fore.RED} {message.from_user.first_name} {Style.RESET_ALL} удалил сообщение из поддержки")
                    bot.reply_to(message, f"Письмо в поддержку от id {id} было удалено!!!")
                except Exception as ex:
                    print(ex)
                    print(
                        f"{Fore.RED} {message.from_user.first_name} {Style.RESET_ALL} пытался удалить сообщение из поддержки")
                    bot.reply_to(message, "Пользователь с таким айди не найден")
            else:
                print(
                    f"{Fore.RED} {message.from_user.first_name} {Style.RESET_ALL} пытался удалить сообщение из поддержки")
                bot.reply_to(message, "Пользователь с таким айди не найден")


def add_ad(message: types.Message):
    if not message.from_user:
        return
    id = int(message.text or 0)
    data["ADMIN"].append(id)
    with open(API_JSON, "w", encoding="utf-8") as jsf:
        json.dump(data, jsf, ensure_ascii=False, indent=4)
    bot.reply_to(message, "Админ добавлен.")
    print(f"{Fore.RED}{message.from_user.first_name} {Style.RESET_ALL}добавил админа {Fore.RED}{id}{Style.RESET_ALL}")


# Запускаем бота с обработкой ошибок
if __name__ == "__main__":
    try:
        print(f"{Fore.CYAN}***Бот запущен***{Style.RESET_ALL}")
        init_db()
        bot.infinity_polling()
    except Exception as e:
        print(f"{Fore.RED}Произошла ошибка: {Style.RESET_ALL}{e}")
        # Можно добавить задержку или повторный запуск
