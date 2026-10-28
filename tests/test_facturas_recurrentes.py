"""Pruebas con facturas SINTETICAS (nada de SIIGO real). Ejecutar: python -m unittest discover -s tests"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import facturas_recurrentes as fr  # noqa: E402


def fac(cli, ym, total, dia=15, num=None):
    return {"cliente": cli, "fecha": f"{ym}-{dia:02d}", "total": total, "numero": num or f"FV-{cli}-{ym}"}


def serie(cli, meses, total, dia=15):
    return [fac(cli, m, total, dia) for m in meses]


HOY = date(2026, 10, 25)
MESES6 = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


class TestCalendario(unittest.TestCase):
    def test_festivos_2026(self):
        esperados = {date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2), date(2026, 4, 3), date(2026, 5, 1), date(2026, 5, 18), date(2026, 6, 8),
                     date(2026, 6, 15), date(2026, 6, 29), date(2026, 7, 20), date(2026, 8, 7), date(2026, 8, 17), date(2026, 10, 12), date(2026, 11, 2), date(2026, 11, 16),
                     date(2026, 12, 8), date(2026, 12, 25)}
        self.assertEqual(fr.festivos_colombia(2026), esperados)

    def test_pascua(self):
        self.assertEqual(fr.pascua(2026), date(2026, 4, 5))
        self.assertEqual(fr.pascua(2027), date(2027, 3, 28))

    def test_ultimo_habil(self):
        self.assertEqual(fr.ultimo_habil(2026, 10), date(2026, 10, 30))   # 31 es sabado
        self.assertEqual(fr.ultimo_habil(2026, 11), date(2026, 11, 30))   # lunes
        self.assertEqual(fr.ultimo_habil(2026, 12), date(2026, 12, 31))
        self.assertEqual(fr.ultimo_habil(2026, 5), date(2026, 5, 29))     # 30-31 fin de semana
        self.assertEqual(fr.ultimo_habil(2027, 4), date(2027, 4, 30))

    def test_modos(self):
        self.assertTrue(fr.debe_correr("dia25", date(2026, 11, 25))[0])
        self.assertFalse(fr.debe_correr("dia25", date(2026, 11, 24))[0])
        self.assertTrue(fr.debe_correr("ultimo-habil", date(2026, 10, 30))[0])
        self.assertFalse(fr.debe_correr("ultimo-habil", date(2026, 10, 29))[0])
        self.assertFalse(fr.debe_correr("ultimo-habil", date(2026, 10, 31))[0])    # sabado: no es habil
        self.assertTrue(fr.debe_correr("ahora", date(2026, 10, 31))[0])

    def test_fechas_de_control(self):
        f = fr.fechas_de_control(date(2026, 10, 26), 3)
        self.assertEqual(f[:4], [(date(2026, 10, 30), "ultimo-habil"), (date(2026, 11, 25), "dia25"), (date(2026, 11, 30), "ultimo-habil"), (date(2026, 12, 25), "dia25")])
        self.assertEqual(len(fr.fechas_de_control(date(2026, 10, 26), 13)), 26 - 1)    # 13 meses x 2, menos el dia 25 de octubre ya pasado


class TestAnalisis(unittest.TestCase):
    def test_caso_tecnolavex_cliente_fijo_sin_factura_en_septiembre(self):
        meses = [m for m in MESES6 if m != "2026-09"] + ["2026-03", "2026-02"]
        f = serie("890801201", meses, 22_860_000) + [fac("890801201", "2026-10", 68_580_000, 20)]       # octubre: 3 meses juntos
        h = fr.analizar(f, HOY)
        self.assertEqual(len(h), 1)
        self.assertIn("MES_SALTADO", h[0]["estado"])
        self.assertEqual(h[0]["meses_saltados"], ["2026-09"])
        self.assertTrue(h[0]["mes_pasado_saltado"])
        self.assertEqual(h[0]["urgencia"], "ALTA")          # el caso Tecnolavex: mes pasado sin factura => urgente aunque octubre traiga un valor acumulado
        self.assertIn("VALOR_DISTINTO", h[0]["estado"])
        self.assertTrue(h[0]["valor_fijo"])
        self.assertEqual(h[0]["valor_habitual"], 22_860_000)

    def test_cliente_fijo_sin_factura_este_mes_es_urgencia_alta(self):
        h = fr.analizar(serie("111", MESES6, 6_540_874, 10), HOY)
        self.assertEqual((h[0]["estado"], h[0]["urgencia"], h[0]["ya_deberia_estar"]), (["FALTA"], "ALTA", True))

    def test_cliente_al_dia_no_genera_alerta(self):
        f = serie("222", MESES6 + ["2026-10"], 5_000_000)
        self.assertEqual(fr.analizar(f, HOY), [])

    def test_no_recurrente_se_ignora(self):
        f = [fac("333", "2026-08", 1_000_000), fac("333", "2026-04", 900_000)]
        self.assertEqual(fr.analizar(f, HOY), [])

    def test_variable_recurrente_sin_factura_se_marca(self):
        vals = [3_000_000, 5_000_000, 4_000_000, 6_000_000, 3_500_000, 5_500_000]
        f = [fac("444", m, v, 12) for m, v in zip(MESES6, vals)]
        h = fr.analizar(f, HOY)
        self.assertFalse(h[0]["valor_fijo"])
        self.assertEqual(h[0]["estado"], ["FALTA"])

    def test_dia_habitual_posterior_no_es_urgencia_alta_si_es_variable(self):
        vals = [3_000_000, 5_000_000, 4_000_000, 6_000_000, 3_500_000, 5_500_000]
        f = [fac("555", m, v, 28) for m, v in zip(MESES6, vals)]
        h = fr.analizar(f, HOY)
        self.assertEqual((h[0]["urgencia"], h[0]["ya_deberia_estar"]), ("MEDIA", False))

    def test_posible_baja(self):
        f = serie("666", ["2026-04", "2026-05", "2026-06", "2026-07"], 2_000_000)
        h = fr.analizar(f, HOY)
        self.assertIn("POSIBLE_BAJA", h[0]["estado"])
        self.assertNotEqual(h[0]["urgencia"], "ALTA")

    def test_ordenado_por_urgencia_y_valor(self):
        f = serie("A", MESES6, 1_000_000) + serie("B", MESES6, 9_000_000)
        h = fr.analizar(f, HOY)
        self.assertEqual([x["cliente"] for x in h], ["B", "A"])

    def test_cambio_de_ano(self):
        hoy = date(2027, 1, 25)
        f = serie("777", ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"], 3_000_000)
        self.assertEqual(fr.analizar(f, hoy)[0]["estado"], ["FALTA"])


class TestAvisos(unittest.TestCase):
    def res(self, faltas):
        h = fr.analizar(serie("890801201", MESES6, 22_860_000, 15), HOY) if faltas else []
        for x in h:
            x["nombre"] = "Cliente de prueba"
        return {"tecnolavex": {"hallazgos": h, "error": None}, "klar": {"hallazgos": [], "error": None}}

    def test_aviso_urgente(self):
        t = fr.texto_aviso(self.res(True), HOY, "dia25")
        self.assertTrue(t.startswith("URGENTE"))
        self.assertIn("Tecnolavex", t)
        self.assertLessEqual(len(t), 190)

    def test_aviso_ok_se_envia_tambien(self):
        self.assertIn("todas al dia", fr.texto_aviso(self.res(False), HOY, "ultimo-habil"))

    def test_error_de_siigo_es_urgente(self):
        r = {"tecnolavex": {"hallazgos": [], "error": "RuntimeError: x"}}
        self.assertIn("no pude revisar SIIGO de Tecnolavex", fr.texto_aviso(r, HOY, "dia25"))

    def test_aviso_cuenta_el_mes_pasado_saltado(self):
        meses = [m for m in MESES6 if m != "2026-09"] + ["2026-03"]
        h = fr.analizar(serie("890801201", meses, 22_860_000) + [fac("890801201", "2026-10", 68_580_000, 20)], HOY)
        h[0]["nombre"] = "CRUZ ROJA"
        t = fr.texto_aviso({"tecnolavex": {"hallazgos": h, "error": None}}, HOY, "dia25")
        self.assertIn("1 con el mes pasado sin facturar", t)
        self.assertIn("CRUZ ROJA", fr.texto_correo_contabilidad({"tecnolavex": {"hallazgos": h, "error": None}}, HOY))

    def test_correo_a_contabilidad_es_borrador_con_datos(self):
        c = fr.texto_correo_contabilidad(self.res(True), HOY)
        self.assertIn("URGENTE", c)
        self.assertIn("890801201", c)
        self.assertIn("$22.860.000", c)


class TestSinSecretos(unittest.TestCase):
    def test_credenciales_solo_por_entorno(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(fr.__file__)), "facturas_recurrentes.py"), encoding="utf-8").read()
        self.assertNotIn("ACCESS_KEY =", src)
        with self.assertRaises(RuntimeError):
            os.environ.pop("SIIGO_TECNOLAVEX_USER", None)
            fr.siigo_headers("tecnolavex")


if __name__ == "__main__":
    unittest.main()
