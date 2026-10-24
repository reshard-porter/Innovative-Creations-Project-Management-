"""Application factory and shared configuration."""

from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import secrets
from zoneinfo import ZoneInfo

import click
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, session
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import generate_password_hash

from .store import MongoStore, SQLiteStore, StaleRecord

ROOT = Path(__file__).resolve().parent.parent
csrf = CSRFProtect()


def create_app(test_config=None):
    load_dotenv(ROOT / ".env")
    overrides = test_config or {}
    instance = Path(
        overrides.get("INSTANCE_PATH") or os.getenv("INSTANCE_PATH") or ROOT / "instance"
    ).resolve()
    app = Flask(__name__, instance_path=str(instance), instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        APP_ENV=os.getenv("APP_ENV", "development"),
        DATABASE_BACKEND=os.getenv(
            "DATABASE_BACKEND", "mongo" if os.getenv("MONGO_URI") else "sqlite"
        ),
        DATABASE=str(instance / "creations.sqlite3"),
        MONGO_URI=os.getenv("MONGO_URI", "mongodb://localhost:27017/Users"),
        APP_BASE_URL=os.getenv("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/"),
        AUTH_MAIL_MODE=os.getenv("AUTH_MAIL_MODE", "console"),
        SMTP_HOST=os.getenv("SMTP_HOST", ""),
        SMTP_PORT=int(os.getenv("SMTP_PORT", "587")),
        SMTP_USERNAME=os.getenv("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.getenv("SMTP_PASSWORD", ""),
        SMTP_FROM=os.getenv("SMTP_FROM", ""),
        SMTP_STARTTLS=os.getenv("SMTP_STARTTLS", "true").lower() == "true",
        SESSION_COOKIE_NAME="ic_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        MAX_CONTENT_LENGTH=32768,
        WTF_CSRF_TIME_LIMIT=7200,
        DISPLAY_TIMEZONE="America/Jamaica",
        RESET_TOKEN_SECONDS=1800,
    )
    app.config.update(overrides)
    instance.mkdir(parents=True, exist_ok=True)
    production = app.config["APP_ENV"] == "production"
    if production:
        if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
            raise ValueError("Production requires a random SECRET_KEY of at least 32 characters.")
        if not app.config["APP_BASE_URL"].startswith("https://"):
            raise ValueError("Production APP_BASE_URL must start with https://.")
        if (
            app.config["AUTH_MAIL_MODE"] != "smtp"
            or not app.config["SMTP_HOST"]
            or not app.config["SMTP_FROM"]
        ):
            raise ValueError(
                "Production requires AUTH_MAIL_MODE=smtp, SMTP_HOST and SMTP_FROM for password recovery."
            )
        app.config["SESSION_COOKIE_SECURE"] = True
    if not app.config["SECRET_KEY"]:
        key_path = instance / "secret.key"
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w") as key_file:
                key_file.write(secrets.token_hex(32))
        app.config["SECRET_KEY"] = key_path.read_text().strip()
    if app.config["AUTH_MAIL_MODE"] not in {"console", "smtp"}:
        raise ValueError("AUTH_MAIL_MODE must be console or smtp.")

    if app.config["DATABASE_BACKEND"] == "sqlite":
        store = SQLiteStore(app.config["DATABASE"])
    elif app.config["DATABASE_BACKEND"] == "mongo":
        store = MongoStore(app.config["MONGO_URI"], client=app.config.get("MONGO_CLIENT"))
    else:
        raise ValueError("DATABASE_BACKEND must be sqlite or mongo.")
    app.extensions["store"] = store
    app.extensions["dummy_password_hash"] = generate_password_hash(secrets.token_urlsafe(24))
    if app.testing:
        app.extensions["mail_outbox"] = []
    app.logger.setLevel(logging.INFO)
    csrf.init_app(app)

    @app.before_request
    def load_current_user():
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            user = store.get("users", user_id)
            if user and user.get("auth_version") == session.get("auth_version"):
                g.user = user
            else:
                session.clear()

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        if response.mimetype == "text/html" or g.get("user"):
            response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.context_processor
    def shared_context():
        zone = ZoneInfo(app.config["DISPLAY_TIMEZONE"])
        return {
            "brand": "Innovative Creations",
            "tagline": "Where innovation starts.",
            "current_year": datetime.now(zone).year,
            "today": datetime.now(zone).date().isoformat(),
        }

    @app.template_filter("date_label")
    def date_label(value, with_time=False):
        if not value:
            return "No due date"
        try:
            date = datetime.fromisoformat(value)
            if date.tzinfo:
                date = date.astimezone(ZoneInfo(app.config["DISPLAY_TIMEZONE"]))
            return date.strftime("%b %d, %Y · %I:%M %p" if with_time else "%b %d, %Y").replace(
                " 0", " "
            )
        except (ValueError, TypeError):
            return "—"

    from .auth import auth
    from .web import web

    app.register_blueprint(auth)
    app.register_blueprint(web)

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template(
            "error.html",
            code=400,
            heading="This form has expired",
            message="Reload the page and submit the form again. Your session may have ended.",
        ), 400

    @app.errorhandler(StaleRecord)
    def stale_record(error):
        return render_template(
            "error.html", code=409, heading="There’s a newer version", message=str(error)
        ), 409

    for code, heading, message in (
        (
            400,
            "Something needs a second look",
            "The request could not be understood. Return to the page and try again.",
        ),
        (403, "This space is private", "You don’t have permission to open this page."),
        (
            404,
            "We couldn’t find that page",
            "The link may have changed, or the project may have been deleted.",
        ),
        (
            405,
            "That action isn’t available",
            "Open the page using its link, then use the form to make changes.",
        ),
        (413, "That request is too large", "Shorten the text in your form and try again."),
        (
            500,
            "We hit a small roadblock",
            "Please try again in a moment. Your saved work will be here when you return.",
        ),
    ):

        def handler(error, code=code, heading=heading, message=message):
            return render_template("error.html", code=code, heading=heading, message=message), code

        app.register_error_handler(code, handler)

    @app.get("/health")
    def health():
        try:
            healthy = store.healthy()
        except Exception:
            app.logger.exception("Database health check failed")
            healthy = False
        return jsonify(status="ok" if healthy else "unavailable"), 200 if healthy else 503

    @app.cli.command("seed-demo")
    @click.option("--email", default="creator@example.test", show_default=True)
    @click.password_option(confirmation_prompt=True)
    def seed_demo(email, password):
        """Create an optional demo account, using your own password."""
        from .auth import validate_registration
        from .web import seed_projects

        values = {
            "first_name": "Alex",
            "last_name": "Morgan",
            "username": "creator",
            "email": email,
            "password": password,
            "confirm_password": password,
        }
        values, errors = validate_registration(values)
        if errors:
            raise click.ClickException(" ".join(errors.values()))
        try:
            user = store.create(
                "users",
                {
                    **{k: values[k] for k in ("first_name", "last_name", "username", "email")},
                    "email_key": email.casefold(),
                    "username_key": "creator",
                    "password_hash": generate_password_hash(password),
                    "auth_version": 1,
                    "bio": "Making useful things, one idea at a time.",
                },
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        seed_projects(store, user["id"])
        click.echo(
            f"Demo account ready. Sign in with {values['email']} and the password you chose."
        )

    return app
