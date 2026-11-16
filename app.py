"""HTTP entry point for CampusShare."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from backend import LIMIT, database, file_kind, initialize, log, matches, password_hash
from frontend import card, e, field, form, layout, select


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
SECURE = os.getenv("CAMPUS_HTTPS") == "1"
BASE = "SELECT r.*, c.name category_name, u.name author FROM resources r JOIN categories c ON c.id=r.category JOIN users u ON u.id=r.owner"


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


@app.middleware("http")
async def context(req, call_next):
    csrf = req.cookies.get("campus_csrf") or secrets.token_urlsafe(32)
    token = req.cookies.get("campus_session", "")
    with database() as db:
        req.state.user = db.execute(
            "SELECT u.* FROM users u JOIN sessions s ON s.user=u.id WHERE token=? AND expires>? AND active=1",
            (fingerprint(token), time.time())).fetchone()
    req.state.csrf = csrf
    response = await call_next(req)
    if "campus_csrf" not in req.cookies:
        response.set_cookie("campus_csrf", csrf, httponly=True, samesite="strict", secure=SECURE)
    response.headers.update({"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                             "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY"})
    return response


def page(req, title, body, status=200):
    return HTMLResponse(layout(title, body, req.state.user, req.state.csrf,
                               req.query_params.get("notice", "")), status)


@app.exception_handler(HTTPException)
async def problem(req, exc):
    if exc.status_code == 401:
        return go("/admin/login" if req.url.path.startswith("/admin") else "/login")
    return page(req, "Request could not be completed", f'<p>{e(exc.detail)}</p><a href="/">Browse resources</a>', exc.status_code)


def go(url, notice=""):
    return RedirectResponse(url + ("?" + urlencode({"notice": notice}) if notice else ""), 303)


def user(req, admin=False):
    current = req.state.user
    if current is None:
        raise HTTPException(401)
    if admin and not current["admin"]:
        raise HTTPException(403, "Administrator access is required.")
    return current


async def submitted(req):
    data = await req.form(max_files=1, max_fields=24, max_part_size=LIMIT)
    csrf = data.get("csrf")
    if not isinstance(csrf, str) or not secrets.compare_digest(csrf.encode(), req.state.csrf.encode()):
        raise HTTPException(403, "Refresh the page and submit the form again.")
    return data


def string(data, key, maximum=200, optional=False):
    val = data.get(key, "")
    if not isinstance(val, str) or len(val) > maximum or (not optional and not val.strip()):
        raise HTTPException(400, f"Enter a valid {key} (up to {maximum} characters).")
    return val.strip()


def number(data, key, low=1, high=2147483647):
    try:
        n = int(data.get(key, ""))
        if low <= n <= high:
            return n
    except (ValueError, TypeError):
        pass
    raise HTTPException(400, f"Invalid {key}.")


def cats(db):
    return [(r["id"], r["name"]) for r in db.execute("SELECT * FROM categories ORDER BY name")]


@app.get("/login")
@app.get("/register")
@app.get("/admin/login")
def credentials(req: Request):
    registering = req.url.path == "/register"
    title = "Create student account" if registering else "Student login"
    if req.url.path == "/admin/login":
        title = "Administrator login"
    body = field("Display name", "name") if registering else ""
    body += field("Email", "email", "email") + field("Password (8 or more characters)" if registering else "Password", "password", "password")
    link = '<a href="/login">Log in</a>' if registering else '<a href="/register">Create a student account</a>'
    if req.url.path == "/admin/login":
        link = '<a href="/login">Student login</a>'
    elif not registering:
        link += ' · <a href="/admin/login">Administrator login</a>'
    return page(req, title, '<section>' + form(req.url.path, req.state.csrf, body, title) + link + '</section>')


@app.post("/register")
@app.post("/login")
@app.post("/admin/login")
async def authenticate(req: Request):
    data = await submitted(req)
    email = string(data, "email", 254).lower()
    pw = data.get("password", "")
    if not isinstance(pw, str) or len(pw) > 256:
        raise HTTPException(400, "Invalid password.")
    with database() as db:
        if req.url.path == "/register":
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(pw) < 8:
                raise HTTPException(400, "Enter a valid email and a password of at least eight characters.")
            try:
                db.execute("INSERT INTO users(email,name,password) VALUES(?,?,?)",
                           (email, string(data, "name", 80), password_hash(pw)))
            except sqlite3.IntegrityError:
                raise HTTPException(400, "An account already uses this email.")
        account = db.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
        if not account or not matches(pw, account["password"]) or (req.url.path == "/admin/login" and not account["admin"]):
            return page(req, "Login unsuccessful", f'<p>Check your credentials and account access.</p><a href="{req.url.path}">Try again</a>' , 403)
        token = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires<=? OR token=?", (time.time(), fingerprint(req.cookies.get("campus_session", ""))))
        db.execute("INSERT INTO sessions VALUES(?,?,?)", (fingerprint(token), account["id"], int(time.time()) + 86400))
    response = go("/admin" if req.url.path == "/admin/login" else "/")
    response.set_cookie("campus_session", token, max_age=86400, httponly=True, samesite="lax", secure=SECURE)
    return response


@app.post("/logout")
async def logout(req: Request):
    await submitted(req)
    with database() as db:
        db.execute("DELETE FROM sessions WHERE token=?", (fingerprint(req.cookies.get("campus_session", "")),))
    response = go("/login")
    response.delete_cookie("campus_session")
    return response


@app.get("/")
@app.get("/saved")
def listing(req: Request):
    who = user(req)
    saved = req.url.path == "/saved"
    q = req.query_params
    clauses, args = ["r.status='Available'"], []
    if saved:
        clauses.append("EXISTS(SELECT 1 FROM bookmarks b WHERE b.resource=r.id AND b.user=?)")
        args.append(who["id"])
    if q.get("q"):
        clauses.append("(" + " OR ".join(f"instr(lower(r.{k}),lower(?))>0" for k in ("title","subject","tags","description","course")) + ")")
        args.extend([q["q"]] * 5)
    filters = field("Search title, subject or tags", "q", value=q.get("q",""), required=False)
    with database() as db:
        for key, label, options in [
            ("subject","Subject",[(r[0],r[0]) for r in db.execute("SELECT DISTINCT subject FROM resources WHERE status='Available' ORDER BY subject")]),
            ("course","Course",[(r[0],r[0]) for r in db.execute("SELECT DISTINCT course FROM resources WHERE status='Available' ORDER BY course")]),
            ("semester","Semester",[(i,i) for i in range(1,13)]), ("category","Category",cats(db)),
            ("kind","File type",[("PDF","PDF"),("TXT","TXT")])]:
            filters += select(label,key,[("","All")]+options,q.get(key,""))
            if q.get(key):
                clauses.append(f"r.{key}=?")
                args.append(q[key])
        filters += select("Sort by","sort",[("new","Newest"),("title","Title"),("downloads","Most downloaded")],q.get("sort","new"))
        order = {"title":"r.title COLLATE NOCASE, r.id", "downloads":"r.downloads DESC, r.id DESC"}.get(q.get("sort"),"r.id DESC")
        index = number(q,"page",1,1000000) if q.get("page") else 1
        rows = db.execute(BASE + " WHERE " + " AND ".join(clauses) + " ORDER BY " + order + " LIMIT 25 OFFSET ?", (*args,(index-1)*24)).fetchall()
    body = '<form><div class="grid">'+filters+'</div><button>Search</button></form><div class="grid">'
    body += "".join(map(card,rows[:24])) or '<p>No resources match. Try another filter or upload your notes.</p>'
    body += "</div>"
    for show, target, label in [(index>1,index-1,"Previous"),(len(rows)>24,index+1,"Next")]:
        if show:
            body += f' <a href="?{e(urlencode(dict(q,page=target)))}">{label}</a>'
    return page(req, "Saved resources" if saved else "Resource library", body)


@app.get("/upload")
def upload_page(req: Request):
    user(req)
    with database() as db:
        categories = cats(db)
    fields = "".join(field(k.title(),k) for k in ("title","subject","course"))
    fields += select("Semester","semester",[(i,i) for i in range(1,13)]) + select("Category","category",categories)
    fields += field("Description","description","textarea") + field("Tags (comma-separated)","tags",required=False)
    fields += select("Download access","access",[("open","All registered students"),("restricted","Owner approval required")])
    fields += '<label>Academic file (PDF or UTF-8 TXT, up to 10 MiB)<input type="file" name="file" accept=".pdf,.txt" required></label>'
    fields += '<label><input style="width:auto;display:inline" type="checkbox" name="permission" required> I have permission to share this material.</label>'
    return page(req,"Upload a resource",form("/upload",req.state.csrf,fields,"Publish resource",True))


@app.post("/upload")
async def upload(req: Request):
    who = user(req)
    data = await submitted(req)
    try:
        f = data.get("file")
        if not hasattr(f,"read") or data.get("permission") != "on":
            raise HTTPException(400,"Choose a file and confirm sharing permission.")
        raw = await f.read(LIMIT+1)
        try:
            kind = file_kind(f.filename or "",raw)
        except ValueError as exc:
            raise HTTPException(400,str(exc))
        with database() as db:
            category = number(data,"category")
            if not db.execute("SELECT id FROM categories WHERE id=?",(category,)).fetchone():
                raise HTTPException(400,"Choose a current category.")
            access = string(data,"access")
            if access not in ("open","restricted"):
                raise HTTPException(400,"Choose a download access setting.")
            rid = db.execute("""INSERT INTO resources(owner,title,subject,course,semester,category,description,tags,kind,restricted)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(who["id"], string(data,"title"), string(data,"subject"),string(data,"course"),
                number(data,"semester",1,12),category,string(data,"description",4000),string(data,"tags",300,True),kind,access=="restricted")).lastrowid
            db.execute("INSERT INTO files VALUES(?,?)",(rid,raw))
            log(db,who["id"],"Uploaded",rid)
    finally:
        await data.close()
    return go(f"/r/{rid}","Resource published.")


def resource(db, rid, who):
    r = db.execute(BASE+" WHERE r.id=?",(rid,)).fetchone()
    if not r or (r["status"]!="Available" and not who["admin"] and r["owner"]!=who["id"]):
        raise HTTPException(404,"Resource unavailable.")
    return r


def can_download(db,r,who):
    if who["admin"]:
        return True
    if r["status"]!="Available":
        return False
    return (not r["restricted"] or who["id"]==r["owner"] or db.execute(
        "SELECT 1 FROM requests WHERE resource=? AND user=? AND decision='Approved'",(r["id"],who["id"])).fetchone())


@app.get("/r/{rid}")
def detail(req: Request,rid:int):
    who = user(req)
    url = f"/r/{rid}"
    def action(key, fields, button):
        return form(url+"/"+key,req.state.csrf,fields,button)
    with database() as db:
        r = resource(db,rid,who)
        body = (f'<section><p class="meta">{e(r["category_name"])} · {e(r["kind"])} · {e(r["status"])}</p>'
                f'<p>{e(r["subject"])} · {e(r["course"])} · Semester {r["semester"]}</p><p>{e(r["description"])}</p>'
                f'<p>Shared by {e(r["author"])} · {e(r["created"])} UTC</p><p>Tags: {e(r["tags"]) or "None"}</p>')
        if can_download(db,r,who):
            body += f'<a href="{url}/file">Download {e(r["kind"])}</a>'
        elif r["status"]=="Available":
            decision = db.execute("SELECT decision FROM requests WHERE user=? AND resource=?",(who["id"],rid)).fetchone()
            body += f'<p>Access request: {e(decision[0])}</p>' if decision else action("request","","Request download access")
        body += "</section>"
        if r["status"]=="Available":
            saved = db.execute("SELECT 1 FROM bookmarks WHERE user=? AND resource=?",(who["id"],rid)).fetchone()
            body += action("bookmark","","Remove bookmark" if saved else "Bookmark resource")
            body += '<section><h2>Student feedback</h2>'
            for row in db.execute("SELECT u.name,v.stars,v.feedback FROM reviews v JOIN users u ON v.user=u.id WHERE resource=?",(rid,)):
                body += f'<p><strong>{e(row["name"])} · {row["stars"]}/5</strong> {e(row["feedback"])}</p>'
            body += action("review",select("Your rating","stars",[(i,i) for i in range(1,6)])+
                           field("Your feedback","feedback","textarea",required=False),"Save rating")+"</section>"
            body += "<details><summary>Report this resource</summary>"+action("report",field("Reason","reason","textarea"),"Send for review")+"</details>"
        if who["id"]==r["owner"] or who["admin"]:
            for row in db.execute("SELECT u.id,u.name FROM requests a JOIN users u ON a.user=u.id WHERE resource=? AND decision='Pending'",(rid,)):
                body += action("decide",f'<input type="hidden" name="student" value="{row["id"]}">'+
                    select(f'Download request from {row["name"]}',"decision",[("Approved","Approve"),("Denied","Deny")]),"Save decision")
    return page(req,r["title"],body)


@app.get("/r/{rid}/file")
def download(req: Request,rid:int):
    who = user(req)
    with database() as db:
        r = resource(db,rid,who)
        if not can_download(db,r,who):
            raise HTTPException(403,"Download access is required.")
        data = db.execute("SELECT data FROM files WHERE resource=?",(rid,)).fetchone()[0]
        db.execute("UPDATE resources SET downloads=downloads+1 WHERE id=?",(rid,))
    return Response(data,media_type="application/pdf" if r["kind"]=="PDF" else "text/plain",
                    headers={"Content-Disposition":f'attachment; filename="campusshare-{rid}.{r["kind"].lower()}"'})


@app.post("/r/{rid}/{action}")
async def interact(req: Request,rid:int,action:str):
    who = user(req)
    uid = who["id"]
    d = await submitted(req)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        r = resource(db,rid,who)
        if r["status"]!="Available":
            raise HTTPException(409,"This resource is unavailable.")
        if action=="bookmark":
            removed = db.execute("DELETE FROM bookmarks WHERE user=? AND resource=?",(uid,rid)).rowcount
            if not removed:
                db.execute("INSERT INTO bookmarks VALUES(?,?)",(uid,rid))
        elif action=="review":
            db.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?)",(uid,rid,number(d,"stars",1,5),string(d,"feedback",1000,True)))
        elif action=="report":
            db.execute("INSERT INTO reports(user,resource,reason) VALUES(?,?,?)",(uid,rid,string(d,"reason",1500)))
            db.execute("UPDATE resources SET status='Under Review' WHERE id=?",(rid,))
            log(db,uid,"Reported",rid)
            return go("/","Report submitted for moderator review.")
        elif action=="request" and r["restricted"] and uid!=r["owner"]:
            db.execute("INSERT OR IGNORE INTO requests(user,resource) VALUES(?,?)",(uid,rid))
        elif action=="decide" and (uid==r["owner"] or who["admin"]):
            decision = string(d,"decision")
            if decision not in ("Approved","Denied"):
                raise HTTPException(400,"Choose a valid decision.")
            db.execute("UPDATE requests SET decision=? WHERE resource=? AND user=? AND decision='Pending'",
                       (decision,rid,number(d,"student")))
        else:
            raise HTTPException(403,"Action unavailable.")
    return go(f"/r/{rid}","Changes saved.")


@app.get("/account")
def account(req: Request):
    who = user(req)
    body = '<section>'+form("/account",req.state.csrf,field("Display name","name",value=who["name"]),"Update profile")+"</section><h2>My uploads</h2>"
    with database() as db:
        rows = db.execute(BASE+" WHERE owner=? ORDER BY r.id DESC",(who["id"],)).fetchall()
        body += "".join(f'<p>{e(r["status"])} · <a href="/r/{r["id"]}">{e(r["title"])}</a></p>' for r in rows) or "<p>No uploads yet.</p>"
        body += "<h2>Incoming download requests</h2>"
        pending = db.execute("SELECT DISTINCT r.id,r.title FROM resources r JOIN requests a ON a.resource=r.id WHERE r.owner=? AND a.decision='Pending' AND r.status='Available'",(who["id"],)).fetchall()
        body += "".join(f'<p><a href="/r/{r["id"]}">{e(r["title"])}</a></p>' for r in pending) or "<p>No pending requests.</p>"
    return page(req,"My account",body)


@app.post("/account")
async def edit_account(req: Request):
    who = user(req)
    d = await submitted(req)
    with database() as db:
        db.execute("UPDATE users SET name=? WHERE id=?",(string(d,"name",80),who["id"]))
    return go("/account","Profile updated.")


@app.get("/admin")
def admin(req: Request):
    user(req,True)
    def control(action,body,button):
        return form("/admin/"+action,req.state.csrf,body,button)
    with database() as db:
        total, downloads = db.execute("SELECT count(*),coalesce(sum(downloads),0) FROM resources").fetchone()
        students = db.execute("SELECT count(*) FROM users").fetchone()[0]
        body = f'<p>{students} accounts · {total} uploads · {downloads} downloads</p><section><h2>Reports awaiting review</h2>'
        reports = db.execute("SELECT p.*,r.title FROM reports p JOIN resources r ON r.id=p.resource WHERE resolved=0").fetchall()
        for p in reports:
            body += f'<p><a href="/r/{p["resource"]}">{e(p["title"])}</a> · {e(p["reason"])}</p>'
            body += control("moderate",f'<input type="hidden" name="resource" value="{p["resource"]}">'+select("Decision","decision",[("Available","Approve resource"),("Removed","Remove resource")]),"Resolve report")
        if not reports:
            body += "<p>No open reports.</p>"
        body += "</section><section><h2>Resource categories</h2>"
        body += control("add",field("New category","name"),"Add category")
        choices = cats(db)
        if choices:
            pick = select("Category","category",choices)
            body += control("rename",pick+field("New name","name"),"Rename")
            body += control("delete",pick,"Delete unused category")
        body += "</section><section><h2>Student accounts</h2>"
        for u in db.execute("SELECT id,name,email,active FROM users WHERE admin=0 ORDER BY name"):
            body += control("account",f'<p>{e(u["name"])} · {e(u["email"])}</p><input type="hidden" name="student" value="{u["id"]}"><input type="hidden" name="active" value="{1-u["active"]}">',
                            "Suspend" if u["active"] else "Reactivate")
        body += "</section><section><h2>Recent activity</h2>"
        for row in db.execute("SELECT a.*,u.name FROM audit a JOIN users u ON u.id=a.actor ORDER BY a.id DESC LIMIT 40"):
            body += f'<p>{e(row["created"])} UTC · {e(row["name"])} · {e(row["action"])}'+(f' · Resource {row["resource"]}' if row["resource"] else "")+"</p>"
    return page(req,"Administration",body+"</section>")


@app.post("/admin/{action}")
async def manage(req: Request,action:str):
    who = user(req,True)
    d = await submitted(req)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if action=="moderate":
                rid = number(d,"resource")
                decision = string(d,"decision")
                if decision not in ("Available","Removed") or not db.execute(
                    "UPDATE resources SET status=? WHERE id=? AND status='Under Review'",(decision,rid)).rowcount:
                    raise HTTPException(409,"This report or decision is unavailable.")
                db.execute("UPDATE reports SET resolved=1 WHERE resource=?",(rid,))
                log(db,who["id"],"Moderated: "+decision,rid)
            elif action in ("add","rename","delete"):
                if action=="add":
                    db.execute("INSERT INTO categories(name) VALUES(?)",(string(d,"name",100),))
                elif action=="rename":
                    db.execute("UPDATE categories SET name=? WHERE id=?",(string(d,"name",100),number(d,"category")))
                else:
                    db.execute("DELETE FROM categories WHERE id=?",(number(d,"category"),))
                log(db,who["id"],"Category: "+action)
            elif action=="account":
                uid = number(d,"student")
                active = number(d,"active",0,1)
                if not db.execute("UPDATE users SET active=? WHERE id=? AND admin=0",(active,uid)).rowcount:
                    raise HTTPException(400,"Select a student account.")
                db.execute("DELETE FROM sessions WHERE user=?",(uid,))
                log(db,who["id"],f"Account {uid}: "+("reactivated" if active else "suspended"))
            else:
                raise HTTPException(404,"Unknown action.")
        except sqlite3.IntegrityError:
            raise HTTPException(400,"Category names must be unique. Only unused categories can be deleted.")
    return go("/admin","Changes saved.")
