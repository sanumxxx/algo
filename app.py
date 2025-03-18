from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SelectField, BooleanField, SubmitField, SelectMultipleField
from wtforms.validators import DataRequired, NumberRange
from flask_wtf.csrf import CSRFProtect
from datetime import datetime, timedelta
import random
import copy
import os
import math
import time
from collections import defaultdict

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///schedule.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
csrf = CSRFProtect(app)


# Модели данных
class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Изменено отношение с курсами
    courses = relationship("CourseTeacher", back_populates="teacher")

    def __repr__(self):
        return f'<Teacher {self.name}>'


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    courses = relationship("CourseGroup", back_populates="group")

    def __repr__(self):
        return f'<Group {self.name}>'


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    is_computer_lab = db.Column(db.Boolean, default=False)
    is_lecture_hall = db.Column(db.Boolean, default=False)
    is_lab = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<Room {self.name}>'


# Связь между курсами и предпочтительными аудиториями
course_preferred_rooms = db.Table('course_preferred_rooms',
                                  db.Column('course_id', db.Integer, db.ForeignKey('course.id'), primary_key=True),
                                  db.Column('room_id', db.Integer, db.ForeignKey('room.id'), primary_key=True)
                                  )


# Новая модель для связи курса с преподавателями по типам занятий
class CourseTeacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    lesson_type = db.Column(db.String(10), nullable=False)  # 'lecture', 'practice', 'lab'

    course = relationship("Course", back_populates="course_teachers")
    teacher = relationship("Teacher", back_populates="courses")

    def __repr__(self):
        return f'<CourseTeacher {self.course.name} - {self.teacher.name} - {self.lesson_type}>'


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Удалены поля teacher_id и teacher, добавлено отношение course_teachers
    lecture_count = db.Column(db.Integer, default=0)
    practice_count = db.Column(db.Integer, default=0)
    lab_count = db.Column(db.Integer, default=0)
    start_week = db.Column(db.Integer, default=1)
    distribution_type = db.Column(db.String(20), default='even')  # even, front_loaded, back_loaded, etc.
    groups = relationship("CourseGroup", back_populates="course")
    course_teachers = relationship("CourseTeacher", back_populates="course", cascade="all, delete-orphan")
    schedule_items = relationship("ScheduleItem", back_populates="course")
    preferred_rooms = relationship("Room", secondary=course_preferred_rooms,
                                   backref=db.backref('preferred_for_courses', lazy='dynamic'))

    def __repr__(self):
        return f'<Course {self.name}>'

    def get_teacher_for_type(self, lesson_type):
        """Получить преподавателя для определенного типа занятий"""
        course_teacher = CourseTeacher.query.filter_by(course_id=self.id, lesson_type=lesson_type).first()
        return course_teacher.teacher if course_teacher else None

    def get_teacher_name_for_type(self, lesson_type):
        """Получить имя преподавателя для определенного типа занятий"""
        teacher = self.get_teacher_for_type(lesson_type)
        return teacher.name if teacher else "Не назначен"


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
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'),
                           nullable=True)  # Изменено: добавлен ID преподавателя
    teacher = relationship("Teacher")  # Изменено: добавлено отношение с преподавателем

    def __repr__(self):
        return f'<ScheduleItem {self.course.name} - Week {self.week}, Day {self.day}, Slot {self.time_slot}>'

    def get_group_ids(self):
        return [int(g) for g in self.groups.split(',')]


class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    weeks_count = db.Column(db.Integer, default=18)
    days_per_week = db.Column(db.Integer, default=5)
    slots_per_day = db.Column(db.Integer, default=7)

    def __repr__(self):
        return f'<Settings weeks={self.weeks_count}>'


# Формы
class TeacherForm(FlaskForm):
    name = StringField('ФИО преподавателя', validators=[DataRequired()])
    submit = SubmitField('Сохранить')


class GroupForm(FlaskForm):
    name = StringField('Название группы', validators=[DataRequired()])
    size = IntegerField('Численность', validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Сохранить')


class RoomForm(FlaskForm):
    name = StringField('Номер аудитории', validators=[DataRequired()])
    capacity = IntegerField('Вместимость', validators=[DataRequired(), NumberRange(min=1)])
    is_computer_lab = BooleanField('Компьютерный класс')
    is_lecture_hall = BooleanField('Лекционная аудитория')
    is_lab = BooleanField('Лабораторная')
    submit = SubmitField('Сохранить')


class CourseForm(FlaskForm):
    name = StringField('Название дисциплины', validators=[DataRequired()])
    # Изменено: добавлен флаг для разных преподавателей и поля для разных типов занятий
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
    groups = SelectMultipleField('Группы', coerce=int, validators=[DataRequired()])
    preferred_rooms = SelectMultipleField('Предпочтительные аудитории', coerce=int)
    submit = SubmitField('Сохранить')


class SettingsForm(FlaskForm):
    weeks_count = IntegerField('Количество недель', validators=[DataRequired(), NumberRange(min=1, max=52)])
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
    schedule_exists = ScheduleItem.query.first() is not None

    return render_template('index.html',
                           settings=settings,
                           teacher_count=teacher_count,
                           group_count=group_count,
                           room_count=room_count,
                           course_count=course_count,
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
        db.session.commit()
        flash('Настройки успешно сохранены!', 'success')
        return redirect(url_for('index'))

    return render_template('settings.html', form=form)


@app.route('/teachers')
def teachers_list():
    teachers = Teacher.query.all()
    return render_template('teachers_list.html', teachers=teachers)


@app.route('/teachers/add', methods=['GET', 'POST'])
def add_teacher():
    form = TeacherForm()
    if form.validate_on_submit():
        teacher = Teacher(name=form.name.data)
        db.session.add(teacher)
        db.session.commit()
        flash('Преподаватель успешно добавлен!', 'success')
        return redirect(url_for('teachers_list'))
    return render_template('teacher_form.html', form=form, title='Добавить преподавателя')


@app.route('/teachers/edit/<int:id>', methods=['GET', 'POST'])
def edit_teacher(id):
    teacher = Teacher.query.get_or_404(id)
    form = TeacherForm(obj=teacher)
    if form.validate_on_submit():
        form.populate_obj(teacher)
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
    if form.validate_on_submit():
        group = Group(name=form.name.data, size=form.size.data)
        db.session.add(group)
        db.session.commit()
        flash('Группа успешно добавлена!', 'success')
        return redirect(url_for('groups_list'))
    return render_template('group_form.html', form=form, title='Добавить группу')


@app.route('/groups/edit/<int:id>', methods=['GET', 'POST'])
def edit_group(id):
    group = Group.query.get_or_404(id)
    form = GroupForm(obj=group)
    if form.validate_on_submit():
        form.populate_obj(group)
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
            is_lab=form.is_lab.data
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
    form.groups.choices = [(g.id, g.name) for g in Group.query.all()]
    form.preferred_rooms.choices = [(r.id, f"{r.name} (вместимость: {r.capacity})") for r in Room.query.all()]

    if form.validate_on_submit():
        print("\n=== ОТЛАДКА: ДОБАВЛЕНИЕ ДИСЦИПЛИНЫ ===")
        print(f"Название: {form.name.data}")

        # Создаем объект курса без преподавателей
        course = Course(
            name=form.name.data,
            lecture_count=form.lecture_count.data,
            practice_count=form.practice_count.data,
            lab_count=form.lab_count.data,
            start_week=form.start_week.data,
            distribution_type=form.distribution_type.data
        )
        db.session.add(course)
        db.session.flush()  # Получаем ID курса без коммита

        # Связываем курс с группами
        for group_id in form.groups.data:
            course_group = CourseGroup(course_id=course.id, group_id=group_id)
            db.session.add(course_group)

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
        if form.lab_count.data > 0 and form.lab_teacher_id.data:
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
            print(
                f"  - Тип: {teacher.lesson_type}, Преподаватель ID: {teacher.teacher_id}, Имя: {Teacher.query.get(teacher.teacher_id).name}")
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
    form.groups.choices = [(g.id, g.name) for g in Group.query.all()]
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
        lab_teacher = course.get_teacher_for_type('lab')

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

        # Update course groups
        CourseGroup.query.filter_by(course_id=course.id).delete()
        for group_id in form.groups.data:
            course_group = CourseGroup(course_id=course.id, group_id=group_id)
            db.session.add(course_group)

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
        if form.lab_count.data > 0 and form.lab_teacher_id.data:
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
            print(
                f"  - Тип: {teacher.lesson_type}, Преподаватель ID: {teacher.teacher_id}, Имя: {Teacher.query.get(teacher.teacher_id).name}")
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
    # Удалим существующее расписание
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
    schedule_generator = ScheduleGenerator(settings.weeks_count)
    success = schedule_generator.generate()

    if success:
        flash('Расписание успешно сгенерировано!', 'success')
    else:
        flash('Не удалось сгенерировать расписание. Попробуйте изменить параметры.', 'error')

    return redirect(url_for('index'))


@app.route('/schedule')
def view_schedule():
    groups = Group.query.all()
    settings = Settings.query.first()
    if not settings:
        settings = Settings(weeks_count=18)
        db.session.add(settings)
        db.session.commit()

    weeks = list(range(1, settings.weeks_count + 1))

    return render_template('schedule_view.html', groups=groups, weeks=weeks)


@app.route('/schedule/data')
def schedule_data():
    group_id = request.args.get('group_id', type=int)
    week = request.args.get('week', type=int)

    if not group_id or not week:
        return jsonify({'error': 'Missing parameters'}), 400

    # Получаем расписание для выбранной группы и недели
    schedule_items = db.session.query(ScheduleItem).join(
        Course
    ).filter(
        ScheduleItem.week == week,
        ScheduleItem.groups.like(f'%{group_id}%')
    ).all()

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
                lesson_type=item.lesson_type
            ).first()
            if course_teacher and course_teacher.teacher:
                teacher_name = course_teacher.teacher.name

        schedule_data.append({
            'id': item.id,
            'day': item.day,
            'time_slot': item.time_slot,
            'course_name': course.name,
            'teacher_name': teacher_name,
            'room_name': room.name,
            'lesson_type': item.lesson_type
        })

    return jsonify(schedule_data)


# Класс для генерации расписания
class ScheduleGenerator:
    def __init__(self, weeks_count=18):
        self.weeks_count = weeks_count
        self.days_per_week = 5  # Пн-Пт
        self.slots_per_day = 7  # 7 пар в день

        # Получаем все необходимые данные
        self.courses = Course.query.all()
        self.rooms = Room.query.all()
        self.teachers = Teacher.query.all()
        self.groups = Group.query.all()

        # Создаем пустое расписание
        self.schedule = {}  # (week, day, slot) -> [schedule_items]

        # Ограничения по времени и итерациям
        self.max_generation_time = 30  # максимальное время генерации расписания в секундах
        self.max_iterations = 1000  # максимальное количество итераций

    def generate(self):
        try:
            start_time = time.time()
            print("Начало генерации расписания...")

            # Создаем начальное расписание с учетом частоты занятий
            if not self._create_frequency_based_schedule():
                print("Не удалось создать начальное расписание")
                return False

            print(f"Начальное расписание создано за {time.time() - start_time:.2f} сек.")

            # Оптимизируем расписание, если есть время
            if time.time() - start_time < self.max_generation_time:
                print("Оптимизация размещения в дни недели...")
                self._optimize_day_distribution()

            # Сохраняем сгенерированное расписание в БД
            self._save_schedule()
            print(f"Расписание сгенерировано и сохранено за {time.time() - start_time:.2f} сек.")
            return True
        except Exception as e:
            print(f"Ошибка при генерации расписания: {e}")
            return False

    def _create_frequency_based_schedule(self):
        """Создаем расписание, исходя из частоты проведения занятий разных типов"""
        # Для каждого курса определяем частоту занятий
        for course in self.courses:
            # Получаем базовую информацию
            group_ids = [g.group_id for g in course.groups]
            total_students = sum([Group.query.get(gid).size for gid in group_ids])

            # Определяем доступные недели с учетом начальной недели курса
            available_weeks = list(range(course.start_week, self.weeks_count + 1))

            if not available_weeks:
                print(f"Недостаточно недель для дисциплины {course.name}")
                continue

            # Общее количество доступных недель - именно в этот диапазон нужно распределить занятия
            total_weeks = len(available_weeks)

            print(f"Курс: {course.name}, начинается с недели {course.start_week}, доступно {total_weeks} недель")

            # Рассчитываем частоту занятий
            lessons_to_schedule = []

            # Обрабатываем лекции
            if course.lecture_count > 0:
                # Получаем преподавателя для лекций
                lecture_teacher = course.get_teacher_for_type('lecture')
                if not lecture_teacher:
                    print(f"  ОШИБКА: Преподаватель для лекций не назначен для курса {course.name}")
                    continue

                # Рассчитываем частоту - как часто нужно проводить лекции
                frequency = total_weeks / course.lecture_count
                print(f"  Лекции: {course.lecture_count} шт., частота: одна лекция каждые {frequency:.2f} недели")

                # Генерируем недели для лекций с учетом частоты
                weeks = self._generate_weeks_with_frequency(
                    course, 'lecture', frequency, available_weeks)

                # Добавляем лекции в список занятий
                for week in weeks:
                    lessons_to_schedule.append({
                        'course': course,
                        'lesson_type': 'lecture',
                        'teacher': lecture_teacher,
                        'group_ids': group_ids,
                        'total_students': total_students,
                        'target_week': week
                    })

            # Обрабатываем практики
            if course.practice_count > 0:
                # Получаем преподавателя для практик
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
                for week in weeks:
                    lessons_to_schedule.append({
                        'course': course,
                        'lesson_type': 'practice',
                        'teacher': practice_teacher,
                        'group_ids': group_ids,
                        'total_students': total_students,
                        'target_week': week
                    })

            # Обрабатываем лабораторные
            if course.lab_count > 0:
                # Получаем преподавателя для лабораторных
                lab_teacher = course.get_teacher_for_type('lab')
                if not lab_teacher:
                    print(f"  ОШИБКА: Преподаватель для лабораторных не назначен для курса {course.name}")
                    continue

                # Рассчитываем частоту
                frequency = total_weeks / course.lab_count
                print(f"  Лабораторные: {course.lab_count} шт., частота: одна лаба каждые {frequency:.2f} недели")

                # Генерируем недели для лабораторных с учетом частоты
                weeks = self._generate_weeks_with_frequency(
                    course, 'lab', frequency, available_weeks)

                # Добавляем лабораторные в список занятий
                for week in weeks:
                    lessons_to_schedule.append({
                        'course': course,
                        'lesson_type': 'lab',
                        'teacher': lab_teacher,
                        'group_ids': group_ids,
                        'total_students': total_students,
                        'target_week': week
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
                print(f"  Недели лабораторных: {sorted([l['target_week'] for l in labs])}")

            # Размещаем все занятия курса
            for lesson in lessons_to_schedule:
                if not self._place_lesson(lesson):
                    print(
                        f"  ОШИБКА: Не удалось разместить занятие {course.name} {lesson['lesson_type']} на неделе {lesson['target_week']}")

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
        teacher = lesson.get('teacher')  # Преподаватель для данного типа занятия

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

        # Пробуем найти место в указанной неделе
        for day in range(self.days_per_week):
            for slot in range(self.slots_per_day):
                time_key = (target_week, day, slot)

                # Проверяем ограничения с учетом конкретного преподавателя
                if self._check_constraints(time_key, course, group_ids, suitable_rooms, teacher):
                    # Выбираем аудиторию
                    room = self._select_best_room(course, suitable_rooms, total_students)

                    # Добавляем занятие в расписание
                    if time_key not in self.schedule:
                        self.schedule[time_key] = []

                    self.schedule[time_key].append({
                        'course': course,
                        'room': room,
                        'lesson_type': lesson_type,
                        'groups': group_ids,
                        'teacher': teacher  # Добавляем преподавателя в запись расписания
                    })

                    return True

        # Если не смогли разместить в текущую неделю, пробуем в ближайшие
        for offset in range(1, 3):  # Проверяем до 2 недель в обе стороны
            # Пробуем неделю раньше
            earlier_week = target_week - offset
            if earlier_week >= course.start_week:
                for day in range(self.days_per_week):
                    for slot in range(self.slots_per_day):
                        time_key = (earlier_week, day, slot)
                        if self._check_constraints(time_key, course, group_ids, suitable_rooms, teacher):
                            room = self._select_best_room(course, suitable_rooms, total_students)
                            if time_key not in self.schedule:
                                self.schedule[time_key] = []
                            self.schedule[time_key].append({
                                'course': course,
                                'room': room,
                                'lesson_type': lesson_type,
                                'groups': group_ids,
                                'teacher': teacher
                            })
                            return True

            # Пробуем неделю позже
            later_week = target_week + offset
            if later_week <= self.weeks_count:
                for day in range(self.days_per_week):
                    for slot in range(self.slots_per_day):
                        time_key = (later_week, day, slot)
                        if self._check_constraints(time_key, course, group_ids, suitable_rooms, teacher):
                            room = self._select_best_room(course, suitable_rooms, total_students)
                            if time_key not in self.schedule:
                                self.schedule[time_key] = []
                            self.schedule[time_key].append({
                                'course': course,
                                'room': room,
                                'lesson_type': lesson_type,
                                'groups': group_ids,
                                'teacher': teacher
                            })
                            return True

        # Не смогли разместить занятие
        return False

    def _optimize_day_distribution(self):
        """Оптимизирует распределение занятий по дням недели"""
        # Для этой версии просто перебалансируем нагрузку по дням недели
        iterations = 0
        start_time = time.time()

        while iterations < self.max_iterations and time.time() - start_time < self.max_generation_time:
            # Анализируем текущее распределение по дням недели
            day_loads = self._analyze_day_distribution()

            # Находим день с максимальной и минимальной нагрузкой
            max_day = max(day_loads.items(), key=lambda x: x[1])[0]
            min_day = min(day_loads.items(), key=lambda x: x[1])[0]

            # Если разница невелика, завершаем оптимизацию
            if day_loads[max_day] - day_loads[min_day] <= 1:
                break

            # Пробуем переместить занятие из дня с максимальной нагрузкой в день с минимальной
            moved = False
            for time_key, lessons in list(self.schedule.items()):
                week, day, slot = time_key

                # Ищем занятие в день с максимальной нагрузкой
                if day == max_day:
                    for lesson_idx, lesson in enumerate(lessons):
                        # Проверяем, можно ли переместить это занятие в день с минимальной нагрузкой
                        for new_slot in range(self.slots_per_day):
                            new_key = (week, min_day, new_slot)

                            # Проверяем ограничения для нового расположения
                            if new_key not in self.schedule:
                                self.schedule[new_key] = []

                            # Временно удаляем занятие из текущего расписания
                            self.schedule[time_key].pop(lesson_idx)
                            if not self.schedule[time_key]:
                                del self.schedule[time_key]

                            # Пробуем разместить в новом месте
                            suitable_rooms = self._find_suitable_rooms(
                                lesson['course'], lesson['lesson_type'],
                                sum([Group.query.get(gid).size for gid in lesson['groups']])
                            )

                            if suitable_rooms and self._check_constraints(
                                    new_key, lesson['course'], lesson['groups'], suitable_rooms, lesson['teacher']
                            ):
                                # Нашли подходящее место - перемещаем занятие
                                lesson['room'] = self._select_best_room(
                                    lesson['course'], suitable_rooms,
                                    sum([Group.query.get(gid).size for gid in lesson['groups']])
                                )
                                self.schedule[new_key].append(lesson)
                                moved = True
                                break
                            else:
                                # Возвращаем занятие на место
                                if time_key not in self.schedule:
                                    self.schedule[time_key] = []
                                self.schedule[time_key].insert(lesson_idx, lesson)

                        if moved:
                            break

                if moved:
                    break

            # Если не смогли переместить ни одно занятие, завершаем оптимизацию
            if not moved:
                break

            iterations += 1

        print(f"Оптимизация дней завершена после {iterations} итераций.")

    def _analyze_day_distribution(self):
        """Анализирует распределение занятий по дням недели"""
        day_loads = {day: 0 for day in range(self.days_per_week)}

        for time_key, lessons in self.schedule.items():
            week, day, slot = time_key
            day_loads[day] += len(lessons)

        return day_loads

    def _analyze_distribution(self):
        """Анализирует распределение занятий по неделям"""
        week_loads = defaultdict(int)
        course_distribution = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        for time_key, lessons in self.schedule.items():
            week, day, slot = time_key
            week_loads[week] += len(lessons)

            for lesson in lessons:
                course_id = lesson['course'].id
                lesson_type = lesson['lesson_type']
                course_distribution[course_id][lesson_type][week] += 1

        # Вывод общей статистики
        print("\n=== Распределение занятий по неделям ===")
        for week, count in sorted(week_loads.items()):
            print(f"Неделя {week}: {count} занятий")

        # Вывод распределения по курсам
        print("\n=== Распределение занятий по курсам ===")
        for course_id, types in course_distribution.items():
            course = Course.query.get(course_id)
            print(f"\nКурс: {course.name}")

            for lesson_type, weeks in types.items():
                print(f"  {lesson_type.capitalize()}:")
                for week, count in sorted(weeks.items()):
                    print(f"    Неделя {week}: {count} занятий")

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

    def _check_constraints(self, time_key, course, group_ids, suitable_rooms, teacher):
        """Проверяет жесткие и мягкие ограничения для размещения занятия"""
        week, day, slot = time_key

        # Если время уже занято в расписании
        if time_key in self.schedule:
            # Проверка доступности преподавателя
            for item in self.schedule[time_key]:
                if item['teacher'].id == teacher.id:
                    return False

                # Проверка доступности групп
                for group_id in group_ids:
                    if group_id in item['groups']:
                        return False

            # Проверка доступности аудиторий
            occupied_rooms = [item['room'].id for item in self.schedule[time_key]]
            if all(room.id in occupied_rooms for room in suitable_rooms):
                return False

        # Проверка мягких ограничений
        # Например, не ставить более 3 пар одному преподавателю в день
        teacher_lessons_today = 0
        for check_slot in range(self.slots_per_day):
            check_key = (week, day, check_slot)
            if check_key in self.schedule:
                for item in self.schedule[check_key]:
                    if item['teacher'].id == teacher.id:
                        teacher_lessons_today += 1

        if teacher_lessons_today >= 3:
            return False

        # Не ставить больше 4 пар в день для одной группы
        for group_id in group_ids:
            group_lessons_today = 0
            for check_slot in range(self.slots_per_day):
                check_key = (week, day, check_slot)
                if check_key in self.schedule:
                    for item in self.schedule[check_key]:
                        if group_id in item['groups']:
                            group_lessons_today += 1

            if group_lessons_today >= 4:
                return False

        return True

    def _save_schedule(self):
        """Сохраняет сгенерированное расписание в базу данных"""
        for time_key, items in self.schedule.items():
            week, day, slot = time_key

            for item in items:
                schedule_item = ScheduleItem(
                    course_id=item['course'].id,
                    room_id=item['room'].id,
                    teacher_id=item['teacher'].id,  # Сохраняем ID преподавателя
                    week=week,
                    day=day,
                    time_slot=slot,
                    lesson_type=item['lesson_type'],
                    groups=','.join(map(str, item['groups']))
                )
                db.session.add(schedule_item)

        db.session.commit()


# Создание базы данных при запуске приложения
def create_tables():
    with app.app_context():
        db.create_all()

        # Создаем настройки по умолчанию, если их нет
        if not Settings.query.first():
            settings = Settings(weeks_count=18)
            db.session.add(settings)
            db.session.commit()


if __name__ == '__main__':
    # Инициализация базы данных перед запуском приложения
    create_tables()
    app.run(debug=True)