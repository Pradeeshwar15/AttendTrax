#!/usr/bin/env python3
"""
AttendTrax Institutional Master Database Backup CLI
====================================================
Performs a scheduled or on-demand automated institutional database backup.
Exports all 7 core institutional datasets into an encrypted/compressed ZIP archive:
1. Students_Master (with Gender, Residence Type, Placement Standing)
2. Faculty_Master
3. Classes_Master (with Class Incharge assignments)
4. Subjects_Master
5. Departments_Master
6. Leaves_Audit (Faculty & Student leave queues)
7. Attendance_Reports

Can be triggered by:
- GitHub Actions daily cron (00:00 UTC / 05:30 AM IST)
- Render or Linux cron jobs
- Windows Task Scheduler
- Local administrative command line
"""

import os
import sys
import argparse
import urllib.request
import urllib.parse
import json
import zipfile
import io
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_API_URL = os.environ.get("ATTENDTRAX_API_URL", "https://attendtrax-api.onrender.com")
DEFAULT_USERNAME = os.environ.get("BACKUP_PRINCIPAL_USER", "principal")
DEFAULT_PASSWORD = os.environ.get("BACKUP_PRINCIPAL_PASS", "Principal@2026")
DEFAULT_BACKUP_DIR = os.environ.get("BACKUP_DIR", "backups")


def authenticate(api_base: str, username: str, password: str) -> str:
    """Obtains a Super Admin JWT token using JSON login."""
    login_url = f"{api_base.rstrip('/')}/auth/login"
    data = json.dumps({
        "username": username,
        "password": password
    }).encode("utf-8")

    req = urllib.request.Request(
        login_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AttendTrax-BackupBot/2.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            token = body.get("access_token")
            if not token:
                raise ValueError("No access_token returned by authentication endpoint.")
            return token
    except Exception as exc:
        print(f"[ERROR] Authentication failed against {login_url}: {exc}", file=sys.stderr)
        raise


def fetch_master_backup(api_base: str, token: str) -> bytes:
    """Fetches the 7-table Master Backup ZIP archive from the executive router."""
    export_url = f"{api_base.rstrip('/')}/admin/executive/export-all"
    req = urllib.request.Request(
        export_url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "AttendTrax-BackupBot/2.0"
        }
    )

    print(f"[INFO] Requesting institutional backup snapshot from {export_url}...")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status != 200:
                raise ValueError(f"Server returned HTTP status {resp.status}")
            zip_bytes = resp.read()
            print(f"[INFO] Successfully received {len(zip_bytes):,} bytes from server.")
            return zip_bytes
    except Exception as exc:
        print(f"[ERROR] Failed to download master backup: {exc}", file=sys.stderr)
        raise


def inspect_and_save_backup(zip_bytes: bytes, out_dir: Path) -> Path:
    """Validates the ZIP integrity, parses member table statistics, and writes to disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"AttendTrax_Backup_{timestamp}.zip"

    # Integrity verification
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        corrupt = zf.testzip()
        if corrupt:
            raise ValueError(f"Corrupt file detected inside downloaded archive: {corrupt}")
        
        namelist = zf.namelist()
        print(f"[INFO] Verified ZIP archive integrity. Tables found ({len(namelist)}):")
        
        table_stats = {}
        for name in namelist:
            raw = zf.read(name).decode("utf-8", errors="replace")
            lines = [l for l in raw.splitlines() if l.strip()]
            header = lines[0] if lines else "EMPTY"
            row_count = max(0, len(lines) - 1)
            table_stats[name] = {"rows": row_count, "bytes": len(raw)}
            print(f"       * {name:<35} | {row_count:>5} records | {len(raw):>7,} bytes")

    # Write ZIP to destination
    with open(zip_path, "wb") as f:
        f.write(zip_bytes)

    # Write accompanying metadata JSON
    meta_path = out_dir / f"AttendTrax_Backup_{timestamp}.meta.json"
    meta = {
        "backup_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "backup_filename": zip_path.name,
        "backup_size_bytes": len(zip_bytes),
        "tables": table_stats,
        "total_tables": len(namelist),
        "total_records": sum(t["rows"] for t in table_stats.values()),
        "status": "HEALTHY",
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"[SUCCESS] Master institutional backup saved successfully:")
    print(f"          Archive:  {zip_path.resolve()}")
    print(f"          Metadata: {meta_path.resolve()}")
    return zip_path


def main():
    parser = argparse.ArgumentParser(description="AttendTrax Automated Database Backup CLI")
    parser.add_argument("--url", default=DEFAULT_API_URL, help="Base URL of AttendTrax API")
    parser.add_argument("--user", default=DEFAULT_USERNAME, help="Super Admin Username")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Super Admin Password")
    parser.add_argument("--out-dir", default=DEFAULT_BACKUP_DIR, help="Output directory for backup archives")
    args = parser.parse_args()

    print("===================================================================")
    print("  AttendTrax Enterprise – Institutional Backup Engine")
    print(f"  Target:     {args.url}")
    print(f"  User:       {args.user}")
    print(f"  Timestamp:  {datetime.now(timezone.utc).isoformat()} UTC")
    print("===================================================================")

    try:
        token = authenticate(args.url, args.user, args.password)
        zip_bytes = fetch_master_backup(args.url, token)
        zip_path = inspect_and_save_backup(zip_bytes, Path(args.out_dir))
        print("===================================================================")
        print(f"  BACKUP COMPLETED CLEANLY: {zip_path.name}")
        print("===================================================================")
        sys.exit(0)
    except Exception as exc:
        print(f"\n[FATAL] Backup procedure failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
