from pathlib import Path

import pytest

from sql.apply import MIGRATIONS_DIR, migration_paths


def test_repository_migrations_are_contiguous_and_include_reserved_0009() -> None:
    paths = migration_paths()
    assert paths[0].name.startswith("0000_")
    assert any(path.name.startswith("0013_") for path in paths)
    assert any(path.name.startswith("0014_") for path in paths)
    assert any(path.name == "0009_reserved.sql" for path in paths)


def test_migration_plan_rejects_a_missing_version(tmp_path: Path) -> None:
    (tmp_path / "0000_base.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0002_later.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(RuntimeError, match="0001"):
        migration_paths(tmp_path)


def test_migration_plan_rejects_duplicate_numeric_versions(tmp_path: Path) -> None:
    (tmp_path / "0000_base.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0000_duplicate.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(RuntimeError, match="重复"):
        migration_paths(tmp_path)
