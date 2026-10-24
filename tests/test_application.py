import re

import pytest
from werkzeug.security import check_password_hash

from conftest import PASSWORD, login, post, project, register


def user(app, email="alex@example.test"):
    return app.extensions["store"].find("users", email_key=email)[0]


def saved_project(app, user_id=None):
    values = app.extensions["store"].find("projects", **({"user_id": user_id} if user_id else {}))
    return values[-1]


def test_public_routes_and_assets(client):
    for path in (
        "/",
        "/login",
        "/send",
        "/register",
        "/forgot-password",
        "/help",
        "/privacy",
        "/health",
        "/static/app.css",
        "/static/app.js",
        "/static/favicon.svg",
        "/static/poster.jpg",
    ):
        assert client.get(path).status_code == 200, path
    assert client.get("/health").json == {"status": "ok"}
    assert client.get("/static/back.mp4", headers={"Range": "bytes=0-999"}).status_code == 206


def test_registration_persists_a_hash_and_opens_workspace(client, app):
    response = register(client)
    assert response.status_code == 200
    assert b"Hello, Alex" in response.data
    saved = user(app)
    assert saved["password_hash"] != PASSWORD
    assert check_password_hash(saved["password_hash"], PASSWORD)
    assert PASSWORD.encode() not in response.data
    with client.session_transaction() as session:
        assert session["user_id"] == saved["id"]
        assert "password" not in session


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"password": "short", "confirm_password": "short"}, b"12"),
        ({"username": "bad username"}, b"underscores"),
        ({"email": "bad"}, b"valid email"),
        ({"first_name": ""}, b"First name"),
        ({"confirm_password": "different"}, b"match"),
    ],
)
def test_registration_rejects_invalid_input(client, app, changes, message):
    data = {
        "first_name": "Alex",
        "last_name": "Morgan",
        "username": "alex",
        "email": "alex@example.test",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
        **changes,
    }
    response = post(client, "/register", data)
    assert response.status_code == 400
    assert message in response.data
    assert app.extensions["store"].find("users") == []


def test_case_insensitive_uniqueness(member, app):
    post(member, "/logout")
    response = register(member, email="ALEX@example.test", username="another")
    assert response.status_code == 400
    assert b"already registered" in response.data
    response = register(member, email="different@example.test", username="ALEX")
    assert response.status_code == 400
    assert len(app.extensions["store"].find("users")) == 1


def test_login_logout_and_legacy_routes(member):
    assert member.get("/Profile").location.endswith("/profile")
    assert member.get("/Home").location.endswith("/dashboard")
    assert post(member, "/logout").status_code == 200
    assert member.get("/profile").status_code == 302
    assert login(member, password="incorrect passphrase").status_code == 400
    assert login(member, identity="ALEX").status_code == 200
    post(member, "/logout")
    assert post(member, "/send", {"email": "alex@example.test", "pwd": PASSWORD}).status_code == 200
    assert member.get("/logout").status_code == 405


@pytest.mark.parametrize(
    "destination", ["https://example.org/steal", "//example.org", "/\\example.org", "http://[bad"]
)
def test_authentication_requires_csrf_and_rejects_open_redirect(member, destination):
    post(member, "/logout")
    assert member.post("/login", data={"identity": "alex", "password": PASSWORD}).status_code == 400
    response = post(
        member,
        "/login",
        {"identity": "alex", "password": PASSWORD, "next": destination},
        follow=False,
    )
    assert response.location.endswith("/dashboard")


def test_login_rate_limit_persists_in_store(member, app):
    post(member, "/logout")
    for _ in range(8):
        assert login(member, password="incorrect passphrase").status_code == 400
    response = login(member)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_project_lifecycle_and_checklist(member, app):
    response = project(member)
    assert response.status_code == 200
    p = saved_project(app)
    assert p["title"] == "A thoughtful project"
    assert b"The next small steps" in response.data
    assert (
        post(member, f"/projects/{p['id']}/tasks", {"title": "Sketch the first idea"}).status_code
        == 200
    )
    task = app.extensions["store"].find("tasks")[0]
    assert not task["done"]
    post(member, f"/projects/{p['id']}/tasks/{task['id']}/toggle", {"version": task["version"]})
    assert app.extensions["store"].get("tasks", task["id"])["done"]
    assert b"1 of 1 done" in member.get(f"/projects/{p['id']}").data
    assert post(member, f"/projects/{p['id']}/delete", {"version": p["version"]}).status_code == 409
    p = app.extensions["store"].get("projects", p["id"])
    previous_version = p["version"]
    updated = post(
        member,
        f"/projects/{p['id']}/edit",
        {
            "version": p["version"],
            "title": "A completed project",
            "description": "All done.",
            "status": "completed",
            "category": "design",
            "due_date": "2027-01-15",
        },
    )
    assert updated.status_code == 200
    p = app.extensions["store"].get("projects", p["id"])
    assert p["status"] == "completed"
    assert p["version"] == previous_version + 1
    assert len(app.extensions["store"].find("activity")) >= 4
    assert b"A completed project" in member.get("/projects?status=completed&q=done").data
    assert b"No projects found" in member.get("/projects?q=nonexistent").data
    post(member, f"/projects/{p['id']}/delete", {"version": p["version"]})
    assert not app.extensions["store"].get("projects", p["id"])
    assert app.extensions["store"].find("tasks") == []
    assert app.extensions["store"].find("activity") == []


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"title": "x"}, b"between 3 and 120"),
        ({"due_date": "2026-02-30"}, b"valid date"),
        ({"status": "invalid"}, b"Choose a project status"),
        ({"category": "invalid"}, b"Choose a project category"),
        ({"description": "a" * 5001}, b"5,000"),
    ],
)
def test_project_validation(member, app, changes, message):
    response = project(member, **changes)
    assert response.status_code == 400
    assert message in response.data
    assert app.extensions["store"].find("projects") == []


def test_project_text_is_escaped(member, app):
    response = project(
        member, title="<script>alert(1)</script>", description="<img src=x onerror=alert(1)>"
    )
    assert response.status_code == 200
    assert b"&lt;script&gt;" in response.data
    assert b"<script>alert(1)</script>" not in response.data
    assert b"<img src=x" not in response.data


def test_ownership_is_enforced_for_all_project_actions(member, app):
    project(member)
    p = saved_project(app)
    post(member, f"/projects/{p['id']}/tasks", {"title": "Private item"})
    task = app.extensions["store"].find("tasks")[0]
    other = app.test_client()
    register(other, email="other@example.test", username="other")
    for path in (f"/projects/{p['id']}", f"/projects/{p['id']}/edit"):
        assert other.get(path).status_code == 404
    for path in (
        f"/projects/{p['id']}/edit",
        f"/projects/{p['id']}/delete",
        f"/projects/{p['id']}/tasks",
        f"/projects/{p['id']}/tasks/{task['id']}/toggle",
        f"/projects/{p['id']}/tasks/{task['id']}/delete",
    ):
        assert post(other, path, {"title": "intruder", "version": 1}).status_code == 404
    assert b"A thoughtful project" not in other.get("/dashboard").data
    assert other.get("/account/export").json["projects"] == []
    assert app.extensions["store"].get("projects", p["id"])["title"] == "A thoughtful project"


def test_stale_edits_and_checklist_updates_do_not_overwrite(member, app):
    project(member)
    p = saved_project(app)
    app.extensions["store"].update(
        "projects", p["id"], {"title": "Newer title"}, expected_version=1
    )
    response = post(
        member,
        f"/projects/{p['id']}/edit",
        {
            "version": 1,
            "title": "Old tab edit",
            "description": "",
            "status": "idea",
            "category": "web",
            "due_date": "",
        },
    )
    assert response.status_code == 409
    assert post(member, f"/projects/{p['id']}/delete", {"version": 1}).status_code == 409
    assert app.extensions["store"].get("projects", p["id"])["title"] == "Newer title"
    post(member, f"/projects/{p['id']}/tasks", {"title": "A task"})
    task = app.extensions["store"].find("tasks")[0]
    assert (
        post(member, f"/projects/{p['id']}/tasks/{task['id']}/toggle", {"version": 1}).status_code
        == 200
    )
    assert (
        post(member, f"/projects/{p['id']}/tasks/{task['id']}/toggle", {"version": 1}).status_code
        == 409
    )


def test_pagination_and_bad_page_values(member, app):
    repo = app.extensions["store"]
    owner = user(app)["id"]
    for index in range(11):
        repo.create(
            "projects",
            {
                "user_id": owner,
                "title": f"Project {index:02d}",
                "description": "",
                "status": "idea",
                "category": "web",
                "due_date": "",
            },
        )
    response = member.get("/projects?page=1")
    assert b"Page 1 of 2" in response.data
    assert response.data.count(b'<article class="project-card') == 9
    assert member.get("/projects?page=2").data.count(b'<article class="project-card') == 2
    assert member.get("/projects?page=bad").status_code == 200
    assert member.get("/projects?page=-5").status_code == 200


def test_profile_email_change_and_export(member, app):
    data = {
        "action": "profile",
        "version": user(app)["version"],
        "first_name": "Alicia",
        "last_name": "Morgan",
        "username": "alicia",
        "email": "new@example.test",
        "bio": "Making good things.",
    }
    assert post(member, "/profile", data).status_code == 400
    assert user(app)["email"] == "alex@example.test"
    response = post(member, "/profile", {**data, "current_password": PASSWORD})
    assert response.status_code == 200
    assert b"Alicia" in response.data
    saved = user(app, "new@example.test")
    assert saved["username_key"] == "alicia"
    exported = member.get("/account/export")
    assert "attachment" in exported.headers["Content-Disposition"]
    assert exported.json["profile"]["email"] == "new@example.test"
    assert b"password_hash" not in exported.data
    assert PASSWORD.encode() not in exported.data


def test_password_change_invalidates_other_sessions(member, app):
    other_session = app.test_client()
    assert login(other_session).status_code == 200
    new_password = "my newer thoughtful passphrase"
    response = post(
        member,
        "/profile",
        {
            "action": "password",
            "version": user(app)["version"],
            "current_password": PASSWORD,
            "password": new_password,
            "confirm_password": new_password,
        },
    )
    assert response.status_code == 200
    assert member.get("/profile").status_code == 200
    assert other_session.get("/profile").status_code == 302
    post(member, "/logout")
    assert login(member).status_code == 400
    assert login(member, password=new_password).status_code == 200


def test_password_recovery_generic_single_use_and_session_invalidation(member, app):
    guest = app.test_client()
    known = post(guest, "/forgot-password", {"email": "alex@example.test"})
    unknown = post(guest, "/forgot-password", {"email": "missing@example.test"})

    def strip_csrf(body):
        return re.sub(rb'name="csrf_token" value="[^"]+"', b"csrf", body)

    assert strip_csrf(known.data) == strip_csrf(unknown.data)
    assert len(app.extensions["mail_outbox"]) == 1
    message = app.extensions["mail_outbox"][0]
    assert message["link"].startswith("http://127.0.0.1:5000/reset-password/")
    path = "/reset-password/" + message["token"]
    assert guest.get(path).status_code == 200
    newer = "another thoughtful secret passphrase"
    assert post(guest, path, {"password": newer, "confirm_password": newer}).status_code == 200
    assert guest.get(path).status_code == 400
    assert member.get("/profile").status_code == 302
    assert login(guest, password=newer).status_code == 200


def test_invalid_and_expired_recovery_links(client, app):
    assert client.get("/reset-password/not-a-valid-token").status_code == 400
    register(client)
    post(client, "/logout")
    post(client, "/forgot-password", {"email": "alex@example.test"})
    path = "/reset-password/" + app.extensions["mail_outbox"][0]["token"]
    app.config["RESET_TOKEN_SECONDS"] = -1
    assert client.get(path).status_code == 400


def test_email_change_invalidates_old_reset_links_and_sessions(member, app):
    guest = app.test_client()
    post(guest, "/forgot-password", {"email": "alex@example.test"})
    old_link = "/reset-password/" + app.extensions["mail_outbox"][0]["token"]
    other_session = app.test_client()
    login(other_session)
    response = post(
        member,
        "/profile",
        {
            "action": "profile",
            "version": user(app)["version"],
            "first_name": "Alex",
            "last_name": "Morgan",
            "username": "alex",
            "email": "changed@example.test",
            "bio": "",
            "current_password": PASSWORD,
        },
    )
    assert response.status_code == 200
    assert guest.get(old_link).status_code == 400
    assert other_session.get("/profile").status_code == 302
    assert member.get("/profile").status_code == 200


def test_account_delete_requires_credentials_and_removes_records(member, app):
    project(member)
    p = saved_project(app)
    post(member, f"/projects/{p['id']}/tasks", {"title": "Private task"})
    data = {
        "action": "delete",
        "version": user(app)["version"],
        "confirm_username": "alex",
        "current_password": "wrong password",
    }
    assert post(member, "/profile", data).status_code == 400
    assert (
        post(
            member, "/profile", {**data, "current_password": PASSWORD, "confirm_username": "wrong"}
        ).status_code
        == 400
    )
    assert post(member, "/profile", {**data, "current_password": PASSWORD}).status_code == 200
    repo = app.extensions["store"]
    for collection in ("users", "projects", "tasks", "activity"):
        assert repo.find(collection) == []
    assert member.get("/dashboard").status_code == 302


def test_security_headers_and_session_cookie(client):
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_404_405_and_database_health_failure(client, app, monkeypatch):
    assert client.get("/not-a-page").status_code == 404
    assert client.get("/projects/no-project/delete").status_code == 405
    monkeypatch.setattr(app.extensions["store"], "healthy", lambda: False)
    assert client.get("/health").status_code == 503
    assert client.get("/health").json == {"status": "unavailable"}


def test_seed_demo_command_does_not_overwrite_accounts(app):
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["seed-demo", "--email", "demo@example.test", "--password", PASSWORD]
    )
    assert result.exit_code == 0, result.output
    assert len(app.extensions["store"].find("projects")) == 4
    result = runner.invoke(
        args=["seed-demo", "--email", "demo@example.test", "--password", PASSWORD]
    )
    assert result.exit_code != 0
    assert len(app.extensions["store"].find("users")) == 1
