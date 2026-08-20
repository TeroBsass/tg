"""
bot_core.py — мост между веб-демо на сайте и реальными хендлерами из bot.py.
"""
from types import SimpleNamespace
import tg_bot as bot_module

DEMO_USER_ID = -1


class _FakeUser:
    def __init__(self, user_id, first_name):
        self.id = user_id
        self.first_name = first_name
        self.username = "web_demo"


class _CapturingBot:
    """Перехватывает отправку сообщений вместо реального Telegram API."""
    def __init__(self, real_bot):
        self._real = real_bot
        self.captured = []  # список отдельных сообщений, каждое — отдельный элемент

    def reply_to(self, message, text, **kwargs):
        self.captured.append(text)

    def send_message(self, chat_id, text, **kwargs):
        self.captured.append(text)

    def send_audio(self, *args, **kwargs):
        pass  # в веб-демо аудио не поддерживаем

    def register_next_step_handler(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return getattr(self._real, name)


def _call_with_capture(fn, *args, **kwargs) -> list[str]:
    """Подменяет bot.bot на перехватчик, вызывает fn, возвращает список отправленных сообщений по порядку."""
    capturing = _CapturingBot(bot_module.bot)
    original_bot = bot_module.bot
    bot_module.bot = capturing
    try:
        fn(*args, **kwargs)
    finally:
        bot_module.bot = original_bot
    return capturing.captured if capturing.captured else ["Не удалось получить ответ."]


# ─── Точка входа для веб-демо ───────────────────────────────────────────

_WORD_INFO_TRIGGERS = ("расскажи про", "расскажи о", "что значит", "что такое")


def demo_reply(user_text: str, user_id=None) -> list[str]:
    """
    Разбирает сообщение из веб-чата и вызывает реальный хендлер из bot.py.
    Всегда возвращает СПИСОК отдельных сообщений — так же, как бот шлёт
    их по одному в Telegram, а не единым блоком.
    """
    resolved_id = user_id if user_id else DEMO_USER_ID
    text = user_text.strip()
    if not text:
        return ["Напишите что-нибудь 🙂"]

    lower = text.lower()

    for trigger in _WORD_INFO_TRIGGERS:
        if lower.startswith(trigger):
            word = lower[len(trigger):].strip().split(" ")[-1]
            if not word:
                return ["Укажите слово, например: расскажи про apple"]

            fake_message = SimpleNamespace(
                text=word,
                chat=SimpleNamespace(id=resolved_id),
                message_id=0,
                from_user=_FakeUser(resolved_id, "Web Guest"),
            )
            print(f"[demo_chat] user={resolved_id} -> more_and_more('{word}')")
            return _call_with_capture(bot_module.more_and_more, fake_message)

    fake_message = SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=resolved_id),
        message_id=0,
        from_user=_FakeUser(resolved_id, "Web Guest"),
    )
    print(f"[demo_chat] user={resolved_id} -> translate_process('{text}')")
    return _call_with_capture(bot_module.translate_process, fake_message, text)