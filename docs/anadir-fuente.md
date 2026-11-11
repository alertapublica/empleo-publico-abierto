# Añadir un organismo

1. Crea `empleo/sources/<organismo>.py` con una clase que herede de `Source`, o reutiliza una plataforma ya hecha (SuccessFactors, por ejemplo). Si es autonómico, declara su `scope` con el nombre de la comunidad.
2. Implementa `list_offers`, que debe lanzar `SourceLayoutError` si la página cambia.
3. Implementa, si procede, `fetch_detail`, `enrich` y `list_announcements`.
4. Añádelo a su grupo en `CATALOG` (`empleo/sources/__init__.py`): Grupo SEPI, otras empresas del Estado, empresas públicas autonómicas, empresas públicas locales o fundaciones y centros de investigación. Quítalo de `PLANNED`.

El motor, la web y los feeds no necesitan cambios. La clase `FakeSource` de `tests/test_ingest.py` es un ejemplo mínimo.

Antes de escribir el analizador, mira cómo se lee un portal nuevo y qué se sabe ya de cada fuente en [`hallazgos/`](../hallazgos/).

## Cómo se reparte lo que publica cada portal

Lo decide la forma en que publica el propio portal, no una clasificación nuestra:

- **Oferta** (`ListedOffer`, portada): algo a lo que una persona de fuera puede presentarse ahora, con ficha y plazo. Incluye bolsas, prácticas y becas.
- **Proceso** (`Announcement`, «Procesos selectivos»): comunicados de un proceso publicado por fases. Solo título, fecha y enlace.
- **No se lee:** ayudas a proyectos, resoluciones con nombres, exámenes, listas de personas y la promoción interna como oferta.

## Reglas al escribir una fuente

- El contrato va con el texto literal de la fuente en `contract`. `kind` solo se rellena si la fuente lo dice sin ambigüedad. No se deduce nada del título.
- Si el portal pega un código interno al título («OE 25/26 - Analista»), la fuente declara `title_code`: el título queda limpio, el código va a `code` y el literal a `source_title`. `ref_code` dice qué `ref` son el código que publica el portal; los ids de URL, hashes y slugs no se enseñan.
- Abierta o cerrada se decide por las fechas (`opens_on`, `deadline`, `deadline_time`), no por la etiqueta de la web.
- Si el portal pide una pausa mayor entre peticiones, se respeta.
- No se copian listas de personas candidatas, se omiten los códigos de candidatura y nunca se automatiza una inscripción.
