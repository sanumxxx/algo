from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SelectField, BooleanField, SubmitField, SelectMultipleField, FieldList, \
    FormField, HiddenField, TextAreaField
from wtforms.validators import DataRequired, NumberRange, Optional
from flask_wtf.csrf import CSRFProtect
from datetime import datetime, timedelta
import random
import copy
import os
import math
import time
import json
from collections import defaultdict

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///schedule.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
csrf = CSRFProtect(app)


# Модели данных
class Faculty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    priority = db.Column(db.Integer, default=5)  # Приоритет факультета (1-10, где 10 - наивысший)
    groups = relationship("Group", back_populates="faculty", cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Faculty {self.name}>'


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Изменено отношение с курсами
    courses = relationship("CourseTeacher", back_populates="teacher")
    # Добавлены новые поля для предпочтений
    preferred_days = db.Column(db.String(20), default="0,1,2,3,4")  # Предпочтительные дни (индексы)
    preferred_time_slots = db.Column(db.String(20), default="0,1,2,3,4,5,6")  # Предпочтительные пары
    max_lessons_per_day = db.Column(db.Integer, default=4)  # Максимум пар в день
    notes = db.Column(db.Text, nullable=True)  # Примечания

    def __repr__(self):
        return f'<Teacher {self.name}>'

    def get_preferred_days_list(self):
        if not self.preferred_days:
            return []
        return [int(day) for day in self.preferred_days.split(',')]

    def get_preferred_time_slots_list(self):
        if not self.preferred_time_slots:
            return []
        return [int(slot) for slot in self.preferred_time_slots.split(',')]


class LabSubgroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    subgroup_number = db.Column(db.Integer, nullable=False)  # Номер подгруппы
    name = db.Column(db.String(50), nullable=False)  # Название (например "ПГ-1")
    size = db.Column(db.Integer, nullable=False)  # Размер подгруппы

    group = relationship("Group", back_populates="lab_subgroups")
    course_teachers = relationship("CourseTeacher", back_populates="lab_subgroup")

    def __repr__(self):
        return f'<LabSubgroup {self.name} (Group: {self.group.name})>'


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    year_of_study = db.Column(db.Integer, default=1)  # Курс (год обучения)
    lab_subgroups_count = db.Column(db.Integer, default=1)  # Количество подгрупп для лабораторных
    courses = relationship("CourseGroup", back_populates="group")
    lab_subgroups = relationship("LabSubgroup", back_populates="group", cascade="all, delete-orphan")
    # Добавлено поле для связи с факультетом
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.id'), nullable=True)
    faculty = relationship("Faculty", back_populates="groups")
    # Настройки расписания для группы
    max_lessons_per_day = db.Column(db.Integer, default=4)  # Максимум пар в день
    preferred_time_slots = db.Column(db.String(20), default="0,1,2,3,4,5,6")  # Предпочтительные пары

    def __repr__(self):
        return f'<Group {self.name}>'

    def create_subgroups(self):
        """Создает подгруппы на основе указанного количества"""
        # Удаляем существующие подгруппы
        LabSubgroup.query.filter_by(group_id=self.id).delete()

        # Если количество подгрупп 1 или меньше, не создаем подгруппы
        if self.lab_subgroups_count <= 1:
            return

        # Рассчитываем размер каждой подгруппы
        base_size = self.size // self.lab_subgroups_count
        remainder = self.size % self.lab_subgroups_count

        # Создаем подгруппы
        for i in range(1, self.lab_subgroups_count + 1):
            subgroup_size = base_size + (1 if i <= remainder else 0)
            subgroup = LabSubgroup(
                group_id=self.id,
                subgroup_number=i,
                name=f"ПГ-{i}",
                size=subgroup_size
            )
            db.session.add(subgroup)

    def has_lab_subgroups(self):
        """Проверяет, разделена ли группа на подгруппы для лабораторных"""
        return self.lab_subgroups_count > 1

    def get_preferred_time_slots_list(self):
        if not self.preferred_time_slots:
            return []
        return [int(slot) for slot in self.preferred_time_slots.split(',')]


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    is_computer_lab = db.Column(db.Boolean, default=False)
    is_lecture_hall = db.Column(db.Boolean, default=False)
    is_lab = db.Column(db.Boolean, default=False)
    building = db.Column(db.String(50), nullable=True)  # Корпус
    floor = db.Column(db.Integer, nullable=True)  # Этаж
    notes = db.Column(db.Text, nullable=True)  # Примечания

    def __repr__(self):
        return f'<Room {self.name}>'


# Связь между курсами и предпочтительными аудиториями
course_preferred_rooms = db.Table('course_preferred_rooms',
                                  db.Column('course_id', db.Integer, db.ForeignKey('course.id'), primary_key=True),
                                  db.Column('room_id', db.Integer, db.ForeignKey('room.id'), primary_key=True)
                                  )


# Модель для связи курса с преподавателями по типам занятий и подгруппам
class CourseTeacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    lesson_type = db.Column(db.String(10), nullable=False)  # 'lecture', 'practice', 'lab'
    lab_subgroup_id = db.Column(db.Integer, db.ForeignKey('lab_subgroup.id'), nullable=True)

    course = relationship("Course", back_populates="course_teachers")
    teacher = relationship("Teacher", back_populates="courses")
    lab_subgroup = relationship("LabSubgroup", back_populates="course_teachers")

    def __repr__(self):
        subgroup_info = f" - {self.lab_subgroup.name}" if self.lab_subgroup else ""
        return f'<CourseTeacher {self.course.name} - {self.teacher.name} - {self.lesson_type}{subgroup_info}>'


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    lecture_count = db.Column(db.Integer, default=0)
    practice_count = db.Column(db.Integer, default=0)
    lab_count = db.Column(db.Integer, default=0)
    start_week = db.Column(db.Integer, default=1)
    distribution_type = db.Column(db.String(20), default='even')  # even, front_loaded, back_loaded, etc.
    priority = db.Column(db.Integer, default=5)  # Приоритет курса (1-10, где 10 - наивысший)
    groups = relationship("CourseGroup", back_populates="course")
    course_teachers = relationship("CourseTeacher", back_populates="course", cascade="all, delete-orphan")
    schedule_items = relationship("ScheduleItem", back_populates="course")
    preferred_rooms = relationship("Room", secondary=course_preferred_rooms,
                                   backref=db.backref('preferred_for_courses', lazy='dynamic'))
    notes = db.Column(db.Text, nullable=True)  # Примечания

    def __repr__(self):
        return f'<Course {self.name}>'

    def get_teacher_for_type(self, lesson_type, lab_subgroup_id=None):
        """Получить преподавателя для определенного типа занятий и подгруппы (если указана)"""
        query = CourseTeacher.query.filter_by(course_id=self.id, lesson_type=lesson_type)

        if lesson_type == 'lab' and lab_subgroup_id:
            query = query.filter_by(lab_subgroup_id=lab_subgroup_id)
        elif lesson_type == 'lab':
            query = query.filter(CourseTeacher.lab_subgroup_id == None)

        course_teacher = query.first()
        return course_teacher.teacher if course_teacher else None

    def get_teacher_name_for_type(self, lesson_type, lab_subgroup_id=None):
        """Получить имя преподавателя для определенного типа занятий и подгруппы (если указана)"""
        teacher = self.get_teacher_for_type(lesson_type, lab_subgroup_id)
        return teacher.name if teacher else "Не назначен"

    def get_all_lab_teachers(self):
        """Получить всех преподавателей лабораторных работ для курса с учетом подгрупп"""
        return CourseTeacher.query.filter_by(course_id=self.id, lesson_type='lab').all()

    # Метод для вычисления эффективного приоритета на основе приоритета курса и факультетов групп
    def get_effective_priority(self):
        if not self.groups:
            return self.priority

        # Находим факультеты групп курса
        faculties = []
        for course_group in self.groups:
            if course_group.group.faculty:
                faculties.append(course_group.group.faculty)

        if not faculties:
            return self.priority

        # Вычисляем средний приоритет всех факультетов
        faculty_priority = sum(f.priority for f in faculties) / len(faculties)

        # Комбинируем приоритет курса и факультетов (можно настроить формулу)
        return (self.priority * 0.7) + (faculty_priority * 0.3)


class CourseGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    course = relationship("Course", back_populates="groups")
    group = relationship("Group", back_populates="courses")

    def __repr__(self):
        return f'<CourseGroup {self.course.name} - {self.group.name}>'


class ScheduleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    course = relationship("Course", back_populates="schedule_items")
    room = relationship("Room")
    week = db.Column(db.Integer, nullable=False)
    day = db.Column(db.Integer, nullable=False)  # 0-4 (Понедельник-Пятница)
    time_slot = db.Column(db.Integer, nullable=False)  # 0-7 (пары в день)
    lesson_type = db.Column(db.String(10), nullable=False)  # lecture, practice, lab
    groups = db.Column(db.String, nullable=False)  # Сериализованный список ID групп
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=True)
    teacher = relationship("Teacher")
    lab_subgroup_id = db.Column(db.Integer, db.ForeignKey('lab_subgroup.id'), nullable=True)
    lab_subgroup = relationship("LabSubgroup")
    is_manually_placed = db.Column(db.Boolean, default=False)  # Флаг для ручного размещения
    notes = db.Column(db.Text, nullable=True)  # Примечания

    def __repr__(self):
        subgroup_info = f" ({self.lab_subgroup.name})" if self.lab_subgroup else ""
        return f'<ScheduleItem {self.course.name}{subgroup_info} - Week {self.week}, Day {self.day}, Slot {self.time_slot}>'

    def get_group_ids(self):
        return [int(g) for g in self.groups.split(',')]

    def to_dict(self):
        """Преобразует объект ScheduleItem в словарь для API"""
        return {
            'id': self.id,
            'course_id': self.course_id,
            'course_name': self.course.name,
            'room_id': self.room_id,
            'room_name': self.room.name,
            'week': self.week,
            'day': self.day,
            'time_slot': self.time_slot,
            'lesson_type': self.lesson_type,
            'groups': self.groups,
            'teacher_id': self.teacher_id,
            'teacher_name': self.teacher.name if self.teacher else None,
            'lab_subgroup_id': self.lab_subgroup_id,
            'lab_subgroup_name': self.lab_subgroup.name if self.lab_subgroup else None,
            'is_manually_placed': self.is_manually_placed,
            'notes': self.notes
        }


class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    weeks_count = db.Column(db.Integer, default=18)
    days_per_week = db.Column(db.Integer, default=5)
    slots_per_day = db.Column(db.Integer, default=7)
    # Добавлены новые поля настроек
    avoid_windows = db.Column(db.Boolean, default=True)  # Избегать "окон" у студентов
    prioritize_faculty = db.Column(db.Boolean, default=True)  # Учитывать приоритеты факультетов
    respect_teacher_preferences = db.Column(db.Boolean, default=True)  # Учитывать предпочтения преподавателей
    optimize_room_usage = db.Column(db.Boolean, default=True)  # Оптимизировать использование аудиторий
    max_lessons_per_day_global = db.Column(db.Integer, default=4)  # Глобальный максимум пар в день
    preferred_lesson_distribution = db.Column(db.String(20), default='balanced')  # balanced, morning, afternoon
    version = db.Column(db.Integer, default=1)  # Версия расписания для отслеживания изменений

    def __repr__(self):
        return f'<Settings weeks={self.weeks_count}>'


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


# Маршруты
@app.route('/')
def index():
    settings = Settings.query.first()
    if not settings:
        settings = Settings(weeks_count=18)
        db.session.add(settings)
        db.session.commit()

    teacher_count = Teacher.query.count()
    group_count = Group.query.count()
    room_count = Room.query.count()
    course_count = Course.query.count()
    faculty_count = Faculty.query.count()
    schedule_exists = ScheduleItem.query.first() is not None

    return render_template('index.html',
                           settings=settings,
                           teacher_count=teacher_count,
                           group_count=group_count,
                           room_count=room_count,
                           course_count=course_count,
                           faculty_count=faculty_count,
                           schedule_exists=schedule_exists)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    settings_record = Settings.query.first()
    if not settings_record:
        settings_record = Settings(weeks_count=18)
        db.session.add(settings_record)
        db.session.commit()

    form = SettingsForm(obj=settings_record)

    if form.validate_on_submit():
        form.populate_obj(settings_record)
        # Увеличиваем версию при каждом обновлении настроек
        settings_record.version += 1
        db.session.commit()
        flash('Настройки успешно сохранены!', 'success')
        return redirect(url_for('index'))

    return render_template('settings.html', form=form)


# Маршруты для факультетов
@app.route('/faculties')
def faculties_list():
    faculties = Faculty.query.all()
    return render_template('faculties_list.html', faculties=faculties)


@app.route('/faculties/add', methods=['GET', 'POST'])
def add_faculty():
    form = FacultyForm()
    if form.validate_on_submit():
        faculty = Faculty(
            name=form.name.data,
            description=form.description.data,
            priority=form.priority.data
        )
        db.session.add(faculty)
        db.session.commit()
        flash('Факультет успешно добавлен!', 'success')
        return redirect(url_for('faculties_list'))
    return render_template('faculty_form.html', form=form, title='Добавить факультет')


@app.route('/faculties/edit/<int:id>', methods=['GET', 'POST'])
def edit_faculty(id):
    faculty = Faculty.query.get_or_404(id)
    form = FacultyForm(obj=faculty)
    if form.validate_on_submit():
        form.populate_obj(faculty)
        db.session.commit()
        flash('Данные факультета обновлены!', 'success')
        return redirect(url_for('faculties_list'))
    return render_template('faculty_form.html', form=form, title='Редактировать факультет')


@app.route('/faculties/delete/<int:id>')
def delete_faculty(id):
    faculty = Faculty.query.get_or_404(id)
    db.session.delete(faculty)
    db.session.commit()
    flash('Факультет удален!', 'success')
    return redirect(url_for('faculties_list'))


@app.route('/teachers')
def teachers_list():
    teachers = Teacher.query.all()
    return render_template('teachers_list.html', teachers=teachers)


@app.route('/teachers/add', methods=['GET', 'POST'])
def add_teacher():
    form = TeacherForm()
    if form.validate_on_submit():
        # Преобразуем списки дней и слотов в строки
        preferred_days = ','.join(map(str, form.preferred_days.data)) if form.preferred_days.data else ''
        preferred_time_slots = ','.join(
            map(str, form.preferred_time_slots.data)) if form.preferred_time_slots.data else ''

        teacher = Teacher(
            name=form.name.data,
            preferred_days=preferred_days,
            preferred_time_slots=preferred_time_slots,
            max_lessons_per_day=form.max_lessons_per_day.data,
            notes=form.notes.data
        )
        db.session.add(teacher)
        db.session.commit()
        flash('Преподаватель успешно добавлен!', 'success')
        return redirect(url_for('teachers_list'))
    return render_template('teacher_form.html', form=form, title='Добавить преподавателя')


@app.route('/teachers/edit/<int:id>', methods=['GET', 'POST'])
def edit_teacher(id):
    teacher = Teacher.query.get_or_404(id)
    form = TeacherForm(obj=teacher)

    # Заполняем значения множественных селекторов
    if request.method == 'GET':
        form.preferred_days.data = teacher.get_preferred_days_list()
        form.preferred_time_slots.data = teacher.get_preferred_time_slots_list()

    if form.validate_on_submit():
        teacher.name = form.name.data
        teacher.preferred_days = ','.join(map(str, form.preferred_days.data)) if form.preferred_days.data else ''
        teacher.preferred_time_slots = ','.join(
            map(str, form.preferred_time_slots.data)) if form.preferred_time_slots.data else ''
        teacher.max_lessons_per_day = form.max_lessons_per_day.data
        teacher.notes = form.notes.data

        db.session.commit()
        flash('Данные преподавателя обновлены!', 'success')
        return redirect(url_for('teachers_list'))
    return render_template('teacher_form.html', form=form, title='Редактировать преподавателя')


@app.route('/teachers/delete/<int:id>')
def delete_teacher(id):
    teacher = Teacher.query.get_or_404(id)
    db.session.delete(teacher)
    db.session.commit()
    flash('Преподаватель удален!', 'success')
    return redirect(url_for('teachers_list'))


@app.route('/groups')
def groups_list():
    groups = Group.query.all()
    return render_template('groups_list.html', groups=groups)


@app.route('/groups/add', methods=['GET', 'POST'])
def add_group():
    form = GroupForm()

    # Заполняем список факультетов
    faculties = Faculty.query.all()
    faculty_choices = [(0, 'Нет')] + [(f.id, f.name) for f in faculties]
    form.faculty_id.choices = faculty_choices

    if form.validate_on_submit():
        # Преобразуем предпочтительные слоты в строку
        preferred_time_slots = ','.join(
            map(str, form.preferred_time_slots.data)) if form.preferred_time_slots.data else ''

        faculty_id = form.faculty_id.data if form.faculty_id.data != 0 else None

        group = Group(
            name=form.name.data,
            size=form.size.data,
            year_of_study=form.year_of_study.data,
            faculty_id=faculty_id,
            lab_subgroups_count=form.lab_subgroups_count.data,
            max_lessons_per_day=form.max_lessons_per_day.data,
            preferred_time_slots=preferred_time_slots
        )
        db.session.add(group)
        db.session.flush()  # Получаем ID без коммита

        # Создаем подгруппы если нужно
        group.create_subgroups()

        db.session.commit()
        flash('Группа успешно добавлена!', 'success')
        return redirect(url_for('groups_list'))
    return render_template('group_form.html', form=form, title='Добавить группу')


@app.route('/groups/edit/<int:id>', methods=['GET', 'POST'])
def edit_group(id):
    group = Group.query.get_or_404(id)
    form = GroupForm(obj=group)

    # Заполняем список факультетов
    faculties = Faculty.query.all()
    faculty_choices = [(0, 'Нет')] + [(f.id, f.name) for f in faculties]
    form.faculty_id.choices = faculty_choices

    # Предварительно заполняем поля формы
    if request.method == 'GET':
        form.faculty_id.data = group.faculty_id if group.faculty_id else 0
        form.preferred_time_slots.data = group.get_preferred_time_slots_list()

    if form.validate_on_submit():
        # Запоминаем старое количество подгрупп
        old_subgroups_count = group.lab_subgroups_count

        # Обновляем основные данные группы
        group.name = form.name.data
        group.size = form.size.data
        group.year_of_study = form.year_of_study.data
        group.faculty_id = form.faculty_id.data if form.faculty_id.data != 0 else None
        group.lab_subgroups_count = form.lab_subgroups_count.data
        group.max_lessons_per_day = form.max_lessons_per_day.data
        group.preferred_time_slots = ','.join(
            map(str, form.preferred_time_slots.data)) if form.preferred_time_slots.data else ''

        # Если изменилось количество подгрупп, перестраиваем их
        if old_subgroups_count != group.lab_subgroups_count:
            group.create_subgroups()

        db.session.commit()
        flash('Данные группы обновлены!', 'success')
        return redirect(url_for('groups_list'))

    return render_template('group_form.html', form=form, title='Редактировать группу')


@app.route('/groups/delete/<int:id>')
def delete_group(id):
    group = Group.query.get_or_404(id)
    db.session.delete(group)
    db.session.commit()
    flash('Группа удалена!', 'success')
    return redirect(url_for('groups_list'))


@app.route('/groups/get_subgroups/<int:id>')
def get_group_subgroups(id):
    """API для получения подгрупп группы"""
    group = Group.query.get_or_404(id)
    subgroups = []

    if group.has_lab_subgroups():
        for subgroup in group.lab_subgroups:
            subgroups.append({
                'id': subgroup.id,
                'name': subgroup.name,
                'size': subgroup.size
            })

    return jsonify(subgroups)


@app.route('/rooms')
def rooms_list():
    rooms = Room.query.all()
    return render_template('rooms_list.html', rooms=rooms)


@app.route('/rooms/add', methods=['GET', 'POST'])
def add_room():
    form = RoomForm()
    if form.validate_on_submit():
        room = Room(
            name=form.name.data,
            capacity=form.capacity.data,
            is_computer_lab=form.is_computer_lab.data,
            is_lecture_hall=form.is_lecture_hall.data,
            is_lab=form.is_lab.data,
            building=form.building.data,
            floor=form.floor.data,
            notes=form.notes.data
        )
        db.session.add(room)
        db.session.commit()
        flash('Аудитория успешно добавлена!', 'success')
        return redirect(url_for('rooms_list'))
    return render_template('room_form.html', form=form, title='Добавить аудиторию')


@app.route('/rooms/edit/<int:id>', methods=['GET', 'POST'])
def edit_room(id):
    room = Room.query.get_or_404(id)
    form = RoomForm(obj=room)
    if form.validate_on_submit():
        form.populate_obj(room)
        db.session.commit()
        flash('Данные аудитории обновлены!', 'success')
        return redirect(url_for('rooms_list'))
    return render_template('room_form.html', form=form, title='Редактировать аудиторию')


@app.route('/rooms/delete/<int:id>')
def delete_room(id):
    room = Room.query.get_or_404(id)
    db.session.delete(room)
    db.session.commit()
    flash('Аудитория удалена!', 'success')
    return redirect(url_for('rooms_list'))


@app.route('/courses')
def courses_list():
    courses = Course.query.all()
    return render_template('courses_list.html', courses=courses)


@app.route('/courses/add', methods=['GET', 'POST'])
def add_course():
    form = CourseForm()
    # Заполняем списки выбора
    form.lecture_teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]
    form.practice_teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]
    form.lab_teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]

    # Добавляем информацию о подгруппах к группам
    groups = Group.query.all()
    form.groups.choices = []
    for g in groups:
        faculty_info = f" ({g.faculty.name})" if g.faculty else ""
        has_subgroups = " (с подгруппами)" if g.has_lab_subgroups() else ""
        form.groups.choices.append((g.id, f"{g.name}{faculty_info}{has_subgroups}"))

    form.preferred_rooms.choices = [(r.id, f"{r.name} (вместимость: {r.capacity})") for r in Room.query.all()]

    if form.validate_on_submit():
        print("\n=== ОТЛАДКА: ДОБАВЛЕНИЕ ДИСЦИПЛИНЫ ===")
        print(f"Название: {form.name.data}")

        # Создаем объект курса
        course = Course(
            name=form.name.data,
            lecture_count=form.lecture_count.data,
            practice_count=form.practice_count.data,
            lab_count=form.lab_count.data,
            start_week=form.start_week.data,
            distribution_type=form.distribution_type.data,
            priority=form.priority.data,
            notes=form.notes.data
        )
        db.session.add(course)
        db.session.flush()  # Получаем ID курса без коммита

        # Связываем курс с группами
        selected_groups = []
        for group_id in form.groups.data:
            course_group = CourseGroup(course_id=course.id, group_id=group_id)
            db.session.add(course_group)
            selected_groups.append(Group.query.get(group_id))

        # Сохраняем преподавателей для каждого типа занятий
        teachers_added = []

        # Лекции
        if form.lecture_count.data > 0 and form.lecture_teacher_id.data:
            lecture_teacher_id = form.lecture_teacher_id.data
            print(f"Добавление преподавателя лекций: ID={lecture_teacher_id}")
            ct = CourseTeacher(
                course_id=course.id,
                teacher_id=lecture_teacher_id,
                lesson_type='lecture'
            )
            db.session.add(ct)
            teacher_name = Teacher.query.get(lecture_teacher_id).name
            teachers_added.append(f"лекции: {teacher_name}")

        # Практики
        if form.practice_count.data > 0 and form.practice_teacher_id.data:
            practice_teacher_id = form.practice_teacher_id.data
            print(f"Добавление преподавателя практик: ID={practice_teacher_id}")
            ct = CourseTeacher(
                course_id=course.id,
                teacher_id=practice_teacher_id,
                lesson_type='practice'
            )
            db.session.add(ct)
            teacher_name = Teacher.query.get(practice_teacher_id).name
            teachers_added.append(f"практики: {teacher_name}")

        # Лабораторные
        if form.lab_count.data > 0:
            # Проверяем, есть ли группы с подгруппами среди выбранных
            has_subgroups = False
            for group in selected_groups:
                if group.has_lab_subgroups():
                    has_subgroups = True
                    break

            if has_subgroups:
                # Собираем преподавателей для каждой подгруппы из формы
                for group in selected_groups:
                    if group.has_lab_subgroups():
                        for subgroup in group.lab_subgroups:
                            teacher_id = request.form.get(f'lab_teacher_id_{subgroup.id}')
                            if teacher_id and int(teacher_id) > 0:
                                ct = CourseTeacher(
                                    course_id=course.id,
                                    teacher_id=int(teacher_id),
                                    lesson_type='lab',
                                    lab_subgroup_id=subgroup.id
                                )
                                db.session.add(ct)
                                teacher_name = Teacher.query.get(int(teacher_id)).name
                                teachers_added.append(f"лабораторные ({subgroup.name}): {teacher_name}")
                    else:
                        # Для групп без подгрупп используем общего преподавателя
                        if form.lab_teacher_id.data:
                            ct = CourseTeacher(
                                course_id=course.id,
                                teacher_id=form.lab_teacher_id.data,
                                lesson_type='lab'
                            )
                            db.session.add(ct)
                            teacher_name = Teacher.query.get(form.lab_teacher_id.data).name
                            teachers_added.append(f"лабораторные (для групп без подгрупп): {teacher_name}")
            else:
                # Обычный случай - один преподаватель на все лабораторные
                if form.lab_teacher_id.data:
                    lab_teacher_id = form.lab_teacher_id.data
                    print(f"Добавление преподавателя лабораторных: ID={lab_teacher_id}")
                    ct = CourseTeacher(
                        course_id=course.id,
                        teacher_id=lab_teacher_id,
                        lesson_type='lab'
                    )
                    db.session.add(ct)
                    teacher_name = Teacher.query.get(lab_teacher_id).name
                    teachers_added.append(f"лабораторные: {teacher_name}")

        # Связываем курс с предпочтительными аудиториями
        if form.preferred_rooms.data:
            for room_id in form.preferred_rooms.data:
                room = Room.query.get(room_id)
                if room:
                    course.preferred_rooms.append(room)

        db.session.commit()

        # Проверяем что реально сохранилось в базе
        print("\n=== ПРОВЕРКА СОХРАНЕННЫХ ДАННЫХ ===")
        saved_course = Course.query.get(course.id)
        saved_teachers = CourseTeacher.query.filter_by(course_id=course.id).all()
        print(f"Сохраненный курс: ID={saved_course.id}, Название={saved_course.name}")
        print(f"Количество преподавателей: {len(saved_teachers)}")
        for teacher in saved_teachers:
            subgroup_info = f" ({teacher.lab_subgroup.name})" if teacher.lab_subgroup else ""
            print(
                f"  - Тип: {teacher.lesson_type}{subgroup_info}, Преподаватель ID: {teacher.teacher_id}, Имя: {Teacher.query.get(teacher.teacher_id).name}")
        print("===================================\n")

        teachers_text = ", ".join(teachers_added)
        flash(f'Дисциплина успешно добавлена! Преподаватели: {teachers_text}', 'success')
        return redirect(url_for('courses_list'))

    return render_template('course_form.html', form=form, title='Добавить дисциплину')


@app.route('/courses/edit/<int:id>', methods=['GET', 'POST'])
def edit_course(id):
    course = Course.query.get_or_404(id)
    form = CourseForm(obj=course)
    form.lecture_teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]
    form.practice_teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]
    form.lab_teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]

    # Добавляем информацию о подгруппах к группам
    groups = Group.query.all()
    form.groups.choices = []
    for g in groups:
        faculty_info = f" ({g.faculty.name})" if g.faculty else ""
        has_subgroups = " (с подгруппами)" if g.has_lab_subgroups() else ""
        form.groups.choices.append((g.id, f"{g.name}{faculty_info}{has_subgroups}"))

    form.preferred_rooms.choices = [(r.id, f"{r.name} (вместимость: {r.capacity})") for r in Room.query.all()]

    # Pre-populate groups and preferred rooms
    if request.method == 'GET':
        print("\n=== ОТЛАДКА: ЗАГРУЗКА ФОРМЫ РЕДАКТИРОВАНИЯ ===")
        print(f"Курс ID: {course.id}, Название: {course.name}")

        form.groups.data = [cg.group_id for cg in CourseGroup.query.filter_by(course_id=course.id).all()]
        form.preferred_rooms.data = [room.id for room in course.preferred_rooms]

        # Предзаполняем данные о преподавателях
        lecture_teacher = course.get_teacher_for_type('lecture')
        practice_teacher = course.get_teacher_for_type('practice')
        lab_teacher = course.get_teacher_for_type('lab')  # Базовый преподаватель лабораторных

        print(f"Текущие преподаватели:")
        if lecture_teacher:
            print(f"- Лекции: {lecture_teacher.name} (ID: {lecture_teacher.id})")
            form.lecture_teacher_id.data = lecture_teacher.id
        else:
            print("- Лекции: не назначен")

        if practice_teacher:
            print(f"- Практики: {practice_teacher.name} (ID: {practice_teacher.id})")
            form.practice_teacher_id.data = practice_teacher.id
        else:
            print("- Практики: не назначен")

        if lab_teacher:
            print(f"- Лабораторные: {lab_teacher.name} (ID: {lab_teacher.id})")
            form.lab_teacher_id.data = lab_teacher.id
        else:
            print("- Лабораторные: не назначен")

        # Логируем информацию о преподавателях подгрупп
        lab_subgroup_teachers = CourseTeacher.query.filter_by(
            course_id=course.id,
            lesson_type='lab'
        ).filter(CourseTeacher.lab_subgroup_id != None).all()

        if lab_subgroup_teachers:
            print("- Преподаватели лабораторных для подгрупп:")
            for teacher in lab_subgroup_teachers:
                print(f"  * {teacher.lab_subgroup.name}: {teacher.teacher.name} (ID: {teacher.teacher_id})")

        print("==============================\n")

    if form.validate_on_submit():
        print("\n=== ОТЛАДКА: СОХРАНЕНИЕ ИЗМЕНЕНИЙ ДИСЦИПЛИНЫ ===")
        print(f"Курс ID: {course.id}, Название: {form.name.data}")

        # Обновляем основные поля курса (кроме отношений)
        course.name = form.name.data
        course.lecture_count = form.lecture_count.data
        course.practice_count = form.practice_count.data
        course.lab_count = form.lab_count.data
        course.start_week = form.start_week.data
        course.distribution_type = form.distribution_type.data
        course.priority = form.priority.data
        course.notes = form.notes.data

        # Update course groups
        CourseGroup.query.filter_by(course_id=course.id).delete()
        selected_groups = []
        for group_id in form.groups.data:
            course_group = CourseGroup(course_id=course.id, group_id=group_id)
            db.session.add(course_group)
            selected_groups.append(Group.query.get(group_id))

        # Update preferred rooms
        course.preferred_rooms = []  # Очищаем текущие связи
        for room_id in form.preferred_rooms.data:
            room = Room.query.get(room_id)
            if room:
                course.preferred_rooms.append(room)

        # Обновляем преподавателей
        # Удаляем существующие связи с преподавателями
        CourseTeacher.query.filter_by(course_id=course.id).delete()

        # Сохраняем преподавателей для каждого типа занятий
        teachers_added = []

        # Лекции
        if form.lecture_count.data > 0 and form.lecture_teacher_id.data:
            lecture_teacher_id = form.lecture_teacher_id.data
            print(f"Добавление преподавателя лекций: ID={lecture_teacher_id}")
            ct = CourseTeacher(
                course_id=course.id,
                teacher_id=lecture_teacher_id,
                lesson_type='lecture'
            )
            db.session.add(ct)
            teacher_name = Teacher.query.get(lecture_teacher_id).name
            teachers_added.append(f"лекции: {teacher_name}")

        # Практики
        if form.practice_count.data > 0 and form.practice_teacher_id.data:
            practice_teacher_id = form.practice_teacher_id.data
            print(f"Добавление преподавателя практик: ID={practice_teacher_id}")
            ct = CourseTeacher(
                course_id=course.id,
                teacher_id=practice_teacher_id,
                lesson_type='practice'
            )
            db.session.add(ct)
            teacher_name = Teacher.query.get(practice_teacher_id).name
            teachers_added.append(f"практики: {teacher_name}")

        # Лабораторные
        if form.lab_count.data > 0:
            # Проверяем, есть ли группы с подгруппами среди выбранных
            has_subgroups = False
            for group in selected_groups:
                if group.has_lab_subgroups():
                    has_subgroups = True
                    break

            if has_subgroups:
                # Собираем преподавателей для каждой подгруппы из формы
                for group in selected_groups:
                    if group.has_lab_subgroups():
                        for subgroup in group.lab_subgroups:
                            teacher_id = request.form.get(f'lab_teacher_id_{subgroup.id}')
                            if teacher_id and int(teacher_id) > 0:
                                ct = CourseTeacher(
                                    course_id=course.id,
                                    teacher_id=int(teacher_id),
                                    lesson_type='lab',
                                    lab_subgroup_id=subgroup.id
                                )
                                db.session.add(ct)
                                teacher_name = Teacher.query.get(int(teacher_id)).name
                                teachers_added.append(f"лабораторные ({subgroup.name}): {teacher_name}")
                    else:
                        # Для групп без подгрупп используем общего преподавателя
                        if form.lab_teacher_id.data:
                            ct = CourseTeacher(
                                course_id=course.id,
                                teacher_id=form.lab_teacher_id.data,
                                lesson_type='lab'
                            )
                            db.session.add(ct)
                            teacher_name = Teacher.query.get(form.lab_teacher_id.data).name
                            teachers_added.append(f"лабораторные (для групп без подгрупп): {teacher_name}")
            else:
                # Обычный случай - один преподаватель на все лабораторные
                if form.lab_teacher_id.data:
                    lab_teacher_id = form.lab_teacher_id.data
                    print(f"Добавление преподавателя лабораторных: ID={lab_teacher_id}")
                    ct = CourseTeacher(
                        course_id=course.id,
                        teacher_id=lab_teacher_id,
                        lesson_type='lab'
                    )
                    db.session.add(ct)
                    teacher_name = Teacher.query.get(lab_teacher_id).name
                    teachers_added.append(f"лабораторные: {teacher_name}")

        db.session.commit()

        # Проверяем что реально сохранилось в базе
        print("\n=== ПРОВЕРКА СОХРАНЕННЫХ ДАННЫХ ===")
        saved_course = Course.query.get(course.id)
        saved_teachers = CourseTeacher.query.filter_by(course_id=course.id).all()
        print(f"Сохраненный курс: ID={saved_course.id}, Название={saved_course.name}")
        print(f"Количество преподавателей: {len(saved_teachers)}")
        for teacher in saved_teachers:
            subgroup_info = f" ({teacher.lab_subgroup.name})" if teacher.lab_subgroup else ""
            print(
                f"  - Тип: {teacher.lesson_type}{subgroup_info}, Преподаватель ID: {teacher.teacher_id}, Имя: {Teacher.query.get(teacher.teacher_id).name}")
        print("===================================\n")

        teachers_text = ", ".join(teachers_added)
        flash(f'Данные дисциплины обновлены! Преподаватели: {teachers_text}', 'success')
        return redirect(url_for('courses_list'))

    return render_template('course_form.html', form=form, title='Редактировать дисциплину')


@app.route('/courses/delete/<int:id>')
def delete_course(id):
    course = Course.query.get_or_404(id)
    # Удаляем связи с группами
    CourseGroup.query.filter_by(course_id=course.id).delete()
    # Удаляем связи с преподавателями (автоматически через cascade)
    db.session.delete(course)
    db.session.commit()
    flash('Дисциплина удалена!', 'success')
    return redirect(url_for('courses_list'))


@app.route('/generate-schedule')
def generate_schedule():
    # Удалим существующее расписание, сохраняя ручные корректировки
    if request.args.get('keep_manual', False):
        # Удаляем только автоматически созданные элементы
        ScheduleItem.query.filter_by(is_manually_placed=False).delete()
    else:
        # Удаляем все элементы расписания
        ScheduleItem.query.delete()

    db.session.commit()

    settings = Settings.query.first()
    if not settings:
        settings = Settings(weeks_count=18)
        db.session.add(settings)
        db.session.commit()

    courses = Course.query.all()
    rooms = Room.query.all()

    if not courses or not rooms:
        flash('Невозможно сгенерировать расписание. Добавьте дисциплины и аудитории.', 'error')
        return redirect(url_for('index'))

    # Генерация расписания с использованием оптимизированного алгоритма
    schedule_generator = ScheduleGenerator(settings)
    success = schedule_generator.generate()

    if success:
        flash('Расписание успешно сгенерировано!', 'success')
    else:
        flash('Не удалось сгенерировать расписание. Попробуйте изменить параметры.', 'error')

    return redirect(url_for('index'))


@app.route('/schedule')
def view_schedule():
    groups = Group.query.all()
    teachers = Teacher.query.all()
    settings = Settings.query.first()
    if not settings:
        settings = Settings(weeks_count=18)
        db.session.add(settings)
        db.session.commit()

    weeks = list(range(1, settings.weeks_count + 1))

    return render_template('schedule_view.html',
                           groups=groups,
                           teachers=teachers,
                           weeks=weeks)


@app.route('/schedule/data')
def schedule_data():
    group_id = request.args.get('group_id', type=int)
    teacher_id = request.args.get('teacher_id', type=int)
    week = request.args.get('week', type=int)

    if not ((group_id or teacher_id) and week):
        return jsonify({'error': 'Missing parameters'}), 400

    # Базовый запрос
    query = db.session.query(ScheduleItem).join(Course)

    # Фильтруем по группе или преподавателю и неделе
    if group_id:
        query = query.filter(
            ScheduleItem.week == week,
            ScheduleItem.groups.like(f'%{group_id}%')
        )
    elif teacher_id:
        query = query.filter(
            ScheduleItem.week == week,
            ScheduleItem.teacher_id == teacher_id
        )

    schedule_items = query.all()

    schedule_data = []
    for item in schedule_items:
        course = Course.query.get(item.course_id)
        room = Room.query.get(item.room_id)

        # Получаем преподавателя для этого занятия
        teacher_name = "Не назначен"
        if item.teacher_id:
            teacher = Teacher.query.get(item.teacher_id)
            teacher_name = teacher.name if teacher else "Не назначен"
        else:
            # Если преподаватель не назначен в ScheduleItem, ищем в CourseTeacher
            course_teacher = CourseTeacher.query.filter_by(
                course_id=course.id,
                lesson_type=item.lesson_type,
                lab_subgroup_id=item.lab_subgroup_id
            ).first()
            if course_teacher and course_teacher.teacher:
                teacher_name = course_teacher.teacher.name

        # Добавляем информацию о подгруппе, если это лабораторная работа для подгруппы
        subgroup_info = ""
        if item.lesson_type == 'lab' and item.lab_subgroup:
            subgroup_info = f" ({item.lab_subgroup.name})"

        # Получаем список групп
        group_names = []
        for group_id in item.get_group_ids():
            group = Group.query.get(group_id)
            if group:
                group_names.append(group.name)

        schedule_data.append({
            'id': item.id,
            'day': item.day,
            'time_slot': item.time_slot,
            'course_name': f"{course.name}{subgroup_info}",
            'teacher_name': teacher_name,
            'teacher_id': item.teacher_id,
            'room_name': room.name,
            'room_id': item.room_id,
            'lesson_type': item.lesson_type,
            'subgroup_id': item.lab_subgroup_id,
            'is_manually_placed': item.is_manually_placed,
            'group_names': ', '.join(group_names)
        })

    return jsonify(schedule_data)


@app.route('/schedule/manual', methods=['GET', 'POST'])
def manual_schedule():
    """Страница для ручного управления расписанием"""
    settings = Settings.query.first()
    weeks = list(range(1, settings.weeks_count + 1))

    return render_template('manual_schedule.html',
                           weeks=weeks,
                           settings=settings)


@app.route('/schedule/add-item', methods=['GET', 'POST'])
def add_schedule_item():
    """Добавление элемента расписания вручную"""
    form = ManualScheduleItemForm()

    # Заполняем списки выбора
    form.course_id.choices = [(c.id, c.name) for c in Course.query.all()]
    form.teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]
    form.room_id.choices = [(r.id, f"{r.name} (вместимость: {r.capacity})") for r in Room.query.all()]
    form.groups.choices = [(g.id, g.name) for g in Group.query.all()]

    # Опциональный список подгрупп
    all_subgroups = LabSubgroup.query.all()
    form.lab_subgroup_id.choices = [(0, 'Нет')] + [(s.id, f"{s.name} ({Group.query.get(s.group_id).name})") for s in
                                                   all_subgroups]

    settings = Settings.query.first()

    if form.validate_on_submit():
        # Проверяем на конфликты
        time_key = (form.week.data, form.day.data, form.time_slot.data)
        group_ids = form.groups.data
        teacher_id = form.teacher_id.data
        room_id = form.room_id.data

        conflicts = check_schedule_conflicts(time_key, teacher_id, room_id, group_ids)

        if conflicts:
            # Если есть конфликты, выводим их и не сохраняем
            for conflict in conflicts:
                flash(conflict, 'error')
            return render_template('manual_schedule_form.html', form=form, title='Добавить занятие вручную')

        # Если нет конфликтов, создаем новый элемент расписания
        lab_subgroup_id = form.lab_subgroup_id.data if form.lab_subgroup_id.data != 0 else None

        schedule_item = ScheduleItem(
            course_id=form.course_id.data,
            teacher_id=form.teacher_id.data,
            room_id=form.room_id.data,
            week=form.week.data,
            day=form.day.data,
            time_slot=form.time_slot.data,
            lesson_type=form.lesson_type.data,
            groups=','.join(map(str, form.groups.data)),
            lab_subgroup_id=lab_subgroup_id,
            is_manually_placed=True,
            notes=form.notes.data
        )

        db.session.add(schedule_item)
        db.session.commit()

        flash('Занятие успешно добавлено в расписание!', 'success')
        return redirect(url_for('manual_schedule'))

    # Устанавливаем значение недели по умолчанию
    if form.week.data is None:
        form.week.data = 1

    return render_template('manual_schedule_form.html', form=form, title='Добавить занятие вручную')


@app.route('/schedule/edit-item/<int:id>', methods=['GET', 'POST'])
def edit_schedule_item(id):
    """Редактирование элемента расписания"""
    schedule_item = ScheduleItem.query.get_or_404(id)
    form = ManualScheduleItemForm(obj=schedule_item)

    # Заполняем списки выбора
    form.course_id.choices = [(c.id, c.name) for c in Course.query.all()]
    form.teacher_id.choices = [(t.id, t.name) for t in Teacher.query.all()]
    form.room_id.choices = [(r.id, f"{r.name} (вместимость: {r.capacity})") for r in Room.query.all()]
    form.groups.choices = [(g.id, g.name) for g in Group.query.all()]

    # Опциональный список подгрупп
    all_subgroups = LabSubgroup.query.all()
    form.lab_subgroup_id.choices = [(0, 'Нет')] + [(s.id, f"{s.name} ({Group.query.get(s.group_id).name})") for s in
                                                   all_subgroups]

    if request.method == 'GET':
        # Предзаполняем данные формы
        form.groups.data = schedule_item.get_group_ids()
        form.lab_subgroup_id.data = schedule_item.lab_subgroup_id if schedule_item.lab_subgroup_id else 0

    if form.validate_on_submit():
        # Проверяем на конфликты, исключая текущий элемент
        time_key = (form.week.data, form.day.data, form.time_slot.data)
        group_ids = form.groups.data
        teacher_id = form.teacher_id.data
        room_id = form.room_id.data

        conflicts = check_schedule_conflicts(time_key, teacher_id, room_id, group_ids, exclude_id=id)

        if conflicts:
            # Если есть конфликты, выводим их и не сохраняем
            for conflict in conflicts:
                flash(conflict, 'error')
            return render_template('manual_schedule_form.html', form=form, title='Редактировать занятие')

        # Если нет конфликтов, обновляем элемент расписания
        schedule_item.course_id = form.course_id.data
        schedule_item.teacher_id = form.teacher_id.data
        schedule_item.room_id = form.room_id.data
        schedule_item.week = form.week.data
        schedule_item.day = form.day.data
        schedule_item.time_slot = form.time_slot.data
        schedule_item.lesson_type = form.lesson_type.data
        schedule_item.groups = ','.join(map(str, form.groups.data))
        schedule_item.lab_subgroup_id = form.lab_subgroup_id.data if form.lab_subgroup_id.data != 0 else None
        schedule_item.is_manually_placed = True
        schedule_item.notes = form.notes.data

        db.session.commit()

        flash('Занятие успешно обновлено!', 'success')
        return redirect(url_for('manual_schedule'))

    return render_template('manual_schedule_form.html', form=form, title='Редактировать занятие')


@app.route('/schedule/delete-item/<int:id>')
def delete_schedule_item(id):
    """Удаление элемента расписания"""
    schedule_item = ScheduleItem.query.get_or_404(id)
    db.session.delete(schedule_item)
    db.session.commit()

    flash('Занятие удалено из расписания!', 'success')
    return redirect(url_for('manual_schedule'))


@app.route('/schedule/get-items')
def get_schedule_items():
    """API для получения элементов расписания для ручного управления"""
    week = request.args.get('week', type=int)

    if not week:
        return jsonify({'error': 'Missing week parameter'}), 400

    items = ScheduleItem.query.filter_by(week=week).all()
    result = []

    for item in items:
        course = Course.query.get(item.course_id)
        room = Room.query.get(item.room_id)
        teacher = Teacher.query.get(item.teacher_id) if item.teacher_id else None

        group_names = []
        for group_id in item.get_group_ids():
            group = Group.query.get(group_id)
            if group:
                group_names.append(group.name)

        subgroup_name = ""
        if item.lab_subgroup_id:
            subgroup = LabSubgroup.query.get(item.lab_subgroup_id)
            if subgroup:
                subgroup_name = subgroup.name

        # Определяем типы занятий
        lesson_types = {
            'lecture': 'Лекция',
            'practice': 'Практика',
            'lab': 'Лабораторная'
        }

        result.append({
            'id': item.id,
            'course_name': course.name,
            'course_id': course.id,
            'room_name': room.name,
            'room_id': room.id,
            'teacher_name': teacher.name if teacher else "Не назначен",
            'teacher_id': teacher.id if teacher else None,
            'day': item.day,
            'day_name': ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница'][item.day],
            'time_slot': item.time_slot,
            'time_name': ['8:00 - 9:20', '9:30 - 10:50', '11:00 - 12:20', '12:40 - 14:00',
                          '14:10 - 15:30', '15:40 - 17:00', '17:10 - 18:30'][item.time_slot],
            'lesson_type': item.lesson_type,
            'lesson_type_name': lesson_types.get(item.lesson_type, item.lesson_type),
            'groups': item.groups,
            'group_names': ', '.join(group_names),
            'subgroup_id': item.lab_subgroup_id,
            'subgroup_name': subgroup_name,
            'is_manually_placed': item.is_manually_placed,
            'notes': item.notes
        })

    return jsonify(result)


@app.route('/api/check-conflicts', methods=['POST'])
def api_check_conflicts():
    """API для проверки конфликтов перед добавлением/редактированием занятия"""
    data = request.json

    week = data.get('week')
    day = data.get('day')
    time_slot = data.get('time_slot')
    teacher_id = data.get('teacher_id')
    room_id = data.get('room_id')
    group_ids = data.get('group_ids', [])
    exclude_id = data.get('exclude_id')

    time_key = (week, day, time_slot)
    conflicts = check_schedule_conflicts(time_key, teacher_id, room_id, group_ids, exclude_id)

    return jsonify({
        'has_conflicts': len(conflicts) > 0,
        'conflicts': conflicts
    })


# Вспомогательные функции

def check_schedule_conflicts(time_key, teacher_id, room_id, group_ids, exclude_id=None):
    """
    Проверяет наличие конфликтов в расписании при добавлении нового занятия.
    Возвращает список строк с описаниями конфликтов.
    """
    week, day, time_slot = time_key
    conflicts = []

    # Получаем существующие занятия в это время
    existing_items = ScheduleItem.query.filter_by(
        week=week, day=day, time_slot=time_slot
    ).all()

    # Исключаем элемент, который редактируется
    if exclude_id:
        existing_items = [item for item in existing_items if item.id != exclude_id]

    # Проверка на конфликт преподавателя
    teacher_conflicts = [item for item in existing_items if item.teacher_id == teacher_id]
    if teacher_conflicts:
        teacher = Teacher.query.get(teacher_id)
        conflicts.append(f"Преподаватель {teacher.name} уже занят в это время другим занятием")

    # Проверка на конфликт аудитории
    room_conflicts = [item for item in existing_items if item.room_id == room_id]
    if room_conflicts:
        room = Room.query.get(room_id)
        conflicts.append(f"Аудитория {room.name} уже занята в это время")

    # Проверка на конфликт групп
    for item in existing_items:
        item_group_ids = item.get_group_ids()
        for group_id in group_ids:
            if group_id in item_group_ids:
                group = Group.query.get(group_id)
                conflicts.append(f"Группа {group.name} уже имеет занятие в это время")
                break

    return conflicts


def get_day_name(day_index):
    """Возвращает название дня недели по индексу"""
    days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
    if 0 <= day_index < len(days):
        return days[day_index]
    return "Неизвестный день"


def get_time_name(slot_index):
    """Возвращает название временного слота по индексу"""
    slots = ['8:00 - 9:20', '9:30 - 10:50', '11:00 - 12:20', '12:40 - 14:00',
             '14:10 - 15:30', '15:40 - 17:00', '17:10 - 18:30']
    if 0 <= slot_index < len(slots):
        return slots[slot_index]
    return "Неизвестное время"


# Класс для генерации расписания с поддержкой подгрупп и приоритетов
class ScheduleGenerator:
    def __init__(self, settings):
        self.settings = settings
        self.weeks_count = settings.weeks_count
        self.days_per_week = settings.days_per_week
        self.slots_per_day = settings.slots_per_day

        # Получаем все необходимые данные
        self.courses = Course.query.all()
        self.rooms = Room.query.all()
        self.teachers = Teacher.query.all()
        self.groups = Group.query.all()

        # Создаем пустое расписание
        self.schedule = {}  # (week, day, slot) -> [schedule_items]

        # Загружаем уже размещенные вручную элементы
        self.load_manual_items()

        # Ограничения по времени и итерациям
        self.max_generation_time = 45  # максимальное время генерации расписания в секундах
        self.max_iterations = 1500  # максимальное количество итераций

        # Параметры оптимизации
        self.temperature = 1.0  # Начальная температура для имитации отжига
        self.cooling_rate = 0.99  # Коэффициент охлаждения

    def load_manual_items(self):
        """Загружает размещенные вручную элементы в расписание"""
        manual_items = ScheduleItem.query.filter_by(is_manually_placed=True).all()
        for item in manual_items:
            time_key = (item.week, item.day, item.time_slot)
            if time_key not in self.schedule:
                self.schedule[time_key] = []

            group_ids = item.get_group_ids()
            self.schedule[time_key].append({
                'course': item.course,
                'room': item.room,
                'lesson_type': item.lesson_type,
                'groups': group_ids,
                'teacher': item.teacher,
                'lab_subgroup': item.lab_subgroup,
                'is_manually_placed': True
            })

    def generate(self):
        try:
            start_time = time.time()
            print("Начало генерации расписания...")

            # Сортируем курсы по приоритету
            prioritized_courses = sorted(self.courses,
                                         key=lambda c: c.get_effective_priority(),
                                         reverse=True)

            # Создаем начальное расписание с учетом частоты занятий, подгрупп и приоритетов
            if not self._create_frequency_based_schedule(prioritized_courses):
                print("Не удалось создать начальное расписание")
                return False

            print(f"Начальное расписание создано за {time.time() - start_time:.2f} сек.")

            # Оптимизируем расписание с использованием симуляции отжига
            if time.time() - start_time < self.max_generation_time:
                print("Оптимизация расписания...")
                self._optimize_schedule()

            # Сохраняем сгенерированное расписание в БД
            self._save_schedule()
            print(f"Расписание сгенерировано и сохранено за {time.time() - start_time:.2f} сек.")
            return True
        except Exception as e:
            print(f"Ошибка при генерации расписания: {e}")
            return False

    def _create_frequency_based_schedule(self, prioritized_courses):
        """Создаем расписание, исходя из частоты проведения занятий разных типов, с учетом подгрупп и приоритетов"""
        # Для каждого курса определяем частоту занятий, начиная с курсов с высшим приоритетом
        for course in prioritized_courses:
            # Получаем связанные группы
            course_groups = CourseGroup.query.filter_by(course_id=course.id).all()
            group_ids = [cg.group_id for cg in course_groups]

            # Если нет групп, пропускаем курс
            if not group_ids:
                continue

            # Получаем группы с разделением на подгруппы для лабораторных
            groups_with_subgroups = []
            for group_id in group_ids:
                group = Group.query.get(group_id)
                if group.has_lab_subgroups():
                    groups_with_subgroups.append(group)

            # Определяем доступные недели с учетом начальной недели курса
            available_weeks = list(range(course.start_week, self.weeks_count + 1))

            if not available_weeks:
                print(f"Недостаточно недель для дисциплины {course.name}")
                continue

            # Общее количество доступных недель
            total_weeks = len(available_weeks)

            print(f"Курс: {course.name}, начинается с недели {course.start_week}, доступно {total_weeks} недель")
            print(f"Приоритет: {course.priority}, эффективный приоритет: {course.get_effective_priority():.2f}")

            # Рассчитываем занятия для расписания
            lessons_to_schedule = []

            # Обрабатываем лекции
            if course.lecture_count > 0:
                lecture_teacher = course.get_teacher_for_type('lecture')
                if not lecture_teacher:
                    print(f"  ОШИБКА: Преподаватель для лекций не назначен для курса {course.name}")
                    continue

                # Рассчитываем частоту
                frequency = total_weeks / course.lecture_count
                print(f"  Лекции: {course.lecture_count} шт., частота: одна лекция каждые {frequency:.2f} недели")

                # Генерируем недели для лекций с учетом частоты
                weeks = self._generate_weeks_with_frequency(
                    course, 'lecture', frequency, available_weeks)

                # Добавляем лекции в список занятий
                total_students = sum([Group.query.get(gid).size for gid in group_ids])
                for week in weeks:
                    lessons_to_schedule.append({
                        'course': course,
                        'lesson_type': 'lecture',
                        'teacher': lecture_teacher,
                        'group_ids': group_ids,
                        'total_students': total_students,
                        'target_week': week,
                        'lab_subgroup': None  # Лекции не делятся на подгруппы
                    })

            # Обрабатываем практики
            if course.practice_count > 0:
                practice_teacher = course.get_teacher_for_type('practice')
                if not practice_teacher:
                    print(f"  ОШИБКА: Преподаватель для практик не назначен для курса {course.name}")
                    continue

                # Рассчитываем частоту
                frequency = total_weeks / course.practice_count
                print(f"  Практики: {course.practice_count} шт., частота: одна практика каждые {frequency:.2f} недели")

                # Генерируем недели для практик с учетом частоты
                weeks = self._generate_weeks_with_frequency(
                    course, 'practice', frequency, available_weeks)

                # Добавляем практики в список занятий
                total_students = sum([Group.query.get(gid).size for gid in group_ids])
                for week in weeks:
                    lessons_to_schedule.append({
                        'course': course,
                        'lesson_type': 'practice',
                        'teacher': practice_teacher,
                        'group_ids': group_ids,
                        'total_students': total_students,
                        'target_week': week,
                        'lab_subgroup': None  # Практики не делятся на подгруппы
                    })

            # Обрабатываем лабораторные
            if course.lab_count > 0:
                # Генерируем недели для лабораторных
                frequency = total_weeks / course.lab_count
                print(f"  Лабораторные: {course.lab_count} шт., частота: одна лаба каждые {frequency:.2f} недели")
                weeks = self._generate_weeks_with_frequency(
                    course, 'lab', frequency, available_weeks)

                # Если есть группы с подгруппами, создаем отдельные занятия для каждой подгруппы
                if groups_with_subgroups:
                    for week in weeks:
                        # Для каждой группы с подгруппами
                        for group in groups_with_subgroups:
                            # Получаем подгруппы и их преподавателей
                            for subgroup in group.lab_subgroups:
                                # Ищем преподавателя для этой подгруппы
                                lab_teacher = None
                                course_teacher = CourseTeacher.query.filter_by(
                                    course_id=course.id,
                                    lesson_type='lab',
                                    lab_subgroup_id=subgroup.id
                                ).first()

                                if course_teacher:
                                    lab_teacher = course_teacher.teacher
                                else:
                                    # Если нет специального преподавателя, используем общего
                                    lab_teacher = course.get_teacher_for_type('lab')

                                if not lab_teacher:
                                    print(
                                        f"  ОШИБКА: Преподаватель для лабораторных не назначен для курса {course.name} и подгруппы {subgroup.name}")
                                    continue

                                # Добавляем занятие для этой подгруппы
                                lessons_to_schedule.append({
                                    'course': course,
                                    'lesson_type': 'lab',
                                    'teacher': lab_teacher,
                                    'group_ids': [group.id],  # Только для этой группы
                                    'total_students': subgroup.size,  # Размер подгруппы
                                    'target_week': week,
                                    'lab_subgroup': subgroup  # Указываем подгруппу
                                })

                # Для остальных групп без подгрупп
                groups_without_subgroups = [Group.query.get(gid) for gid in group_ids
                                            if Group.query.get(gid) not in groups_with_subgroups]

                if groups_without_subgroups:
                    # Находим преподавателя для обычных лабораторных
                    lab_teacher = course.get_teacher_for_type('lab')
                    if not lab_teacher:
                        print(f"  ОШИБКА: Преподаватель для лабораторных не назначен для курса {course.name}")
                        continue

                    # Добавляем обычные лабораторные для групп без подгрупп
                    for week in weeks:
                        group_ids_without_subgroups = [g.id for g in groups_without_subgroups]
                        total_students = sum([g.size for g in groups_without_subgroups])

                        lessons_to_schedule.append({
                            'course': course,
                            'lesson_type': 'lab',
                            'teacher': lab_teacher,
                            'group_ids': group_ids_without_subgroups,
                            'total_students': total_students,
                            'target_week': week,
                            'lab_subgroup': None  # Нет подгруппы
                        })

            # Выводим информацию о запланированных занятиях
            lectures = [l for l in lessons_to_schedule if l['lesson_type'] == 'lecture']
            practices = [l for l in lessons_to_schedule if l['lesson_type'] == 'practice']
            labs = [l for l in lessons_to_schedule if l['lesson_type'] == 'lab']

            if lectures:
                print(f"  Недели лекций: {sorted([l['target_week'] for l in lectures])}")
            if practices:
                print(f"  Недели практик: {sorted([l['target_week'] for l in practices])}")
            if labs:
                for lab in labs:
                    subgroup_info = f" ({lab['lab_subgroup'].name})" if lab['lab_subgroup'] else ""
                    group_ids = lab['group_ids']
                    print(f"  Лабораторная на неделе {lab['target_week']}{subgroup_info} для групп: {group_ids}")

            # Размещаем все занятия курса
            for lesson in lessons_to_schedule:
                if not self._place_lesson(lesson):
                    subgroup_info = f" ({lesson['lab_subgroup'].name})" if lesson['lab_subgroup'] else ""
                    print(
                        f"  ОШИБКА: Не удалось разместить занятие {course.name} {lesson['lesson_type']}{subgroup_info} на неделе {lesson['target_week']}")

        # Анализируем распределение
        self._analyze_distribution()

        return True

    def _generate_weeks_with_frequency(self, course, lesson_type, frequency, available_weeks):
        """Генерирует список недель для занятий с учетом их частоты"""
        # Получаем количество занятий данного типа
        if lesson_type == 'lecture':
            count = course.lecture_count
        elif lesson_type == 'practice':
            count = course.practice_count
        else:  # lab
            count = course.lab_count

        # Если занятий нет, возвращаем пустой список
        if count == 0 or not available_weeks:
            return []

        # Обработка в зависимости от типа распределения
        if course.distribution_type == 'even':
            # Для равномерного распределения вычисляем оптимальный интервал
            # с учетом доступных недель и количества занятий

            # Число недель между занятиями (может быть дробным)
            exact_interval = len(available_weeks) / count

            # Генерируем недели с точным интервалом
            weeks = []
            for i in range(count):
                # Вычисляем индекс с использованием дробного интервала для максимальной равномерности
                index = int(i * exact_interval)
                if index < len(available_weeks):
                    weeks.append(available_weeks[index])
                else:
                    # Если выходим за пределы, берем последнюю неделю
                    weeks.append(available_weeks[-1])

            return weeks

        elif course.distribution_type == 'front_loaded':
            # Для front_loaded концентрируем занятия в начале доступного периода
            weeks = []
            for i in range(count):
                index = int((i / count) ** 1.5 * len(available_weeks))
                weeks.append(available_weeks[min(index, len(available_weeks) - 1)])

            return weeks

        elif course.distribution_type == 'back_loaded':
            # Для back_loaded концентрируем занятия в конце доступного периода
            weeks = []
            for i in range(count):
                index = int((1 - ((count - i - 1) / count) ** 1.5) * len(available_weeks))
                weeks.append(available_weeks[min(index, len(available_weeks) - 1)])

            return weeks

        elif course.distribution_type == 'block':
            # Для block распределения размещаем занятия последовательно в начале доступного периода
            return available_weeks[:min(count, len(available_weeks))]

        # По умолчанию используем равномерное распределение
        # (с дробным интервалом для максимальной равномерности)
        exact_interval = len(available_weeks) / count
        weeks = []
        for i in range(count):
            index = int(i * exact_interval)
            if index < len(available_weeks):
                weeks.append(available_weeks[index])
            else:
                weeks.append(available_weeks[-1])

        return weeks

    def _place_lesson(self, lesson):
        """Пытается разместить занятие на неделе, указанной в lesson['target_week']"""
        course = lesson['course']
        lesson_type = lesson['lesson_type']
        group_ids = lesson['group_ids']
        total_students = lesson['total_students']
        target_week = lesson.get('target_week')
        teacher = lesson.get('teacher')
        lab_subgroup = lesson.get('lab_subgroup')

        if target_week is None:
            print(f"Ошибка: не указана целевая неделя для занятия {course.name} {lesson_type}")
            return False

        if not teacher:
            print(f"Ошибка: не указан преподаватель для занятия {course.name} {lesson_type}")
            return False

        # Находим подходящие аудитории
        suitable_rooms = self._find_suitable_rooms(course, lesson_type, total_students)
        if not suitable_rooms:
            print(f"Нет подходящих аудиторий для {course.name} ({lesson_type})")
            return False

        # Определяем оптимальный порядок слотов с учетом настроек
        time_slots = self._get_prioritized_time_slots(teacher, course, group_ids)

        # Пробуем разместить в оптимальном слоте для каждого дня
        # Перебор по дням с учетом предпочтений преподавателя
        days = self._get_prioritized_days(teacher)

        for day in days:
            for slot in time_slots:
                time_key = (target_week, day, slot)
                if self._check_constraints(time_key, course, group_ids, suitable_rooms, teacher, lab_subgroup):
                    room = self._select_best_room(course, suitable_rooms, total_students)
                    if time_key not in self.schedule:
                        self.schedule[time_key] = []
                    self.schedule[time_key].append({
                        'course': course,
                        'room': room,
                        'lesson_type': lesson_type,
                        'groups': group_ids,
                        'teacher': teacher,
                        'lab_subgroup': lab_subgroup,
                        'is_manually_placed': False
                    })
                    return True

        # Если не смогли разместить в текущую неделю, пробуем в ближайшие
        for offset in range(1, 3):  # Проверяем до 2 недель в обе стороны
            # Пробуем неделю раньше
            earlier_week = target_week - offset
            if earlier_week >= course.start_week:
                for day in days:
                    for slot in time_slots:
                        time_key = (earlier_week, day, slot)
                        if self._check_constraints(time_key, course, group_ids, suitable_rooms, teacher, lab_subgroup):
                            room = self._select_best_room(course, suitable_rooms, total_students)
                            if time_key not in self.schedule:
                                self.schedule[time_key] = []
                            self.schedule[time_key].append({
                                'course': course,
                                'room': room,
                                'lesson_type': lesson_type,
                                'groups': group_ids,
                                'teacher': teacher,
                                'lab_subgroup': lab_subgroup,
                                'is_manually_placed': False
                            })
                            return True

            # Пробуем неделю позже
            later_week = target_week + offset
            if later_week <= self.weeks_count:
                for day in days:
                    for slot in time_slots:
                        time_key = (later_week, day, slot)
                        if self._check_constraints(time_key, course, group_ids, suitable_rooms, teacher, lab_subgroup):
                            room = self._select_best_room(course, suitable_rooms, total_students)
                            if time_key not in self.schedule:
                                self.schedule[time_key] = []
                            self.schedule[time_key].append({
                                'course': course,
                                'room': room,
                                'lesson_type': lesson_type,
                                'groups': group_ids,
                                'teacher': teacher,
                                'lab_subgroup': lab_subgroup,
                                'is_manually_placed': False
                            })
                            return True

        # Не смогли разместить занятие
        return False

    def _get_prioritized_days(self, teacher):
        """Возвращает список дней, отсортированный по предпочтениям преподавателя"""
        all_days = list(range(self.days_per_week))

        # Если нужно учитывать предпочтения преподавателя
        if self.settings.respect_teacher_preferences and teacher:
            preferred_days = teacher.get_preferred_days_list()
            if preferred_days:
                # Сначала предпочитаемые дни, затем остальные
                return sorted(all_days, key=lambda d: d not in preferred_days)

        # Если нет предпочтений или не нужно их учитывать
        return all_days

    def _get_prioritized_time_slots(self, teacher, course, group_ids):
        """Возвращает отсортированный список временных слотов с учетом настроек и предпочтений"""
        all_slots = list(range(self.slots_per_day))

        # Получаем настройки предпочтительного распределения
        distribution = self.settings.preferred_lesson_distribution

        # Получаем предпочтения преподавателя
        teacher_preferred_slots = []
        if self.settings.respect_teacher_preferences and teacher:
            teacher_preferred_slots = teacher.get_preferred_time_slots_list()

        # Получаем предпочтения групп
        groups_preferred_slots = []
        for group_id in group_ids:
            group = Group.query.get(group_id)
            if group:
                groups_preferred_slots.extend(group.get_preferred_time_slots_list())

        # Нормализуем предпочтения групп, считая самыми предпочтительными те слоты,
        # которые выбраны большинством групп
        slot_counts = {}
        for slot in groups_preferred_slots:
            slot_counts[slot] = slot_counts.get(slot, 0) + 1

        # Сортируем слоты с учетом всех факторов
        def slot_priority(slot):
            # Начальное значение приоритета
            priority = 0

            # Учитываем глобальные настройки
            if distribution == 'morning' and slot < 3:
                priority += 10
            elif distribution == 'afternoon' and 2 < slot < 5:
                priority += 10
            elif distribution == 'balanced':
                # Для сбалансированного распределения приоритет средних пар немного выше
                priority += 5 - abs(slot - 3)

            # Учитываем предпочтения преподавателя
            if slot in teacher_preferred_slots:
                priority += 15

            # Учитываем предпочтения групп
            if slot in slot_counts:
                # Чем больше групп выбрали этот слот, тем выше приоритет
                priority += 5 * slot_counts[slot] / len(group_ids)

            return priority

        return sorted(all_slots, key=slot_priority, reverse=True)

    def _optimize_schedule(self):
        """Оптимизирует расписание с использованием симуляции отжига"""
        iterations = 0
        start_time = time.time()
        current_score = self._evaluate_schedule()
        best_score = current_score
        best_schedule = copy.deepcopy(self.schedule)
        temperature = self.temperature

        print(f"Начальная оценка расписания: {current_score}")

        while iterations < self.max_iterations and time.time() - start_time < self.max_generation_time:
            # Пытаемся произвести случайную перестановку
            if self._make_random_swap():
                new_score = self._evaluate_schedule()

                # Решаем, принимать ли новое расписание
                if new_score > current_score:
                    # Если новое расписание лучше, всегда принимаем его
                    current_score = new_score
                    if new_score > best_score:
                        best_score = new_score
                        best_schedule = copy.deepcopy(self.schedule)
                        print(f"Найдено лучшее расписание с оценкой: {best_score}")
                else:
                    # Если хуже, принимаем с вероятностью, зависящей от температуры
                    delta = new_score - current_score
                    acceptance_probability = math.exp(delta / temperature)
                    if random.random() < acceptance_probability:
                        current_score = new_score
                    else:
                        # Отменяем перестановку
                        self._undo_last_swap()

            # Снижаем температуру
            temperature *= self.cooling_rate
            iterations += 1

            # Периодически выводим информацию
            if iterations % 100 == 0:
                print(f"Итерация {iterations}, текущая оценка: {current_score}, лучшая оценка: {best_score}")

        # Восстанавливаем лучшее найденное расписание
        self.schedule = best_schedule
        print(f"Оптимизация завершена после {iterations} итераций. Финальная оценка: {best_score}")

    def _make_random_swap(self):
        """Производит случайную перестановку в расписании"""
        # Сохраняем предыдущее состояние для возможной отмены
        self._previous_schedule = copy.deepcopy(self.schedule)

        # Получаем все ключи времени, где есть занятия
        time_keys = list(self.schedule.keys())
        if len(time_keys) < 2:
            return False

        # Выбираем два случайных ключа времени
        key1, key2 = random.sample(time_keys, 2)

        # Выбираем случайные занятия в этих временных слотах
        if not self.schedule[key1] or not self.schedule[key2]:
            return False

        idx1 = random.randrange(len(self.schedule[key1]))
        idx2 = random.randrange(len(self.schedule[key2]))

        # Проверяем, не являются ли занятия ручными (их не трогаем)
        if self.schedule[key1][idx1].get('is_manually_placed') or self.schedule[key2][idx2].get('is_manually_placed'):
            return False

        # Запоминаем занятия
        lesson1 = self.schedule[key1][idx1]
        lesson2 = self.schedule[key2][idx2]

        # Удаляем занятия из расписания
        self.schedule[key1].pop(idx1)
        self.schedule[key2].pop(idx2)

        # Проверяем ограничения для перемещения
        suitable_rooms1 = self._find_suitable_rooms(lesson2['course'], lesson2['lesson_type'],
                                                    sum([Group.query.get(gid).size for gid in lesson2['groups']]))
        suitable_rooms2 = self._find_suitable_rooms(lesson1['course'], lesson1['lesson_type'],
                                                    sum([Group.query.get(gid).size for gid in lesson1['groups']]))

        can_swap = (suitable_rooms1 and suitable_rooms2 and
                    self._check_constraints(key1, lesson2['course'], lesson2['groups'],
                                            suitable_rooms1, lesson2['teacher'], lesson2.get('lab_subgroup')) and
                    self._check_constraints(key2, lesson1['course'], lesson1['groups'],
                                            suitable_rooms2, lesson1['teacher'], lesson1.get('lab_subgroup')))

        if can_swap:
            # Если можем поменять, выбираем подходящие аудитории
            lesson2['room'] = self._select_best_room(lesson2['course'], suitable_rooms1,
                                                     sum([Group.query.get(gid).size for gid in lesson2['groups']]))
            lesson1['room'] = self._select_best_room(lesson1['course'], suitable_rooms2,
                                                     sum([Group.query.get(gid).size for gid in lesson1['groups']]))

            # Добавляем занятия в новые места
            self.schedule[key1].append(lesson2)
            self.schedule[key2].append(lesson1)
            return True
        else:
            # Если не можем поменять, возвращаем занятия на место
            self.schedule[key1].append(lesson1)
            self.schedule[key2].append(lesson2)
            return False

    def _undo_last_swap(self):
        """Отменяет последнюю перестановку, восстанавливая предыдущее состояние"""
        if hasattr(self, '_previous_schedule'):
            self.schedule = self._previous_schedule

    def _evaluate_schedule(self):
        """Оценивает качество расписания по нескольким критериям"""
        score = 100  # Начальная оценка

        # Критерии оценки:
        # 1. Количество занятий в неудобное время (штраф)
        inconvenient_time_count = 0
        for time_key, lessons in self.schedule.items():
            week, day, slot = time_key
            # Последняя пара считается менее удобной
            if slot >= self.slots_per_day - 1:
                inconvenient_time_count += len(lessons)

        score -= inconvenient_time_count * 0.5

        # 2. Оценка "окон" в расписании групп (штраф)
        if self.settings.avoid_windows:
            group_windows = self._count_group_windows()
            score -= group_windows * 2  # Серьезный штраф за окна

        # 3. Соответствие предпочтениям преподавателей
        if self.settings.respect_teacher_preferences:
            teacher_preferences_score = self._evaluate_teacher_preferences()
            score += teacher_preferences_score

        # 4. Равномерность распределения занятий
        distribution_score = self._evaluate_distribution()
        score += distribution_score

        # 5. Эффективность использования аудиторий
        if self.settings.optimize_room_usage:
            room_usage_score = self._evaluate_room_usage()
            score += room_usage_score

        return score

    def _count_group_windows(self):
        """Подсчитывает количество "окон" в расписании групп"""
        total_windows = 0

        # Для каждой группы проверяем расписание по дням
        for group in self.groups:
            for week in range(1, self.weeks_count + 1):
                for day in range(self.days_per_week):
                    # Собираем все занятия группы в этот день
                    day_slots = []
                    for slot in range(self.slots_per_day):
                        time_key = (week, day, slot)
                        if time_key in self.schedule:
                            for lesson in self.schedule[time_key]:
                                if group.id in lesson['groups']:
                                    day_slots.append(slot)

                    # Проверяем на окна (пропуски между занятиями)
                    if day_slots:
                        day_slots.sort()
                        # Считаем окна только если есть хотя бы два занятия
                        if len(day_slots) >= 2:
                            for i in range(len(day_slots) - 1):
                                # Если разница больше 1, значит есть окно
                                if day_slots[i + 1] - day_slots[i] > 1:
                                    total_windows += day_slots[i + 1] - day_slots[i] - 1

        return total_windows

    def _evaluate_teacher_preferences(self):
        """Оценивает соответствие расписания предпочтениям преподавателей"""
        score = 0

        # Для каждого занятия проверяем, соответствует ли оно предпочтениям преподавателя
        for time_key, lessons in self.schedule.items():
            week, day, slot = time_key
            for lesson in lessons:
                teacher = lesson['teacher']
                if teacher:
                    preferred_days = teacher.get_preferred_days_list()
                    preferred_slots = teacher.get_preferred_time_slots_list()

                    # Проверяем день
                    if preferred_days and day in preferred_days:
                        score += 0.5

                    # Проверяем временной слот
                    if preferred_slots and slot in preferred_slots:
                        score += 0.5

        return score

    def _evaluate_distribution(self):
        """Оценивает равномерность распределения занятий"""
        score = 0

        # Для каждой группы оцениваем распределение занятий по дням
        for group in self.groups:
            # Считаем количество занятий в каждый день недели
            day_counts = defaultdict(int)

            for time_key, lessons in self.schedule.items():
                week, day, slot = time_key
                for lesson in lessons:
                    if group.id in lesson['groups']:
                        day_counts[(week, day)] += 1

            # Оцениваем равномерность распределения
            # (считаем стандартное отклонение количества занятий)
            if day_counts:
                counts = list(day_counts.values())
                mean = sum(counts) / len(counts)
                variance = sum((c - mean) ** 2 for c in counts) / len(counts)
                std_dev = math.sqrt(variance) if variance > 0 else 0

                # Чем меньше стандартное отклонение, тем лучше распределение
                score += 10 / (1 + std_dev)

        return score

    def _evaluate_room_usage(self):
        """Оценивает эффективность использования аудиторий"""
        score = 0

        # Для каждого занятия оцениваем соответствие размера аудитории количеству студентов
        for time_key, lessons in self.schedule.items():
            for lesson in lessons:
                room = lesson['room']
                total_students = sum([Group.query.get(gid).size for gid in lesson['groups']])

                # Если есть подгруппа, используем ее размер
                if lesson.get('lab_subgroup'):
                    total_students = lesson['lab_subgroup'].size

                # Оцениваем соответствие: штраф за слишком большие и слишком маленькие аудитории
                capacity_ratio = total_students / room.capacity if room.capacity > 0 else 0

                # Идеальное соотношение - 0.8-0.9
                if 0.7 <= capacity_ratio <= 0.95:
                    score += 0.5  # Хорошее использование
                elif capacity_ratio > 1:
                    score -= 1  # Перегруженная аудитория (штраф)
                elif capacity_ratio < 0.4:
                    score -= 0.5  # Неэффективное использование (небольшой штраф)

        return score

    def _analyze_distribution(self):
        """Анализирует распределение занятий по неделям с учетом подгрупп"""
        week_loads = defaultdict(int)
        course_distribution = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        for time_key, lessons in self.schedule.items():
            week, day, slot = time_key
            week_loads[week] += len(lessons)

            for lesson in lessons:
                course_id = lesson['course'].id
                lesson_type = lesson['lesson_type']

                # Добавляем информацию о подгруппе, если есть
                subgroup_key = 'general'
                if lesson.get('lab_subgroup'):
                    subgroup_key = f"subgroup_{lesson['lab_subgroup'].id}"

                course_distribution[course_id][lesson_type][f"{week}_{subgroup_key}"] += 1

        # Вывод общей статистики
        print("\n=== Распределение занятий по неделям ===")
        for week, count in sorted(week_loads.items()):
            print(f"Неделя {week}: {count} занятий")

        # Вывод распределения по курсам
        print("\n=== Распределение занятий по курсам ===")
        for course_id, types in course_distribution.items():
            course = Course.query.get(course_id)
            print(f"\nКурс: {course.name}")

            for lesson_type, weeks_data in types.items():
                print(f"  {lesson_type.capitalize()}:")
                for week_key, count in sorted(weeks_data.items()):
                    week_num, subgroup_key = week_key.split('_', 1)
                    subgroup_info = ""

                    if subgroup_key != 'general':
                        subgroup_id = int(subgroup_key.split('_')[1])
                        subgroup = LabSubgroup.query.get(subgroup_id)
                        if subgroup:
                            subgroup_info = f" ({subgroup.name})"

                    print(f"    Неделя {week_num}{subgroup_info}: {count} занятий")

    def _find_suitable_rooms(self, course, lesson_type, total_students):
        """Находит подходящие аудитории с учетом предпочтений курса"""
        suitable_rooms = []

        # Сначала проверяем предпочтительные аудитории курса
        preferred_rooms = list(course.preferred_rooms)
        if preferred_rooms:
            for room in preferred_rooms:
                # Проверяем вместимость
                if room.capacity < total_students:
                    continue

                # Проверяем тип аудитории
                if lesson_type == "lecture" and not room.is_lecture_hall:
                    continue
                if lesson_type == "lab" and not room.is_lab:
                    continue

                suitable_rooms.append(room)

        # Если подходящих предпочтительных аудиторий нет, ищем среди всех
        if not suitable_rooms:
            for room in self.rooms:
                # Проверяем вместимость
                if room.capacity < total_students:
                    continue

                # Проверяем тип аудитории
                if lesson_type == "lecture" and not room.is_lecture_hall:
                    continue
                if lesson_type == "lab" and not room.is_lab:
                    continue

                if lesson_type == "lab" and room.is_computer_lab:
                    suitable_rooms.insert(0, room)  # Компьютерные классы в приоритете для лабораторных
                else:
                    suitable_rooms.append(room)

        return suitable_rooms

    def _select_best_room(self, course, rooms, total_students):
        """Выбирает наиболее подходящую аудиторию с учетом предпочтений"""
        # Сначала проверяем предпочтительные аудитории
        preferred_rooms = [room for room in rooms if room in course.preferred_rooms]
        if preferred_rooms:
            # Из предпочтительных выбираем наиболее подходящую по размеру
            return min(preferred_rooms,
                       key=lambda r: r.capacity - total_students if r.capacity >= total_students else float('inf'))

        # Если предпочтительных нет или они не подходят, выбираем из всех доступных
        return min(rooms, key=lambda r: r.capacity - total_students if r.capacity >= total_students else float('inf'))

    def _check_constraints(self, time_key, course, group_ids, suitable_rooms, teacher, lab_subgroup=None):
        """Проверяет жесткие и мягкие ограничения для размещения занятия с учетом подгрупп"""
        week, day, slot = time_key

        # Проверка на уже размещенные вручную занятия
        for time_k, lessons in self.schedule.items():
            if time_k == time_key:
                for lesson in lessons:
                    if lesson.get('is_manually_placed', False):
                        # Если это ручное занятие, проверяем конфликты
                        # Конфликт преподавателя
                        if lesson['teacher'] and lesson['teacher'].id == teacher.id:
                            return False

                        # Конфликт аудитории
                        if all(room.id == lesson['room'].id for room in suitable_rooms):
                            return False

                        # Конфликт групп
                        for group_id in group_ids:
                            if group_id in lesson['groups']:
                                # Проверяем подгруппы при необходимости
                                if lab_subgroup and lesson.get('lab_subgroup'):
                                    if lab_subgroup.id != lesson['lab_subgroup'].id:
                                        continue  # Разные подгруппы могут заниматься параллельно
                                return False

        # НОВОЕ: Добавляем предпочтение к ранним парам в зависимости от настроек
        if self.settings.preferred_lesson_distribution == 'morning' and slot > 3:
            # Для утренних пар высокая вероятность отклонения поздних пар
            rejection_probability = (slot - 3) / self.slots_per_day
            if random.random() < rejection_probability:
                return False
        elif self.settings.preferred_lesson_distribution == 'afternoon' and (slot < 2 or slot > 5):
            # Для дневных пар предпочтение средних слотов
            rejection_probability = min(abs(slot - 3.5) / self.slots_per_day, 0.5)
            if random.random() < rejection_probability:
                return False

        # Если время уже занято в расписании
        if time_key in self.schedule:
            # Проверка доступности преподавателя
            for item in self.schedule[time_key]:
                if item['teacher'].id == teacher.id:
                    return False

                # Проверка доступности групп с учетом подгрупп
                if lab_subgroup:
                    # Если это занятие для подгруппы, проверяем конфликты с другими занятиями этой же группы
                    # Нельзя ставить занятия одной группе и ее подгруппам одновременно
                    for group_id in group_ids:
                        if group_id in item['groups']:
                            # Проверяем, не пересекаются ли подгруппы
                            item_subgroup = item.get('lab_subgroup')

                            # Если другое занятие не для подгруппы, или для другой подгруппы той же группы
                            if not item_subgroup or (item_subgroup and item_subgroup.group_id == lab_subgroup.group_id):
                                return False
                else:
                    # Если это обычное занятие, проверяем простое пересечение групп
                    for group_id in group_ids:
                        if group_id in item['groups']:
                            return False

            # Проверка доступности аудиторий
            occupied_rooms = [item['room'].id for item in self.schedule[time_key]]
            if all(room.id in occupied_rooms for room in suitable_rooms):
                return False

        # Проверка мягких ограничений с учетом предпочтений преподавателя

        # 1. Проверка на максимальное количество пар в день
        max_lessons = min(self.settings.max_lessons_per_day_global, teacher.max_lessons_per_day)
        teacher_lessons_today = 0
        for check_slot in range(self.slots_per_day):
            check_key = (week, day, check_slot)
            if check_key in self.schedule:
                for item in self.schedule[check_key]:
                    if item['teacher'].id == teacher.id:
                        teacher_lessons_today += 1

        if teacher_lessons_today >= max_lessons:
            return False

        # 2. Проверка на максимальное количество пар в день для групп
        for group_id in group_ids:
            group = Group.query.get(group_id)
            group_max_lessons = min(self.settings.max_lessons_per_day_global, group.max_lessons_per_day)
            group_lessons_today = 0
            for check_slot in range(self.slots_per_day):
                check_key = (week, day, check_slot)
                if check_key in self.schedule:
                    for item in self.schedule[check_key]:
                        if group_id in item['groups']:
                            # Учитываем подгруппы - если текущее занятие для подгруппы,
                            # и другое занятие тоже для подгруппы этой же группы,
                            # мы можем их запланировать параллельно
                            if lab_subgroup and item.get('lab_subgroup'):
                                # Если оба занятия для разных подгрупп той же группы, не считаем как пересечение
                                if item['lab_subgroup'].group_id == lab_subgroup.group_id and item[
                                    'lab_subgroup'].id != lab_subgroup.id:
                                    continue

                            group_lessons_today += 1

            if group_lessons_today >= group_max_lessons:
                return False

        # 3. Проверка на "окна" в расписании студентов, если включена соответствующая настройка
        if self.settings.avoid_windows:
            for group_id in group_ids:
                # Получаем все занятия группы в этот день
                group_slots = []
                for check_slot in range(self.slots_per_day):
                    check_key = (week, day, check_slot)
                    if check_key in self.schedule:
                        for item in self.schedule[check_key]:
                            if group_id in item['groups']:
                                group_slots.append(check_slot)

                # Проверяем, создаст ли новое занятие "окно"
                if group_slots:
                    min_slot = min(group_slots)
                    max_slot = max(group_slots)

                    # Если занятие создает окно, с некоторой вероятностью отклоняем его
                    if min_slot < slot < max_slot and slot not in group_slots:
                        # Окно возникает - с вероятностью 70% отклоняем это размещение
                        if random.random() < 0.7:
                            return False

                    # Если занятие расширяет диапазон занятий, создавая большой разрыв
                    if (slot < min_slot and min_slot - slot > 2) or (slot > max_slot and slot - max_slot > 2):
                        # С вероятностью 40% отклоняем большие разрывы
                        if random.random() < 0.4:
                            return False

        return True

    def _save_schedule(self):
        """Сохраняет сгенерированное расписание в базу данных с учетом подгрупп"""
        for time_key, items in self.schedule.items():
            week, day, slot = time_key

            for item in items:
                # Пропускаем уже размещенные вручную элементы, чтобы не дублировать их
                if item.get('is_manually_placed', False):
                    continue

                schedule_item = ScheduleItem(
                    course_id=item['course'].id,
                    room_id=item['room'].id,
                    teacher_id=item['teacher'].id,
                    week=week,
                    day=day,
                    time_slot=slot,
                    lesson_type=item['lesson_type'],
                    groups=','.join(map(str, item['groups'])),
                    is_manually_placed=False
                )

                # Добавляем информацию о подгруппе, если есть
                if item.get('lab_subgroup'):
                    schedule_item.lab_subgroup_id = item['lab_subgroup'].id

                db.session.add(schedule_item)

        db.session.commit()


# Создание базы данных при запуске приложения
def create_tables():
    with app.app_context():
        db.create_all()

        # Создаем настройки по умолчанию, если их нет
        if not Settings.query.first():
            settings = Settings(
                weeks_count=18,
                days_per_week=5,
                slots_per_day=7,
                avoid_windows=True,
                prioritize_faculty=True,
                respect_teacher_preferences=True,
                optimize_room_usage=True,
                max_lessons_per_day_global=4,
                preferred_lesson_distribution='balanced',
                version=1
            )
            db.session.add(settings)
            db.session.commit()


if __name__ == '__main__':
    # Инициализация базы данных перед запуском приложения
    create_tables()
    app.run(debug=True)