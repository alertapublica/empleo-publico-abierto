# Certificados intermedios

Algunos servidores oficiales envían un certificado intermedio equivocado y la verificación TLS falla. En lugar de desactivarla, el cliente añade estos intermedios al almacén del sistema: la cadena se sigue comprobando hasta una raíz del sistema.

| Archivo | Lo necesita | Comprobado |
|---|---|---|
| `digicert-global-g2-tls-rsa-sha256-2020-ca1.pem` | `www.senasa.es` (envía «RapidSSL TLS RSA CA G1») | 2026-11-08: emitido por DigiCert Global Root G2, `CA:TRUE`, caduca el 29-03-2031. SHA-256 `C8:02:5F:9F:…:D0:B6:25:A9` |
| `sectigo-public-server-authentication-ca-dv-r36.pem` | `www.gpex.es`, `candidato.gpex.es` (envían «Thawte RSA CA 2018») | 2026-11-08: emitido por Sectigo Public Server Authentication Root R46, `CA:TRUE`, caduca el 21-03-2036. SHA-256 `8C:54:C3:34:…:A5:A4:EF:22:E0` |

Se descargan desde la dirección «CA Issuers» del certificado del propio servidor y se comprueban con `openssl verify -CApath /etc/ssl/certs`. Solo se añaden intermedios, nunca raíces: `tests/test_http.py` lo comprueba.
