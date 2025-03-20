from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_wtf.csrf import CSRFProtect
import os
import random
import copy
import math
import time
import json

# Import models
from models import db, Faculty, Teacher, Group, Room, Course, CourseGroup, ScheduleItem, Settings, LabSubgroup, CourseTeacher

# Import forms
from forms import (FacultyForm, TeacherForm, GroupForm, RoomForm, CourseForm,
                  SettingsForm, ManualScheduleItemForm, SubgroupForm)

# Import scheduler
from scheduler import ScheduleGenerator

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///schedule.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
csrf = CSRFProtect(app)

# Helper functions
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