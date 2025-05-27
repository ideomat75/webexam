import os
import hashlib
from flask import current_app
import bleach
from io import StringIO
import csv


# -------------------------
# Функции для работы с файлами
# -------------------------

def allowed_file(filename):
    """Проверяет, разрешено ли расширение файла"""
    ALLOWED_EXTENSIONS = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif'})
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_cover(file):
    """Сохраняет обложку и возвращает её метаданные"""
    if not file:
        return None

    # Читаем файл и вычисляем MD5-хэш
    file_content = file.read()
    md5_hash = hashlib.md5(file_content).hexdigest()
    file.seek(0)  # Возвращаем указатель в начало файла для последующего сохранения

    # Проверяем, существует ли файл с таким же хэшем
    from models import Cover
    existing_cover = Cover.query.filter_by(md5_hash=md5_hash).first()
    if existing_cover:
        return existing_cover

    # Генерируем уникальное имя файла
    from models import db
    cover_count = Cover.query.count()
    filename = f"{cover_count + 1}{os.path.splitext(file.filename)[1]}"
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)

    # Сохраняем файл
    file.save(file_path)

    # Создаем запись в БД
    cover = Cover(
        filename=filename,
        mime_type=file.mimetype,
        md5_hash=md5_hash
    )
    db.session.add(cover)
    db.session.flush()
    return cover


# -------------------------
# Функции для санитизации данных
# -------------------------

def sanitize_description(text):
    """Очищает описание книги от потенциально опасных тегов"""
    return bleach.clean(text, tags=[])


# -------------------------
# Функции для работы с сессиями
# -------------------------

def add_to_recent_views(book_id):
    """Добавляет книгу в список недавно просмотренных для анонимного пользователя"""
    recent_views = current_app.config.get('recent_views', [])
    if book_id not in recent_views:
        recent_views.insert(0, book_id)
        if len(recent_views) > 5:
            recent_views.pop()
        current_app.config['recent_views'] = recent_views


# -------------------------
# Функции для экспорта в CSV
# -------------------------

def generate_csv(data, headers):
    """Генерирует CSV-файл из данных"""
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(headers)
    cw.writerows(data)
    return si.getvalue()