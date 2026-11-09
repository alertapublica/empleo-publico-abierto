"""El catálogo de fuentes: cada organismo en un grupo y con su ámbito."""
import unittest

from empleo.model import GROUPS, STATE_SCOPE
from empleo.regions import NATIONAL, REGIONS, SEVERAL, UNKNOWN
from empleo.sources import ACTIVE, CATALOG

COMMUNITIES = [r for r in REGIONS if r not in (NATIONAL, SEVERAL, UNKNOWN)]


class Catalogo(unittest.TestCase):
    def test_los_grupos_son_los_del_modelo_y_en_su_orden(self):
        self.assertEqual(list(CATALOG), list(GROUPS))

    def test_cada_fuente_tiene_su_grupo(self):
        for group, sources in CATALOG.items():
            for source in sources:
                self.assertEqual(source.group, group, source.id)

    def test_identificadores_unicos(self):
        ids = [source.id for source in ACTIVE]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ambito_coherente_con_el_grupo(self):
        for source in ACTIVE:
            if source.group in ("sepi", "estatal"):
                self.assertEqual(source.scope, STATE_SCOPE, source.id)
            elif source.group == "autonomica":
                self.assertIn(source.scope, COMMUNITIES, source.id)
            else:
                self.assertIn(source.scope, [STATE_SCOPE, *COMMUNITIES], source.id)
