import os
import sqlite3
from werkzeug.security import generate_password_hash

DB_DIR = 'data'
DB_PATH = os.path.join(DB_DIR, 'emby_bot.db')

def get_db_connection():
    """获取数据库连接，设置 row_factory 为 sqlite3.Row 以便类似字典操作"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库与数据表，创建默认系统配置项"""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)

    conn = get_db_connection()
    cursor = conn.cursor()

    # 创建注册用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emby_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            emby_username TEXT NOT NULL,
            password TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建系统设置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # 定义初始默认配置（如果不存在则插入）
    default_settings = {
        'web_username': 'admin',
        'web_password': generate_password_hash('admin'),
        'tg_token': '',
        'emby_server_url': '',
        'emby_api_key': '',
        'emby_proxy_url': '',
        'allowed_chat_id': '',
        'template_user_id': '',
        'policy_json': '{}'
    }

    for key, value in default_settings.items():
        cursor.execute('SELECT 1 FROM system_settings WHERE key = ?', (key,))
        if not cursor.fetchone():
            cursor.execute('INSERT INTO system_settings (key, value) VALUES (?, ?)', (key, value))

    conn.commit()
    conn.close()

# --- 配置管理 (Settings CRUD) ---

def get_setting(key, default=None):
    """读取单个系统配置项"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM system_settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['value']
    return default

def get_all_settings():
    """读取所有配置项，返回字典"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM system_settings')
    rows = cursor.fetchall()
    conn.close()
    return {row['key']: row['value'] for row in rows}

def save_settings(settings_dict):
    """批量更新配置项"""
    conn = get_db_connection()
    cursor = conn.cursor()
    for key, value in settings_dict.items():
        cursor.execute(
            'INSERT INTO system_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (key, str(value))
        )
    conn.commit()
    conn.close()

# --- 用户管理 (Users CRUD) ---

def get_all_users():
    """获取所有已注册用户，按时间倒序排列"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, chat_id, emby_username, password, created_at FROM emby_users ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def check_user_exists(chat_id):
    """检查 Telegram 用户是否已经创建过账号"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM emby_users WHERE chat_id = ?', (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def add_emby_user(chat_id, emby_username, password):
    """保存新创建的 Emby 用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO emby_users (chat_id, emby_username, password) VALUES (?, ?, ?)',
        (chat_id, emby_username, password)
    )
    conn.commit()
    conn.close()

def delete_user(user_id):
    """从数据库中删除指定用户记录"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM emby_users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

# 模块导入时自动执行自愈初始化，确保所有数据表和初始配置在任何查询之前建立完毕
init_db()
