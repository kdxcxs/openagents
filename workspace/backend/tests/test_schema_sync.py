"""Schema sync checks for ORM models, Alembic migrations, and init SQL."""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import sqlalchemy as sa

from app.database import Base
import app.models  # noqa: F401  # Populate Base.metadata.


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[1]
ALEMBIC_VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"
INIT_SQL_PATH = REPO_ROOT / "workspace" / "scripts" / "insforge-migration" / "0001_initial_schema.sql"


class _MigrationSchema:
    def __init__(self) -> None:
        self.tables: dict[str, set[str]] = {}
        self.indexes: set[str] = set()


class _FakeResult:
    def fetchall(self) -> list[tuple]:
        return []

    def first(self) -> None:
        return None


class _FakeConnection:
    def execute(self, *_args, **_kwargs) -> _FakeResult:
        return _FakeResult()


class _FakeOp:
    def __init__(self) -> None:
        self.schema = _MigrationSchema()

    def create_table(self, table_name: str, *elements, **_kwargs) -> None:
        columns = {
            element.name
            for element in elements
            if isinstance(element, sa.Column)
        }
        self.schema.tables.setdefault(table_name, set()).update(columns)

    def add_column(self, table_name: str, column: sa.Column, **_kwargs) -> None:
        self.schema.tables.setdefault(table_name, set()).add(column.name)

    def create_index(self, index_name: str, _table_name: str, _columns, **_kwargs) -> None:
        self.schema.indexes.add(index_name)

    def alter_column(self, *_args, **_kwargs) -> None:
        pass

    def execute(self, statement, *_args, **_kwargs) -> None:
        sql = str(statement)
        for table_name, column_name in re.findall(
            r"ALTER TABLE\s+(\w+)\s+ADD COLUMN IF NOT EXISTS\s+(\w+)",
            sql,
            re.I,
        ):
            self.schema.tables.setdefault(table_name, set()).add(column_name)

        for table_name, table_body in re.findall(
            r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s+\((.*?)\);",
            sql,
            re.S | re.I,
        ):
            self.schema.tables.setdefault(table_name, set()).update(_columns_from_sql_table_body(table_body))

        for index_name in re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS\s+(\w+)", sql, re.I):
            self.schema.indexes.add(index_name)

    def get_bind(self) -> _FakeConnection:
        return _FakeConnection()


def _migration_files() -> list[Path]:
    files = sorted(ALEMBIC_VERSIONS_DIR.glob("*.py"))
    revision_by_file = {}
    down_revision_by_file = {}
    for path in files:
        text = path.read_text()
        revision_by_file[path] = re.search(r'^revision = ["\']([^"\']+)["\']', text, re.M).group(1)
        down_match = re.search(r'^down_revision = ["\']([^"\']+)["\']', text, re.M)
        down_revision_by_file[path] = down_match.group(1) if down_match else None

    by_down_revision = {
        down_revision: path
        for path, down_revision in down_revision_by_file.items()
        if down_revision is not None
    }
    first = next(path for path, down_revision in down_revision_by_file.items() if down_revision is None)
    ordered = [first]
    while revision_by_file[ordered[-1]] in by_down_revision:
        ordered.append(by_down_revision[revision_by_file[ordered[-1]]])
    return ordered


def _latest_revision() -> str:
    return _revision_id(_migration_files()[-1])


def _revision_id(path: Path) -> str:
    return re.search(r'^revision = ["\']([^"\']+)["\']', path.read_text(), re.M).group(1)


def _replayed_migration_schema() -> _MigrationSchema:
    fake_op = _FakeOp()
    alembic_module = types.ModuleType("alembic")
    alembic_module.op = fake_op
    original_alembic = sys.modules.get("alembic")
    sys.modules["alembic"] = alembic_module
    try:
        for path in _migration_files():
            module_name = f"_schema_sync_{path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            module.upgrade()
    finally:
        if original_alembic is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = original_alembic
    return fake_op.schema


def _model_tables() -> dict[str, set[str]]:
    return {
        table_name: {column.name for column in table.columns}
        for table_name, table in Base.metadata.tables.items()
    }


def _model_index_names() -> set[str]:
    return {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }


def _init_sql_tables() -> dict[str, set[str]]:
    sql = INIT_SQL_PATH.read_text()
    tables: dict[str, set[str]] = {}
    for match in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", sql, re.S | re.I):
        table_name, table_body = match.groups()
        tables[table_name] = _columns_from_sql_table_body(table_body)
    return tables


def _columns_from_sql_table_body(table_body: str) -> set[str]:
    columns = set()
    for line in table_body.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or stripped.startswith("--"):
            continue
        first_token = stripped.split()[0].lower()
        if first_token in {"primary", "constraint", "unique", "foreign", "check"}:
            continue
        columns.add(stripped.split()[0].strip('"'))
    return columns


def _init_sql_index_names() -> set[str]:
    sql = INIT_SQL_PATH.read_text()
    return set(re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)", sql, re.I))


def test_alembic_migrations_cover_model_tables_columns_and_indexes() -> None:
    migration_schema = _replayed_migration_schema()

    assert migration_schema.tables == _model_tables()
    assert migration_schema.indexes == _model_index_names()


def test_insforge_init_sql_covers_model_tables_columns_indexes_and_head_stamp() -> None:
    sql = INIT_SQL_PATH.read_text()
    init_sql_tables = _init_sql_tables()
    model_tables = _model_tables()

    assert {name: init_sql_tables[name] for name in model_tables} == model_tables
    assert set(init_sql_tables) - set(model_tables) == {"alembic_version"}
    assert _init_sql_index_names() == _model_index_names()
    assert re.search(
        rf"INSERT INTO alembic_version \(version_num\)\s+SELECT\s+'{_latest_revision()}'",
        sql,
        re.I,
    )
