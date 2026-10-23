import pytest

from app.services.goal_parser import GoalParserError, parse_goal_plan


def test_parse_goal_plan_success() -> None:
    text = """
ЦЕЛЬ: Выучить английский до B2 за 6 месяцев
ЭТАПЫ:
1. Пройти тест на уровень
2. Выбрать курс и расписание
3. Учить 30 слов ежедневно
4. Смотреть 1 видео на английском в день
5. Практиковать разговорную речь 2 раза в неделю
"""

    plan = parse_goal_plan(text)

    assert plan.title == "Выучить английский до B2 за 6 месяцев"
    assert len(plan.steps) == 5
    assert plan.steps[0] == "Пройти тест на уровень"


def test_parse_goal_plan_limits_to_seven_steps() -> None:
    text = """
ЦЕЛЬ: Подготовиться к марафону
ЭТАПЫ:
1. Шаг 1
2. Шаг 2
3. Шаг 3
4. Шаг 4
5. Шаг 5
6. Шаг 6
7. Шаг 7
8. Шаг 8
"""

    plan = parse_goal_plan(text)

    assert len(plan.steps) == 7
    assert plan.steps[-1] == "Шаг 7"


def test_parse_goal_plan_requires_three_steps() -> None:
    text = """
ЦЕЛЬ: Научиться медитировать
ЭТАПЫ:
1. Выбрать приложение
2. Медитировать 5 минут
"""

    with pytest.raises(GoalParserError):
        parse_goal_plan(text)
