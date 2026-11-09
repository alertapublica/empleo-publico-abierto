"""Cliente HTTP: los intermedios añadidos y la pausa de cada fuente."""
import ssl
import unittest
from unittest import mock

from empleo import http, ingest


def decoded(pem):
    return ssl._ssl._test_decode_cert(str(pem))


def name(fields):
    return dict(pair for rdn in fields for pair in rdn).get("commonName")


class Certificados(unittest.TestCase):
    def test_solo_intermedios_nunca_raices(self):
        pems = sorted(http.CERTS.glob("*.pem"))
        self.assertTrue(pems)
        for pem in pems:
            cert = decoded(pem)
            self.assertNotEqual(name(cert["subject"]), name(cert["issuer"]), pem.name)

    def test_el_cliente_los_carga_ademas_del_sistema(self):
        loaded = {name(c["subject"]) for c in http.tls_context().get_ca_certs()}
        self.assertIn("DigiCert Global G2 TLS RSA SHA256 2020 CA1", loaded)
        self.assertIn("Sectigo Public Server Authentication CA DV R36", loaded)
        self.assertEqual(http.tls_context().verify_mode, ssl.CERT_REQUIRED)


class Pausa(unittest.TestCase):
    def test_cada_fuente_lee_con_su_pausa(self):
        slow = type("S", (), {"id": "lenta", "delay": 10.0})()
        normal = type("S", (), {"id": "normal", "delay": http.DEFAULT_DELAY})()
        seen = []
        with mock.patch.object(ingest, "ACTIVE", [slow, normal]), \
                mock.patch.object(ingest, "run_source", lambda s, client, *_: seen.append((s.id, client.delay))):
            ingest.main()
        self.assertEqual(seen, [("lenta", 10.0), ("normal", http.DEFAULT_DELAY)])
