from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired
from models import db, User, DetectionRecord
from werkzeug.security import generate_password_hash, check_password_hash
from inference import predict_pneumonia
from datetime import datetime
import os
import csv
from io import StringIO

# 初始化Flask应用
app = Flask(__name__)
app.secret_key = 'your-secret-key-123'  # 必须设置且保持唯一

# 数据库配置
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(base_dir, "instance", "database.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# 初始化数据库
db.init_app(app)

# 自动创建目录
with app.app_context():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(base_dir, 'static', 'results'), exist_ok=True)

# 表单定义
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    submit = SubmitField('登录')

class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    submit = SubmitField('注册')

class ResetPasswordForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    new_password = PasswordField('新密码', validators=[DataRequired()])
    submit = SubmitField('重置密码')

# 路由定义
@app.route('/')
def welcome():
    return render_template('welcome.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            session['user_id'] = user.id
            return redirect(url_for('detect'))
        flash('用户名或密码错误')
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        new_user = User(username=form.username.data)
        new_user.set_password(form.password.data)
        db.session.add(new_user)
        db.session.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            user.set_password(form.new_password.data)
            db.session.commit()
            flash('密码已重置')
            return redirect(url_for('login'))
        flash('用户名不存在')
    return render_template('reset_password.html', form=form)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('welcome'))

@app.route('/detect', methods=['GET', 'POST'])
def detect():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('未选择文件')
            return redirect(request.url)
        file = request.files['image']
        if file.filename == '':
            flash('未选择文件')
            return redirect(request.url)
        
        # 添加文件格式验证
        allowed_extensions = {'png', 'jpg', 'jpeg'}
        if '.' not in file.filename or file.filename.split('.')[-1].lower() not in allowed_extensions:
            flash('仅支持PNG/JPG/JPEG格式')
            return redirect(request.url)
        
        # 保存文件
        filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        
        # 预测并保存结果
        result_img, statistics = predict_pneumonia(save_path)
        # 修正图片路径存储方式
        relative_path = f"results/{os.path.basename(result_img)}"
        new_record = DetectionRecord(
            user_id=session['user_id'],
            image_path=relative_path,  # 改为存储相对路径
            result=str(statistics),
            detection_time=datetime.now()
        )
        db.session.add(new_record)
        db.session.commit()
        
        # 修改结果返回方式
        return render_template('detect.html', 
                             result=statistics, 
                             image=url_for('static', filename=f'results/{os.path.basename(result_img)}'))
    
    return render_template('detect.html')

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    records = DetectionRecord.query.filter_by(user_id=session['user_id']).all()
    for record in records:
        try:
            # 加强结果解析
            result_data = eval(record.result)
            if not isinstance(result_data, dict):
                raise ValueError("无效的结果格式")
            record.result = {
                '诊断结果': result_data.get('诊断结果', '未知'),
                '病灶数量': result_data.get('病灶数量', 0),
                '最大置信度': result_data.get('最大置信度', '0%'),
                '平均置信度': result_data.get('平均置信度', '0%')
            }
        except Exception as e:
            print(f"解析记录{record.id}失败: {str(e)}")
            record.result = {
                'error': '结果解析失败',
                'raw_data': record.result[:50]  # 显示原始数据前50个字符
            }
    return render_template('history.html', records=records)

@app.route('/delete_record/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    record = DetectionRecord.query.get_or_404(record_id)
    if record.user_id != session['user_id']:
        flash('无权操作')
        return redirect(url_for('history'))
    
    try:
        # 修正文件删除路径
        full_path = os.path.join(app.root_path, 'static', record.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        db.session.delete(record)
        db.session.commit()
        flash('记录删除成功')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}')
    
    return redirect(url_for('history'))

@app.route('/export_history')
def export_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # 获取当前用户的历史记录
    records = DetectionRecord.query.filter_by(user_id=session['user_id']).all()
    
    # 创建内存文件对象
    csv_data = StringIO()
    writer = csv.writer(csv_data)
    
    # 写入CSV头部
    writer.writerow(['检测时间', '诊断结果', '病灶数量', '最大置信度', '平均置信度', '图片路径'])
    
    # 写入数据行
    for record in records:
        try:
            result = eval(record.result)
            writer.writerow([
                record.detection_time.strftime('%Y-%m-%d %H:%M'),
                result.get('诊断结果', ''),
                result.get('病灶数量', 0),
                result.get('最大置信度', '0%'),
                result.get('平均置信度', '0%'),
                url_for('static', filename=record.image_path, _external=True)
            ])
        except:
            continue
    
    # 创建响应对象
    from flask import make_response
    response = make_response(csv_data.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = 'attachment; filename=detection_history.csv'
    
    return response

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=False)