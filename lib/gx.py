#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gx.py — herramienta unica de los agentes del Grupo EG en la nube (Odoo, SIIGO, correo IMAP). Solo libreria estandar.
Credenciales SOLO por variables de entorno (nunca se imprimen):
  ODOO_URL ODOO_DB ODOO_USER ODOO_API_KEY | SIIGO_<EMP>_USER SIIGO_<EMP>_KEY SIIGO_PARTNER_ID | MAIL_<CUENTA>_USER MAIL_<CUENTA>_PASS
Empresas SIIGO: omicron klar lavaclinicas tecnolavex. Cuentas de correo: klar lavaclinicas omicron tecnolavex.

  python3 gx.py odoo-sr <modelo> --domain '[...]' --fields a,b [--limit N] [--order 'x desc'] [--inactivos]
  python3 gx.py odoo-note <modelo> <id> --body 'texto'
  python3 gx.py odoo-call <modelo> <metodo> --args '[...]' [--kw '{...}']
  python3 gx.py siigo-cartera <empresa> | siigo-ingresos <empresa> <AAAA-MM> | siigo-clientes <empresa>
  python3 gx.py mail-list <cuenta> [--dias 2] [--max 40] [--no-leidos]      (no marca como leido)
  python3 gx.py mail-get <cuenta> <uid> [--max-chars 5000]
  python3 gx.py mail-search <cuenta> 'texto' [--dias 60] [--max 20]
  python3 gx.py mail-draft <cuenta> --to a@b.com --subject 'x' --body-file ruta.txt [--cc x@y] [--reply-uid UID]   (BORRADOR; nunca envia)
"""
import os, sys, re, json, time, html, socket, argparse, imaplib, email, urllib.request, xmlrpc.client
from datetime import date, datetime, timedelta
from calendar import monthrange
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

sys.stdout.reconfigure(encoding="utf-8")
ALL = [1, 2, 3, 4, 5, 6, 7, 8, 9]


def retry(fn, tries=4, wait=3):
    for i in range(tries):
        try:
            return fn()
        except (socket.gaierror, ConnectionError, TimeoutError, OSError):
            if i == tries - 1:
                raise
            time.sleep(wait * (i + 1))


def out(o):
    print(o if isinstance(o, str) else json.dumps(o, ensure_ascii=False, indent=1))


def need(*names):
    try:
        return [os.environ[n] for n in names]
    except KeyError as e:
        sys.exit(f"Falta la variable de entorno {e}")


# ---------------- Odoo ----------------
_o = {}


def odoo(model, method, args, **kw):
    if not _o:
        u, d, usr, key = need("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_API_KEY")
        uid = retry(lambda: xmlrpc.client.ServerProxy(f"{u}/xmlrpc/2/common").authenticate(d, usr, key, {}))
        if not uid:
            sys.exit("Autenticacion Odoo fallida")
        _o.update(d=d, k=key, uid=uid, m=xmlrpc.client.ServerProxy(f"{u}/xmlrpc/2/object"))
    kw.setdefault("context", {"allowed_company_ids": ALL})
    try:
        return retry(lambda: _o["m"].execute_kw(_o["d"], _o["uid"], _o["k"], model, method, args, kw))
    except xmlrpc.client.Fault as e:
        last = [l for l in str(e.faultString).strip().splitlines() if l.strip()][-1]
        sys.exit(f"ERROR Odoo {model}.{method}: {last[:300]}")


# ---------------- SIIGO ----------------
def siigo_hdr(emp):
    u, k = need(f"SIIGO_{emp.upper()}_USER", f"SIIGO_{emp.upper()}_KEY")
    pid = os.environ.get("SIIGO_PARTNER_ID", "grupoEgAutomatizacion")
    req = urllib.request.Request("https://api.siigo.com/auth", data=json.dumps({"username": u, "access_key": k}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Partner-Id": pid})
    tok = json.loads(retry(lambda: urllib.request.urlopen(req, timeout=25)).read().decode())["access_token"]
    return {"Authorization": f"Bearer {tok}", "Partner-Id": pid}


def sget(url, h):
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25).read().decode())
        except Exception:
            time.sleep(2 * (i + 1))
    return {}


_names = {}


def cname(ident, h):
    if ident not in _names:
        c = (sget("https://api.siigo.com/v1/customers?identification=" + str(ident), h).get("results") or [{}])[0]
        _names[ident] = c.get("commercial_name") or " ".join(c.get("name") or []).strip() or "Cliente sin nombre"
    return _names[ident]


def invoices(h, desde=None, hasta=None, maxp=25):
    p = 1
    while p <= maxp:
        q = f"https://api.siigo.com/v1/invoices?page={p}&page_size=100" + (f"&created_start={desde}" if desde else "") + (f"&created_end={hasta}" if hasta else "")
        res = sget(q, h).get("results") or []
        if not res:
            return
        yield from res
        p += 1


# ---------------- Correo ----------------
def dec(v):
    try:
        return str(make_header(decode_header(v or ""))).strip()
    except Exception:
        return (v or "").strip()


def imap(cta, readonly=True, folder="INBOX"):
    u, p = need(f"MAIL_{cta.upper()}_USER", f"MAIL_{cta.upper()}_PASS")

    def c():
        im = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=40)
        im.login(u, p)
        return im
    im = retry(c)
    if folder:
        im.select(folder, readonly=readonly)
    return im, u


def headers(im, uids):
    rows = []
    for u in uids:
        st, d = im.uid("fetch", u, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
        if st != "OK" or not d or not isinstance(d[0], tuple):
            continue
        msg = email.message_from_bytes(d[0][1])
        rows.append({"uid": u.decode(), "leido": "\\Seen" in d[0][0].decode("utf-8", "ignore"), "de": dec(msg["From"])[:90],
                     "asunto": dec(msg["Subject"])[:120], "fecha": (msg["Date"] or "")[:31]})
    return rows


def body_of(msg):
    plain, hts, adj = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_filename():
            adj.append(dec(part.get_filename()))
            continue
        try:
            raw = part.get_payload(decode=True)
            t = raw.decode(part.get_content_charset() or "utf-8", "ignore") if raw else ""
        except Exception:
            continue
        (plain if part.get_content_type() == "text/plain" else hts if part.get_content_type() == "text/html" else []).append(t)
    b = "\n".join(plain).strip()
    if not b and hts:
        h = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(hts))
        b = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)))
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", b)).strip(), adj


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("odoo-sr"); a.add_argument("modelo"); a.add_argument("--domain", default="[]"); a.add_argument("--fields", default="name")
    a.add_argument("--limit", type=int, default=50); a.add_argument("--order", default=""); a.add_argument("--inactivos", action="store_true")
    n = sp.add_parser("odoo-note"); n.add_argument("modelo"); n.add_argument("id"); n.add_argument("--body", required=True)
    k = sp.add_parser("odoo-call"); k.add_argument("modelo"); k.add_argument("metodo"); k.add_argument("--args", default="[]"); k.add_argument("--kw", default="{}")
    for c in ("siigo-cartera", "siigo-clientes"):
        s = sp.add_parser(c); s.add_argument("empresa")
    s = sp.add_parser("siigo-ingresos"); s.add_argument("empresa"); s.add_argument("mes")
    m = sp.add_parser("mail-list"); m.add_argument("cuenta"); m.add_argument("--dias", type=int, default=2); m.add_argument("--max", type=int, default=40); m.add_argument("--no-leidos", action="store_true")
    g = sp.add_parser("mail-get"); g.add_argument("cuenta"); g.add_argument("uid"); g.add_argument("--max-chars", type=int, default=5000)
    q = sp.add_parser("mail-search"); q.add_argument("cuenta"); q.add_argument("texto"); q.add_argument("--dias", type=int, default=60); q.add_argument("--max", type=int, default=20)
    d = sp.add_parser("mail-draft"); d.add_argument("cuenta"); d.add_argument("--to", required=True); d.add_argument("--subject", required=True)
    d.add_argument("--body-file", required=True); d.add_argument("--cc"); d.add_argument("--reply-uid")
    x = ap.parse_args()
    c = x.cmd
    if c == "odoo-sr":
        kw = {"fields": x.fields.split(","), "limit": x.limit}
        if x.order:
            kw["order"] = x.order
        if x.inactivos:
            kw["context"] = {"allowed_company_ids": ALL, "active_test": False}
        out(odoo(x.modelo, "search_read", [json.loads(x.domain)], **kw))
    elif c == "odoo-note":
        out(odoo(x.modelo, "message_post", [[int(x.id)]], body=x.body))
    elif c == "odoo-call":
        out(odoo(x.modelo, x.metodo, json.loads(x.args), **json.loads(x.kw)))
    elif c == "siigo-cartera":
        h, por = siigo_hdr(x.empresa), {}
        for f in invoices(h, maxp=3):
            bal = f.get("balance") or 0
            if bal > 0:
                dues = [p.get("due_date") for p in f.get("payments", []) if p.get("due_date")]
                dias = (date.today() - datetime.strptime(min(dues), "%Y-%m-%d").date()).days if dues else None
                e = por.setdefault(cname((f.get("customer") or {}).get("identification"), h), {"saldo": 0, "max_dias": None, "facturas": 0})
                e["saldo"] += bal; e["facturas"] += 1
                if dias is not None:
                    e["max_dias"] = max(dias, e["max_dias"] or dias)
        out(sorted(({"cliente": k_, **v} for k_, v in por.items()), key=lambda z: -(z["max_dias"] or 0)))
    elif c == "siigo-ingresos":
        h = siigo_hdr(x.empresa); y, mo = map(int, x.mes.split("-"))
        out({"empresa": x.empresa, "mes": x.mes, "total": sum((f.get("total") or 0) for f in invoices(h, f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{monthrange(y, mo)[1]:02d}", 15))})
    elif c == "siigo-clientes":
        h = siigo_hdr(x.empresa); ids = {}
        for f in invoices(h, (date.today() - timedelta(days=548)).isoformat()):
            i = (f.get("customer") or {}).get("identification")
            if i:
                ids[i] = 1
        out(sorted({cname(i, h) for i in list(ids)[:600]}))
    elif c == "mail-list":
        im, u = imap(x.cuenta)
        crit = ["SINCE", (datetime.now() - timedelta(days=x.dias)).strftime("%d-%b-%Y")] + (["UNSEEN"] if x.no_leidos else [])
        st, dd = im.uid("search", None, *crit); uids = dd[0].split()[-x.max:] if dd and dd[0] else []
        out({"cuenta": u, "total_ventana": len(uids), "correos": headers(im, uids)[::-1]}); im.logout()
    elif c == "mail-get":
        im, u = imap(x.cuenta); st, dd = im.uid("fetch", x.uid, "(BODY.PEEK[])"); im.logout()
        msg = email.message_from_bytes(dd[0][1]); b, adj = body_of(msg)
        out({"uid": x.uid, "de": dec(msg["From"]), "para": dec(msg["To"]), "asunto": dec(msg["Subject"]), "fecha": msg["Date"], "adjuntos": adj,
             "cuerpo": b[:x.max_chars] + ("…[recortado]" if len(b) > x.max_chars else "")})
    elif c == "mail-search":
        im, u = imap(x.cuenta); since = (datetime.now() - timedelta(days=x.dias)).strftime("%d-%b-%Y"); found = set()
        for fld in ("SUBJECT", "FROM", "BODY"):
            try:
                im.literal = x.texto.encode("utf-8"); st, dd = im.uid("search", "CHARSET", "UTF-8", "SINCE", since, fld)
                if st == "OK" and dd and dd[0]:
                    found.update(dd[0].split())
            except Exception:
                pass
        out({"cuenta": u, "resultados": headers(im, sorted(found, key=int)[-x.max:])[::-1]}); im.logout()
    elif c == "mail-draft":
        im, u = imap(x.cuenta, folder=None)
        msg = EmailMessage(); msg["From"], msg["To"], msg["Subject"] = u, x.to, x.subject
        if x.cc:
            msg["Cc"] = x.cc
        msg["Date"] = formatdate(localtime=True); msg["Message-ID"] = make_msgid()
        if x.reply_uid:
            im.select("INBOX", readonly=True); st, dd = im.uid("fetch", x.reply_uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            mid = email.message_from_bytes(dd[0][1])["Message-ID"] if dd and isinstance(dd[0], tuple) else None
            if mid:
                msg["In-Reply-To"] = mid; msg["References"] = mid
        msg.set_content(open(x.body_file, encoding="utf-8").read())
        st, l = im.list(); folder = "[Gmail]/Drafts"
        for z in l or []:
            s_ = z.decode("utf-8", "ignore")
            if "\\Drafts" in s_ and re.search(r'"([^"]+)"\s*$', s_):
                folder = re.search(r'"([^"]+)"\s*$', s_).group(1)
        st, r = im.append(f'"{folder}"', "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes()); im.logout()
        out({"ok": st == "OK", "cuenta": u, "carpeta": folder, "para": x.to, "asunto": x.subject})


if __name__ == "__main__":
    main()
