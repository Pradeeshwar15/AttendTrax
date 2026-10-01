# AttendTrax

AttendTrax is a modern, lightweight, role-based student attendance management system. It uses **Google Sheets as its database**, providing a visual and highly accessible way for administrators to view data while enforcing strict immutability and role-based access through a Python backend.

---

## 🌟 Features

- **Role-Based Access Control**:
  - **Admin**: Manage classes, students, subjects, faculty, and import past attendance data via Excel.
  - **Faculty**: Select a class/subject/hour and easily mark student attendance. Data is locked after submission to prevent tampering.
  - **Student**: View their own attendance history, day-wise records, and overall attendance percentage.
- **Google Sheets Database**:
  - Automatically generates and formats class-wise monthly attendance registers.
  - Maintains a strict, append-only `Attendance_Log` sheet for backend analytics and calculations.
- **Data Immutability**: Once an attendance slot (Class + Date + Hour + Subject) is marked, the backend rejects any further attempts to modify it.
- **Bulk Import**: Admins can bulk-upload past attendance records using an Excel template.
- **Dynamic Frontend**: Modern, responsive UI with animations, toasts, and role-specific dashboards built purely with HTML, CSS, and JS.

---

## 🛠️ Tech Stack

**Backend**
- **Framework**: Python / FastAPI
- **Database / API**: `gspread`, Google Sheets API, Google Drive API
- **Security**: JWT (`PyJWT`), Password Hashing (`passlib` with `bcrypt`)
- **Deployment**: Configured for [Render.com](https://render.com) (includes `Procfile`)

**Frontend**
- **Core**: Vanilla HTML5, CSS3, JavaScript (ES6)
- **Deployment**: Configured for static hosting on [Vercel](https://vercel.com) (includes `vercel.json`)

---

## 📁 Project Structure

```text
AttendTrax/
├── backend/
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Environment variable configuration
│   ├── auth.py              # JWT and password hashing logic
│   ├── sheets.py            # Google Sheets read/write operations
│   ├── dependencies.py      # Dependency injection & Auth guards
│   ├── setup_sheets.py      # Script to auto-format Google Sheets
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Template for environment variables
│   └── routers/             # API Endpoints (admin, faculty, student, auth)
└── frontend/
    ├── index.html           # Login page & redirect handler
    ├── admin.html           # Admin dashboard
    ├── faculty.html         # Faculty dashboard
    ├── student.html         # Student dashboard
    ├── style.css            # Global design system
    ├── api.js               # Centralized API client and utilities
    └── vercel.json          # Vercel routing configuration
```

---

## 🚀 Getting Started (Local Development)

### 1. Google Cloud Setup
1. Create a project in the [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account** and download the JSON key.
4. Create a folder in Google Drive (e.g., "AttendTrax DB") and share it with your Service Account email as an **Editor**.

### 2. Backend Setup
1. Navigate to the `backend/` directory.
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your Service Account JSON (as a single line), Drive Folder ID, and generate a `SECRET_KEY`.

### 3. Database Initialization
Create 9 blank spreadsheets in your Drive folder (Users, Classes, Students, Subjects, Attendance_Log, and one for each class). Share them with your service account, grab their IDs, and add them to `setup_sheets.py`. 
Then run the setup script to initialize the tables and formatting:
```bash
python setup_sheets.py
```

### 4. Run the Server
```bash
uvicorn main:app --reload --port 8000
```
The API documentation will be available at `http://127.0.0.1:8000/docs`.

### 5. Frontend Setup
1. Open `frontend/api.js` and ensure `API_BASE` points to `http://127.0.0.1:8000` for local development.
2. Serve the `frontend/` directory using any static file server (e.g., VS Code Live Server, or `python -m http.server 5500`).

---

## 🌐 Deployment

**Backend (Render.com)**
1. Connect your GitHub repository to Render as a "Web Service".
2. Set Root Directory to `backend`.
3. Set the start command to `uvicorn main:app --host 0.0.0.0 --port $PORT`.
4. Add all your `.env` variables to the Render environment variables settings.

**Frontend (Vercel)**
1. Connect your GitHub repository to Vercel.
2. Set the Root Directory to `frontend`.
3. Vercel will automatically detect the `vercel.json` and deploy your static assets.
4. Remember to update the `API_BASE` in `frontend/api.js` to point to your live Render backend URL before deploying!
