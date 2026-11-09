# Plazos: cómo los publica cada portal y cómo no equivocarse

Revisado el 2026-11-08.

## Fallos pendientes en el portal

Resuelto el 2026-11-08: la hora de cierre ya cierra la oferta (`deadline_passed` en `empleo/model.py`), y Cetarsa, SADIM, Mercasa, Tragsa (fijas) y ENAIRE guardan la hora que leen. Los procesos (`Announcement`) también admiten `deadline_time`: pasada la hora, la inscripción deja de figurar abierta.

1. **Correos y Navantia:** el plazo se lee una vez al encontrar la oferta. Si después lo amplían, no se detecta.

## Reglas

- **Lo que manda son las fechas, no la etiqueta.** «Abierta», «Vigente», «Activa» o «Abierto» no significan que se pueda presentar candidatura. Comprobado en EFE, Sepides, SARGA, FGC, IDISNA, FUNDESALUD, CiQUS, FISEVI, VAERSA, ISDEFE y Canal.
- **Si el portal da el inicio, se guarda (`opens_on`).** Algunas convocatorias se publican antes de abrir: CiQUS marcaba «Abierta» una que empezaba al día siguiente.
- **Si da la hora de cierre, se guarda (`deadline_time`)**, se muestra y la oferta se cierra a esa hora (Madrid). Sin hora, el último día cuenta entero. En una ampliación a otro día, la hora del plazo anterior no se arrastra.
- **Ampliaciones: vale la fecha mayor** entre las bases y sus ampliaciones (Mercasa pasó del 29-10 al 16-11; Enusa y Cetarsa añaden la nueva fecha en el mismo texto). Una rectificación con otras palabras no se detectaría.
- **Fechas sin año** (Enusa: «hasta el próximo día 11 de noviembre»): el año de la publicación, o el siguiente si así la fecha queda antes de publicarse. Si no hay forma segura (SERPA: «el próximo lunes 7 de abril» en fichas antiguas), no se ofrece.
- **No inventar el plazo.** Sin fecha fiable se muestra «Plazo sin indicar», o la fuente no se activa.
- **Zona horaria:** todo se calcula en Europe/Madrid (`empleo/model.py`). Canarias publica en su hora local (GESPLAN), aunque hoy no lo distinguimos.

## Fechas que no son el plazo

| Fuente | Fecha engañosa | Qué es en realidad |
|---|---|---|
| SuccessFactors (FGC) | `validThrough` del JobPosting | Cuándo se retira el anuncio. Puede caer días después del plazo. En FGC vale la tarjeta del listado |
| SuccessFactors (Correos, Navantia) | `validThrough` | Medianoche UTC del día siguiente al último día. Se convierte |
| SENASA | «fecha fin de vigencia» | Parece la retirada del anuncio, no el plazo de las bases. Es la única fecha que hay. Se exige además que el título enlace al formulario |
| GPEX, llamamientos de bolsa | «48 horas» | Cuándo empiezan a seleccionar entre quienes ya están en la bolsa, no un plazo de inscripción. Van a procesos |
| Tragsa, portal de candidatos | `MM/DD/AAAA` | Mismo plazo que la web, que usa `DD/MM/AAAA` |
| Rutas de PDF (Sepides, Mercasa, Zarzuela) | `/2026/07/` | Mes de subida del documento. Sirve para ordenar fases, no como fecha de publicación |
| ISDEFE | Columna de estado | Igual en todas las filas. El plazo está en `/calendario-N` |
| FISEVI | Etiqueta «Abierta»/«Cerrada» del listado web | No sigue el plazo; el año del plazo puede estar mal |
| CiMUS | `datetime` del campo de fin (`T12:00:00Z`) y «Fecha fin enmiendas» | Día sin hora (la hora está en el texto) y plazo de subsanación |
| IRYCIS | Fechas «DD/MM» sin año | El año es el de la tabla; un cierre en enero de una convocatoria de diciembre es del año siguiente |

## Dónde está el plazo en cada fuente activa

| Fuente | Dónde | Inicio | Hora |
|---|---|---|---|
| Tragsa (temporales) | Columna del listado | — | 23:59 en la ficha (no se lee) |
| Tragsa (fijas) | Cuerpo de los comunicados | — | Sí |
| EFE | Columna «plazo» | — | — |
| Correos, Navantia | `validThrough` de la ficha | — | — |
| Enusa | Texto de la descripción | — | — |
| RTVE | API, `fechaInicioInscripcion` / `fechaFinInscripcion` | Sí | Formato real sin ver |
| Enresa | Texto «del 4 al 17 de noviembre de 2026» | — | — |
| ETSA | Ficha, «antes del …» | — | — |
| Cetarsa | Fila de texto de la tabla | — | 14:00 |
| Cofivacasa | Solo en las bases (PDF); la página da mes y estado | — | — |
| Zarzuela | Bases (PDF) | — | — |
| Mercasa | Bases y ampliaciones (PDF) | — | 12:00 |
| SADIM | Texto de la página | — | 17:00 |
| Sepides | PDF de convocatoria | — | — |
| ENAIRE, Aena | Listado con fechas de inscripción | Sí (filtra) | ENAIRE 23:59 |
| Puertos del Estado | Ficha | — | — |
| SENASA | «fecha fin de vigencia» (ver arriba) | — | — |
| ISDEFE | Calendario, hito de inscripción | Sí | — |
| FGC | Tarjeta del listado | — | — |
| GPEX | Tarjeta, «DD/MM/AAAA - DD/MM/AAAA» | Sí | — |
| GESPLAN | Tarjeta, «Plazo de inscripción» | — | — |
| SARGA | Listado (día) y bases (hora) | — | Sí, si coincide el día |
| SERPA | Ficha, «Hasta las 08:00 horas del …» | — | Sí |
| IDIBELL, FISABIO, IDIVAL | Columnas de la tabla de Fundanet | Sí | Sí, variable |
| IdiSNA | RSS, «Fecha de cierre: … a las 12:00h» | — | Sí |
| IBSAL | Ficha, caducidad del plugin | — | — |
| Navarrabiomed | Tarjeta, «Fecha de cierre» | — | — |
| FUNDESALUD | Tarjeta, «Inicia» y «Finaliza» | Sí | — |
| IIS La Fe | Tarjeta, «Plazo de presentación» | — | — |
| CiQUS | Tabla, atributo ISO | Sí | Sí |
| CiMUS | Ficha, campo de fin y «Fecha fin candidaturas» | Sí | Sí, 23:59 |
| FISEVI | Texto de la entrada, «Antes de las 23:59 horas del día …» | — | Sí |
| IMIB | Rango en el listado; hora en la ficha antigua («hasta las 10:00 del …») | Sí | Sí, variable |
| IRYCIS | Tabla por año con «DD/MM» de convocatoria y cierre; año de la tabla, igual al sufijo de la referencia; cierre anterior a la convocatoria = año siguiente | Sí | No |
| FNMT-RCM | Aviso de convocatoria en PDF («estará abierto desde el día 27 de octubre hasta el 18 de noviembre de 2026»); sin aviso, las bases | No (el inicio va sin año) | No vista |
| Mayasa | «CIERRE · DD-MM-AAAA» en el listado; hora en la convocatoria PDF (día y mes sin año) | No | Sí (23:59 visto) |
| Canal de Isabel II | Calendario `/calendario-N`, fase «Admisión de solicitudes» | Sí | No |

## Plazos en las fuentes de la siguiente tanda

Leído el 2026-11-08 (ver `fuentes.md`). Antes de escribir cada analizador se vuelve a comprobar en directo.

| Fuente | Dónde | Inicio | Hora | Riesgo |
|---|---|---|---|---|
| IGTP (Personio) | No consta | — | — | Ofertas sin plazo; el feed mantiene convocatorias de julio: no consta que retire las cerradas |
