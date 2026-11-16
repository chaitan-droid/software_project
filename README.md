# CampusShare

A Python web application for sharing permitted study materials among students. FastAPI handles HTTP requests, Python renders the responsive browser pages, and SQLite stores accounts, resource metadata, files, and moderation history together.

## Run in VS Code on Windows

Install Python 3.12 and Git. Open a PowerShell terminal:

```powershell
git clone https://github.com/chaitan-droid/software_project.git
cd software_project
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000 and choose **Create a student account**. On Linux or macOS use `python3.12 -m venv .venv` and `.venv/bin/python` in place of the Windows interpreter path.

## Walk through the project

1. Register a student and upload a UTF-8 text file or PDF with a title, course, subject, semester, category and description. Add tags if desired. The limit is 10 MiB per file. Lecture slides and scans can be exported to PDF.
2. Open a private browser window and register a second student. Search by subject, apply filters, open the file details, bookmark it and submit a rating or feedback.
3. For an approval-only upload, request download access. The owner can open **Account → Incoming download requests**, select the resource and approve or deny the request.
4. Report a resource. It leaves the student catalog and ordinary downloads are blocked while it is under review.
5. To try moderation, register a separate account. In another terminal in the project directory, run the following using that account's email:

   ```powershell
   .\.venv\Scripts\python.exe backend.py moderator@example.org
   ```

   Refresh the moderator's page and open **Admin**. Review the file, restore or remove it, rename categories, manage student access, and inspect usage totals and recent activity. Administrative access is granted locally. There is no seeded administrator password.

## Project files

| File | Responsibility |
| --- | --- |
| frontend.py | Python page layout, styles, resource cards and form components |
| app.py | Browser routes, session and role checks, discovery, download access and moderation workflows |
| backend.py | SQLite schema, password hashing, file validation and administrator setup |
| test_campusshare.py | Integration workflows and file-size boundary tests |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest -v
```

Tests use a temporary database. They exercise valid and invalid login, duplicate accounts, CSRF protection, permissions, accepted and rejected uploads, search, bookmarks, ratings, reports, moderation, category administration, account suspension and access grants.

## Storage and deployment

The first launch creates `data/campus.sqlite3`. Upload metadata and bytes are saved in one transaction. To back up a local demo, stop the server and copy the data directory. Set `CAMPUS_DB` to select another database path.

The commands above start a local development server. For an institutional deployment, configure HTTPS and set `CAMPUS_HTTPS=1` for secure cookies. Set upload request limits at the reverse proxy and add malware scanning before accepting files from untrusted users. Current checks cover file size, extension and basic content format. The report's search-latency target requires a separately defined dataset and workload.
