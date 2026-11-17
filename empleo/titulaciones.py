"""Titulación exigida en cada oferta: lectura orientativa nuestra, solo para filtrar.

Cada fuente dice dónde está su titulación exigida (`Source.titulacion`, sobre los apartados ya
guardados, sin red): aquí están el modelo, la lista común y la lectura de una frase. El texto
literal manda siempre; lo que se saca de él es un índice para buscar, no un dictamen de acceso.

Modelo (`Requisito`):
- `estado`: consta, no exigida (solo si la ficha lo dice) o no consta, con su `motivo`.
- `exigido`: el texto literal del que sale todo lo demás.
- `vias`: formas de cumplir el requisito, alternativas entre sí. Los títulos de una vía se suman
  («Grado + Máster» es una vía con dos títulos; «Licenciatura o Grado» son dos vías). Cada vía
  lleva el nivel MECES que el texto escribe para ella, si lo escribe.
- `titulaciones`: claves de TITULACIONES y FP_FAMILIAS que el texto nombra, sin repartir por vías.
- `sin_clave`: especialidades que nombra y no están en la lista (para ampliarla).
- `parcial`: motivos por los que la lectura no es completa. Con alguno, lo leído vale como
  mención, no como relación de vías.

Lectura de la frase (`lee`), sobre el texto normalizado:
- FRASES, en orden: cada una se come su texto. None: parece un título y no lo es.
- «+ Máster» (o «y», «con») se suma al título anterior y a los de primer ciclo que lo preceden
  seguidos («Diplomatura/Grado + Máster»); una licenciatura anterior queda como vía aparte.
- «Ingeniería» y «Arquitectura» son título (anterior a Bolonia) en una enumeración de títulos
  («Licenciatura, Ingeniería o Grado») y especialidad detrás de «en» o dentro de una lista de
  especialidades («Grado en Ingeniería Forestal»). Lo dudoso se queda en especialidad.
- «o experiencia…», «o conocimientos…»: vía sin título. Una experiencia que se suma al título, una
  habilitación o cualquier palabra de ALARMA sin leer dejan la lectura en parcial.
- El MECES escrito tiene que casar con la vía (un grado solo con MECES 3, salvo los que lo son, o
  una licenciatura con MECES 2 delatan una lectura mala): si no casa, parcial.
  Un «nivel 2 o 3» escrito para varias vías no se reparte (no dice cuál es cuál).
- Menciones: ante la duda, ninguna (mejor no salir en un filtro que salir en uno que no toca). Una
  clave cuenta si nombra la especialidad: al empezar su nombre o como complemento con «de» o «en»
  («Cuidados de Enfermería»); no si es adjetivo de otro nombre («Química Industrial», «Física
  Médica»), si va tras otra preposición o dentro de otra palabra, ni dentro de una condición
  («que incluya…», «valorándose…», «o afines», hasta el final de su frase).
No se calculan mínimos ni equivalencias: «Licenciatura» no se convierte en máster.

Nada de esto se publica todavía. `python -m empleo.titulaciones informe [fuente…]` da el resumen por
fuente, las lecturas parciales y las especialidades sin clave; `… fichas [fuente…]`, cada ficha con
su lectura, para revisarla a mano. Una fuente se publica cuando su muestra está revisada.
"""
from __future__ import annotations

import html
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import NamedTuple

CONSTA, NO_EXIGIDA, NO_CONSTA = "consta", "no_exigida", "no_consta"

TIPOS = {  # de más a menos
    "doctorado": "Doctorado",
    "master": "Máster",
    "titulo_superior": "Licenciatura, ingeniería, arquitectura o titulación superior",
    "grado": "Grado",
    "titulo_medio": "Diplomatura, ingeniería técnica o arquitectura técnica",
    "universitaria": "Titulación universitaria (sin más precisión)",
    "fp_superior": "FP de grado superior",
    "fp_medio": "FP de grado medio",
    "fp": "Formación profesional (sin grado indicado)",
    "fp_basica": "FP básica",
    "bachillerato": "Bachillerato",
    "eso": "ESO, EGB o graduado escolar",
    "experiencia": "Experiencia o conocimientos, sin título",
}
PRIMER_CICLO = {"grado", "titulo_medio", "universitaria"}
DE_FP = {"fp_superior", "fp_medio", "fp", "fp_basica"}
UNIVERSITARIOS = {"doctorado", "master", "titulo_superior", "grado", "titulo_medio", "universitaria"}


class Via(NamedTuple):
    tipos: tuple[str, ...]  # claves de TIPOS; se suman
    meces: tuple[int, ...] = ()  # niveles MECES escritos para esta vía («nivel 2 o 3 MECES» → 2, 3)


class Requisito(NamedTuple):
    estado: str
    motivo: str = ""  # si no consta: sin_lector, sin_ficha, sin_apartado
    exigido: str = ""
    vias: tuple[Via, ...] = ()
    titulaciones: tuple[str, ...] = ()
    sin_clave: tuple[str, ...] = ()
    parcial: tuple[str, ...] = ()


SIN_LECTOR = Requisito(NO_CONSTA, "sin_lector")

# ------------------------------------------------------------------------- vocabulario universitario
# (cada idioma va en su alternativa, pero todas se buscan en todos los textos: una excepción que solo
# lleve la española la salta la catalana. «Arquitectura» no es «Arquitectura Naval» ni la «de Software»)
_ARQ_ANTES = r"(?<!ingenieria de la )(?<!ingenieria de )(?<!ingenieria y )(?<!enginyeria i )(?<!enxenaria e )"
_ARQ_DESPUES = r"(?! tecnic)(?! naval)(?! (de|del|de la|d'|da) (software|programari|sistemas|sistemes|soluciones|solucions|datos|dades|computadores|red|redes|xarxes|la informacion|informacio))"
# clave: (nombre, {idioma: expresión}) sobre el texto normalizado (minúsculas, sin tildes ni «/a»).
TITULACIONES = {
    "caminos": ("Ingeniería civil, de caminos y obras públicas", {
        "es": r"caminos,? canales y puertos|\bcaminos\b|obras publicas|\bcivil\b(?! (y|e) )|\biccp\b|\bitop\b",
        "ca": r"camins,? canals i ports|obres publiques",
        "gl": r"camins,? canles e portos|camiños|obras publicas",
        "eu": r"ingeniaritza zibil\w*",
        "en": r"civil engineering"}),
    "industrial": ("Ingeniería industrial", {
        "es": r"\bindustrial\w*|tecnologias industriales|ingenieria (\w+ )?(mecanica|electrica|electronica|energetica|de la energia|de materiales|"
              r"en automatica|nuclear|de organizacion)(?! de (tele)?comunicaci)|mecanica|electrica\b|electronica industrial|automatica|\biti\b|organizacion industrial|"
              r"energias renovables",
        "ca": r"\bindustrials?\b|enginyeria (mecanica|electrica|electronica|de l'energia|de materials)(?! de (tele)?comunicaci)",
        "gl": r"enxenaria (mecanica|electrica|electronica|da enerxia)",
        "eu": r"industria ingeniaritza|ingeniaritza (mekaniko|elektriko|elektroniko)\w*",
        "en": r"(mechanical|electrical|industrial|electronic|energy|nuclear) engineering"}),
    "informatica": ("Informática y ciencia de datos", {
        "es": r"informatic\w*|\bsoftware\b|computacion|computadores|sistemas de informacion(?! geografica)|ciencias? de (los )?datos|inteligencia artificial|"
              r"ciberseguridad|sistemas de datos|tecnologias? de la informacion(?! geografica)|bioinformatic\w*",
        "ca": r"informatic\w*|\bprogramari\b|ciencia de dades",
        "gl": r"informatic\w*|ciencia de datos",  # (sin «comunicacion», que es de otra clave)
        "eu": r"informatika\w*",
        "en": r"computer science|computer engineering|software engineering|computing|data science|bioinformatics"}),
    "teleco": ("Telecomunicación", {
        "es": r"telecomunicaci\w*|telematic\w*|sistemas audiovisuales|sonido e imagen|comunicaciones moviles",
        "ca": r"telecomunicaci\w*|telematic\w*",
        "gl": r"telecomunicaci\w*",
        "eu": r"telekomunikazi\w*",
        "en": r"telecommunications?"}),
    "arquitectura": ("Arquitectura", {
        "es": _ARQ_ANTES + r"\barquitect(ura|o|os)\b" + _ARQ_DESPUES,
        "ca": _ARQ_ANTES + r"\barquitect(ura|e|es)\b" + _ARQ_DESPUES,
        "gl": _ARQ_ANTES + r"\barquitectura\b" + _ARQ_DESPUES,
        "eu": r"arkitektura\b",
        "en": r"\barchitecture degree|degree in architecture"}),
    "arquitectura_tecnica": ("Arquitectura técnica y edificación", {
        "es": r"arquitect\w* tecnic\w*|aparejador\w*|edificacion",
        "ca": r"arquitect\w* tecnic\w*|aparellador\w*|edificacio",
        "gl": r"arquitectura tecnica|aparellador\w*",
        "eu": r"arkitektura tekniko\w*",
        "en": r"building engineering"}),
    "montes": ("Ingeniería de montes y forestal", {
        "es": r"\bmontes\b|forestal\w*|medio natural",
        "ca": r"forestal\w*|\bforests\b",
        "gl": r"forestal\w*|\bmontes\b",
        "eu": r"basogintza\w*",
        "en": r"forestry|forest engineering"}),
    "agronomica": ("Ingeniería agronómica y agrícola", {
        "es": r"agronom\w*|agricola\w*|agroalimentari\w*|agrari\w*|hortofruticultura|explotaciones agropecuarias",
        "ca": r"agronom\w*|agricola|agroalimentari\w*|agrari\w*",
        "gl": r"agronom\w*|agricola|agrari\w*",
        "eu": r"nekazaritza\w*",
        "en": r"agronom\w*|agricultur\w*"}),
    "aeroespacial": ("Ingeniería aeroespacial y aeronáutica", {
        "es": r"aeroespacial|aeronautic\w*|sistemas del transporte aereo",  # «transporte aéreo» a secas es otro campo (SIIU 1041)
        "ca": r"aeroespacial|aeronautic\w*",
        "gl": r"aeroespacial|aeronautic\w*",
        "eu": r"aeroespazial\w*|aeronautika\w*",
        "en": r"aerospace|aeronautic\w*"}),
    "minas": ("Ingeniería de minas", {
        "es": r"\bminas\b|\bminer[oa]s?\b|recursos mineros",
        "ca": r"\bmines\b|enginyeria minera",
        "gl": r"\bminas\b",
        "eu": r"meatz\w*",
        "en": r"mining engineering"}),
    "naval": ("Ingeniería naval y oceánica", {
        "es": r"arquitectura naval|\bnaval\w*|\boceanic\w*|ingenieria maritima",  # «Náutica y Transporte Marítimo» es otro título
        "ca": r"\bnaval\b",
        "gl": r"\bnaval\b",
        "eu": r"itsas ingeniaritza",
        "en": r"naval architecture|marine engineering"}),
    "quimica": ("Química e ingeniería química", {
        "es": r"(?<!bio)\bquimic\w*",
        "ca": r"(?<!bio)\bquimic\w*",
        "gl": r"(?<!bio)\bquimic\w*",
        "eu": r"\bkimika\w*",
        "en": r"(?<!bio)chemistry|chemical engineering"}),
    "fisica": ("Física", {  # no «actividad física (y del deporte)»
        "es": r"(?<!actividad )(?<!actividades )(?<!activitat )(?<!actividade )\bfisicas?\b|astrofisica",
        "ca": r"(?<!activitat )(?<!actividad )(?<!actividade )\bfisica\b",
        "gl": r"(?<!actividade )(?<!actividad )(?<!activitat )\bfisica\b",
        "eu": r"\bfisika\b",
        "en": r"\bphysics\b"}),
    "matematicas": ("Matemáticas y estadística", {
        "es": r"matematic\w*|\bestadistic\w*",
        "ca": r"matematiques|estadistica",
        "gl": r"matematicas|estatistica",
        "eu": r"matematika\w*|estatistika\w*",
        "en": r"mathematics|statistics|biostatistics"}),
    "biologia": ("Biología, bioquímica y biotecnología", {
        "es": r"biolog\w*|bioquimic\w*|biotecnolog\w*|(?<!ingenieria )(?<!enginyeria )(?<!enxenaria )biomedic\w*|genetica|microbiolog\w*|ciencias de la vida|biosanitari\w*|ciencias del medio ambiente natural",
        "ca": r"biolog\w*|bioquimica|biotecnolog\w*|(?<!ingenieria )(?<!enginyeria )(?<!enxenaria )biomedic\w*|ciencies de la vida",
        "gl": r"bioloxi\w*|bioquimica|biotecnoloxi\w*|(?<!ingenieria )(?<!enginyeria )(?<!enxenaria )biomedic\w*",
        "eu": r"biologia\w*|biokimika\w*|bioteknologia\w*",
        "en": r"biology|biochemistry|biotechnology|life sciences?|\blife (or|and) health|(?<!ingenieria )(?<!enginyeria )(?<!enxenaria )biomedic\w*\b(?! engineering)|biological sciences|biosciences|genetic\w*"}),
    "ambientales": ("Ciencias ambientales", {
        "es": r"ciencias (medio)?ambientales|ciencias \w+ (o|y) (medio)?ambientales|ambientologia|ingenieria ambiental|medio ?ambiente",
        "ca": r"ciencies ambientals|enginyeria ambiental|medi ambient",
        "gl": r"ciencias ambientais|medio ambiente",
        "eu": r"ingurumen zientzi\w*",
        "en": r"environmental (science|engineering)"}),
    "geologia": ("Geología", {  # «Ingeniería Geológica» es otro título (ni Geología ni Minas)
        "es": r"(?<!ingenieria )(?<!enginyeria )(?<!enxenaria )geolog\w*", "ca": r"(?<!ingenieria )(?<!enginyeria )(?<!enxenaria )geolog\w*", "gl": r"xeolox\w*", "eu": r"geologia\w*", "en": r"geology"}),
    "geografia": ("Geografía y ordenación del territorio", {
        "es": r"\bgeografia\b|ordenacion del territorio", "ca": r"\bgeografia\b", "gl": r"\bxeografia\b",
        "eu": r"geografia\w*", "en": r"geography"}),
    "geomatica": ("Geomática y topografía", {
        "es": r"geomatic\w*|topograf\w*|geodesi\w*|cartograf\w*|geoinformacion|sistemas de informacion geografica|teledeteccion",
        "ca": r"topograf\w*|geomatica|sistemes d'informacio geografica",
        "gl": r"topograf\w*", "eu": r"topografia\w*", "en": r"geomatics|surveying"}),
    "mar": ("Ciencias del mar", {
        "es": r"ciencias del mar", "ca": r"ciencies del mar", "gl": r"ciencias do mar", "eu": r"itsas zientzi\w*",
        "en": r"marine science"}),
    "veterinaria": ("Veterinaria", {
        "es": r"veterinari\w*", "ca": r"veterinari\w*", "gl": r"veterinari\w*", "eu": r"albaitar\w*", "en": r"veterinary"}),
    "alimentos": ("Ciencia y tecnología de los alimentos", {
        "es": r"tecnologia de (los )?alimentos|ciencia y tecnologia de los alimentos|industrias alimentarias",
        "ca": r"tecnologia dels aliments", "gl": r"tecnoloxia dos alimentos", "eu": r"elikagaien zientzia\w*",
        "en": r"food (science|technology)"}),
    "medicina": ("Medicina", {
        "es": r"\bmedicina\b(?! nuclear)|\bmedic[oa]s?\b(?! (especialista|interno))", "ca": r"\bmedicina\b|\bmetges?\b",
        "gl": r"\bmedicina\b", "eu": r"medikuntza\w*", "en": r"\bmedicine\b|\bmd\b|medical degree"}),
    "enfermeria": ("Enfermería", {
        "es": r"enfermeria|enfermer[oa]s?\b", "ca": r"infermeria|infermer[ae]s?\b", "gl": r"enfermaria|enfermeir[oa]s?\b",
        "eu": r"erizain\w*", "en": r"nursing"}),
    "farmacia": ("Farmacia", {
        "es": r"\bfarmacia\b|farmaceutic[oa]s?\b", "ca": r"\bfarmacia\b", "gl": r"\bfarmacia\b", "eu": r"farmazia\w*",
        "en": r"pharmacy"}),
    "psicologia": ("Psicología", {
        "es": r"psicolog\w*", "ca": r"psicolog\w*", "gl": r"psicolox\w*", "eu": r"psikologia\w*", "en": r"psychology"}),
    "sanidad_otras": ("Otras ciencias de la salud", {
        "es": r"fisioterapi\w*|odontolog\w*|terapia ocupacional|logopedia|optica y optometria|podologia|ciencias de la salud|"
              r"nutricion humana|dietetica",
        "ca": r"fisioterapi\w*|ciencies de la salut",
        "gl": r"fisioterapi\w*|ciencias da saude",
        "eu": r"fisioterapia\w*|osasun zientzi\w*",
        "en": r"physiotherapy|health sciences?|\bhealth (or|and) \w+ sciences|nutrition"}),
    "economia": ("Economía, ADE y empresa", {
        "es": r"\beconomi\w*|\bade\b|administracion y direccion de empresas|empresariales|finanzas|contabilidad|actuarial|"
              r"marketing|comercio internacional",
        "ca": r"\beconomi\w*|administracio i direccio d'empreses|empresarials|finances|marqueting",
        "gl": r"\beconomi\w*|administracion e direccion de empresas|empresariais",
        "eu": r"ekonomia\w*|enpresen administrazio\w*",
        "en": r"economics|business administration|\bmba\b|finance|accounting"}),
    "derecho": ("Derecho", {
        "es": r"\bderecho\b|ciencias juridicas(?! de las administraciones)", "ca": r"\bdret\b", "gl": r"\bdereito\b", "eu": r"zuzenbide\w*",
        "en": r"\blaw\b|\bllb\b"}),
    "laborales": ("Relaciones laborales y recursos humanos", {
        "es": r"relaciones laborales|graduado social|recursos humanos|ciencias del trabajo",
        "ca": r"relacions laborals|recursos humans", "gl": r"relacions laborais",
        "eu": r"lan harreman\w*", "en": r"human resources|labou?r relations"}),
    "comunicacion": ("Periodismo y comunicación", {
        "es": r"periodismo|\bcomunicacion\b( audiovisual| digital| corporativa)?|publicidad|ciencias de la informacion|relaciones publicas",
        "ca": r"periodisme|\bcomunicacio\b|publicitat", "gl": r"xornalismo|\bcomunicacion\b",
        "eu": r"kazetaritza\w*|komunikazio\w*", "en": r"journalism|communication"}),
    "humanidades": ("Humanidades, filología y traducción", {
        "es": r"filolog\w*|traduccion|interpretacion|humanidades|(grado|licenciatura|diplomatura) en historia|historia del arte|"
              r"bellas artes|(informacion y )?documentacion(?! sanitaria)(?=\W*$)|biblioteconomia|archivistica|filosofia|arqueologia|"
              r"(grado|licenciatura|diplomatura) en (informacion y )?documentacion|informacion y documentacion",
        "ca": r"filolog\w*|traduccio|humanitats",
        "gl": r"filoloxi\w*|traducion|humanidades",
        "eu": r"filologia\w*|itzulpengintza\w*",
        "en": r"philology|translation|humanities|history|archaeology"}),
    "social": ("Trabajo social, educación y sociología", {
        "es": r"trabajo social|educacion social|\bsociolog\w*|ciencias politicas|magisterio|maestro|pedagog\w*|"
              r"ciencias de la educacion|antropologia|intervencion social",
        "ca": r"treball social|educacio social|sociolog\w*|magisteri|pedagog\w*",
        "gl": r"traballo social|educacion social|socioloxi\w*",
        "eu": r"gizarte lan\w*|soziologia\w*",
        "en": r"social work|\bsociology|political science"}),
    "turismo": ("Turismo", {
        "es": r"\bturismo\b", "ca": r"\bturisme\b|empreses turistiques", "gl": r"\bturismo\b", "eu": r"turismo\w*",
        "en": r"tourism"}),
    "deporte": ("Ciencias de la actividad física y del deporte", {
        "es": r"actividad fisica y (del )?deporte|\bcafyd\b|\binef\b", "ca": r"activitat fisica i (de l')?esport",
        "gl": r"actividade fisica e (do )?deporte", "eu": r"jarduera fisiko\w*", "en": r"sports? science"}),
    # genéricas: solo si la ficha lo dice
    "cualquier_ingenieria": ("Cualquier ingeniería", {
        "es": r"cualquier ingenieria|ingenieria (superior |tecnica )?(en |de )?cualquier (rama|especialidad)|ingenierias? en general",
        "ca": r"qualsevol enginyeria|enginyeria \(qualsevol especialitat\)",
        "gl": r"calquera enxe\w*ria",
        "eu": r"edozein ingeniaritza",
        "en": r"any engineering"}),
    "cualquier_universitaria": ("Cualquier titulación universitaria", {
        "es": r"cualquier (titulacion|grado|licenciatura|carrera)(?! equivalente)|(?<!ingenieria \()(?<!ingenieria en )(?<!ingenieria de )cualquier (rama|especialidad|area|disciplina)|"
              r"titulacion universitaria de cualquier",  # «otros estudios universitarios» no dice «cualquiera»
        "ca": r"qualsevol (titulacio|grau|llicenciatura|ambit|branca)",
        "gl": r"calquera (titulacion|grao)",
        "eu": r"edozein (titulazio|gradu)\w*",
        "en": r"any (degree|discipline|field)"}),
    "stem": ("Titulación científica o técnica (STEM)", {
        "es": r"\bstem\b|titulacion(es)? (cientific\w*|tecnic\w*)( o tecnic\w*)?|cientifico[- ]tecnic\w*|carreras? tecnic\w*",
        "ca": r"\bstem\b|cientificotecnic\w*|cientific[oa]-tecnic\w*",
        "gl": r"\bstem\b",
        "eu": r"\bstem\b",
        "en": r"\bstem\b|scientific[- ]technical"}),
}

# --------------------------------------------------------------------------------- familias de FP
# clave: (nombre, {idioma: nombre de la familia}, ciclos LOE y LOGSE de sondeo/titulaciones/fp.csv
# y ramas de la FP antigua). Solo se buscan dentro de una alternativa de FP.
_FP = {
    "fp-actividades-fisicas": ("Actividades Físicas y Deportivas", {
        "es": r"actividades fisicas y deportivas", "ca": r"activitats fisiques i esportives",
        "gl": r"actividades fisicas e deportivas", "eu": r"jarduera fisiko eta kirol\w*"},
        "acondicionamiento fisico|actividades ecuestres|animacion de actividades fisicas y deportivas|conduccion de actividades fisico-deportivas"
        "|ensenanza y animacion sociodeportiva|guia en el medio natural y de tiempo libre|rama deportiva"),
    "fp-administracion": ("Administración y Gestión", {
        "es": r"administracion y gestion|\badministracion\b(?! y direccion)|\badministrativ\w*", "ca": r"administracio i gestio|\badministrati\w*|administracio",
        "gl": r"administracion e xestion", "eu": r"administrazio eta kudeaketa\w*", "en": r"\badministrati\w*"},
        "administracion y finanzas|asistencia a la direccion|gestion administrativa|secretariado|rama administrativa"),
    "fp-agraria": ("Agraria", {
        "es": r"\bagrari[ao]\b|actividades agrarias", "ca": r"\bagrari[ae]\b", "gl": r"\bagraria\b", "eu": r"nekazaritza\w*",
        "en": r"agricultur\w*|animal care"},
        "aprovechamiento y conservacion del medio natural|ganaderia y asistencia en sanidad animal|gestion forestal y del medio natural"
        "|jardineria|paisajismo y medio rural|produccion agroecologica|produccion agropecuaria|explotaciones agrarias|explotaciones agricolas"
        "|explotaciones ganaderas|empresas agropecuarias|recursos naturales y paisajisticos|trabajos forestales|rama agraria"),
    "fp-artes-graficas": ("Artes Gráficas", {
        "es": r"artes graficas", "ca": r"arts grafiques", "gl": r"artes graficas", "eu": r"arte grafiko\w*"},
        "publicaciones impresas y multimedia|produccion grafica|produccion editorial|encuadernacion|impresion grafica|postimpresion|preimpresion"),
    "fp-artes-artesanias": ("Artes y Artesanías", {
        "es": r"artes y artesanias", "ca": r"arts i artesanies", "gl": r"artes e artesania", "eu": r"arte eta artisautza\w*"},
        "artista fallero"),
    "fp-comercio": ("Comercio y Marketing", {
        "es": r"comercio y marketing", "ca": r"comerc i marqueting", "gl": r"comercio e marketing", "eu": r"merkataritza eta marketin\w*"},
        "actividades comerciales|comercializacion de productos alimentarios|comercio internacional|gestion comercial y marketing"
        "|gestion de ventas y espacios comerciales|gestion del transporte|marketing y publicidad|servicios al consumidor|transporte y logistica"),
    "fp-edificacion": ("Edificación y Obra Civil", {
        "es": r"edificacion (y|o) obra civil|delinea\w*", "ca": r"edificacio (i|o) obra civil|delinea\w*", "gl": r"edificacion e obra civil",
        "eu": r"eraikuntza eta obra zibil\w*"},
        "acabados de construccion|\bconstruccion\b|proyectos urbanisticos y operaciones topograficas|proyectos de construccion"
        "|obras de albanileria|obras de hormigon|obras de interior|maquinaria de construccion|organizacion y control de obras"
        "|proyectos de edificacion|proyectos de obra civil|realizacion y planes de obra|rama (de la )?(edificacion|construccion)"),
    "fp-electricidad": ("Electricidad y Electrónica", {
        "es": r"electricidad y electronica|\belectricidad\b|\belectronica\b", "ca": r"electricitat i electronica|\belectricitat\b",
        "gl": r"electricidade e electronica", "eu": r"elektrizitatea eta elektronika\w*", "en": r"electricity|electronics"},
        "automatizacion y robotica industrial|productos electronicos|electromedicina|instalaciones electrotecnicas|equipos electronicos"
        "|instalaciones de telecomunicaciones|instalaciones electricas|mantenimiento electronico|regulacion y control automaticos"
        "|telecomunicaci\\w* e informaticos|sistemas electrotecnicos|electrotecni\\w*"),
    "fp-energia-agua": ("Energía y Agua", {
        "es": r"energia y agua", "ca": r"energia i aigua", "gl": r"enerxia e auga", "eu": r"energia eta ur\w*"},
        "centrales electricas|eficiencia energetica|energias renovables|gestion del agua|tratamiento de aguas"),
    "fp-fabricacion-mecanica": ("Fabricación Mecánica", {
        "es": r"fabricacion mecanica|\bmetal\b", "ca": r"fabricacio mecanica", "gl": r"fabricacion mecanica",
        "eu": r"fabrikazio mekaniko\w*"},
        "moldeo de metales|construcciones metalicas|proyectos mecanicos|fundicion|joyeria|mecanizado|optica de anteojeria"
        "|pulvimetalurgia|soldadura|caldereria|tratamientos superficiales"),
    "fp-hosteleria": ("Hostelería y Turismo", {
        "es": r"hosteleria y turismo|hosteleria|\bturismo\b|gestion hotelera", "ca": r"hoteleria i turisme|hoteleria|\bturisme\b|gestio hotelera", "gl": r"hostalaria e turismo",
        "eu": r"ostalaritza eta turismo\w*"},
        "agencias de viajes|alojamiento|animacion turistica|\bcocina\b|direccion de servicios en restauracion|alojamientos turisticos"
        "|asistencia turisticas|comercializacion turisticas|pasteleria|servicios de restaurante|servicios en restauracion|\brestauracion\b"),
    "fp-imagen-personal": ("Imagen Personal", {
        "es": r"imagen personal", "ca": r"imatge personal", "gl": r"imaxe persoal", "eu": r"irudi pertsonal\w*"},
        "asesoria de imagen|caracterizacion|estetica|estilismo|peluqueria|cosmetica capilar|termalismo"),
    "fp-imagen-sonido": ("Imagen y Sonido", {
        "es": r"imagen y sonido", "ca": r"imatge i so", "gl": r"imaxe e son", "eu": r"irudia eta soinua"},
        "animaciones 3d|tratamiento de imagen|produccion de audiovisuales|proyectos de audiovisuales|sonido para audiovisuales|disc-jockey"),
    "fp-alimentarias": ("Industrias Alimentarias", {
        "es": r"industrias alimentarias", "ca": r"industries alimentaries", "gl": r"industrias alimentarias",
        "eu": r"elikagaien industri\w*"},
        "aceites de oliva y vinos|conserveria|aceites y jugos|productos alimenticios|productos lacteos|elaboracion de vinos"
        "|industria alimentaria|matadero|molineria|panaderia|panificacion|vitivinicultura"),
    "fp-extractivas": ("Industrias Extractivas", {
        "es": r"industrias extractivas", "ca": r"industries extractives", "gl": r"industrias extractivas",
        "eu": r"erauzketa industri\w*"},
        "excavaciones y sondeos|piedra natural"),
    "fp-informatica": ("Informática y Comunicaciones", {
        "es": r"informatica y comunicaciones|\binformatic\w*", "ca": r"informatica i comunicacions|\binformatic\w*",
        "gl": r"informatica e comunicacions|\binformatic\w*", "eu": r"informatika eta komunikazio\w*", "en": r"\bcomputing|\bit\b"},
        "sistemas informaticos|sistemas y redes|inteligencia artificial y big data|aplicaciones informaticas|aplicaciones multiplataforma|aplicaciones web|microinformaticos|\\basir\\b|\\bdaw\\b|\\bdam\\b|\\bsmr\\b"),
    "fp-instalacion-mantenimiento": ("Instalación y Mantenimiento", {
        "es": r"instalacion y mantenimiento|(?<!transporte y )\bmantenimiento\b(?! de vehiculos)", "ca": r"installacio i manteniment|\bmanteniment\b",
        "gl": r"instalacion e mantemento", "eu": r"instalazio eta mantentze\w*", "en": r"maintenance"},
        "instalaciones termicas y de fluidos|produccion de calor|frigorificas|climatizacion|mantenimiento electromecanico|mecatronica"
        "|instalaciones de fluidos|electromecanico de maquinaria|equipo industrial|mantenimiento ferroviario|instalaciones de edificio"
        "|frio,? climatizacion"),
    "fp-madera": ("Madera, Mueble y Corcho", {
        "es": r"madera,? mueble y corcho|madera y mueble", "ca": r"fusta,? moble i suro", "gl": r"madeira,? moble e cortiza",
        "eu": r"zura,? altzariak eta kortxo\w*"},
        "carpinteria|amueblamiento|transformacion de la madera|madera y corcho"),
    "fp-maritimo-pesquera": ("Marítimo-Pesquera", {
        "es": r"maritimo[- ]pesquer\w*", "ca": r"maritimopesquer\w*|maritimo[- ]pesquer\w*", "gl": r"maritimo[- ]pesqueir\w*",
        "eu": r"itsas[- ]arrantza\w*"},
        "acuicola|acuicultura|maquinaria de buques|navegacion|pesca|operaciones subacuaticas|buceo|transporte maritimo|instalaciones del buque"),
    "fp-quimica": ("Química", {
        "es": r"\bquimica\b", "ca": r"\bquimica\b", "gl": r"\bquimica\b", "eu": r"\bkimika\b", "en": r"chemistry|\blaboratory\b|\blab technician"},
        "analisis y control|productos farmaceuticos|pasta y papel|proceso quimico|\\blaboratorio\\b(?! (de diagnostico )?clinico)|planta quimica|plasticos y caucho"
        "|quimica ambiental|quimica industrial"),  # «laboratorio (de diagnóstico) clínico» es Sanidad
    "fp-sanidad": ("Sanidad", {
        "es": r"\bsanidad\b|rama sanitaria|\b(bio)?sanitari[oa]\b", "ca": r"\bsanitat\b", "gl": r"\bsanidade\b", "eu": r"\bosasun\w*",
        "en": r"health"},
        "anatomia patologica|audiologia|audioprotesis|cuidados auxiliares de enfermeria|\\btcae\\b|dietetica|documentacion sanitaria"
        "|administracion sanitarias|emergencias sanitarias|farmacia|higiene bucodental|imagen para el diagnostico|laboratorio clinico"
        "|laboratorio de diagnostico clinico|ortoprotesi\\w*|protesis dentales|radioterapia|salud ambiental"),
    "fp-seguridad-ambiente": ("Seguridad y Medio Ambiente", {
        "es": r"seguridad y medio ?ambiente", "ca": r"seguretat i medi ambient", "gl": r"seguridade e medio ambiente",
        "eu": r"segurtasuna eta ingurumen\w*"},
        "emergencias y proteccion civil|educacion y control ambiental|quimica y salud ambiental"),
    "fp-sociocultural": ("Servicios Socioculturales y a la Comunidad", {
        "es": r"servicios socioculturales y a la comunidad|servicios socioculturales", "ca": r"serveis socioculturals i a la comunitat",
        "gl": r"servizos socioculturais e a comunidade", "eu": r"gizarte eta kultur zerbitzu\w*"},
        "animacion sociocultural|situacion de dependencia|atencion sociosanitaria|educacion infantil|movilidad segura|integracion social"
        "|lengua de signos|mediacion comunicativa|igualdad de genero"),
    "fp-textil": ("Textil, Confección y Piel", {
        "es": r"textil,? confeccion y piel", "ca": r"textil,? confeccio i pell", "gl": r"textil,? confeccion e pel",
        "eu": r"ehungintza\w*"},
        "calzado|confeccion|curtidos|textil|ennoblecimiento|patronaje|hilatura|tejeduria|tejidos de punto|vestuario a medida"),
    "fp-vehiculos": ("Transporte y Mantenimiento de Vehículos", {
        "es": r"transporte y mantenimiento de vehiculos|mantenimiento de vehiculos", "ca": r"transport i manteniment de vehicles",
        "gl": r"transporte e mantemento de vehiculos", "eu": r"garraioa eta ibilgailu\w*"},
        "automocion|carroceria|vehiculos de transporte por carretera|electromecanica de maquinaria|electromecanica de vehiculos"
        "|mantenimiento aeromecanico|avionica|embarcaciones de recreo|material rodante ferroviario|sistemas aeronauticos|aeronaves"),
    "fp-vidrio-ceramica": ("Vidrio y Cerámica", {
        "es": r"vidrio y ceramica", "ca": r"vidre i ceramica", "gl": r"vidro e ceramica", "eu": r"beira eta zeramika\w*"},
        "productos ceramicos|productos de vidrio|vidrio y transformados"),
}
FP_FAMILIAS = {key: (name, langs) for key, (name, langs, _) in _FP.items()}
NOMBRES = {**{key: name for key, (name, _) in TITULACIONES.items()}, **{key: name for key, (name, _) in FP_FAMILIAS.items()}}


def _join(*parts: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in parts if p))


UNI_RX = {key: _join(*langs.values()) for key, (_, langs) in TITULACIONES.items()}
FP_RX = {key: _join(*langs.values(), ciclos) for key, (_, langs, ciclos) in _FP.items()}

# ------------------------------------------------------------------------------- tipos de título
# (tipo, expresión) en orden; cada una se come su texto. None: no es un título. Con «*»: expresión
# genérica, que es un rótulo si le sigue el título concreto («titulación universitaria de Grado»).
# «ing_arq»: «Ingeniería» o «Arquitectura», título o especialidad según dónde esté (ver `lee`).
_U = r"(?: universitari\w+)?(?: oficial\w*)?"
FRASES = [
    (None, r"programas? (oficial(es)? )?de doctorado|estudios de doctorado|tesis doctoral|doctoral (studies|programme|program|thesis|candidate|student)s?"
           r"( \(phd\))?|(pre|post|pos)-?doc\w*|doctorand\w*|phd (student|candidate|position|programme|program|studies|call)s?|"
           r"pursue (a )?(phd|doctorate)|doctorat en curs"),
    (None, r"tecnic\w* (de )?(nivel )?superior (en|de) (prevencion|riesgos)( de)? riesgos (laborales|profesionales)[^.;\n]*|"
           r"higher technician in occupational[^.;\n]*"),
    ("doctorado", r"(grado|titulo|titulacion|titol) de doctor\w*|\bdoctor\w*|\bph\.? ?d\b\.?( degree)?|doctorat\w*|doutor\w*|doktore\w*"),
    (None, r"\bgrados? de (discapacidad|minusvalia|experiencia|autonomia|responsabilidad|dependencia|parentesco|consanguinidad|"
           r"afinidad|cumplimiento|conocimiento)\w*"),
    ("titulo_medio", r"titulad\w* (de )?grado medio|titulad\w* medio\w*"),
    ("titulo_superior*", r"titulad\w* (de )?grado superior|titulad\w* superior\w*( universitari\w*)?|titulacion(es)? superior(es)?|"
                         r"titulacio superior|tecnic\w* titulad\w* superior"),
    ("eso", r"(graduad\w* (en )?)?graduadoeso|graduad\w* (en )?(educacion secundaria( obligatoria)?|escolar)|"
            r"graduat (en educacio secundaria|escolar)|educacion secundaria obligatoria|educacio secundaria obligatoria|"
            r"educacion secundaria|ensino secundario obrigatorio|\begb\b|derrigorrezko bigarren hezkuntza|\bdbh\b"),
    ("fp_basica", r"\bfpgb\b|\bfp ?basica|formacion profesional basica|formacio professional basica|ciclos? formativos? (de )?grado basico|grado basico"),
    ("titulo_medio", r"(?:(?:ingenier\w*|enginyer\w*|enxe\w*|arquitect\w*) tecnic\w*|aparejador\w*|aparellador\w*|diplomatura|"
                     r"diplomad\w*|diplomat\w*)" + _U),
    (None, r"(con )?menos de \d+ ects|\(\s*\d+ ects( o mas)?\s*\)|\d+ ects( o mas)?"),
    ("fp_superior", r"ciclos? formativos? (de )?grado superior|cicles? formatius? (de )?grau superior|ciclos? (formativos? )?(de )?grao superior|"
                    r"\bcfgs\b|\bf\.?p\.? ?(ii|2)\b|\bfpii\b|formacion profesional (de )?(grado superior|segundo grado|ii\b|2\b)|"
                    r"formacio professional (de )?grau superior|\bfp (de )?grado superior|grado superior|grau superior|grao superior|"
                    r"ciclo superior|cicle superior|tecnic\w* superior en|tecnic\w* superior\b|tecnic\w* especialista|"
                    r"modulo (profesional )?(de )?nivel (iii|3)\b|"
                    r"higher (vocational|national)\w*( education)?( and)?( training)?( qualifications?)?|advanced vocational\w*|"
                    r"goi[- ]mailako heziketa zikl\w*"),
    ("fp_medio", r"ciclos? formativos? (de )?grado medio|cicles? formatius? (de )?grau (mitja|mig)|\bcfgm\b|\bf\.?p\.? ?(i|1)\b(?!i)|\bfpi\b|"
                 r"formacion profesional (de )?(al menos |como minimo )?(grado medio|primer grado)|formacio professional (de )?grau (mitja|mig)|"
                 r"grado medio|grau (mitja|mig)|grao medio|ciclo medio|cicle mitja|tecnic\w* auxiliar|"
                 r"tecnic\w* en (?!el |la |los |las |un |una |su |sus |materia )|modulo (profesional )?(de )?nivel (ii|2)\b|"
                 r"intermediate vocational\w*( training)?( certificate)?|erdi[- ]mailako heziketa zikl\w*"),
    ("fp", r"formacion profesional|formacio professional|\bfp\b|ciclos? formativos?|cicles? formatius?|"
           r"vocational (training|education|qualification)\w*|tecnic\w* (de )?rama|lanbide heziketa\w*"),
    ("bachillerato", r"bachiller\w*|batxiller\w*|bacharel\w*|batxilergo\w*|\bbup\b|\bcou\b"),
    ("master", r"(?:\bmaster\w*|\bmsc\b|\bm\.sc\b|\bmba\b)(?:'s)?(?: degree)?" + _U + r"(?: habilitante)?"),
    ("universitaria*", r"titulaci\w* universitari\w*( oficial\w*)?|titulo universitario( oficial)?|titol universitari|titulad\w* universitari\w*|"
                       r"formacion universitaria|formacio universitaria|estudios universitarios|estudis universitaris|"
                       r"(university|college) (degree|qualification|studies|education)"),
    ("grado", r"(?:\bgrados?\b|\bgraduad\w*|\bgrau\b|\bgraduat\w*|\bgrao\b|bachelor\w*(?:'?s)?|undergraduate|\bdegrees?\b|\bb\.?sc\b|"
              r"graduatu\w*|\bgradu(?:a|ko)\b)" + _U),
    ("titulo_superior", r"(?:licenciatura|licenciad\w*|llicenciat\w*|lizentziatur\w*)" + _U + r"|(?:ingenier\w*|arquitect\w*) superior(?:es)?\b"),
    ("ing_arq", r"ingenier\w*|enginyer\w*|enxe\w*ari\w*|ingeniari\w*|engineer\w*|"
                r"\barquitect(?:ura|o|os|a|as|e|es)\b(?! (?:de|del) (?:software|sistemas|soluciones|datos|computadores|red|redes))"),
]
FRASES_RX = [(tipo, re.compile(rx)) for tipo, rx in FRASES]
MECES = re.compile(
    r"(?:nivel(?:es)?\W{0,3})?(?:[1-4]\W{0,3}(?:(?:o|y)\W{0,3}[1-4]\W{0,3})?)?meces(?:\W{0,4}(?:nivel\W{0,3})?[1-4](?:\W{0,3}(?:o|y)\W{0,3}[1-4])?)?"
    r"(?:\W{0,3}o\W{0,3}[1-4]\W{0,3}meces)?|"
    r"nivel\W{0,3}[1-4]\W{0,3}(?:\([^)]{0,30}\)\W{0,3})?(?:segun |del |de )?(?:el )?marco espanol de cualificaciones")
SIN_EXIGIR = re.compile(r"titulacion no exigida|no se (exige|requiere|necesita|pide) (ninguna )?titulacion(?! especifica)|sin titulacion|"
                        r"sense titulacio|no es necesaria (ninguna )?titulacion|no (formal )?(degree|qualification)s? (is )?required")
# coletillas que no dicen nada de la titulación exigida
COLETILLA = re.compile(
    r"\(?\s*(?:titulacion(?:es)?\s+)?homologad\w*\s+en\s+espana(?:(?:\s+o)?(?:\s+con)?\s+certificado\s+de\s+equivalencia"
    r"(?:\s+emitido\s+por\s+la\s+secretaria(?:\s+general)?\s+de\s+universidades)?)?\s*\)?|"
    r"\(?\s*(?:\bo\s+)?(?:con\s+)?certificado\s+de\s+equivalencia\s+emitido\s+por\s+la\s+secretaria(?:\s+general)?\s+de\s+universidades\s*\)?|"
    r"\(\s*se comprobara en valoracion tecnica\s*\)|\(\s*plan bolonia\s*\)|\(\s*master habilitante\s*\)")
# arranque de la frase y fórmulas de habilitación: no son ni título ni especialidad
RUIDO = re.compile(
    r"\b(?:estar en posesion de|disponer de|poseer|posees?)\b(?:\s+(?:alguna de las siguientes|una de las siguientes|la|una|el)\b)?"
    r"(?:\s+titulaci\w+\b(?!\s+(?:universitari|superior))(?:\s+oficial\w*)?)?(?:\s+(?:de|en)\b)?|"
    r"\b(?:la\s+)?titulaci\w+(?:\s+oficial\w*)?\s+(?:de|en)\b|^\W*titulaci\w+\b(?!\s+(?:universitari|superior))(?:\s+oficial\w*)?\W|\ben titulaciones del?\b|"
    r"\bque (?:habilit\w+|d[ae]n? acceso) (?:para |a )(?:el ejercicio de )?la profesion(?: regulada)?(?: de)?\b")
EXPERIENCIA = re.compile(r"\b(?:o bien|o|u)\s+(?:(?!(?:o|u|con|y|e|mas)\b)[^\s.;,()]+\s+){0,6}?(?:experiencia|conocimientos|experience)\b")
SUMA = re.compile(r"(?:\+|\b(?:y|e|i|con|mas|and|plus)\b)\s*(?:un |una |el |an? )?$")
_CONECTOR = r"\s|[,/():\-–]|\b(?:o|u|superior(?:es)?|oficial(?:es)?)\b"
PURO = re.compile(rf"(?:{_CONECTOR})*")  # entre dos títulos de una enumeración
PURO_INICIO = re.compile(rf"(?:{_CONECTOR}|\b(?:de|del)\b)*")  # al empezar la frase o tras un rótulo
PURO_ROTULO = re.compile(rf"(?:{_CONECTOR}|\b(?:de|del|en)\b)*")  # tras un rótulo genérico («Titulación universitaria en Ingeniería …»)
ROTULO = re.compile(r"(?:\s|[():\-–]|\b(?:de|del|en|la|las|el|los|oficial(?:es)?)\b)*")
ALARMA = re.compile(r"experiencia|experience|conocimientos|tarjetas?\b|\bcarne\b|certificad\w*|\bcursos?\b|\banos\b|\bmeses\b|valora\w*|"
                    r"preferent\w*|preferib\w*|deseable\w*|titulaci\w+|\btitulos?\b|equivalent\w*|acredit\w*|que incluya\w*|plan de estudios|"
                    r"\bcon (?:la |una )?especialidad|\bminim[oa]s?\b|\bafin\w*|\bsimilar\w*|\banalog\w*")
NEGACION = re.compile(r"\bno (?:estar|haber|poseer|tener|disponer|hallarse)\b|\bnot (?:hold|have|be)\b")
PROFESION = re.compile(r"titulaci\w+ que (?:habilit\w+|d[ae]n? acceso)")  # nombra la profesión, no los títulos
ESPECIALIDAD_DE = re.compile(r"\s*(?:en|de)\s+")
TECNICA = re.compile(r"ingenier|enginyer|enxe|arquitect")
SIN_ESPECIALIDAD = re.compile(r"licenci|llicenci|diplom|ingenier|enginyer|enxe")
ING_CUALQUIERA = re.compile(r"[\s(]*(?:(?:en|de|d'|da) )?(?:cualquier|qualsevol|calquera) (?:rama|especialidad|branca|especialitat|especialidade)\b")
MECES3_SIN_MASTER = re.compile(r"veterinari|farmaci|medicina|odontolog|arquitectura")  # grados que son MECES 3
# palabras que no nombran una especialidad (para `sin_clave`)
VACIAS = set("""de del la el los las lo en a al y e i con para por que su sus un una como segun al menos mas
    ingenieria ingenierias ingeniero ingeniera ingenieros ing ciencia ciencias grado grados master licenciatura titulacion titulaciones
    oficial oficiales universitario universitaria universitarios universitarias superior superiores tecnica tecnico tecnicas tecnicos
    especialidad especialidades especializaciones rama ramas campo campos estudio estudios ambito ambitos area areas familia familias
    profesional profesionales alguna algunas siguientes relacionado relacionada relacionados funciones puesto habilite habiliten
    habilitante profesion regulada nivel ruct incluida incluidas incluya plan planes materia requiera itinerario afin afines similar
    similares otras otros""".split())
# y, además, las que pueden ir delante del nombre de una especialidad sin ser otra (`_cabeza`)
DELANTE = VACIAS | set("""doble dobles titulo titulos carrera carreras disciplina disciplinas masteres tecnologia tecnologias
    sistemas gestion direccion les els da do das dos in of the or an field fields related science sciences engineering enginyeria
    ciencies enxenaria grau llicenciatura cc investigacion intervencion terapia terapias tratamiento tratamientos evaluacion
    atencion cuidados analisis""".split())
PARTE = re.compile(r"[,;/\n:().«»\"“”]|\s[-–]\s|\b(?:o|u)\b")
CORTE = re.compile(rf"(?:{ALARMA.pattern}|\bque\b)[^().;\n]*")  # una condición, hasta el fin de su frase: no nombra especialidades
PIEZA = re.compile(PARTE.pattern + r"|\b(?:y|e|i|and)\b|[+&]")  # nombres de una lista

GENDER = re.compile(r"(?<=\w)\s?/\s?(?:a|as|o|os|ora|oras|ra|na|es)\b")
ESO_LITERAL = re.compile(r"\bE\.?\s?S\.?\s?O\b\.?")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes ni «/a»; conserva líneas, cifras y signos («MECES 3», «Grado+Máster»)."""
    text = ESO_LITERAL.sub(" graduadoeso ", text)  # «ESO» en mayúsculas; «eso» en minúsculas es otra cosa
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("l·l", "ll").replace("’", "'").replace("´", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\b(y|i|e)/(o|ou)\b|\band/or\b", " o ", text)  # «y/o» antes de quitar «/o»
    text = GENDER.sub("", text)
    return re.sub(r"[ \t ]+", " ", text).strip()


def _blank(rx: re.Pattern, text: str) -> str:
    return rx.sub(lambda m: " " * len(m.group()), text)


def _tokens(body: str) -> tuple[list[tuple[int, int, str, tuple[int, ...], str]], str]:
    """(inicio, fin, tipo, niveles MECES, primera palabra) de cada título, marca de MECES o candidato
    «ing_arq», y el texto con todo eso en blanco menos los «ing_arq»."""
    tokens = []
    for match in MECES.finditer(body):
        levels = tuple(sorted({int(n) for n in re.findall(r"[1-4]", match.group())}))
        if levels:
            tokens.append((match.start(), match.end(), "meces", levels, ""))
    body = _blank(MECES, body)
    for tipo, rx in FRASES_RX:
        if tipo:
            tokens += [(m.start(), m.end(), tipo, (), m.group().split()[0]) for m in rx.finditer(body)]
        if tipo != "ing_arq":
            body = _blank(rx, body)
    return sorted(tokens), body


def _sumandos(vias: list[dict], text: str) -> tuple[list[dict], bool]:
    """Vías a las que se suma un «+ Máster»: la anterior y, hacia atrás, las de primer ciclo que la
    preceden seguidas («Diplomatura/Grado + Máster»). «Grado o Grado + Máster»: el primero va solo.
    Si entre dos títulos de primer ciclo hay especialidades y no una barra («Diplomatura en X o Grado +
    Máster»), no se sabe si el máster va con los dos: se ata solo a los seguidos y se avisa (segundo valor)."""
    bound = [vias[-1]]
    for earlier in reversed(vias[:-1]):
        later = bound[-1]
        between = text[earlier["fin"]:later["ini"]]
        if (len(earlier["tipos"]) > 1 or earlier["tipos"][0] not in PRIMER_CICLO or later["tipos"][0] not in PRIMER_CICLO
                or ";" in between or "\n" in between):
            break
        if "/" not in between and any(earlier["palabra"] == b["palabra"] for b in bound):
            break
        if "/" not in between and not PURO.fullmatch(between):
            return bound, True
        bound.append(earlier)
    return bound, False


def _cabeza(text: str, pos: int) -> bool:
    """La coincidencia nombra la especialidad: empieza el nombre (delante, en su trozo de la lista, solo
    hay palabras genéricas: «Ingeniería de …») o es su complemento con «de» o «en» («Cuidados de
    Enfermería», «Redes de Telecomunicación»). No la nombra si es adjetivo de otro nombre («Química
    Industrial», «Física Médica»), si va tras otra preposición («Bioinformática para las Ciencias de la
    Salud») o si es media palabra («bioestadística»)."""
    if pos and text[pos - 1].isalnum():
        return False
    words = re.findall(r"[a-z']+", PIEZA.split(text[:pos])[-1])
    if all(w in DELANTE for w in words):
        return True
    while words and words[-1] in DELANTE and words[-1] not in PREPOSICIONES:  # «… en Ingeniería Industrial»
        words.pop()
    return not words or words[-1] in COMPLEMENTO


COMPLEMENTO = {"de", "del", "en", "do", "da", "dos", "das", "in", "of"}  # «Cuidados de Enfermería»
PREPOSICIONES = COMPLEMENTO | {"para", "por", "a", "al", "con", "segun", "como", "sin", "sobre", "entre", "per", "amb", "for", "with",
                               "to", "on"}


def _sin_clave(text: str, spans: list[tuple[int, int]]) -> list[str]:
    """Nombres de la lista en los que no se ha reconocido ninguna clave (los que tienen alguna no
    dejan restos: «Historia del Arte y Patrimonio», «Fundamentos de la Arquitectura»)."""
    out, start = [], 0
    for sep in [*PARTE.finditer(text), None]:
        end = sep.start() if sep else len(text)
        if not any(a < end and b > start for a, b in spans):
            words = re.findall(r"[a-z']+", text[start:end])
            while words and words[0] in VACIAS:
                words.pop(0)
            while words and words[-1] in VACIAS:
                words.pop()
            if any(len(w) >= 4 and w not in VACIAS for w in words):
                out.append(" ".join(words))
        start = sep.end() if sep else end
    return out


def lee(texto: str) -> Requisito:
    """Lectura de una frase de titulación exigida (la fuente ya la ha separado de lo valorable)."""
    norm = normalize(texto)
    if SIN_EXIGIR.search(norm):
        return Requisito(NO_EXIGIDA, exigido=texto)
    exp = EXPERIENCIA.search(norm)
    body, tail = (norm[:exp.start()], norm[exp.start():]) if exp else (norm, "")
    source = _blank(RUIDO, _blank(COLETILLA, body))
    tokens, text = _tokens(source)
    parcial: list[str] = []
    if NEGACION.search(norm):
        parcial.append("requisito negativo")
    if PROFESION.search(norm):
        parcial.append("titulación que habilita para una profesión: vías sin desglosar")
    vias: list[dict] = []  # tipos, meces, palabra, ini, fin, k (su título en `titles`)
    titles: list[tuple[int, int, str]] = []  # títulos aceptados: el texto que sigue a cada uno son sus especialidades
    group, pending = 0, ()  # primera vía a la que se refiere la próxima marca de MECES; marca que va delante
    prev_end, at_start, doubtful = 0, True, False
    after_label = False  # lo anterior es un rótulo genérico («titulación universitaria»)
    for i, (start, end, tipo, levels, word) in enumerate(tokens):
        gap = text[prev_end:start]
        if tipo == "meces":
            if len(vias) > group:
                if len(levels) == 1 or len(vias) - group == 1:  # «2 o 3» para varias vías no dice cuál es cuál
                    for via in vias[group:]:
                        via["meces"] = levels
                group, pending = len(vias), ()
            else:
                pending = levels
            prev_end, at_start, after_label = end, True, False
            continue
        if tipo.endswith("*"):
            following = [t for t in tokens[i + 1:] if t[2] != "meces"]
            if following and ROTULO.fullmatch(text[end:following[0][0]]):  # rótulo del título que sigue
                prev_end, at_start, after_label = end, True, True
                continue
            tipo = tipo[:-1]
        if tipo == "titulo_medio" and TECNICA.match(word) and titles and titles[-1][2] in ("grado", "master") \
                and not at_start and ESPECIALIDAD_DE.fullmatch(gap):
            text = text[:start] + source[start:end] + text[end:]  # se queda en el texto, como especialidad
            continue
        if tipo == "ing_arq":
            if "\n" in gap:  # primera del renglón: título si el renglón trae otro, o si aún no hay ninguno
                first = start - len(gap) + gap.rindex("\n") + 1
                last = text.find("\n", end) if "\n" in text[end:] else len(text)
                others = any(first <= s < last and t not in ("ing_arq", "meces") for s, _, t, _, _ in tokens)
                is_title = bool(PURO_INICIO.fullmatch(text[first:start])) and (others or not vias)
            elif ";" in gap:
                is_title = bool(PURO_INICIO.fullmatch(gap.rsplit(";", 1)[1]))
            else:
                is_title = bool((PURO_ROTULO if after_label else PURO_INICIO if at_start else PURO).fullmatch(gap))
            if not is_title:
                doubtful = doubtful or bool(re.search(r"\b[ou]\s*$", gap))
                continue  # especialidad: se queda en el texto
            tipo = "titulo_superior"
        titles.append((start, end, tipo))
        summed = bool(SUMA.search(gap)) and len(vias) > group
        prev_end, at_start, after_label = end, False, False
        if summed and tipo == "master":
            bound, doubtful_sum = _sumandos(vias[group:], text)
            for via in bound:
                via["tipos"].append("master")
            if doubtful_sum:
                parcial.append("«+ Máster»: no se sabe a qué títulos se suma")
            continue
        if summed:
            parcial.append("suma sin leer")
        vias.append({"tipos": [tipo], "meces": (), "palabra": word, "ini": start, "fin": end, "k": len(titles) - 1})
    for via in vias[group:] if pending and (len(pending) == 1 or len(vias) - group == 1) else ():
        via["meces"] = pending

    def segment(k: int) -> str:
        return text[titles[k][1]:titles[k + 1][0] if k + 1 < len(titles) else len(text)]

    for via in vias:  # el MECES escrito tiene que casar con lo leído
        tipos, levels = via["tipos"], via["meces"]
        high = "master" in tipos or tipos[0] in ("titulo_superior", "doctorado")
        if levels and high and max(levels) < 3:
            parcial.append("MECES 2 en una vía de máster o licenciatura")
        if levels and not high and tipos[0] in ("grado", "titulo_medio") and min(levels) >= 3 \
                and not MECES3_SIN_MASTER.search(segment(via["k"])):
            parcial.append("MECES 3 en una vía sin máster")
    if doubtful and any("master" in via["tipos"] for via in vias) and not any(via["tipos"] == ["titulo_superior"] for via in vias):
        parcial.append("«Ingeniería» o «Arquitectura» tras «o»: título o especialidad")
    found: list[str] = []
    missing: list[str] = []
    general = any(SIN_ESPECIALIDAD.match(source[start:end]) and PURO.fullmatch(segment(k)) for k, (start, end, _) in enumerate(titles))
    for k, (start, end, tipo) in enumerate(titles):
        vocabulary = UNI_RX if tipo in UNIVERSITARIOS else FP_RX if tipo in DE_FP else {}
        if not general and source[start:end].startswith(("arquitect", "aparej", "aparell")):
            found += [key for key in ("arquitectura_tecnica", "arquitectura") if UNI_RX[key].match(source, start)]
        named = _blank(CORTE, segment(k))
        spans: list[tuple[int, int]] = []
        if source[start:end].startswith(("ingenier", "enginyer", "enxe")) and ING_CUALQUIERA.match(named):
            found.append("cualquier_ingenieria")  # «Ingeniería en cualquier especialidad»: el título se lleva «Ingeniería»
            spans.append(ING_CUALQUIERA.match(named).span())
        for key, rx in vocabulary.items():  # sobre el texto entero, para que las excepciones vean lo que sigue
            hits = [m.span() for m in rx.finditer(named) if not any(a < m.end() and m.start() < b for a, b in spans)
                    and (vocabulary is FP_RX or _cabeza(named, m.start()))]  # (la FP nombra ciclos a medias)
            if hits:
                found.append(key)
                spans += hits
        missing += _sin_clave(named, spans) if vocabulary else []
    for start, end, _ in titles:
        text = text[:start] + " " * (end - start) + text[end:]
    alarms = sorted(set(ALARMA.findall(text)))
    if alarms:
        parcial.append("sin leer: " + ", ".join(alarms))
    if not vias:
        parcial.append("sin título académico reconocido")
    with_level = {tuple(v["tipos"]) for v in vias if v["meces"]}
    out = [Via(tuple(v["tipos"]), v["meces"]) for v in vias if v["meces"] or tuple(v["tipos"]) not in with_level]
    if exp:
        if any(t not in ("meces", "ing_arq") for _, _, t, _, _ in _tokens(tail)[0]):
            parcial.append("títulos tras la experiencia")
        if vias:  # sin título leído delante, no es una alternativa a él («Titulación o conocimientos equivalentes…»)
            out.append(Via(("experiencia",)))
    return Requisito(CONSTA, exigido=texto, vias=tuple(dict.fromkeys(out)), titulaciones=tuple(dict.fromkeys(found)),
                     sin_clave=tuple(dict.fromkeys(missing)), parcial=tuple(dict.fromkeys(parcial)))


# ---------------------------------------------------------------------------- apartados de la ficha
BLOCK = re.compile(r"<(?:br|/p|/li|li|/div|/h\d|/tr|/dd|/dt|/ul|/ol)\b[^>]*>", re.I)
TAGS = re.compile(r"<[^>]+>")


def lines(html_text: str) -> list[str]:
    text = html.unescape(TAGS.sub(" ", BLOCK.sub("\n", html_text or "")))
    return [line for line in (re.sub(r"[ \t ]+", " ", raw).strip() for raw in text.split("\n")) if line]


def apartado(offer: dict, title: str, under: str | None = None) -> str | None:
    """Texto literal del apartado `title` (el que cuelga de `under`, si se indica), o None si no está."""
    parents: dict[int, str] = {}
    for section in offer.get("sections") or []:
        level, name = section.get("level") or 0, (section.get("title") or "").strip()
        parents = {depth: parent for depth, parent in parents.items() if depth < level}
        if name == title and (under is None or under in parents.values()):
            return "\n".join(lines(section.get("html") or ""))
        parents[level] = name
    return None


def de_apartado(offer: dict, title: str, under: str | None = None) -> Requisito:
    """Para las fuentes con un apartado propio de titulación exigida."""
    if not offer.get("sections"):
        return Requisito(NO_CONSTA, "sin_ficha")
    text = apartado(offer, title, under)
    return lee(text) if text else Requisito(NO_CONSTA, "sin_apartado")


# ------------------------------------------------------------------------------------- informe
def describe(via: Via) -> str:
    levels = f" (MECES {' o '.join(map(str, via.meces))})" if via.meces else ""
    return " + ".join(TIPOS[tipo] for tipo in via.tipos) + levels


def ficha(offer: dict, req: Requisito) -> str:
    """Una ficha con su lectura, para revisarla a mano."""
    out = [f"### `{offer['id']}` {offer.get('title') or ''}", offer.get("url") or "", ""]
    out += ["> " + line for line in req.exigido.split("\n")] if req.exigido else [f"({req.estado}: {req.motivo})"]
    out += [""] + [f"- Vía: {describe(via)}" for via in req.vias]
    if req.titulaciones:
        out.append("- Nombra: " + "; ".join(NOMBRES[key] for key in req.titulaciones))
    if req.sin_clave:
        out.append("- Sin clave: " + "; ".join(req.sin_clave))
    if req.parcial:
        out.append("- **Lectura parcial**: " + "; ".join(req.parcial))
    return "\n".join(out) + "\n"


def report(read: list[tuple[dict, Requisito]]) -> str:
    """Resumen por fuente, lecturas parciales y especialidades sin clave."""
    by_source: dict[str, list[tuple[dict, Requisito]]] = {}
    for offer, req in read:
        by_source.setdefault(offer["source"], []).append((offer, req))
    out = ["| Fuente | Fichas | Completas | Parciales | No exigida | No consta |", "|---|---:|---:|---:|---:|---:|"]
    for source, rows in sorted(by_source.items()):
        reasons = Counter(req.motivo for _, req in rows if req.estado == NO_CONSTA)
        consta = [req for _, req in rows if req.estado == CONSTA]
        out.append(f"| {source} | {len(rows)} | {sum(not r.parcial for r in consta)} | {sum(bool(r.parcial) for r in consta)} | "
                   f"{sum(req.estado == NO_EXIGIDA for _, req in rows)} | "
                   f"{', '.join(f'{n} {reason}' for reason, n in reasons.most_common()) or 0} |")
    for source, rows in sorted(by_source.items()):
        partial = [(offer, req) for offer, req in rows if req.parcial]
        if partial:
            out += ["", f"## {source}: lecturas parciales", ""]
            out += [f"- `{offer['id']}` {'; '.join(req.parcial)}: {' / '.join(req.exigido.split(chr(10)))}" for offer, req in partial]
        missing = Counter(item for _, req in rows for item in req.sin_clave)
        if missing:
            out += ["", f"## {source}: especialidades sin clave", ""]
            out += [f"- {n} × {item}" for item, n in missing.most_common()]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    from . import site  # importación tardía: las fuentes importan este módulo
    from .sources import ACTIVE

    if argv[:1] not in (["informe"], ["fichas"]):
        print("Uso: python -m empleo.titulaciones informe|fichas [fuente…]", file=sys.stderr)
        return 2
    readers = {source.id: source for source in ACTIVE}
    offers, _, _ = site.load_all(Path("data"))
    chosen = set(argv[1:]) or {id_ for id_, source in readers.items() if type(source).titulacion is not _base().titulacion}
    read = [(offer, readers[offer["source"]].titulacion(offer)) for _, offer in sorted(offers.items())
            if offer["source"] in chosen and offer["source"] in readers]
    sys.stdout.write(report(read) if argv[0] == "informe" else "\n".join(ficha(offer, req) for offer, req in read))
    return 0


def _base():
    from .sources.base import Source
    return Source


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
