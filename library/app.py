from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    session,
    send_from_directory,
    flash,
    jsonify,
    Response
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from datetime import datetime, timedelta
import os
import hashlib
import bleach
import markdown2
import csv
from io import StringIO
from models import db, User, Book, Review, ViewHistory, Genre, Cover
from forms import LoginForm, BookForm, ReviewForm
from config import Config
from utils import allowed_file, save_cover, sanitize_description, generate_csv
from forms import ProfileForm
from models import db, Role, Genre  # Добавьте явный импорт
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_wtf.csrf import CSRFProtect
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Ваш секретный ключ
app.config.from_object(Config)  # Загрузка остальных настроек

# Инициализация CSRF после создания приложения
csrf = CSRFProtect(app)
# app = Flask(__name__)
# app.config.from_object(Config)
# Инициализация расширений

migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Для выполнения данного действия необходимо пройти аутентификацию'
login_manager.login_message_category = 'info'

# Инициализация SQLAlchemy после настройки config
db.init_app(app)

with app.app_context():
    db.create_all()

    # Инициализация ролей
    if not Role.query.first():
        Role.initialize_default_roles()
        print("Роли успешно созданы")

    # Инициализация жанров
    if not Genre.query.first():
        Genre.initialize_defaults()
        print("Жанры успешно созданы")

    db.session.commit()

    default_genres = [
        "Фантастика", "Детектив", "Роман",
        "Научная литература", "Исторический", "Триллер",
        "Фэнтези", "Приключения", "Ужасы", "Поэзия",
        "Драма", "Комедия", "Биография", "Публицистика",
        "Техническая литература", "Детская литература",
        "Мистика", "Классика", "Современная проза", "Психология"
    ]

    for genre_name in default_genres:
        if not Genre.query.filter_by(name=genre_name).first():
            db.session.add(Genre(name=genre_name))
    db.session.commit()
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Маршруты
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    books = Book.query.options(
        db.joinedload(Book.genres),
        db.joinedload(Book.cover)
    ).order_by(Book.year.desc()).paginate(page=page, per_page=10)

    # Получаем популярные книги (за последние 3 месяца)
    three_months_ago = datetime.utcnow() - timedelta(days=90)
    popular_books = db.session.query(
        Book,  # <-- Вместо Book.id, Book.title
        db.func.count(ViewHistory.id).label('views')
    ).join(ViewHistory).filter(
        ViewHistory.viewed_at >= three_months_ago
    ).group_by(Book.id).order_by(db.desc('views')).limit(5).all()

    # Получаем недавно просмотренные книги для анонимных пользователей
    recent_views = session.get('recent_views', [])

    # Получаем историю просмотров для аутентифицированных пользователей
    user_recent_views = []
    if current_user.is_authenticated:
        user_recent_views = ViewHistory.query.filter_by(user_id=current_user.id).order_by(
            ViewHistory.viewed_at.desc()
        ).limit(5).all()

    return render_template('index.html',
                           books=books,
                           popular_books=popular_books,
                           recent_views=recent_views,
                           user_recent_views=user_recent_views,
                           Book=Book,
                           markdown=markdown2.markdown)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect(url_for('index'))
        flash('Неверный логин или пароль', 'danger')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/book/<int:book_id>')
def book_detail(book_id):
    book = Book.query.options(
        db.joinedload(Book.genres),
        db.joinedload(Book.cover),
        db.joinedload(Book.reviews)
    ).get_or_404(book_id)

    try:
        # Атомарное обновление счетчика просмотров
        db.session.query(Book).filter_by(id=book.id).update(
            {Book.view_count: Book.view_count + 1},
            synchronize_session=False
        )

        if current_user.is_authenticated:
            today = datetime.utcnow().date()
            existing_views = ViewHistory.query.filter(
                db.func.date(ViewHistory.viewed_at) == today,
                ViewHistory.user_id == current_user.id,
                ViewHistory.book_id == book.id
            ).count()

            if existing_views < 10:
                db.session.add(ViewHistory(
                    user_id=current_user.id,
                    book_id=book.id
                ))

        else:
            recent_views = session.get('recent_views', [])
            if book.id in recent_views:
                recent_views.remove(book.id)
            recent_views.insert(0, book.id)
            session['recent_views'] = recent_views[:10]

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error tracking view: {str(e)}")

    related_books = Book.query.filter(
        Book.author == book.author,
        Book.id != book.id
    ).limit(4).all()

    return render_template(
        'book_detail.html',
        book=book,
        user_review=Review.query.filter_by(
            book_id=book.id,
            user_id=current_user.id if current_user.is_authenticated else None
        ).first(),
        related_books=related_books,
        markdown=markdown2.markdown
    )

@app.route('/add_book', methods=['GET', 'POST'])
@login_required
def add_book():
    if not current_user.role.name in ['Администратор', 'Модератор']:
        flash('У вас недостаточно прав', 'warning')
        return redirect(url_for('index'))

    form = BookForm()
    form.genres.choices = [(g.id, g.name) for g in Genre.query.all()]

    if form.validate_on_submit():
        try:
            # 1. Создаем книгу без обложки
            book = Book(
                title=form.title.data,
                description=sanitize_description(form.description.data),
                year=form.year.data,
                publisher=form.publisher.data,
                author=form.author.data,
                pages=form.pages.data
            )

            # 2. Добавляем жанры
            genre_ids = [int(g_id) for g_id in request.form.getlist('genres')]
            book.genres = Genre.query.filter(Genre.id.in_(genre_ids)).all()

            # 3. Сохраняем книгу чтобы получить ID
            db.session.add(book)
            db.session.commit()

            # 4. Обработка обложки после сохранения книги
            if form.cover.data:
                # Валидация файла
                if not allowed_file(form.cover.data.filename):
                    flash('Недопустимый формат файла', 'danger')
                    return render_template('book_form.html', form=form, action='add')

                # Сохранение файла
                cover_file = form.cover.data
                filename = secure_filename(cover_file.filename)
                cover_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                cover_file.save(cover_path)

                # Создание записи обложки
                cover = Cover(
                    filename=filename,
                    mime_type=cover_file.mimetype,
                    md5_hash=hashlib.md5(open(cover_path, 'rb').read()).hexdigest(),
                    book_id=book.id  # Явная привязка к книге
                )
                db.session.add(cover)
                db.session.commit()

            flash('Книга успешно добавлена', 'success')
            return redirect(url_for('book_detail', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка: {str(e)}', 'danger')
            return render_template('book_form.html', form=form, action='add')

    return render_template('book_form.html', form=form, action='add')


@app.route('/edit_book/<int:book_id>', methods=['GET', 'POST'])
@login_required
def edit_book(book_id):
    if not current_user.role.name in ['Администратор', 'Модератор']:
        flash('У вас недостаточно прав', 'warning')
        return redirect(url_for('index'))

    book = Book.query.get_or_404(book_id)
    form = BookForm(obj=book)
    form.genres.choices = [(g.id, g.name) for g in Genre.query.all()]

    if request.method == 'GET':
        form.genres.data = [g.id for g in book.genres]

    if form.validate_on_submit():
        try:
            # Обновляем только простые поля (без cover)
            book.title = form.title.data
            book.description = sanitize_description(form.description.data)
            book.year = form.year.data
            book.publisher = form.publisher.data
            book.author = form.author.data
            book.pages = form.pages.data

            # Обработка обложки
            if form.cover.data and isinstance(form.cover.data, FileStorage):
                if book.cover:
                    # Удаляем старую обложку
                    old_cover = book.cover
                    db.session.delete(old_cover)
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], old_cover.filename))

                # Сохраняем новую обложку
                cover_file = form.cover.data
                filename = secure_filename(cover_file.filename)
                cover_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                cover_file.save(cover_path)

                # Создаем новую запись обложки
                new_cover = Cover(
                    filename=filename,
                    mime_type=cover_file.mimetype,
                    md5_hash=hashlib.md5(open(cover_path, 'rb').read()).hexdigest()
                )
                db.session.add(new_cover)
                book.cover = new_cover

            # Обновляем жанры
            genre_ids = [int(g_id) for g_id in request.form.getlist('genres')]
            book.genres = Genre.query.filter(Genre.id.in_(genre_ids)).all()

            db.session.commit()
            flash('Книга успешно обновлена', 'success')
            return redirect(url_for('book_detail', book_id=book.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка: {str(e)}', 'danger')
            return render_template('book_form.html', form=form, action='edit', book=book)

    return render_template('book_form.html', form=form, action='edit', book=book)


@app.route('/delete_book/<int:book_id>', methods=['POST'])
@login_required
@csrf.exempt
def delete_book(book_id):
    if current_user.role.name != 'Администратор':
        flash('У вас недостаточно прав', 'danger')
        return redirect(url_for('index'))

    book = Book.query.get_or_404(book_id)

    try:
        # Удаляем связанные файлы
        if book.cover:
            cover_path = os.path.join(app.config['UPLOAD_FOLDER'], book.cover.filename)
            if os.path.exists(cover_path):
                os.remove(cover_path)

        # Удаляем саму книгу (каскад удалит связанные записи)
        db.session.delete(book)
        db.session.commit()
        flash('Книга и все связанные данные успешно удалены', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления: {str(e)}', 'danger')
        app.logger.error(f"Delete book error: {str(e)}")

    return redirect(url_for('index'))


@app.route('/add_review/<int:book_id>', methods=['GET', 'POST'])
@login_required
def add_review(book_id):
    if current_user.role.name not in ['Пользователь', 'Модератор', 'Администратор']:
        flash('У вас недостаточно прав для выполнения данного действия', 'warning')
        return redirect(url_for('index'))

    book = Book.query.get_or_404(book_id)

    # Проверяем, не оставил ли пользователь рецензию
    user_review = Review.query.filter_by(book_id=book_id, user_id=current_user.id).first()
    if user_review:
        flash('Вы уже оставили рецензию на эту книгу', 'info')
        return redirect(url_for('book_detail', book_id=book_id))

    form = ReviewForm()
    if form.validate_on_submit():
        try:
            # Обработка рецензии
            sanitized_text = sanitize_description(form.text.data)

            review = Review(
                book_id=book_id,
                user_id=current_user.id,
                rating=form.rating.data,
                text=sanitized_text
            )

            db.session.add(review)
            db.session.commit()

            flash('Рецензия успешно добавлена', 'success')
            return redirect(url_for('book_detail', book_id=book_id))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при добавлении рецензии', 'danger')
            print(f"Ошибка при добавлении рецензии: {str(e)}")

    return render_template('review_form.html', form=form, book_id=book_id)


@app.route('/stats')
@login_required
def stats():
    if current_user.role.name != 'Администратор':
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('index'))

    tab = request.args.get('tab', 'actions')
    page = request.args.get('page', 1, type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    if tab == 'actions':
        # Журнал действий с фильтрацией по дате
        query = ViewHistory.query.options(
            db.joinedload(ViewHistory.viewer),
            db.joinedload(ViewHistory.book)
        ).order_by(ViewHistory.viewed_at.desc())

        # Применяем фильтры даты
        if date_from:
            query = query.filter(ViewHistory.viewed_at >= date_from)
        if date_to:
            query = query.filter(ViewHistory.viewed_at <= f"{date_to} 23:59:59")

        actions = query.paginate(page=page, per_page=10)
        return render_template('stats_actions.html',
                               actions=actions,
                               tab=tab,
                               date_from=date_from,
                               date_to=date_to)

    elif tab == 'book_stats':
        # Статистика по книгам с использованием общего счетчика просмотров
        query = Book.query.options(
            db.joinedload(Book.genres),
            db.joinedload(Book.cover)
        ).order_by(Book.views.desc())

        # Фильтр по дате для авторизованных просмотров
        if date_from or date_to:
            subquery = ViewHistory.query.filter(
                ViewHistory.user_id.isnot(None),
                ViewHistory.book_id == Book.id
            )
            if date_from:
                subquery = subquery.filter(ViewHistory.viewed_at >= date_from)
            if date_to:
                subquery = subquery.filter(ViewHistory.viewed_at <= f"{date_to} 23:59:59")

            query = query.add_columns(
                Book.views,
                db.func.coalesce(subquery.count(), 0).label('auth_views')
            )
        else:
            query = query.add_columns(
                Book.views,
                db.func.coalesce(
                    db.session.query(db.func.count(ViewHistory.id))
                    .filter(ViewHistory.book_id == Book.id)
                    .filter(ViewHistory.user_id.isnot(None))
                    .scalar_subquery(),
                    0
                ).label('auth_views')
            )

        stats = query.paginate(page=page, per_page=10)
        max_views = Book.query.with_entities(db.func.max(Book.views)).scalar() or 1

        return render_template('stats_books.html',
                               books=stats,
                               max_views=max_views,
                               tab=tab,
                               date_from=date_from,
                               date_to=date_to)

    return redirect(url_for('stats', tab='actions'))


@app.route('/export_csv/<string:export_type>')
@login_required
def export_csv(export_type):
    if current_user.role.name != 'Администратор':
        flash('У вас недостаточно прав для выполнения данного действия', 'warning')
        return redirect(url_for('index'))

    if export_type == 'actions':
        headers = ['№', 'ФИО пользователя', 'Книга', 'Дата просмотра']
        actions = ViewHistory.query.options(
            db.joinedload(ViewHistory.viewer),
            db.joinedload(ViewHistory.book)
        ).order_by(ViewHistory.viewed_at.desc()).all()

        data = []
        for i, action in enumerate(actions, 1):
            user_name = "Неаутентифицированный"
            if action.user_id:
                if action.viewer:
                    user_name = f"{action.viewer.last_name} {action.viewer.first_name}"
                else:
                    user_name = "Удаленный пользователь"
            book_title = action.book.title if action.book else "Книга удалена"
            data.append([
                i,
                user_name,
                book_title,
                action.viewed_at.strftime("%Y-%m-%d %H:%M:%S")
            ])


    elif export_type == 'book_stats':
        headers = ['№', 'Книга', 'Всего просмотров', 'Просмотров авторизованными']
        books = Book.query.options(
            db.joinedload(Book.view_history)
        ).order_by(Book.view_count.desc()).all()  # Сортировка по view_count
        data = []
        for i, book in enumerate(books, 1):
            auth_views = sum(1 for v in book.view_history if v.user_id is not None)
            data.append([
                i,
                book.title,
                book.view_count,  # Используем переименованное поле
                auth_views
            ])

        data.sort(key=lambda x: x[2], reverse=True)

    else:
        flash('Некорректный тип экспорта', 'danger')
        return redirect(url_for('stats'))

    output = generate_csv(data, headers)
    filename = f"{export_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@app.route('/clear_recent_views')
def clear_recent_views():
    session['recent_views'] = []
    flash('История просмотров очищена', 'info')
    return redirect(url_for('index'))


# API маршруты
@app.route('/api/book/<int:book_id>/rating', methods=['GET'])
def get_book_rating(book_id):
    book = Book.query.get_or_404(book_id)
    reviews = book.reviews
    if not reviews:
        return jsonify({'rating': None, 'count': 0})

    rating = sum(review.rating for review in reviews) / reviews.count()
    return jsonify({
        'book_id': book_id,
        'rating': round(rating, 1),
        'count': reviews.count()
    })


@app.route('/api/book/<int:book_id>/check_view', methods=['GET'])
@login_required
def check_book_view(book_id):
    twentyfour_hours_ago = datetime.utcnow() - timedelta(hours=24)
    view = ViewHistory.query.filter_by(user_id=current_user.id, book_id=book_id).filter(
        ViewHistory.viewed_at >= twentyfour_hours_ago
    ).first()
    return jsonify({'has_view': bool(view)})


@app.route('/api/book/<int:book_id>/related_books', methods=['GET'])
def get_related_books(book_id):
    book = Book.query.get_or_404(book_id)

    # Получаем книги того же автора
    related_books = Book.query.filter(
        Book.author == book.author,
        Book.id != book_id
    ).all()

    return jsonify([{
        'id': b.id,
        'title': b.title,
        'year': b.year,
        'genres': [g.name for g in b.genres]
    } for b in related_books])


@app.route('/api/book/<int:book_id>/check_review', methods=['GET'])
@login_required
def check_book_review_handler(book_id):  # Уникальное имя
    user_review = Review.query.filter_by(book_id=book_id, user_id=current_user.id).first()
    return jsonify({
        'book_id': book_id,
        'has_review': bool(user_review)
    })


@app.route('/api/books/popular', methods=['GET'])
def get_popular_books():
    three_months_ago = datetime.utcnow() - timedelta(days=90)
    popular_books = db.session.query(
        Book.id,
        Book.title,
        db.func.count(ViewHistory.id).label('views')
    ).join(ViewHistory).filter(
        ViewHistory.viewed_at >= three_months_ago
    ).group_by(Book.id).order_by(db.desc('views')).limit(5).all()

    return jsonify([{
        'id': pb.id,
        'title': pb.title,
        'views': pb.views
    } for pb in popular_books])


@app.route('/api/book/<int:book_id>/users_who_viewed', methods=['GET'])
@login_required
def get_users_who_viewed(book_id):
    if current_user.role.name != 'Администратор':
        return jsonify({'error': 'Недостаточно прав'}), 403

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    users = User.query.join(User.history).filter(
        ViewHistory.book_id == book_id,
        ViewHistory.viewed_at >= thirty_days_ago
    ).distinct().all()

    return jsonify([{
        'id': u.id,
        'name': f"{u.last_name} {u.first_name}"
    } for u in users])

@app.route('/api/book/<int:book_id>/update', methods=['POST'])
@login_required
def update_book_api(book_id):
    if not current_user.role.name in ['Администратор', 'Модератор']:
        return jsonify({'error': 'У вас недостаточно прав для выполнения данного действия'}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных для обновления'}), 400

        book = Book.query.get_or_404(book_id)

        # Обновляем поля книги
        if 'title' in data:
            book.title = data['title']
        if 'description' in data:
            book.description = sanitize_description(data['description'])
        if 'year' in data:
            book.year = data['year']
        if 'publisher' in data:
            book.publisher = data['publisher']
        if 'author' in data:
            book.author = data['author']
        if 'pages' in data:
            book.pages = data['pages']

        # Обновление жанров
        if 'genre_ids' in data:
            genre_ids = data['genre_ids']
            book.genres = Genre.query.filter(Genre.id.in_(genre_ids)).all()

        db.session.commit()
        return jsonify({'success': 'Книга успешно обновлена'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'При обновлении книги произошла ошибка'}), 500


@app.route('/api/book/<int:book_id>/add_review', methods=['POST'])
@login_required
def add_api_review(book_id):
    if current_user.role.name not in ['Пользователь', 'Модератор', 'Администратор']:
        return jsonify({'error': 'Недостаточно прав для оставления рецензии'}), 403

    try:
        existing_review = Review.query.filter_by(book_id=book_id, user_id=current_user.id).first()
        if existing_review:
            return jsonify({'error': 'Вы уже оставили рецензию на эту книгу'}), 403

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных для рецензии'}), 400

        sanitized_text = sanitize_description(data.get('text', ''))
        review = Review(
            book_id=book_id,
            user_id=current_user.id,
            rating=data.get('rating', 5),
            text=sanitized_text
        )

        db.session.add(review)
        db.session.commit()
        return jsonify({'success': 'Рецензия успешно добавлена'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Ошибка при добавлении рецензии'}), 500


@app.route('/api/book/<int:book_id>/check_view', methods=['GET'])
def check_book_view_api(book_id):
    if not current_user.is_authenticated:
        return jsonify({'error': 'Необходимо войти в систему'}), 401

    twentyfour_hours_ago = datetime.utcnow() - timedelta(hours=24)
    view = ViewHistory.query.filter_by(user_id=current_user.id, book_id=book_id).filter(
        ViewHistory.viewed_at >= twentyfour_hours_ago
    ).first()

    return jsonify({'has_view': bool(view)})


@app.route('/api/recent_views', methods=['GET'])
def get_recent_views():
    """Получает список недавних просмотров"""
    recent_views = session.get('recent_views', [])
    return jsonify({
        'recent_views': recent_views
    })


@app.route('/api/recent_views', methods=['POST'])
def add_to_recent_views():
    """Добавляет книгу в историю просмотров"""
    if current_user.is_authenticated:
        return jsonify({'error': 'Для аутентифицированных пользователей история ведется отдельно'}), 400

    try:
        data = request.get_json()
        book_id = data.get('book_id')
        if not book_id:
            return jsonify({'error': 'Не указан ID книги'}), 400

        recent_views = session.get('recent_views', [])

        # Удаляем старое вхождение
        if book_id in recent_views:
            recent_views.remove(book_id)

        # Добавляем в начало списка
        recent_views.insert(0, book_id)

        # Ограничиваем 10 просмотрами в день
        if len(recent_views) > 10:
            recent_views = recent_views[:10]

        session['recent_views'] = recent_views
        return jsonify({'success': 'Книга добавлена в историю просмотров'})
    except Exception as e:
        return jsonify({'error': 'Ошибка при добавлении в историю просмотров'}), 500


@app.route('/api/book/<int:book_id>/check_review', methods=['GET'])
def check_book_review_api(book_id):
    if not current_user.is_authenticated:
        return jsonify({'error': 'Необходимо войти в систему'}), 401

    user_review = Review.query.filter_by(book_id=book_id, user_id=current_user.id).first()
    return jsonify({
        'book_id': book_id,
        'has_review': bool(user_review)
    })


def is_view_duplicate(user_id, book_id):
    """Проверяет, просматривал ли пользователь книгу за последние 24 часа"""
    if not user_id:
        return False

    twentyfour_hours_ago = datetime.utcnow() - timedelta(hours=24)
    existing = ViewHistory.query.filter(
        ViewHistory.user_id == user_id,
        ViewHistory.book_id == book_id,
        ViewHistory.viewed_at >= twentyfour_hours_ago
    ).first()
    return bool(existing)


@app.route('/profile')
@login_required
def profile():
    user = current_user
    recent_views = ViewHistory.query.filter_by(user_id=user.id).order_by(
        ViewHistory.viewed_at.desc()
    ).limit(5).all()
    return render_template('profile.html',
                         user=user,
                         recent_views=recent_views)

# app.py
@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        try:
            # Обновляем данные пользователя
            form.populate_obj(current_user)
            db.session.commit()
            flash('Профиль успешно обновлен', 'success')
            return redirect(url_for('profile'))
        except Exception as e:
            db.session.rollback()
            flash('Ошибка при обновлении профиля', 'danger')
    return render_template('profile_form.html', form=form)