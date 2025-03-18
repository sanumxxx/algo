from app import app, db, Course, CourseTeacher, ScheduleItem, Teacher
from sqlalchemy import text


def migrate_database():
    """
    Скрипт для обновления структуры базы данных и миграции данных
    для поддержки разных преподавателей для разных типов занятий.
    """
    with app.app_context():
        print("Начало миграции базы данных...")

        # 1. Проверяем, существует ли таблица course_teacher
        try:
            db.session.execute(text("SELECT * FROM course_teacher LIMIT 1"))
            print("Таблица course_teacher уже существует")
        except:
            print("Создание таблицы course_teacher...")
            # Создаем новую таблицу для связи курсов с преподавателями
            db.create_all()

        # 2. Проверяем наличие поля teacher_id в таблице schedule_item
        try:
            db.session.execute(text("SELECT teacher_id FROM schedule_item LIMIT 1"))
            print("Поле teacher_id в таблице schedule_item уже существует")
        except:
            print("Добавление поля teacher_id в таблицу schedule_item...")
            # Добавляем поле teacher_id в таблицу расписания
            db.session.execute(text("ALTER TABLE schedule_item ADD COLUMN teacher_id INTEGER REFERENCES teacher(id)"))

        # 3. Переносим данные из существующих курсов в новую структуру
        print("Перенос данных о преподавателях из курсов в таблицу course_teacher...")

        # Проверяем, есть ли поле teacher_id в таблице course
        try:
            # Получаем все курсы и создаем соответствующие записи CourseTeacher
            courses = db.session.execute(
                text("SELECT id, teacher_id, lecture_count, practice_count, lab_count FROM course")).fetchall()

            for course in courses:
                course_id = course[0]
                teacher_id = course[1]
                lecture_count = course[2] or 0
                practice_count = course[3] or 0
                lab_count = course[4] or 0

                # Создаем новые записи в CourseTeacher для каждого типа занятий
                if teacher_id and teacher_id > 0:
                    if lecture_count > 0:
                        db.session.add(CourseTeacher(
                            course_id=course_id,
                            teacher_id=teacher_id,
                            lesson_type='lecture'
                        ))

                    if practice_count > 0:
                        db.session.add(CourseTeacher(
                            course_id=course_id,
                            teacher_id=teacher_id,
                            lesson_type='practice'
                        ))

                    if lab_count > 0:
                        db.session.add(CourseTeacher(
                            course_id=course_id,
                            teacher_id=teacher_id,
                            lesson_type='lab'
                        ))

            db.session.commit()

            # 4. Обновляем записи расписания
            print("Обновление записей расписания...")
            schedule_items = ScheduleItem.query.all()
            for item in schedule_items:
                if not item.teacher_id:
                    course = Course.query.get(item.course_id)
                    if course:
                        course_teacher = CourseTeacher.query.filter_by(
                            course_id=course.id,
                            lesson_type=item.lesson_type
                        ).first()

                        if course_teacher:
                            item.teacher_id = course_teacher.teacher_id

            db.session.commit()

            # 5. Удаляем ненужное поле teacher_id из таблицы course
            print("Удаление поля teacher_id из таблицы course...")
            try:
                db.session.execute(text("ALTER TABLE course DROP COLUMN teacher_id"))
            except:
                print(
                    "Не удалось удалить поле teacher_id из таблицы course. Возможно, оно уже удалено или требуется ручное вмешательство.")

            print("Миграция завершена успешно!")

        except Exception as e:
            print(f"Ошибка при миграции: {e}")
            db.session.rollback()


if __name__ == "__main__":
    migrate_database()