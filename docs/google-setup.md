# Connect Gmail, Calendar and Sheets

In the open-source edition each business uses **its own Google OAuth app**. It's free, takes
about 10 minutes once, and means your data goes only between your computer and Google: no
M3allema server is involved.

## 1. Create a Google Cloud project

1. Open <https://console.cloud.google.com/> and sign in with the Google account M3allema
   should use.
2. Click the project picker at the top → **New project** → name it `m3allema` → **Create**.

## 2. Turn on the APIs

In the new project, open **APIs & Services → Library**, then search for and **Enable** each:

- **Gmail API**
- **Google Calendar API**
- **Google Sheets API**

## 3. Set up the consent screen

1. **APIs & Services → OAuth consent screen** (or **Google Auth Platform → Branding**).
2. User type: **External** → fill in an app name (`M3allema`) and your email.
3. Under **Audience → Test users**, add your own Gmail address.

The app stays in *Testing* mode. That's fine for your own account; you never need Google's
verification for personal use.

## 4. Create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
2. Application type: **Desktop app** → **Create**.
3. Click **Download JSON**. Keep this file private.

## 5. Connect M3allema

From your workspace folder:

```bash
m3allema google connect --client-secret path/to/client_secret.json
```

Your browser opens Google's consent page. Choose your account and allow access. Google warns
that the app is unverified because it's your own app: click **Continue**.

Then enable the tools in `config.yaml`:

```yaml
builtin_tools: [files, excel, docs, web, gmail, calendar, sheets]
```

Check it with `m3allema google status`.

## What M3allema can do, and what needs your approval

| Tool | Risk | Default policy |
|---|---|---|
| Search and read email, list events, read sheets | read | runs on its own |
| Save a draft, archive an email, append rows to a sheet | write | asks you |
| **Send an email, create an event with invitations, overwrite sheet cells** | external | asks you |

Tighten or relax this in `policy.yaml`, for example `"gmail__send_email": deny`.

## Where the sign-in is kept

- The OAuth client file is copied to `.m3allema/google_client_secret.json`.
- The sign-in token is **encrypted** in `.m3allema/google_token.enc`. The key is
  `M3ALLEMA_SECRET_KEY` in your workspace `.env`, generated on first connect.
- Neither is ever shown to the AI model. Never commit `.env` or `.m3allema/`.

## Disconnect

```bash
m3allema google disconnect
```

Then remove the app's access at <https://myaccount.google.com/permissions>.

## Troubleshooting

| Problem | Fix |
|---|---|
| `access_denied` in the browser | Add your address under **Test users** (step 3) |
| `Google rejected the stored sign-in` | Run `m3allema google connect` again. Testing-mode tokens can expire after 7 days |
| A Google tool is missing | Add it to `builtin_tools` in `config.yaml` |
