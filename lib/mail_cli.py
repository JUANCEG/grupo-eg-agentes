#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Correo por IMAP (Gmail con contraseña de aplicación) para los agentes en la nube. NUNCA envía: solo lee y deja BORRADORES.
Variables de entorno: MAIL_<CUENTA>_USER y MAIL_<CUENTA>_PASS (cuentas: KLAR, LAVACLINICAS, OMICRON, TECNOLAVEX).
  python lib/mail_cli.py list <cuenta> [--dias 2] [--max 40] [--no-leidos]
  python lib/mail_cli.py get <cuenta> <uid> [--max-chars 5000]
  python lib/mail_cli.py search <cuenta> "texto" [--dias 60] [--max 20]
  python lib/mail_cli.py draft <cuenta> --to a@b.com --subject "..." --body-file ruta.txt [--cc x@y] [--reply-uid UID]
"""
import os, sys, re, json, html, time, email, imaplib, argparse, socket
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

sys.stdout.reconfigure(encoding="utf-8")
CUENTAS = ("klar", "lavaclinicas", "omicron", "tecnolavex")


def _retry(fn, tries=4, wait=3):
    for i in range(tries):
        try:
            return fn()
        except (socket.gaierror, ConnectionError, TimeoutError, OSError):
            if i == tries - 1:
                raise
            time.sleep(wait * (i + 1))


def _cred(c):
    try:
        return os.environ[f"MAIL_{c.upper()}_USER"], os.environ[f"MAIL_{c.upper()}_PASS"]
    except KeyError as e:
        sys.exit(f"Falta la variable de entorno {e} (cuenta '{c}' sin conectar)")


def _imap(c, readonly=True, folder="INBOX"):
    u, p = _cred(c)

    def go():
        im = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=40)
        im.login(u, p)
        return im
    im = _retry(go)
    if folder:
        im.select(folder, readonly=readonly)
    return im, u


def _dec(v):
    try:
        return str(make_header(decode_header(v or ""))).strip()
    except Exception:
        return (v or "").strip()


def _hdrs(im, uids):
    rows = []
    for u in uids:
        st, d = im.uid("fetch", u, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
        if st != "OK" or not d or not isinstance(d[0], tuple):
            continue
        meta = d[0][0].decode("utf-8", "ignore")
        m = email.message_from_bytes(d[0][1])
        rows.append({"uid": u.decode() if isinstance(u, bytes) else str(u), "leido": "\\Seen" in meta, "de": _dec(m["From"])[:90],
                     "para": _dec(m["To"])[:70], "asunto": _dec(m["Subject"])[:120], "fecha": (m["Date"] or "")[:31]})
    return rows


def lst(c, dias, mx, nl):
    im, u = _imap(c)
    since = (datetime.now() - timedelta(days=dias)).strftime("%d-%b-%Y")
    st, d = im.uid("search", None, *(["SINCE", since] + (["UNSEEN"] if nl else [])))
    uids = d[0].split()[-mx:] if d and d[0] else []
    rows = _hdrs(im, uids)
    im.logout()
    return {"cuenta": u, "desde": since, "total_ventana": len(uids), "correos": rows[::-1]}


def _text(msg):
    plain, htmls, adj = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_filename():
            adj.append(_dec(part.get_filename()))
            continue
        try:
            pl = part.get_payload(decode=True)
            t = pl.decode(part.get_content_charset() or "utf-8", "ignore") if pl else ""
        except Exception:
            continue
        (plain if part.get_content_type() == "text/plain" else htmls if part.get_content_type() == "text/html" else []).append(t)
    body = "\n".join(plain).strip()
    if not body and htmls:
        h = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(htmls))
        h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
        body = html.unescape(re.sub(r"<[^>]+>", " ", h))
    body = re.sub(r"\n\s*\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", body)).strip()
    return body, adj


def get(c, uid, mx):
    im, _ = _imap(c)
    st, d = im.uid("fetch", str(uid), "(BODY.PEEK[])")
    im.logout()
    if st != "OK" or not d or not isinstance(d[0], tuple):
        sys.exit("no se pudo leer ese uid")
    m = email.message_from_bytes(d[0][1])
    b, adj = _text(m)
    return {"uid": str(uid), "de": _dec(m["From"]), "para": _dec(m["To"]), "cc": _dec(m["Cc"]), "asunto": _dec(m["Subject"]), "fecha": m["Date"],
            "message_id": m["Message-ID"], "adjuntos": adj, "cuerpo": b[:mx] + ("…[recortado]" if len(b) > mx else "")}


def search(c, texto, dias, mx):
    im, u = _imap(c)
    since = (datetime.now() - timedelta(days=dias)).strftime("%d-%b-%Y")
    uids = set()
    for fld in ("SUBJECT", "FROM", "BODY"):
        try:
            im.literal = texto.encode("utf-8")
            st, d = im.uid("search", "CHARSET", "UTF-8", "SINCE", since, fld)
            if st == "OK" and d and d[0]:
                uids.update(d[0].split())
        except Exception:
            pass
    uids = sorted(uids, key=lambda x: int(x))[-mx:]
    rows = _hdrs(im, uids)
    im.logout()
    return {"cuenta": u, "busqueda": texto, "resultados": rows[::-1]}


def draft(c, to, subject, body, cc=None, reply_uid=None):
    u, p = _cred(c)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = u, to, subject
    if cc:
        msg["Cc"] = cc
    msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid()
    if reply_uid:
        o = get(c, reply_uid, 10)
        if o.get("message_id"):
            msg["In-Reply-To"] = msg["References"] = o["message_id"]
    msg.set_content(body)
    im = _retry(lambda: (lambda x: (x.login(u, p), x)[1])(imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=40)))
    folder = "[Gmail]/Drafts"
    for x in im.list()[1] or []:
        s = x.decode("utf-8", "ignore")
        if "\\Drafts" in s:
            mm = re.search(r'"([^"]+)"\s*$', s)
            folder = mm.group(1) if mm else folder
    st, r = im.append(f'"{folder}"', "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    im.logout()
    if st != "OK":
        sys.exit(f"no se pudo guardar el borrador: {r}")
    return {"ok": True, "cuenta": u, "carpeta": folder, "para": to, "asunto": subject}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("list"); a.add_argument("cuenta", choices=CUENTAS); a.add_argument("--dias", type=int, default=2); a.add_argument("--max", type=int, default=40); a.add_argument("--no-leidos", action="store_true")
    g = sp.add_parser("get"); g.add_argument("cuenta", choices=CUENTAS); g.add_argument("uid"); g.add_argument("--max-chars", type=int, default=5000)
    s = sp.add_parser("search"); s.add_argument("cuenta", choices=CUENTAS); s.add_argument("texto"); s.add_argument("--dias", type=int, default=60); s.add_argument("--max", type=int, default=20)
    d = sp.add_parser("draft"); d.add_argument("cuenta", choices=CUENTAS); d.add_argument("--to", required=True); d.add_argument("--subject", required=True); d.add_argument("--body-file", required=True); d.add_argument("--cc"); d.add_argument("--reply-uid")
    x = ap.parse_args()
    if x.cmd == "list":
        r = lst(x.cuenta, x.dias, x.max, x.no_leidos)
    elif x.cmd == "get":
        r = get(x.cuenta, x.uid, x.max_chars)
    elif x.cmd == "search":
        r = search(x.cuenta, x.texto, x.dias, x.max)
    else:
        r = draft(x.cuenta, x.to, x.subject, open(x.body_file, encoding="utf-8").read(), x.cc, x.reply_uid)
    print(json.dumps(r, ensure_ascii=False, indent=1))
