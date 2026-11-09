# Relay con IP española (SEPI y otras fuentes que no responden desde Actions)

`www.sepi.es` no responde a las IP de GitHub (Azure) y sí desde una IP española. Usamos el
relay PHP de `thendabs1/boletines-es`, que ya sirve al BOPA. No hay que montar nada nuevo:
solo firmar las peticiones desde aquí.

## Qué hay montado (08/11/2026)

- `http://casccadacaldas.es/relay.php`, en el hosting de Piensa Solutions (IP 217.76.150.74). Va por HTTP
  porque Piensa cobra el certificado; por eso la clave no viaja, solo una firma que caduca.
- Código: `relay/relay.php` en boletines-es (PR #27 la firma y PR #29 los hosts de SEPI). Probado en vivo:
  `https://www.sepi.es/es/empleo-publico` → 200, «Empleo público | SEPI», ~200 ms.
- Hosts admitidos para este portal: `sepi.es` y `www.sepi.es`. El resto de la lista es de los boletines.

## Cómo se pide

```
GET http://casccadacaldas.es/relay.php/?url=<URL de destino codificada>
x-ts:    segundos unix (str(int(time.time())))
x-firma: hex(HMAC-SHA256(RELAY_CLAVE, x-ts + "\n" + URL de destino))
```

- La URL firmada es la de destino exactamente como va en `url` (antes de codificar).
- Validez ±120 s: firma nueva en cada intento, no reutilizar la de un reintento anterior.
- Respuestas: el estado y el `Content-Type` del destino, con `x-relay-ms`. Sin `x-relay-ms`, la respuesta es del
  propio relay: 403 `no` (firma mala, caducada o reloj desfasado), 400 (host fuera de la lista), 405 (no es GET),
  502 con `x-relay-error: red` (el destino no respondió; conviene reintentarlo como un fallo de red).

Ejemplo en Python (el mismo que `boletines/red.py:firmar_relay`):

```python
import hashlib, hmac, time
from urllib.parse import urlencode

def por_relay(url, clave, base="http://casccadacaldas.es/relay.php"):
    ts = str(int(time.time()))
    firma = hmac.new(clave.encode(), f"{ts}\n{url}".encode(), hashlib.sha256).hexdigest()
    return base.rstrip("/") + "/?" + urlencode({"url": url}), {"x-ts": ts, "x-firma": firma}
```

## Cómo se usa en este repo

- Secretos `RELAY_CLAVE` (el mismo valor que en boletines-es, en `~/boletines-es/.env`) y `RELAY_URL` en
  `alertapublica/empleo-publico-abierto`. `actualizar.yml` (paso «Leer las webs oficiales») y `sondeo.yml` los pasan en `env`.
- `empleo/http.py`: los hosts de `VIA_RELAY` (hoy `sepi.es` y `www.sepi.es`) van por el relay en los GET de `Client`
  y en el sondeo. La firma se calcula en cada intento. Sin `RELAY_CLAVE` (en local) se leen directos: desde casa
  la SEPI sí responde. Los POST nunca van por el relay.
- Errores: el 403 de firma mala o caducada no se reintenta; el 502 del relay (`x-relay-error: red`) sí.
- Pruebas: `tests/test_relay.py`, con un servidor local que comprueba la firma como `relay.php`.
- Lector: `empleo/sources/sepi.py`. Al añadir otro host a `VIA_RELAY`, añadirlo antes al relay (ver abajo).

## Límites del relay

- Solo GET. No reenvía cabeceras, cookies ni el `User-Agent` del portal: sale con el de boletines-es.
- Sigue él las redirecciones (máx. 5, todas dentro de la lista) y devuelve la final; no se ve la URL final.
- Descomprime gzip y devuelve el cuerpo sin `Content-Encoding`.
- Tiempo máximo 25 s por petición. Comparte hosting con el BOPA: ritmo tranquilo, una petición cada pocos segundos.
- TLS con los certificados del hosting: los intermedios de `empleo/certs/` no se aplican allí.

## Añadir otra fuente

1. En boletines-es, añadir el host a `HOSTS_PERMITIDOS` de `relay/relay.php` (bloque final, «empleo-sepi-abierto»)
   con un PR.
2. Subir el fichero a Piensa por SFTP: credenciales `RELAY_SFTP_*` en `~/boletines-es/.env`, destino
   `$RELAY_SFTP_HTML/relay.php`. Guardar antes una copia del remoto y comparar después con `main`.
3. Comprobar: `RELAY_URL=http://casccadacaldas.es/relay.php python herramientas/verificar_relay.py` (8 casos) y una
   petición firmada a la nueva fuente. Para verlo en el navegador: `verificar_relay.py --enlace-prueba` (vale 2 min).
