"""Persistent recommended-task catalog with one-time, atomic seed initialization."""

import json
from pathlib import Path
from uuid import uuid4

try:
    from admin_console.database.connection import db_session
    from admin_console.schemas.task_preset_schema import TaskPreset, TaskPresetInput
    from admin_console.services.task_template import infer_task_template_parameters
except ImportError:
    from apps.admin_console.database.connection import db_session
    from apps.admin_console.schemas.task_preset_schema import TaskPreset, TaskPresetInput
    from apps.admin_console.services.task_template import infer_task_template_parameters


class TaskPresetRepository:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path

    def initialize(self, seeds: list[TaskPreset]) -> None:
        with db_session(self.db_path) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("CREATE TABLE IF NOT EXISTS task_presets (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                conn.execute("CREATE TABLE IF NOT EXISTS task_preset_seed (id INTEGER PRIMARY KEY CHECK (id = 1))")
                if conn.execute("SELECT 1 FROM task_preset_seed WHERE id = 1").fetchone() is None:
                    conn.executemany(
                        "INSERT INTO task_presets (id, payload) VALUES (?, ?)",
                        [(task.id, task.model_dump_json()) for task in seeds],
                    )
                    conn.execute("INSERT INTO task_preset_seed (id) VALUES (1)")
                # Older presets already used placeholders before declarations
                # existed. Upgrade those rows atomically; explicit declarations
                # on current templates must never be inferred or overwritten.
                legacy_rows = conn.execute(
                    "SELECT id, payload FROM task_presets WHERE json_type(payload, '$.parameters') IS NULL"
                ).fetchall()
                for row in legacy_rows:
                    payload = json.loads(row["payload"])
                    payload["parameters"] = infer_task_template_parameters(payload["goal"])
                    TaskPreset.model_validate(payload)
                    conn.execute(
                        "UPDATE task_presets SET payload = ? WHERE id = ?",
                        (json.dumps(payload, ensure_ascii=False), row["id"]),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_all(self) -> list[TaskPreset]:
        with db_session(self.db_path) as conn:
            rows = conn.execute("SELECT payload FROM task_presets ORDER BY rowid").fetchall()
        return [TaskPreset.model_validate_json(row["payload"]) for row in rows]

    def get(self, preset_id: str) -> TaskPreset | None:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT payload FROM task_presets WHERE id = ?", (preset_id,)).fetchone()
        return TaskPreset.model_validate_json(row["payload"]) if row else None

    def create(self, data: TaskPresetInput) -> TaskPreset:
        task = TaskPreset(id=str(uuid4()), **data.model_dump())
        with db_session(self.db_path) as conn:
            with conn:
                conn.execute("INSERT INTO task_presets (id, payload) VALUES (?, ?)", (task.id, task.model_dump_json()))
        return task

    def update(self, preset_id: str, data: TaskPresetInput) -> TaskPreset | None:
        task = TaskPreset(id=preset_id, **data.model_dump())
        with db_session(self.db_path) as conn:
            with conn:
                updated = conn.execute(
                    "UPDATE task_presets SET payload = json_set(?, '$.archived', "
                    "json(CASE WHEN json_extract(payload, '$.archived') THEN 'true' ELSE 'false' END)) "
                    "WHERE id = ?",
                    (task.model_dump_json(), preset_id),
                ).rowcount
                row = (
                    conn.execute("SELECT payload FROM task_presets WHERE id = ?", (preset_id,)).fetchone()
                    if updated else None
                )
        return TaskPreset.model_validate_json(row["payload"]) if row else None

    def set_archived(self, preset_id: str, archived: bool) -> TaskPreset | None:
        with db_session(self.db_path) as conn:
            with conn:
                updated = conn.execute(
                    "UPDATE task_presets SET payload = json_set(payload, '$.archived', json(?)) WHERE id = ?",
                    (json.dumps(archived), preset_id),
                ).rowcount
                row = (
                    conn.execute("SELECT payload FROM task_presets WHERE id = ?", (preset_id,)).fetchone()
                    if updated else None
                )
        return TaskPreset.model_validate_json(row["payload"]) if row else None

    def delete(self, preset_id: str) -> bool:
        with db_session(self.db_path) as conn:
            with conn:
                deleted = conn.execute("DELETE FROM task_presets WHERE id = ?", (preset_id,)).rowcount
        return bool(deleted)


task_preset_repo = TaskPresetRepository()
