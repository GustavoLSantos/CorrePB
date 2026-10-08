"""Tests for payload_store round-trip and safety of the restore path."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data_collection.utils.payload_store import (
    _doc_for,
    database_name,
    drop_payload,
    load_payload,
    payload_collection,
    save_payload,
)


class _Result:
    def __init__(self, deleted):
        self.deleted_count = deleted


class FakeCollection:
    """Mimica o necessário de uma collection do pymongo."""

    def __init__(self):
        self.docs = {}

    def update_one(self, filt, update, upsert=False):
        self.docs[filt["_id"]] = update["$set"]

    def find(self, query):
        job_id = query["job_id"]
        return [d for d in self.docs.values() if d["job_id"] == job_id]

    def delete_many(self, query):
        job_id = query["job_id"]
        keys = [k for k, d in self.docs.items() if d["job_id"] == job_id]
        for key in keys:
            del self.docs[key]
        return _Result(len(keys))

    def count_documents(self, query):
        job_id = query["job_id"]
        return sum(1 for d in self.docs.values() if d["job_id"] == job_id)

    def create_index(self, *_a, **_k):
        return "idx"


def _csv_map(tmp: Path):
    return {
        "brasilquecorre": tmp / "brasilquecorre.csv",
        "smcrono": tmp / "smcrono.csv",
    }


def test_save_and_load_roundtrip():
    store = FakeCollection()
    with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
        source = _csv_map(Path(dir_a))
        source["brasilquecorre"].write_text("a;b\n1;2\n", encoding="utf-8")

        saved = save_payload(store, "job-1", source)
        assert saved == ["brasilquecorre"], saved
        assert store.docs["job-1|brasilquecorre"]["content"] == "a;b\n1;2\n"

        target = _csv_map(Path(dir_b))
        assert not target["brasilquecorre"].exists()
        restored = load_payload(store, "job-1", target)
        assert restored == ["brasilquecorre"], restored
        assert target["brasilquecorre"].read_text(encoding="utf-8") == "a;b\n1;2\n"


def test_roundtrip_preserves_semicolon_content():
    store = FakeCollection()
    with tempfile.TemporaryDirectory() as dir_a, tempfile.TemporaryDirectory() as dir_b:
        source = _csv_map(Path(dir_a))
        payload = '"Nome do Evento";"Data"\n"Corrida; do parque";"24 de Setembro de 2026"\n'
        source["smcrono"].write_text(payload, encoding="utf-8")

        save_payload(store, "job-2", source)
        target = _csv_map(Path(dir_b))
        load_payload(store, "job-2", target)
        assert target["smcrono"].read_text(encoding="utf-8") == payload


def test_load_ignores_unknown_fonte():
    store = FakeCollection()
    store.docs["job-3|injetada"] = {
        "_id": "job-3|injetada",
        "job_id": "job-3",
        "fonte": "injetada",
        "content": "x",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    with tempfile.TemporaryDirectory() as dir_b:
        target = _csv_map(Path(dir_b))
        restored = load_payload(store, "job-3", target)
        assert restored == []


def test_drop_payload():
    store = FakeCollection()
    with tempfile.TemporaryDirectory() as dir_a:
        source = _csv_map(Path(dir_a))
        source["brasilquecorre"].write_text("x", encoding="utf-8")
        save_payload(store, "job-4", source)
        assert drop_payload(store, "job-4") == 1
        assert store.docs == {}


def test_doc_for_keys_and_ttl():
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    doc = _doc_for("job", "fonte", "conteudo", now)
    assert doc["_id"] == "job|fonte"
    assert doc["expires_at"] == now + timedelta(hours=24)
    assert doc["content"] == "conteudo"


def test_database_name_prefers_remote():
    import os

    saved = {
        key: os.environ.get(key)
        for key in ("MONGODB_REMOTE_DB_NAME", "MONGODB_DB_NAME")
    }
    try:
        os.environ["MONGODB_REMOTE_DB_NAME"] = "remoto"
        os.environ["MONGODB_DB_NAME"] = "local"
        assert database_name() == "remoto"
        del os.environ["MONGODB_REMOTE_DB_NAME"]
        assert database_name() == "local"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_payload_collection_uses_database_name():
    import os

    saved = {key: os.environ.get(key) for key in ("MONGODB_REMOTE_DB_NAME", "MONGODB_DB_NAME")}
    try:
        os.environ.pop("MONGODB_REMOTE_DB_NAME", None)
        os.environ.pop("MONGODB_DB_NAME", None)
        assert database_name() == "correpb"

        class Client:
            def __getitem__(self, name):
                return {"scrape_payload": (name, "scrape_payload")}

        assert payload_collection(Client()) == ("correpb", "scrape_payload")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
