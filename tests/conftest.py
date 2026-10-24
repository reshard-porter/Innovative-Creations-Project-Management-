"""Exercise the same application behavior against both storage adapters."""

from pathlib import Path
import re
import sys

import mongomock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from innovative import create_app

PASSWORD = "a thoughtful test passphrase"


@pytest.fixture(params=["sqlite", "mongo"])
def app(request, tmp_path):
    config = {
        "TESTING": True,
        "SECRET_KEY": "test-only-random-looking-secret",
        "INSTANCE_PATH": str(tmp_path),
        "DATABASE": str(tmp_path / "test.sqlite3"),
        "DATABASE_BACKEND": request.param,
    }
    if request.param == "mongo":
        config["MONGO_CLIENT"] = mongomock.MongoClient("mongodb://localhost/Users")
    return create_app(config)


@pytest.fixture
def client(app):
    return app.test_client()


def token(client, page="/login"):
    response = client.get(page, follow_redirects=True)
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match, response.data[:300]
    return match.group(1).decode()


def post(client, path, data=None, follow=True):
    data = dict(data or {})
    data.setdefault("csrf_token", token(client))
    return client.post(path, data=data, follow_redirects=follow)


def register(client, email="alex@example.test", username="alex", password=PASSWORD):
    return post(
        client,
        "/register",
        {
            "first_name": "Alex",
            "last_name": "Morgan",
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )


def login(client, identity="alex@example.test", password=PASSWORD, **extra):
    return post(client, "/login", {"identity": identity, "password": password, **extra})


def project(client, **overrides):
    return post(
        client,
        "/projects/new",
        {
            "title": "A thoughtful project",
            "description": "A small idea with a big future.",
            "status": "idea",
            "category": "web",
            "due_date": "",
            **overrides,
        },
    )


@pytest.fixture
def member(client):
    assert register(client).status_code == 200
    return client
