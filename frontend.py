"""Server-rendered Python UI. Escape all user-controlled values at output."""
from html import escape

def e(value):
    return escape(str(value), quote=True)


STYLE = """
*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#172a40;font:16px/1.5 system-ui,sans-serif}
header{background:#142d43;color:white}nav,main{max-width:1050px;margin:auto;padding:18px 24px}
nav{display:flex;gap:18px;align-items:center;flex-wrap:wrap}nav strong{margin-right:auto;font-size:1.45rem}
nav a{color:white}a{color:#075e69;text-underline-offset:3px}main{padding-bottom:60px}
h1{font-size:clamp(2rem,5vw,3rem);letter-spacing:-.045em;margin:24px 0 12px}h2{font-size:1.3rem}
.card,section{background:white;border:1px solid #cfdae1;border-radius:12px;padding:18px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(210px,100%),1fr));gap:12px}
label{display:block;margin:8px 0;font-weight:600}input,select,textarea,button{font:inherit}
input,textarea,select{display:block;width:100%;padding:9px;border:1px solid #8698a4;border-radius:6px}
textarea{min-height:80px}button{cursor:pointer;border:0;background:#096467;color:white;border-radius:6px;padding:8px 14px}
form{margin:8px 0}nav form{margin:0}.meta{color:#486172}.notice{background:#dff3ea;padding:12px;border-radius:8px}
p{overflow-wrap:anywhere}article h2{margin:4px 0}details{margin:14px 0}summary{cursor:pointer;font-weight:600}
"""


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


def layout(title, body, user, csrf, notice=""):
    links = ""
    if user:
        links = '<a href="/">Browse</a><a href="/upload">Upload</a><a href="/saved">Saved</a><a href="/account">Account</a>'
        if user["admin"]:
            links += '<a href="/admin">Admin</a>'
        links += form("/logout", csrf, "", "Log out")
    note = f'<p class="notice" role="status">{e(notice)}</p>' if notice else ""
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(title)} · CampusShare</title><style>{STYLE}</style><header><nav><strong>CampusShare</strong>{links}</nav></header>'
            f'<main><h1>{e(title)}</h1>{note}{body}</main></html>')


def card(r):
    return (f'<article class="card"><span class="meta">{e(r["category_name"])} · {e(r["kind"])}</span>'
            f'<h2><a href="/r/{r["id"]}">{e(r["title"])}</a></h2>'
            f'<p>{e(r["subject"])} · {e(r["course"])} · Semester {r["semester"]}</p></article>')
