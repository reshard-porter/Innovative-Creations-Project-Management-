"""Public pages, personal projects, checklists and account settings."""

from datetime import date
from io import BytesIO
import json
import math

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .auth import EMAIL, USERNAME, limited, login_required, start_session, store
from .store import DuplicateUser

web = Blueprint("web", __name__)
STATUSES = {"idea": "Idea", "in_progress": "In progress", "completed": "Completed"}
CATEGORIES = {"web": "Web & digital", "design": "Design", "brand": "Branding", "other": "Other"}


@web.app_context_processor
def project_options():
    return {"statuses": STATUSES, "categories": CATEGORIES}


def owned_project(project_id):
    project = store().get("projects", project_id)
    if not project or project["user_id"] != g.user["id"]:
        abort(404)
    return project


def record_version():
    try:
        version = int(request.form.get("version", ""))
        if version > 0:
            return version
    except ValueError:
        pass
    abort(400)


def activity(project, text):
    store().create("activity", {"user_id": g.user["id"], "project_id": project["id"], "text": text})


def decorate_projects(projects, tasks):
    for project in projects:
        checklist = [task for task in tasks if task["project_id"] == project["id"]]
        project["task_count"] = len(checklist)
        project["done_count"] = sum(bool(task["done"]) for task in checklist)
        project["progress"] = (
            round(project["done_count"] / len(checklist) * 100) if checklist else 0
        )
    return projects


@web.get("/")
def index():
    return render_template("index.html")


@web.get("/Home")
def legacy_home():
    return redirect(url_for("web.dashboard" if g.user else "web.index"))


@web.get("/Profile")
@login_required
def legacy_profile():
    return redirect(url_for("web.profile"))


@web.get("/help")
def help_page():
    return render_template("help.html")


@web.get("/privacy")
def privacy():
    return render_template("privacy.html")


@web.get("/dashboard")
@login_required
def dashboard():
    projects = store().find("projects", user_id=g.user["id"])
    tasks = store().find("tasks", user_id=g.user["id"])
    projects.sort(key=lambda item: item["updated_at"], reverse=True)
    decorate_projects(projects, tasks)
    counts = {
        status: sum(project["status"] == status for project in projects) for status in STATUSES
    }
    events = sorted(
        store().find("activity", user_id=g.user["id"]),
        key=lambda item: item["created_at"],
        reverse=True,
    )[:5]
    project_names = {p["id"]: p["title"] for p in projects}
    return render_template(
        "dashboard.html",
        active="dashboard",
        projects=projects[:4],
        total=len(projects),
        counts=counts,
        tasks_done=sum(t["done"] for t in tasks),
        tasks_total=len(tasks),
        events=events,
        project_names=project_names,
    )


@web.get("/projects")
@login_required
def projects():
    status = request.args.get("status", "all")
    if status not in {*STATUSES, "all"}:
        status = "all"
    query = request.args.get("q", "").strip()[:100]
    items = store().find("projects", user_id=g.user["id"])
    counts = {key: sum(p["status"] == key for p in items) for key in STATUSES}
    total = len(items)
    items = [
        p
        for p in items
        if (status == "all" or p["status"] == status)
        and (not query or query.casefold() in (p["title"] + " " + p["description"]).casefold())
    ]
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    pages = max(1, math.ceil(len(items) / 9))
    try:
        page = max(1, min(pages, int(request.args.get("page", "1"))))
    except ValueError:
        page = 1
    visible = items[(page - 1) * 9 : page * 9]
    decorate_projects(visible, store().find("tasks", user_id=g.user["id"]))
    return render_template(
        "projects.html",
        active="projects",
        projects=visible,
        total=total,
        matched=len(items),
        counts=counts,
        status=status,
        query=query,
        page=page,
        pages=pages,
    )


def validate_project():
    values = {
        field: request.form.get(field, "").strip()
        for field in ("title", "description", "status", "category", "due_date")
    }
    errors = {}
    if not 3 <= len(values["title"]) <= 120:
        errors["title"] = "Give your project a title between 3 and 120 characters."
    if len(values["description"]) > 5000:
        errors["description"] = "Keep the description under 5,000 characters."
    if values["status"] not in STATUSES:
        errors["status"] = "Choose a project status."
    if values["category"] not in CATEGORIES:
        errors["category"] = "Choose a project category."
    if values["due_date"]:
        try:
            date.fromisoformat(values["due_date"])
            if len(values["due_date"]) != 10:
                raise ValueError
        except ValueError:
            errors["due_date"] = "Choose a valid date."
    return values, errors


@web.route("/projects/new", methods=["GET", "POST"])
@login_required
def new_project():
    values = {"status": "idea", "category": "web"}
    errors = {}
    if request.method == "POST":
        values, errors = validate_project()
        if len(store().find("projects", user_id=g.user["id"])) >= 1000:
            errors["form"] = (
                "Your workspace has reached its 1,000 project limit. Export and remove older work before adding more."
            )
        if not errors:
            project = store().create("projects", {**values, "user_id": g.user["id"]})
            activity(project, "Created the project")
            flash("New project, new possibilities. Your project is saved.", "success")
            return redirect(url_for("web.project_detail", project_id=project["id"]))
    return render_template(
        "project_form.html", active="projects", values=values, errors=errors, project=None
    ), 400 if errors else 200


@web.get("/projects/<project_id>")
@login_required
def project_detail(project_id):
    project = owned_project(project_id)
    tasks = sorted(
        store().find("tasks", user_id=g.user["id"], project_id=project_id),
        key=lambda item: item["created_at"],
    )
    decorate_projects([project], tasks)
    events = sorted(
        store().find("activity", user_id=g.user["id"], project_id=project_id),
        key=lambda item: item["created_at"],
        reverse=True,
    )[:20]
    return render_template(
        "project_detail.html", active="projects", project=project, tasks=tasks, events=events
    )


@web.route("/projects/<project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    project = owned_project(project_id)
    values, errors = project.copy(), {}
    if request.method == "POST":
        values, errors = validate_project()
        if not errors:
            store().update("projects", project_id, values, expected_version=record_version())
            activity(project, "Updated the project details")
            flash("Your changes are saved.", "success")
            return redirect(url_for("web.project_detail", project_id=project_id))
    return render_template(
        "project_form.html", active="projects", values=values, errors=errors, project=project
    ), 400 if errors else 200


@web.post("/projects/<project_id>/delete")
@login_required
def delete_project(project_id):
    project = owned_project(project_id)
    # Require the latest version so an older open tab cannot remove newer work.
    if record_version() != project["version"]:
        from .store import StaleRecord

        raise StaleRecord("This project changed in another tab. Reload before deleting.")
    store().delete_project(g.user["id"], project_id)
    flash("Project and checklist deleted.", "success")
    return redirect(url_for("web.projects"))


@web.post("/projects/<project_id>/tasks")
@login_required
def add_task(project_id):
    project = owned_project(project_id)
    title = request.form.get("title", "").strip()
    if not 1 <= len(title) <= 200:
        flash("Write a checklist item between 1 and 200 characters.", "error")
    elif len(store().find("tasks", user_id=g.user["id"], project_id=project_id)) >= 100:
        flash("A project can have up to 100 checklist items.", "error")
    else:
        store().create(
            "tasks",
            {"user_id": g.user["id"], "project_id": project_id, "title": title, "done": False},
        )
        store().update("projects", project_id, {})
        activity(project, "Added a checklist item")
        flash("Checklist item added.", "success")
    return redirect(url_for("web.project_detail", project_id=project_id) + "#checklist")


def owned_task(project_id, task_id):
    task = store().get("tasks", task_id)
    if not task or task["user_id"] != g.user["id"] or task["project_id"] != project_id:
        abort(404)
    return task


@web.post("/projects/<project_id>/tasks/<task_id>/toggle")
@login_required
def toggle_task(project_id, task_id):
    project = owned_project(project_id)
    task = owned_task(project_id, task_id)
    store().update("tasks", task_id, {"done": not task["done"]}, expected_version=record_version())
    store().update("projects", project_id, {})
    activity(
        project, "Completed a checklist item" if not task["done"] else "Reopened a checklist item"
    )
    return redirect(url_for("web.project_detail", project_id=project_id) + "#checklist")


@web.post("/projects/<project_id>/tasks/<task_id>/delete")
@login_required
def delete_task(project_id, task_id):
    project = owned_project(project_id)
    task = owned_task(project_id, task_id)
    if record_version() != task["version"]:
        from .store import StaleRecord

        raise StaleRecord("This checklist item changed. Reload before deleting.")
    store().delete("tasks", task_id)
    store().update("projects", project_id, {})
    activity(project, "Removed a checklist item")
    return redirect(url_for("web.project_detail", project_id=project_id) + "#checklist")


@web.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    values = g.user.copy()
    errors = {}
    if request.method == "POST":
        action = request.form.get("action", "profile")
        if action == "profile":
            values = {
                k: request.form.get(k, "").strip()
                for k in ("first_name", "last_name", "username", "email", "bio")
            }
            for name in ("first_name", "last_name"):
                if not 1 <= len(values[name]) <= 50:
                    errors[name] = "Use between 1 and 50 characters."
            if not USERNAME.fullmatch(values["username"]):
                errors["username"] = "Use 3–24 letters, numbers or underscores."
            if len(values["email"]) > 254 or not EMAIL.fullmatch(values["email"]):
                errors["email"] = "Enter a valid email address."
            if len(values["bio"]) > 500:
                errors["bio"] = "Keep your bio under 500 characters."
            email_changed = values["email"].casefold() != g.user["email_key"]
            if email_changed and not check_password_hash(
                g.user["password_hash"], request.form.get("current_password", "")
            ):
                errors["current_password"] = "Confirm your current password to change your email."
            if not errors:
                try:
                    updated_user = store().update(
                        "users",
                        g.user["id"],
                        {
                            **values,
                            "email_key": values["email"].casefold(),
                            "username_key": values["username"].casefold(),
                            "auth_version": g.user["auth_version"] + int(email_changed),
                        },
                        expected_version=record_version(),
                    )
                except DuplicateUser as exc:
                    errors["form"] = str(exc)
                else:
                    if email_changed:
                        remember = session.permanent
                        start_session(updated_user, remember)
                    flash("Your profile is up to date.", "success")
                    return redirect(url_for("web.profile"))
        elif action in {"password", "delete"}:
            _, wait = limited("account-sensitive", g.user["id"])
            if wait:
                errors["form"] = "Too many attempts. Wait a few minutes before trying again."
            elif not check_password_hash(
                g.user["password_hash"], request.form.get("current_password", "")[:128]
            ):
                errors["form"] = "Your current password is incorrect."
            elif action == "password":
                password = request.form.get("password", "")
                if not 12 <= len(password) <= 128:
                    errors["form"] = "Your new password must have 12–128 characters."
                elif password != request.form.get("confirm_password"):
                    errors["form"] = "The new passwords don’t match."
                else:
                    user = store().update(
                        "users",
                        g.user["id"],
                        {
                            "password_hash": generate_password_hash(password),
                            "auth_version": g.user["auth_version"] + 1,
                        },
                        expected_version=record_version(),
                    )
                    remember = session.permanent
                    start_session(user, remember)
                    flash("Password changed. Your other sessions have been signed out.", "success")
                    return redirect(url_for("web.profile"))
            elif request.form.get("confirm_username") != g.user["username"]:
                errors["form"] = "Type your username exactly to confirm account deletion."
            else:
                if record_version() != g.user["version"]:
                    from .store import StaleRecord

                    raise StaleRecord(
                        "Your account changed in another tab. Reload before closing it."
                    )
                store().delete_account(g.user["id"])
                session.clear()
                flash("Your account and workspace data have been deleted.", "success")
                return redirect(url_for("web.index"))
        else:
            abort(400)
    return render_template(
        "profile.html", active="profile", values=values, errors=errors
    ), 400 if errors else 200


@web.get("/account/export")
@login_required
def export_account():
    user = {
        key: g.user[key]
        for key in ("first_name", "last_name", "username", "email", "bio", "created_at")
    }
    data = {
        "profile": user,
        "projects": store().find("projects", user_id=g.user["id"]),
        "checklist_items": store().find("tasks", user_id=g.user["id"]),
        "activity": store().find("activity", user_id=g.user["id"]),
    }
    payload = BytesIO(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
    return send_file(
        payload,
        mimetype="application/json",
        as_attachment=True,
        download_name="innovative-creations-workspace.json",
    )


def seed_projects(repository, user_id):
    examples = [
        (
            "A brighter brand identity",
            "Explore a fresh visual identity: a clear logo, a confident colour palette and a set of everyday brand essentials.",
            "in_progress",
            "brand",
            ["Collect inspiration", "Explore three logo directions", "Refine the final identity"],
        ),
        (
            "Portfolio, reimagined",
            "Create a home for the work that matters. Keep the layout simple, the stories clear and the details thoughtful.",
            "in_progress",
            "web",
            ["Select featured work", "Write project stories", "Build the first prototype"],
        ),
        (
            "Little ideas, big possibilities",
            "A collection of small product ideas worth exploring. Start with one problem and sketch a few possible solutions.",
            "idea",
            "design",
            ["Choose a problem to explore", "Sketch a first solution"],
        ),
        (
            "The welcome collection",
            "A simple set of graphics to help new members feel at home.",
            "completed",
            "design",
            ["Design the welcome card", "Prepare final artwork"],
        ),
    ]
    for title, description, status, category, tasks in examples:
        project = repository.create(
            "projects",
            {
                "user_id": user_id,
                "title": title,
                "description": description,
                "status": status,
                "category": category,
                "due_date": "",
            },
        )
        for index, title in enumerate(tasks):
            repository.create(
                "tasks",
                {
                    "user_id": user_id,
                    "project_id": project["id"],
                    "title": title,
                    "done": status == "completed" or (status == "in_progress" and index == 0),
                },
            )
        repository.create(
            "activity",
            {"user_id": user_id, "project_id": project["id"], "text": "Created the project"},
        )
