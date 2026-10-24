"""Check the running WSGI server using only Python's standard library.

Usage: python tests/http_smoke.py --base-url http://127.0.0.1:5000
Creates a temporary local test account and removes it after successful checks.
"""

import argparse
from http.cookiejar import CookieJar
import json
import re
import secrets
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    base = parser.parse_args().base_url.rstrip("/")
    if urlsplit(base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Use a local development server; this check creates temporary data.")
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    checks = []

    def get(path):
        with opener.open(base + path, timeout=10) as response:
            return response.read().decode("utf-8"), response.geturl(), dict(response.headers)

    def post(path, values):
        page, _, _ = get("/login")
        csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', page)
        if not csrf:
            # Templates may put the name and value attributes on separate lines.
            csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page)
        assert csrf, "Missing CSRF token"
        payload = urlencode({"csrf_token": csrf[1], **values}).encode()
        with opener.open(Request(base + path, data=payload), timeout=10) as response:
            return response.read().decode("utf-8"), response.geturl(), dict(response.headers)

    assert json.loads(get("/health")[0])["status"] == "ok"
    home = get("/")
    assert "Good ideas deserve" in home[0]
    assert "default-src 'self'" in home[2]["Content-Security-Policy"]
    checks.append("Public page and database health through the running server")
    username = "qa_" + secrets.token_hex(5)
    password = secrets.token_urlsafe(24)
    email = username + "@example.test"
    page, address, _ = post(
        "/register",
        {
            "first_name": "HTTP",
            "last_name": "Check",
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )
    assert address.endswith("/dashboard") and "Hello, HTTP" in page
    checks.append("Registration, session cookie and authenticated dashboard")
    page, address, _ = post(
        "/projects/new",
        {
            "title": "HTTP smoke project",
            "description": "A real request through Waitress.",
            "status": "in_progress",
            "category": "web",
            "due_date": "",
        },
    )
    project_path = urlsplit(address).path
    assert "HTTP smoke project" in page
    page, _, _ = post(project_path + "/tasks", {"title": "Verify the running server"})
    assert "Verify the running server" in page
    toggle = re.search(r'action="([^"]+/toggle)"', page)[1]
    page, _, _ = post(toggle, {"version": "1"})
    assert "1 of 1 done" in page
    checks.append("Project creation and persisted checklist changes")
    exported = json.loads(get("/account/export")[0])
    assert exported["profile"]["email"] == email
    assert len(exported["projects"]) == 1 and exported["checklist_items"][0]["done"]
    assert "password_hash" not in json.dumps(exported)
    checks.append("Account export contains work and excludes credentials")
    post("/logout", {})
    assert "/login" in get("/dashboard")[1]
    page, address, _ = post("/login", {"identity": username, "password": password})
    assert address.endswith("/dashboard") and "HTTP smoke project" in page
    checks.append("Logout, protected redirect and sign-in to persisted data")
    profile, _, _ = get("/profile")
    version = re.search(r'name="version"\s+value="([^"]+)"', profile)[1]
    page, _, _ = post(
        "/profile",
        {
            "action": "delete",
            "version": version,
            "confirm_username": username,
            "current_password": password,
        },
    )
    assert "Your account and workspace data have been deleted" in page
    assert "/login" in get("/dashboard")[1]
    checks.append("Temporary account deletion and signed-out state")
    print(json.dumps({"passed": len(checks), "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
