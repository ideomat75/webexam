from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import check_password_hash
from sqlalchemy import String, Date, Index

db = SQLAlchemy()


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)

    @classmethod
    def initialize_default_roles(cls):
        roles = [
            ('Администратор', 'Полный доступ к системе'),
            ('Модератор', 'Редактирование книг и модерация'),
            ('Пользователь', 'Базовые функции')
        ]
        for name, desc in roles:
            if not cls.query.filter_by(name=name).first():
                db.session.add(cls(name=name, description=desc))
        db.session.commit()

    def __repr__(self):
        return f'<Role {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    middle_name = db.Column(db.String(50))
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    role = db.relationship('Role', backref='users')
    reviews = db.relationship('Review', backref='user', lazy='dynamic')
    viewed_books = db.relationship('ViewHistory', back_populates='viewer', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.username}>'

    def check_role(self, role_name):
        return self.role.name == role_name

    def get_full_name(self):
        return f"{self.last_name} {self.first_name} {self.middle_name}" if self.middle_name else f"{self.last_name} {self.first_name}"

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Genre(db.Model):
    __tablename__ = 'genres'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)

    DEFAULT_GENRES = [
        "Фантастика", "Детектив", "Роман",
        "Научная литература", "Исторический", "Триллер",
        "Фэнтези", "Приключения", "Ужасы", "Поэзия",
        "Драма", "Комедия", "Биография", "Публицистика",
        "Техническая литература", "Детская литература",
        "Мистика", "Классика", "Современная проза", "Психология"
    ]

    @classmethod
    def initialize_defaults(cls):
        for name in cls.DEFAULT_GENRES:
            if not cls.query.filter_by(name=name).first():
                db.session.add(cls(name=name))
        db.session.commit()


book_genre = db.Table('book_genres',
                      db.Column('book_id', db.Integer, db.ForeignKey('books.id'), primary_key=True),
                      db.Column('genre_id', db.Integer, db.ForeignKey('genres.id'), primary_key=True)
                      )


class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    year = db.Column(db.Integer, nullable=False, index=True)
    publisher = db.Column(db.String(100), nullable=False)
    author = db.Column(db.String(100), nullable=False, index=True)
    pages = db.Column(db.Integer, nullable=False)
    view_count = db.Column(db.Integer, default=0)

    # Relationships
    cover = db.relationship('Cover', uselist=False, backref='book', cascade='all, delete-orphan')
    genres = db.relationship('Genre', secondary=book_genre, backref='books')
    reviews = db.relationship('Review', backref='book', cascade='all, delete-orphan')
    view_history = db.relationship('ViewHistory', back_populates='book', cascade='all, delete-orphan')

    def get_rating(self):
        if not self.reviews:
            return None
        return sum(review.rating for review in self.reviews) / len(self.reviews)

    def __repr__(self):
        return f'<Book {self.title}>'

    def get_reviews_count(self):
        return len(self.reviews)

    def get_views_count(self):
        return self.view_count


class Cover(db.Model):
    __tablename__ = 'covers'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100))
    md5_hash = db.Column(String(32), unique=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id', ondelete='CASCADE'), unique=True, nullable=False)


class Review(db.Model):
    __tablename__ = 'reviews'
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ViewHistory(db.Model):
    __tablename__ = 'view_history'
    __table_args__ = (
        Index('ix_view_history_user_book_date', 'user_id', 'book_id', 'viewed_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    viewed_date = db.Column(db.Date, default=datetime.utcnow, nullable=False)

    viewer = db.relationship('User', back_populates='viewed_books')
    book = db.relationship('Book', back_populates='view_history')