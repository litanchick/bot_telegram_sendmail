import datetime
import logging
import os
import smtplib
import sqlite3

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

from constans import (EMAIL, INSTR, LIST_EXIST_USERNAME, SEND_EMAIL,
                      TIME_WORK_CHAT, TEXT_MESSAGE, PASSWORD, USERNAME)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(lineno)s',
    level=logging.INFO
)

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TOKEN')
TELEGRAM_CHAT_ID = os.getenv('CHAT_ID')
SMTP_SERVER = os.getenv('SERVER')
NAME_BD = os.getenv('BD')


def start(update: Update, _) -> None:
    """Функция-обработчик для команды /start."""
    update.message.reply_text("Привет! Я бот.")


def join_datatime(country):
    day_now = str(datetime.date.today()) + ' '
    datatime_begin = datetime.datetime.strptime(
        day_now + TIME_WORK_CHAT[country]['time_begin'], '%Y-%m-%d %H:%M:%S'
    )
    datatime_close = datetime.datetime.strptime(
        day_now + TIME_WORK_CHAT[country]['time_close'], '%Y-%m-%d %H:%M:%S'
    )
    return datatime_begin, datatime_close


def create_message(chat, update_id, username, text):
    """Формируем текст сообщения для отправки по почте."""
    message_info = (
            f'Поступило обращение от НКО в чате "{chat}". \n'
            f'Обновление № {update_id}: пользователь {username} написал: \n'
            f'\n{text}.\n'
        )
    return message_info


def choice_text_message(chat, country):
    text_auto = ''
    datatime_begin, datatime_close = join_datatime(country)
    for language in TIME_WORK_CHAT[country]['language_message']:
        # В Молдавии летом и в другие сезоны отличется часовой пояс.
        index_time_zone = 0
        if country == 'MD':
            month = datetime.date.today().month
            # Проверяем сейчас лето, если нет,
            # то используем второе число для определения местного времени.
            if 6 <= month <= 8:
                index_time_zone = 1
        time_zone = datetime.timedelta(
            hours=TIME_WORK_CHAT[country]['timezone_delta'][index_time_zone]
        )
        # В чатах РФ нужно определить это чат по товарам или по такси.
        if country == 'RU':
            # Такси есть только в РФ чатах.
            if 'такси' in chat:
                text_auto = TEXT_MESSAGE["RU такси"]
            else:
                text_auto = TEXT_MESSAGE["RU товары"]
            # Возвращаем сразу сообщение, т.к. в РФ
            # наличие отбивок на 2-х языках отстутвует.
            return text_auto.format(
                (datatime_begin + time_zone).time(),
                (datatime_close + time_zone).time()
            )
        # Формируем текстовое сообщение на языке страны.
        text_auto += TEXT_MESSAGE[language].format(
            (datatime_begin + time_zone).time(),
            (datatime_close + time_zone).time()
        ) + '\n'
    return text_auto


def check_send_in_bd():
    datatime_now = datetime.datetime.now()
    for country in TIME_WORK_CHAT:
        time_begin_country, time_close_country = join_datatime(country)
        if datatime_now >= time_begin_country:
            connection = sqlite3.connect(NAME_BD)
            cursor = connection.cursor()
            query = (
                'SELECT chat_name, username, text, update_id, country '
                'FROM Messages WHERE flag = ? AND country = ?'
            )
            cursor.execute(query, ('not send', country))
            records = cursor.fetchall()
            for row in records:
                chat = row[0]
                username = row[1]
                text = row[2]
                update_id = row[3]
                country = row[4]
                message_info = create_message(chat, update_id, username, text)
                send_message(message_info, chat, country)
                query = (
                    'UPDATE Messages SET flag = ? '
                    'WHERE flag = ? AND text = ?'
                )
                cursor.execute(query, ('send', 'not send', text))
                connection.commit()
            connection.close()


def send_message(text, chat, country):
    """Отправка сообщения на почту."""

    subject = f'Сообщение в Telegram-чате {chat}.'
    if country == 'RU':
        manual = INSTR['RU']
    else:
        manual = INSTR['international']
    email_text = text + manual
    message = 'From: {}\nTo: {}\nSubject: {}\n\n{}'.format(
        EMAIL, SEND_EMAIL, subject, email_text
    )

    # Активация сервера отправки исходящих сообщений.
    server = smtplib.SMTP_SSL(SMTP_SERVER)
    server.set_debuglevel(1)
    server.ehlo(EMAIL)
    server.login(USERNAME, PASSWORD)
    server.auth_plain()
    server.sendmail(EMAIL, SEND_EMAIL, message.encode('utf-8'))
    server.quit()
    return True


def add_message_db(
        message_info,
        message_id, chat: str,
        username, text,
        date_now, update_id,
        country, date_begin, date_close):
    """Функция добавления новой записи в БД.
    Добавляет следующие параметры:
    текст сообщения, номер сообщения и обновления,
    название чата, логин пользователя, дата."""

    # Устанавливаем соединение с БД.
    connection = sqlite3.connect(NAME_BD)
    cursor = connection.cursor()
    flag_send = 'send'

    query = (
        'SELECT data, username, chat_name '
        'FROM Messages WHERE update_id = ?'
    )
    cursor.execute(query, (update_id - 1,))
    records = cursor.fetchall()

    # Исключаем из отправки письма,
    # если один и тот же пользователь написал
    # в рамках 5-ти минут несколько сообщений.
    for row in records:
        data_last = datetime.datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
        delta_time = date_now - data_last
        if ((delta_time) < datetime.timedelta(minutes=5)) and (
            row[1] == username
        ):
            # письмо отпарвлять не нужно
            flag_send = 'dont need send'
        else:
            # Отправляем письмо на почту и
            # ставим флаг отправки сообщения.
            if date_begin <= date_now < date_close:
                flag_send = 'send'
            # Проверяем, если сообщение пришло в нерабочее время,
            # то флаг отправки сообщения ставим 0.
            else:
                flag_send = 'not send'

    if flag_send == 'send':
        send_message(message_info, chat, country)
    # Добавляем запись в БД.
    query = 'INSERT INTO Messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
    cursor.execute(
        query,
        (
            update_id, chat, country,
            message_id, date_now,
            username, text, flag_send,
        )
    )
    connection.commit()
    connection.close()
    return flag_send


def echo(update: Update, _) -> None:
    """Функция-обработчик для входящих сообщений."""

    username = update.message.from_user.name
    # Проверяем написали саообщение через ответ или нет.
    # if not update.message.reply_to_message:

    # Проверяем логин пользователя, чтобы исключить тех,
    # от кого обрабатывать обращения не нужно.
    if username not in LIST_EXIST_USERNAME:

        # Обрабатываем данные из сообщения,
        # приводим к нужному формату.
        chat = str(update.message.chat.title)
        text = str(update.message.text)
        update_id = int(update.update_id)
        message_id = int(update.message.message_id)

        # Вычисляем часовой пояс МСК,
        # чтобы сохранить дату в нужном формате.
        three_hour = datetime.timedelta(hours=3)
        date = (update.message.date + three_hour).replace(tzinfo=None)

        # Достаём из чата пометку страны.
        country = chat.split('[')[1].split(']')[0].replace('такси', '').strip()
        if country not in TIME_WORK_CHAT:
            country = 'RU'
        date_begin, date_close = join_datatime(country)

        # Проверяем нет ли сообщений, которые пришли в нерабочее время
        # и если есть - отправляем.
        check_send_in_bd()

        # Формируем сообщение, добавление в БД и отправку письма.
        message_info = create_message(chat, update_id, username, text)
        flag_send = add_message_db(
            message_info, message_id,
            chat, username, text, date, update_id,
            country, date_begin, date_close,
        )
        if flag_send == 'not send':
            text_auto = choice_text_message(chat, country)
            update.message.reply_text(text_auto)


def main() -> None:
    updater = Updater(TELEGRAM_TOKEN)

    # Получаем объект диспетчера для регистрации обработчиков
    dispatcher = updater.dispatcher

    # Регистрируем обработчик команды /start
    dispatcher.add_handler(CommandHandler('start', start))

    # Регистрируем обработчик входящих сообщений
    dispatcher.add_handler(
        MessageHandler(Filters.text & ~Filters.command, echo)
    )

    # Запускаем бот
    updater.start_polling()

    # Ждем остановки бота (Ctrl+C для завершения)
    updater.idle()


if __name__ == '__main__':
    main()
