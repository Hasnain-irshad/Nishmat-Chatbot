# Setup — getting the app running locally

Follow these in order. Steps 1–4 are one-time; step 5 is what you run every day.

---

## 1. Create the Supabase project

1. Go to <https://supabase.com/dashboard> → **New project**.
2. Pick a region close to the client (Europe or US East are both fine).
3. Save the database password somewhere safe — you cannot see it again.

Once the project is ready, open **Project Settings → API** and copy:

| Value | Where it goes |
|---|---|
| Project URL | `NEXT_PUBLIC_SUPABASE_URL` **and** `SUPABASE_URL` |
| `anon` `public` key | `NEXT_PUBLIC_SUPABASE_ANON_KEY` |
| `service_role` `secret` key | `SUPABASE_SERVICE_ROLE_KEY` — **backend only, never the frontend** |

---

## 2. Apply the database schema

Open **SQL Editor** in the Supabase dashboard and run these two files, in order:

1. `backend/migrations/0001_init.sql` — tables, enums, indexes, RLS policies, the
   hybrid search function, and the private storage bucket.
2. `backend/migrations/0002_seed_template.sql` — the series and the default
   "Nishmat — A Journey of Praise" lesson template.

Paste the whole file, press **Run**, and confirm it reports success before
moving to the next one.

> `0001_init.sql` enables the `vector` extension. If Supabase complains that it
> is not available, enable **pgvector** first under *Database → Extensions*.

---

## 3. Turn on Google sign-in

1. **Google Cloud Console** → *APIs & Services → Credentials* → **Create
   credentials → OAuth client ID → Web application**.
2. Under **Authorised redirect URIs**, add:
   ```
   https://<your-project-ref>.supabase.co/auth/v1/callback
   ```
3. Copy the Client ID and Client Secret.
4. In Supabase: **Authentication → Providers → Google** → paste them → **Save**.
5. In Supabase: **Authentication → URL Configuration**:
   - *Site URL*: `http://localhost:3000` (change to the real domain at launch)
   - *Redirect URLs*: add `http://localhost:3000/auth/callback`

Email/password sign-in works out of the box. While developing, you may want to
turn **off** *Authentication → Providers → Email → Confirm email* so test
accounts work immediately.

---

## 4. Configure environment variables

```bash
cd frontend
cp .env.example .env.local
```

Fill in `.env.local`:

```bash
NEXT_PUBLIC_SUPABASE_URL=https://<your-project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

**Never** put `OPENAI_API_KEY` or `SUPABASE_SERVICE_ROLE_KEY` in this file. The
frontend bundle is public — anything in it is readable by anyone.

---

## 5. Run it

```bash
cd frontend
npm install      # first time only
npm run dev
```

Open <http://localhost:3000>.

---

## 6. Make yourself an admin

Sign up through the UI first (Google or email), then run this in the Supabase
**SQL Editor**:

```sql
update profiles
set role = 'admin'
where email = 'your@email.com';
```

Sign out and back in. You will land on `/admin` instead of `/app`.

> Role can only be changed this way, or later from the admin panel. There is no
> API a person can call to promote themselves — the signup trigger always
> writes `'user'`, and RLS blocks any attempt to change it.

---

## Verifying it works

| Check | Expected |
|---|---|
| Visit `/` | Landing page with the star field and emblem |
| Visit `/app` while signed out | Redirects to `/sign-in?next=/app` |
| Visit `/admin` as a normal user | Redirects to `/app` |
| Sign in with Google | Lands on `/app`, or `/admin` if you are an admin |
| `npm run build` | Completes with no errors |

---

## Troubleshooting

**"Invalid API key" on any page**
`.env.local` is missing or has a stale key. Restart `npm run dev` after editing
it — Next.js only reads env files at startup.

**Google sign-in returns to the landing page**
The redirect URL in Supabase does not match. It must be exactly
`http://localhost:3000/auth/callback`, and the Google console must have the
Supabase callback (`.../auth/v1/callback`), not the app one.

**"relation does not exist" errors**
`0001_init.sql` did not finish. Re-run it and read the error at the point it
stopped — usually the `vector` extension.

**Signing up creates a user but `/app` shows nothing**
The `handle_new_user` trigger did not fire, so there is no `profiles` row.
Confirm the trigger exists:
```sql
select * from pg_trigger where tgname = 'on_auth_user_created';
```

**Everything loads but no lessons appear**
Expected — the corpus has not been imported yet. That is the ingestion script
in Phase 1b.
