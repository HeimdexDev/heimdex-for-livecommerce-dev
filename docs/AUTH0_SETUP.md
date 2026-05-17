# Auth0 Setup for Heimdex

## 1. Create Auth0 Resources

### SPA Application

1. Auth0 Dashboard → Applications → Create Application
2. Type: **Single Page Application**
3. Settings:

| Field | Staging | Production |
|-------|---------|------------|
| Allowed Callback URLs | `https://*.app.heimdexdemo.dev/auth/callback` | `https://*.app.heimdex.co/auth/callback` |
| Allowed Logout URLs | `https://*.app.heimdexdemo.dev` | `https://*.app.heimdex.co` |
| Allowed Web Origins | `https://*.app.heimdexdemo.dev` | `https://*.app.heimdex.co` |

For local testing (staging app only), add `http://localhost:3000/auth/callback` and `http://localhost:3000`.

4. Advanced Settings → Grant Types: Ensure **Authorization Code** is enabled (PKCE is automatic).

### API (Resource Server)

1. Auth0 Dashboard → Applications → APIs → Create API
2. Settings:

| Field | Staging | Production |
|-------|---------|------------|
| Name | heimdex api | Heimdex |
| Identifier (audience) | `https://api.staging.heimdexdemo.dev` | `https://api.heimdex.co` |
| Signing Algorithm | RS256 | RS256 |

### Auth0 Organizations (Recommended)

Auth0 Organizations provide built-in multi-tenant isolation. When enabled for an org,
the access token automatically includes a top-level `org_id` claim — no custom Action needed.

1. Auth0 Dashboard → Organizations → Create Organization
2. Set the Organization ID (e.g., `org_abc123`)
3. Enable the SPA application for this Organization
4. Add members to the Organization

Then store the Auth0 Organization ID on the Heimdex org record:

```sql
UPDATE orgs SET auth0_org_id = 'org_abc123' WHERE slug = 'acme';
```

The backend enforces binding: if an org has `auth0_org_id` set, every Auth0 token
accessing that org's subdomain **must** contain a matching `org_id` claim. Tokens
without `org_id`, or with a different `org_id`, are rejected with 403.

Orgs without `auth0_org_id` (legacy) continue to work — the backend falls back to
comparing the token's `org_id` (if present) against the internal UUID.

### (Optional) Custom Organization Claim

If you need a custom claim instead of (or in addition to) Auth0 Organizations:

```javascript
// Auth0 Dashboard → Actions → Flows → Post Login → Custom Action
exports.onExecutePostLogin = async (event, api) => {
  if (event.organization) {
    api.accessToken.setCustomClaim(
      'https://heimdex.io/org_id',
      event.organization.name
    );
  }
};
```

## 2. Environment Variables

### Frontend (services/web)

```bash
NEXT_PUBLIC_AUTH0_ENABLED=true
NEXT_PUBLIC_AUTH0_DOMAIN=heimdex.jp.auth0.com
NEXT_PUBLIC_AUTH0_CLIENT_ID=<SPA client ID from Auth0 Dashboard>
NEXT_PUBLIC_AUTH0_AUDIENCE=<audience matching your Auth0 API identifier>
```

### Backend (services/api)

```bash
AUTH0_ENABLED=true
AUTH0_DOMAIN=heimdex.jp.auth0.com
AUTH0_AUDIENCE=<audience matching your Auth0 API identifier>
AUTH0_ORG_CLAIM=https://heimdex.io/org_id   # optional
ENVIRONMENT=staging  # or production
```

Note: `AUTH0_ALGORITHMS` defaults to `RS256` and does not need to be set.

## 3. Auth Flow

```
Browser → /login → "Continue with Heimdex" button
    ↓
Auth0 Universal Login (Authorization Code + PKCE)
    ↓
Redirect to /auth/callback?code=...&state=...
    ↓
@auth0/auth0-react handles code exchange (token stored in memory)
    ↓
Redirect to /
    ↓
API calls include Authorization: Bearer <access_token>
    ↓
Backend validates RS256 JWT via JWKS (cached 1h)
```

## 4. Backend JWT Verification

The backend fetches JWKS from `https://{AUTH0_DOMAIN}/.well-known/jwks.json` and verifies:
- Signature (RS256 via public key matching `kid`)
- Issuer == `https://{AUTH0_DOMAIN}/`
- Audience includes `AUTH0_AUDIENCE`
- Token is not expired

On first request after startup (or cache expiry), there is a one-time JWKS fetch. Keys are cached for 1 hour.

## 5. User Linking

Users must exist in the Heimdex database before they can log in via Auth0. On first Auth0 login:
1. Backend looks up user by `auth0_sub` (Auth0 subject ID)
2. If not found and email is verified, auto-links by email
3. If still not found → 401 (contact org admin)

Seed users via: `docker compose exec api python -m app.seed`

## 6. Local Testing

```bash
# 1. Set Auth0 env vars in docker-compose.yml or .env
# 2. Build and start
docker compose build api web
docker compose up -d api web

# 3. Seed database
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed

# 4. Open browser
# Auth0 mode: navigating to http://localhost:3000/login shows "Continue with Heimdex"
# Dev mode:   set AUTH0_ENABLED=false to use email/password form
```

## 7. Wildcard Subdomains

Heimdex uses subdomain-based multi-tenancy: `{org}.app.heimdexdemo.dev`.

Auth0 supports wildcard URLs in callback/origins configuration. Ensure you enter them with `*` prefix (e.g., `https://*.app.heimdexdemo.dev/auth/callback`).

Tenancy is ALWAYS derived from the Host header, even when Auth0 is enabled. The optional `AUTH0_ORG_CLAIM` is for additional validation, not primary routing.

## 8. Startup Validation (Fail-Closed)

When `AUTH0_ENABLED=true`, the API performs a startup check to ensure **every** org in the database has an `auth0_org_id` bound. If any org is missing its Auth0 binding, the API refuses to start.

```
FATAL: AUTH0_ENABLED=true but 1 org(s) have no auth0_org_id:

  - acme

Every org must be bound to an Auth0 Organization.
Run: UPDATE orgs SET auth0_org_id = '<org_id>' WHERE slug = '<slug>';
```

**Why fail-closed?** An org without `auth0_org_id` would bypass the Auth0 Organizations binding check, allowing any authenticated user to access that org's data — regardless of their Auth0 Organization membership.

When `AUTH0_ENABLED=false` (local development), this check is skipped entirely.

## 9. Adding a New Organization

To onboard a new customer organization:

### Step 1: Create Auth0 Organization

1. Auth0 Dashboard → Organizations → Create Organization
2. Set a display name and note the generated Organization ID (e.g., `org_XYZ789`)
3. Go to the new Organization → Applications → Enable your SPA application
4. Add initial members to the Organization

### Step 2: Create Heimdex Org Record

Insert the org into the database with the Auth0 Organization ID:

```sql
INSERT INTO orgs (id, slug, name, auth0_org_id, created_at, updated_at)
VALUES (
  gen_random_uuid(),
  'acme',                   -- subdomain: acme.app.heimdexdemo.dev
  'Acme Corporation',
  'org_XYZ789',             -- from Auth0 Dashboard
  now(),
  now()
);
```

Or create a new Alembic migration (recommended for reproducibility):

```bash
cd services/api
alembic revision -m "add_acme_org"
# Edit the migration to INSERT the org record
alembic upgrade head
```

### Step 3: Seed Users

Add users who should have access to the new org:

```sql
INSERT INTO users (id, org_id, email, name, role, created_at, updated_at)
VALUES (
  gen_random_uuid(),
  (SELECT id FROM orgs WHERE slug = 'acme'),
  'admin@acme.com',
  'Admin User',
  'admin',
  now(),
  now()
);
```

### Step 4: Configure DNS (if needed)

The wildcard DNS record `*.app.heimdexdemo.dev` already routes all subdomains, so no DNS changes are needed for new orgs on the same base domain.

### Step 5: Verify

1. Restart the API — startup validation should pass (all orgs have `auth0_org_id`)
2. Navigate to `https://acme.app.heimdexdemo.dev`
3. Log in via Auth0 — the user should be prompted to select the "Acme Corporation" organization

## 10. Migration Reference

| Migration | Description |
|-----------|-------------|
| 001 | Create orgs table with `slug` (UNIQUE, indexed) |
| 002 | Add `auth0_sub` column to users |
| 007 | Add `auth0_org_id` column to orgs (UNIQUE index) |
| 008 | Add `(org_id, email)` unique constraint on users |
| 009 | Set `auth0_org_id = 'org_V0Y81197qiMgjFFX'` for devorg (staging) |
