"""Integration tests against the Python web interface and an isolated SQLite DB."""
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import app
from backend import LIMIT, database, file_kind


class CampusShareTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        folder = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, CAMPUS_DB=os.path.join(folder, "test.db")))
        self.owner, self.student, self.mod = [stack.enter_context(TestClient(app)) for _ in range(3)]
        for client, name in [(self.owner, "Owner"), (self.student, "Student"), (self.mod, "Moderator")]:
            client.get("/register")
            response = self.post(client, "/register", name=name, email=name+"@example.org", password="campus-test")
            self.assertIn("Resource library", response.text)
        with database() as db:
            db.execute("UPDATE users SET admin=1 WHERE name='Moderator'")

    def post(self, client, path, files=None, **data):
        data["csrf"] = client.cookies["campus_csrf"]
        return client.post(path, data=data, files=files)

    def upload(self, access="open", title="Signals lab", filename="notes.txt"):
        return self.post(self.owner, "/upload", files={"file": (filename,b"Fourier notes")}, title=title,
                         course="ENTC", subject="Signals", semester="4", category="1", description="Lab notes",
                         tags="DSP", access=access, permission="on")

    def test_accounts_and_permissions(self):
        self.assertEqual(self.student.get("/admin").status_code,403)
        self.assertEqual(self.student.post("/account",data={"name":"Other"}).status_code,403)
        self.post(self.student,"/logout")
        self.assertEqual(self.student.get("/upload").url.path,"/login")
        self.assertEqual(self.post(self.student,"/login",email="Student@example.org",password="incorrect").status_code,403)
        self.assertEqual(self.post(self.student,"/register",name="S",email="Student@example.org",password="campus-test").status_code,400)
        self.assertEqual(self.post(self.student,"/login",email="Student@example.org",password="campus-test").url.path,"/")
        self.assertIn("New name",self.post(self.student,"/account",name="New name").text)

    def test_upload_discovery_and_moderation(self):
        self.assertEqual(self.upload(filename="notes.exe").status_code,400)
        self.assertEqual(self.upload(title="").status_code,400)
        self.assertIn("Resource published",self.upload().text)
        self.assertIn("Signals lab",self.student.get("/?q=signals&semester=4&category=1&kind=TXT").text)
        self.assertIn("No resources match",self.student.get("/?q=mathematics").text)
        self.post(self.student,"/r/1/bookmark")
        self.assertIn("Signals lab",self.student.get("/saved").text)
        self.assertIn("Good notes",self.post(self.student,"/r/1/review",stars=4,feedback="Good notes").text)
        self.assertEqual(self.student.get("/r/1/file").content,b"Fourier notes")
        self.post(self.student,"/r/1/report",reason="Outdated edition")
        self.assertEqual(self.student.get("/r/1/file").status_code,404)
        self.assertIn("Outdated edition",self.mod.get("/admin").text)
        self.post(self.mod,"/admin/moderate",resource=1,decision="Available")
        self.assertEqual(self.student.get("/r/1/file").status_code,200)
        self.post(self.student,"/r/1/report",reason="Wrong course")
        self.post(self.mod,"/admin/moderate",resource=1,decision="Removed")
        self.assertEqual(self.student.get("/r/1").status_code,404)

    def test_restricted_download(self):
        self.upload(access="restricted")
        self.assertEqual(self.student.get("/r/1/file").status_code,403)
        self.post(self.student,"/r/1/request")
        self.assertIn("Pending",self.student.get("/r/1").text)
        self.assertEqual(self.post(self.student,"/r/1/decide",student=2,decision="Approved").status_code,403)
        self.post(self.owner,"/r/1/decide",student=2,decision="Approved")
        self.assertEqual(self.student.get("/r/1/file").content,b"Fourier notes")

    def test_admin_controls(self):
        self.post(self.mod,"/admin/add",name="Worksheets")
        self.assertIn("Worksheets",self.owner.get("/upload").text)
        self.post(self.mod,"/admin/rename",category=6,name="Assignments")
        self.assertIn("Assignments",self.owner.get("/upload").text)
        self.post(self.mod,"/admin/delete",category=6)
        self.assertNotIn("Assignments",self.owner.get("/upload").text)
        self.post(self.mod,"/admin/account",student=2,active=0)
        self.assertEqual(self.student.get("/saved").url.path,"/login")
        self.assertEqual(self.post(self.student,"/login",email="Student@example.org",password="campus-test").status_code,403)

    def test_upload_boundaries(self):
        for size in (LIMIT-1,LIMIT):
            self.assertEqual(file_kind("notes.txt",b"a"*size),"TXT")
        for data in (b"", b"a"*(LIMIT+1), b"\x00"):
            with self.assertRaises(ValueError):
                file_kind("notes.txt",data)


class DemoTests(unittest.TestCase):
    def test_demo_accounts_data_and_restart(self):
        from demo import seed
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, CAMPUS_DB=os.path.join(folder, "demo.db")))
        seed()
        client = self.enterContext(TestClient(app))
        self.assertEqual(client.get("/admin").url.path, "/admin/login")
        def login(role, password, path):
            client.get(path)
            return client.post(path, data={"csrf": client.cookies["campus_csrf"],
                               "email": role+"@campus.example", "password": password})
        self.assertEqual(login("student","CampusStudent42!","/admin/login").status_code,403)
        self.assertEqual(login("admin","CampusAdmin42!","/admin/login").url.path,"/admin")
        self.assertIn("omits the signal bandwidth",client.get("/admin").text)
        self.assertEqual(login("student","CampusStudent42!","/login").url.path,"/")
        self.assertIn("CMOS inverter worksheet",client.get("/saved").text)
        self.assertIn("Pending",client.get("/r/2").text)
        self.assertEqual(client.get("/r/2/file").status_code,403)
        self.assertIn(b"truth table",client.get("/r/1/file").content)
        self.assertNotIn("Sampling theory revision draft",client.get("/").text)
        with database() as db:
            db.execute("UPDATE users SET name='Edited' WHERE email='owner@campus.example'")
        seed()
        with database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM files").fetchone()[0],10)
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0],3)
            self.assertTrue(db.execute("SELECT 1 FROM users WHERE name='Edited'").fetchone())


if __name__ == "__main__":
    unittest.main()
