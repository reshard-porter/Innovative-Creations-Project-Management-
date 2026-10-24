"""Small document repository with interchangeable SQLite and MongoDB storage.

The application uses opaque UUIDs with both engines. Every query that reads
personal project data is scoped to the signed-in user in the route layer.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

COLLECTIONS = {"users", "projects", "tasks", "activity"}


class DuplicateUser(ValueError):
    pass


class StaleRecord(ValueError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_record(data):
    stamp = now_iso()
    return {**data, "id": uuid4().hex, "created_at": stamp, "updated_at": stamp, "version": 1}


class SQLiteStore:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            for collection in COLLECTIONS:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {collection} (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
                )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS user_email ON users(json_extract(data, '$.email_key'))"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS user_username ON users(json_extract(data, '$.username_key'))"
            )
            for collection in ("projects", "tasks", "activity"):
                db.execute(
                    f"CREATE INDEX IF NOT EXISTS {collection}_owner ON {collection}(json_extract(data, '$.user_id'))"
                )
            db.execute(
                "CREATE TABLE IF NOT EXISTS throttles (id TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL)"
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def table(collection):
        if collection not in COLLECTIONS:
            raise ValueError("Unknown collection")
        return collection

    def find(self, collection, **filters):
        table = self.table(collection)
        clauses, parameters = [], []
        for field, value in filters.items():
            clauses.append("json_extract(data, ?) = ?")
            parameters.extend(["$." + field, value])
        query = f"SELECT data FROM {table}"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute(query, parameters)]

    def get(self, collection, record_id):
        with self.connection() as db:
            row = db.execute(
                f"SELECT data FROM {self.table(collection)} WHERE id = ?", (record_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def create(self, collection, data):
        record = new_record(data)
        try:
            with self.connection() as db:
                db.execute(
                    f"INSERT INTO {self.table(collection)}(id, data) VALUES (?, ?)",
                    (record["id"], json.dumps(record)),
                )
        except sqlite3.IntegrityError as exc:
            if collection == "users":
                raise DuplicateUser("That email or username is already registered.") from exc
            raise
        return record

    def update(self, collection, record_id, changes, expected_version=None):
        immutable = {"id", "created_at", "version"}
        changes = {k: v for k, v in changes.items() if k not in immutable}
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"SELECT data FROM {self.table(collection)} WHERE id = ?", (record_id,)
            ).fetchone()
            if not row:
                return None
            old = json.loads(row[0])
            if expected_version is not None and old["version"] != expected_version:
                raise StaleRecord("This record changed in another tab. Reload before saving.")
            updated = {**old, **changes, "version": old["version"] + 1, "updated_at": now_iso()}
            try:
                db.execute(
                    f"UPDATE {self.table(collection)} SET data = ? WHERE id = ?",
                    (json.dumps(updated), record_id),
                )
            except sqlite3.IntegrityError as exc:
                if collection == "users":
                    raise DuplicateUser("That email or username is already registered.") from exc
                raise
        return updated

    def delete(self, collection, record_id):
        with self.connection() as db:
            db.execute(f"DELETE FROM {self.table(collection)} WHERE id = ?", (record_id,))

    def delete_project(self, user_id, project_id):
        with self.connection() as db:
            for collection in ("tasks", "activity"):
                db.execute(
                    f"DELETE FROM {collection} WHERE json_extract(data, '$.user_id') = ? AND json_extract(data, '$.project_id') = ?",
                    (user_id, project_id),
                )
            db.execute(
                "DELETE FROM projects WHERE id = ? AND json_extract(data, '$.user_id') = ?",
                (project_id, user_id),
            )

    def delete_account(self, user_id):
        with self.connection() as db:
            for collection in ("tasks", "activity", "projects"):
                db.execute(
                    f"DELETE FROM {collection} WHERE json_extract(data, '$.user_id') = ?",
                    (user_id,),
                )
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def throttle(self, key, limit, seconds):
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM throttles WHERE expires <= ?", (now,))
            row = db.execute("SELECT count, expires FROM throttles WHERE id = ?", (key,)).fetchone()
            if row and row[0] >= limit:
                return max(1, int(row[1] - now) + 1)
            if row:
                db.execute("UPDATE throttles SET count = count + 1 WHERE id = ?", (key,))
            else:
                db.execute("INSERT INTO throttles VALUES (?, 1, ?)", (key, now + seconds))
        return 0

    def clear_throttle(self, key):
        with self.connection() as db:
            db.execute("DELETE FROM throttles WHERE id = ?", (key,))

    def healthy(self):
        with self.connection() as db:
            return db.execute("SELECT 1").fetchone()[0] == 1


class MongoStore:
    def __init__(self, uri, client=None):
        from pymongo import MongoClient

        self.client = client or MongoClient(uri, serverSelectionTimeoutMS=4000)
        self.db = self.client.get_default_database()
        if self.db is None:
            raise ValueError("MONGO_URI must include a database name, for example /Users")
        self.client.admin.command("ping")
        self.db.users.create_index("email_key", unique=True)
        self.db.users.create_index("username_key", unique=True)
        for collection in ("projects", "tasks", "activity"):
            self.db[collection].create_index("user_id")
        self.db.throttles.create_index("expires", expireAfterSeconds=0)

    def collection(self, name):
        if name not in COLLECTIONS:
            raise ValueError("Unknown collection")
        return self.db[name]

    @staticmethod
    def clean(record):
        if record:
            return {k: v for k, v in record.items() if k != "_id"}
        return None

    def find(self, collection, **filters):
        return [self.clean(row) for row in self.collection(collection).find(filters)]

    def get(self, collection, record_id):
        return self.clean(self.collection(collection).find_one({"_id": record_id}))

    def create(self, collection, data):
        from pymongo.errors import DuplicateKeyError

        record = new_record(data)
        try:
            self.collection(collection).insert_one({"_id": record["id"], **record})
        except DuplicateKeyError as exc:
            if collection == "users":
                raise DuplicateUser("That email or username is already registered.") from exc
            raise
        return record

    def update(self, collection, record_id, changes, expected_version=None):
        from pymongo import ReturnDocument
        from pymongo.errors import DuplicateKeyError

        query = {"_id": record_id}
        if expected_version is not None:
            query["version"] = expected_version
        changes = {
            k: v for k, v in changes.items() if k not in {"id", "_id", "created_at", "version"}
        }
        try:
            row = self.collection(collection).find_one_and_update(
                query,
                {"$set": {**changes, "updated_at": now_iso()}, "$inc": {"version": 1}},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            if collection == "users":
                raise DuplicateUser("That email or username is already registered.") from exc
            raise
        if row is None and expected_version is not None and self.get(collection, record_id):
            raise StaleRecord("This record changed in another tab. Reload before saving.")
        return self.clean(row)

    def delete(self, collection, record_id):
        self.collection(collection).delete_one({"_id": record_id})

    def delete_project(self, user_id, project_id):
        for collection in ("tasks", "activity"):
            self.db[collection].delete_many({"user_id": user_id, "project_id": project_id})
        self.db.projects.delete_one({"_id": project_id, "user_id": user_id})

    def delete_account(self, user_id):
        for collection in ("tasks", "activity", "projects"):
            self.db[collection].delete_many({"user_id": user_id})
        self.db.users.delete_one({"_id": user_id})

    def throttle(self, key, limit, seconds):
        from pymongo import ReturnDocument
        from pymongo.errors import DuplicateKeyError

        now = datetime.now(timezone.utc)
        from datetime import timedelta

        # Atomic increments protect the limit even when requests arrive together.
        row = self.db.throttles.find_one_and_update(
            {"_id": key, "expires": {"$gt": now}},
            {"$inc": {"count": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if row is None:
            try:
                row = self.db.throttles.find_one_and_update(
                    {
                        "_id": key,
                        "$or": [{"expires": {"$lte": now}}, {"expires": {"$exists": False}}],
                    },
                    {"$set": {"count": 1, "expires": now + timedelta(seconds=seconds)}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
            except DuplicateKeyError:
                row = self.db.throttles.find_one_and_update(
                    {"_id": key}, {"$inc": {"count": 1}}, return_document=ReturnDocument.AFTER
                )
        if row["count"] > limit:
            expires = row["expires"].replace(tzinfo=timezone.utc)
            return max(1, int((expires - now).total_seconds()) + 1)
        return 0

    def clear_throttle(self, key):
        self.db.throttles.delete_one({"_id": key})

    def healthy(self):
        return self.client.admin.command("ping").get("ok") == 1
