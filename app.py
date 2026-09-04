from flask import Flask, render_template, request, jsonify, send_from_directory, url_for, make_response, redirect
import os
import sqlite3
from datetime import datetime
import pandas as pd
from werkzeug.utils import secure_filename
import json
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, Table, TableStyle, KeepTogether
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage
import base64
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user


# 数据库路径配置
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'products.db')

app = Flask(__name__)
# 上传目录放到 data 下面，方便只挂载一个 Volume
app.config['DATA_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
app.config['UPLOAD_FOLDER'] = os.path.join(app.config['DATA_FOLDER'], 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'xlsx', 'xls'}
app.config['EXPORT_FOLDER'] = os.path.join(app.config['DATA_FOLDER'], 'exports')
app.secret_key = os.environ.get('SECRET_KEY', 'dev_secret_key_change_in_production')

# 初始化 Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'error': '未登录或会话已过期，请重新登录'}), 401
    return redirect(url_for('login'))

@app.errorhandler(413)
def request_entity_too_large(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': '上传文件过大，超出系统限制(100MB)'}), 413
    return "上传文件过大，超出系统限制", 413

@app.errorhandler(500)
def internal_server_error(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': '服务器内部错误'}), 500
    return "服务器内部错误", 500

# 用户类
class User(UserMixin):
    def __init__(self, id, username, role, permissions):
        self.id = id
        self.username = username
        self.role = role
        self.permissions = permissions  # dict

    @property
    def can_upload(self):
        return self.role == 'admin' or self.permissions.get('can_upload', False)

    @property
    def can_delete(self):
        return self.role == 'admin' or self.permissions.get('can_delete', False)
    
    @property
    def is_admin(self):
        return self.role == 'admin'

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, username, role, permissions FROM users WHERE id = ?', (user_id,))
    user_data = c.fetchone()
    conn.close()
    
    if user_data:
        permissions = {}
        if user_data[3]:
            try:
                permissions = json.loads(user_data[3])
            except:
                pass
        return User(id=user_data[0], username=user_data[1], role=user_data[2], permissions=permissions)
    return None

# 确保所有必要目录存在（都在 data 目录下）
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'images'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'pending_images'), exist_ok=True)
os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)

# 注册中文字体（用于PDF生成）
_chinese_font_registered = False

def register_chinese_font():
    """注册中文字体"""
    global _chinese_font_registered
    if _chinese_font_registered:
        return True

    try:
        # 优先查找当前目录下的fonts文件夹
        current_dir = os.path.dirname(os.path.abspath(__file__))
        local_font_paths = [
            os.path.join(current_dir, 'fonts', 'SimHei.ttf'),
            os.path.join(current_dir, 'fonts', 'simhei.ttf'),
            os.path.join(current_dir, 'fonts', 'msyh.ttc'),
            os.path.join(current_dir, 'fonts', 'simsun.ttc')
        ]
        
        font_paths = local_font_paths + [
            'C:/Windows/Fonts/msyh.ttc',  # 微软雅黑
            'C:/Windows/Fonts/simsun.ttc',  # 宋体
            'C:/Windows/Fonts/simhei.ttf',  # 黑体
            'C:/Windows/Fonts/simkai.ttf',  # 楷体
            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf', # Ubuntu/Debian 常用
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc' # 其他 Linux
        ]

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                    pdfmetrics.registerFont(TTFont('ChineseFontBold', font_path))
                    print(f"成功注册字体: {font_path}")
                    _chinese_font_registered = True
                    return True
                except Exception as e:
                    print(f"尝试注册字体 {font_path} 失败: {e}")
                    continue
        
        print("未找到可用的中文字体，PDF中文可能无法显示")
        return False
    except Exception as e:
        print(f"注册字体出错: {e}")
        return False

# 初始化时注册字体
_chinese_font_registered = register_chinese_font()

# 获取中文字体路径（用于图片生成）
def get_chinese_font_path():
    """获取可用的中文字体路径（用于PIL）"""
    # 优先查找当前目录下的fonts文件夹
    current_dir = os.path.dirname(os.path.abspath(__file__))
    font_paths = [
        os.path.join(current_dir, 'fonts', 'SimHei.ttf'),
        os.path.join(current_dir, 'fonts', 'simhei.ttf'),
        os.path.join(current_dir, 'fonts', 'msyh.ttc'),
        os.path.join(current_dir, 'fonts', 'simsun.ttc'),
        'C:/Windows/Fonts/msyh.ttc',  # 微软雅黑
        'C:/Windows/Fonts/simsun.ttc',  # 宋体
        'C:/Windows/Fonts/simhei.ttf',  # 黑体
        'C:/Windows/Fonts/simkai.ttf',  # 楷体
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
    ]
    
    for font_path in font_paths:
        if os.path.exists(font_path):
            return font_path
    return None

# 初始化数据库
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  code TEXT UNIQUE NOT NULL,
                  text_info TEXT,
                  image_path TEXT,
                  extra_fields TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # 用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL DEFAULT 'user',
                  permissions TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # 系统设置表
    c.execute('''CREATE TABLE IF NOT EXISTS system_settings
                 (key TEXT PRIMARY KEY,
                  value TEXT)''')
    
    # 如果表已存在但没有extra_fields列，则添加该列
    try:
        c.execute('ALTER TABLE products ADD COLUMN extra_fields TEXT')
    except sqlite3.OperationalError:
        # 列已存在，忽略错误
        pass
    
    # 检查是否需要创建默认管理员
    try:
        c.execute('SELECT count(*) FROM users')
        if c.fetchone()[0] == 0:
            default_password = generate_password_hash('admin123')
            default_permissions = json.dumps({'can_upload': True, 'can_delete': True})
            c.execute('INSERT INTO users (username, password_hash, role, permissions) VALUES (?, ?, ?, ?)',
                     ('admin', default_password, 'admin', default_permissions))
            print("Created default admin user: admin / admin123")
    except sqlite3.IntegrityError:
        # 在多进程启动时，另一个进程可能已经插入了用户，忽略此错误
        pass

    # 初始化默认设置
    c.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)', ('allow_registration', 'true'))
    
    conn.commit()
    conn.close()

# 初始化数据库（确保在应用启动时创建表）
init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_code_from_filename(filename):
    """从文件名提取款号（去掉扩展名）"""
    if '.' in filename:
        return filename.rsplit('.', 1)[0]
    return filename

def match_pending_image(code):
    """检查是否有待匹配的图片，如果有则匹配并返回图片路径"""
    pending_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'pending_images')
    if not os.path.exists(pending_dir):
        return None
    
    # 支持的图片扩展名
    image_extensions = ['jpg', 'jpeg', 'png', 'gif']
    
    # 遍历待匹配目录中的所有文件
    try:
        for filename in os.listdir(pending_dir):
            file_path = os.path.join(pending_dir, filename)
            if not os.path.isfile(file_path):
                continue
            
            # 提取文件名（不含扩展名）
            if '.' in filename:
                file_code = filename.rsplit('.', 1)[0]
                ext = filename.rsplit('.', 1)[1].lower()
            else:
                continue
            
            # 检查款号是否匹配（不区分大小写）
            if file_code.lower() == code.lower() and ext in image_extensions:
                # 移动到 images 目录
                new_filename = secure_filename(f"{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
                target_path = os.path.join(app.config['UPLOAD_FOLDER'], 'images', new_filename)
                try:
                    os.rename(file_path, target_path)
                    return f"images/{new_filename}"
                except Exception as e:
                    print(f'移动待匹配图片失败: {e}')
                    return None
    except Exception as e:
        print(f'遍历待匹配目录失败: {e}')
    
    return None

def match_existing_image(code):
    """检查images目录中是否已有匹配的图片（文件名匹配款号），且未被其他产品使用"""
    images_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'images')
    if not os.path.exists(images_dir):
        return None
    
    # 支持的图片扩展名
    image_extensions = ['jpg', 'jpeg', 'png', 'gif']
    
    # 检查数据库中哪些图片已被使用
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT image_path FROM products WHERE image_path IS NOT NULL')
    used_images = set(row[0] for row in c.fetchall())
    conn.close()
    
    # 检查是否有文件名匹配款号的图片（不区分大小写）
    try:
        for filename in os.listdir(images_dir):
            file_path = os.path.join(images_dir, filename)
            if not os.path.isfile(file_path):
                continue
            
            # 提取文件名（不含扩展名）
            if '.' in filename:
                file_code = filename.rsplit('.', 1)[0]
                ext = filename.rsplit('.', 1)[1].lower()
            else:
                continue
            
            image_path = f"images/{filename}"
            
            # 如果图片已被其他产品使用，跳过
            if image_path in used_images:
                continue
            
            # 检查款号是否匹配（不区分大小写）
            # 支持两种格式：1) 文件名就是款号 2) 文件名以款号_开头
            if ext in image_extensions:
                # 检查文件名是否就是款号
                if file_code.lower() == code.lower():
                    return image_path
                # 检查文件名是否以款号_开头（如：ABC001_20240101.jpg）
                elif file_code.lower().startswith(code.lower() + '_'):
                    return image_path
    except Exception as e:
        print(f'遍历images目录失败: {e}')
    
    return None

# 获取系统设置
def get_system_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT value FROM system_settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id, username, password_hash, role, permissions FROM users WHERE username = ?', (username,))
        user_data = c.fetchone()
        conn.close()
        
        if user_data and check_password_hash(user_data[2], password):
            permissions = {}
            if user_data[4]:
                try:
                    permissions = json.loads(user_data[4])
                except:
                    pass
            user = User(id=user_data[0], username=user_data[1], role=user_data[3], permissions=permissions)
            login_user(user)
            return jsonify({'success': True, 'redirect': url_for('index')})
        
        return jsonify({'error': '用户名或密码错误'}), 401
    
    # Check if registration is allowed to show/hide link
    allow_registration = get_system_setting('allow_registration', 'true') == 'true'
    return render_template('login.html', allow_registration=allow_registration)

@app.route('/register', methods=['GET', 'POST'])
def register():
    # check system setting
    allow_registration = get_system_setting('allow_registration', 'true') == 'true'
    if not allow_registration:
        if request.is_json:
            return jsonify({'error': '注册功能已关闭'}), 403
        return "注册功能已关闭", 403

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            return jsonify({'error': '用户名和密码不能为空'}), 400
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        try:
            # Check if user exists
            c.execute('SELECT id FROM users WHERE username = ?', (username,))
            if c.fetchone():
                return jsonify({'error': '用户名已存在'}), 400
                
            password_hash = generate_password_hash(password)
            # Default permissions for new users: read-only
            default_permissions = json.dumps({'can_upload': False, 'can_delete': False})
            
            c.execute('INSERT INTO users (username, password_hash, role, permissions) VALUES (?, ?, ?, ?)',
                     (username, password_hash, 'user', default_permissions))
            conn.commit()
            return jsonify({'success': True, 'redirect': url_for('login')})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()
            
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return "无权访问", 403
    return render_template('admin.html')

@app.route('/api/admin/users', methods=['GET'])
@login_required
def list_users():
    if not current_user.is_admin:
        return jsonify({'error': '无权访问'}), 403
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, username, role, permissions, created_at FROM users')
    rows = c.fetchall()
    conn.close()
    
    users = []
    for row in rows:
        permissions = {}
        if row[3]:
            try:
                permissions = json.loads(row[3])
            except:
                pass
        users.append({
            'id': row[0],
            'username': row[1],
            'role': row[2],
            'permissions': permissions,
            'created_at': row[4]
        })
        
    # Get system settings too
    allow_registration = get_system_setting('allow_registration', 'true') == 'true'
    
    return jsonify({'users': users, 'settings': {'allow_registration': allow_registration}})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': '无权访问'}), 403
        
    if user_id == current_user.id:
        return jsonify({'error': '不能删除自己'}), 400
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/admin/users/<int:user_id>/permissions', methods=['PUT'])
@login_required
def update_permissions(user_id):
    if not current_user.is_admin:
        return jsonify({'error': '无权访问'}), 403
        
    data = request.get_json()
    new_permissions = json.dumps(data.get('permissions', {}))
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET permissions = ? WHERE id = ?', (new_permissions, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/admin/settings', methods=['POST'])
@login_required
def update_settings():
    if not current_user.is_admin:
        return jsonify({'error': '无权访问'}), 403
        
    data = request.get_json()
    key = data.get('key')
    value = str(data.get('value')).lower()
    
    if key not in ['allow_registration']:
        return jsonify({'error': '无效的设置项'}), 400
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/user/profile', methods=['PUT'])
@login_required
def update_profile():
    data = request.get_json()
    new_username = data.get('username')
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password:
        return jsonify({'error': '需要提供当前密码验证身份'}), 400
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Verify current password
    c.execute('SELECT password_hash FROM users WHERE id = ?', (current_user.id,))
    user_data = c.fetchone()
    if not user_data or not check_password_hash(user_data[0], current_password):
        conn.close()
        return jsonify({'error': '当前密码错误'}), 401
    
    try:
        if new_username and new_username != current_user.username:
            # Check uniqueness
            c.execute('SELECT id FROM users WHERE username = ? AND id != ?', (new_username, current_user.id))
            if c.fetchone():
                conn.close()
                return jsonify({'error': '用户名已存在'}), 400
            c.execute('UPDATE users SET username = ? WHERE id = ?', (new_username, current_user.id))
            
        if new_password:
            password_hash = generate_password_hash(new_password)
            c.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, current_user.id))
            
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user_by_admin(user_id):
    if not current_user.is_admin:
        return jsonify({'error': '无权访问'}), 403
        
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        if username:
            # Check uniqueness
            c.execute('SELECT id FROM users WHERE username = ? AND id != ?', (username, user_id))
            if c.fetchone():
                conn.close()
                return jsonify({'error': '用户名已存在'}), 400
            c.execute('UPDATE users SET username = ? WHERE id = ?', (username, user_id))
            
        if password:
            password_hash = generate_password_hash(password)
            c.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, user_id))
            
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return render_template('index.html', user=current_user)

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    if not current_user.can_upload:
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        data = request.form
        code = data.get('code', '').strip()
        
        if not code:
            return jsonify({'error': '款号不能为空'}), 400
        
        text_info = data.get('text_info', '').strip()
        image_path = None
        
        # 处理图片上传
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                ext = os.path.splitext(file.filename)[1]
                filename = secure_filename(f"{code}{ext}")
                # If secure_filename strips everything (e.g. chinese code), we fallback to manual sanitization
                if not filename or filename.startswith('.'):
                     filename = f"{code}{ext}"
                     import re
                     filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'images', filename)
                file.save(filepath)
                image_path = f"images/{filename}"
        
        # 如果没有上传图片，检查是否有待匹配的图片
        if not image_path:
            image_path = match_pending_image(code)
        
        # 保存到数据库
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO products (code, text_info, image_path, extra_fields)
                         VALUES (?, ?, ?, ?)''',
                     (code, text_info, image_path, None))
            conn.commit()
            product_id = c.lastrowid
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'error': '款号已存在'}), 400
        finally:
            conn.close()
        
        # 生成访问链接
        view_url = url_for('view_product', code=code, _external=True)
        
        return jsonify({
            'success': True,
            'message': '产品添加成功',
            'code': code,
            'view_url': view_url
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/excel', methods=['POST'])
@login_required
def import_excel():
    if not current_user.can_upload:
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        if 'excel_file' not in request.files:
            return jsonify({'error': '未选择文件'}), 400
        
        file = request.files['excel_file']
        if file.filename == '':
            return jsonify({'error': '未选择文件'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': '文件格式不支持，请上传Excel文件'}), 400
        
        # 读取Excel文件
        df = pd.read_excel(file)
        
        # 检查必要的列（第一列必须是款号）
        if len(df.columns) == 0:
            return jsonify({'error': 'Excel文件为空'}), 400
        
        # 第一列必须是款号
        first_col = df.columns[0]
        if first_col not in ['款号', 'code']:
            return jsonify({'error': 'Excel文件第一列必须是"款号"或"code"'}), 400
        
        code_col = first_col
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        success_count = 0
        error_messages = []
        
        for index, row in df.iterrows():
            code = str(row[code_col]).strip()
            if not code or code == 'nan':
                continue
            
            # 构建额外字段字典（从第二列开始的所有列）
            extra_fields = {}
            for col in df.columns[1:]:  # 跳过第一列（款号）
                value = row[col]
                if pd.notna(value) and str(value).strip():
                    # 只保存有数据的列
                    extra_fields[col] = str(value).strip()
            
            # 将extra_fields转换为JSON字符串
            extra_fields_json = json.dumps(extra_fields, ensure_ascii=False) if extra_fields else None
            
            # 检查是否有待匹配的图片（优先检查pending_images）
            image_path = match_pending_image(code)
            
            # 如果没有待匹配的图片，检查images目录中是否已有匹配的图片
            if not image_path:
                image_path = match_existing_image(code)
            
            try:
                c.execute('''INSERT INTO products (code, text_info, image_path, extra_fields)
                             VALUES (?, ?, ?, ?)''',
                         (code, None, image_path, extra_fields_json))
                success_count += 1
            except sqlite3.IntegrityError:
                error_messages.append(f'款号 {code} 已存在，跳过')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'成功导入 {success_count} 条记录',
            'success_count': success_count,
            'errors': error_messages
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'导入失败: {str(e)}'}), 500

@app.route('/查看<code>')
@app.route('/view/<code>')
# 允许游客访问，查看不需要登录
def view_product(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code, text_info, image_path, extra_fields, created_at FROM products WHERE code = ?', (code,))
    product = c.fetchone()
    conn.close()
    
    if not product:
        return render_template('not_found.html', code=code), 404
    
    # 解析extra_fields
    extra_fields = {}
    if product[3]:  # extra_fields列
        try:
            extra_fields = json.loads(product[3])
        except (json.JSONDecodeError, TypeError):
            extra_fields = {}
    
    product_data = {
        'code': product[0],
        'text_info': product[1],
        'image_path': product[2],
        'extra_fields': extra_fields,
        'created_at': product[4]
    }
    
    return render_template('view.html', product=product_data)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/products/<code>/export/pdf', methods=['GET'])
def export_product_pdf(code):
    """导出产品信息为PDF"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT code, text_info, image_path, extra_fields, created_at FROM products WHERE code = ?', (code,))
        product = c.fetchone()
        conn.close()
        
        if not product:
            return jsonify({'error': '产品不存在'}), 404
        
        # 解析extra_fields
        extra_fields = {}
        if product[3]:
            try:
                extra_fields = json.loads(product[3])
            except (json.JSONDecodeError, TypeError):
                extra_fields = {}
        
        # 创建PDF
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = []
        
        # 设置样式
        styles = getSampleStyleSheet()
        
        # 如果已注册中文字体，使用中文字体；否则使用默认字体
        font_name = 'ChineseFont' if _chinese_font_registered else 'Helvetica'
        font_name_bold = 'ChineseFontBold' if _chinese_font_registered else 'Helvetica-Bold'
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor='black',
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName=font_name_bold
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor='black',
            spaceAfter=12,
            spaceBefore=12,
            fontName=font_name_bold
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=12,
            leading=18,
            fontName=font_name
        )
        
        # 1. 文本信息块（标题、时间、描述、详细信息）
        info_content = []

        # 标题
        info_content.append(Paragraph(f"产品信息：{product[0]}", title_style))
        info_content.append(Spacer(1, 0.2*inch))
        
        # 创建时间
        info_content.append(Paragraph(f"创建时间：{product[4]}", normal_style))
        info_content.append(Spacer(1, 0.3*inch))
        
        # 文本信息
        if product[1]:
            info_content.append(Paragraph("产品描述", heading_style))
            info_content.append(Paragraph(product[1].replace('\n', '<br/>'), normal_style))
            info_content.append(Spacer(1, 0.2*inch))
        
        # 额外字段
        if extra_fields:
            info_content.append(Paragraph("详细信息", heading_style))
            info_content.append(Spacer(1, 0.1*inch))
            
            table_data = []
            col1_width = 1.5 * inch
            col2_width = 4.5 * inch
            
            for field_name, field_value in extra_fields.items():
                p_key = Paragraph(f"<b>{field_name}</b>", normal_style)
                # Ensure value is string and handle newlines
                val_str = str(field_value) if field_value is not None else ""
                p_value = Paragraph(val_str.replace('\n', '<br/>'), normal_style)
                table_data.append([p_key, p_value])
            
            if table_data:
                t = Table(table_data, colWidths=[col1_width, col2_width])
                t.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('PADDING', (0, 0), (-1, -1), 6),
                    ('BACKGROUND', (0, 0), (0, -1), colors.whitesmoke),
                ]))
                info_content.append(t)
                info_content.append(Spacer(1, 0.2*inch))
        
        # 将文本信息作为一个整体保持在一起
        story.append(KeepTogether(info_content))

        # 2. 产品图片部分（单独块，如果空间不足会自动去下一页）
        if product[2]:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], product[2])
            if os.path.exists(image_path):
                try:
                    img_content = []
                    img = RLImage(image_path, width=5*inch, height=5*inch, kind='proportional')
                    img_content.append(Paragraph("产品图片", heading_style))
                    img_content.append(img)
                    # 图片和图片标题保持在一起
                    story.append(KeepTogether(img_content))
                except Exception as e:
                    story.append(Paragraph(f"图片加载失败：{str(e)}", normal_style))
        
        # 构建PDF
        doc.build(story)
        buffer.seek(0)
        
        # 返回PDF文件
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=product_{code}_{datetime.now().strftime("%Y%m%d")}.pdf'
        return response
        
    except Exception as e:
        import traceback
        print(f'生成PDF失败: {str(e)}')
        print(traceback.format_exc())
        return jsonify({'error': f'生成PDF失败: {str(e)}'}), 500


@app.route('/api/products/export/pdf/batch', methods=['POST'])
@login_required
def export_products_pdf_batch():
    """批量导出多个产品信息为一个PDF"""
    try:
        data = request.get_json()
        if not data or 'codes' not in data or not isinstance(data.get('codes'), list) or len(data.get('codes')) == 0:
            return jsonify({'error': '缺少产品款号列表'}), 400

        codes = [str(c).strip() for c in data.get('codes') if str(c).strip()]
        if not codes:
            return jsonify({'error': '产品款号列表为空'}), 400

        # 去重但保持原有顺序
        seen = set()
        ordered_codes = []
        for c in codes:
            if c not in seen:
                seen.add(c)
                ordered_codes.append(c)

        # 查询数据库
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        placeholders = ','.join('?' for _ in ordered_codes)
        c.execute(f'''SELECT code, text_info, image_path, extra_fields, created_at 
                      FROM products WHERE code IN ({placeholders})''', ordered_codes)
        rows = c.fetchall()
        conn.close()

        # 建立code到数据的映射
        row_map = {row[0]: row for row in rows}
        products = []
        for code in ordered_codes:
            if code in row_map:
                row = row_map[code]
                extra_fields = {}
                if row[3]:
                    try:
                        extra_fields = json.loads(row[3])
                    except (json.JSONDecodeError, TypeError):
                        extra_fields = {}
                products.append({
                    'code': row[0],
                    'text_info': row[1],
                    'image_path': row[2],
                    'extra_fields': extra_fields,
                    'created_at': row[4]
                })

        if not products:
            return jsonify({'error': '未找到任何产品'}), 404

        # 创建PDF，版式与单个产品导出保持一致
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = []

        # 样式与单个导出一致
        styles = getSampleStyleSheet()
        font_name = 'ChineseFont' if _chinese_font_registered else 'Helvetica'
        font_name_bold = 'ChineseFontBold' if _chinese_font_registered else 'Helvetica-Bold'

        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor='black',
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName=font_name_bold
        )

        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor='black',
            spaceAfter=12,
            spaceBefore=12,
            fontName=font_name_bold
        )

        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=12,
            leading=18,
            fontName=font_name
        )

        for idx, product in enumerate(products):
            # 1. 文本信息块
            info_content = []

            # 标题与时间
            info_content.append(Paragraph(f"产品信息：{product['code']}", title_style))
            info_content.append(Spacer(1, 0.2 * inch))
            info_content.append(Paragraph(f"创建时间：{product['created_at']}", normal_style))
            info_content.append(Spacer(1, 0.3 * inch))

            # 文本信息
            if product['text_info']:
                info_content.append(Paragraph("产品描述", heading_style))
                info_content.append(Paragraph(str(product['text_info']).replace('\n', '<br/>'), normal_style))
                info_content.append(Spacer(1, 0.2 * inch))

            # 额外字段
            if product['extra_fields']:
                info_content.append(Paragraph("详细信息", heading_style))
                info_content.append(Spacer(1, 0.1*inch))
                
                table_data = []
                col1_width = 1.5 * inch
                col2_width = 4.5 * inch
                
                for field_name, field_value in product['extra_fields'].items():
                    p_key = Paragraph(f"<b>{field_name}</b>", normal_style)
                    val_str = str(field_value) if field_value is not None else ""
                    p_value = Paragraph(val_str.replace('\n', '<br/>'), normal_style)
                    table_data.append([p_key, p_value])
                
                if table_data:
                    t = Table(table_data, colWidths=[col1_width, col2_width])
                    t.setStyle(TableStyle([
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('PADDING', (0, 0), (-1, -1), 6),
                        ('BACKGROUND', (0, 0), (0, -1), colors.whitesmoke),
                    ]))
                    info_content.append(t)
                    info_content.append(Spacer(1, 0.2*inch))

            # 无内容提示 (如果只是没有文本和表格，但有图片，这段不应该显示，需要调整逻辑。或者无内容提示也归入info)
            if not product['text_info'] and not product['extra_fields'] and not product['image_path']:
                info_content.append(Paragraph("该产品暂无详细信息", normal_style))
            
            # 将文本信息作为一个整体
            story.append(KeepTogether(info_content))

            # 2. 产品图片块
            if product['image_path']:
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], product['image_path'])
                if os.path.exists(image_path):
                    try:
                        img_content = []
                        img = RLImage(image_path, width=5 * inch, height=5 * inch, kind='proportional')
                        img_content.append(Paragraph("产品图片", heading_style))
                        img_content.append(img)
                        story.append(KeepTogether(img_content))
                    except Exception as e:
                        story.append(Paragraph(f"图片加载失败：{str(e)}", normal_style))

            # 分页（最后一个不分页）
            if idx != len(products) - 1:
                story.append(PageBreak())

        doc.build(story)
        buffer.seek(0)

        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        filename = f"products_batch_{datetime.now().strftime('%Y%m%d')}.pdf"
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response

    except Exception as e:
        import traceback
        print(f'批量生成PDF失败: {str(e)}')
        print(traceback.format_exc())
        return jsonify({'error': f'批量生成PDF失败: {str(e)}'}), 500

@app.route('/api/products/<code>/export/image', methods=['GET'])
def export_product_image(code):
    """导出产品信息为图片"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT code, text_info, image_path, extra_fields, created_at FROM products WHERE code = ?', (code,))
        product = c.fetchone()
        conn.close()
        
        if not product:
            return jsonify({'error': '产品不存在'}), 404
        
        # 解析extra_fields
        extra_fields = {}
        if product[3]:
            try:
                extra_fields = json.loads(product[3])
            except (json.JSONDecodeError, TypeError):
                extra_fields = {}
        
        # 使用Pillow创建图片
        from PIL import ImageDraw, ImageFont
        
        # 计算所需高度
        padding = 40
        line_height = 30
        title_height = 60
        section_spacing = 30
        
        content_height = title_height + line_height  # 标题 + 创建时间
        
        if product[1]:
            text_lines = product[1].split('\n')
            content_height += 40 + len(text_lines) * line_height  # 标题 + 内容
        
        if extra_fields:
            content_height += 40  # 标题
            for field_name, field_value in extra_fields.items():
                field_text = f"{field_name}：{str(field_value)}"
                field_lines = field_text.split('\n')
                content_height += len(field_lines) * line_height + 10
        
        # 产品图片高度
        product_img_height = 0
        if product[2]:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], product[2])
            if os.path.exists(image_path):
                try:
                    img = PILImage.open(image_path)
                    max_width = 700
                    ratio = min(max_width / img.width, 500 / img.height)
                    product_img_height = int(img.height * ratio) + 40  # 加上标题和间距
                except:
                    pass
        
        total_height = padding * 2 + content_height + product_img_height + section_spacing * 2
        width = 800
        
        # 创建图片
        img = PILImage.new('RGB', (width, total_height), color='white')
        draw = ImageDraw.Draw(img)
        
        # 尝试加载中文字体（优先）
        chinese_font_path = get_chinese_font_path()
        title_font = None
        heading_font = None
        normal_font = None
        
        if chinese_font_path:
            try:
                title_font = ImageFont.truetype(chinese_font_path, 32)
                heading_font = ImageFont.truetype(chinese_font_path, 18)
                normal_font = ImageFont.truetype(chinese_font_path, 14)
            except Exception as e:
                print(f'加载中文字体失败: {e}')
        
        # 如果中文字体加载失败，尝试其他字体
        if not title_font:
            font_paths = [
                'C:/Windows/Fonts/msyh.ttc',
                'C:/Windows/Fonts/simsun.ttc',
                'C:/Windows/Fonts/simhei.ttf',
            ]
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        title_font = ImageFont.truetype(font_path, 32)
                        heading_font = ImageFont.truetype(font_path, 18)
                        normal_font = ImageFont.truetype(font_path, 14)
                        break
                    except:
                        continue
        
        # 如果所有中文字体都失败，使用默认字体
        if not title_font:
            title_font = ImageFont.load_default()
            heading_font = ImageFont.load_default()
            normal_font = ImageFont.load_default()
        
        y = padding
        
        # 标题
        title = f"产品信息：{product[0]}"
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        draw.text(((width - title_width) / 2, y), title, fill=(102, 126, 234), font=title_font)
        y += title_height
        
        # 创建时间
        draw.text((padding, y), f"创建时间：{product[4]}", fill=(0, 0, 0), font=normal_font)
        y += line_height + section_spacing
        
        # 文本信息
        if product[1]:
            draw.text((padding, y), "产品描述", fill=(102, 126, 234), font=heading_font)
            y += 40
            text_lines = product[1].split('\n')
            max_width = width - padding * 2
            for line in text_lines:
                # 处理长文本自动换行
                words = line
                while len(words) > 0:
                    # 计算可以显示的字符数
                    char_width = draw.textlength(words[:1], font=normal_font) if len(words) > 0 else 10
                    if char_width == 0:
                        char_width = 10  # 默认字符宽度
                    chars_per_line = int(max_width / char_width) if char_width > 0 else 50
                    
                    if len(words) <= chars_per_line:
                        draw.text((padding, y), words, fill=(0, 0, 0), font=normal_font)
                        y += line_height
                        break
                    else:
                        # 尝试找到合适的断点（优先在空格、标点处断开）
                        break_pos = chars_per_line
                        for i in range(min(chars_per_line, len(words) - 1), max(0, chars_per_line - 20), -1):
                            if words[i] in '，。！？；：、\n\t ':
                                break_pos = i + 1
                                break
                        draw.text((padding, y), words[:break_pos], fill=(0, 0, 0), font=normal_font)
                        y += line_height
                        words = words[break_pos:].lstrip()
            y += section_spacing
        
        # 额外字段
        if extra_fields:
            draw.text((padding, y), "详细信息", fill=(102, 126, 234), font=heading_font)
            y += 40
            max_width = width - padding * 2
            for field_name, field_value in extra_fields.items():
                field_text = f"{field_name}：{str(field_value)}"
                field_lines = field_text.split('\n')
                for line in field_lines:
                    # 处理长文本自动换行
                    words = line
                    while len(words) > 0:
                        # 计算可以显示的字符数
                        char_width = draw.textlength(words[:1], font=normal_font)
                        if char_width == 0:
                            char_width = 10  # 默认字符宽度
                        chars_per_line = int(max_width / char_width) if char_width > 0 else 50
                        
                        if len(words) <= chars_per_line:
                            draw.text((padding, y), words, fill=(0, 0, 0), font=normal_font)
                            y += line_height
                            break
                        else:
                            # 尝试找到合适的断点（优先在空格、标点处断开）
                            break_pos = chars_per_line
                            for i in range(min(chars_per_line, len(words) - 1), max(0, chars_per_line - 20), -1):
                                if words[i] in '，。！？；：、\n\t ':
                                    break_pos = i + 1
                                    break
                            draw.text((padding, y), words[:break_pos], fill=(0, 0, 0), font=normal_font)
                            y += line_height
                            words = words[break_pos:].lstrip()
                y += 10
            y += section_spacing
        
        # 产品图片
        if product[2]:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], product[2])
            if os.path.exists(image_path):
                try:
                    draw.text((padding, y), "产品图片", fill=(102, 126, 234), font=heading_font)
                    y += 40
                    
                    product_img = PILImage.open(image_path)
                    max_width = 700
                    ratio = min(max_width / product_img.width, 500 / product_img.height)
                    new_width = int(product_img.width * ratio)
                    new_height = int(product_img.height * ratio)
                    product_img = product_img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
                    
                    img.paste(product_img, ((width - new_width) // 2, y))
                    y += new_height
                except Exception as e:
                    draw.text((padding, y), f"图片加载失败：{str(e)}", fill=(255, 0, 0), font=normal_font)
        
        # 保存到BytesIO
        img_buffer = BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        response = make_response(img_buffer.getvalue())
        response.headers['Content-Type'] = 'image/png'
        response.headers['Content-Disposition'] = f'attachment; filename=product_{code}_{datetime.now().strftime("%Y%m%d")}.png'
        return response
        
    except Exception as e:
        import traceback
        print(f'生成图片失败: {str(e)}')
        print(traceback.format_exc())
        return jsonify({'error': f'生成图片失败: {str(e)}'}), 500

@app.route('/api/products/<code>/share-link', methods=['GET'])
def get_share_link(code):
    """获取产品分享链接"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT code FROM products WHERE code = ?', (code,))
        product = c.fetchone()
        conn.close()
        
        if not product:
            return jsonify({'error': '产品不存在'}), 404
        
        share_url = url_for('view_product', code=code, _external=True)
        
        return jsonify({
            'success': True,
            'share_url': share_url,
            'code': code
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'获取分享链接失败: {str(e)}'}), 500

@app.route('/api/products/list', methods=['GET'])
@login_required
def list_products():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 获取分页参数
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    offset = (page - 1) * page_size
    
    # 支持搜索功能
    search = request.args.get('search', '').strip()
    
    # 获取总数
    if search:
        c.execute('''SELECT COUNT(*) FROM products 
                     WHERE code LIKE ? OR text_info LIKE ? OR extra_fields LIKE ?''', 
                 (f'%{search}%', f'%{search}%', f'%{search}%'))
    else:
        c.execute('SELECT COUNT(*) FROM products')
    
    total = c.fetchone()[0]
    
    # 获取分页数据
    if search:
        c.execute('''SELECT code, text_info, image_path, extra_fields, created_at FROM products 
                     WHERE code LIKE ? OR text_info LIKE ? OR extra_fields LIKE ?
                     ORDER BY created_at DESC LIMIT ? OFFSET ?''', 
                 (f'%{search}%', f'%{search}%', f'%{search}%', page_size, offset))
    else:
        c.execute('SELECT code, text_info, image_path, extra_fields, created_at FROM products ORDER BY created_at DESC LIMIT ? OFFSET ?',
                 (page_size, offset))
    
    products = c.fetchall()
    conn.close()
    
    product_list = []
    for p in products:
        # 解析extra_fields
        extra_fields = {}
        if p[3]:  # extra_fields列
            try:
                extra_fields = json.loads(p[3])
            except (json.JSONDecodeError, TypeError):
                extra_fields = {}
        
        product_list.append({
            'code': p[0],
            'text_info': p[1],
            'image_path': p[2],
            'extra_fields': extra_fields,
            'created_at': p[4],
            'view_url': url_for('view_product', code=p[0], _external=True)
        })
    
    return jsonify({
        'products': product_list,
        'total': total,
        'page': page,
        'page_size': page_size
    })

@app.route('/api/products/<code>', methods=['GET'])
@login_required
def get_product(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT code, text_info, image_path, extra_fields, created_at FROM products WHERE code = ?', (code,))
    product = c.fetchone()
    conn.close()
    
    if not product:
        return jsonify({'error': '产品不存在'}), 404
    
    # 解析extra_fields
    extra_fields = {}
    if product[3]:  # extra_fields列
        try:
            extra_fields = json.loads(product[3])
        except (json.JSONDecodeError, TypeError):
            extra_fields = {}
    
    return jsonify({
        'code': product[0],
        'text_info': product[1],
        'image_path': product[2],
        'extra_fields': extra_fields,
        'created_at': product[4],
        'view_url': url_for('view_product', code=product[0], _external=True)
    })

@app.route('/api/products/<code>', methods=['PUT'])
@login_required
def update_product(code):
    if not current_user.can_upload: # 修改也是upload权限
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 检查产品是否存在
        c.execute('SELECT image_path FROM products WHERE code = ?', (code,))
        product = c.fetchone()
        if not product:
            conn.close()
            return jsonify({'error': '产品不存在'}), 404
        
        old_image_path = product[0]
        text_info = request.form.get('text_info', '').strip()
        image_path = old_image_path
        
        # 处理图片上传
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                # 删除旧图片
                if old_image_path:
                    old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], old_image_path)
                    if os.path.exists(old_filepath):
                        try:
                            os.remove(old_filepath)
                        except Exception as e:
                            print(f'删除旧图片失败: {e}')
                
                # 保存新图片
                ext = os.path.splitext(file.filename)[1]
                filename = secure_filename(f"{code}{ext}")
                # Fallback for non-ascii codes
                if not filename or filename.startswith('.'):
                     filename = f"{code}{ext}"
                     import re
                     filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'images', filename)
                file.save(filepath)
                image_path = f"images/{filename}"
        
        # 更新数据库
        c.execute('''UPDATE products SET text_info = ?, image_path = ? WHERE code = ?''',
                 (text_info, image_path, code))
        conn.commit()
        conn.close()
        
        view_url = url_for('view_product', code=code, _external=True)
        
        return jsonify({
            'success': True,
            'message': '产品更新成功',
            'code': code,
            'text_info': text_info,
            'image_path': image_path,
            'view_url': view_url
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products', methods=['DELETE'])
@login_required
def delete_products():
    if not current_user.can_delete:
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        data = request.get_json()
        if not data or 'codes' not in data:
            return jsonify({'error': '缺少产品款号列表'}), 400
        
        codes = data.get('codes', [])
        if not codes or not isinstance(codes, list):
            return jsonify({'error': '产品款号列表格式错误'}), 400
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        deleted_count = 0
        deleted_codes = []
        
        for code in codes:
            # 获取产品信息，用于删除图片
            c.execute('SELECT image_path FROM products WHERE code = ?', (code,))
            product = c.fetchone()
            
            if product:
                # 删除图片文件
                if product[0]:
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], product[0])
                    if os.path.exists(image_path):
                        try:
                            os.remove(image_path)
                        except Exception as e:
                            print(f'删除图片失败 {code}: {e}')
                
                # 删除数据库记录
                c.execute('DELETE FROM products WHERE code = ?', (code,))
                deleted_count += 1
                deleted_codes.append(code)
        
        conn.commit()
        conn.close()
        
        if deleted_count == 0:
            return jsonify({'error': '没有找到要删除的产品'}), 404
        
        message = f'成功删除 {deleted_count} 个产品'
        if len(codes) > deleted_count:
            message += f'（共请求删除 {len(codes)} 个）'
        
        return jsonify({
            'success': True,
            'message': message,
            'deleted_count': deleted_count,
            'deleted_codes': deleted_codes
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@app.route('/api/images/upload', methods=['POST'])
@login_required
def upload_images():
    """批量上传图片，根据文件名自动匹配产品"""
    if not current_user.can_upload:
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        if 'images' not in request.files:
            return jsonify({'error': '未选择文件'}), 400
        
        files = request.files.getlist('images')
        if not files or all(f.filename == '' for f in files):
            return jsonify({'error': '未选择文件'}), 400
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        matched_count = 0
        pending_count = 0
        error_messages = []
        matched_codes = []
        
        for file in files:
            if not file.filename:
                continue
            
            if not allowed_file(file.filename):
                error_messages.append(f'{file.filename}: 文件格式不支持')
                continue
            
            # 从文件名提取款号（去掉扩展名）
            code = extract_code_from_filename(file.filename)
            if not code:
                error_messages.append(f'{file.filename}: 无法提取款号')
                continue
            
            # 检查产品是否存在
            c.execute('SELECT image_path FROM products WHERE code = ?', (code,))
            product = c.fetchone()
            
            if product:
                # 产品存在，更新图片
                old_image_path = product[0]
                
                # 删除旧图片
                if old_image_path:
                    old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], old_image_path)
                    if os.path.exists(old_filepath):
                        try:
                            os.remove(old_filepath)
                        except Exception as e:
                            print(f'删除旧图片失败 {code}: {e}')
                
                # 保存新图片
                ext = os.path.splitext(file.filename)[1]
                if not ext: ext = f".{file.filename.rsplit('.', 1)[1].lower()}" if '.' in file.filename else ''
                
                filename = secure_filename(f"{code}{ext}")
                # Fallback
                if not filename or filename.startswith('.'):
                     filename = f"{code}{ext}"
                     import re
                     filename = re.sub(r'[\\/*?:"<>|]', "", filename).strip()
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'images', filename)
                file.save(filepath)
                image_path = f"images/{filename}"
                
                # 更新数据库
                c.execute('UPDATE products SET image_path = ? WHERE code = ?', (image_path, code))
                matched_count += 1
                matched_codes.append(code)
            else:
                # 产品不存在，保存到待匹配目录
                pending_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'pending_images')
                filename = secure_filename(file.filename)
                filepath = os.path.join(pending_dir, filename)
                
                # 如果已存在同名文件，先删除
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception as e:
                        print(f'删除旧待匹配图片失败 {filename}: {e}')
                
                file.save(filepath)
                pending_count += 1
        
        conn.commit()
        conn.close()
        
        message_parts = []
        if matched_count > 0:
            message_parts.append(f'成功匹配并更新 {matched_count} 个产品的图片')
        if pending_count > 0:
            message_parts.append(f'{pending_count} 个图片已保存待匹配（产品不存在）')
        
        message = '；'.join(message_parts) if message_parts else '处理完成'
        
        return jsonify({
            'success': True,
            'message': message,
            'matched_count': matched_count,
            'pending_count': pending_count,
            'matched_codes': matched_codes,
            'errors': error_messages
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'上传失败: {str(e)}'}), 500

@app.route('/api/images/list', methods=['GET'])
@login_required
def list_images():
    """获取所有图片列表"""
    try:
        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 20, type=int)
        offset = (page - 1) * page_size
        
        all_images = []
        
        # 定义获取图片信息的辅助函数
        def scan_directory(dir_name, status_type):
            dir_path = os.path.join(app.config['UPLOAD_FOLDER'], dir_name)
            if os.path.exists(dir_path):
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if entry.is_file():
                            try:
                                stat = entry.stat()
                                all_images.append({
                                    'name': entry.name,
                                    'dir': dir_name,
                                    'path': f'{dir_name}/{entry.name}',
                                    'full_path': entry.path,
                                    'size': stat.st_size,
                                    'mtime': stat.st_mtime,
                                    'status': status_type
                                })
                            except OSError:
                                continue

        # 扫描两个目录
        scan_directory('images', 'matched')
        scan_directory('pending_images', 'pending')
        
        # 按时间倒序排序
        all_images.sort(key=lambda x: x['mtime'], reverse=True)
        
        # 获取总数
        total = len(all_images)
        
        # 分页切片
        paginated_images = all_images[offset : offset + page_size]
        
        # 提取当前页的图片路径，用于查询使用情况
        page_image_paths = [img['path'] for img in paginated_images]
        
        # 检查当前页图片的使用情况
        image_usage_map = {}
        if page_image_paths:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            placeholders = ','.join('?' for _ in page_image_paths)
            c.execute(f'SELECT image_path, code FROM products WHERE image_path IN ({placeholders})', page_image_paths)
            results = c.fetchall()
            conn.close()
            
            for path, code in results:
                image_usage_map[path] = code
        
        # 构建最终返回列表
        result_list = []
        for img in paginated_images:
            result_list.append({
                'filename': img['name'],
                'path': img['path'],
                'full_path': img['full_path'],
                'size': img['size'],
                'created_at': datetime.fromtimestamp(img['mtime']).strftime('%Y-%m-%d %H:%M:%S'),
                'status': img['status'],
                'used_by_product': image_usage_map.get(img['path'])
            })
        
        return jsonify({
            'success': True,
            'images': result_list,
            'total': total,
            'page': page,
            'page_size': page_size
        }), 200
        
    except Exception as e:
        import traceback
        print(f'获取图片列表失败: {str(e)}')
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': f'获取图片列表失败: {str(e)}',
            'images': [],
            'total': 0
        }), 500

@app.route('/api/images', methods=['DELETE'])
@login_required
def delete_images():
    """删除图片"""
    if not current_user.can_delete:
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        data = request.get_json()
        if not data or 'paths' not in data:
            return jsonify({'error': '缺少图片路径列表'}), 400
        
        paths = data.get('paths', [])
        if not paths or not isinstance(paths, list):
            return jsonify({'error': '图片路径列表格式错误'}), 400
        
        deleted_count = 0
        deleted_paths = []
        error_messages = []
        
        for path in paths:
            try:
                # 构建完整路径
                if path.startswith('images/') or path.startswith('pending_images/'):
                    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
                else:
                    full_path = os.path.join(app.config['UPLOAD_FOLDER'], path)
                
                if os.path.exists(full_path):
                    # 检查是否被产品使用
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute('SELECT code FROM products WHERE image_path = ?', (path,))
                    product = c.fetchone()
                    conn.close()
                    
                    if product:
                        # 如果被产品使用，同时更新数据库
                        conn = sqlite3.connect(DB_PATH)
                        c = conn.cursor()
                        c.execute('UPDATE products SET image_path = NULL WHERE image_path = ?', (path,))
                        conn.commit()
                        conn.close()
                    
                    # 删除文件
                    os.remove(full_path)
                    deleted_count += 1
                    deleted_paths.append(path)
                else:
                    error_messages.append(f'文件不存在: {path}')
            except Exception as e:
                error_messages.append(f'删除失败 {path}: {str(e)}')
        
        if deleted_count == 0:
            return jsonify({'error': '没有成功删除任何图片'}), 404
        
        message = f'成功删除 {deleted_count} 个图片'
        if len(paths) > deleted_count:
            message += f'（共请求删除 {len(paths)} 个）'
        
        return jsonify({
            'success': True,
            'message': message,
            'deleted_count': deleted_count,
            'deleted_paths': deleted_paths,
            'errors': error_messages
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@app.route('/api/products/all', methods=['DELETE'])
@login_required
def delete_all_products():
    if not current_user.can_delete:
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 获取所有产品图片路径
        c.execute('SELECT image_path FROM products WHERE image_path IS NOT NULL')
        rows = c.fetchall()
        
        deleted_images_count = 0
        for row in rows:
            image_path = row[0]
            if image_path:
                full_path = os.path.join(app.config['UPLOAD_FOLDER'], image_path)
                if os.path.exists(full_path):
                    try:
                        os.remove(full_path)
                        deleted_images_count += 1
                    except Exception as e:
                        print(f'删除图片失败: {e}')

        # 删除所有产品记录
        c.execute('DELETE FROM products')
        deleted_products_count = c.rowcount
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'成功删除所有产品（共 {deleted_products_count} 个），并清理了 {deleted_images_count} 张关联图片',
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

@app.route('/api/images/all', methods=['DELETE'])
@login_required
def delete_all_images():
    if not current_user.can_delete:
        return jsonify({'error': '无权限执行此操作'}), 403
    try:
        # 1. 扫描并删除所有图片文件
        deleted_count = 0
        
        # 定义要清理的目录
        dirs_to_clean = ['images', 'pending_images']
        
        for dir_name in dirs_to_clean:
            dir_path = os.path.join(app.config['UPLOAD_FOLDER'], dir_name)
            if os.path.exists(dir_path):
                for filename in os.listdir(dir_path):
                    file_path = os.path.join(dir_path, filename)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                        except Exception as e:
                            print(f'删除文件失败 {file_path}: {e}')
        
        # 2. 更新数据库，清空所有image_path
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE products SET image_path = NULL')
        updated_products_count = c.rowcount
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'成功删除所有图片（共 {deleted_count} 个），并更新了 {updated_products_count} 个产品的图片关联',
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
