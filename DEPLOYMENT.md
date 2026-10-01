# 🚀 AttendTrax — Production Deployment Guide

This guide provides step-by-step instructions to deploy **AttendTrax** (FastAPI Backend + Modern Web Frontend) to production.

---

## 1. Architecture Overview

- **Backend**: FastAPI (Python 3.11) with Google Sheets API integration and in-memory rate limiting / sliding-window cache.
  - Recommended Host: [Render](https://render.com) (Free Tier available) or [Railway](https://railway.app) / [Fly.io](https://fly.io) / Docker.
- **Frontend**: Vanilla HTML5/CSS3/JavaScript SPA with real-time Chart.js dashboards.
  - Recommended Host: [Vercel](https://vercel.com) (Free Tier) or [Netlify](https://netlify.com) / GitHub Pages.
- **Database**: Google Sheets (Enterprise Cloud Spreadsheet storage with per-class tabs and master audit log).

---

## 2. Deploying Backend to Render (Recommended)

### Step A: Push Code to GitHub / GitLab
Ensure your project repository is uploaded to your GitHub or GitLab account.

### Step B: Create Web Service on Render
1. Log in to [dashboard.render.com](https://dashboard.render.com) and click **New + > Web Service**.
2. Connect your GitHub repository.
3. Configure the following service settings:
   - **Name**: `attendtrax-api`
   - **Root Directory**: `backend`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Step C: Set Environment Variables on Render
Under **Environment Variables**, configure the following keys:

| Variable | Description / Sample Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON credentials string of your Google Cloud service account. |
| `SPREADSHEET_FOLDER_ID` | Google Drive folder ID where class spreadsheets reside. |
| `USERS_SHEET_ID` | Google Sheet ID for Users master table. |
| `CLASSES_SHEET_ID` | Google Sheet ID for Classes master table. |
| `STUDENTS_SHEET_ID` | Google Sheet ID for Students master table. |
| `SUBJECTS_SHEET_ID` | Google Sheet ID for Subjects master table. |
| `ATTENDANCE_LOG_SHEET_ID` | Google Sheet ID for Attendance_Log table. |
| `ADMIN_USERNAME` | `admin` |
| `ADMIN_PASSWORD_HASH` | Bcrypt hash for your production admin password. |
| `SECRET_KEY` | Strong random string (e.g. `openssl rand -hex 32`). |
| `ALLOWED_ORIGINS` | Comma-separated frontend domains, e.g.: `https://your-attendtrax.vercel.app,http://localhost:5500` |

4. Click **Deploy Web Service**. Once deployed, copy your backend URL (e.g. `https://attendtrax-api.onrender.com`).

---

## 3. Deploying Frontend to Vercel (Recommended)

### Step A: Point Frontend to Render Backend URL
In `frontend/api.js`, update line 8:
```javascript
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://127.0.0.1:8000'
  : 'https://attendtrax-api.onrender.com'; // ← Paste your Render URL here
```

### Step B: Deploy via Vercel CLI or Dashboard
1. Open terminal in the `frontend/` directory.
2. Run:
   ```bash
   npx vercel
   ```
3. Follow the CLI prompts to deploy.
4. Your application will be live instantly with global SSL!

---

## 4. Deploying via Docker (Alternative)

To build and run the backend as a container:
```bash
cd backend
docker build -t attendtrax-api .
docker run -p 8000:8000 --env-file .env attendtrax-api
```

---

## 5. Security & Verification Checklist

- [x] **Rate Limiting**: Sliding-window IP and account rate limiter enabled on `/auth/login` (blocks brute force attacks).
- [x] **Security Headers**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`, and `Referrer-Policy` automatically injected.
- [x] **Google Sheets Formula Injection Neutralizer**: All cells beginning with `=`, `+`, `-`, `@`, `\t`, `\r` sanitized with leading `'`.
- [x] **Role-Based Access Control (RBAC)**: Enforced with cryptographically signed JWT tokens for Admin, Faculty, and Student routes.
- [x] **XSS Prevention**: `escapeHtml()` helper prevents DOM injection on dynamic tables and charts.

---

## 6. Pre-Configured Accounts

| Role | Username / RegNo | Password | Features |
|---|---|---|---|
| **Admin** | `admin` | `AttendTrax@2026` | Full Analytics, Class Performance, Student/Faculty/Subject Management, Bulk XLSX Import. |
| **Faculty** | `fathima.cse` | `Staff@2026` | 1-Click Daily Attendance Marking, Live Status Counters, Class Attendance Reports. |
| **Student** | `410125104001` | `410125104001` | Personal Attendance Dashboard, Subject-wise Breakdown, Daily History. |
