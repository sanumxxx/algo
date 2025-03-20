from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SelectField, BooleanField, SubmitField, SelectMultipleField, FieldList, \
    FormField, HiddenField, TextAreaField
from wtforms.validators import DataRequired, NumberRange, Optional


# Подформа для подгруппы
class SubgroupForm(FlaskForm):
    size = IntegerField('Размер подгруппы', validators=[DataRequired(), NumberRange(min=1)])
    name = StringField('Название подгруппы', validators=[DataRequired()])


# Формы
class FacultyForm(FlaskForm):
    name = StringField('Название факультета', validators=[DataRequired()])
    description = TextAreaField('Описание')
    priority = IntegerField('Приоритет (1-10)', default=5, validators=[NumberRange(min=1, max=10)])
    submit = SubmitField('Сохранить')


class TeacherForm(FlaskForm):
    name = StringField('ФИО преподавателя', validators=[DataRequired()])
    preferred_days = SelectMultipleField('Предпочтительные дни',
                                         choices=[(0, 'Понедельник'), (1, 'Вторник'),
                                                  (2, 'Среда'), (3, 'Четверг'),
                                                  (4, 'Пятница')],
                                         coerce=int)
    preferred_time_slots = SelectMultipleField('Предпочтительные пары',
                                               choices=[(0, '8:00 - 9:20'), (1, '9:30 - 10:50'),
                                                        (2, '11:00 - 12:20'), (3, '12:40 - 14:00'),
                                                        (4, '14:10 - 15:30'), (5, '15:40 - 17:00'),
                                                        (6, '17:10 - 18:30')],
                                               coerce=int)
    max_lessons_per_day = IntegerField('Максимум пар в день', default=4,
                                       validators=[NumberRange(min=1, max=7)])
    notes = TextAreaField('Примечания')
    submit = SubmitField('Сохранить')


class GroupForm(FlaskForm):
    name = StringField('Название группы', validators=[DataRequired()])
    size = IntegerField('Численность', validators=[DataRequired(), NumberRange(min=1)])
    year_of_study = IntegerField('Курс (год обучения)', default=1, validators=[NumberRange(min=1, max=6)])
    faculty_id = SelectField('Факультет', coerce=int, validators=[Optional()])
    lab_subgroups_count = IntegerField('Количество подгрупп для лаб. работ', validators=[NumberRange(min=1, max=10)],
                                       default=1)
    max_lessons_per_day = IntegerField('Максимум пар в день', default=4, validators=[NumberRange(min=1, max=7)])
    preferred_time_slots = SelectMultipleField('Предпочтительные пары',
                                               choices=[(0, '8:00 - 9:20'), (1, '9:30 - 10:50'),
                                                        (2, '11:00 - 12:20'), (3, '12:40 - 14:00'),
                                                        (4, '14:10 - 15:30'), (5, '15:40 - 17:00'),
                                                        (6, '17:10 - 18:30')],
                                               coerce=int)
    submit = SubmitField('Сохранить')


class RoomForm(FlaskForm):
    name = StringField('Номер аудитории', validators=[DataRequired()])
    capacity = IntegerField('Вместимость', validators=[DataRequired(), NumberRange(min=1)])
    is_computer_lab = BooleanField('Компьютерный класс')
    is_lecture_hall = BooleanField('Лекционная аудитория')
    is_lab = BooleanField('Лабораторная')
    building = StringField('Корпус')
    floor = IntegerField('Этаж', validators=[Optional()])
    notes = TextAreaField('Примечания')
    submit = SubmitField('Сохранить')


class CourseForm(FlaskForm):
    name = StringField('Название дисциплины', validators=[DataRequired()])
    different_teachers = BooleanField('Разные преподаватели для типов занятий')
    lecture_teacher_id = SelectField('Преподаватель (лекции)', coerce=int)
    practice_teacher_id = SelectField('Преподаватель (практики)', coerce=int)
    lab_teacher_id = SelectField('Преподаватель (лабораторные)', coerce=int)
    lecture_count = IntegerField('Количество лекций', default=0)
    practice_count = IntegerField('Количество практик', default=0)
    lab_count = IntegerField('Количество лабораторных', default=0)
    start_week = IntegerField('Начальная неделя', validators=[DataRequired(), NumberRange(min=1)])
    distribution_type = SelectField('Распределение занятий', choices=[
        ('even', 'По частоте (1 пр. в неделю, 1 лекция в 2 недели)'),
        ('front_loaded', 'Больше занятий в начале семестра'),
        ('back_loaded', 'Больше занятий в конце семестра'),
        ('block', 'Блочное распределение (все занятия подряд)')
    ])
    priority = IntegerField('Приоритет (1-10)', default=5, validators=[NumberRange(min=1, max=10)])
    groups = SelectMultipleField('Группы', coerce=int, validators=[DataRequired()])
    preferred_rooms = SelectMultipleField('Предпочтительные аудитории', coerce=int)
    notes = TextAreaField('Примечания')
    submit = SubmitField('Сохранить')


class SettingsForm(FlaskForm):
    weeks_count = IntegerField('Количество недель', validators=[DataRequired(), NumberRange(min=1, max=52)])
    days_per_week = IntegerField('Дней в неделе', default=5, validators=[NumberRange(min=1, max=7)])
    slots_per_day = IntegerField('Пар в день', default=7, validators=[NumberRange(min=1, max=12)])
    avoid_windows = BooleanField('Избегать "окон" у студентов')
    prioritize_faculty = BooleanField('Учитывать приоритеты факультетов')
    respect_teacher_preferences = BooleanField('Учитывать предпочтения преподавателей')
    optimize_room_usage = BooleanField('Оптимизировать использование аудиторий')
    max_lessons_per_day_global = IntegerField('Глобальный максимум пар в день', default=4)
    preferred_lesson_distribution = SelectField('Предпочтительное распределение пар', choices=[
        ('balanced', 'Сбалансированное'),
        ('morning', 'Преимущественно утренние пары'),
        ('afternoon', 'Преимущественно дневные пары')
    ])
    submit = SubmitField('Сохранить')


class ManualScheduleItemForm(FlaskForm):
    course_id = SelectField('Дисциплина', coerce=int, validators=[DataRequired()])
    teacher_id = SelectField('Преподаватель', coerce=int, validators=[DataRequired()])
    room_id = SelectField('Аудитория', coerce=int, validators=[DataRequired()])
    week = IntegerField('Неделя', validators=[DataRequired(), NumberRange(min=1)])
    day = SelectField('День', coerce=int, choices=[(0, 'Понедельник'), (1, 'Вторник'),
                                                   (2, 'Среда'), (3, 'Четверг'),
                                                   (4, 'Пятница')], validators=[DataRequired()])
    time_slot = SelectField('Пара', coerce=int, choices=[(0, '8:00 - 9:20'), (1, '9:30 - 10:50'),
                                                         (2, '11:00 - 12:20'), (3, '12:40 - 14:00'),
                                                         (4, '14:10 - 15:30'), (5, '15:40 - 17:00'),
                                                         (6, '17:10 - 18:30')], validators=[DataRequired()])
    lesson_type = SelectField('Тип занятия', choices=[('lecture', 'Лекция'),
                                                      ('practice', 'Практика'),
                                                      ('lab', 'Лабораторная')])
    groups = SelectMultipleField('Группы', coerce=int, validators=[DataRequired()])
    lab_subgroup_id = SelectField('Подгруппа (для лабораторных)', coerce=int, validators=[Optional()])
    notes = TextAreaField('Примечания')
    submit = SubmitField('Сохранить')