"""Server-rendered Python UI. Escape all user-controlled values at output."""
from html import escape
from pathlib import Path

def e(value):
    return escape(str(value), quote=True)


STYLE = Path(__file__).with_name("campus.css").read_text(encoding="utf-8")


def field(label, name, kind="text", value="", required=True):
    req = " required" if required else ""
    if kind == "textarea":
        widget = f'<textarea name="{name}"{req}>{e(value)}</textarea>'
    else:
        widget = f'<input type="{kind}" name="{name}" value="{e(value)}"{req}>'
    return f"<label>{e(label)}{widget}</label>"


def select(label, name, options, value=""):
    opts = "".join(f'<option value="{e(k)}"{" selected" if str(k)==str(value) else ""}>{e(v)}</option>'
                   for k, v in options)
    return f'<label>{e(label)}<select name="{name}">{opts}</select></label>'


def form(action, csrf, body, button, upload=False):
    enctype = ' enctype="multipart/form-data"' if upload else ""
    return (f'<form method="post" action="{e(action)}"{enctype}>'
            f'<input type="hidden" name="csrf" value="{e(csrf)}">{body}<button>{e(button)}</button></form>')


def layout(title, body, user, csrf, notice="", path=""):
    links = ""
    if user:
        items = [("/", "Library"), ("/saved", "Saved"), ("/upload", "Upload"), ("/account", "Account")]
        if user["admin"]:
            items.append(("/admin", "Admin"))
        for url, label in items:
            current = ' aria-current="page"' if path == url else ""
            links += f'<a href="{url}"{current}>{label}</a>'
        links += form("/logout", csrf, "", "Log out")
    descriptions = {
        "/": "Explore notes, lab manuals and practice papers shared by students.",
        "/saved": "Revisit the resources you bookmarked.",
        "/admin": "Review reported materials and manage student access.",
        "/login": "Sign in to your student library.",
        "/admin/login": "Sign in to review reports and manage the library.",
    }
    intro = f"<p>{descriptions[path]}</p>" if path in descriptions else ""
    note = f'<p class="notice" role="status">{e(notice)}</p>' if notice else ""
    auth = ' class="auth"' if path in ("/login", "/admin/login", "/register") else ""
    art = '<span class="shelf" aria-hidden="true"><i></i><i></i><i></i><i></i></span>'
    brand = '<a class="brand" href="/"><span class="mark" aria-hidden="true"><i></i><i></i><i></i></span>CampusShare</a>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(title)} · CampusShare</title><style>{STYLE}</style></head><body><a class="skip" href="#main">Skip to content</a>'
            f'<header><nav aria-label="Main navigation">{brand}{links}</nav></header><main id="main"{auth}>'
            f'<div class="hero"><h1>{e(title)}</h1>{intro}{art}</div>{note}{body}</main></body></html>')


def card(r):
    access = "Approval required" if r["restricted"] else "Open download"
    return (f'<article class="card"><div class="cover t{r["category"] % 5}">{e(r["category_name"])}</div>'
            f'<div class="card-info"><span class="meta">{e(r["subject"])} · Sem {r["semester"]}</span>'
            f'<h2><a href="/r/{r["id"]}">{e(r["title"])}</a></h2><p>{e(r["course"])}</p></div>'
            f'<footer>{e(r["kind"])} · {access}</footer></article>')
