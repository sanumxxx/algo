import random
import copy
import math
import time
from collections import defaultdict
from models import db, Course, Group, Teacher, Room, ScheduleItem, LabSubgroup


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
            course_groups = course.groups
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
                                course_teacher = next((ct for ct in course.course_teachers
                                                      if ct.lesson_type == 'lab' and ct.lab_subgroup_id == subgroup.id), None)

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