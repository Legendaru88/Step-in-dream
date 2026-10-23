from pydantic import BaseModel, Field


class GoalPlan(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    steps: list[str] = Field(min_length=1, max_length=7)
    raw_response: str
