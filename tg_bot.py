# Импортируем необходимые библиотеки
import random, os, time
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
        id="monthly_results",        # фиксированный id, чтобы переопределять задачу
        replace_existing=True,       # если задача уже есть — заменить
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
        db.execute("""CREATE TABLE IF NOT EXISTS users(id INT, password_key INT, words TEXT, quiz TEXT, name TEXT, username TEXT)""")
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
user_tests = {}


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
        except Exception as ex:
            print(ex)
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


# Создает .html документ
def html_saves(res):
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Ваши выученные слова</title>
        <style>
            table {
                border-collapse: collapse;
                width: 80%;
                margin: 20px auto;
            }
            th, td{
                border: 1px solid #333;
                padding: 8px 12px;
                text-align: left;
            }
            th {
                background-color: #f2f2f2;
            }
        </style>
    </head>
    <body>
        <table>
            <tr><th>Слова. Транскрипции. Перевод.</th></tr>
    """
    for i in res:
        html_content += f"""     <tr><td>{i}</td></tr>\n"""

    html_content += """
        </table>
    </body>
    </html>
    """
    with open(data["html"], "w", encoding="utf-8") as file:
        file.write(html_content)
    print(f"{Fore.GREEN}***HTML файл успешно создан***{Style.RESET_ALL}")


# Функция для создания пользователя по тг айди и проверки на повторение
def add_user(id, user_name, tag):
    from colorama import Fore, Style
    with closing(get_users_db()) as db:
        res = db.execute("""SELECT password_key FROM users WHERE id=?""", (int(id),)).fetchone()
        if res is None:
            password_k = str(id) + str(random.randint(1000, 1000000))
            db.execute("""INSERT INTO users VALUES(?, ?, ?, ?, ?, ?)""", (id, password_k, "", 0, user_name, tag))
            print(f"{Fore.RED}{id} - {Fore.GREEN}{user_name}{Style.RESET_ALL} - зарегался")
        else:
            print(f"{Fore.RED}{id} - {Fore.GREEN}{user_name}{Style.RESET_ALL} зашел еще раз.")
            rev = db.execute("""SELECT name, username FROM users WHERE id=?""", (id, )).fetchone()
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
        reses = db.execute("""SELECT id FROM users""").fetchall()
        res = [row[0] for row in reses]
    return res


# Функция для выдачи множества рандомных слов
def g_ws(message: types.Message):
    ct = message.text
    c = int(round(float(ct.replace(",", "."))))
    name = message.from_user.first_name
    bot.reply_to(message, "These are your words(Это ваши слова):")
    print(f"{Fore.RED}{name}:{Style.RESET_ALL}")
    if c <= 30:
        for i in range(c):
            g_w(message, 2)
    else:
        for i in range(30):
            g_w(message, 2)


def g_w(message: types.Message, n):
    if n == 1:
        id = message.from_user.id
        user = message.from_user.first_name
        is_tr = False
        print(f"{Fore.RED}{user}:{Style.RESET_ALL}")
        with closing(get_users_db()) as db:
            try:
                # проверка на повторение слов и вывод слова, которое еще не было изучено.
                rand = random.randint(1, 9824)
                res = db.execute("""SELECT words FROM users WHERE id=?""", (int(id),)).fetchone()
                numbers = result(res)
                print(f"{Fore.YELLOW}Check {Style.RESET_ALL}{rand}")
                while not is_tr:
                    for i in numbers:
                        if i != rand:
                            pass
                        else:
                            rand = random.randint(1, 9824)
                    is_tr = True
                bot.reply_to(message=message, text="This is your random word to learn(Это твоё рандомное слово для "
                                                   "изучения):")
                with open(data["file"], 'r', encoding='utf-8') as file:
                    lines = file.readlines()
                bot.send_message(message.chat.id, text=lines[rand])
                words = f"{' '.join(str(w) for w in res)}{rand};"
                db.execute("""UPDATE users SET words=? WHERE id=?""", (
                    words, id))
                db.commit()
                print(f"{Fore.GREEN}Checked {Style.RESET_ALL}{rand}")
            except Exception as ex:
                print(f"{Fore.YELLOW}{ex}{Style.RESET_ALL}")
    elif n == 2:
        id = message.from_user.id
        # user = message.from_user.first_name
        is_tr = False
        with closing(get_users_db()) as db:
            try:
                # проверка на повторение слов и вывод слова, которое еще не было изучено.
                rand = random.randint(1, 9824)
                res = db.execute("""SELECT words FROM users WHERE id=?""", (int(id),)).fetchone()
                numbers = result(res)
                print(f"{Fore.YELLOW}Check {Style.RESET_ALL}{rand}")
                while not is_tr:
                    for i in numbers:
                        if i != rand:
                            pass
                        else:
                            rand = random.randint(1, 9824)
                    is_tr = True
                with open(data["file"], 'r', encoding='utf-8') as file:
                    lines = file.readlines()
                bot.send_message(message.chat.id, text=lines[rand])
                words = f"{' '.join(str(w) for w in res)}{rand};"
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
    id = message.from_user.id
    name = message.from_user.first_name
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
    ler(message=message)


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
    global menu_state
    menu_state = main_state
    bot.reply_to(message, "Меню с основными командами:", reply_markup=main_menu())


def more_and_more(message: types.Message):
    text = message.text
    info = get_word_data(text)
    print(f"{Fore.RED}{message.from_user.first_name}{Style.RESET_ALL} запросил подробности о слове {Fore.BLUE}{text}{Style.RESET_ALL}...")
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

    if transcription is not None:
        line += f" {transcription}"
    if audio is not None and audio != "":
        audio_file = audio
    else:
        audio_file = None
    translation = GoogleTranslator(source="auto", target="ru").translate(text)
    if transcription != text:
        line += f" {translation}"
    else:
        transcription = ""
    if part is not None and part2 is not None and part != part2:
        line2 += f"{part}, {part2}"
    elif part is not None:
        line2 += f"{part}"
    else:
        line2 += "отсутствует"
    if example is not None:
        line3 += f"{example}"
    else:
        line3 += "отсутствует"

    if definition is not None and text not in definition:
        tr_definition = GoogleTranslator(source="auto", target="ru").translate(definition)
        line4 += f"{tr_definition}"
    elif definition2 is not None:
        if transcription != "":
            tr_definition2 = GoogleTranslator(source="auto", target="ru").translate(definition2).replace(translation, text)
            line4 += f"{tr_definition2}"
        else:
            line4 += f"{definition2}"
    else:
        line4 += "отсутствует"
    bot.reply_to(message, line)
    bot.send_message(message.chat.id, line2)
    bot.send_message(message.chat.id, line3)
    bot.send_message(message.chat.id, line4)
    if audio_file is not None:
        bot.send_audio(message.chat.id, audio_file)
    else:
        bot.send_message(message.chat.id, "Аудио - отсутствует")
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
    user = message.from_user.first_name
    id = message.from_user.id
    tag = message.from_user.username
    print(f"{Fore.RED}{user} {Style.RESET_ALL}need help!!")
    bot.reply_to(message,
                 "Чтобы пользоваться ботом просто нажмите на кнопки снизу или собственноручно вводите команды"
                 "команды(To use bot you can touch a blue button in down corner or write commands yourself): ")
    bot.send_message(message.chat.id,
                     "При введение команд вам будет прислано сообщение , прочитав которое вы все поймете.(When you "
                     "write commands, you get a message and if you will read it, you understand all.)")
    bot.send_message(message.chat.id,
                     "Функционал пока маленький, но обновления не за горами!(Bot have not a lot of functions, "
                     "but updates will be soon!)", reply_markup=switch_menu())
    add_user(id, user, tag)


# Рассылка (команда bc)
@bot.message_handler(commands=['bc'])
def handle_broadcast(message):
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
            print(f"{Fore.LIGHTRED_EX}$$${Fore.RED}Рассылка прервалась из-за ошибки запроса{Fore.LIGHTRED_EX}$$${Style.RESET_ALL}")
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
                quiz = db.execute("""SELECT quiz FROM users WHERE id=?""", (i, )).fetchone()
                if quiz is not None and quiz[0] not in ("", "0", 0):
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
    if message.from_user.id in admin_ids:
        user_day = int(message.text.strip().split(" ")[1])
        clock = message.text.strip().split(" ")[2]
        if user_day < 1 or user_day > 31:
            bot.reply_to(message, "Неверный день. Пожалуйста, введите день от 1 до 31.")
        else:
            try:
                bot.reply_to(message, f"Напоминание будет срабатывать каждый {user_day}-й день месяца в {clock}.")
                schedule_reminder(clock, user_day)
            except Exception as ex:
                print(ex)
                bot.reply_to(message, "Команда набрана неправильно!!!")
    else:
        bot.reply_to(message, "У вас нет прав на совершение данной команды!!!")


@bot.message_handler(commands=['end_bct'])
def end_bct(message):
    admin_ids = [i for i in data["ADMIN"]]
    if message.from_user.id in admin_ids:
        try:
            scheduler.remove_job("monthly_results")
            bot.reply_to(message, "Все планированные рассылки отменены!!!")
        except Exception as ex:
            print(ex)
            bot.reply_to(message, "Нет назначенных рассылок!!!")
    else:
        bot.reply_to(message, "У вас нет прав на совершение данной команды!!!")


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


def transced(line):
    if "[" in line:
        transc = line[line.index('['):line.index(']')]
    else:
        transc = "Отсутствует."
    return transc


def transled(line):
    if "[" in line:
        transl = line[line.index(']'):-1]
    else:
        transl = line.split(' ')[-1]
    return transl


def send_next_question(chat_id):
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
            if number != 1:
                bot.send_message(chat_id, f"Ты смог ответить верно {correct} из {amount}"
                                          f"(1/{number} из всех изученных тобой слов)")
            else:
                bot.send_message(chat_id, f"Ты смог ответить верно {correct} из {amount}"
                                          f"(все твои слова)")
            if correct <= amount // 3:
                bot.send_message(chat_id, "Твой результат не такой красочный, какой мог быть.")
                bot.send_message(chat_id, "Тебе следует изучить заново слова!!!")
            elif amount // 3 < correct <= amount // 2:
                bot.send_message(chat_id, "Твой результат неплох.")
                bot.send_message(chat_id, "Но у тебя были ошибки, для закрепления повтори слова еще раз.")
                if number == 3:
                    db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + 1, chat_id))
                elif number == 2:
                    db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + 2, chat_id))
                else:
                    db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + 3, chat_id))
            else:
                bot.send_message(chat_id, "Ты молодец!!!!")
                bot.send_message(chat_id, "Двигайся в том же направление!!!")
                if number == 3:
                    db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + 2, chat_id))
                elif number == 2:
                    db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + 3, chat_id))
                else:
                    db.execute("""UPDATE users SET quiz=? WHERE id=?""", (quiz_v + 4, chat_id))
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
        send_next_question(chat_id)
        return

    r = random.randint(1, 4)
    r2 = random.randint(1, 3)
    inline, text = cases_test(r, r2, info, word_index, word)

    bot.send_message(chat_id, text, reply_markup=inline)


@bot.callback_query_handler(func=lambda c: c.data in ("true", "false"))
def test_answer(call):
    chat_id = call.message.chat.id
    state = user_tests.get(chat_id)

    # если тест уже завершён/нет состояния — игнор
    if not state:
        bot.answer_callback_query(call.id, "Этот вопрос уже неактивен.")
        return

    is_right = (call.data == "true")

    # отключаем кнопки у старого сообщения
    if is_right:
        bot.answer_callback_query(call.id, "Верно!")
        state["count"] += 1
    else:
        bot.answer_callback_query(call.id, "Неверно.")
    try:
        bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=None
        )
        bot.delete_message(chat_id, call.message.message_id)
    except Exception as ex:
        print(ex)



    # двигаем указатель и отправляем СЛЕДУЮЩЕЕ слово
    state["pos"] += 1
    send_next_question(chat_id)


def cases_test(r, r2, info, word_index, word):
    r_ind = random.randint(4, 10)
    if r == 1:
        part_of_speech = info["part_of_speech"]
        n, v, adj, p, adv, pre, con, inter  = "noun", "verb", "adjective", "pronoun", "adverb", "preposition", "conjunction", "interjection"
        parts = [n, v, adj, p, adv, pre, con, inter]
        others = [i for i in parts if i != part_of_speech]
        inline = types.InlineKeyboardMarkup()
        if r2 == 1:
            btn1_text = random.choice(others)
            btn1 = types.InlineKeyboardButton(btn1_text, callback_data="false")
            others.remove(btn1_text)
            btn2 = types.InlineKeyboardButton(part_of_speech, callback_data="true")
            btn3 = types.InlineKeyboardButton(random.choice(others), callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 2:
            btn1 = types.InlineKeyboardButton(part_of_speech, callback_data="true")
            btn2_text = random.choice(others)
            btn2 = types.InlineKeyboardButton(btn2_text, callback_data="false")
            others.remove(btn2_text)
            btn3 = types.InlineKeyboardButton(random.choice(others), callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 3:
            btn3_text = random.choice(others)
            btn1 = types.InlineKeyboardButton(btn3_text, callback_data="false")
            others.remove(btn3_text)
            btn2 = types.InlineKeyboardButton(random.choice(others), callback_data="false")
            btn3 = types.InlineKeyboardButton(part_of_speech, callback_data="true")
            inline.add(btn1, btn2, btn3)
        return inline, word
    elif r == 2:
        with open(data["file"], "r", encoding="utf-8") as f:
            lines = f.readlines()
        if "]" in lines[word_index]:
            correct_translation = lines[word_index].split("]")[-1].strip()
        else:
            correct_translation = " ".join(lines[word_index].split(" ")[0:-1])
        if "]" in lines[word_index + r_ind]:
            incorrect_1 = lines[word_index + r_ind].split("]")[-1].strip()
        else:
            incorrect_1 = " ".join(lines[word_index + r_ind].split(" ")[0:-1])
        if "]" in lines[word_index + r_ind + r_ind]:
            incorrect_2 = lines[word_index + r_ind + r_ind].split("]")[-1].strip()
        else:
            incorrect_2 = " ".join(lines[word_index + r_ind + r_ind].split(" ")[0:-1])
        inline = types.InlineKeyboardMarkup()
        if r2 == 1:
            btn1 = types.InlineKeyboardButton(incorrect_1, callback_data="false")
            btn2 = types.InlineKeyboardButton(correct_translation, callback_data="true")
            btn3 = types.InlineKeyboardButton(incorrect_2, callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 2:
            btn1 = types.InlineKeyboardButton(correct_translation, callback_data="true")
            btn2 = types.InlineKeyboardButton(incorrect_2, callback_data="false")
            btn3 = types.InlineKeyboardButton(incorrect_1, callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 3:
            btn1 = types.InlineKeyboardButton(incorrect_1, callback_data="false")
            btn2 = types.InlineKeyboardButton(incorrect_2, callback_data="false")
            btn3 = types.InlineKeyboardButton(correct_translation, callback_data="true")
            inline.add(btn1, btn2, btn3)
        return inline, word
    elif r == 3:
        with open(data["file"], "r", encoding="utf-8") as f:
            lines = f.readlines()
        try:
            transcript = info["transcription"]
            transcript = f"[{transcript.replace('/', '')}]"
            word2 = get_word_data(worded(lines[word_index + r_ind].strip()))
            word3 = get_word_data(worded(lines[word_index + r_ind + r_ind].strip()))
            incorrect_1 = f"[{word2['transcription'].replace('/', '')}]"
            incorrect_2 = f"[{word3['transcription'].replace('/', '')}]"
        except Exception as ex:
            print(ex)
            mass = [1, 2, 4]
            return cases_test(random.choice(mass), r2, info, word_index, word)
        inline = types.InlineKeyboardMarkup()
        if r2 == 1:
            btn1 = types.InlineKeyboardButton(incorrect_1, callback_data="false")
            btn2 = types.InlineKeyboardButton(transcript, callback_data="true")
            btn3 = types.InlineKeyboardButton(incorrect_2, callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 2:
            btn1 = types.InlineKeyboardButton(transcript, callback_data="true")
            btn2 = types.InlineKeyboardButton(incorrect_2, callback_data="false")
            btn3 = types.InlineKeyboardButton(incorrect_1, callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 3:
            btn1 = types.InlineKeyboardButton(incorrect_1, callback_data="false")
            btn2 = types.InlineKeyboardButton(incorrect_2, callback_data="false")
            btn3 = types.InlineKeyboardButton(transcript, callback_data="true")
            inline.add(btn1, btn2, btn3)
        return inline, word
    else:
        text = info["example"]
        try:
            if word in text:
                tr_text = text.replace(word, "... ")
            else:
                tr_text = info["definition"]
                if word in tr_text and info["definition2"] is not None and word not in info["definition2"]:
                    tr_text = info["definition2"]
                else:
                    return cases_test(random.randint(1, 3), r2, info, word_index, word)
        except Exception as ex:
            print(ex)
            return cases_test(random.randint(1, 3), r2, info, word_index, word)
        with open(data["file"], "r", encoding="utf-8") as f:
            lines = f.readlines()
        inline = types.InlineKeyboardMarkup()
        if r2 == 1:
            btn1 = types.InlineKeyboardButton(worded(lines[word_index + r_ind].strip()), callback_data="false")
            btn2 = types.InlineKeyboardButton(word, callback_data="true")
            btn3 = types.InlineKeyboardButton(worded(lines[word_index + r_ind + r_ind].strip()), callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 2:
            btn1 = types.InlineKeyboardButton(word, callback_data="true")
            btn2 = types.InlineKeyboardButton(worded(lines[word_index + r_ind].strip()), callback_data="false")
            btn3 = types.InlineKeyboardButton(worded(lines[word_index + r_ind + r_ind].strip()), callback_data="false")
            inline.add(btn1, btn2, btn3)
        if r2 == 3:
            btn1 = types.InlineKeyboardButton(worded(lines[word_index + r_ind].strip()), callback_data="false")
            btn2 = types.InlineKeyboardButton(worded(lines[word_index + r_ind + r_ind].strip()), callback_data="false")
            btn3 = types.InlineKeyboardButton(word, callback_data="true")
            inline.add(btn1, btn2, btn3)

        return inline, tr_text


@bot.message_handler(text=["Легкий тест"])
def easy_test(message):
    print(f"{Fore.RED}{message.from_user.first_name}{Style.RESET_ALL} - хочет пройти легкий тест...")
    test(message, 3)


@bot.message_handler(text=["Средний тест"])
def middle_test(message):
    print(f"{Fore.RED}{message.from_user.first_name}{Style.RESET_ALL} - хочет пройти средний тест...")
    test(message, 2)


@bot.message_handler(text=["Сложный тест"])
def hard_test(message):
    print(f"{Fore.RED}{message.from_user.first_name}{Style.RESET_ALL} - хочет пройти сложный тест...")
    test(message, 1)


def test(message, number):
    with closing(get_users_db()) as db:
        res = db.execute(
            """SELECT words FROM users WHERE id=?""",
            (int(message.from_user.id),)
        ).fetchone()
    user = message.from_user.first_name
    chat_id = message.chat.id

    res_w = result(res)
    if not res or len(res_w) < 20:
        bot.reply_to(message, "Недостаточно слов для теста (нужно ≥20)")
        print(f"{Fore.RED}{user}{Style.RESET_ALL} закончил тест досрочно...")
        return


    print(f"{Fore.RED}{user}{Style.RESET_ALL} начал тест...")

    with open(data["file"], "r", encoding="utf-8") as f:
        lines = f.readlines()

    words_ind = result(res)  # список индексов слов
    random.shuffle(words_ind)
    amount = len(words_ind) // number  # сколько вопросов хочешь

    user_tests[chat_id] = {
        "word_indexes": words_ind[:amount],
        "pos": 0,
        "lines": lines,
        "amount": amount,
        "count": 0,
        "number": number
    }

    bot.reply_to(message, "Тест по ранее вами изученным словам"
                          "(могут быть сложности с определением частей речи, "
                          "даже зная перевод, тк бот может брать сведения из нестандартных случаев):")
    send_next_question(chat_id)



def ler(message):
    id = message.from_user.id
    name = message.from_user.first_name
    print(f"{Fore.RED}{name}: {Style.RESET_ALL}запрашивает выученные слова...")
    bot.reply_to(message, "Ваши выученные слова сохранились в этот файле:")
    res = get_saves(id)
    html_saves(res)
    time.sleep(1)
    with open(data["html"], "rb") as f:
        bot.send_document(message.chat.id, f)
    os.remove(data["html"])
    print(f"{Fore.RED}{name}: {Style.RESET_ALL} получил свой файл.")


@bot.message_handler(commands=["add_ad", "a_a"])
def add_admin(message):
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
    id = message.text[len('/del '):]
    admin_ids = [i for i in data["ADMIN"]]
    id2 = message.from_user.id
    with closing(get_pods_db()) as db:
        res = db.execute("""SELECT email FROM pods WHERE id=?""", (id,)).fetchone()
        if id2 not in admin_ids:
            bot.reply_to(message, "У вас нет прав на выполнение этой команды.")
        else:
            if res is not None:
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
                print(f"{Fore.RED} {message.from_user.first_name} {Style.RESET_ALL} пытался удалить сообщение из поддержки")
                bot.reply_to(message, "Пользователь с таким айди не найден")


def add_ad(message: types.Message):
    id = int(message.text)
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
        bot.polling(non_stop=True)
    except Exception as e:
        print(f"{Fore.RED}Произошла ошибка: {Style.RESET_ALL}{e}")
        # Можно добавить задержку или повторный запуск
