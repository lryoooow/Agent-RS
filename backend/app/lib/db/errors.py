from __future__ import annotations


MISSING_SCHEMA_ERROR_NAMES = {
    "UndefinedTableError",
    "UndefinedColumnError",
    "UndefinedObjectError",
}


def is_missing_schema_error(exc: Exception) -> bool:
    return exc.__class__.__name__ in MISSING_SCHEMA_ERROR_NAMES
