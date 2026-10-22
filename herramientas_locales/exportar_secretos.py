# -*- coding: utf-8 -*-
"""Corre SOLO en tu PC. Lee tus archivos locales de credenciales y escribe un archivo de texto con lineas NOMBRE=valor
para pegarlas en 'Variables de entorno' del entorno de la nube en claude.ai. No envia nada a ningun lado.
BORRA el archivo de salida cuando termines de pegar."""
import json, os, importlib.util

P = r"C:\Users\juanc\OneDrive\Documentos\Claude\Projects"
out = os.path.join(os.path.expanduser("~"), "Desktop", "SECRETOS_NUBE_BORRAR_DESPUES.txt")
o = json.load(open(r"C:\Users\juanc\.claude\secrets\odoo_credentials.json", encoding="utf-8"))
lines = [f"ODOO_URL={o['url']}", f"ODOO_DB={o['db']}", f"ODOO_USER={o['username']}", f"ODOO_API_KEY={o['api_key']}"]


def mod(folder, name):
    s = importlib.util.spec_from_file_location(name, os.path.join(P, folder, name + ".py"))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


for emp, folder in (("OMICRON", "Omicron 3X"), ("KLAR", "Klar 3X"), ("LAVACLINICAS", "Lavanderías 3X"), ("TECNOLAVEX", "Lavanderías 3X")):
    m = mod(folder, f"siigo_credenciales_{emp.lower()}")
    lines += [f"SIIGO_{emp}_USER={m.USERNAME}", f"SIIGO_{emp}_KEY={m.ACCESS_KEY}"]
lines.append("SIIGO_PARTNER_ID=grupoEgAutomatizacion")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("Listo:", out, "| variables:", len(lines), "| (no se muestran valores)")
