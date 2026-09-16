# Tiago's super admin login

Local implementation is ready. **The live account has not been activated or verified by this change.**
The read-only Supabase Admin API check returned HTTP 504. That response does not establish
whether the account exists. No remote database writes, emails, password changes, or deployment were performed.

## What changed

- `/auth/config` returns only the Supabase URL and public key from the backend environment.
  It refuses secret keys and legacy service-role keys. The service key stays server-side.
- Real Supabase password login replaces the fake-token fallback. Old `23e_token` entries
  are removed. Supabase handles stored sessions, OAuth return, refresh, and local logout.
- The server verifies every Bearer token with Supabase Auth. Only an active, trusted
  `company_members.role = platform_admin` record grants platform-wide access.
  The email typed into a form and editable user metadata never grant privileges.
- A platform admin enters the dashboard without customer onboarding and can select
  another company for its leads, dashboard, conversations, and settings.
  The default company is the admin's home company, not an aggregate of all companies.
- Ordinary users cannot select another company's data using `company_id`.

## Remaining trusted provisioning steps

1. In the Supabase project matching backend `SUPABASE_URL`, open Authentication > Users.
   Find **agencia23e@gmail.com** and verify that email ownership is confirmed.
   Copy that exact user's UUID. Do not invent a UUID or mark an unknown identity verified.
   If the account does not exist or is unverified, complete normal account creation and
   ownership verification first. No account creation/email delivery is implemented here.
2. Check database setup. On a fresh project, run `sql/schema.sql`, then
   `sql/migration_001_gestao23e.sql` in SQL Editor. On an existing project, review which
   scripts have already been applied before running them; do not replace existing tables.
   The application now requires the migration's `company_members` table.
3. Open `sql/provision_tiago_platform_admin.sql`. Replace
   `REPLACE_WITH_VERIFIED_AUTH_USER_UUID` with the UUID from step 1. Run the script as
   the trusted database administrator in SQL Editor. It verifies the UUID, exact email,
   and confirmation state before granting access. It aligns the home company's legacy
   organization ID, assigns `platform_admin`, and marks only Tiago's profile onboarded.
   If conflicting home-company IDs exist, the transaction stops for review.
4. Keep the backend `.env` values configured: `SUPABASE_URL`, `SUPABASE_PUBLIC_KEY`
   (publishable or legacy anon key), and `SUPABASE_SERVICE_ROLE_KEY` (backend only).
   The local `/auth/config` check passed with the existing environment without exposing
   the private key. This does not prove the remote keys remain valid.
5. Start locally from this folder in PowerShell:

   ```powershell
   .\.venv\Scripts\python.exe wsgi.py
   ```

   Open the HTTP address printed by Flask (normally `http://127.0.0.1:5000/`).
   Do not open `public/index.html` directly. Sign in with Tiago's existing Supabase
   email/password. No password was created or changed by this implementation.
6. For Google login, enable/configure the Google provider in Supabase and allow the
   exact application root URL in Auth redirect settings. For local testing use the
   same host consistently (`127.0.0.1` or `localhost`). Google login is optional;
   password login does not depend on Google setup.
7. Confirm the header says **Super admin (23e growth)**, `/api/v1/me` returns
   `platform_admin`, and the company selector lists customer companies. Test selection
   with an existing customer company. Confirm an ordinary account cannot read or edit
   a different company's records. Do not paste access tokens into messages.

No public endpoint can grant this role. To revoke Tiago's global role, the trusted
administrator must deactivate or downgrade his active `platform_admin` membership(s).
Role checks happen on every API request.

## Validation

Run the existing and added backend tests:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
node --test tests/test_frontend_auth.cjs
```

Tests cover public config, secret-key rejection, server-side admin scope, tenant isolation,
metadata spoofing, restored sessions, refreshed tokens, Google redirect/error handling,
and logout. Auth and database calls are simulated: real credentials, browser/CDN loading,
Google configuration, and SQL execution still require the live checks above.

Supabase API references used:
- https://supabase.com/docs/reference/javascript/auth-getsession
- https://supabase.com/docs/reference/javascript/auth-onauthstatechange
- https://supabase.com/docs/reference/javascript/auth-signinwithoauth
