from aiogram.fsm.state import State, StatesGroup


class GoalDialog(StatesGroup):
    waiting_goal_input = State()
    waiting_goal_revision = State()
    waiting_goal_confirmation = State()
