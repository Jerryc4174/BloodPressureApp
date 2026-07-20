# Blood Pressure App

## Database Connection

This app reads its PostgreSQL connection string from `DATABASE_URL`.

For local development, you can keep the value in `.streamlit/secrets.toml`:

```toml
DATABASE_URL = "postgresql://postgres:<password>@<host>:5432/postgres"
```

For Streamlit Cloud, use the Supabase **Session pooler** connection string instead of the direct database host. This avoids DNS and IPv6 issues on cloud hosts.

In Supabase:

1. Open your project dashboard.
2. Click **Connect**.
3. Choose **Session pooler**.
4. Copy the connection string that looks like `postgres://postgres.<project-ref>:[password]@aws-<region>.pooler.supabase.com:5432/postgres`.

In Streamlit Cloud:

1. Open your app settings.
2. Add the copied value as the `DATABASE_URL` secret.
3. Redeploy the app.

If you prefer, you can also store the pooler URL under `DATABASE_URL_POOLER` or `SUPABASE_POOLER_URL`, but `DATABASE_URL` is the simplest option for this app.
