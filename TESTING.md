# Validation of the completed project

Verified on Python 3.12 with the runtime versions pinned in `requirements.txt`.

| Check | Result |
| --- | --- |
| Application and configuration tests | **69 passed**, zero failures, errors or skips |
| Real HTTP checks through Waitress | **6 passed** |
| Python lint checks | Passed |
| Python formatting checks | Passed |
| JavaScript syntax: application and browser checks | Passed |
| POSIX start script syntax | Passed |
| Clean dependency install and template rendering | Passed: 12 pages and 16 internal links |

The application tests exercise both the SQLite repository and MongoDB adapter, using `mongomock` for MongoDB. Coverage includes form validation, real CSRF tokens, hashed passwords, session invalidation, generic password recovery responses, single-use and expired reset links, email change invalidation, sign-in limits, private project boundaries, checklist changes, search, pagination, stale edits, account exports, deletion, persistence, production configuration and health checks.

The real HTTP check starts the application with Waitress and exercises its database health, home page, account registration, session cookie, project creation, checklist updates, credential-free export, logout, sign-in to saved data and cleanup of its temporary account.

## Environment-dependent checks

- **Browser and visual checks were not completed here.** The local browser runtime could not launch, and the remote browser could not access the local application. An optional Playwright workflow is included in `tests/browser-smoke.cjs`; it checks desktop/mobile pages, interactions, overflow, browser errors and axe accessibility findings. Run it on your computer before relying on a particular browser or claiming accessibility compliance.
- **Live MongoDB was not available.** Its adapter passed the mock-backed tests. Verify your own MongoDB server, connection string, credentials and indexes when enabling this backend.
- **External SMTP delivery was not exercised.** Recovery was tested with the test outbox. Configure your provider and verify delivery before hosting the app.
- **Docker and Windows launch scripts were not executed in this environment.** Docker packaging and a Windows launcher are included for those environments.

No user credentials, live databases, generated signing keys or test accounts are included in the ZIP.
