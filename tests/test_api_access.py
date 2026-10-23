"""Preserve the agreed ID-based API boundary using real HTTP routes and SQLite."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.main import app
from app.database import Base, get_session


@pytest.mark.asyncio
async def test_api_trusts_supplied_id_but_checks_goal_ownership(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def session_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for uid in [111, 222]:
                response = await client.post("/api/v1/users/upsert", json={"external_user_id": uid})
                assert response.status_code == 200
            response = await client.post("/api/v1/users/111/goals", json={"title": "Goal", "steps": ["Step"]})
            assert response.status_code == 201
            gid = response.json()["id"]
            assert (await client.get(f"/api/v1/users/222/goals/{gid}")).status_code == 404
            assert (await client.delete(f"/api/v1/users/222/goals/{gid}")).status_code == 404
            # No credentials: selecting the owner's ID is sufficient by contract.
            assert (await client.get(f"/api/v1/users/111/goals/{gid}")).status_code == 200
            assert (await client.delete(f"/api/v1/users/111/goals/{gid}")).json() == {"status": "deleted"}
            assert (await client.get("/api/v1/users/111/goals")).json() == []
            assert (await client.delete(f"/api/v1/users/111/goals/{gid}")).status_code == 404
    finally:
        app.dependency_overrides.pop(get_session, None)
        await engine.dispose()
