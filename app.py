from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import json
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'university_schedule_generator_secret_key'

# Путь к файлу с данными
DATA_FILE = 'schedule_data.json'

# Инициализация данных
default_data = {
    'semester_weeks': 0,
    'professors': [],
    'classrooms': [],
    'groups': [],
    'courses': [],
    'schedule': {}
}


# Функция для загрузки данных из файла
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
            return default_data
    return default_data


# Функция для сохранения данных в файл
def save_data(data_to_save):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Ошибка сохранения данных: {e}")
        return False


# Загрузка данных при запуске приложения
data = load_data()


# Вспомогательные функции
def get_professor_by_id(professor_id):
    """Получение преподавателя по ID с корректной обработкой типов."""
    if professor_id is None:
        return None

    # Преобразуем ID к целому числу для сравнения
    try:
        professor_id = int(professor_id)
    except (ValueError, TypeError):
        return None

    for professor in data['professors']:
        if int(professor['id']) == professor_id:
            return professor
    return None


def get_groups_by_ids(group_ids):
    """Получение групп по списку ID с корректной обработкой типов."""
    if not group_ids:
        return []

    # Преобразуем все ID к целым числам для сравнения
    try:
        group_ids = [int(gid) for gid in group_ids]
    except (ValueError, TypeError):
        return []

    result = []
    for group in data['groups']:
        if int(group['id']) in group_ids:
            result.append(group)

    return result


def get_classroom_by_id(classroom_id):
    """Получение аудитории по ID с корректной обработкой типов."""
    if classroom_id is None:
        return None

    # Преобразуем ID к целому числу для сравнения
    try:
        classroom_id = int(classroom_id)
    except (ValueError, TypeError):
        return None

    for classroom in data['classrooms']:
        if int(classroom['id']) == classroom_id:
            return classroom
    return None


def get_course_by_id(course_id):
    """Получение курса по ID с правильной обработкой типов."""
    if course_id is None:
        return None

    # Пробуем сравнивать как числа и как строки
    for course in data['courses']:
        if str(course['id']) == str(course_id):
            return course
    return None


# Добавление вспомогательных функций в контекст шаблонов
@app.context_processor
def utility_processor():
    return {
        'get_professor_by_id': get_professor_by_id,
        'get_groups_by_ids': get_groups_by_ids,
        'get_classroom_by_id': get_classroom_by_id,
        'get_course_by_id': get_course_by_id
    }


# Маршруты
@app.route('/')
def index():
    return render_template('index.html', data=data)


@app.route('/set_semester', methods=['POST'])
def set_semester():
    weeks = int(request.form['weeks'])
    data['semester_weeks'] = weeks
    save_data(data)
    flash(f'Семестр установлен на {weeks} недель')
    return redirect(url_for('index'))


@app.route('/add_professor', methods=['POST'])
def add_professor():
    name = request.form['name']
    professor_id = max([p.get('id', 0) for p in data['professors']] + [0]) + 1
    data['professors'].append({
        'id': professor_id,
        'name': name
    })
    save_data(data)
    flash(f'Преподаватель {name} добавлен')
    return redirect(url_for('index'))


@app.route('/edit_professor/<int:professor_id>', methods=['POST'])
def edit_professor(professor_id):
    professor_index = None
    for i, p in enumerate(data['professors']):
        if int(p['id']) == professor_id:
            professor_index = i
            break

    if professor_index is None:
        flash('Преподаватель не найден', 'danger')
        return redirect(url_for('index'))

    name = request.form['name']
    data['professors'][professor_index]['name'] = name
    save_data(data)

    flash(f'Преподаватель обновлен', 'success')
    return redirect(url_for('index'))


@app.route('/delete_professor/<int:professor_id>', methods=['POST'])
def delete_professor(professor_id):
    professor_index = None
    for i, p in enumerate(data['professors']):
        if int(p['id']) == professor_id:
            professor_index = i
            break

    if professor_index is None:
        flash('Преподаватель не найден', 'danger')
        return redirect(url_for('index'))

    # Проверяем, используется ли преподаватель в дисциплинах
    used_in_courses = []
    for course in data['courses']:
        if int(course.get('professor_id', 0)) == professor_id:
            used_in_courses.append(course['name'])

    if used_in_courses:
        flash(f'Невозможно удалить преподавателя, так как он используется в дисциплинах: {", ".join(used_in_courses)}',
              'danger')
        return redirect(url_for('index'))

    deleted_professor = data['professors'].pop(professor_index)
    save_data(data)
    flash(f'Преподаватель {deleted_professor["name"]} удален', 'success')
    return redirect(url_for('index'))


@app.route('/add_classroom', methods=['POST'])
def add_classroom():
    name = request.form['name']
    capacity = int(request.form['capacity'])
    features = request.form.getlist('features')
    classroom_id = max([c.get('id', 0) for c in data['classrooms']] + [0]) + 1
    data['classrooms'].append({
        'id': classroom_id,
        'name': name,
        'capacity': capacity,
        'features': features
    })
    save_data(data)
    flash(f'Аудитория {name} добавлена')
    return redirect(url_for('index'))


@app.route('/edit_classroom/<int:classroom_id>', methods=['POST'])
def edit_classroom(classroom_id):
    classroom_index = None
    for i, c in enumerate(data['classrooms']):
        if int(c['id']) == classroom_id:
            classroom_index = i
            break

    if classroom_index is None:
        flash('Аудитория не найдена', 'danger')
        return redirect(url_for('index'))

    name = request.form['name']
    capacity = int(request.form['capacity'])
    features = request.form.getlist('features')

    data['classrooms'][classroom_index]['name'] = name
    data['classrooms'][classroom_index]['capacity'] = capacity
    data['classrooms'][classroom_index]['features'] = features
    save_data(data)

    flash(f'Аудитория обновлена', 'success')
    return redirect(url_for('index'))


@app.route('/delete_classroom/<int:classroom_id>', methods=['POST'])
def delete_classroom(classroom_id):
    classroom_index = None
    for i, c in enumerate(data['classrooms']):
        if int(c['id']) == classroom_id:
            classroom_index = i
            break

    if classroom_index is None:
        flash('Аудитория не найдена', 'danger')
        return redirect(url_for('index'))

    # Проверяем, используется ли аудитория в дисциплинах
    used_in_courses = []
    for course in data['courses']:
        if 'possible_classrooms' in course:
            for c_id in course['possible_classrooms']:
                if int(c_id) == classroom_id:
                    used_in_courses.append(course['name'])
                    break

    if used_in_courses:
        flash(f'Невозможно удалить аудиторию, так как она используется в дисциплинах: {", ".join(used_in_courses)}',
              'danger')
        return redirect(url_for('index'))

    deleted_classroom = data['classrooms'].pop(classroom_index)
    save_data(data)
    flash(f'Аудитория {deleted_classroom["name"]} удалена', 'success')
    return redirect(url_for('index'))


@app.route('/add_group', methods=['POST'])
def add_group():
    name = request.form['name']
    students_count = int(request.form['students_count'])
    group_id = max([g.get('id', 0) for g in data['groups']] + [0]) + 1
    data['groups'].append({
        'id': group_id,
        'name': name,
        'students_count': students_count
    })
    save_data(data)
    flash(f'Группа {name} добавлена')
    return redirect(url_for('index'))


@app.route('/edit_group/<int:group_id>', methods=['POST'])
def edit_group(group_id):
    group_index = None
    for i, g in enumerate(data['groups']):
        if int(g['id']) == group_id:
            group_index = i
            break

    if group_index is None:
        flash('Группа не найдена', 'danger')
        return redirect(url_for('index'))

    name = request.form['name']
    students_count = int(request.form['students_count'])
    data['groups'][group_index]['name'] = name
    data['groups'][group_index]['students_count'] = students_count
    save_data(data)

    flash(f'Группа обновлена', 'success')
    return redirect(url_for('index'))


@app.route('/delete_group/<int:group_id>', methods=['POST'])
def delete_group(group_id):
    group_index = None
    for i, g in enumerate(data['groups']):
        if int(g['id']) == group_id:
            group_index = i
            break

    if group_index is None:
        flash('Группа не найдена', 'danger')
        return redirect(url_for('index'))

    # Проверяем, используется ли группа в дисциплинах
    used_in_courses = []
    for course in data['courses']:
        if 'groups' in course:
            group_ids = [int(g) for g in course['groups']]
            if group_id in group_ids:
                used_in_courses.append(course['name'])

    if used_in_courses:
        flash(f'Невозможно удалить группу, так как она используется в дисциплинах: {", ".join(used_in_courses)}',
              'danger')
        return redirect(url_for('index'))

    deleted_group = data['groups'].pop(group_index)
    save_data(data)
    flash(f'Группа {deleted_group["name"]} удалена', 'success')
    return redirect(url_for('index'))


@app.route('/add_course', methods=['POST'])
def add_course():
    name = request.form['name']
    professor_id = int(request.form['professor_id'])
    possible_classrooms = request.form.getlist('classrooms')
    groups = request.form.getlist('groups')
    lecture_count = int(request.form['lecture_count'])
    practice_count = int(request.form['practice_count'])
    start_week = int(request.form['start_week'])
    periodicity = request.form.get('periodicity', 'weekly')

    # Преобразуем ID в целые числа
    possible_classrooms = [int(c) for c in possible_classrooms]
    groups = [int(g) for g in groups]

    course_id = max([c.get('id', 0) for c in data['courses']] + [0]) + 1
    data['courses'].append({
        'id': course_id,
        'name': name,
        'professor_id': professor_id,
        'possible_classrooms': possible_classrooms,
        'groups': groups,
        'lecture_count': lecture_count,
        'practice_count': practice_count,
        'start_week': start_week,
        'periodicity': periodicity
    })
    save_data(data)
    flash(f'Дисциплина {name} добавлена')
    return redirect(url_for('index'))


@app.route('/edit_course/<int:course_id>')
def edit_course(course_id):
    course = None
    for c in data['courses']:
        if int(c['id']) == course_id:
            course = c
            break

    if not course:
        flash('Дисциплина не найдена', 'danger')
        return redirect(url_for('index'))

    return render_template('edit_course.html', course=course, data=data)


@app.route('/update_course/<int:course_id>', methods=['POST'])
def update_course(course_id):
    course_index = None
    for i, c in enumerate(data['courses']):
        if int(c['id']) == course_id:
            course_index = i
            break

    if course_index is None:
        flash('Дисциплина не найдена', 'danger')
        return redirect(url_for('index'))

    name = request.form['name']
    professor_id = int(request.form['professor_id'])
    possible_classrooms = request.form.getlist('classrooms')
    groups = request.form.getlist('groups')
    lecture_count = int(request.form['lecture_count'])
    practice_count = int(request.form['practice_count'])
    start_week = int(request.form['start_week'])
    periodicity = request.form.get('periodicity', 'weekly')

    # Преобразуем ID в целые числа
    possible_classrooms = [int(c) for c in possible_classrooms]
    groups = [int(g) for g in groups]

    # Обновляем данные дисциплины
    data['courses'][course_index] = {
        'id': course_id,
        'name': name,
        'professor_id': professor_id,
        'possible_classrooms': possible_classrooms,
        'groups': groups,
        'lecture_count': lecture_count,
        'practice_count': practice_count,
        'start_week': start_week,
        'periodicity': periodicity
    }

    # Если дисциплина уже была в расписании, удаляем её
    course_id_str = str(course_id)
    if course_id_str in data['schedule']:
        del data['schedule'][course_id_str]

    save_data(data)
    flash(f'Дисциплина {name} обновлена')
    return redirect(url_for('index'))


@app.route('/delete_course/<int:course_id>', methods=['POST'])
def delete_course(course_id):
    course_index = None
    course_name = ""

    for i, c in enumerate(data['courses']):
        if int(c['id']) == course_id:
            course_index = i
            course_name = c['name']
            break

    if course_index is None:
        flash('Дисциплина не найдена', 'danger')
        return redirect(url_for('index'))

    # Удаляем дисциплину
    data['courses'].pop(course_index)

    # Если дисциплина была в расписании, удаляем её
    course_id_str = str(course_id)
    if course_id_str in data['schedule']:
        del data['schedule'][course_id_str]

    save_data(data)
    flash(f'Дисциплина {course_name} удалена')
    return redirect(url_for('index'))


@app.route('/generate_schedule', methods=['POST'])
def generate_schedule():
    schedule = generate_schedule_csp()
    data['schedule'] = schedule
    save_data(data)
    flash('Расписание успешно сгенерировано')
    return redirect(url_for('view_schedule'))


@app.route('/view_schedule')
def view_schedule():
    return render_template('schedule.html', data=data)


@app.route('/clear_data', methods=['POST'])
def clear_data():
    global data
    data = default_data.copy()
    save_data(data)
    flash('Все данные очищены')
    return redirect(url_for('index'))


# Алгоритм генерации расписания на основе CSP
def generate_schedule_csp():
    # Инициализация пустого расписания
    schedule = {}

    # Получение данных
    weeks = data['semester_weeks']
    courses = data['courses']

    # Создание трекера доступности ресурсов
    # Формат: {week: {day: {period: {'professors': [ids], 'classrooms': [ids], 'groups': [ids]}}}}
    availability = {}
    for week in range(1, weeks + 1):
        availability[week] = {}
        for day in range(5):  # Понедельник - Пятница
            availability[week][day] = {}
            for period in range(8):  # 8 пар в день
                availability[week][day][period] = {
                    'professors': [int(p['id']) for p in data['professors']],
                    'classrooms': [int(c['id']) for c in data['classrooms']],
                    'groups': [int(g['id']) for g in data['groups']]
                }

    # Сортировка курсов по ограничениям (сначала самые ограниченные)
    sorted_courses = sorted(
        courses,
        key=lambda c: (
            c['start_week'],
            -(c['lecture_count'] + c['practice_count']),  # Больше занятий = больше ограничений
            -len(c.get('possible_classrooms', [])),  # Меньше аудиторий = больше ограничений
            -len(c.get('groups', []))  # Меньше групп = больше ограничений
        )
    )

    # Обработка каждого курса
    for course in sorted_courses:
        course_id = int(course['id'])
        professor_id = int(course['professor_id'])
        possible_classroom_ids = [int(c_id) for c_id in course.get('possible_classrooms', [])]
        group_ids = [int(g_id) for g_id in course.get('groups', [])]
        remaining_lectures = course['lecture_count']
        remaining_practices = course['practice_count']
        start_week = course['start_week']
        periodicity = course.get('periodicity', 'weekly')

        # Определить количество занятий на неделю в зависимости от периодичности
        # и равномерно распределить занятия по всему семестру
        available_weeks = max(1, weeks - start_week + 1)

        # Определить периодичность проведения занятий
        if periodicity == 'weekly':
            week_step = 1  # каждую неделю
        elif periodicity == 'biweekly':
            week_step = 2  # через неделю
        else:
            week_step = 1  # по умолчанию каждую неделю

        # Вычислить доступные недели с учетом периодичности
        potential_weeks = list(range(start_week, weeks + 1, week_step))

        # Планирование лекций и практик
        lecture_weeks = distribute_sessions(remaining_lectures, potential_weeks)
        practice_weeks = distribute_sessions(remaining_practices, potential_weeks)

        # Расписание лекций
        for week in lecture_weeks:
            slot = find_best_slot_for_week(
                professor_id, possible_classroom_ids, group_ids, week, availability
            )

            if slot:
                # Обновить доступность
                day = slot['day']
                period = slot['period']
                classroom_id = slot['classroom_id']

                # Удалить ресурсы из доступных
                availability[week][day][period]['professors'].remove(professor_id)
                availability[week][day][period]['classrooms'].remove(classroom_id)

                # Удалить группы из доступных
                for group_id in group_ids:
                    if group_id in availability[week][day][period]['groups']:
                        availability[week][day][period]['groups'].remove(group_id)

                # Добавить в расписание
                course_key = str(course_id)  # Используем строку в качестве ключа
                if course_key not in schedule:
                    schedule[course_key] = []

                schedule[course_key].append({
                    'week': week,
                    'day': day,
                    'period': period,
                    'classroom_id': classroom_id,
                    'groups': group_ids,
                    'type': 'lecture'
                })
            else:
                print(f"Не удалось найти слот для лекции в неделю {week} для курса {course['name']}")

        # Расписание практик
        for week in practice_weeks:
            slot = find_best_slot_for_week(
                professor_id, possible_classroom_ids, group_ids, week, availability
            )

            if slot:
                # Обновить доступность
                day = slot['day']
                period = slot['period']
                classroom_id = slot['classroom_id']

                # Удалить ресурсы из доступных
                availability[week][day][period]['professors'].remove(professor_id)
                availability[week][day][period]['classrooms'].remove(classroom_id)

                # Удалить группы из доступных
                for group_id in group_ids:
                    if group_id in availability[week][day][period]['groups']:
                        availability[week][day][period]['groups'].remove(group_id)

                # Добавить в расписание
                course_key = str(course_id)  # Используем строку в качестве ключа
                if course_key not in schedule:
                    schedule[course_key] = []

                schedule[course_key].append({
                    'week': week,
                    'day': day,
                    'period': period,
                    'classroom_id': classroom_id,
                    'groups': group_ids,
                    'type': 'practice'
                })
            else:
                print(f"Не удалось найти слот для практики в неделю {week} для курса {course['name']}")

    return schedule


# Функция для равномерного распределения занятий по неделям
def distribute_sessions(session_count, available_weeks):
    if session_count == 0 or not available_weeks:
        return []

    result = []

    # Если занятий меньше чем недель, распределим их равномерно
    if session_count <= len(available_weeks):
        # Берем начало и равномерно распределенные недели
        step = len(available_weeks) // session_count
        for i in range(session_count):
            idx = min(i * step, len(available_weeks) - 1)
            result.append(available_weeks[idx])
    else:
        # Если занятий больше чем недель, используем все доступные недели,
        # и повторно используем некоторые недели для оставшихся занятий
        result = available_weeks.copy()
        remaining = session_count - len(available_weeks)

        # Равномерно распределим оставшиеся занятия
        for i in range(remaining):
            idx = (i * len(available_weeks)) // remaining
            result.append(available_weeks[idx])

    return sorted(result)


def find_best_slot_for_week(professor_id, possible_classroom_ids, group_ids, week, availability):
    # Найти и оценить все потенциальные слоты для конкретной недели
    candidate_slots = []

    for day in range(5):  # Понедельник - Пятница
        for period in range(8):  # 8 пар в день
            # Проверить доступность преподавателя
            if professor_id not in availability[week][day][period]['professors']:
                continue

            # Найти доступные аудитории из возможных
            available_classrooms = [
                c_id for c_id in possible_classroom_ids
                if c_id in availability[week][day][period]['classrooms']
            ]

            if not available_classrooms:
                continue

            # Проверить доступность всех групп
            all_groups_available = True
            for group_id in group_ids:
                if group_id not in availability[week][day][period]['groups']:
                    all_groups_available = False
                    break

            if not all_groups_available:
                continue

            # Для простоты выберем первую доступную аудиторию
            classroom_id = available_classrooms[0]

            # Вычислить оценку слота (меньше = лучше)
            score = (
                    abs(period - 3.5) * 10 +  # Предпочтение середине дня
                    day * 5  # Небольшое предпочтение началу недели
            )

            # Добавить к кандидатам
            candidate_slots.append({
                'week': week,
                'day': day,
                'period': period,
                'classroom_id': classroom_id,
                'score': score
            })

    # Сортировка по оценке (меньше = лучше)
    candidate_slots.sort(key=lambda s: s['score'])

    # Вернуть лучший слот или None, если нет подходящих
    return candidate_slots[0] if candidate_slots else None


# Запуск приложения
if __name__ == '__main__':
    app.run(debug=True)