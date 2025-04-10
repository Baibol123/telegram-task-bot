import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ConversationHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
import sqlite3
from datetime import datetime
import os
from config import ADMIN_IDS


# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)


# Состояния бота
WAITING_PHOTO, ADMIN_MENU, ADD_TASK, EDIT_TASK, DELETE_TASK, USER_MODE, WAITING_COMMENT = range(7)
# В начале файла с другими состояниями
WAITING_PHOTO, ADMIN_MENU, ADD_TASK, EDIT_TASK, DELETE_TASK, USER_MODE, WAITING_COMMENT, SKIP_TASK = range(8)
# Инициализация базы данных
def init_db():
    db_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(db_dir, exist_ok=True)
    
    # Указываем путь к БД в папке data
    db_path = os.path.join(db_dir, 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('DROP TABLE IF EXISTS completed_tasks')
    cursor.execute('DROP TABLE IF EXISTS task_comments')
    cursor.execute('DROP TABLE IF EXISTS skipped_tasks')
    # Таблица задач
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        is_active BOOLEAN DEFAULT 1
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS completed_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        telegram_file_id TEXT,
        file_type TEXT,
        completion_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    ''')
    
    # Таблица комментариев
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS task_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT,
        comment TEXT,
        voice_message_id TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    ''')
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS skipped_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        reason TEXT,
        voice_message_id TEXT,
        skip_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    )
    ''')
    conn.commit()
    conn.close()


# Проверка прав администратора
def is_admin(user_id):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return user_id in ADMIN_IDS

# Получение списка задач
def get_tasks(only_active=False):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if only_active:
        cursor.execute('SELECT id, description FROM tasks WHERE is_active = 1 ORDER BY id')
    else:
        cursor.execute('SELECT id, description, is_active FROM tasks ORDER BY id')
    
    tasks = cursor.fetchall()
    conn.close()
    return tasks

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    # Сохраняем/обновляем информацию о пользователе
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO users (id, first_name, username)
    VALUES (?, ?, ?)
    ''', (user.id, user.first_name, user.username))
    conn.commit()
    conn.close()
    
    if is_admin(user.id):
        keyboard = [
            [KeyboardButton("Рабочий режим")],
            [KeyboardButton("Админ-панель")]
        ]
        await update.message.reply_text(
            "Вы вошли как администратор. Выберите режим:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return ADMIN_MENU
    else:
        return await user_mode_start(update, context)

# Обработчик команды /admin
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ У вас нет прав администратора")
        return ConversationHandler.END
    
    await show_admin_menu(update, context)
    return ADMIN_MENU

# Режим пользователя
async def user_mode_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks(only_active=True)
    
    if not tasks:
        await update.message.reply_text("В настоящее время нет активных задач.")
        return ConversationHandler.END
    
    context.user_data['tasks'] = tasks
    context.user_data['current_task'] = 0
    
    keyboard = [
        [KeyboardButton("Задача выполнена")],
        [KeyboardButton("Пропустить задачу")]
    ]
    
    await update.message.reply_text(
        f"Добро пожаловать!\n\nВаша первая задача:\n1. {tasks[0][1]}",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return WAITING_PHOTO
# Админ-меню
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("Добавить задачу"), KeyboardButton("Редактировать задачи")],
        [KeyboardButton("Удалить задачу"), KeyboardButton("Статистика")],
        [KeyboardButton("📷 Просмотреть фото"), KeyboardButton("📝 Комментарии")],
        [KeyboardButton("⏸ Пропущенные задачи"), KeyboardButton("Рабочий режим")]  # Убрали лишний символ ️
    ]
    await update.message.reply_text(
        "⚙️ Админ-панель:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ADMIN_MENU
# Обработчик фото
async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.message.from_user
        file_id = None
        file_type = None
        
        if update.message.photo:
            photo_file = update.message.photo[-1]
            file_id = photo_file.file_id
            file_type = 'photo'
        elif update.message.video:
            video_file = update.message.video
            file_id = video_file.file_id
            file_type = 'video'
        else:
            await update.message.reply_text("Пожалуйста, отправьте фото или видео.")
            return WAITING_PHOTO

        tasks = context.user_data.get('tasks', [])
        current_task_idx = context.user_data.get('current_task', 0)
        
        if current_task_idx >= len(tasks):
            await update.message.reply_text("❌ Ошибка: задача не найдена.")
            return ConversationHandler.END
        
        task_id = tasks[current_task_idx][0]
        context.user_data['current_task_id'] = task_id

        db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''INSERT INTO completed_tasks 
            (user_id, task_id, telegram_file_id, file_type) 
            VALUES (?, ?, ?, ?)''',
            (user.id, task_id, file_id, file_type)
        )
        conn.commit()
        conn.close()

        keyboard = [
            [KeyboardButton("Пропустить комментарий")]
        ]
        await update.message.reply_text(
            "📝 Теперь добавьте комментарий к выполненной задаче (текст или голосовое):",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return WAITING_COMMENT

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")
        return WAITING_PHOTO

async def show_user_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT ct.telegram_file_id, ct.file_type, u.first_name, u.username, t.description, ct.completion_date
    FROM completed_tasks ct
    JOIN tasks t ON ct.task_id = t.id
    JOIN users u ON ct.user_id = u.id
    WHERE ct.telegram_file_id IS NOT NULL
    ORDER BY ct.completion_date DESC
    LIMIT 10
    ''')
    
    media_items = cursor.fetchall()
    conn.close()
    
    if not media_items:
        await update.message.reply_text("Нет отправленных медиафайлов.")
        return
    
    for item in media_items:
        try:
            file_id, file_type, first_name, username, description, completion_date = item
            
            if username:
                user_link = f"<a href='https://t.me/{username}'>{first_name}</a>"
            else:
                user_link = first_name
                
            caption = f"👤 {user_link}\n📝 {description}\n🕒 {completion_date}"
            
            if file_type == 'photo':
                await context.bot.send_photo(
                    chat_id=update.message.chat_id,
                    photo=file_id,
                    caption=caption,
                    parse_mode='HTML'
                )
            elif file_type == 'video':
                await context.bot.send_video(
                    chat_id=update.message.chat_id,
                    video=file_id,
                    caption=caption,
                    parse_mode='HTML'
                )
        except Exception as e:
            logger.error(f"Ошибка отправки медиа: {e}")
    
    await update.message.reply_text(
        "Загружены последние 10 медиафайлов",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Показать еще", callback_data="show_more_media")]
        ])
    )

async def handle_show_more_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    offset = context.user_data.get('media_offset', 10)
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT ct.telegram_file_id, ct.file_type, u.first_name, u.username, t.description, ct.completion_date
    FROM completed_tasks ct
    JOIN tasks t ON ct.task_id = t.id
    JOIN users u ON ct.user_id = u.id
    WHERE ct.telegram_file_id IS NOT NULL
    ORDER BY ct.completion_date DESC
    LIMIT 10 OFFSET ?
    ''', (offset,))
    
    media_items = cursor.fetchall()
    conn.close()
    
    if not media_items:
        await query.edit_message_text("Больше медиафайлов нет.")
        return
    
    for item in media_items:
        try:
            file_id, file_type, first_name, username, description, completion_date = item
            
            if username:
                user_link = f"<a href='https://t.me/{username}'>{first_name}</a>"
            else:
                user_link = first_name
                
            caption = f"👤 {user_link}\n📝 {description}\n🕒 {completion_date}"
            
            if file_type == 'photo':
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=file_id,
                    caption=caption,
                    parse_mode='HTML'
                )
            elif file_type == 'video':
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=file_id,
                    caption=caption,
                    parse_mode='HTML'
                )
        except Exception as e:
            logger.error(f"Ошибка отправки медиа: {e}")
    
    context.user_data['media_offset'] = offset + 10
    
    await query.edit_message_text(
        "Загружены следующие 10 медиафайлов",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Показать еще", callback_data="show_more_media")]
        ])
    )

async def show_comments_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks()
    
    if not tasks:
        await update.message.reply_text("Нет задач для просмотра.")
        await show_admin_menu(update, context)
        return ADMIN_MENU
    
    keyboard = []
    for task in tasks:
        keyboard.append([InlineKeyboardButton(
            f"{task[0]}. {task[1]}",
            callback_data=f"view_comments_{task[0]}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_admin")])
    
    await update.message.reply_text(
        "Выберите задачу для просмотра комментариев:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_MENU

async def handle_comments_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("view_comments_"):
        task_id = int(query.data.split("_")[2])
        db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT description FROM tasks WHERE id = ?', (task_id,))
        task_description = cursor.fetchone()[0]
        
        cursor.execute('''
        SELECT username, comment, voice_message_id, timestamp 
        FROM task_comments 
        WHERE task_id = ?
        ORDER BY timestamp DESC
        ''', (task_id,))
        comments = cursor.fetchall()
        conn.close()
        
        if not comments:
            await query.edit_message_text("Комментариев пока нет.")
            return
        
        comments_text = []
        for comment in comments:
            username, text_comment, voice_id, timestamp = comment
            if voice_id:
                # Отправляем голосовое сообщение
                await context.bot.send_voice(
                    chat_id=query.message.chat_id,
                    voice=voice_id,
                    caption=f"👤 {username}\n🕒 {timestamp.split('.')[0]}"
                )
                comments_text.append(f"👤 {username} (голосовое сообщение)")
            else:
                comments_text.append(
                    f"👤 {username}\n💬 {text_comment}\n🕒 {timestamp.split('.')[0]}"
                )
        
        await query.edit_message_text(
            f"📌 Задача: {task_description}\n\n"
            f"📝 Комментарии:\n\n" + "\n\n".join(comments_text),
            parse_mode='HTML'
        )

async def save_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    task_id = context.user_data.get('current_task_id')
    
    if not task_id:
        await update.message.reply_text("❌ Ошибка: задача не найдена.")
        return ConversationHandler.END
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if update.message.voice:
        voice_id = update.message.voice.file_id
        cursor.execute(
            '''INSERT INTO task_comments 
            (task_id, user_id, username, comment, voice_message_id) 
            VALUES (?, ?, ?, ?, ?)''',
            (task_id, user.id, user.username or user.first_name, None, voice_id)
        )
        await update.message.reply_text("🎤 Голосовой комментарий сохранён!")
    else:
        comment = update.message.text
        cursor.execute(
            '''INSERT INTO task_comments 
            (task_id, user_id, username, comment, voice_message_id) 
            VALUES (?, ?, ?, ?, ?)''',
            (task_id, user.id, user.username or user.first_name, comment, None)
        )
        await update.message.reply_text("📝 Текстовый комментарий сохранён!")
    
    conn.commit()
    conn.close()
    
    tasks = context.user_data.get('tasks', [])
    current_task_idx = context.user_data.get('current_task', 0)
    next_task_idx = current_task_idx + 1
    context.user_data['current_task'] = next_task_idx
    
    if next_task_idx < len(tasks):
        # Создаем клавиатуру для следующей задачи
        keyboard = [
            [KeyboardButton("Задача выполнена")],
            [KeyboardButton("Пропустить задачу")]
        ]
        await update.message.reply_text(
            f"✅ Спасибо за комментарий! Следующая задача:\n{next_task_idx + 1}. {tasks[next_task_idx][1]}",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return WAITING_PHOTO
    else:
        await update.message.reply_text(
            "🎉 Поздравляем! Вы выполнили все задачи!",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
        )
        return ConversationHandler.END

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите описание новой задачи:",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return ADD_TASK

async def save_new_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_description = update.message.text
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (description) VALUES (?)', (task_description,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ Задача добавлена: {task_description}")
    await show_admin_menu(update, context)
    return ADMIN_MENU

async def edit_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks()
    
    if not tasks:
        await update.message.reply_text("Нет задач для редактирования.")
        await show_admin_menu(update, context)
        return ADMIN_MENU
    
    tasks_text = "\n".join(
        f"{task[0]}. {task[1]} {'(активна)' if task[2] else '(неактивна)'}"
        for task in tasks
    )
    
    await update.message.reply_text(
        f"📝 Список задач:\n{tasks_text}\n\n"
        "Отправьте номер задачи и новый статус через пробел (например: '1 активна' или '2 неактивна'):",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return EDIT_TASK

async def skip_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = context.user_data.get('tasks', [])
    current_task_idx = context.user_data.get('current_task', 0)
    next_task_idx = current_task_idx + 1
    context.user_data['current_task'] = next_task_idx
    
    if next_task_idx < len(tasks):
        keyboard = [
            [KeyboardButton("Задача выполнена")],
            [KeyboardButton("Пропустить задачу")]
        ]
        await update.message.reply_text(
            f"✅ Комментарий пропущен. Следующая задача:\n{next_task_idx + 1}. {tasks[next_task_idx][1]}",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return WAITING_PHOTO
    else:
        await update.message.reply_text(
            "🎉 Поздравляем! Вы выполнили все задачи!",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
        )
        return ConversationHandler.END

async def save_task_changes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        task_id = int(text.split()[0])
        new_status = ' '.join(text.split()[1:]).lower()
        
        if new_status not in ['активна', 'неактивна']:
            raise ValueError
        
        db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM tasks WHERE id = ?', (task_id,))
        if not cursor.fetchone():
            await update.message.reply_text("❌ Задачи с таким ID не существует")
            return await show_admin_menu(update, context)
        
        cursor.execute(
            'UPDATE tasks SET is_active = ? WHERE id = ?',
            (1 if new_status == 'активна' else 0, task_id)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Статус задачи {task_id} изменен на '{new_status}'")
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Неверный формат. Пример: '1 активна' или '2 неактивна'")
    
    await show_admin_menu(update, context)
    return ADMIN_MENU

async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks()
    
    if not tasks:
        await update.message.reply_text("Нет задач для удаления.")
        await show_admin_menu(update, context)
        return ADMIN_MENU
    
    tasks_text = "\n".join(
        f"{task[0]}. {task[1]}"
        for task in tasks
    )
    
    await update.message.reply_text(
        f"🗑 Список задач для удаления:\n{tasks_text}\n\n"
        "Отправьте номер задачи для удаления:",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return DELETE_TASK

async def confirm_delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        task_id = int(update.message.text)
        
        db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT description FROM tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()
        
        if not task:
            await update.message.reply_text("❌ Задачи с таким ID не существует")
            return await show_admin_menu(update, context)
        
        cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Задача {task_id} удалена: {task[0]}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите номер задачи")
    
    await show_admin_menu(update, context)
    return ADMIN_MENU

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)   
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM completed_tasks')
    total_completed = cursor.fetchone()[0]
    
    cursor.execute('''
    SELECT t.description, COUNT(c.id) as completions 
    FROM tasks t
    LEFT JOIN completed_tasks c ON t.id = c.task_id
    GROUP BY t.id
    ORDER BY completions DESC
    ''')
    tasks_stats = cursor.fetchall()
    
    conn.close()
    
    stats_text = f"📊 Всего выполнено задач: {total_completed}\n\n"
    stats_text += "Статистика по задачам:\n"
    stats_text += "\n".join(
        f"{task[0]}: {task[1]} выполнений"
        for task in tasks_stats
    )
    
    await update.message.reply_text(stats_text)
    await show_admin_menu(update, context)
    return ADMIN_MENU

async def task_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Отправьте фото в качестве доказательства выполнения задачи "
        "или голосовое сообщение с комментарием.",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return WAITING_PHOTO

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет пользователю его Telegram ID"""
    user_id = update.message.from_user.id
    await update.message.reply_text(f"Ваш ID: {user_id}")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает текущий диалог"""
    user = update.message.from_user
    logger.info("Пользователь %s отменил действие.", user.first_name)
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return ConversationHandler.END

def check_db_structure():
    conn = None
    try:
        db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
        conn = sqlite3.connect(db_path)        
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(completed_tasks)")
        columns = [col[1] for col in cursor.fetchall()]
        required_columns = {'id', 'user_id', 'task_id', 'telegram_file_id', 'completion_date'}
        
        if not required_columns.issubset(columns):
            logger.error(f"Отсутствуют необходимые колонки. Имеющиеся: {columns}")
            return False
            
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка проверки БД: {e}")
        return False
    finally:
        if conn:
            conn.close()


def migrate_db():
    db_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(db_dir, exist_ok=True)  # Создаем папку если ее нет
    db_path = os.path.join(db_dir, 'tasks.db')
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Переименовываем старую таблицу
        cursor.execute('ALTER TABLE completed_tasks RENAME TO completed_tasks_old')
        
        # Создаем новую таблицу
        cursor.execute('''
        CREATE TABLE completed_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            telegram_file_id TEXT,
            completion_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        )
        ''')    
        
        # Переносим данные
        cursor.execute('''
        INSERT INTO completed_tasks (id, user_id, task_id, telegram_file_id, completion_date)
        SELECT id, user_id, task_id, photo_path, completion_date 
        FROM completed_tasks_old
        ''')
        
        # Удаляем старую таблицу
        cursor.execute('DROP TABLE completed_tasks_old')
        
        conn.commit()
        logger.info("Миграция базы данных успешно завершена")
        
    except sqlite3.Error as e:
        conn.rollback()
        logger.error(f"Ошибка миграции: {e}")
    finally:
        conn.close()
    
async def skip_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Укажите причину пропуска задачи текстом или голосовым сообщением:",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return SKIP_TASK
async def save_skip_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    tasks = context.user_data.get('tasks', [])
    current_task_idx = context.user_data.get('current_task', 0)
    
    if current_task_idx >= len(tasks):
        await update.message.reply_text("❌ Ошибка: задача не найдена.")
        return ConversationHandler.END
    
    task_id = tasks[current_task_idx][0]
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if update.message.voice:
        voice_id = update.message.voice.file_id
        cursor.execute(
            '''INSERT INTO skipped_tasks 
            (user_id, task_id, reason, voice_message_id) 
            VALUES (?, ?, ?, ?)''',
            (user.id, task_id, "Голосовое сообщение", voice_id)
        )
        await update.message.reply_text("🎤 Голосовая причина пропуска сохранена!")
    else:
        reason = update.message.text
        cursor.execute(
            '''INSERT INTO skipped_tasks 
            (user_id, task_id, reason, voice_message_id) 
            VALUES (?, ?, ?, ?)''',
            (user.id, task_id, reason, None)
        )
        await update.message.reply_text("📝 Текстовая причина пропуска сохранена!")
    
    conn.commit()
    conn.close()
    
    next_task_idx = current_task_idx + 1
    context.user_data['current_task'] = next_task_idx
    
    if next_task_idx < len(tasks):
        # Создаем клавиатуру для следующей задачи
        keyboard = [
            [KeyboardButton("Задача выполнена")],
            [KeyboardButton("Пропустить задачу")]
        ]
        await update.message.reply_text(
            f"✅ Причина пропуска сохранена. Следующая задача:\n{next_task_idx + 1}. {tasks[next_task_idx][1]}",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return WAITING_PHOTO
    else:
        await update.message.reply_text(
            "🎉 Вы завершили все задачи (некоторые были пропущены)!",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
        )
        return ConversationHandler.END

async def show_skipped_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'tasks.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT st.task_id, t.description, u.first_name, u.username, st.reason, st.voice_message_id, st.skip_date
    FROM skipped_tasks st
    JOIN tasks t ON st.task_id = t.id
    JOIN users u ON st.user_id = u.id
    ORDER BY st.skip_date DESC
    LIMIT 10
    ''')
    
    skipped_tasks = cursor.fetchall()
    conn.close()
    
    if not skipped_tasks:
        await update.message.reply_text("Нет пропущенных задач.")
        return
    
    for task in skipped_tasks:
        task_id, description, first_name, username, reason, voice_id, skip_date = task
        user_link = f"@{username}" if username else first_name
        
        if voice_id:  # Если есть голосовое сообщение
            await context.bot.send_voice(
                chat_id=update.message.chat_id,
                voice=voice_id,
                caption=f"⏸ Пропущена задача {task_id}: {description}\n👤 {user_link}\n📅 {skip_date}"
            )
        else:  # Текстовая причина
            await update.message.reply_text(
                f"⏸ Пропущена задача {task_id}: {description}\n"
                f"👤 {user_link}\n"
                f"📅 {skip_date}\n"
                f"📝 Причина: {reason}",
                parse_mode='HTML'
            )
def main():
    migrate_db()
    init_db()
    if not check_db_structure():
        logger.error("Проблема с структурой базы данных!")
        # Пересоздаем таблицы
        init_db()
        if not check_db_structure():
            logger.critical("Не удалось инициализировать БД!")
            return
        
    from config import BOT_TOKEN
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('admin', admin_command),
            CommandHandler('id', get_id)
        ],
        states={
            ADMIN_MENU: [
                MessageHandler(filters.Regex('^Админ-панель$'), show_admin_menu),
                MessageHandler(filters.Regex('^Добавить задачу$'), add_task),
                MessageHandler(filters.Regex('^Редактировать задачи$'), edit_tasks),
                MessageHandler(filters.Regex('^Удалить задачу$'), delete_task),
                MessageHandler(filters.Regex('^Статистика$'), show_stats),
                MessageHandler(filters.Regex('^📷 Просмотреть фото$'), show_user_photos),
                MessageHandler(filters.Regex('^📝 Комментарии$'), show_comments_menu),
                MessageHandler(filters.Regex('^Рабочий режим$'), user_mode_start),
                MessageHandler(filters.Regex('^⏸ Пропущенные задачи$'), show_skipped_tasks),
                CallbackQueryHandler(handle_show_more_media, pattern="^show_more_media$"),
                CallbackQueryHandler(handle_comments_callback)
            ],
            WAITING_PHOTO: [
                MessageHandler(filters.Regex('^Задача выполнена$'), task_done),
                MessageHandler(filters.Regex('^Пропустить задачу$'), skip_task),
                MessageHandler(filters.PHOTO | filters.VIDEO, receive_photo)
            ],
            SKIP_TASK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_skip_reason),
                MessageHandler(filters.VOICE, save_skip_reason)  # Добавляем обработку голосовых
            ],
              WAITING_COMMENT: [
                MessageHandler(filters.Regex('^Пропустить комментарий$'), skip_comment),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_comment),
                MessageHandler(filters.VOICE, save_comment)
            ],
            ADD_TASK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_task)
            ],
            EDIT_TASK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_task_changes)
            ],
            DELETE_TASK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_task)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    if not os.path.exists('photos'):    
        os.makedirs('photos')
    main()