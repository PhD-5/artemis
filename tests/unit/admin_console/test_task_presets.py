"""Persistent presets and the management/recommendation HTTP contract."""

import asyncio
import importlib
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from apps.admin_console.database.repositories.task_preset_repository import TaskPresetRepository
from apps.admin_console.routers import tasks
from apps.admin_console.database.connection import db_session
from apps.admin_console.schemas.task_preset_schema import TaskPresetInput
from apps.admin_console.services.task_preset_catalog import PRESET_TASK_CATALOG, TaskRecommendationEngine
from artemis_client import ArtemisClient


@pytest.fixture
def repository(tmp_path):
    repo = TaskPresetRepository(tmp_path / "presets.db")
    repo.initialize(PRESET_TASK_CATALOG)
    return repo


def test_seed_is_atomic_and_never_restored_after_deleting_every_preset(repository):
    assert len(repository.list_all()) == len(PRESET_TASK_CATALOG)
    for task in repository.list_all():
        assert repository.delete(task.id)
    restarted = TaskPresetRepository(repository.db_path)
    restarted.initialize(PRESET_TASK_CATALOG)
    assert restarted.list_all() == []
    assert TaskRecommendationEngine(restarted).recommend_tasks([]) == []


def test_recommendation_reads_updates_and_respects_all_any_matching(repository):
    engine = TaskRecommendationEngine(repository)
    all_required = next(task for task in repository.list_all() if task.id == "pro_commute_share")
    any_required = next(task for task in repository.list_all() if task.id == "clock_timer")
    packages = {all_required.required_packages[0], any_required.required_packages[-1]}
    matches = {task["id"]: task["is_device_matched"] for task in engine.recommend_tasks(packages, limit=100)}
    assert matches[all_required.id] is False
    assert matches[any_required.id] is True
    packages.add(all_required.required_packages[1])
    matches = {task["id"]: task["is_device_matched"] for task in engine.recommend_tasks(packages, limit=100)}
    assert matches[all_required.id] is True
    updated = repository.update(all_required.id, TaskPresetInput(**{**all_required.model_dump(exclude={"id"}), "title": "Updated"}))
    assert updated and next(task for task in engine.get_all_tasks() if task["id"] == all_required.id)["title"] == "Updated"


@pytest.mark.asyncio
async def test_preset_crud_catalog_and_validation(repository, monkeypatch):
    monkeypatch.setattr(tasks, "task_preset_repo", repository)
    monkeypatch.setattr(tasks, "task_recommendation_engine", TaskRecommendationEngine(repository))
    app = FastAPI()
    app.include_router(tasks.router)
    payload = PRESET_TASK_CATALOG[0].model_dump(exclude={"id"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        created = await client.post("/api/tasks/presets", json=payload)
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert task_id not in {task.id for task in PRESET_TASK_CATALOG}
        assert (await client.get(f"/api/tasks/presets/{task_id}")).json()["title"] == payload["title"]
        assert task_id in {item["id"] for item in (await client.get("/api/tasks/catalog")).json()["tasks"]}
        edited = await client.put(f"/api/tasks/presets/{task_id}", json={**payload, "title": "Edited"})
        assert edited.status_code == 200
        assert "Edited" in {item["title"] for item in (await client.get("/api/tasks/presets")).json()}
        assert (await client.post("/api/tasks/presets", json={**payload, "profile": "invalid"})).status_code == 422
        assert (await client.put(f"/api/tasks/presets/{task_id}", json={**payload, "match_mode": "invalid"})).status_code == 422
        assert (await client.delete(f"/api/tasks/presets/{task_id}")).status_code == 204
        assert (await client.get(f"/api/tasks/presets/{task_id}")).status_code == 404
        assert (await client.put(f"/api/tasks/presets/{task_id}", json=payload)).status_code == 404
        assert (await client.delete(f"/api/tasks/presets/{task_id}")).status_code == 404


def test_archived_preset_persists_through_reload_and_content_edit(repository):
    seed = repository.list_all()[0]
    with db_session(repository.db_path) as conn, conn:
        conn.execute(
            "UPDATE task_presets SET payload = ? WHERE id = ?",
            (seed.model_dump_json(exclude={"archived"}), seed.id),
        )
    assert repository.get(seed.id).archived is False

    archived = repository.set_archived(seed.id, True)
    assert archived is not None
    assert archived.archived is True
    assert archived.goal == seed.goal
    restarted = TaskPresetRepository(repository.db_path)
    restarted.initialize(PRESET_TASK_CATALOG)
    assert restarted.get(seed.id) == archived
    edited = restarted.update(
        seed.id, TaskPresetInput(**{**seed.model_dump(exclude={"id", "archived"}), "title": "Edited while archived"})
    )
    assert edited is not None
    assert edited.archived is True
    assert edited.title == "Edited while archived"
    assert edited.goal == seed.goal
    assert repository.get(seed.id) == edited
    unarchived = repository.set_archived(seed.id, False)
    assert unarchived is not None
    assert unarchived.archived is False
    assert unarchived.title == edited.title
    assert unarchived.goal == edited.goal
    assert restarted.get(seed.id) == unarchived
    assert repository.set_archived("missing", True) is None


@pytest.fixture
def run_app(repository, monkeypatch, tmp_path):
    queue_state = importlib.import_module(tasks.task_queue_service.__module__).state
    monkeypatch.setattr(tasks, "state", queue_state)
    monkeypatch.setattr(queue_state, "queue_items", [])
    monkeypatch.setattr(queue_state, "active_runs", {})
    monkeypatch.setattr(queue_state, "active_connections", {})
    monkeypatch.setattr(queue_state, "active_session_id", None)
    monkeypatch.setattr(queue_state, "current_process", None)
    monkeypatch.setattr(queue_state, "startup_progress", {})
    monkeypatch.setattr(queue_state, "_wake_event", asyncio.Event())
    monkeypatch.setattr(tasks, "task_preset_repo", repository)
    monkeypatch.setattr(tasks.session_repo, "get_session_by_id", lambda _sid: None)
    monkeypatch.setattr(tasks.task_queue_service, "ensure_worker_running", lambda: None)
    monkeypatch.setattr("artemis.runtime.device_lock.get_temp_dir", lambda _folder=None: tmp_path)
    monkeypatch.setattr(tasks.device_pool, "validate_explicit_serial_async", AsyncMock(return_value=None))
    monkeypatch.setattr(tasks.readiness_engine, "run_device_submission_probe", AsyncMock(return_value=None))
    app = FastAPI()
    app.include_router(tasks.router)
    return app


def template_payload(**changes):
    return {
        **PRESET_TASK_CATALOG[0].model_dump(exclude={"id"}),
        "goal": "打开 ${APP_NAME}；${APP_NAME} 搜索 ${QUERY}；$${APP_NAME}；$5",
        "parameters": ["APP_NAME", "QUERY"],
        "profile": "pro",
        "expected_output": "Return the result",
        **changes,
    }


@pytest.mark.asyncio
async def test_template_run_uses_literal_arguments_and_admission_snapshot(run_app, repository):
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        created = await client.post("/api/tasks/presets", json=template_payload())
        assert created.status_code == 201
        template_id = created.json()["id"]
        assert (await client.get(f"/api/tasks/presets/{template_id}")).json()["parameters"] == ["APP_NAME", "QUERY"]
        sid = str(uuid4())
        request = {
            "template_id": template_id,
            "args": {"APP_NAME": "地图", "QUERY": '${APP_NAME}\n"咖啡"\\'},
            "device_serial": "target",
            "session_id": sid,
        }
        response = await client.post("/api/run", json=request)
        assert response.status_code == 200
        admitted = response.json()["tasks"][0]
        assert admitted["goal"] == '打开 地图；地图 搜索 ${APP_NAME}\n"咖啡"\\；${APP_NAME}；$5'
        assert admitted["profile"] == "pro"
        assert admitted["expected_output"] == "Return the result"
        assert tasks.state.queue_items[0]["goal"] == admitted["goal"]

        # Neither later edits nor deletion may rewrite an admitted task. A retry
        # uses its original session key before template lookup or device probing.
        edited = await client.put(
            f"/api/tasks/presets/{template_id}",
            json=template_payload(goal="Different ${APP_NAME}", parameters=["APP_NAME"]),
        )
        assert edited.status_code == 200
        assert repository.delete(template_id)
        tasks.readiness_engine.run_device_submission_probe.reset_mock()
        retried = await client.post("/api/run", json=request)
        assert retried.status_code == 200
        assert retried.json()["enqueued_count"] == 0
        assert retried.json()["tasks"][0] == admitted
        assert tasks.state.queue_items == [admitted]
        tasks.readiness_engine.run_device_submission_probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_archive_endpoint_filters_recommendations_and_blocks_new_runs(run_app, repository, monkeypatch):
    monkeypatch.setattr(tasks, "task_recommendation_engine", TaskRecommendationEngine(repository))
    template = repository.create(TaskPresetInput(**PRESET_TASK_CATALOG[0].model_dump(exclude={"id", "archived"})))
    url = f"/api/tasks/presets/{template.id}"
    request = {"template_id": template.id, "device_serial": "target", "session_id": str(uuid4())}
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        original = await client.post("/api/run", json=request)
        assert original.status_code == 200
        archived = await client.patch(f"{url}/archive", json={"archived": True})
        assert archived.status_code == 200
        assert archived.json()["archived"] is True
        assert archived.json()["goal"] == template.goal
        assert (await client.get(url)).json()["archived"] is True
        catalog = (await client.get("/api/tasks/catalog")).json()["tasks"]
        assert next(item for item in catalog if item["id"] == template.id)["archived"] is True
        recommended = (await client.get("/api/tasks/presets", params={"limit": 1000})).json()
        assert template.id not in {item["id"] for item in recommended}

        updated = await client.put(url, json={**template.model_dump(exclude={"id"}), "title": "Archived edit"})
        assert updated.status_code == 200
        assert updated.json()["archived"] is True
        assert updated.json()["title"] == "Archived edit"
        assert repository.get(template.id).archived is True

        tasks.readiness_engine.run_device_submission_probe.reset_mock()
        rejected = await client.post("/api/run", json={**request, "session_id": str(uuid4())})
        assert rejected.status_code == 409
        assert "archived" in rejected.text
        tasks.readiness_engine.run_device_submission_probe.assert_not_awaited()
        assert tasks.state.queue_items == original.json()["tasks"]

        retried = await client.post("/api/run", json=request)
        assert retried.status_code == 200
        assert retried.json()["enqueued_count"] == 0
        assert retried.json()["tasks"] == original.json()["tasks"]
        tasks.readiness_engine.run_device_submission_probe.assert_not_awaited()

        assert (await client.patch("/api/tasks/presets/missing/archive", json={"archived": True})).status_code == 404
        unarchived = await client.patch(f"{url}/archive", json={"archived": False})
        assert unarchived.status_code == 200
        assert unarchived.json()["archived"] is False
        assert unarchived.json()["title"] == "Archived edit"
        recommended = (await client.get("/api/tasks/presets", params={"limit": 1000})).json()
        assert template.id in {item["id"] for item in recommended}
        resumed = await client.post("/api/run", json={**request, "session_id": str(uuid4())})
        assert resumed.status_code == 200
        assert resumed.json()["tasks"][0]["goal"] == template.goal


@pytest.mark.asyncio
async def test_template_overrides_and_explicit_empty_string_arguments(run_app, repository):
    template = repository.create(TaskPresetInput(**template_payload()))
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        response = await client.post("/api/run", json={
            "template_id": template.id,
            "args": {"APP_NAME": "", "QUERY": "tea"},
            "profile": "flash",
            "expected_output": None,
            "device_serial": "target",
        })
        assert response.status_code == 200
        task = response.json()["tasks"][0]
        assert task["goal"] == "打开 ； 搜索 tea；${APP_NAME}；$5"
        assert task["profile"] == "flash"
        assert task["expected_output"] is None


@pytest.mark.parametrize(("extra", "error"), [
    ({"args": {"APP_NAME": "地图"}}, "QUERY"),
    ({"args": {"APP_NAME": "地图", "QUERY": "tea", "EXTRA": "x"}}, "EXTRA"),
    ({"args": {"APP_NAME": 123, "QUERY": "tea"}}, "APP_NAME"),
    ({"args": {"APP_NAME": None, "QUERY": "tea"}}, "APP_NAME"),
    ({"goal": "raw", "args": {"APP_NAME": "地图", "QUERY": "tea"}}, "cannot be combined"),
    ({"goals": [], "args": {"APP_NAME": "地图", "QUERY": "tea"}}, "cannot be combined"),
])
@pytest.mark.asyncio
async def test_invalid_template_submission_has_no_admission_side_effects(run_app, repository, extra, error):
    template = repository.create(TaskPresetInput(**template_payload()))
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        response = await client.post("/api/run", json={
            "template_id": template.id, "device_serial": "target", **extra,
        })
        assert response.status_code == 422
        assert error in response.text
        assert tasks.state.queue_items == []
        tasks.readiness_engine.run_device_submission_probe.assert_not_awaited()
        tasks.device_pool.validate_explicit_serial_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_template_and_args_without_template_are_rejected(run_app):
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        assert (await client.post("/api/run", json={"template_id": "missing", "args": {}})).status_code == 404
        orphan = await client.post("/api/run", json={"goal": "raw", "args": {}})
        assert orphan.status_code == 422
        assert "args requires template_id" in orphan.text
        assert tasks.state.queue_items == []
        tasks.readiness_engine.run_device_submission_probe.assert_not_awaited()


@pytest.mark.parametrize(("goal", "parameters", "error"), [
    ("${APP_NAME}", ["APP_NAME", "APP_NAME"], "Duplicate parameter"),
    ("${APP_NAME}", ["bad-name"], "Invalid parameter name"),
    ("${UNKNOWN}", ["APP_NAME"], "Undeclared parameter"),
    ("${bad name}", [], "Invalid placeholder name"),
    ("${APP_NAME", ["APP_NAME"], "Unterminated placeholder"),
])
@pytest.mark.asyncio
async def test_template_crud_rejects_invalid_declarations(run_app, goal, parameters, error):
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        response = await client.post(
            "/api/tasks/presets", json=template_payload(goal=goal, parameters=parameters),
        )
        assert response.status_code == 422
        assert error in response.text


@pytest.mark.asyncio
async def test_parameterless_existing_preset_and_raw_goal_modes_remain_executable(run_app, repository):
    seed = PRESET_TASK_CATALOG[0]
    # Emulate a persisted record from before parameters existed.
    with db_session(repository.db_path) as conn, conn:
        conn.execute(
            "UPDATE task_presets SET payload = ? WHERE id = ?",
            (json.dumps(seed.model_dump(exclude={"parameters"})), seed.id),
        )
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        response = await client.post("/api/run", json={"template_id": seed.id, "device_serial": "target"})
        assert response.status_code == 200
        assert response.json()["tasks"][0]["goal"] == seed.goal
        raw = await client.post("/api/run", json={"goal": "Literal ${APP_NAME}", "device_serial": "target"})
        assert raw.status_code == 200
        assert raw.json()["tasks"][0]["goal"] == "Literal ${APP_NAME}"
        batch = await client.post("/api/run", json={"goals": ["First", "Second"], "device_serial": "target"})
        assert batch.status_code == 200
        assert [task["goal"] for task in batch.json()["tasks"]] == ["First", "Second"]


@pytest.mark.asyncio
async def test_escaped_literals_and_unused_declared_arguments(run_app, repository):
    template = repository.create(TaskPresetInput(**template_payload(
        goal="$${literal content} ${APP_NAME}", parameters=["APP_NAME", "UNUSED"],
    )))
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
        missing = await client.post("/api/run", json={
            "template_id": template.id, "args": {"APP_NAME": "Settings"},
        })
        assert missing.status_code == 422
        assert "UNUSED" in missing.text
        accepted = await client.post("/api/run", json={
            "template_id": template.id,
            "args": {"APP_NAME": "Settings", "UNUSED": ""},
            "device_serial": "target",
        })
        assert accepted.status_code == 200
        assert accepted.json()["tasks"][0]["goal"] == "${literal content} Settings"


@pytest.mark.asyncio
async def test_python_template_submission_applies_server_config_precedence(run_app, repository):
    template = repository.create(TaskPresetInput(**template_payload()))
    with TestClient(run_app) as http:
        class ApiTransport:
            def request(self, method, path, *, json_body=None):
                response = http.request(method, path, json=json_body)
                response.raise_for_status()
                return response.json()

        client = ArtemisClient(transport=ApiTransport(), default_profile="flash", device_serial="target")
        for app_name, overrides, profile, expected in [
            ("Inherited", {}, "pro", "Return the result"),
            ("Cleared null", {"expected_output": None}, "pro", None),
            ("Overridden", {"profile": "flash", "expected_output": ""}, "flash", ""),
        ]:
            handle = await client.submit(
                template_id=template.id,
                args={"APP_NAME": app_name, "QUERY": "coffee"},
                **overrides,
            )
            admitted = next(item for item in tasks.state.queue_items if item["session_id"] == handle.task_id)
            assert admitted["goal"] == f"打开 {app_name}；{app_name} 搜索 coffee；${{APP_NAME}}；$5"
            assert admitted["profile"] == profile
            assert admitted["expected_output"] == expected


@pytest.mark.asyncio
async def test_legacy_placeholder_presets_migrate_before_catalog_loading(run_app, repository):
    legacy = template_payload(
        id="legacy-template",
        title="Legacy parameterized task",
        goal="Open ${APP_NAME}; find ${QUERY} in ${APP_NAME}; keep $${LITERAL}",
        profile="flash",
    )
    legacy.pop("parameters")
    manual = repository.create(TaskPresetInput(**template_payload(
        title="Explicit declaration", goal="Manual task", parameters=["UNUSED"],
    )))
    with db_session(repository.db_path) as conn, conn:
        conn.execute(
            "INSERT INTO task_presets (id, payload) VALUES (?, ?)",
            (legacy["id"], json.dumps(legacy)),
        )

    # Startup upgrades older rows rather than relaxing validation or dropping
    # one bad row from a catalog response.
    repository.initialize(PRESET_TASK_CATALOG)
    assert repository.get(manual.id) == manual
    expected = {**legacy, "parameters": ["APP_NAME", "QUERY"], "archived": False}
    assert repository.get(legacy["id"]).model_dump() == expected
    repository.initialize(PRESET_TASK_CATALOG)
    assert repository.get(legacy["id"]).model_dump() == expected

    monkey_engine = TaskRecommendationEngine(repository)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tasks, "task_recommendation_engine", monkey_engine)
        async with AsyncClient(transport=ASGITransport(app=run_app), base_url="http://localhost") as client:
            catalog = await client.get("/api/tasks/catalog")
            assert catalog.status_code == 200
            assert next(task for task in catalog.json()["tasks"] if task["id"] == legacy["id"]) == expected
            recommendations = await client.get("/api/tasks/presets", params={"limit": 100})
            assert recommendations.status_code == 200
            assert next(task for task in recommendations.json() if task["id"] == legacy["id"])["parameters"] == ["APP_NAME", "QUERY"]
            response = await client.post("/api/run", json={
                "template_id": legacy["id"],
                "args": {"APP_NAME": "Settings", "QUERY": "Battery"},
                "device_serial": "target",
            })
            assert response.status_code == 200
            assert response.json()["tasks"][0]["goal"] == "Open Settings; find Battery in Settings; keep ${LITERAL}"
