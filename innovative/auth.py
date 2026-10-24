"""Registration, sign-in, recovery and session helpers."""

from email.message import EmailMessage
from functools import wraps
import hashlib
import re
import smtplib
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .store import DuplicateUser

auth = Blueprint("auth", __name__)
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME = re.compile(r"^[A-Za-z0-9_]{3,24}$")


def store():
    return current_app.extensions["store"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def safe_next(value):
    if not value or len(value) > 500 or "\\" in value:
        return url_for("web.dashboard")
    try:
        parsed = urlsplit(value)
    except ValueError:
        return url_for("web.dashboard")
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return url_for("web.dashboard")
    return value


def start_session(user, remember=False):
    session.clear()
    session["user_id"] = user["id"]
    session["auth_version"] = user["auth_version"]
    session.permanent = remember


def validate_registration(raw):
    values = {
        key: raw.get(key, "").strip() for key in ("first_name", "last_name", "username", "email")
    }
    errors = {}
    for key, label in (("first_name", "First name"), ("last_name", "Last name")):
        if not 1 <= len(values[key]) <= 50:
            errors[key] = f"{label} must be between 1 and 50 characters."
    if not USERNAME.fullmatch(values["username"]):
        errors["username"] = "Use 3–24 letters, numbers or underscores."
    if len(values["email"]) > 254 or not EMAIL.fullmatch(values["email"]):
        errors["email"] = "Enter a valid email address."
    if not 12 <= len(raw.get("password", "")) <= 128:
        errors["password"] = "Use 12–128 characters. A memorable passphrase works well."
    if raw.get("confirm_password") != raw.get("password"):
        errors["confirm_password"] = "The passwords don’t match."
    return values, errors


def throttle_key(scope, identity=""):
    # X-Forwarded-For is intentionally not trusted without an explicitly configured proxy.
    return hashlib.sha256(
        f"{scope}:{request.remote_addr}:{identity.casefold()}".encode()
    ).hexdigest()


def limited(scope, identity="", limit=8, seconds=900):
    key = throttle_key(scope, identity)
    wait = store().throttle(key, limit, seconds)
    return key, wait


def too_many(template, values, wait):
    response = current_app.make_response(
        (
            render_template(
                template,
                values=values,
                errors={"form": "Too many attempts. Please wait a few minutes and try again."},
            ),
            429,
        )
    )
    response.headers["Retry-After"] = str(wait)
    return response


@auth.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("web.dashboard"))
    values, errors = {}, {}
    if request.method == "POST":
        values, errors = validate_registration(request.form)
        _, wait = limited("register", limit=8, seconds=3600)
        if wait:
            return too_many("register.html", values, wait)
        if not errors:
            try:
                user = store().create(
                    "users",
                    {
                        **values,
                        "email_key": values["email"].casefold(),
                        "username_key": values["username"].casefold(),
                        "password_hash": generate_password_hash(request.form["password"]),
                        "auth_version": 1,
                        "bio": "",
                    },
                )
            except DuplicateUser as exc:
                errors["form"] = str(exc)
            else:
                start_session(user)
                flash("Your workspace is ready. Let’s make something great.", "success")
                return redirect(url_for("web.dashboard"))
    return render_template("register.html", values=values, errors=errors), 400 if errors else 200


@auth.route("/send", methods=["GET", "POST"])
@auth.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("web.dashboard"))
    values = {
        "identity": request.form.get("identity", request.form.get("email", "")).strip(),
        "next": request.form.get("next", request.args.get("next", "")),
    }
    errors = {}
    if request.method == "POST":
        identity = values["identity"].casefold()[:254]
        key, wait = limited("login", identity)
        _, global_wait = limited("login-ip", limit=40)
        if wait or global_wait:
            return too_many("login.html", values, max(wait, global_wait))
        users = store().find(
            "users", **({"email_key": identity} if "@" in identity else {"username_key": identity})
        )
        user = users[0] if users else None
        password = request.form.get("password", request.form.get("pwd", ""))
        valid = check_password_hash(
            user["password_hash"] if user else current_app.extensions["dummy_password_hash"],
            password[:128],
        )
        if user and valid and len(password) <= 128:
            store().clear_throttle(key)
            start_session(user, request.form.get("remember") == "on")
            flash(f"Welcome back, {user['first_name']}.", "success")
            return redirect(safe_next(values["next"]))
        errors["form"] = "The email or username and password don’t match."
    return render_template("login.html", values=values, errors=errors), 400 if errors else 200


@auth.post("/logout")
@login_required
def logout():
    session.clear()
    flash("You’re signed out. See you next time.", "success")
    return redirect(url_for("web.index"))


def reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="ic-password-reset-v1")


def issue_reset(user):
    token = reset_serializer().dumps({"id": user["id"], "auth_version": user["auth_version"]})
    link = current_app.config["APP_BASE_URL"] + url_for("auth.reset_password", token=token)
    message = f"Hello {user['first_name']},\n\nChoose a new Innovative Creations password:\n{link}\n\nThis link expires in 30 minutes and can be used once. If you didn’t request it, you can ignore this message.\n"
    if current_app.testing:
        current_app.extensions["mail_outbox"].append(
            {"to": user["email"], "link": link, "token": token}
        )
        return
    if current_app.config["AUTH_MAIL_MODE"] == "console":
        current_app.logger.info("LOCAL PASSWORD RESET for %s\n%s", user["email"], message)
        return
    email = EmailMessage()
    email["Subject"] = "Reset your Innovative Creations password"
    email["From"] = current_app.config["SMTP_FROM"]
    email["To"] = user["email"]
    email.set_content(message)
    with smtplib.SMTP(
        current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"], timeout=15
    ) as smtp:
        if current_app.config["SMTP_STARTTLS"]:
            import ssl

            smtp.starttls(context=ssl.create_default_context())
        if current_app.config["SMTP_USERNAME"]:
            smtp.login(current_app.config["SMTP_USERNAME"], current_app.config["SMTP_PASSWORD"])
        smtp.send_message(email)


@auth.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    values, errors = {}, {}
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        values["email"] = email
        _, wait = limited("reset", limit=5, seconds=3600)
        if wait:
            return too_many("forgot_password.html", values, wait)
        if not EMAIL.fullmatch(email) or len(email) > 254:
            errors["email"] = "Enter a valid email address."
        else:
            users = store().find("users", email_key=email.casefold())
            if users:
                try:
                    issue_reset(users[0])
                except (OSError, smtplib.SMTPException):
                    current_app.logger.exception("Password recovery message could not be delivered")
            return render_template("forgot_password.html", values={}, errors={}, sent=True)
    return render_template(
        "forgot_password.html", values=values, errors=errors
    ), 400 if errors else 200


def reset_user(token):
    try:
        payload = reset_serializer().loads(token, max_age=current_app.config["RESET_TOKEN_SECONDS"])
        user = store().get("users", payload.get("id", ""))
        if user and payload.get("auth_version") == user["auth_version"]:
            return user
    except (BadSignature, SignatureExpired, AttributeError):
        pass
    return None


@auth.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = reset_user(token)
    if user is None:
        return render_template(
            "error.html",
            code=400,
            heading="This reset link has expired",
            message="Request a new password reset link to continue.",
            recovery=True,
        ), 400
    errors = {}
    if request.method == "POST":
        password = request.form.get("password", "")
        if not 12 <= len(password) <= 128:
            errors["password"] = "Use 12–128 characters."
        if password != request.form.get("confirm_password"):
            errors["confirm_password"] = "The passwords don’t match."
        if not errors:
            store().update(
                "users",
                user["id"],
                {
                    "password_hash": generate_password_hash(password),
                    "auth_version": user["auth_version"] + 1,
                },
                expected_version=user["version"],
            )
            session.clear()
            flash("Your password has been updated. Sign in with your new password.", "success")
            return redirect(url_for("auth.login"))
    return render_template("reset_password.html", values={}, errors=errors), 400 if errors else 200
