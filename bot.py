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
from config import ADMIN_IDS, BOT_TOKEN
from telegram import InputMediaPhoto, InputMediaVideo

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния бота
(
    ADMIN_MENU, TRUCK_MENU, DRIVER_MENU, TASK_MENU, REPORT_MENU,
    ADD_TRUCK, LIST_TRUCKS, ASSIGN_DRIVER, ADD_TASK, EDIT_TASK, DELETE_TASK,
    VIEW_TRUCK_REPORTS, SELECT_TRUCK_FOR_ASSIGNMENT, SELECT_DRIVER_FOR_TRUCK, MANAGE_DRIVERS,
    DELETE_DRIVER, CONFIRM_DELETE_DRIVER, REVIEW_REPORTS, APPROVE_REPORT,
    MULTI_PHOTO_UPLOAD, WAITING_MORE_PHOTOS, TASK_PROOF, SKIP_REASON, TASK_COMMENT, 
    VIEW_TRUCK_REPORTS_DETAILS, TASK_DESCRIPTION, WAITING_COMMENT, DELETE_TRUCK, CONFIRM_DELETE_TRUCK
) = range(29)

def init_db():
    db_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(db_dir, exist_ok=True)
    
    db_path = os.path.join(db_dir, 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()


    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trucks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_number TEXT UNIQUE NOT NULL,
        model TEXT,
        year INTEGER,
        status TEXT DEFAULT 'active'
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS drivers (
        id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        current_truck_id INTEGER,
        status TEXT DEFAULT 'active',
        FOREIGN KEY(current_truck_id) REFERENCES trucks(id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS truck_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        frequency TEXT,
        is_active BOOLEAN DEFAULT 1,
        FOREIGN KEY(truck_id) REFERENCES trucks(id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS completed_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_id INTEGER NOT NULL,
        driver_id INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        telegram_file_id TEXT,
        file_type TEXT,
        completion_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending',
        skipped BOOLEAN DEFAULT FALSE,
        FOREIGN KEY(truck_id) REFERENCES trucks(id),
        FOREIGN KEY(driver_id) REFERENCES drivers(id),
        FOREIGN KEY(task_id) REFERENCES truck_tasks(id)
    )
    ''')
    cursor.execute("PRAGMA table_info(completed_checks)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'completion_date' not in columns:
        cursor.execute('''
            ALTER TABLE completed_checks
            ADD COLUMN completion_date DATETIME DEFAULT CURRENT_TIMESTAMP
        ''')
        logger.info("Добавлен столбец completion_date в таблицу completed_checks")
    
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS check_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        check_id INTEGER NOT NULL,
        driver_id INTEGER NOT NULL,
        comment TEXT,
        voice_message_id TEXT,
        type TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(check_id) REFERENCES completed_checks(id),
        FOREIGN KEY(driver_id) REFERENCES drivers(id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS report_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER NOT NULL,
        file_id TEXT NOT NULL,
        file_type TEXT NOT NULL,
        FOREIGN KEY(report_id) REFERENCES completed_checks(id)
    )
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_drivers_current_truck 
    ON drivers(current_truck_id)
    ''')

    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_trucks_status 
    ON trucks(status)
    ''')
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_trucks(only_active=True):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = 'SELECT id, truck_number, model FROM trucks'
    if only_active:
        query += " WHERE status = 'active'"
    query += ' ORDER BY truck_number'
    
    cursor.execute(query)
    trucks = cursor.fetchall()
    conn.close()
    return trucks

def get_drivers(only_active=True):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = 'SELECT id, first_name, username FROM drivers'
    if only_active:
        query += " WHERE status = 'active'"
    query += ' ORDER BY first_name'
    
    cursor.execute(query)
    drivers = cursor.fetchall()
    conn.close()
    return drivers

def get_truck_tasks(truck_id, only_active=True):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = 'SELECT id, description, is_active FROM truck_tasks WHERE truck_id = ?'
    if only_active:
        query += ' AND is_active = 1'
    query += ' ORDER BY id'
    
    cursor.execute(query, (truck_id,))
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def get_driver_tasks(driver_id):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT tt.id, tt.description, t.truck_number 
    FROM truck_tasks tt
    JOIN trucks t ON tt.truck_id = t.id
    JOIN drivers d ON t.id = d.current_truck_id
    WHERE d.id = ? 
      AND tt.is_active = 1 
      AND t.status = 'active'
      AND d.status = 'active'
    ORDER BY tt.id
    ''', (driver_id,))
    
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def get_pending_reports():
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT cc.id, t.truck_number, d.first_name, tt.description, cc.completion_date
    FROM completed_checks cc
    JOIN trucks t ON cc.truck_id = t.id
    JOIN drivers d ON cc.driver_id = d.id
    JOIN truck_tasks tt ON cc.task_id = tt.id
    WHERE cc.status = 'pending'
    ORDER BY cc.completion_date DESC
    LIMIT 10
    ''')
    
    reports = cursor.fetchall()
    conn.close()
    return reports

def get_report_media(report_id):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT file_id, file_type FROM report_media
    WHERE report_id = ?
    ORDER BY id
    ''', (report_id,))
    
    media = cursor.fetchall()
    conn.close()
    return media

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"User {user.id} started the bot")
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT current_truck_id FROM drivers WHERE id = ?', (user.id,))
            result = cursor.fetchone()
            current_truck_id = result[0] if result else None
            
            cursor.execute('''
                INSERT OR REPLACE INTO drivers 
                (id, first_name, username, current_truck_id, status)
                VALUES (?, ?, ?, ?, 'active')
            ''', (user.id, user.first_name, user.username, current_truck_id))
            
            conn.commit()

    except sqlite3.OperationalError as e:
        logger.error(f"Database error: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка базы данных. Попробуйте снова через минуту.")
        return ConversationHandler.END
    
    context.user_data.clear()
    
    if is_admin(user.id):
        return await show_admin_menu(update, context)
    else:
        return await show_driver_menu(update, context)

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("🚛 Управление фурами"), KeyboardButton("👤 Управление водителями")],
        [KeyboardButton("📋 Управление задачами"), KeyboardButton("📊 Просмотр отчетов")],
        [KeyboardButton("🔙 Выход")]
    ]
    
    if update.message:
        await update.message.reply_text(
            "⚙️ Админ-панель:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "⚙️ Админ-панель:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
    
    return ADMIN_MENU

async def show_truck_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("➕ Добавить фуру"), KeyboardButton("📋 Список фур")],
        [KeyboardButton("👥 Назначить водителя"), KeyboardButton("🗑 Удалить фуру")],
        [KeyboardButton("🔙 Назад")]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(
            "🚛 Управление фурами:",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.message.reply_text(
            "🚛 Управление фурами:",
            reply_markup=reply_markup
        )
    
    return TRUCK_MENU

async def delete_truck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trucks = get_trucks()
    if not trucks:
        await update.message.reply_text("Нет зарегистрированных фур")
        return TRUCK_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{truck[1]} ({truck[2]})", callback_data=f"delete_truck_{truck[0]}")]
        for truck in trucks
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_truck_menu")])
    
    await update.message.reply_text(
        "Выберите фуру для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DELETE_TRUCK

async def confirm_truck_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_truck_menu":
        await show_truck_menu(update, context)
        return TRUCK_MENU
    
    truck_id = int(query.data.split('_')[-1])
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_truck_delete_{truck_id}")],
        [InlineKeyboardButton("❌ Нет, отменить", callback_data="back_to_truck_menu")]
    ]
    
    await query.edit_message_text(
        "⚠️ Вы уверены, что хотите удалить эту фуру? Все связанные задачи также будут удалены.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_DELETE_TRUCK

async def complete_truck_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    truck_id = int(query.data.split('_')[-1])
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Получаем информацию о фуре перед удалением
        cursor.execute('SELECT truck_number, model FROM trucks WHERE id = ?', (truck_id,))
        truck_info = cursor.fetchone()
        
        if not truck_info:
            await query.edit_message_text("❌ Фура не найдена")
            return TRUCK_MENU
        
        # Удаляем связанные задачи
        cursor.execute('DELETE FROM truck_tasks WHERE truck_id = ?', (truck_id,))
        
        # Обнуляем current_truck_id у водителей
        cursor.execute('''
            UPDATE drivers 
            SET current_truck_id = NULL 
            WHERE current_truck_id = ?
        ''', (truck_id,))
        
        # Удаляем саму фуру
        cursor.execute('DELETE FROM trucks WHERE id = ?', (truck_id,))
        
        conn.commit()
        
        await query.edit_message_text(
            f"✅ Фура {truck_info[0]} ({truck_info[1]}) и все связанные задачи удалены")
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка при удалении фуры: {e}")
        await query.edit_message_text("❌ Произошла ошибка при удалении фуры")
    finally:
        conn.close()
    
    await show_truck_menu(update, context)
    return TRUCK_MENU

async def show_driver_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT t.truck_number, t.model 
    FROM trucks t
    JOIN drivers d ON t.id = d.current_truck_id
    WHERE d.id = ? 
      AND d.status = 'active' 
      AND t.status = 'active'
    ''', (user_id,))
    
    truck = cursor.fetchone()
    conn.close()
    
    if not truck:
        await update.message.reply_text("❌ Вам не назначена фура. Обратитесь к администратору.")
        return ConversationHandler.END
    
    tasks = get_driver_tasks(user_id)
    if not tasks:
        await update.message.reply_text("✅ Все задачи выполнены!")
        return ConversationHandler.END
    
    tasks_list = "\n".join([f"• {task[1]}" for task in tasks])
    await update.message.reply_text(
        f"🚛 Фура: {truck[0]} ({truck[1]})\n\nАктивные задачи:\n{tasks_list}",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📸 Начать отчет")]], resize_keyboard=True)
    )
    return DRIVER_MENU

async def show_task_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("📋 Список задач"), KeyboardButton("➕ Добавить задачу")],
        [KeyboardButton("✏️ Редактировать задачи"), KeyboardButton("🗑 Удалить задачи")],
        [KeyboardButton("🔙 Назад")]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(
            "📋 Управление задачами:",
            reply_markup=reply_markup
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            "📋 Управление задачами:",
            reply_markup=reply_markup
        )
    
    return TASK_MENU

async def show_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("📊 Отчеты по фурам")],
        [KeyboardButton("🔙 Назад")]
    ]
    
    await update.message.reply_text(
        "📊 Просмотр отчетов:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return REPORT_MENU

async def show_driver_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("📋 Список водителей"), KeyboardButton("🚛 Назначить фуру")],
        [KeyboardButton("🗑 Удалить водителя"), KeyboardButton("🔙 Назад")]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(
            "👤 Управление водителями:",
            reply_markup=reply_markup
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.message.reply_text(
            "👤 Управление водителями:",
            reply_markup=reply_markup
        )
    
    return DRIVER_MENU

async def add_truck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите номер и модель фуры через запятую (например, А123БВ, Volvo FH16):",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return ADD_TRUCK

async def save_truck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split(',')
        if len(parts) < 2:
            raise ValueError("Неверный формат. Введите номер и модель через запятую.")
            
        truck_number = parts[0].strip()
        model = parts[1].strip()
        
        db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM trucks WHERE truck_number = ?', (truck_number,))
        if cursor.fetchone():
            await update.message.reply_text("❌ Фура с таким номером уже существует")
            conn.close()
            return TRUCK_MENU
        
        cursor.execute(
            'INSERT INTO trucks (truck_number, model) VALUES (?, ?)',
            (truck_number, model)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ Фура {truck_number} ({model}) успешно добавлена",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
        )
        return TRUCK_MENU
        
    except Exception as e:
        logger.error(f"Error saving truck: {e}")
        await update.message.reply_text(
            "❌ Ошибка при добавлении фуры. Убедитесь, что данные введены правильно.",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
        )
        return TRUCK_MENU

async def list_trucks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trucks = get_trucks()
    if not trucks:
        await update.message.reply_text("Нет зарегистрированных фур.")
        return TRUCK_MENU
    
    trucks_list = "\n".join([f"{truck[1]} ({truck[2]})" for truck in trucks])
    await update.message.reply_text(
        f"Список фур:\n\n{trucks_list}",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
    )
    return TRUCK_MENU

async def assign_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        trucks = get_trucks()
        if not trucks:
            if update.message:
                await update.message.reply_text("Нет зарегистрированных фур")
            elif update.callback_query:
                await update.callback_query.answer("Нет зарегистрированных фур")
            return TRUCK_MENU
        
        keyboard = [
            [InlineKeyboardButton(f"{truck[1]} ({truck[2]})", callback_data=f"assign_truck_{truck[0]}")]
            for truck in trucks
        ]
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_truck_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(
                "Выберите фуру для назначения водителя:",
                reply_markup=reply_markup
            )
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "Выберите фуру для назначения водителя:",
                reply_markup=reply_markup
            )
        
        return SELECT_TRUCK_FOR_ASSIGNMENT
        
    except Exception as e:
        logger.error(f"Error in assign_driver: {e}")
        if update.message:
            await update.message.reply_text("❌ Произошла ошибка при выборе фуры")
        elif update.callback_query:
            await update.callback_query.answer("❌ Ошибка при выборе фуры", show_alert=True)
        return TRUCK_MENU

async def select_driver_for_truck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
        
        if query.data == "back_to_truck_menu":
            await show_truck_menu(update, context)
            return TRUCK_MENU
        
        truck_id = int(query.data.split('_')[-1])
        context.user_data['truck_menu_assign_truck_id'] = truck_id
        
        drivers = get_drivers()
        if not drivers:
            await query.edit_message_text("Нет зарегистрированных водителей.")
            return SELECT_TRUCK_FOR_ASSIGNMENT
        
        keyboard = [
            [InlineKeyboardButton(f"{driver[1]} (@{driver[2]})", callback_data=f"assign_driver_{driver[0]}")]
            for driver in drivers
        ]
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_assign")])
        
        await query.edit_message_text(
            "Выберите водителя для назначения на эту фуру:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECT_DRIVER_FOR_TRUCK
        
    except Exception as e:
        logger.error(f"Error in select_driver_for_truck: {e}")
        await query.answer("❌ Произошла ошибка", show_alert=True)
        return SELECT_TRUCK_FOR_ASSIGNMENT

async def confirm_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
        
        if query.data == "back_to_assign":
            return await assign_driver(update, context)
        
        driver_id = int(query.data.split('_')[-1])
        truck_id = context.user_data.get('truck_menu_assign_truck_id')
        
        if not truck_id:
            raise KeyError("Не найден ID фуры")
        
        db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE drivers 
            SET current_truck_id = ?, 
                status = 'active' 
            WHERE id = ?
        ''', (truck_id, driver_id))

        cursor.execute('''
            UPDATE trucks 
            SET status = 'active' 
            WHERE id = ?
        ''', (truck_id,))
        
        cursor.execute('SELECT truck_number, model FROM trucks WHERE id = ?', (truck_id,))
        truck = cursor.fetchone()
        
        cursor.execute('SELECT first_name, username FROM drivers WHERE id = ?', (driver_id,))
        driver = cursor.fetchone()
        
        conn.commit()
        conn.close()
        
        await query.edit_message_text(
            f"✅ Водитель {driver[0]} (@{driver[1]}) назначен на фуру {truck[0]} ({truck[1]})"
        )
        
        if 'truck_menu_assign_truck_id' in context.user_data:
            del context.user_data['truck_menu_assign_truck_id']
            
        await show_truck_menu(update, context)
        return TRUCK_MENU
        
    except Exception as e:
        logger.error(f"Error in confirm_assignment: {e}")
        await query.answer("❌ Ошибка при назначении", show_alert=True)
        return SELECT_DRIVER_FOR_TRUCK

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trucks = get_trucks()
    if not trucks:
        await update.message.reply_text("Нет зарегистрированных фур")
        return TASK_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{truck[1]} ({truck[2]})", callback_data=f"add_task_{truck[0]}")]
        for truck in trucks
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_task_menu")])
    
    await update.message.reply_text(
        "Выберите фуру для добавления задачи:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADD_TASK

async def handle_truck_selection_for_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_task_menu":
        await show_task_menu(update, context)
        return TASK_MENU
    
    truck_id = int(query.data.split('_')[-1])
    context.user_data['task_truck_id'] = truck_id
    
    try:
        await query.edit_message_text(
            "Введите описание задачи для этой фуры:",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await query.message.reply_text(
            "Введите описание задачи для этой фуры:",
            reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
        )
    
    return TASK_DESCRIPTION

async def save_task_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    truck_id = context.user_data['task_truck_id']
    description = update.message.text
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute(
        'INSERT INTO truck_tasks (truck_id, description) VALUES (?, ?)',
        (truck_id, description)
    )
    conn.commit()
    
    cursor.execute('SELECT truck_number FROM trucks WHERE id = ?', (truck_id,))
    truck_number = cursor.fetchone()[0]
    conn.close()
    
    await update.message.reply_text(
        f"✅ Задача для фуры {truck_number} добавлена: {description}",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
    )
    return TASK_MENU

async def edit_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trucks = get_trucks()
    if not trucks:
        await update.message.reply_text("Нет зарегистрированных фур")
        return TASK_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{truck[1]} ({truck[2]})", callback_data=f"edit_truck_{truck[0]}")]
        for truck in trucks
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_task_menu")])
    
    await update.message.reply_text(
        "Выберите фуру для редактирования задач:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDIT_TASK

async def handle_truck_selection_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_task_menu":
        await show_task_menu(update, context)
        return TASK_MENU
    
    truck_id = int(query.data.split('_')[-1])
    tasks = get_truck_tasks(truck_id, only_active=False)
    
    if not tasks:
        await query.edit_message_text("У этой фуры нет задач для редактирования.")
        return TASK_MENU
    
    keyboard = []
    for task in tasks:
        status = "✅" if task[2] else "❌"
        keyboard.append([InlineKeyboardButton(
            f"{task[0]}. {status} {task[1]}",
            callback_data=f"edit_task_{task[0]}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_edit_menu")])
    
    await query.edit_message_text(
        "Выберите задачу для редактирования:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDIT_TASK

async def edit_task_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_edit_menu":
        return await edit_tasks(update, context)
    
    task_id = int(query.data.split('_')[-1])
    context.user_data['edit_task_id'] = task_id
    
    keyboard = [
        [InlineKeyboardButton("Активировать", callback_data="set_active_1")],
        [InlineKeyboardButton("Деактивировать", callback_data="set_active_0")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_edit_menu")]
    ]
    
    await query.edit_message_text(
        "Выберите новый статус задачи:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDIT_TASK

async def save_task_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_edit_menu":
        return await edit_tasks(update, context)
    
    task_id = context.user_data['edit_task_id']
    new_status = int(query.data.split('_')[-1])
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute(
        'UPDATE truck_tasks SET is_active = ? WHERE id = ?',
        (new_status, task_id)
    )
    conn.commit()
    
    cursor.execute('SELECT description FROM truck_tasks WHERE id = ?', (task_id,))
    task_description = cursor.fetchone()[0]
    conn.close()
    
    status_text = "активна" if new_status else "неактивна"
    await query.edit_message_text(
        f"✅ Статус задачи '{task_description}' изменен на '{status_text}'")
    
    await show_task_menu(update, context)
    return TASK_MENU

async def delete_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trucks = get_trucks()
    if not trucks:
        await update.message.reply_text("Нет зарегистрированных фур")
        return TASK_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{truck[1]} ({truck[2]})", callback_data=f"delete_truck_{truck[0]}")]
        for truck in trucks
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_task_menu")])
    
    await update.message.reply_text(
        "Выберите фуру для удаления задач:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DELETE_TASK

async def handle_truck_selection_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_task_menu":
        await show_task_menu(update, context)
        return TASK_MENU
    
    truck_id = int(query.data.split('_')[-1])
    tasks = get_truck_tasks(truck_id, only_active=False)
    
    if not tasks:
        await query.edit_message_text("У этой фуры нет задач для удаления.")
        return TASK_MENU
    
    keyboard = []
    for task in tasks:
        keyboard.append([InlineKeyboardButton(
            f"{task[0]}. {task[1]}",
            callback_data=f"delete_task_{task[0]}")
        ])
    
    keyboard.append([InlineKeyboardButton("🗑 Удалить ВСЕ задачи", callback_data=f"delete_all_{truck_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_delete_menu")])
    
    await query.edit_message_text(
        "Выберите задачу для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DELETE_TASK

async def confirm_task_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_delete_menu":
        return await delete_tasks(update, context)
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    if query.data.startswith("delete_all_"):
        truck_id = int(query.data.split('_')[-1])
        cursor.execute('DELETE FROM truck_tasks WHERE truck_id = ?', (truck_id,))
        cursor.execute('SELECT truck_number FROM trucks WHERE id = ?', (truck_id,))
        truck_number = cursor.fetchone()[0]
        await query.edit_message_text(f"✅ Все задачи для фуры {truck_number} удалены")
    else:
        task_id = int(query.data.split('_')[-1])
        cursor.execute('SELECT description FROM truck_tasks WHERE id = ?', (task_id,))
        task_description = cursor.fetchone()[0]
        cursor.execute('DELETE FROM truck_tasks WHERE id = ?', (task_id,))
        await query.edit_message_text(f"✅ Задача удалена: {task_description}")
    
    conn.commit()
    conn.close()
    
    await show_task_menu(update, context)
    return TASK_MENU

async def view_truck_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trucks = get_trucks()
    if not trucks:
        await update.message.reply_text("Нет зарегистрированных фур.")
        return REPORT_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{truck[1]} ({truck[2]})", callback_data=f"view_truck_{truck[0]}")] 
        for truck in trucks
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_report_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(
            "Выберите фуру для просмотра отчетов:",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.message.reply_text(
            "Выберите фуру для просмотра отчетов:",
            reply_markup=reply_markup
        )
    
    return VIEW_TRUCK_REPORTS

async def show_truck_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"Callback data: {query.data}")
    
    truck_id = int(query.data.split('_')[-1])
    context.user_data['current_truck_id'] = truck_id
    context.user_data['report_offset'] = 0

    await show_reports_page(update, context)
    return VIEW_TRUCK_REPORTS_DETAILS

async def show_full_comment(update: Update, context: ContextTypes.DEFAULT_TYPE, report_id: int):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT 
        cc.comment,
        cc.voice_message_id,
        strftime('%d.%m.%Y %H:%M', cc.timestamp, '+6 hours') as formatted_date
    FROM check_comments cc
    WHERE cc.check_id = ? AND type = 'comment'
    ''', (report_id,))
    
    comment_data = cursor.fetchone()
    conn.close()
    
    if not comment_data:
        await update.callback_query.answer("Комментарий не найден")
        return
    
    message_text = f"💬 Комментарий от {comment_data[2]}:\n\n"
    
    if comment_data[0]:
        message_text += f"📝 Текст: {comment_data[0]}"
    elif comment_data[1]:
        message_text += "🎤 Голосовое сообщение"
    
    if comment_data[1]:
        await context.bot.send_voice(
            chat_id=update.effective_chat.id,
            voice=comment_data[1]
        )

async def show_skip_details(update: Update, context: ContextTypes.DEFAULT_TYPE, report_id: int):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT 
        cc.comment,
        cc.voice_message_id,
        strftime('%d.%m.%Y %H:%M', cc.timestamp, '+6 hours') as formatted_date,
        d.username
    FROM check_comments cc
    JOIN drivers d ON cc.driver_id = d.id
    WHERE cc.check_id = ? AND type = 'skip_reason'
    ''', (report_id,))
    
    skip_data = cursor.fetchone()
    conn.close()
    
    if not skip_data:
        await update.callback_query.answer("Причина пропуска не указана")
        return
    
    message_text = (
        f"⏭ Причина пропуска от @{skip_data[3]} ({skip_data[2]}):\n\n"
        f"{skip_data[0] if skip_data[0] else '🎤 Голосовое сообщение'}"
    )
    
    if skip_data[1]:
        await context.bot.send_voice(
            chat_id=update.effective_chat.id,
            voice=skip_data[1]
        )

def has_comment(report_id):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT EXISTS(
        SELECT 1 FROM check_comments 
        WHERE check_id = ? AND type = 'comment'
    )
    ''', (report_id,))
    result = cursor.fetchone()[0]
    conn.close()
    return bool(result)

def has_skip_reason(report_id):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT EXISTS(
        SELECT 1 FROM check_comments 
        WHERE check_id = ? AND type = 'skip_reason'
    )
    ''', (report_id,))
    result = cursor.fetchone()[0]
    conn.close()
    return bool(result)

async def show_reports_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    truck_id = context.user_data['current_truck_id']
    offset = context.user_data.get('report_offset', 0)
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT 
        cc.id, 
        t.truck_number,
        d.first_name,
        d.username,
        tt.description,
        strftime('%d.%m.%Y %H:%M', cc.completion_date, '+6 hours') as formatted_date,
        cc.status,
        cc.skipped
    FROM completed_checks cc
    JOIN trucks t ON cc.truck_id = t.id
    JOIN drivers d ON cc.driver_id = d.id
    JOIN truck_tasks tt ON cc.task_id = tt.id
    WHERE cc.truck_id = ?
    ORDER BY tt.id DESC, cc.completion_date DESC
    LIMIT 5 OFFSET ?
    ''', (truck_id, offset))
    
    reports = cursor.fetchall()

    reports_data = []
    for report in reports:
        report_id = report[0]
        
        cursor.execute('''
        SELECT 
            type,
            comment,
            voice_message_id,
            strftime('%d.%m.%Y %H:%M', timestamp, '+6 hours') as formatted_date
        FROM check_comments
        WHERE check_id = ?
        ''', (report_id,))
        
        comments = {
            'comment': [],
            'skip_reason': []
        }
        
        for comment in cursor.fetchall():
            comment_type = comment[0]
            text = comment[1]
            voice = comment[2]
            timestamp = comment[3]
            
            if comment_type == 'comment':
                comments['comment'].append({
                    'text': text,
                    'voice': voice,
                    'time': timestamp
                })
            elif comment_type == 'skip_reason':
                comments['skip_reason'].append({
                    'text': text,
                    'voice': voice,
                    'time': timestamp
                })
        
        reports_data.append({
            'info': report,
            'comments': comments
        })
    
    conn.close()

    for report in reports_data:
        report_info = report['info']
        comments = report['comments']
        report_id = report_info[0]
        
        caption = (
            f"🚛 Фура: {report_info[1]}\n"
            f"👤 Водитель: {report_info[2]} (@{report_info[3]})\n"
            f"📌 Задача: {report_info[4]}\n"
            f"🕒 Время проверки: {report_info[5]}\n"
            f"🔮 Статус: {report_info[6].capitalize()}\n"
        )
        
        if comments['comment']:
            caption += "\n💬 Комментарии:\n"
            for idx, comment in enumerate(comments['comment'], 1):
                if comment['text']:
                    caption += f"{idx}. 📝 {comment['text']} ({comment['time']})\n"
                elif comment['voice']:
                    caption += f"{idx}. 🎧 Голосовой комментарий ({comment['time']})\n"
        
        if comments['skip_reason']:
            caption += "\n⏭ Причины пропуска:\n"
            for idx, reason in enumerate(comments['skip_reason'], 1):
                if reason['text']:
                    caption += f"{idx}. 📝 {reason['text']} ({reason['time']})\n"
                elif reason['voice']:
                    caption += f"{idx}. 🎧 Голосовое объяснение ({reason['time']})\n"

        media = get_report_media(report_id)
        
        if media:
            media_group = []
            for idx, media_item in enumerate(media):
                if idx == 0:
                    media_group.append(InputMediaPhoto(media=media_item[0], caption=caption) if media_item[1] == 'photo' else InputMediaVideo(media=media_item[0], caption=caption))
                else:
                    media_group.append(InputMediaPhoto(media=media_item[0]) if media_item[1] == 'photo' else InputMediaVideo(media=media_item[0]))
            
            await context.bot.send_media_group(
                chat_id=update.effective_chat.id,
                media=media_group
            )
            
        for comment_type in ['comment', 'skip_reason']:
            for comment in comments[comment_type]:
                if comment['voice']:
                    await context.bot.send_voice(
                        chat_id=update.effective_chat.id,
                        voice=comment['voice'],
                        caption=f"🎧 {comment_type.replace('_', ' ').capitalize()} ({comment['time']})"
                    )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=caption
            )

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Предыдущие", callback_data="prev_page"))
    if len(reports) == 5:
        nav_buttons.append(InlineKeyboardButton("Следующие ➡️", callback_data="next_page"))
    
    if nav_buttons:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Листать отчеты:",
            reply_markup=InlineKeyboardMarkup([nav_buttons])
        )

    return VIEW_TRUCK_REPORTS_DETAILS

async def show_single_report(update: Update, context: ContextTypes.DEFAULT_TYPE, report_id: int):
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT 
        cc.id, 
        t.truck_number,
        d.first_name,
        d.username,
        tt.description,
        strftime('%d.%m.%Y %H:%M', cc.completion_date, '+6 hours') as formatted_date,
        cc.status,
        cc.skipped
    FROM completed_checks cc
    JOIN trucks t ON cc.truck_id = t.id
    JOIN drivers d ON cc.driver_id = d.id
    JOIN truck_tasks tt ON cc.task_id = tt.id
    WHERE cc.id = ?
    ''', (report_id,))
    
    report = cursor.fetchone()
    conn.close()

    if not report:
        await update.callback_query.answer("Отчет не найден")
        return

    media = get_report_media(report_id)
    caption = (
        f"🚛 Фура: {report[1]}\n"
        f"👤 Водитель: {report[2]} (@{report[3]})\n"
        f"📌 Задача: {report[4]}\n"
        f"🕒 Время проверки: {report[5]}\n"
        f"🔮 Статус: {report[6].capitalize()}"
    )

    keyboard = []
    if has_comment(report_id):
        keyboard.append(InlineKeyboardButton("💬 Показать комментарий", callback_data=f"comment_{report_id}"))
    if report[7]:
        keyboard.append(InlineKeyboardButton("⏭ Причина пропуска", callback_data=f"skip_reason_{report_id}"))
    
    keyboard.append([InlineKeyboardButton("🔙 К списку отчетов", callback_data="back_to_reports")])

    if media:
        media_group = []
        for idx, media_item in enumerate(media):
            if idx == 0:
                media_group.append(InputMediaPhoto(media=media_item[0], caption=caption) if media_item[1] == 'photo' else InputMediaVideo(media=media_item[0], caption=caption))
            else:
                media_group.append(InputMediaPhoto(media=media_item[0]) if media_item[1] == 'photo' else InputMediaVideo(media=media_item[0]))
        
        await context.bot.send_media_group(
            chat_id=update.effective_chat.id,
            media=media_group
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption
        )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Дополнительные действия:",
        reply_markup=InlineKeyboardMarkup([keyboard])
    )
    return VIEW_TRUCK_REPORTS_DETAILS

async def handle_report_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_reports":
        await show_reports_page(update, context)
        return VIEW_TRUCK_REPORTS_DETAILS
    
    if query.data in ["prev_page", "next_page"]:
        if query.data == "prev_page":
            context.user_data['report_offset'] = max(0, context.user_data['report_offset'] - 5)
        else:
            context.user_data['report_offset'] += 5
        
        await show_reports_page(update, context)
    
    return VIEW_TRUCK_REPORTS_DETAILS

async def review_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reports = get_pending_reports()
    if not reports:
        await update.message.reply_text("Нет отчетов, ожидающих проверки.")
        return REPORT_MENU
    
    keyboard = []
    for report in reports:
        keyboard.append([InlineKeyboardButton(
            f"{report[4].split('.')[0]} - {report[1]} - {report[3]}",
            callback_data=f"review_report_{report[0]}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_report_menu")])
    
    await update.message.reply_text(
        "Отчеты, ожидающие проверки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REVIEW_REPORTS

async def show_report_for_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_report_menu":
        await show_report_menu(update, context)
        return REPORT_MENU
    
    report_id = int(query.data.split('_')[-1])
    context.user_data['review_report_id'] = report_id
    
    media = get_report_media(report_id)
    if not media:
        await query.edit_message_text("Нет медиафайлов для этого отчета.")
        return
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT 
        t.truck_number,
        d.first_name,
        d.username,
        tt.description,
        cc.completion_date,
        cc.skipped,
        cc_skip.comment AS skip_reason_text,
        cc_skip.voice_message_id AS skip_reason_voice,
        cc_comment.comment AS comment_text,
        cc_comment.voice_message_id AS comment_voice
    FROM completed_checks cc
    JOIN trucks t ON cc.truck_id = t.id
    JOIN drivers d ON cc.driver_id = d.id
    JOIN truck_tasks tt ON cc.task_id = tt.id
    LEFT JOIN check_comments cc_skip 
        ON cc.id = cc_skip.check_id AND cc_skip.type = 'skip_reason'
    LEFT JOIN check_comments cc_comment 
        ON cc.id = cc_comment.check_id AND cc_comment.type = 'comment'
    WHERE cc.id = ?
    ''', (report_id,))
    
    report_info = cursor.fetchone()
    conn.close()
    
    if not report_info:
        await query.edit_message_text("Отчет не найден")
        return

    caption = (
        f"🚛 Фура: {report_info[0]}\n"
        f"👤 Водитель: {report_info[1]} (@{report_info[2]})\n"
        f"📝 Проверка: {report_info[3]}\n"
        f"🕒 Дата: {report_info[4].split('.')[0]}"
    )
    
    first_media = media[0]
    if first_media[1] == 'photo':
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=first_media[0],
            caption=caption
        )
    elif first_media[1] == 'video':
        await context.bot.send_video(
            chat_id=query.message.chat_id,
            video=first_media[0],
            caption=caption
        )
    
    for media_item in media[1:]:
        if media_item[1] == 'photo':
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=media_item[0]
            )
        elif media_item[1] == 'video':
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=media_item[0]
            )
    
    keyboard = [
        [InlineKeyboardButton("✅ Одобрить", callback_data="approve_report"),
         InlineKeyboardButton("❌ Отклонить", callback_data="reject_report")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_review")]
    ]
    
    await query.edit_message_text(
        "Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return APPROVE_REPORT

async def handle_report_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_review":
        return await review_reports(update, context)
    
    report_id = context.user_data['review_report_id']
    status = 'approved' if query.data == 'approve_report' else 'rejected'
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute(
        'UPDATE completed_checks SET status = ? WHERE id = ?',
        (status, report_id)
    )
    
    cursor.execute('''
    SELECT d.id, t.truck_number, tt.description
    FROM completed_checks cc
    JOIN drivers d ON cc.driver_id = d.id
    JOIN trucks t ON cc.truck_id = t.id
    JOIN truck_tasks tt ON cc.task_id = tt.id
    WHERE cc.id = ?
    ''', (report_id,))
    
    driver_id, truck_number, task_description = cursor.fetchone()
    conn.commit()
    conn.close()
    
    status_text = "одобрен" if status == 'approved' else "отклонен"
    await query.edit_message_text(f"Отчет по {truck_number} ({task_description}) {status_text}")
    
    try:
        await context.bot.send_message(
            chat_id=driver_id,
            text=f"Ваш отчет по фуре {truck_number} ({task_description}) был {status_text} администратором."
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить водителя {driver_id}: {e}")
    
    return await review_reports(update, context)

async def list_drivers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    drivers = get_drivers()
    if not drivers:
        await update.message.reply_text("Нет зарегистрированных водителей.")
        return DRIVER_MENU
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    drivers_list = []
    for driver in drivers:
        cursor.execute('''
            SELECT t.truck_number 
            FROM trucks t
            JOIN drivers d ON t.id = d.current_truck_id
            WHERE d.id = ?
        ''', (driver[0],))
        truck = cursor.fetchone()
        truck_info = f"🚛 {truck[0]}" if truck else "🚫 Без фуры"
        drivers_list.append(f"{driver[1]} (@{driver[2]}) - {truck_info}")
    
    conn.close()
    
    await update.message.reply_text(
        "Список водителей:\n\n" + "\n".join(drivers_list),
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
    )
    return DRIVER_MENU

async def delete_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    drivers = get_drivers()
    if not drivers:
        await update.message.reply_text("Нет зарегистрированных водителей.")
        return DRIVER_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{driver[1]} (@{driver[2]})", callback_data=f"delete_driver_{driver[0]}")]
        for driver in drivers
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_driver_menu")])
    
    await update.message.reply_text(
        "Выберите водителя для удаления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DELETE_DRIVER

async def assign_truck_to_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    drivers = get_drivers()
    if not drivers:
        await update.message.reply_text("Нет зарегистрированных водителей.")
        return DRIVER_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{driver[1]} (@{driver[2]})", callback_data=f"select_driver_{driver[0]}")]
        for driver in drivers
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_driver_menu")])
    
    message = await update.message.reply_text(
        "Выберите водителя для назначения фуры:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['last_message_id'] = message.message_id
    return SELECT_DRIVER_FOR_TRUCK

async def select_truck_for_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_driver_menu":
        await show_driver_management(update, context)
        return DRIVER_MENU
    
    driver_id = int(query.data.split('_')[-1])
    context.user_data['assign_driver_id'] = driver_id
    
    trucks = get_trucks()
    if not trucks:
        await query.edit_message_text("Нет доступных фур для назначения.")
        return DRIVER_MENU
    
    keyboard = [
        [InlineKeyboardButton(f"{truck[1]} ({truck[2]})", callback_data=f"assign_truck_{truck[0]}")]
        for truck in trucks
    ]
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_select_driver")])
    
    await query.edit_message_text(
        "Выберите фуру для назначения:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECT_TRUCK_FOR_ASSIGNMENT

async def confirm_truck_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        driver_id = context.user_data.get('assign_driver_id')
        if not driver_id:
            raise KeyError("Не найден ID водителя")
        
        truck_id = int(query.data.split('_')[-1])
        
        db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE drivers 
            SET current_truck_id = ?,
                status = 'active'
            WHERE id = ?
        ''', (truck_id, driver_id))
        
        cursor.execute('''
            UPDATE trucks 
            SET status = 'active'
            WHERE id = ?
        ''', (truck_id,))
        
        cursor.execute('''
            SELECT d.current_truck_id, t.status 
            FROM drivers d
            JOIN trucks t ON d.current_truck_id = t.id
            WHERE d.id = ?
        ''', (driver_id,))
        result = cursor.fetchone()
        
        if not result or result[0] != truck_id or result[1] != 'active':
            raise ValueError("Не удалось обновить данные")
        
        cursor.execute('SELECT truck_number, model FROM trucks WHERE id = ?', (truck_id,))
        truck = cursor.fetchone()
        
        cursor.execute('SELECT first_name, username FROM drivers WHERE id = ?', (driver_id,))
        driver = cursor.fetchone()
        
        conn.commit()
        conn.close()
        
        await query.edit_message_text(
            f"✅ Водитель {driver[0]} (@{driver[1]}) назначен на фуру {truck[0]} ({truck[1]})",
            reply_markup=None
        )
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="👤 Управление водителями:",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("📋 Список водителей"), KeyboardButton("🚛 Назначить фуру")],
                [KeyboardButton("🗑 Удалить водителя"), KeyboardButton("🔙 Назад")]
            ], resize_keyboard=True)
        )
        return DRIVER_MENU
    
    except Exception as e:
        logger.error(f"Ошибка назначения фуры: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при назначении фуры. Попробуйте снова.",
            reply_markup=None
        )
        return await show_driver_management(update, context)
    
    finally:
        if 'assign_driver_id' in context.user_data:
            del context.user_data['assign_driver_id']

async def confirm_driver_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_driver_menu":
        await show_driver_management(update, context)
        return DRIVER_MENU
    
    driver_id = int(query.data.split('_')[-1])
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_{driver_id}")],
        [InlineKeyboardButton("❌ Нет, отменить", callback_data="back_to_driver_menu")]
    ]
    
    await query.edit_message_text(
        "⚠️ Вы уверены, что хотите удалить этого водителя?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_DELETE_DRIVER

async def complete_driver_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    driver_id = int(query.data.split('_')[-1])
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE drivers 
        SET current_truck_id = NULL 
        WHERE id = ?
    ''', (driver_id,))
    
    conn.commit()
    conn.close()
    
    await query.edit_message_text(f"✅ Привязка к фуре удалена для водителя")
    await show_driver_management(update, context)
    return DRIVER_MENU

async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    tasks = get_driver_tasks(user_id)
    
    if not tasks:
        await update.message.reply_text("✅ Все задачи уже выполнены!")
        return DRIVER_MENU
    
    context.user_data['tasks'] = tasks
    context.user_data['current_task'] = 0
    return await ask_for_proof(update, context)

async def ask_for_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = context.user_data['tasks'][context.user_data['current_task']]
    context.user_data['current_report'] = {'task_id': task[0]}
    
    await update.message.reply_text(
        f"🛠 Задача: {task[1]}\n"
        "Отправьте фото/видео подтверждение или пропустите:",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("⏭ Пропустить задачу")],
            [KeyboardButton("❌ Отменить отчет")]
        ], resize_keyboard=True)
    )
    return TASK_PROOF

async def handle_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = None
    file_type = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = 'photo'
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = 'video'
    else:
        await update.message.reply_text("❌ Неверный формат. Отправьте фото/видео.")
        return TASK_PROOF
    
    context.user_data['current_report']['proof'] = (file_id, file_type)
    await update.message.reply_text(
        "Добавить комментарий (текст/голос) или пропустить:",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("⏭ Пропустить комментарий")],
            [KeyboardButton("❌ Отменить отчет")]
        ], resize_keyboard=True)
    )
    return TASK_COMMENT

async def skip_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Укажите причину пропуска (текст/голос):",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("⏭ Пропустить причину")],
            [KeyboardButton("❌ Отменить отчет")]
        ], resize_keyboard=True)
    )
    return SKIP_REASON

async def save_skip_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = None
    if update.message.text != "⏭ Пропустить причину":
        if update.message.voice:
            reason = ('voice', update.message.voice.file_id)
        else:
            reason = ('text', update.message.text)
    
    context.user_data['current_report']['skip_reason'] = reason
    context.user_data['current_report']['skipped'] = True
    
    if reason is not None:
        await save_report(update, context)
    return await next_task(update, context)

async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = None
    if update.message.text != "⏭ Пропустить комментарий":
        if update.message.voice:
            comment = ('voice', update.message.voice.file_id)
        else:
            comment = ('text', update.message.text)
    
    if comment is not None:
        context.user_data['current_report']['comment'] = comment
    await save_report(update, context)
    return await next_task(update, context)

async def save_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    report = context.user_data.get('current_report', {})
    
    if not report:
        await update.message.reply_text("❌ Ошибка: данные отчета отсутствуют")
        return

    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT current_truck_id FROM drivers WHERE id = ?',
                (user_id,)
            )
            truck_result = cursor.fetchone()
            
            if not truck_result or not truck_result[0]:
                await update.message.reply_text("❌ Вам не назначена фура")
                return
                
            truck_id = truck_result[0]
            
            cursor.execute('''
                INSERT INTO completed_checks 
                (truck_id, driver_id, task_id, status, skipped)
                VALUES (?, ?, ?, 'pending', ?)
            ''', (
                truck_id,
                user_id,
                report.get('task_id'),
                report.get('skipped', False)
            ))
            report_id = cursor.lastrowid
            
            if 'proof' in report:
                file_id, file_type = report['proof']
                cursor.execute('''
                    INSERT INTO report_media 
                    (report_id, file_id, file_type)
                    VALUES (?, ?, ?)
                ''', (report_id, file_id, file_type))
            
            if 'skip_reason' in report and report['skip_reason'] is not None:
                reason_type, reason_content = report['skip_reason']
                if reason_type == 'voice':
                    cursor.execute('''
                        INSERT INTO check_comments 
                        (check_id, driver_id, voice_message_id, type)
                        VALUES (?, ?, ?, 'skip_reason')
                    ''', (report_id, user_id, reason_content))
                else:
                    cursor.execute('''
                        INSERT INTO check_comments 
                        (check_id, driver_id, comment, type)
                        VALUES (?, ?, ?, 'skip_reason')
                    ''', (report_id, user_id, reason_content))
            
            if 'comment' in report and report['comment'] is not None:
                comment_type, comment_content = report['comment']
                if comment_type == 'voice':
                    cursor.execute('''
                        INSERT INTO check_comments 
                        (check_id, driver_id, voice_message_id, type)
                        VALUES (?, ?, ?, 'comment')
                    ''', (report_id, user_id, comment_content))
                else:
                    cursor.execute('''
                        INSERT INTO check_comments 
                        (check_id, driver_id, comment, type)
                        VALUES (?, ?, ?, 'comment')
                    ''', (report_id, user_id, comment_content))
            
            conn.commit()
            
    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных: {e}")
        await update.message.reply_text("❌ Ошибка при сохранении отчета")
    except Exception as e:
        logger.error(f"Общая ошибка: {e}")
        await update.message.reply_text("❌ Неизвестная ошибка при сохранении")

async def next_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_task'] += 1
    if context.user_data['current_task'] >= len(context.user_data['tasks']):
        await update.message.reply_text(
            "✅ Все задачи завершены! Отчет отправлен на проверку.",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Главное меню")]], resize_keyboard=True)
        )
        return ConversationHandler.END
    return await ask_for_proof(update, context)

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trucks = get_trucks()
    if not trucks:
        await update.message.reply_text("Нет зарегистрированных фур.")
        return TASK_MENU
    
    tasks_list = []
    for truck in trucks:
        tasks = get_truck_tasks(truck[0])
        if tasks:
            truck_tasks = "\n".join([f"  • {task[1]}" for task in tasks])
            tasks_list.append(f"🚛 {truck[1]}:\n{truck_tasks}")
    
    if not tasks_list:
        await update.message.reply_text("Нет активных задач для фур.")
        return TASK_MENU
    
    await update.message.reply_text(
        "Список задач по фурам:\n\n" + "\n\n".join(tasks_list),
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад")]], resize_keyboard=True)
    )
    return TASK_MENU

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return MULTI_PHOTO_UPLOAD

    context.user_data['report_media'].append((file_id, file_type))
    
    await update.message.reply_text(
        "Фото/видео добавлено. Отправьте еще или нажмите 'Завершить загрузку'.",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("✅ Завершить загрузку")],
            [KeyboardButton("❌ Отменить")]
        ], resize_keyboard=True)
    )
    return MULTI_PHOTO_UPLOAD

async def complete_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('report_media'):
        await update.message.reply_text("Вы не добавили ни одного фото/видео. Попробуйте снова.")
        return await start_report(update, context)
    
    await update.message.reply_text(
        "📝 Теперь добавьте комментарий к отчету (текст или голосовое):",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("Пропустить комментарий")]
        ], resize_keyboard=True)
    )
    return WAITING_COMMENT

async def save_report_with_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    tasks = context.user_data.get('tasks', [])
    current_task_idx = context.user_data.get('current_task', 0)
    
    if current_task_idx >= len(tasks):
        await update.message.reply_text("❌ Ошибка: задача не найдена.")
        return DRIVER_MENU
    
    task_id = tasks[current_task_idx][0]
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('SELECT current_truck_id FROM drivers WHERE id = ?', (user.id,))
    truck_id = cursor.fetchone()[0]
    
    cursor.execute('''
    INSERT INTO completed_checks 
    (truck_id, driver_id, task_id, status)
    VALUES (?, ?, ?, 'pending')
    ''', (truck_id, user.id, task_id))
    
    report_id = cursor.lastrowid
    
    for file_id, file_type in context.user_data['report_media']:
        cursor.execute('''
        INSERT INTO report_media (report_id, file_id, file_type)
        VALUES (?, ?, ?)
        ''', (report_id, file_id, file_type))
    
    if update.message.text != "Пропустить комментарий":
        if update.message.voice:
            voice_id = update.message.voice.file_id
            cursor.execute('''
            INSERT INTO check_comments 
            (check_id, driver_id, voice_message_id)
            VALUES (?, ?, ?)
            ''', (report_id, user.id, voice_id))
        else:
            comment = update.message.text
            cursor.execute('''
            INSERT INTO check_comments 
            (check_id, driver_id, comment)
            VALUES (?, ?, ?)
            ''', (report_id, user.id, comment))
    
    conn.commit()
    conn.close()
    
    next_task_idx = current_task_idx + 1
    if next_task_idx < len(tasks):
        context.user_data['current_task'] = next_task_idx
        context.user_data['report_media'] = []
        
        await update.message.reply_text(
            f"✅ Отчет сохранен! Следующая задача:\n{tasks[next_task_idx][1]}\n\n"
            "Отправьте фото/видео выполнения (можно несколько):",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("✅ Завершить загрузку")],
                [KeyboardButton("❌ Отменить")]
            ], resize_keyboard=True)
        )
        return MULTI_PHOTO_UPLOAD
    else:
        await update.message.reply_text(
            "🎉 Все отчеты сохранены и отправлены на проверку!",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("📸 Сделать отчет"), KeyboardButton("📋 Мои отчеты")],
                [KeyboardButton("ℹ️ Информация о фуре"), KeyboardButton("🆘 Помощь")]
            ], resize_keyboard=True)
        )
        return DRIVER_MENU

async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'report_media' in context.user_data:
        del context.user_data['report_media']
    
    await update.message.reply_text(
        "Отчет отменен",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("📸 Сделать отчет"), KeyboardButton("📋 Мои отчеты")],
            [KeyboardButton("ℹ️ Информация о фуре"), KeyboardButton("🆘 Помощь")]
        ], resize_keyboard=True)
    )
    return DRIVER_MENU

async def view_my_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'truck_tasks_v2.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT cc.id, t.truck_number, tt.description, 
           cc.completion_date, cc.status
    FROM completed_checks cc
    JOIN trucks t ON cc.truck_id = t.id
    JOIN truck_tasks tt ON cc.task_id = tt.id
    WHERE cc.driver_id = ?
    ORDER BY cc.completion_date DESC
    LIMIT 10
    ''', (user_id,))
    
    reports = cursor.fetchall()
    conn.close()
    
    if not reports:
        await update.message.reply_text("Вы еще не отправляли отчетов.")
        return DRIVER_MENU
    
    reports_text = []
    for report in reports:
        status_icon = "✅" if report[4] == 'approved' else "❌" if report[4] == 'rejected' else "🕒"
        reports_text.append(
            f"{status_icon} {report[3].split('.')[0]} - {report[1]} - {report[2]}"
        )
    
    await update.message.reply_text(
        "Ваши последние отчеты:\n\n" + "\n".join(reports_text),
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("🔙 Назад")]
        ], resize_keyboard=True)
    )
    return DRIVER_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update:", exc_info=context.error)
    
    if update and hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(
            "Произошла ошибка. Пожалуйста, попробуйте ещё раз."
        )

def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ADMIN_MENU: [
                MessageHandler(filters.Regex('^🚛 Управление фурами$'), show_truck_menu),
                MessageHandler(filters.Regex('^👤 Управление водителями$'), show_driver_management),
                MessageHandler(filters.Regex('^📋 Управление задачами$'), show_task_menu),
                MessageHandler(filters.Regex('^📊 Просмотр отчетов$'), show_report_menu),
                MessageHandler(filters.Regex('^🔙 Выход$'), cancel)
            ],
            TRUCK_MENU: [
                MessageHandler(filters.Regex('^➕ Добавить фуру$'), add_truck),
                MessageHandler(filters.Regex('^📋 Список фур$'), list_trucks),
                MessageHandler(filters.Regex('^👥 Назначить водителя$'), assign_driver),
                MessageHandler(filters.Regex('^🗑 Удалить фуру$'), delete_truck),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            DRIVER_MENU: [
                MessageHandler(filters.Regex('^📋 Список водителей$'), list_drivers),
                MessageHandler(filters.Regex('^🚛 Назначить фуру$'), assign_driver),
                MessageHandler(filters.Regex('^🗑 Удалить водителя$'), delete_driver),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            TASK_MENU: [
                MessageHandler(filters.Regex('^📋 Список задач$'), list_tasks),
                MessageHandler(filters.Regex('^➕ Добавить задачу$'), add_task),
                MessageHandler(filters.Regex('^✏️ Редактировать задачи$'), edit_tasks),
                MessageHandler(filters.Regex('^🗑 Удалить задачи$'), delete_tasks),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            REPORT_MENU: [
                MessageHandler(filters.Regex('^📊 Отчеты по фурам$'), view_truck_reports),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            ADD_TRUCK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_truck),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_truck_menu)
            ],
            SELECT_DRIVER_FOR_TRUCK: [
                CallbackQueryHandler(select_truck_for_driver, pattern="^select_driver_"),
                CallbackQueryHandler(show_driver_management, pattern="^back_to_driver_menu$"),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            SELECT_TRUCK_FOR_ASSIGNMENT: [
                CallbackQueryHandler(confirm_truck_assignment, pattern="^assign_truck_"),
                CallbackQueryHandler(assign_truck_to_driver, pattern="^back_to_select_driver$"),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            ADD_TASK: [
                CallbackQueryHandler(handle_truck_selection_for_task, pattern="^add_task_"),
                CallbackQueryHandler(show_task_menu, pattern="^back_to_task_menu$")
            ],
            TASK_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_task_description),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_task_menu)
            ],
            EDIT_TASK: [
                CallbackQueryHandler(handle_truck_selection_for_edit, pattern="^edit_truck_"),
                CallbackQueryHandler(show_task_menu, pattern="^back_to_task_menu$"),
                CallbackQueryHandler(edit_task_status, pattern="^edit_task_"),
                CallbackQueryHandler(edit_tasks, pattern="^back_to_edit_menu$"),
                CallbackQueryHandler(save_task_status, pattern="^set_active_[01]$")
            ],
            DELETE_TASK: [
                CallbackQueryHandler(handle_truck_selection_for_delete, pattern="^delete_truck_"),
                CallbackQueryHandler(show_task_menu, pattern="^back_to_task_menu$"),
                CallbackQueryHandler(confirm_task_deletion, pattern="^delete_task_"),
                CallbackQueryHandler(confirm_task_deletion, pattern="^delete_all_"),
                CallbackQueryHandler(delete_tasks, pattern="^back_to_delete_menu$")
            ],
            REVIEW_REPORTS: [
                CallbackQueryHandler(show_report_for_review, pattern="^review_report_"),
                CallbackQueryHandler(show_report_menu, pattern="^back_to_report_menu$")
            ],
            APPROVE_REPORT: [
                CallbackQueryHandler(handle_report_approval, pattern="^approve_report$"),
                CallbackQueryHandler(handle_report_approval, pattern="^reject_report$"),
                CallbackQueryHandler(review_reports, pattern="^back_to_review$")
            ],
            DELETE_DRIVER: [
                CallbackQueryHandler(confirm_driver_deletion, pattern="^delete_driver_"),
                CallbackQueryHandler(show_driver_management, pattern="^back_to_driver_menu$"),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            CONFIRM_DELETE_DRIVER: [
                CallbackQueryHandler(complete_driver_deletion, pattern="^confirm_delete_"),
                CallbackQueryHandler(show_driver_management, pattern="^back_to_driver_menu$"),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            DRIVER_MENU: [
                MessageHandler(filters.Regex('^📋 Список водителей$'), list_drivers),
                MessageHandler(filters.Regex('^🚛 Назначить фуру$'), assign_truck_to_driver),
                MessageHandler(filters.Regex('^🗑 Удалить водителя$'), delete_driver),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu),
                MessageHandler(filters.Regex('^📸 Начать отчет$'), start_report)
            ],
            MULTI_PHOTO_UPLOAD: [
                MessageHandler(filters.PHOTO | filters.VIDEO, handle_photo_upload),
                MessageHandler(filters.Regex('^✅ Завершить загрузку$'), complete_photo_upload),
                MessageHandler(filters.Regex('^❌ Отменить$'), cancel_report)
            ],
            WAITING_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.Regex('^Пропустить комментарий$'), save_report_with_media),
                MessageHandler(filters.VOICE, save_report_with_media),
                MessageHandler(filters.Regex('^Пропустить комментарий$'), save_report_with_media)
            ],
            TASK_PROOF: [
                MessageHandler(filters.PHOTO | filters.VIDEO, handle_proof),
                MessageHandler(filters.Regex('^⏭ Пропустить задачу$'), skip_task),
                MessageHandler(filters.Regex('^❌ Отменить отчет$'), cancel_report)
            ],
            SKIP_REASON: [
                MessageHandler(filters.TEXT | filters.VOICE, save_skip_reason),
                MessageHandler(filters.Regex('^⏭ Пропустить причину$'), save_skip_reason),
                MessageHandler(filters.Regex('^❌ Отменить отчет$'), cancel_report)
            ],
            TASK_COMMENT: [
                MessageHandler(filters.TEXT | filters.VOICE, handle_comment),
                MessageHandler(filters.Regex('^⏭ Пропустить комментарий$'), handle_comment),
                MessageHandler(filters.Regex('^❌ Отменить отчет$'), cancel_report)
            ],
            VIEW_TRUCK_REPORTS: [
                CallbackQueryHandler(show_truck_reports, pattern="^view_truck_"),
                CallbackQueryHandler(show_report_menu, pattern="^back_to_report_menu$"),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            VIEW_TRUCK_REPORTS_DETAILS: [
                CallbackQueryHandler(handle_report_details, pattern="^(prev_page|next_page|back_to_reports)"),
                CallbackQueryHandler(show_full_comment, pattern="^comment_"),
                CallbackQueryHandler(show_skip_details, pattern="^skip_reason_"),
                CallbackQueryHandler(view_truck_reports, pattern="^back_to_report_menu$"),
                MessageHandler(filters.Regex('^🔙 Назад$'), show_admin_menu)
            ],
            DELETE_TRUCK: [
                CallbackQueryHandler(confirm_truck_deletion, pattern="^delete_truck_"),
                CallbackQueryHandler(show_truck_menu, pattern="^back_to_truck_menu$")
            ],
            CONFIRM_DELETE_TRUCK: [
                CallbackQueryHandler(complete_truck_deletion, pattern="^confirm_truck_delete_"),
                CallbackQueryHandler(show_truck_menu, pattern="^back_to_truck_menu$")
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_error_handler(error_handler)
    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()