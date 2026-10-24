# Innovative Creations

A complete Flask application built from the supplied `pyprojects` starter. It keeps the Innovative Creations identity and original animated background, and adds a working personal project workspace.

## Start here

Install **Python 3.11 or newer**. Unzip the project and open a terminal in the `innovative-creations` folder.

**macOS or Linux:**

```sh
sh start.sh
```

**Windows:** double-click `start.bat`, or run it in Command Prompt.

Open **http://127.0.0.1:5000** and choose **Get started** to create your account. The first start installs dependencies and needs an internet connection. No Node installation or MongoDB server is required to run the application.

For a manual setup:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

On Windows, use `py -3 -m venv .venv` and `.venv\Scripts\activate` instead of the first two commands.

If port 5000 is already in use, change `PORT` to `5001` and `APP_BASE_URL` to `http://127.0.0.1:5001` in a `.env` file, then restart. On macOS, AirPlay Receiver can use port 5000.

## What works

- Public home page with the original, optimized background video, pause/play control and reduced-motion support.
- Account registration, email/username login, optional persistent sign-in and logout.
- Passwords stored as salted scrypt hashes; no plaintext password storage or profile display.
- Password recovery with expiring, single-use links and optional SMTP delivery.
- Overview with real project counts, checklist progress, recent projects and activity.
- Create, view, edit, search, filter, paginate and delete your own projects.
- Project categories, status, descriptions, optional due dates and up to 100 checklist items per project.
- Editable profile, password changes, account export and permanent account deletion.
- Ownership checks, CSRF protection, database-backed sign-in limits, escaped output and stale-edit protection.
- Responsive navigation, keyboard-friendly forms, labeled controls, confirmation dialogs and useful error pages.
- SQLite storage by default, a MongoDB adapter, automated tests and a health endpoint.

There are no shared workspaces, public project links, payments or administrator dashboard. Each account manages its own projects. These features were not present in the starter and are not simulated.

## Your local data

The app creates `instance/creations.sqlite3` and `instance/secret.key` on first start. Keep this folder to retain accounts, projects and session signing across restarts. Do not publish it or commit it to Git.

To back up a running SQLite installation consistently, use Python's SQLite backup API:

```sh
python -c "import sqlite3; src=sqlite3.connect('instance/creations.sqlite3'); dst=sqlite3.connect('backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
```

Also keep the signing key separately in a private location. Workspace export in **My profile** downloads one account's content as JSON; it is a readable export, not an automatic database restore format.

## Optional configuration

Copy `.env.example` to `.env`. Environment variables override values in the file. The defaults work locally without creating this file.

| Setting | Purpose |
| --- | --- |
| `DATABASE_BACKEND` | `sqlite` (default) or `mongo` |
| `MONGO_URI` | MongoDB connection string including a database name |
| `SECRET_KEY` | Session and reset-token signing key; generated locally if blank |
| `APP_BASE_URL` | Address used in recovery links; update it when changing ports or hosts |
| `AUTH_MAIL_MODE` | `console` locally, or `smtp` for email |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM` | Email server, port and sender |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Optional email credentials |
| `SMTP_STARTTLS` | `true` by default for SMTP STARTTLS |
| `APP_ENV` | `development` (default) or `production` |
| `INSTANCE_PATH` | Optional absolute location for local data |

Display dates use **America/Jamaica**. Database timestamps use UTC. The `tzdata` dependency provides timezone information on Windows too.

### MongoDB

Start your own MongoDB service, then set:

```dotenv
DATABASE_BACKEND=mongo
MONGO_URI=mongodb://localhost:27017/Users
```

Restart the app. It creates `users`, `projects`, `tasks`, `activity` and `throttles` collections and their indexes. Existing collections such as the starter's `Agents` collection are left alone. Changing backends selects a different database; it does **not** migrate data between them. No database credentials or user records were included in the supplied archive.

### Password recovery

Locally, choose **Forgot password?**, submit your account email, and find the reset link in the app's terminal. Links expire after 30 minutes and become invalid when the password is changed. Only local development mode prints recovery links.

For email delivery, set `AUTH_MAIL_MODE=smtp` and configure your own SMTP service. The built-in transport supports SMTP with STARTTLS, normally on port 587. Use a provider-supported application password when required. No external email account is preconfigured.

### Optional example workspace

After activating your environment:

```sh
flask --app app seed-demo --email creator@example.test
```

Choose a password when prompted. The command creates a `creator` account with four sample projects and checklists. It refuses to overwrite an existing email or username. No fixed demo password is shipped.

## Run the tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check innovative app.py tests
```

To check a running local server without installing Node.js:

```sh
python tests/http_smoke.py --base-url http://127.0.0.1:5000
```

This creates a temporary account, exercises the main flows through HTTP, and deletes that account on success.

The application tests run against SQLite and a `mongomock` MongoDB adapter. They include real CSRF tokens, authentication, recovery, ownership boundaries, persistence and stale edits. The mock tests do not verify a live MongoDB server or its network/TLS settings.

Optional browser checks require Node.js 20 or newer and Playwright. Start the local app in one terminal; in another:

```sh
npm install
npx playwright install chromium
npm run test:browser
```

Use `BASE_URL=http://127.0.0.1:5001` if the app runs on another port. The browser checks create and then delete a temporary test account. They capture screenshots and an accessibility report under `browser-artifacts/`. Run them against a local development instance.

## Hosting

For a hosted installation, use Waitress behind an HTTPS reverse proxy:

```sh
waitress-serve --listen=127.0.0.1:8000 app:app
```

Set `APP_ENV=production`, an HTTPS `APP_BASE_URL`, a random `SECRET_KEY` of at least 32 characters, `AUTH_MAIL_MODE=smtp`, `SMTP_HOST` and `SMTP_FROM`. Production mode refuses to start without these settings, enables secure cookies and sends HSTS. Keep the database on persistent storage and arrange backups. The development server started by `python app.py` is for local use.

The application does not trust forwarded IP headers by default. If you configure a reverse proxy, the sign-in IP limit will see the proxy's address until you explicitly configure a trusted proxy setup for your deployment.

For a local Docker installation:

```sh
docker compose up --build
```

It uses Waitress and a persistent named volume. The provided Compose file binds to localhost. MongoDB inside a container needs a reachable URI; `localhost` inside the container is the container itself. Docker packaging is provided but requires Docker to be installed on your machine.

## Project layout

```text
app.py                 Local and WSGI entry point
innovative/__init__.py  Configuration, factory, sessions, errors, health and CLI
innovative/auth.py      Accounts, sign-in and password recovery
innovative/store.py     SQLite and MongoDB repositories
innovative/web.py       Projects, checklists, profile and exports
innovative/templates/   Jinja pages and reusable UI
innovative/static/      Local styles, scripts, icons and optimized original video
tests/                 Application, configuration and optional browser checks
```

The old Windows/Python 3.7 environment, generated logs, corrupted home template and unused files have been replaced with source files and installable dependencies. The original 4K background was reduced to a 720p, muted clip for faster loading. Original media remains user-supplied; no additional rights are granted by this project.

See [TESTING.md](TESTING.md) for the checks completed with this build and the environment-dependent checks still to run.

Reference documentation: [Flask](https://flask.palletsprojects.com/en/stable/), [Flask-WTF](https://flask-wtf.readthedocs.io/en/latest/csrf/), [Werkzeug password helpers](https://werkzeug.palletsprojects.com/en/stable/utils/#module-werkzeug.security), [PyMongo](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/).
# Innovative-Creations-Project-Management-
