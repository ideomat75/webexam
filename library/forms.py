from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, IntegerField, FileField, SelectMultipleField, SelectField, \
    PasswordField, BooleanField
from wtforms.validators import DataRequired, NumberRange, Length, ValidationError
from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
from werkzeug.datastructures import FileStorage

def allowed_file(filename):
    """Проверяет, является ли файл изображением"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class LoginForm(FlaskForm):
    """Форма входа в систему"""
    username = StringField('Логин', validators=[
        DataRequired(message='Введите логин'),
        Length(min=3, max=80, message='Логин должен быть от 3 до 80 символов')
    ])
    password = PasswordField('Пароль', validators=[
        DataRequired(message='Введите пароль')
    ])
    remember_me = BooleanField('Запомнить меня')

    def validate_password(self, field):
        """Дополнительная проверка пароля"""
        if len(field.data) < 6:
            raise ValidationError('Пароль должен содержать минимум 6 символов')


class BookForm(FlaskForm):
    """Форма для добавления/редактирования книги"""
    title = StringField('Название', validators=[
        DataRequired(message='Введите название книги'),
        Length(max=200, message='Название не должно превышать 200 символов')
    ])

    description = TextAreaField('Описание', validators=[
        DataRequired(message='Введите описание книги'),
        Length(max=5000, message='Описание не должно превышать 5000 символов')
    ])

    year = IntegerField('Год', validators=[
        DataRequired(message='Введите год издания'),
        NumberRange(min=1000, max=9999, message='Год должен быть в диапазоне от 1000 до 9999')
    ])

    publisher = StringField('Издательство', validators=[
        DataRequired(message='Введите издательство'),
        Length(max=100, message='Издательство не должно превышать 100 символов')
    ])

    author = StringField('Автор', validators=[
        DataRequired(message='Введите имя автора'),
        Length(max=100, message='Имя автора не должно превышать 100 символов')
    ])

    pages = IntegerField('Количество страниц', validators=[
        DataRequired(message='Введите количество страниц'),
        NumberRange(min=1, max=10000, message='Количество страниц должно быть от 1 до 10000')
    ])

    cover = FileField('Обложка')

    genres = SelectMultipleField(
        'Жанры',
        coerce=int,
        choices=[],
        validators=[
            DataRequired(message='Выберите хотя бы один жанр')
        ]
    )

    def validate_cover(self, field):
        # Проверяем, что поле содержит файл (FileStorage), а не объект Cover
        if isinstance(field.data, FileStorage):
            # Проверяем расширение файла
            filename = field.data.filename.lower()
            if not allowed_file(filename):
                raise ValidationError('Недопустимый тип файла. Поддерживаются: png, jpg, jpeg, gif')

            # Сбрасываем позицию файлового курсора
            field.data.seek(0)
        # Если это не файл (например, существующий объект Cover), пропускаем проверку

    def validate_year(self, field):
        current_year = datetime.now().year
        if field.data > current_year + 1:
            raise ValidationError(f'Год не может превышать {current_year + 1}')

class ReviewForm(FlaskForm):
    """Форма для рецензии"""
    rating = SelectField('Оценка', choices=[
        (5, '5 – отлично'),
        (4, '4 – хорошо'),
        (3, '3 – удовлетворительно'),
        (2, '2 – неудовлетворительно'),
        (1, '1 – плохо'),
        (0, '0 – ужасно')
    ], coerce=int, validators=[
        DataRequired(message='Выберите оценку')
    ])

    text = TextAreaField('Текст рецензии', validators=[
        DataRequired(message='Введите текст рецензии'),
        Length(max=10000, message='Рецензия не должна превышать 10000 символов')
    ])

    def validate_rating(self, field):
        """Проверяет, что оценка в допустимом диапазоне"""
        if field.data is None or field.data < 0 or field.data > 5:
            raise ValidationError('Оценка должна быть от 0 до 5')

class ProfileForm(FlaskForm):
    first_name = StringField('Имя', validators=[DataRequired()])
    last_name = StringField('Фамилия', validators=[DataRequired()])
    middle_name = StringField('Отчество')
    submit = SubmitField('Сохранить')