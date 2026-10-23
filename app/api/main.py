from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    ClassifyIntentRequest,
    ClassifyIntentResponse,
    CreateGoalRequest,
    GoalResponse,
    ProposeGoalPlanRequest,
    ProposeGoalPlanResponse,
    StepResponse,
    UpdateStepStatusRequest,
    UpsertUserRequest,
    UserResponse,
    UserStatsResponse,
)
from app.database import get_session
from app.models.dialog import DialogLog, DialogRole
from app.models.goal import Goal
from app.models.step import Step, StepStatus
from app.models.user import User
from app.services.goal_parser import GoalParserError, parse_goal_plan
from app.services.llm import OpenRouterClient, OpenRouterError
from app.services.progress import refresh_goal_status
from app.utils.db import (
    add_dialog_log,
    get_goal_for_user,
    get_or_create_user,
    get_recent_dialog_logs,
    get_user_goals,
    user_stats,
)

app = FastAPI(
    title="TGGooals API",
    version="1.0.0",
    description="Interface-agnostic API for users, goals, steps, and AI goal planning.",
)

llm_client = OpenRouterClient()


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        external_user_id=user.telegram_id,
        username=user.username,
        created_at=user.created_at,
    )


def _goal_response(goal: Goal) -> GoalResponse:
    steps = [
        StepResponse(
            id=step.id,
            title=step.title,
            order=step.order,
            status=step.status,
            completed_at=step.completed_at,
        )
        for step in goal.steps
    ]
    return GoalResponse(
        id=goal.id,
        title=goal.title,
        status=goal.status,
        progress=goal.progress,
        created_at=goal.created_at,
        completed_at=goal.completed_at,
        steps=steps,
    )


def _normalize_steps(steps: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for step in steps:
        cleaned = " ".join(step.strip().split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


def _goals_context(goals: list[Goal]) -> str:
    if not goals:
        return "У пользователя пока нет активных целей."

    lines: list[str] = []
    for goal in goals:
        lines.append(f"- Цель: {goal.title} | статус: {goal.status.value} | прогресс: {goal.progress}%")
        for index, step in enumerate(goal.steps, start=1):
            marker = "done" if step.status == StepStatus.DONE else "pending"
            lines.append(f"  {index}. [{marker}] {step.title}")
    return "\n".join(lines)


def _dialog_history(logs: list[DialogLog]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for log in logs:
        content = log.content.strip()
        if not content:
            continue
        role = "assistant" if log.role == DialogRole.ASSISTANT else "user"
        history.append({"role": role, "content": content[:700]})
    return history[-6:]


async def _get_user_or_404(session: AsyncSession, external_user_id: int) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == external_user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _get_goal_or_404(session: AsyncSession, user_id: int, goal_id: int) -> Goal:
    goal = await get_goal_for_user(session, user_id=user_id, goal_id=goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/users/upsert", response_model=UserResponse)
async def upsert_user(request: UpsertUserRequest, session: AsyncSession = Depends(get_session)) -> UserResponse:
    user = await get_or_create_user(
        session=session,
        telegram_id=request.external_user_id,
        username=request.username,
    )
    await session.commit()
    return _user_response(user)


@app.get("/api/v1/users/{external_user_id}/goals", response_model=list[GoalResponse])
async def list_goals(external_user_id: int, session: AsyncSession = Depends(get_session)) -> list[GoalResponse]:
    user = await _get_user_or_404(session, external_user_id)
    goals = await get_user_goals(session, user_id=user.id)
    return [_goal_response(goal) for goal in goals]


@app.post("/api/v1/users/{external_user_id}/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    external_user_id: int,
    request: CreateGoalRequest,
    session: AsyncSession = Depends(get_session),
) -> GoalResponse:
    user = await _get_user_or_404(session, external_user_id)
    normalized_steps = _normalize_steps(request.steps)
    if not normalized_steps:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one step is required")

    goal = Goal(user_id=user.id, title=" ".join(request.title.strip().split()))
    session.add(goal)
    await session.flush()

    for idx, step_title in enumerate(normalized_steps, start=1):
        session.add(
            Step(
                goal_id=goal.id,
                title=step_title,
                order=idx,
                status=StepStatus.PENDING,
            )
        )

    await session.flush()
    goal = await _get_goal_or_404(session, user.id, goal.id)
    refresh_goal_status(goal, goal.steps)
    await session.commit()
    return _goal_response(goal)


@app.get("/api/v1/users/{external_user_id}/goals/{goal_id}", response_model=GoalResponse)
async def goal_details(
    external_user_id: int,
    goal_id: int,
    session: AsyncSession = Depends(get_session),
) -> GoalResponse:
    user = await _get_user_or_404(session, external_user_id)
    goal = await _get_goal_or_404(session, user.id, goal_id)
    return _goal_response(goal)


@app.delete("/api/v1/users/{external_user_id}/goals/{goal_id}")
async def delete_goal(external_user_id: int, goal_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    user = await _get_user_or_404(session, external_user_id)
    goal = await _get_goal_or_404(session, user.id, goal_id)
    await session.delete(goal)
    await session.commit()
    return {"status": "deleted"}


@app.patch("/api/v1/users/{external_user_id}/goals/{goal_id}/steps/{step_id}", response_model=GoalResponse)
async def update_step_status(
    external_user_id: int,
    goal_id: int,
    step_id: int,
    request: UpdateStepStatusRequest,
    session: AsyncSession = Depends(get_session),
) -> GoalResponse:
    user = await _get_user_or_404(session, external_user_id)
    step = await session.scalar(
        select(Step)
        .join(Goal, Goal.id == Step.goal_id)
        .where(Goal.user_id == user.id, Goal.id == goal_id, Step.id == step_id)
    )
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")

    if request.done:
        step.status = StepStatus.DONE
        step.completed_at = step.completed_at or datetime.now(timezone.utc)
    else:
        step.status = StepStatus.PENDING
        step.completed_at = None

    await session.flush()
    goal = await _get_goal_or_404(session, user.id, goal_id)
    refresh_goal_status(goal, goal.steps)
    await session.commit()
    return _goal_response(goal)


@app.get("/api/v1/users/{external_user_id}/stats", response_model=UserStatsResponse)
async def get_stats(external_user_id: int, session: AsyncSession = Depends(get_session)) -> UserStatsResponse:
    user = await _get_user_or_404(session, external_user_id)
    stats = await user_stats(session, user.id)
    return UserStatsResponse(**stats)


@app.post("/api/v1/assistant/propose-plan", response_model=ProposeGoalPlanResponse)
async def propose_plan(
    request: ProposeGoalPlanRequest,
) -> ProposeGoalPlanResponse:
    try:
        llm_response = await llm_client.propose_goal_plan(
            request.goal_text,
            revision_message=request.revision_message,
        )
        plan = parse_goal_plan(llm_response)
    except OpenRouterError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except GoalParserError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return ProposeGoalPlanResponse(title=plan.title, steps=plan.steps, raw_response=plan.raw_response)


@app.post("/api/v1/assistant/classify-intent", response_model=ClassifyIntentResponse)
async def classify_intent(request: ClassifyIntentRequest) -> ClassifyIntentResponse:
    try:
        intent = await llm_client.classify_intent(request.message)
    except OpenRouterError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ClassifyIntentResponse(intent=intent)


@app.post("/api/v1/users/{external_user_id}/assistant/chat", response_model=ChatResponse)
async def chat_with_context(
    external_user_id: int,
    request: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    user = await _get_user_or_404(session, external_user_id)
    goals = await get_user_goals(session, user_id=user.id)
    logs = await get_recent_dialog_logs(session, user.id, limit=8)
    history = _dialog_history(logs)

    try:
        reply = await llm_client.chat_in_goals_context(
            user_message=request.message,
            goals_context=_goals_context(goals),
            history=history,
        )
    except OpenRouterError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    await add_dialog_log(session, user_id=user.id, role=DialogRole.USER, content=request.message)
    await add_dialog_log(session, user_id=user.id, role=DialogRole.ASSISTANT, content=reply)
    await session.commit()
    return ChatResponse(reply=reply)
