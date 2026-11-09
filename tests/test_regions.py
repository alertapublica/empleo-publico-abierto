import unittest

from empleo.regions import (NATIONAL, SEVERAL, UNKNOWN, codes_of, location_from_title, municipality_of,
                            region_of)


class Regions(unittest.TestCase):
    def test_valores_reales(self):
        cases = {
            "Comunidad de Madrid": "Comunidad de Madrid",
            "Sede Madrid Tragsatec": "Comunidad de Madrid",
            "València/Valencia": "Comunitat Valenciana",
            "Comunidad de Galicia": "Galicia",
            "Santiago de Compostela": "Galicia",
            "A Coruña": "Galicia",
            "Las Palmas": "Canarias",
            "La Palma": "Canarias",
            "Palma Mallorca": "Illes Balears",
            "Sta. Cruz de Tenerife": "Canarias",
            "Araba": "País Vasco",
            "Ciudad Real": "Castilla-La Mancha",
            "Ávila": "Castilla y León",
            "Melilla": "Melilla",
            "Castilla - La Mancha": "Castilla-La Mancha",
            "Juzbado (Salamanca)": "Castilla y León",
            "El Cabril": "Andalucía",           # centro de Enresa en Hornachuelos (Córdoba)
            "Santa María de Garoña": "Castilla y León",
            "Vandellós I": "Cataluña",
            "Rubí": "Cataluña",                 # municipio de la relación del INE
            "Ribes de Freser": "Cataluña",
        }
        for text, expected in cases.items():
            self.assertEqual(region_of(text), expected, text)

    def test_casos_especiales(self):
        self.assertEqual(region_of("Nacional"), NATIONAL)
        self.assertEqual(region_of("Varias Provincias"), SEVERAL)
        self.assertEqual(region_of("Madrid y Sevilla"), SEVERAL)
        self.assertEqual(region_of("Atlántico"), UNKNOWN)
        self.assertEqual(region_of(None, ""), UNKNOWN)

    def test_usa_la_siguiente_pista(self):
        self.assertEqual(region_of(None, "Toledo"), "Castilla-La Mancha")

    def test_ubicacion_del_titulo(self):
        self.assertEqual(location_from_title("Oficial - Apoyo (Valencia)"), "Valencia")
        self.assertIsNone(location_from_title("Observadores en el Mediterráneo"))


class Places(unittest.TestCase):
    def test_localidad_del_titulo_o_de_la_direccion(self):
        from empleo.regions import place_of
        sec = lambda addr: [{"title": "Lugar de Trabajo", "html": f"<p>Comunidad de Galicia</p><p>Dirección: {addr}</p>"}]
        self.assertEqual(place_of("Técnico (Madrid)", []), "Madrid")
        self.assertEqual(place_of("Técnico (Provincia de Valencia)", []), "Valencia")
        self.assertEqual(place_of("Técnico (Galicia)", sec("Santiago de Compostela")), "Santiago de Compostela")

    def test_no_confunde_comunidades_ni_textos_largos_con_localidades(self):
        from empleo.regions import place_of
        self.assertIsNone(place_of("Técnico (Asturias)", []))
        self.assertIsNone(place_of("Técnico (Varias Provincias)", []))
        self.assertIsNone(place_of("Técnico (Buque Oceanográfico)", []))
        self.assertIsNone(place_of("Técnico", [{"title": "Lugar de Trabajo", "html": "<p>Dirección: Oficinas grupo</p>"}]))


class CodigosINE(unittest.TestCase):
    def test_municipio_solo_sin_ambiguedad(self):
        self.assertEqual(municipality_of("Rubí"), ("08184", "09"))
        self.assertEqual(municipality_of("Langreo (Asturias)"), ("33031", "03"))
        self.assertEqual(municipality_of("Moncada, Valencia"), ("46171", "10"))
        self.assertEqual(municipality_of("L'Hospitalet de Llobregat"), ("08101", "09"))
        self.assertEqual(municipality_of("Hospitalet de Llobregat"), ("08101", "09"))
        self.assertEqual(municipality_of("Donostia"), ("20069", "16"))
        self.assertIsNone(municipality_of("Sevilla"))      # provincia o capital: no se elige
        self.assertIsNone(municipality_of("Cantabria"))
        self.assertIsNone(municipality_of("Rioja"))        # hay un Rioja en Almería
        self.assertIsNone(municipality_of("Villanueva"))   # no existe tal cual
        self.assertIsNone(municipality_of(None))

    def test_provincia_y_comunidad(self):
        self.assertEqual(codes_of("Andalucía", "Sevilla"),
                         {"ccaa": "01", "provincia": "41", "municipio": None})
        self.assertEqual(codes_of("Comunidad de Madrid", "Sede Madrid Tragsatec"),
                         {"ccaa": "13", "provincia": "28", "municipio": None})
        self.assertEqual(codes_of("Canarias", "Sta. Cruz de Tenerife", "Tenerife")["provincia"], "38")
        self.assertEqual(codes_of("Canarias", "Fuerteventura")["provincia"], "35")
        self.assertEqual(codes_of("Illes Balears", "Ibiza - Baleares")["provincia"], "07")
        self.assertEqual(codes_of("Castilla y León", "Castilla y León")["provincia"], None)  # no es León
        self.assertEqual(codes_of("Cataluña", "Cataluña")["provincia"], None)
        self.assertEqual(codes_of("Cantabria", "Comunidad de Cantabria")["provincia"], "39")  # uniprovincial

    def test_el_municipio_afina_la_ubicacion_de_la_fuente(self):
        self.assertEqual(codes_of("Galicia", "Comunidad de Galicia", "Santiago de Compostela"),
                         {"ccaa": "12", "provincia": "15", "municipio": "15078"})
        self.assertEqual(codes_of("Comunitat Valenciana", "València/Valencia", "Moncada, Valencia")["municipio"],
                         "46171")
        self.assertEqual(codes_of("Comunidad de Madrid", "Comunidad de Madrid", None,
                                  "San Fernando de Henares")["municipio"], "28130")

    def test_sin_comunidad_no_hay_codigos(self):
        for region in (NATIONAL, SEVERAL, UNKNOWN, None):
            self.assertEqual(codes_of(region, "Madrid"), {"ccaa": None, "provincia": None, "municipio": None})

    def test_no_contradice_la_comunidad(self):
        self.assertEqual(codes_of("Galicia", "Rubí"), {"ccaa": "12", "provincia": None, "municipio": None})
