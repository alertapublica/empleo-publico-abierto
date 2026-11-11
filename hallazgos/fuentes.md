# Fuentes: estado de cada portal

Revisado el 2026-11-08. Los plazos de cada una están en [`plazos.md`](plazos.md).

**Estados:** **Activa** (en `CATALOG`) · **Centinela** (solo vigila el texto de «no hay ofertas») · **T2** (siguiente tanda) · **Luego** (válida, con más trabajo) · **Fuera** (no se puede leer bien hoy, o no encaja).

## Activas

El detalle de cada una está en el docstring de su módulo. Aquí, solo lo que conviene recordar.

| Fuente | Módulo | A tener en cuenta |
|---|---|---|
| **Tragsa** | `tragsa.py` | Web (SharePoint) y portal de candidatos (PeopleSoft, sesión de invitado) son el mismo universo. La ficha se vacía al cerrar: hay que guardarla al detectar la oferta. Hay republicaciones con `jobid` nuevo («proviene de la publicación con ID …»). Las fijas son procesos con comunicados; algunos títulos traen códigos de candidatura, que se quitan |
| **EFE** | `efe.py` | `robots.txt` bloquea los PDF |
| **Correos, Navantia** | `successfactors.py` | El RSS vacío de Navantia trae un elemento marcador (`guid` 0). Navantia sin ofertas reales vistas; paginación de más de 25 sin ver |
| **Enusa** | `enusa.py` | El contador («13») no coincide con las filas (10) y se ignora. Títulos cortados por la propia web |
| **RTVE** | `rtve.py` | Solo se ha visto sin inscripciones abiertas: el formato real de `fechaFinInscripcion` está sin ver; uno desconocido detiene la fuente. La convocatoria 1/2025 de la prensa no está en la API |
| **Enresa** | `enresa.py` | Los procesos «en proceso» no tienen fecha |
| **ETSA** | `etsa.py` | Contrato deducido del nombre de las bases; ubicación solo en PDF |
| **Cetarsa** | `cetarsa.py` | «Bolsas… para personal de Cetarsa»: no consta si son solo internas |
| **Cofivacasa** | `cofivacasa.py` | Sin día de publicación, solo mes |
| **Zarzuela, Mercasa, Sepides** | `zarzuela.py`, `mercasa.py`, `sepides.py` | Plazo en PDF (`pypdf`). Sus listados y adjudicaciones no se anuncian: no tienen fecha |
| **Grupo Hunosa (SADIM)** | `hunosa.py` | Los 5 enlaces de `hunosa.es/empleo-publico/` dan 404; solo se lee `sadim.es/empleo` |
| **ENAIRE, Aena** | `pfsrv.py` | Latin-1. Aena sin convocatoria abierta real vista. Un anulado con fechas vigentes saldría como abierto |
| **Puertos del Estado** | `puertos.py` | Solo `offer_type=108`. Las autoridades portuarias (`107`, 30+ páginas, plazo a veces solo en PDF) no se leen |
| **SENASA** | `senasa.py` | Intermedio TLS en `empleo/certs/` |
| **ISDEFE** | `isdefe.py` | `seleccionisdefe.es`, sin `www`. Solo se leen los calendarios de filas con enlace de inscripción |
| **TMB** | `tmb.py` | Primer organismo del grupo «local». Liferay en catalán; todas las ofertas laborales en un carrusel (65, casi todas cerradas), con «Termini: dd/mm/aaaa - dd/mm/aaaa» sin hora. Cada tarjeta lleva «En curs» y «Finalitzat» a la vez: mandan las fechas. Ficha con plazas, descripción («amb caràcter indefinit»), bases (Liferay: `….pdf/<uuid>?t=`) y formulario. Prácticas en otra página, sin leer. **Procesos pendientes**: «Estat dels processos de selecció» enlaza 74 páginas de seguimiento. Del informe de Codex (2026-11-11) |
| **FNMT-RCM** | `fnmt.py` | Liferay, 20 procesos por página sin fechas, por última modificación; el id del recurso crece con el alta. La ficha necesita el enlace completo (sin `p_r_p_assetEntryId`: «El usuario no existe»). Oferta = solo comunicados de convocatoria y plazo del aviso (o de las bases) sin vencer; se para en la primera ficha con otras fases (máx. 8). `FC` (p. ej. directores) sin aclarar: se ofrece igual. La «Bolsa de empleo» son bolsas resultantes (listas de personas): no se lee. Los comunicados de fases (Procesos) aún no se anuncian |
| **FGC** | `fgc.py` | Algunas convocatorias son cursos de formación para acceder a puestos: se ofrecen tal cual |
| **GPEX** | `gpex.py` | Intermedio TLS. Latin-1 en la plantilla y UTF-8 en los datos. «Causa del contrato» en plazas fijas sin comprobar |
| **GESPLAN** | `gesplan.py` | Siglas de las islas delante del título |
| **SARGA** | `sarga.py` | `Crawl-delay: 10` y paginación prohibida: solo la primera página. Bases con letras cambiadas («Alcaæiz»). Las convocatorias de campaña (agosto) van en otra página y no se leen |
| **SERPA** | `serpa.py` | Las actas del tablón no se leen: no tienen orden fijo |
| **SEPI** | `sepi.py` | Por un relay con IP española (`VIA_RELAY` en `empleo/http.py`). Drupal sin fechas: solo un texto libre de estado (`.plazo`) que cambia con la fase. Oferta = la frase «plazo de presentación de candidaturas/solicitudes» con fecha completa; la hora, si la da esa frase. Comprobado en capturas del Internet Archive (2025–2026). Sin fecha de publicación (la carpeta del PDF es el mes de subida). Procesos como en EFE (mientras hay plazo, oferta): comunicados = texto de estado del listado + documentos de la ficha (una petición por proceso en cada lectura), sin fecha: se ordenan por detección y los de la primera lectura no son novedad. En 2023–2024 el listado incluía procesos de Mercasa, SAECA o Sepides: hoy saldrían con empresa «SEPI» |
| **Mayasa** | `mayasa.py` | Grupo SEPI. Listado JetEngine con publicación y cierre; manda la fecha, no «Cerrado». La hora («finaliza el día 27 de mayo a las 23:59 horas», sin año) sale del PDF de convocatoria y solo vale si coincide con el día del cierre. Bloque abierto sin ver: el 2026-11-08 las 5 estaban cerradas |
| **Canal de Isabel II** | `canal.py` | Fijas en `convocatoriascanaldeisabelsegunda.es` (misma aplicación que ISDEFE, otra tabla). Fila abierta sin ver (122 «Cerrada inscripción»): no se usan el estado ni la última columna; se leen los calendarios de los últimos 60 días (máx. 8) y manda «Admisión de solicitudes». Sin hora. Cáceres (otra página) y temporales (ePreselec) no se leen |
| **IDIBELL, FISABIO, IDIVAL** | `fundanet.py` | Mismo Fundanet. Fin con hora variable (12:24, 16:59, 0:00). Solo se enlazan las bases: IDIVAL pone «Admitidos y excluidos» entre los documentos. Contrato: ficha (IDIBELL), bases PDF (FISABIO), sin campo (IDIVAL). Ubicación = comunidad. Títulos literales (FISABIO en mayúsculas). IDIBELL solo en inglés (`/es/`, `/ca/` y `/en/` dan el mismo texto): título y texto con `lang="en"`. Listado vacío sin ver |
| **IdiSNA** | `idisna.py` | Todo del RSS (15 últimas, abiertas y cerradas): «Modalidad de contrato», publicación y cierre con hora (12:00). El listado web dice «Vigente» con el plazo vencido. Algún título acaba en «- Copia» (literal) |
| **IBSAL (FIBSAL)** | `ibsal.py` | WP Job Openings: la página solo lista las vigentes. Caducidad sin hora en la ficha («22 Oct 2026»), contrato literal (art. 23 bis). Tarjeta de una vigente sin ver: el 2026-11-08 no había ninguna |
| **Navarrabiomed** | `navarrabiomed.py` | Contrata la Fundación Miguel Servet. Cierre sin hora; contrato solo en las bases. No se sabe si las tarjetas cerradas se retiran |
| **FUNDESALUD** | `fundesalud.py` | Tres pestañas en la misma página; mandan las fechas. Referencias sin formato fijo («Ref:18/2025», «REF. P26-03», «PMP25/2026»): clave = id de la entrada (`post-N`). Plazos de 2–3 días. La ficha no se lee: enlaza listas de admitidos y puntuaciones |
| **IIS La Fe** | `lafe.py` | Tarjetas por referencia; el plazo no sigue ese orden, así que se lee la página siguiente mientras alguna siga en plazo (máx. 3). Contrato solo en las bases. Solo se enlazan las bases |
| **CiQUS (USC)** | `ciqus.py` | Centro de la USC. Plazo con hora en atributo ISO, solo en las abiertas. «Abierta» antes de empezar: se guarda el inicio. `Crawl-delay: 10`, una petición |
| **CiMUS (USC)** | `cimus.py` | Centro de la USC. Listado sin fechas (62 filas desde 2024): se leen las 5 primeras fichas. Fin en campo estructurado sin hora; la hora sale de «Fecha fin candidaturas». «Fecha fin enmiendas» es la subsanación. Los documentos incluyen listas de admitidos: solo se enlaza la ficha |
| **FISEVI** | `fisevi.py` | Listado por la API REST (categoría 45; contenido vacío): se leen las entradas de los últimos 15 días. La etiqueta «Abierta» del listado web no sigue el plazo. Año del plazo a veces mal: solo vale entre la publicación y 60 días después. Anuladas fuera (filtro sin ver con una real). Las correcciones de errores van en PDF |
| **IMIB (FFIS)** | `imib.py` | `rrhh.ffis.es/` por GET: 10 filas sin orden (las de id más alto); si la más antigua sigue en plazo, se detiene. La hora (10:00, 13:00) solo está en la ficha antigua `ofertaEmpleo.jsf`, no en `ofertaEmpleoNew.jsf`: se lee para las que siguen en plazo |
| **IRYCIS** | `irycis.py` | Contrata la Fundación para la Investigación Biomédica del H. U. Ramón y Cajal. Tabla por año con fechas sin año: año de la tabla, que debe coincidir con el sufijo (`C75/26`); cierre anterior a la convocatoria = año siguiente; más de 60 días, fuera. Solo las dos últimas tablas. Convocatoria en PDF escaneado (sin hora). Título literal (suele ser la titulación). Las actas no se enlazan. Si en enero la tabla del año nuevo aún no existe, la fuente se detiene (sin ver) |
| **CESCE** | `cesce.py` | Liferay. Dos listados en la misma página: el de agentes mediadores (tras `carreras.mediadores@cesce.es`) no se lee. Estado literal («Abierta», «Proceso»; uno desconocido detiene la fuente). Plazo solo en el PDF de la convocatoria, sin año ni hora: año de la publicación del documento; vale la fecha mayor con las ampliaciones. «Abierta» con el plazo vencido pasa a proceso. Comunicados = documentos con su «Fecha de publicación», sin los anexos |
| **FRCB-IDIBAPS** | `idibaps.py` | Web del Clínic, en catalán. Pestañas `#active` («Obertes», todas en una página) e `#inactive` (318 páginas de histórico, no se leen). «Data límit» sin hora. El título enlaza al PDF de la convocatoria (no se lee). Código `FU-338/2026` o `FU-ES-16/2026`. Hueco de resoluciones vacío en todas: sin procesos por ahora. Del informe de Codex (2026-11-11) |
| **Mercasturias** | `mercasturias.py` | `www.mercasturias.com` (el `.es` falla en TLS). Página estática: una lista de PDF con fecha («4 de noviembre 2026»), sin bloques por proceso: cada bases («Cobertura de puesto de trabajo …») abre uno. Plazo en las bases y ampliaciones (la extracción parte la hora: «23: 59»). Oferta = solo bases y ampliaciones, con plazo sin vencer; si no, proceso. La web no marca los terminados: siguen «en curso». Las relaciones de admitidos se anuncian (título y enlace), no se copian |
| **IdISBa** | `idisba.py` | Cinco por página (`/page/N`), por publicación, no por plazo: se lee la siguiente mientras alguna siga abierta (máx. 3). Plazo en `<time datetime>` (inicio y fin, sin hora). Referencias `2026-50-RLTIDISBA` o `L03130017`. Documentos con la fecha en el nombre a veces («20261104_lista_…»). Sin procesos: al pasar de página se darían por retirados. Del informe de Codex (2026-11-11) |
| **FGV** | `fgv.py` | WordPress con la API REST desactivada. Árbol de páginas de «Convocatorias en proceso»: convocatoria → subpáginas (comunicados), sin fecha en ningún sitio (tampoco dentro): van sin fecha, ordenados por el id de página. Plazo en la subpágina «Apertura plazo…» («Inicio:» / «Fin: … a las 11:59 horas»); solo se lee en las convocatorias sin listados ni otras fases (hoy, dos peticiones). OEP y bolsas en la misma convocatoria: contrato sin indicar. «ANULADA:» = terminado. Las cerradas (otra rama del árbol) no se leen |
| **CNIC** | `cnic.py` | Drupal 7, una tabla (`views-table`) con puesto, referencia, fin de inscripción (sin hora) y estado literal. El atributo `content` de la fecha no coincide con el texto: manda el texto. `Crawl-delay: 10`. Oferta = «Presentación de solicitudes» en plazo; procesos = el estado literal de las demás, sin fecha (cada cambio, un comunicado); «Cerrada» = terminado. Algún título en inglés. Del informe de Codex (2026-11-11) |

## Centinelas

| Fuente | Qué falta para el analizador |
|---|---|
| **ADIF** | Ver una oferta abierta. Liferay con HTML de servidor (`li.col-12 > div.oep-wrapper-list`). Su WAF (Akamai) da 403 si el `User-Agent` lleva la URL de GitHub o falta `Accept`; con UA corto y `Accept: text/html` da 200, también desde Actions. Procesos en curso y resueltos ya se podrían anunciar (título, fecha, estado, plazas) |
| **Renfe** | Ver `/search/` con ofertas. SuccessFactors muy personalizado: `successfactors.py` no sirve. `robots.txt` prohíbe `/services/`. Las fechas de los procesos solo están en los PDF |

## Siguiente tanda (T2): pendientes

Revisadas de nuevo el 2026-11-08. Las demás de la tanda 2 ya están activas.

| Fuente | Qué falta |
|---|---|
| **IGTP** (Cataluña) | Personio sin plazo en el feed ni en el texto. El feed sigue listando una convocatoria de julio y unas prácticas de febrero: no consta que retire las cerradas, así que no se activa (decisión del 2026-11-08). Comparar los `id` del feed dentro de unas semanas |

## Luego

| Fuente | Motivo |
|---|---|
| **CSAG / CRTVG** (Galicia) | Sin plazo de inscripción en la web. `Crawl-delay: 10`; intermedio TLS equivocado |

## Fuera

| Fuente | Motivo |
|---|---|
| **Paradores** (temporales), **ENWESA**, **Canal** (temporales) | ePreselec con reto de Imperva (405). Paradores además con TLS incompleto |
| **ENSA** | Widget JavaScript de Talentclue sin origen de datos identificado; la URL del estudio lleva a la web comercial |
| **SEAGA** | Sin plazos; listas con nombres |
| **Retegal** | Documentos sin fecha, todo en PDF |
| **VAERSA** | Todo promoción o cobertura interna; listas con nombres |
| **GEACAM** | La API pide un identificador de entidad: no se ve sin cuenta |
| **Correos Express** | Aplicación React; API sin identificar |
| **Fundación SEPI, Correos Telecom** | TLS incompleto, sin revisar intermedio |
| **Saeca, SAES, Emgrisa, Sainsel, Hunosa Empresas, Mercabadajoz, Mercamálaga, Mercalaspalmas, Mercalgeciras** | Sin ofertas a la vista, enlace roto, licitaciones mezcladas o sin sección de empleo (2026-11-07) |
| **SASEMAR** | Timeout también desde Actions |
| **SELAE, ICO, COFIDES, ICEX** | Poco volumen o sin listado |
| **Hispasat** | No es mayoritariamente pública (Indra) |

## Sin revisar

Del estudio externo, todavía sin leer: Sogama, SODECAN, ESAMUR, GITPA, Tracasa, Visesa, VEIASA, IdISBa, INIBIC, IIS Galicia Sur, FIBAO, IBIMA/FIMABIS, IDIS/FIDIS, IRB Barcelona, IDIAP Jordi Gol, Fundación para la Transformación de La Rioja y Fundación de la Universidad de La Rioja. También las filiales del índice de SEPI (`sepi.es/es/empleo-publico/en-empresas-del-grupo`) no citadas aquí.
