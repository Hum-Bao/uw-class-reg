# uw-class-reg

Command-line tool to help UW students view registration data, register classes, schedule registration, and trigger registration from email alerts.

## What It Can Do

- View current and current-year registration details.
- Register classes from MyPlan or by manual SLN entry.
- Schedule registration to run at a specific time.
- Listen for Notify.UW-style emails, extract an SLN, and register automatically.
- Manage existing registration (drop or swap classes).

## Requirements

- Python 3.10 or newer
- Google Chrome

## Quick Start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the project root.
3. Add your UW credentials:

```env
UW_USERNAME=your_uw_netid
UW_PASSWORD=your_uw_password
```

4. Run the app:

```bash
python main.py
```

## Configuration

### Required for Everyone

- `UW_USERNAME`
- `UW_PASSWORD`

### Email Trigger Modes

Choose one mode for email-triggered registration.

#### Gmail API Mode

Use this when your mailbox is Gmail and you want direct Gmail API access.

Required:

- `IMAP_USERNAME` (your Gmail address)
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Optional:

- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_TOKEN_ENDPOINT` (defaults to `https://oauth2.googleapis.com/token`)

#### IMAP Password Mode

Use this for providers that support IMAP login with username and password (or app password).

Required:

- `IMAP_SERVER`
- `IMAP_USERNAME`
- `IMAP_PASSWORD`

Optional:

- `IMAP_AUTH_MODE=password`

Common IMAP servers:

- Gmail: `imap.gmail.com`
- Outlook: `outlook.office365.com`

#### IMAP OAuth2 Mode (Google)

Use this when connecting to IMAP with Google OAuth instead of IMAP password auth.

Required:

- `IMAP_SERVER`
- `IMAP_USERNAME`
- `IMAP_AUTH_MODE=oauth2`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Optional:

- `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_TOKEN_ENDPOINT` (defaults to `https://oauth2.googleapis.com/token`)

## Google OAuth Setup

`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` come from Google Cloud.

1. Go to https://console.cloud.google.com/ and create or select a project.
2. Open APIs & Services > Library and enable Gmail API.
3. Open APIs & Services > OAuth consent screen and configure the app.
4. Add scope `https://mail.google.com/`.
5. Add your account as a test user while testing.
6. Open APIs & Services > Credentials > Create Credentials > OAuth client ID.
7. Choose Desktop app.
8. Copy the generated values into your `.env`:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
```

## Menu Overview

Main menu options:

1. View
2. Register
3. Schedule
4. Manage
5. Exit

Schedule includes:

- Register at a specific time
- Register when a matching email arrives
