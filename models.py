from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from collections import defaultdict

# Create the SQLAlchemy instance
db = SQLAlchemy()

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