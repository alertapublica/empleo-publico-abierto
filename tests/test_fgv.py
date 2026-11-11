import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import fgv

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Listado real; toda subpágina de plazo devuelve la de ingenieros (fin: 30/10/2026 11:59)."""

    def __init__(self):
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        if url == fgv.PAGE:
            return fixture("fgv-en-proceso.html")
        if "ingenieros" in url and "apertura-plazo" in url:
            return fixture("fgv-apertura-ingenieros.html")
        if "apertura-plazo" in url:  # conducción: mismo formato, plazo de 2025
            return fixture("fgv-apertura-ingenieros.html").replace("2026", "2025")
        raise AssertionError(f"petición no esperada: {url}")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


def read(now):
    http = Http()
    source = fgv.FgvSource(now=now)
    offers = source.list_offers(http)
    notices = source.list_announcements(http)
    details = [source.fetch_detail(http, offer) for offer in offers]
    return offers, notices, details, http


class Page(unittest.TestCase):
    def setUp(self):
        self.items = fgv.parse_page(fixture("fgv-en-proceso.html"))

    def test_convocatorias_en_proceso_y_no_las_cerradas(self):
        self.assertEqual(len(self.items), 8)
        self.assertFalse(any("CERRADAS" in i["title"] for i in self.items))
        self.assertEqual([i["cancelled"] for i in self.items], [False] * 7 + [True])

    def test_comunicados_del_mas_reciente_al_mas_antiguo(self):
        conduccion = self.items[2]
        self.assertEqual([n["title"] for n in conduccion["notices"]], [
            "Resolución del 4 de febrero, aclaración temario",
            "Apertura plazo y formulario de inscripción OEP Conducción y Circulación 2023 y 2024",
            "Preguntas frecuentes OEP Conducción y Circulación 2023 y 2024",
        ])
        self.assertEqual(len(self.items[3]["notices"]), 25)

    def test_solo_sin_fases_posteriores_se_mira_el_plazo(self):
        self.assertEqual([fgv._is_candidate(i) for i in self.items],
                         [False, True, True, False, False, False, False, False])

    def test_puesto_del_titulo(self):
        self.assertEqual(fgv._job(self.items[1]["title"]), "Puestos técnicos de ingenieros e ingenieras")
        self.assertEqual(fgv._job(self.items[2]["title"]), "Conducción y circulación")

    def test_sin_arbol_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            fgv.parse_page("<p>Convocatorias</p>")


class DeadlinePage(unittest.TestCase):
    def test_inicio_y_fin_con_hora(self):
        page = fgv.deadline_page(fixture("fgv-apertura-ingenieros.html"))
        self.assertEqual([(d.isoformat(), h) for d, h in page["end"]], [("2026-10-30", "11:59")])
        self.assertEqual([(d.isoformat(), h) for d, h in page["start"]], [("2026-10-21", "12:00")])
        self.assertEqual(page["lines"], ["Inicio: miércoles 21 de octubre de 2026 a las 12:00 horas",
                                         "Fin: viernes 30 de octubre de 2026 a las 11:59 horas"])


class Source(unittest.TestCase):
    def test_en_plazo_es_oferta(self):
        offers, notices, details, _ = read(at(10, 25))
        (offer,) = offers
        self.assertEqual((offer.title, offer.deadline, offer.deadline_time, offer.opens_on),
                         ("Puestos técnicos de ingenieros e ingenieras", "2026-10-30", "11:59", "2026-10-21"))
        self.assertIn("apertura-plazo", offer.apply_url)
        self.assertNotIn(offer.ref, {n.process for n in notices})
        sections = {s["title"]: s["html"] for s in details[0].sections}
        self.assertIn("Fin: viernes 30 de octubre de 2026 a las 11:59 horas", sections["Plazo de presentación de solicitudes"])

    def test_hoy_solo_procesos_sin_fecha(self):
        offers, notices, _, http = read(at(11, 11))
        self.assertEqual(offers, [])
        self.assertEqual(len(http.asked), 3)  # el listado y las dos subpáginas de plazo
        self.assertEqual({n.date for n in notices}, {""})
        self.assertEqual(len({n.process for n in notices}), 8)
        ingenieros = [n for n in notices if "INGENIEROS" in n.process]
        self.assertEqual([n.title for n in ingenieros][-1], ingenieros[0].process)  # la convocatoria, al final
        self.assertEqual((ingenieros[0].via, ingenieros[0].system, ingenieros[0].state),
                         ("oep", "concurso-oposicion", "curso"))
        anulada = {n.state for n in notices if n.process.startswith("ANULADA")}
        self.assertEqual(anulada, {"finalizado"})

    def test_pasada_la_hora_del_ultimo_dia_ya_no_es_oferta(self):
        offers, _, _, _ = read(at(10, 30, 11))  # 12:00 en Madrid
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()
