import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///moods.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.secret_key = 'change_this_secret_key'

db = SQLAlchemy(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EMOJIS = {1: '😞', 2: '😐', 3: '🙂', 4: '😄', 5: '😁'}

class Mood(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), nullable=False, default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M'))
    level = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(500), nullable=True)
    image = db.Column(db.String(255), nullable=True)

    def to_dict(self, include_image_url=False):
        data = {
            'id': self.id,
            'date': self.date,
            'level': self.level,
            'emoji': EMOJIS.get(self.level, '?'),
            'note': self.note
        }
        if include_image_url and self.image:
            data['image_url'] = url_for('static', filename=f'uploads/{self.image}', _external=True)
        return data

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def handle_image_upload():
    file = request.files.get('image')
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        raise ValueError("Недопустимый формат. Разрешены: png, jpg, jpeg, gif, webp")
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return filename

# Routes
@app.route('/')
def index():
    moods = Mood.query.order_by(Mood.date.desc()).limit(10).all()
    return render_template('index.html', moods=moods, emojis=EMOJIS)

@app.route('/add', methods=['POST'])
def add_mood():
    level = request.form.get('level', type=int)
    note = request.form.get('note', '').strip()
    
    if level not in EMOJIS:
        flash('⚠️ Выберите настроение перед сохранением.', 'error')
        return redirect(url_for('index'))
        
    try:
        filename = handle_image_upload()
    except ValueError as e:
        flash(f'⚠️ {e}', 'error')
        return redirect(url_for('index'))

    db.session.add(Mood(level=level, note=note, image=filename))
    db.session.commit()
    flash('Успешно сохранено!', 'success')
    return redirect(url_for('index'))

@app.route('/history')
def history():
    moods = Mood.query.order_by(Mood.date.desc()).all()
    return render_template('history.html', moods=moods, emojis=EMOJIS)

@app.route('/delete/<int:mood_id>')
def delete_mood(mood_id):
    mood = Mood.query.get_or_404(mood_id)
    if mood.image:
        path = os.path.join(app.config['UPLOAD_FOLDER'], mood.image)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(mood)
    db.session.commit()
    flash('Запись удалена.', 'info')
    return redirect(url_for('history'))

# Api
@app.route('/api/moods', methods=['GET'])
def api_get_moods():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    level = request.args.get('level', type=int)

    stmt = db.select(Mood).order_by(Mood.date.desc())
    if level:
        stmt = stmt.filter_by(level=level)
        
    pagination = db.paginate(stmt, page=page, per_page=per_page, error_out=False)
    moods = [m.to_dict(include_image_url=True) for m in pagination.items]

    return jsonify({
        'data': moods,
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages
        }
    })

@app.route('/api/moods/<int:mood_id>', methods=['GET'])
def api_get_mood(mood_id):
    mood = Mood.query.get_or_404(mood_id)
    return jsonify(mood.to_dict(include_image_url=True))

@app.route('/api/moods', methods=['POST'])
def api_create_mood():
    # Поддержка JSON и multipart/form-data
    if request.content_type and 'multipart/form-data' in request.content_type:
        level = request.form.get('level', type=int)
        note = request.form.get('note', '').strip()
    else:
        data = request.get_json(silent=True) or {}
        level = data.get('level')
        note = str(data.get('note', '')).strip()

    if level not in EMOJIS:
        return jsonify({'error': 'Неверный уровень настроения (1-5)'}), 400

    try:
        filename = handle_image_upload()
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    mood = Mood(level=level, note=note, image=filename)
    db.session.add(mood)
    db.session.commit()
    return jsonify(mood.to_dict(include_image_url=True)), 201

@app.route('/api/moods/<int:mood_id>', methods=['PUT', 'PATCH'])
def api_update_mood(mood_id):
    mood = Mood.query.get_or_404(mood_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Требуется JSON тело запроса'}), 400

    if 'level' in data:
        if data['level'] not in EMOJIS:
            return jsonify({'error': 'Неверный уровень настроения'}), 400
        mood.level = data['level']
    if 'note' in data:
        mood.note = data['note']
        
    db.session.commit()
    return jsonify(mood.to_dict(include_image_url=True))

@app.route('/api/moods/<int:mood_id>', methods=['DELETE'])
def api_delete_mood(mood_id):
    mood = Mood.query.get_or_404(mood_id)
    if mood.image:
        path = os.path.join(app.config['UPLOAD_FOLDER'], mood.image)
        if os.path.exists(path):
            os.remove(path)
    db.session.delete(mood)
    db.session.commit()
    return jsonify({'message': 'Запись удалена'}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)