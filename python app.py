import os
import asyncio
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
import uvicorn

# Настройки
BOT_TOKEN = "8298827041:AAG65Vuvnr4pEaCoU3_ZiIWj2skdYFGh9Eo"
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://your-domain.com{WEBHOOK_PATH}"

# Инициализация FastAPI
app = FastAPI(title="2048 Telegram Bot")

# База данных SQLite
SQLALCHEMY_DATABASE_URL = "sqlite:///./game.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Модели БД
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String)
    best_score = Column(Integer, default=0)
    games_played = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# Создание таблиц
Base.metadata.create_all(bind=engine)

# Зависимость для БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Модели Pydantic
class GameScore(BaseModel):
    user_id: int
    score: int

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Игровая логика 2048
class Game2048:
    def __init__(self):
        self.size = 4
        self.grid = [[0 for _ in range(self.size)] for _ in range(self.size)]
        self.score = 0
        self.add_new_tile()
        self.add_new_tile()
    
    def add_new_tile(self):
        empty_cells = []
        for i in range(self.size):
            for j in range(self.size):
                if self.grid[i][j] == 0:
                    empty_cells.append((i, j))
        
        if empty_cells:
            i, j = empty_cells[0]  # Берем первую пустую клетку для простоты
            self.grid[i][j] = 2 if len(empty_cells) % 2 else 4
    
    def move_left(self):
        moved = False
        for i in range(self.size):
            # Сдвиг влево
            row = [x for x in self.grid[i] if x != 0]
            # Объединение
            for j in range(len(row) - 1):
                if row[j] == row[j + 1]:
                    row[j] *= 2
                    self.score += row[j]
                    row[j + 1] = 0
                    moved = True
            # Удаление нулей после объединения
            row = [x for x in row if x != 0]
            # Заполнение нулями
            row.extend([0] * (self.size - len(row)))
            if self.grid[i] != row:
                moved = True
            self.grid[i] = row
        return moved
    
    def move_right(self):
        self.grid = [row[::-1] for row in self.grid]
        moved = self.move_left()
        self.grid = [row[::-1] for row in self.grid]
        return moved
    
    def move_up(self):
        self.grid = [list(x) for x in zip(*self.grid)]
        moved = self.move_left()
        self.grid = [list(x) for x in zip(*self.grid)]
        return moved
    
    def move_down(self):
        self.grid = [list(x) for x in zip(*self.grid)]
        moved = self.move_right()
        self.grid = [list(x) for x in zip(*self.grid)]
        return moved
    
    def is_game_over(self):
        # Проверка на пустые клетки
        for i in range(self.size):
            for j in range(self.size):
                if self.grid[i][j] == 0:
                    return False
        # Проверка на возможные ходы
        for i in range(self.size):
            for j in range(self.size):
                if (j < self.size - 1 and self.grid[i][j] == self.grid[i][j + 1]) or \
                   (i < self.size - 1 and self.grid[i][j] == self.grid[i + 1][j]):
                    return False
        return True
    
    def get_board_text(self):
        text = f"🎮 2048 | Очки: {self.score}\n\n"
        for i in range(self.size):
            row = ""
            for j in range(self.size):
                if self.grid[i][j] == 0:
                    row += "◻️"
                else:
                    row += self.get_tile_emoji(self.grid[i][j])
            text += row + "\n"
        return text
    
    def get_tile_emoji(self, value):
        emoji_map = {
            2: "2️⃣", 4: "4️⃣", 8: "8️⃣", 16: "🔶",
            32: "🔷", 64: "🟣", 128: "🟡", 256: "🟠",
            512: "🔴", 1024: "💎", 2048: "🏆"
        }
        return emoji_map.get(value, "🟦")

# Хранилище активных игр
user_games = {}

# Клавиатуры
def get_game_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ Влево"), KeyboardButton(text="➡️ Вправо")],
            [KeyboardButton(text="⬆️ Вверх"), KeyboardButton(text="⬇️ Вниз")],
            [KeyboardButton(text="🔄 Новая игра"), KeyboardButton(text="🏆 Таблица лидеров")],
            [KeyboardButton(text="📊 Мой счёт")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_start_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎮 Начать игру")],
            [KeyboardButton(text="🏆 Таблица лидеров"), KeyboardButton(text="📊 Мой счёт")]
        ],
        resize_keyboard=True
    )
    return keyboard

# Обработчики бота
@dp.message(Command("start"))
async def cmd_start(message: types.Message, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == message.from_user.id).first()
    if not user:
        user = User(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name
        )
        db.add(user)
        db.commit()
    
    await message.answer(
        "🎮 Добро пожаловать в игру 2048!\n\n"
        "Правила игры:\n"
        "• Используй кнопки для перемещения плиток\n"
        "• Объединяй плитки с одинаковыми числами\n"
        "• Цель - получить плитку 2048!\n\n"
        "Выбери действие:",
        reply_markup=get_start_keyboard()
    )

@dp.message(Command("game"))
async def cmd_game(message: types.Message):
    await start_new_game(message)

@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: types.Message, db: Session = Depends(get_db)):
    await show_leaderboard(message, db)

@dp.message(Command("score"))
async def cmd_score(message: types.Message, db: Session = Depends(get_db)):
    await show_my_score(message, db)

# Текстовые обработчики
@dp.message(lambda message: message.text == "🎮 Начать игру")
async def start_game_handler(message: types.Message):
    await start_new_game(message)

@dp.message(lambda message: message.text == "🏆 Таблица лидеров")
async def leaderboard_handler(message: types.Message, db: Session = Depends(get_db)):
    await show_leaderboard(message, db)

@dp.message(lambda message: message.text == "📊 Мой счёт")
async def my_score_handler(message: types.Message, db: Session = Depends(get_db)):
    await show_my_score(message, db)

@dp.message(lambda message: message.text == "🔄 Новая игра")
async def new_game_handler(message: types.Message):
    await start_new_game(message)

# Обработчики ходов
@dp.message(lambda message: message.text in ["⬅️ Влево", "➡️ Вправо", "⬆️ Вверх", "⬇️ Вниз"])
async def move_handler(message: types.Message, db: Session = Depends(get_db)):
    user_id = message.from_user.id
    
    if user_id not in user_games:
        await message.answer("Сначала начни новую игру!", reply_markup=get_start_keyboard())
        return
    
    game = user_games[user_id]
    moved = False
    
    if message.text == "⬅️ Влево":
        moved = game.move_left()
    elif message.text == "➡️ Вправо":
        moved = game.move_right()
    elif message.text == "⬆️ Вверх":
        moved = game.move_up()
    elif message.text == "⬇️ Вниз":
        moved = game.move_down()
    
    if moved:
        game.add_new_tile()
        
        # Сохраняем лучший результат
        user = db.query(User).filter(User.user_id == user_id).first()
        if game.score > user.best_score:
            user.best_score = game.score
            db.commit()
        
        board_text = game.get_board_text()
        
        if game.is_game_over():
            user.games_played += 1
            db.commit()
            
            await message.answer(
                f"{board_text}\n"
                f"💀 Игра окончена!\n"
                f"🏆 Твой результат: {game.score}\n"
                f"🎯 Лучший результат: {user.best_score}",
                reply_markup=get_start_keyboard()
            )
            del user_games[user_id]
        else:
            await message.answer(board_text, reply_markup=get_game_keyboard())
    else:
        await message.answer("Ход невозможен! Попробуй другое направление.")

# Функции помощники
async def start_new_game(message: types.Message):
    user_id = message.from_user.id
    user_games[user_id] = Game2048()
    game = user_games[user_id]
    
    await message.answer(
        "🎮 Новая игра началась!\n"
        "Используй кнопки для перемещения плиток:",
        reply_markup=get_game_keyboard()
    )
    await message.answer(game.get_board_text(), reply_markup=get_game_keyboard())

async def show_leaderboard(message: types.Message, db: Session):
    top_users = db.query(User).order_by(User.best_score.desc()).limit(10).all()
    
    leaderboard_text = "🏆 Топ 10 игроков:\n\n"
    for i, user in enumerate(top_users, 1):
        name = user.username or user.first_name
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        leaderboard_text += f"{medal} {name}: {user.best_score}\n"
    
    await message.answer(leaderboard_text)

async def show_my_score(message: types.Message, db: Session):
    user = db.query(User).filter(User.user_id == message.from_user.id).first()
    if user:
        await message.answer(
            f"📊 Твоя статистика:\n\n"
            f"🎯 Лучший результат: {user.best_score}\n"
            f"🎮 Сыграно игр: {user.games_played}\n"
            f"📅 Играет с: {user.created_at.strftime('%d.%m.%Y')}"
        )
    else:
        await message.answer("Ты еще не играл! Начни свою первую игру!")

# Вебхук для бота
@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    telegram_update = types.Update(**update)
    await dp.feed_update(bot, telegram_update)

# API endpoints
@app.post("/api/save-score")
async def save_score(score_data: GameScore, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == score_data.user_id).first()
    
    if not user:
        user = User(
            user_id=score_data.user_id,
            username="Unknown",
            first_name="Player"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    if score_data.score > user.best_score:
        user.best_score = score_data.score
        user.games_played += 1
        db.commit()
    
    return {"best_score": user.best_score}

@app.get("/api/best-score")
async def get_best_score(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        return {"best_score": user.best_score}
    return {"best_score": 0}

@app.get("/api/leaderboard")
async def get_leaderboard(db: Session = Depends(get_db)):
    top_users = db.query(User).order_by(User.best_score.desc()).limit(20).all()
    return [
        {
            "username": user.username or user.first_name,
            "best_score": user.best_score,
            "games_played": user.games_played
        }
        for user in top_users
    ]

# Настройка вебхука при запуске
@app.on_event("startup")
async def on_startup():
    webhook_url = os.getenv("WEBHOOK_URL", WEBHOOK_URL)
    if webhook_url != "https://your-domain.com/webhook":
        await bot.set_webhook(webhook_url)
        print(f"Webhook set to: {webhook_url}")
    else:
        print("Running in polling mode (set WEBHOOK_URL environment variable for webhooks)")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()

# Запуск в режиме polling (для разработки)
async def start_polling():
    print("Starting bot in polling mode...")
    await dp.start_polling(bot)

# Запуск приложения
if __name__ == "__main__":
    print("2048 Telegram Bot Started!")
    print("Available commands: /start, /game, /leaderboard, /score")
    
    # Для простоты запускаем polling режим
    # В продакшене используйте вебхуки
    asyncio.run(start_polling())