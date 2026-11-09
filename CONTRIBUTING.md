# Contribuir

Gracias por querer ayudar. Este proyecto es pequeño y los cambios pequeños se revisan antes.

## Qué se agradece

- **Fallos en los datos:** una oferta mal leída, un plazo que no cuadra con el portal oficial, una fuente que ha dejado de funcionar. Abre una *issue* con el enlace oficial y lo que ves.
- **Fuentes nuevas:** empresas públicas, fundaciones o centros de investigación que publiquen ofertas. Antes de programar nada, abre una *issue* con la dirección de su portal; mira [`docs/anadir-fuente.md`](docs/anadir-fuente.md) y [`hallazgos/`](hallazgos/).
- **Accesibilidad y textos de la web**, y correcciones de la documentación.

## Cómo preparar un cambio

1. Crea una rama desde `main`.
2. Prepara el entorno y pasa los tests (ver «Desarrollo» en el [README](README.md)).
3. Haz el cambio más pequeño que lo resuelva, con su test. Las fuentes se prueban con HTML real recortado, en `tests/fixtures/`.
4. Abre una *pull request* explicando qué cambia y qué has comprobado. La CI ejecuta todos los tests.

## Reglas del proyecto

- **Fidelidad a la fuente:** se transforma lo mínimo y los textos van tal como los publica el organismo.
- **Calidad antes que cantidad:** una fuente solo se activa si título, fechas y enlace son fiables.
- **Respeto a los servidores:** peticiones de una en una, con pausa (2 s o la que pida `robots.txt`), sin formularios ni cuentas.
- **TLS siempre verificado:** nunca se desactiva; si un servidor envía mal su cadena, se añade el intermedio correcto en `empleo/certs/`.
- **Sin datos personales:** no se copian listas de personas y nunca se automatiza una inscripción.
- **Sin IA en la ejecución:** la ingesta y los avisos son deterministas, sin llamadas a modelos de lenguaje.

## Licencia de las contribuciones

Al contribuir aceptas que tu aportación se publique con la licencia del proyecto: código bajo [EUPL 1.2](LICENSE) y datos bajo CC BY 4.0.
