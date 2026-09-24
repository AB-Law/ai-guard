"""Comprehensive tests for api/case_store_db.py to reach 90%+ coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from api.case_store_db import (
    SqliteCaseStore,
    _SqliteJSONMap,
    build_case_store,
    build_kv_store,
)


def test_sqlite_json_map_setitem_and_getitem(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["key1"] = {"value": "data1", "number": 42}
    retrieved = store["key1"]
    assert retrieved["value"] == "data1"
    assert retrieved["number"] == 42


def test_sqlite_json_map_update_existing(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["key1"] = {"value": "original"}
    store["key1"] = {"value": "updated", "new_field": True}
    
    retrieved = store["key1"]
    assert retrieved["value"] == "updated"
    assert retrieved["new_field"] is True


def test_sqlite_json_map_getitem_missing_raises_keyerror(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    with pytest.raises(KeyError):
        _ = store["nonexistent"]


def test_sqlite_json_map_delitem(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["key1"] = {"value": "test"}
    assert "key1" in store
    
    del store["key1"]
    
    with pytest.raises(KeyError):
        _ = store["key1"]


def test_sqlite_json_map_delitem_missing_raises_keyerror(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    with pytest.raises(KeyError):
        del store["nonexistent"]


def test_sqlite_json_map_iter(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["key1"] = {"a": 1}
    store["key2"] = {"b": 2}
    store["key3"] = {"c": 3}
    
    keys = list(store)
    assert len(keys) == 3
    assert "key1" in keys
    assert "key2" in keys
    assert "key3" in keys


def test_sqlite_json_map_len(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    assert len(store) == 0
    
    store["key1"] = {"a": 1}
    assert len(store) == 1
    
    store["key2"] = {"b": 2}
    assert len(store) == 2
    
    del store["key1"]
    assert len(store) == 1


def test_sqlite_json_map_clear(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["key1"] = {"a": 1}
    store["key2"] = {"b": 2}
    store["key3"] = {"c": 3}
    assert len(store) == 3
    
    store.clear()
    assert len(store) == 0


def test_sqlite_json_map_contains(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["key1"] = {"value": "test"}
    
    assert "key1" in store
    assert "key2" not in store


def test_sqlite_case_store_cases_mapping(tmp_path: Path) -> None:
    db_path = tmp_path / "cases.db"
    store = SqliteCaseStore(db_path)
    
    case = {
        "case_id": "case-123",
        "status": "completed",
        "process": "procurement_review",
    }
    store.cases["case-123"] = case
    
    retrieved = store.cases["case-123"]
    assert retrieved["case_id"] == "case-123"
    assert retrieved["status"] == "completed"


def test_sqlite_case_store_call_to_case_mapping(tmp_path: Path) -> None:
    db_path = tmp_path / "cases.db"
    store = SqliteCaseStore(db_path)
    
    store.call_to_case["call-456"] = "case-789"
    
    assert store.call_to_case["call-456"] == "case-789"


def test_sqlite_case_store_creates_parent_directory(tmp_path: Path) -> None:
    nested_path = tmp_path / "nested" / "dir" / "cases.db"
    store = SqliteCaseStore(nested_path)
    
    assert nested_path.exists()
    store.cases["test"] = {"id": "test"}
    assert store.cases["test"]["id"] == "test"


def test_build_case_store_memory_default(tmp_path: Path) -> None:
    """When database_url is None, return in-memory factory."""
    def memory_factory():
        return type("Store", (), {"cases": {}, "call_to_case": {}})()
    
    store = build_case_store(None, sqlite_path=tmp_path / "unused.db", memory_factory=memory_factory)
    
    # Should be the memory object, not a SqliteCaseStore
    assert hasattr(store, "cases")
    assert hasattr(store, "call_to_case")
    assert isinstance(store.cases, dict)


def test_build_case_store_sqlite(tmp_path: Path) -> None:
    """When database_url is 'sqlite', return SqliteCaseStore."""
    db_path = tmp_path / "cases.db"
    store = build_case_store("sqlite", sqlite_path=db_path, memory_factory=dict)
    
    assert isinstance(store, SqliteCaseStore)
    
    # Test it actually works
    store.cases["test-case"] = {"id": "test-case"}
    assert store.cases["test-case"]["id"] == "test-case"


def test_build_kv_store_memory_default(tmp_path: Path) -> None:
    """When database_url is None, return in-memory factory."""
    store = build_kv_store(
        None,
        table="test_table",
        key_col="test_key",
        sqlite_path=tmp_path / "unused.db",
        memory_factory=dict,
    )
    
    assert isinstance(store, dict)


def test_build_kv_store_sqlite(tmp_path: Path) -> None:
    """When database_url is 'sqlite', return _SqliteJSONMap."""
    db_path = tmp_path / "kv.db"
    store = build_kv_store(
        "sqlite",
        table="applications",
        key_col="app_id",
        sqlite_path=db_path,
        memory_factory=dict,
    )
    
    assert isinstance(store, _SqliteJSONMap)
    
    # Test it actually works
    store["app-123"] = {"name": "Test App"}
    assert store["app-123"]["name"] == "Test App"


def test_sqlite_json_map_multiple_tables_same_db(tmp_path: Path) -> None:
    """Multiple maps can coexist in the same database file."""
    db_path = tmp_path / "shared.db"
    
    store1 = _SqliteJSONMap(db_path, "table1", "key1")
    store2 = _SqliteJSONMap(db_path, "table2", "key2")
    
    store1["item1"] = {"table": "one"}
    store2["item2"] = {"table": "two"}
    
    assert store1["item1"]["table"] == "one"
    assert store2["item2"]["table"] == "two"
    assert len(store1) == 1
    assert len(store2) == 1


def test_sqlite_json_map_handles_complex_json(tmp_path: Path) -> None:
    """Test storing and retrieving complex nested JSON structures."""
    db_path = tmp_path / "complex.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    complex_data = {
        "nested": {
            "deep": {
                "structure": [1, 2, 3],
                "bool": True,
                "null": None,
            }
        },
        "list": ["a", "b", "c"],
        "number": 42.5,
    }
    
    store["complex"] = complex_data
    retrieved = store["complex"]
    
    assert retrieved["nested"]["deep"]["structure"] == [1, 2, 3]
    assert retrieved["nested"]["deep"]["bool"] is True
    assert retrieved["nested"]["deep"]["null"] is None
    assert retrieved["list"] == ["a", "b", "c"]
    assert retrieved["number"] == 42.5


def test_sqlite_case_store_separate_tables(tmp_path: Path) -> None:
    """Test that cases and call_to_case use separate tables."""
    db_path = tmp_path / "cases.db"
    store = SqliteCaseStore(db_path)
    
    store.cases["case-1"] = {"data": "case"}
    store.call_to_case["call-1"] = "case-1"
    
    assert len(store.cases) == 1
    assert len(store.call_to_case) == 1
    
    # Deleting from one shouldn't affect the other
    del store.call_to_case["call-1"]
    assert len(store.call_to_case) == 0
    assert len(store.cases) == 1


def test_sqlite_json_map_get_with_default(tmp_path: Path) -> None:
    """Test dict-like get() method (inherited from MutableMapping)."""
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["exists"] = {"value": "test"}
    
    assert store.get("exists") == {"value": "test"}
    assert store.get("missing") is None
    assert store.get("missing", "default") == "default"


def test_sqlite_json_map_keys_values_items(tmp_path: Path) -> None:
    """Test dict-like keys(), values(), items() methods."""
    db_path = tmp_path / "test.db"
    store = _SqliteJSONMap(db_path, "test_table", "key_col")
    
    store["key1"] = {"val": 1}
    store["key2"] = {"val": 2}
    
    keys = list(store.keys())
    assert len(keys) == 2
    assert "key1" in keys
    
    values = list(store.values())
    assert len(values) == 2
    assert {"val": 1} in values
    
    items = list(store.items())
    assert len(items) == 2
    assert ("key1", {"val": 1}) in items or ("key2", {"val": 2}) in items
