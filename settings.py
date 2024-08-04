import sqlite3
import os

from dotenv import load_dotenv


load_dotenv()
NAME_BD = os.getenv('BD')

connection = sqlite3.connect(NAME_BD)
cursor = connection.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS Messages (
        update_id INTEGER NOT NULL,
        chat_name TEXT NOT NULL,
        country TEXT NOT NULL,
        message_id INTEGER NOT NULL,
        data DATETIME NOT NULL,
        username TEXT NOT NULL,
        text TEXT NOT NULL,
        flag TEXT)''')
