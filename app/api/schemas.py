from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.goal import GoalStatus
from app.models.step import StepStatus


class UpsertUserRequest(BaseModel):
    external_user_id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=255)


class UserResponse(BaseModel):
    id: int
    external_user_id: int
    username: str | None
    created_at: datetime


class StepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    order: int
    status: StepStatus
    completed_at: datetime | None


class GoalResponse(BaseModel):
    id: int
    title: str
    status: GoalStatus
    progress: int
    created_at: datetime
    completed_at: datetime | None
    steps: list[StepResponse]


class CreateGoalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    steps: list[str] = Field(min_length=1, max_length=7)


class UpdateStepStatusRequest(BaseModel):
    done: bool


class UserStatsResponse(BaseModel):
    total_goals: int
    completed_goals: int
    total_steps: int
    done_steps: int


class ProposeGoalPlanRequest(BaseModel):
    goal_text: str = Field(min_length=1, max_length=4000)
    revision_message: str | None = Field(default=None, max_length=2000)


class ProposeGoalPlanResponse(BaseModel):
    title: str
    steps: list[str]
    raw_response: str


class ClassifyIntentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ClassifyIntentResponse(BaseModel):
    intent: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    reply: str

