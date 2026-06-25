import os
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import get_setting, save_settings, get_all_settings, get_all_users, delete_user

# 设定 Flask 项目路径以正确定位模板和静态资源
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# 动态设定 Secret Key，在数据库中读取，没有则生成并保存，防止容器重启 Session 失效
secret = get_setting('flask_secret_key')
if not secret:
    secret = secrets.token_hex(32)
    save_settings({'flask_secret_key': secret})
app.secret_key = secret

# 全局 bot_manager 引用，由 main.py 启动时注入
bot_manager = None

def set_bot_manager(manager):
    global bot_manager
    bot_manager = manager

# --- 登录校验装饰器 ---
def login_required(func):
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# --- 页面路由 ---

@app.route('/')
@login_required
def index():
    settings = get_all_settings()
    users = get_all_users()
    
    # 若 policy_json 为空或 '{}'，预填内置的 Policy 详细策略包，使用户一目了然、易于调整
    policy_val = settings.get('policy_json', '').strip()
    if not policy_val or policy_val == '{}':
        try:
            from app.bot import DEFAULT_POLICY
            import json
            settings['policy_json'] = json.dumps(DEFAULT_POLICY, indent=4)
        except Exception:
            pass

    # 隐藏敏感的 Flask secret key 和登录密码，不传递到前端
    settings.pop('flask_secret_key', None)
    settings.pop('web_password', None)
    return render_template('dashboard.html', settings=settings, users=users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db_username = get_setting('web_username')
        db_password_hash = get_setting('web_password')
        
        if username == db_username and check_password_hash(db_password_hash, password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误，请重新输入！', 'error')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- API 接口 ---

@app.route('/api/status', methods=['GET'])
@login_required
def status():
    """获取 TG Bot 的当前运行状态"""
    if bot_manager is None:
        return jsonify({'status': 'unknown'})
    
    if bot_manager.is_running():
        return jsonify({'status': 'running'})
    else:
        # 如果没有配置 token，状态显示为 stopped，否则是 error
        token = get_setting('tg_token')
        if not token:
            return jsonify({'status': 'stopped'})
        return jsonify({'status': 'error'})

@app.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    """更新系统设置。若 Token 变更，自动触发 Bot 重载"""
    data = request.json
    if not data:
        return jsonify({'error': '无效的请求数据'}), 400
        
    # 获取修改前的 token 
    old_token = get_setting('tg_token')
    
    # 提取允许修改的字段，防止意外字段覆盖数据库
    allowed_keys = ['tg_token', 'allowed_chat_id', 'emby_server_url', 'emby_api_key', 'emby_proxy_url', 'template_user_id', 'policy_json']
    settings_to_save = {k: data.get(k, '').strip() for k in allowed_keys if k in data}
    
    try:
        # 如果设置了 policy_json，校验其是否为有效 JSON
        policy_str = settings_to_save.get('policy_json')
        if policy_str:
            import json
            json.loads(policy_str) # 尝试解析校验格式
    except json.JSONDecodeError:
        return jsonify({'error': '自定义策略配置不是合法的 JSON 格式！'}), 400
        
    save_settings(settings_to_save)
    
    # 检测 Token 发生改变或原本没有启动时触发重启
    new_token = settings_to_save.get('tg_token', '')
    if bot_manager:
        if old_token != new_token or not bot_manager.is_running():
            bot_manager.restart()
            
    return jsonify({'success': True})

@app.route('/api/password', methods=['POST'])
@login_required
def change_password():
    """修改管理员密码"""
    data = request.json
    if not data:
        return jsonify({'error': '无效的请求数据'}), 400
        
    old_password = data.get('oldPassword')
    new_password = data.get('newPassword')
    
    if not old_password or not new_password:
        return jsonify({'error': '参数不完整'}), 400
        
    db_password_hash = get_setting('web_password')
    if not check_password_hash(db_password_hash, old_password):
        return jsonify({'error': '原密码校验错误！'}), 400
        
    # 保存新密码哈希值
    new_hash = generate_password_hash(new_password)
    save_settings({'web_password': new_hash})
    
    return jsonify({'success': True})

@app.route('/api/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user_record(user_id):
    """删除已开通的用户记录"""
    try:
        delete_user(user_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@app.route('/api/logs', methods=['GET'])
@login_required
def get_logs():
    """获取最新日志内容"""
    log_path = os.path.join('data', 'bot.log')
    if not os.path.exists(log_path):
        return jsonify({'logs': '暂无日志记录。'})
        
    try:
        lines_count = int(request.args.get('lines', 200))
        # 考虑到性能和并发，读取最后 lines_count 行
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            last_lines = lines[-lines_count:]
            return jsonify({'logs': ''.join(last_lines)})
    except Exception as e:
        return jsonify({'error': f'读取日志失败: {str(e)}'}), 500

