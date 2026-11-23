# AttendTrax Enterprise

AttendTrax is an institutional-grade, multi-tier attendance management and campus workflow platform engineered for colleges and universities.

It operates on a **High-Performance Pure Cloud Architecture**:
- **Primary Database**: **Supabase Cloud PostgreSQL** powering all institutional tables: student cohorts, classes, subjects, faculty allocations, attendance sessions, attendance records, leaves, outpasses, audit logs, and notifications with sub-millisecond query performance.
- **Relational SQL Engine**: Powering high-concurrency 10-department administrative hierarchies, multi-tier RBAC, faculty leave workflows, and dual-track student residential outpasses with digital QR tokens.

---

## 🌟 Key Features

### 1. High-Speed Attendance & Academic Management
- **Instant Hourly Attendance**: Fast hour-wise marking (`P` / `A` / `OD`) with lock protection to prevent unauthorized re-marking.
- **Admin Modification & Overrides**: Authorized administrators can view past date logs, update missing attendance, and review audit trails directly in Supabase.
- **Excel & Bulk Import**: High-speed batch insertion for past attendance records, classes, subjects, and student cohorts with zero external spreadsheet latency.

### 2. Multi-Department Hierarchy (9 Academic Departments + Placement)
- Full college-wide scaling supporting:
  - **CSE** (Computer Science & Engineering)
  - **AIDS** (Artificial Intelligence & Data Science)
  - **AIML** (Artificial Intelligence & Machine Learning)
  - **CYBER SECURITY** (Cyber Security)
  - **EEE** (Electrical & Electronics Engineering)
  - **ECE** (Electronics & Communication Engineering)
  - **MECH** (Mechanical Engineering)
  - **S&H** (Science & Humanities)
  - **IT** (Information Technology)
- **Placement & Training Department**: Cross-department universal student roster access for campus training runs, aptitude bootcamps, and recruitment drives.
- **Executive Governance & Switcher**: Allows the Principal and Vice Principal to review institutional benchmarks and toggle departmental data cleanly.

### 3. Faculty Leave & Permission Workflow
- **Multi-Level Approval Chain**: Faculty &rarr; Level 1: Department HOD &rarr; Level 2: Principal / Vice Principal &rarr; Approved.
- **Session Scope Options**:
  - Full Day (`FULL_DAY`)
  - Forenoon Half-Day (`FN_HALF_DAY`)
  - Afternoon Half-Day (`AN_HALF_DAY`)
  - Specific Permission Hours (`SPECIFIC_HOURS`) with designated time window (e.g. `09:30 AM - 11:00 AM`).
- **Real-Time Notification Badges**: Live tracking in `faculty.html` showing approval state and remarks from HOD and Principal.

### 4. Dual-Track Student Leave & Hostel Outpass Queue
- **Day Scholar Track**: Student &rarr; Class Incharge Faculty &rarr; Department HOD &rarr; Granted (auto-reconciled as OD/Leave without attendance penalty).
- **Hosteller Track**: Student &rarr; Class Incharge &rarr; Department HOD &rarr; Hostel Warden &rarr; Digital QR Gatepass Generated.
- **Main Gate Security Terminal**: High-contrast scanner portal (`gatepass.html`) for security officers to verify QR tokens and log timestamped `EXIT` and `RETURN` events.

---

## 🗄️ Database Architecture: How Data is Stored

| Data Category | Primary Storage | Role & Purpose |
| :--- | :--- | :--- |
| **Daily Attendance Logs** | **Supabase PostgreSQL** | `attendance_sessions` and `attendance_records` tables with sub-10ms query and index lookup. |
| **Student Roster & Classes** | **Supabase PostgreSQL** | Normalized `students` and `classes` tables supporting instant filtering by department and semester. |
| **10-Department Structure** | **Supabase PostgreSQL** | Relational mapping of 9 academic departments + Training & Placement with HOD assignments. |
| **Multi-Tier RBAC & Users** | **Supabase PostgreSQL** | Stores credentials for Principal, HODs, Wardens, Faculty, and Students with bcrypt password protection. |
| **Faculty Leave Tickets** | **Supabase PostgreSQL** | Tracks leave category, session scope, dates, HOD review, and Principal sign-off with printable sanction docket. |
| **Student Outpass & Passes** | **Supabase PostgreSQL** | Tracks multi-stage reviews, cryptographic 32-character gate tokens, and security timestamps. |

---

## 🛠️ Tech Stack

- **Backend**: Python 3.11+ / FastAPI, SQLAlchemy 2.0 (Async), `asyncpg` (PostgreSQL), `python-jose` (JWT), `bcrypt`.
- **Frontend**: Vanilla HTML5, Modern CSS3 (Variables, Flexbox/Grid, Glassmorphism), ES6 JavaScript.
- **Security & Caching**: Redis 7, In-memory rate limiting, SHA256 / Bcrypt password hashing.
- **Deployment**: Docker Compose (Nginx + FastAPI + PostgreSQL 16 + Redis), Render.com, Vercel.

---

## 📁 Directory Structure

```text
AttendTrax/
├── backend/
│   ├── main.py                  # FastAPI application entry point & router mounting
│   ├── database.py              # Async SQLAlchemy connection pool & session factory
│   ├── models.py                # 14 normalized relational models (Leaves, RBAC, etc.)
│   ├── migrate_and_seed.py      # Seeding script for 8 departments, admins, wardens
│   ├── config.py                # Pydantic configuration & environment variables
│   ├── auth.py                  # JWT creation, decoding & bcrypt password verification
│   ├── sheets.py                # Google Sheets read/write operations (Primary academic DB)
│   ├── dependencies.py          # Enterprise RBAC role guards (SQL + Sheets fallback)
│   ├── requirements.txt         # Python dependencies
│   ├── .env.example             # Template for secrets and credentials
│   └── routers/
│       ├── auth_router.py       # Authentication & login endpoint
│       ├── faculty_router.py    # Daily attendance marking & class reports
│       ├── student_router.py    # Student attendance summaries & calendar views
│       ├── admin_router.py      # Admin dashboard, past attendance modification, bulk import
│       └── leave_router.py      # Faculty leave & student outpass approval queues
├── frontend/
│   ├── index.html               # Institutional login screen with multi-role routing
│   ├── admin.html               # Admin & HOD dashboard (Analytics, attendance edit, leave reviews)
│   ├── faculty.html             # Faculty portal (Mark attendance, reports, leave application)
│   ├── student.html             # Student portal (Subject breakdown, day history, apply outpass)
│   ├── gatepass.html            # Main gate security verification & hostel warden portal
│   ├── style.css                # Global design system & theme tokens
│   ├── api.js                   # Unified API client, session management & auth guards
│   └── icons/                   # Brand icons & PWA assets
├── docker-compose.yml           # Full production stack (Nginx, API, Postgres, Redis, Backup)
├── nginx/
│   └── nginx.conf               # High-performance reverse proxy & rate limiting
└── README.md
```

---

## 🚀 How to Run the Application (Local Development)

### Step 1: Clone & Environment Configuration

1. Clone the repository:
   ```bash
   git clone https://github.com/imperio-cse/AttendTrax.git
   cd AttendTrax
   ```

2. Create the backend `.env` file:
   ```bash
   cp backend/.env.example backend/.env
   ```

3. Configure your `backend/.env` file with your Supabase credentials:
   ```env
   # Admin Setup
   ADMIN_NAME="System Administrator"
   ADMIN_USERNAME="admin"
   ADMIN_PASSWORD_HASH="<bcrypt_hash_of_your_password>"
   SECRET_KEY="<your_jwt_secret_key>"

   # Primary Supabase PostgreSQL Connection
   DATABASE_URL="postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres"
   ```

---

### Step 2: Backend Setup & Database Seeding

1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```

2. Create and activate a Python virtual environment:
   ```bash
   # Using standard venv:
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: If using `uv`, run `uv pip install -r requirements.txt`)*

4. Run the database migration and seeding script:
   ```bash
   python migrate_and_seed.py
   ```
   *This automatically creates all tables, seeds all 8 college departments, initializes Super Admins (Principal & Vice Principal), 8 Department HODs, Hostel Wardens, and syncs student records.*

5. Start the FastAPI development server:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   The API will be live at `http://127.0.0.1:8000` with interactive Swagger docs at `http://127.0.0.1:8000/docs`.

---

### Step 3: Frontend Setup

1. Open `frontend/api.js` and verify that `API_BASE` points to `http://127.0.0.1:8000`:
   ```javascript
   const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
     ? 'http://127.0.0.1:8000'
     : 'https://attendtrax-api.onrender.com';
   ```

2. Serve the `frontend/` directory with any static server:
   ```bash
   # From project root:
   cd frontend
   python -m http.server 5500
   ```
   Or use VS Code's **Live Server** extension on `frontend/index.html`.

3. Open your browser to `http://127.0.0.1:5500` (or `http://localhost:5500`).

---

## 🔑 Default Login Credentials for Testing

| Role | Username | Password | Accessible Dashboard |
| :--- | :--- | :--- | :--- |
| **Super Admin (Principal)** | `principal` | `Principal@2026` | `admin.html` (8-Dept Switcher & Executive Leave Sign-Off) |
| **Super Admin (Vice Principal)**| `viceprincipal` | `VicePrincipal@2026`| `admin.html` (Executive Leave Sign-Off) |
| **Central Admin** | `admin` | *(From `.env`)* | `admin.html` (Full System Administration) |
| **HOD (Computer Science)** | `hod.cse` | `Hod@2026` | `admin.html` (CSE Staff & Student Leave Queues) |
| **HOD (Other Depts: ECE..CSBS)**| `hod.ece` ... `hod.csbs` | `Hod@2026` | `admin.html` (Department Review Queues) |
| **Hostel Warden (Boys)** | `warden.boys` | `Warden@2026` | `gatepass.html` (Hostel Outpass Approval & Pass Issuance) |
| **Hostel Warden (Girls)** | `warden.girls` | `Warden@2026` | `gatepass.html` (Hostel Outpass Approval & Pass Issuance) |
| **Faculty Member** | `staff` *(or created staff)* | *(Configured PW)* | `faculty.html` (Mark Attendance, Apply Leave, Incharge Queue)|
| **Student (Hosteller / Day Scholar)**| `<RegNo>` (e.g. `410123104001`) | `<RegNo>@CSE` | `student.html` (Attendance Summary, Apply Outpass) |
| **Main Gate Security Officer** | *(Terminal Access)* | — | `gatepass.html` (Scan / Type Token & Record Exit/Return) |

---

## 🐳 On-Premise Production Deployment (Docker Compose)

For deployment on the college's dedicated Ubuntu Linux on-premise server:

1. Install Docker and Docker Compose on the server:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2
   ```

2. Clone repository to `/opt/attendtrax`:
   ```bash
   sudo git clone https://github.com/imperio-cse/AttendTrax.git /opt/attendtrax
   cd /opt/attendtrax
   ```

3. Setup environment configuration:
   ```bash
   cp backend/.env.example backend/.env
   # Update POSTGRES_PASSWORD, SECRET_KEY, and ALLOWED_ORIGINS in backend/.env
   ```

4. Launch the entire containerized production stack:
   ```bash
   docker compose up -d --build
   ```

5. Run initial migration inside the API container:
   ```bash
   docker compose exec api python migrate_and_seed.py
   ```

The application will be served via Nginx on port 80/443 with automated SSL support, rate limiting, and PostgreSQL persistence.

---

## 👥 Engineering & Architecture Team

Engineered & Developed by the **Department of Computer Science & Engineering**:
- **Pradeeshwar** — Full-Stack Architect & Core Lead (`pradeeshwar.cse@gmail.com`)
- **Kanaga Prasath** — Systems Engineer & Data Strategist (`kanagubry@gmail.com`)

&copy; 2026 AttendTrax Platform. All Rights Reserved.
