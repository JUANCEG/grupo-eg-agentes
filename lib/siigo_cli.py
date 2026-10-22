#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIIGO para los agentes en la nube. Variables de entorno por empresa (OMICRON, KLAR, LAVACLINICAS, TECNOLAVEX):
SIIGO_<EMPRESA>_USER, SIIGO_<EMPRESA>_KEY y SIIGO_PARTNER_ID. Nunca imprime credenciales ni NIT.
  python lib/siigo_cli.py cartera <empresa>             facturas con saldo agrupadas por NOMBRE de cliente (dias de mora)
  python lib/siigo_cli.py ingresos <empresa> <AAAA-MM>  total facturado del mes
  python lib/siigo_cli.py clientes <empresa>            nombres de clientes facturados en los ultimos 18 meses
"""
import os, sys, json, time, urllib.request, argparse
from datetime import date, datetime, timedelta
from calendar import monthrange

sys.stdout.reconfigure(encoding="utf-8")
EMP = ("omicron", "klar", "lavaclinicas", "tecnolavex")


def _hdr(emp):
    try:
        u, k = os.environ[f"SIIGO_{emp.upper()}_USER"], os.environ[f"SIIGO_{emp.upper()}_KEY"]
    except KeyError as e:
        sys.exit(f"Falta la variable de entorno {e}")
    pid = os.environ.get("SIIGO_PARTNER_ID", "grupoEgAutomatizacion")
    req = urllib.request.Request("https://api.siigo.com/auth", data=json.dumps({"username": u, "access_key": k}).encode(),
                                 method="POST", headers={"Content-Type": "application/json", "Partner-Id": pid})
    tok = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())["access_token"]
    return {"Authorization": f"Bearer {tok}", "Partner-Id": pid}


def _get(url, h):
    for i in range(3):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25).read().decode())
        except Exception:
            time.sleep(2 * (i + 1))
    return {}


_names = {}


def nombre(ident, h):
    if ident not in _names:
        c = (_get("https://api.siigo.com/v1/customers?identification=" + str(ident), h).get("results") or [{}])[0]
        _names[ident] = c.get("commercial_name") or " ".join(c.get("name") or []).strip() or "Cliente sin nombre"
    return _names[ident]


def facturas(h, desde=None, hasta=None, maxp=25):
    p = 1
    while p <= maxp:
        q = f"https://api.siigo.com/v1/invoices?page={p}&page_size=100" + (f"&created_start={desde}" if desde else "") + (f"&created_end={hasta}" if hasta else "")
        res = _get(q, h).get("results") or []
        if not res:
            return
        yield from res
        p += 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cartera", "ingresos", "clientes"])
    ap.add_argument("empresa", choices=EMP)
    ap.add_argument("mes", nargs="?")
    a = ap.parse_args()
    h = _hdr(a.empresa)
    if a.cmd == "cartera":
        por = {}
        for f in facturas(h, maxp=3):
            bal = f.get("balance") or 0
            if bal > 0:
                dues = [p.get("due_date") for p in f.get("payments", []) if p.get("due_date")]
                dias = (date.today() - datetime.strptime(min(dues), "%Y-%m-%d").date()).days if dues else None
                n = nombre((f.get("customer") or {}).get("identification"), h)
                d = por.setdefault(n, {"saldo": 0, "max_dias": None, "facturas": 0})
                d["saldo"] += bal
                d["facturas"] += 1
                if dias is not None:
                    d["max_dias"] = max(dias, d["max_dias"] or dias)
        print(json.dumps(sorted(({"cliente": k, **v} for k, v in por.items()), key=lambda x: -(x["max_dias"] or 0)), ensure_ascii=False, indent=1))
    elif a.cmd == "ingresos":
        y, m = map(int, a.mes.split("-"))
        ult = monthrange(y, m)[1]
        tot = sum((f.get("total") or 0) for f in facturas(h, f"{y}-{m:02d}-01", f"{y}-{m:02d}-{ult:02d}", 15))
        print(json.dumps({"empresa": a.empresa, "mes": a.mes, "total": tot}))
    else:
        desde = (date.today() - timedelta(days=548)).isoformat()
        ids = {}
        for f in facturas(h, desde):
            i = (f.get("customer") or {}).get("identification")
            if i:
                ids[i] = 1
        print(json.dumps(sorted({nombre(i, h) for i in list(ids)[:600]}), ensure_ascii=False, indent=1))
