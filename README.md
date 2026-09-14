# 🏛️ GovRecruitmentTracker

> **Autonomous Indian Government CS/IT & General Recruitment Pipeline**  
> *Zero-Cost AI Parsing · Resilient Portal Scraping · Google Calendar OAuth2 & iCal Subscriptions · Telegram Instant Alerts*

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1-black?logo=flask)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/Tests-448%20Passing-brightgreen?logo=pytest)](file:///tests)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

---

## 🌟 Overview

**GovRecruitmentTracker** is an end-to-end, production-ready web application and autonomous background scraper designed to track Indian Government, PSU, Banking, and Competitive Examination recruitment notifications.

It solves the critical problem of missing high-value public sector recruitment opportunities (e.g. **NIELIT Scientist B**, **NIC Scientific Officer**, **CDAC**, **DRDO RAC**, **BARC**, **ISRO**, **SSC CGL**, **IBPS**, **UPSC**) by continuously monitoring official career portals, filtering for Computer Science / Information Technology and open graduate eligibility, and synchronizing deadlines directly with your calendars and phone alerts.

---

## ✨ Key Features

- **⚡ Autonomous Resilient Web Scraping**:
  - Monitors 13+ seeded official portals with custom scrapers plus dynamic fallback scraping for user-added career portals.
  - Automatic SSL certificate failure recovery, relative-to-absolute URL normalization, and fault-isolated non-blocking daemon execution.
  - **SHA-256 URL Fingerprint Deduplication**: Prevents redundant PDF downloads and protects your free-tier Gemini API quota.

- **🧠 Zero-Cost 3-Stage AI Extraction Pipeline**:
  - **Stage 1 (Local Regex Pre-Filter)**: Rejects irrelevant non-CS/IT trades instantly (zero API cost).
  - **Stage 2 (Gemini 2.5 Flash)**: High-speed structured JSON parsing of post titles, vacancies, pay levels, age cutoffs, and GATE requirements.
  - **Stage 3 (Offline Regex Engine Fallback)**: 100% offline extraction if no Gemini API key is configured or when offline.

- **📅 Calendar Integration & Subscriptions**:
  - **Google Calendar OAuth2 Push**: Individual, one-event-per-job event synchronization with 3-day and 1-day reminder overrides.
  - **iCal (.ics) Dynamic Feed (`/calendar.ics`)**: One-click subscription on iPhones, iPads, Macs (Apple Calendar), Android, and Microsoft Outlook without requiring any developer credentials.

- **✈️ Real-Time Telegram Dispatcher**:
  - Non-blocking daemon alerts via Telegram Bot with clickable direct links, pay scale highlights, and last-date warnings.

- **📱 Futuristic Dark-Mode-First Web UI**:
  - Glassmorphic `#0d1117` design with electric blue accents (`#58a6ff`).
  - **Mobile**: High-touch urgency cards (🔴 `< 7 Days`, 🟡 `7–30 Days`, 🟢 `> 30 Days`).
  - **Desktop**: Dense sortable table with tags (`[Non-GATE]`, `[Level 10+]`, `[CS/IT]`).
  - **Slide-over Tracking Drawer**: Update application status, registration numbers, roll numbers, and notes via AJAX without page reloads.

---

## 📁 Repository Structure

```
GovRecruitmentTracker/
├── app.py                     # Flask application factory (create_app) & WSGI entry point
├── config.py                  # Environment-aware configuration (Dev, Test, Prod)
├── models.py                  # SQLAlchemy ORM models (Job, Source, UserSettings, SeenURL)
├── db_init.py                 # Database initialization & default source seeders
├── parser.py                  # 3-Stage AI extraction pipeline & Age Verifier
├── dedup.py                   # SHA-256 URL fingerprint deduplication engine
├── calendar_sync.py           # Google Calendar OAuth2 & iCal (.ics) feed generator
├── telegram_notifier.py       # Non-blocking Telegram alert dispatcher
├── blueprints/
│   ├── dashboard.py           # Dashboard routes, KPI metrics, urgency filters, /calendar.ics
│   ├── jobs.py                # Job tracking status, notes, /fetch-now background triggers
│   ├── sources.py             # Portal management (add, pause/resume, delete)
│   ├── settings.py            # User profile (DOB, category), Telegram tester, OAuth
│   ├── auth.py                # Google Calendar OAuth2 callback flow
│   └── api.py                 # REST API endpoints (/api/jobs, /api/metrics, /api/health)
├── scrapers/
│   ├── base.py                # BaseScraper ABC, resilient session handling, SSL bypass
│   └── portal_scraper.py      # Concrete portal scrapers & GenericCareerScraper
├── static/
│   ├── css/styles.css         # Dark-mode first stylesheet with glassmorphism & tokens
│   └── js/main.js             # Theme toggle, AJAX drawer, dynamic search & table sort
├── templates/
│   ├── layout.html            # Main base layout, navbar, drawer modal, toast container
│   ├── dashboard.html         # KPI stats, filter bar, mobile cards, desktop dense table
│   ├── sources.html           # Portal manager table & Add Portal card
│   └── settings.html          # Profile settings, Telegram tester, Calendar sync
├── tests/
│   ├── test_parser.py         # 80 tests for 3-stage extraction & age verification
│   ├── test_scraper_resilience.py # 126 tests for scraping, SSL bypass & dedup
│   ├── test_milestone4.py     # 97 tests for Google Calendar & Telegram alerts
│   ├── test_routes.py         # 83 tests for blueprints, error handlers & APIs
│   └── test_frontend.py       # 62 tests for UI rendering, CSS tokens & iCal feed
├── gunicorn_config.py         # Production Gunicorn WSGI container configuration
├── Procfile                   # Process file for Render / Heroku
├── render.yaml                # Render Blueprint infrastructure-as-code
└── requirements.txt           # Python dependencies
```

---

## 🚀 Quick Start (Local Development)

### 1. Prerequisites
- Python 3.10, 3.11, 3.12, or 3.14
- Git

### 2. Clone and Setup Environment
```bash
git clone https://github.com/<your-username>/GovRecruitmentTracker.git
cd GovRecruitmentTracker

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Initialize Database & Seed Portals
```bash
flask init-db
```
*(Automatically creates `instance/recruitment_tracker.db` and seeds 13 official recruitment boards).*

### 4. Run Development Server
```bash
python app.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

## 🧪 Running Automated Tests

GovRecruitmentTracker includes an exhaustive **448-test test suite** with 100% passing coverage:

```bash
# Run all test suites
.venv/bin/python tests/test_parser.py
.venv/bin/python tests/test_scraper_resilience.py
.venv/bin/python tests/test_milestone4.py
.venv/bin/python tests/test_routes.py
.venv/bin/python tests/test_frontend.py
```

Check linting and types:
```bash
.venv/bin/pyflakes ./*.py ./blueprints/*.py ./scrapers/*.py ./tests/*.py
.venv/bin/mypy --ignore-missing-imports ./*.py ./blueprints/*.py ./scrapers/*.py
```

---

## 📦 Step-by-Step GitHub Setup & Push

Follow these steps to push the code to your GitHub account:

### Step 1: Initialize Git Repository (if not already done)
```bash
cd /path/to/GovRecruitmentTracker
git init
```

### Step 2: Add Files & Create Initial Commit
```bash
git add .
git commit -m "feat: Initial commit with complete GovRecruitmentTracker system"
```

### Step 3: Link to Your GitHub Repository
1. Go to [github.com/new](https://github.com/new) and create a repository named `GovRecruitmentTracker`.
2. Link your remote and push:
```bash
git branch -M main
git remote add origin https://github.com/<your-github-username>/GovRecruitmentTracker.git
git push -u origin main
```

---

## ☁️ Production Deployment on Render (Free Tier)

You can deploy GovRecruitmentTracker on Render's free tier in two ways:

### Option A: 1-Click Render Blueprint (Recommended)
1. Log in to your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** → **Blueprint**.
3. Connect your GitHub repository `GovRecruitmentTracker`.
4. Render will detect `render.yaml` and configure the Web Service automatically.
5. Provide your optional environment variables (e.g. `GEMINI_API_KEY`) and click **Apply**.

### Option B: Manual Web Service Setup
1. On the Render Dashboard, click **New +** → **Web Service**.
2. Select your repository `GovRecruitmentTracker`.
3. Configure the following settings:
   - **Name**: `gov-recruitment-tracker`
   - **Region**: Oregon (or nearest region)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt && flask init-db`
   - **Start Command**: `gunicorn app:app --config gunicorn_config.py`
   - **Plan**: `Free`
4. Under **Advanced** → **Environment Variables**, add the variables detailed below.
5. Click **Create Web Service**.

---

## ⚙️ Environment Variables Reference

| Variable Name | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Optional | `sqlite:///instance/recruitment_tracker.db` | Database connection URL. Supports PostgreSQL on cloud or SQLite locally. |
| `SECRET_KEY` | Optional | (auto-generated) | Cryptographic secret for Flask session and flash cookies. |
| `GEMINI_API_KEY` | Optional | `""` | Free Google AI Studio API key for high-speed Stage 2 notification extraction. |
| `TELEGRAM_BOT_TOKEN`| Optional | `""` | Telegram Bot API token from [@BotFather](https://t.me/BotFather) for push alerts. |
| `TELEGRAM_CHAT_ID` | Optional | `""` | Telegram User ID or Group ID to receive recruitment notifications. |
| `GOOGLE_CREDENTIALS_FILE` | Optional | `credentials.json` | Path to Google OAuth2 Desktop client secret JSON. |
| `GOOGLE_TOKEN_FILE` | Optional | `token.json` | Path to generated Google OAuth2 authorized token JSON. |
| `WEB_CONCURRENCY` | Optional | `2` | Number of Gunicorn worker processes. |
| `GUNICORN_THREADS` | Optional | `4` | Number of threads per Gunicorn worker. |
| `LOG_LEVEL` | Optional | `info` | Logging verbosity (`debug`, `info`, `warning`, `error`). |

---

## 🗓️ Subscribing to Deadlines on Your Devices

### 1. iCal (.ics) One-Click Subscription
Navigate to `/settings` or copy the direct feed URL:
```
https://<your-app-domain>/calendar.ics
```
- **iPhone / iPad / Mac**: Click **"Subscribe in Calendar App"** or add `webcal://<your-app-domain>/calendar.ics` in the Calendar app (`File` → `New Calendar Subscription`).
- **Google Calendar**: Go to Google Calendar → Click `+` next to *Other calendars* → *From URL* → Paste `https://<your-app-domain>/calendar.ics`.
- **Microsoft Outlook**: *Add Calendar* → *Subscribe from web* → Paste the `.ics` URL.

### 2. Google Calendar Direct OAuth Sync
1. In Google Cloud Console, enable **Google Calendar API**.
2. Create an **OAuth 2.0 Client ID** (Desktop Application) and download it as `credentials.json` in the root folder.
3. In the web application, visit **Settings** → click **Connect with Google Calendar**.
4. Deadlines and exam dates will now push directly into your primary Google Calendar with 3-day and 1-day reminders.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
