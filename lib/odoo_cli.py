#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Odoo por XML-RPC para los agentes en la nube. Credenciales SOLO por variables de entorno:
ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY. Nunca imprime credenciales.
  python lib/odoo_cli.py sr <modelo> --domain "[...]" --fields a,b [--limit N] [--order "x desc"] [--inactivos]
  python lib/odoo_cli.py note <modelo> <id> --body "texto"
  python lib/odoo_cli.py call <modelo> <metodo> --args "[...]" [--kw "{...}"]
"""
import os, sys, json, time, argparse, socket, xmlrpc.client

sys.stdout.reconfigure(encoding="utf-8")
ALL = [1, 2, 3, 4, 5, 6, 7, 8, 9]
_c = {}


def _retry(fn, tries=4, wait=3):
    for i in range(tries):
        try:
            return fn()
        except (socket.gaierror, ConnectionError, TimeoutError, OSError):
            if i == tries - 1:
                raise
            time.sleep(wait * (i + 1))


def conn():
    if not _c:
        try:
            u, d, usr, key = (os.environ[k] for k in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_API_KEY"))
        except KeyError as e:
            sys.exit(f"Falta la variable de entorno {e}. Configurala en el entorno de la rutina (claude.ai).")
        uid = _retry(lambda: xmlrpc.client.ServerProxy(f"{u}/xmlrpc/2/common").authenticate(d, usr, key, {}))
        if not uid:
            sys.exit("Autenticacion Odoo fallida")
        _c.update(u=u, d=d, k=key, uid=uid, m=xmlrpc.client.ServerProxy(f"{u}/xmlrpc/2/object"))
    return _c


def call(model, method, args, **kw):
    c = conn()
    kw.setdefault("context", {"allowed_company_ids": ALL})
    try:
        return _retry(lambda: c["m"].execute_kw(c["d"], c["uid"], c["k"], model, method, args, kw))
    except xmlrpc.client.Fault as e:
        last = [l for l in str(e.faultString).strip().splitlines() if l.strip()][-1]
        sys.exit(f"ERROR Odoo en {model}.{method}: {last[:300]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("sr")
    a.add_argument("modelo"); a.add_argument("--domain", default="[]"); a.add_argument("--fields", default="name")
    a.add_argument("--limit", type=int, default=50); a.add_argument("--order", default=""); a.add_argument("--inactivos", action="store_true")
    n = sp.add_parser("note")
    n.add_argument("modelo"); n.add_argument("id"); n.add_argument("--body", required=True)
    k = sp.add_parser("call")
    k.add_argument("modelo"); k.add_argument("metodo"); k.add_argument("--args", default="[]"); k.add_argument("--kw", default="{}")
    x = ap.parse_args()
    if x.cmd == "sr":
        kw = {"fields": x.fields.split(","), "limit": x.limit}
        if x.order:
            kw["order"] = x.order
        if x.inactivos:
            kw["context"] = {"allowed_company_ids": ALL, "active_test": False}
        print(json.dumps(call(x.modelo, "search_read", [json.loads(x.domain)], **kw), ensure_ascii=False, indent=1))
    elif x.cmd == "note":
        print(json.dumps(call(x.modelo, "message_post", [[int(x.id)]], body=x.body), ensure_ascii=False))
    else:
        print(json.dumps(call(x.modelo, x.metodo, json.loads(x.args), **json.loads(x.kw)), ensure_ascii=False, indent=1))
