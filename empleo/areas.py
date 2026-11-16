"""Área profesional de cada oferta: clasificación orientativa nuestra, solo para filtrar.

Las fuentes no traen un dato común sobre el tipo de puesto, así que se deduce del título con
reglas deterministas (sin servicios externos). Si el título no basta, se mira el principio de la
ficha y, en último término, el ámbito de la fuente (SOURCE_AREAS). Lo que queda sin área o solo
con el de la fuente se lista en el informe (`python -m empleo.areas informe`), que en Actions
abre o actualiza un issue para revisarlo. En los centros de investigación y las universidades el
área decide además si la oferta sale también en la portada (site.research_only): el informe
lista las decididas con menos seguridad. Los contratos con cargo a un proyecto cuyo título es
«categoría + nombre del proyecto» o «categoría · centro» (PROJECT_TITLES) son siempre de
investigación y salen solo allí: el proyecto o el centro puede añadir la segunda área, no decidir
el puesto.

Reglas sobre el texto normalizado (sin tildes, minúsculas, sin «/a», sin códigos con cifras):
- FRASES, en orden: suman y se «comen» el texto, para que las palabras sueltas no lo vuelvan a
  contar («caminos, canales y puertos» no es transporte; «seguridad y salud» no es sanidad).
- PALABRAS: suman una vez por regla, sin comerse nada.
Peso 3: dice qué se hace; 2: indicio fuerte; 1: titulación o palabra ambigua; {}: solo se come.
Idiomas: es, ca, gl, eu, en (raíces de cada uno en la misma regla).
Los casos revisados están en areas_referencia.csv (fuente, título, áreas esperadas y, si hace
falta, el principio de la ficha). Los tests exigen que todos sigan saliendo igual, y el informe ya
no avisa de ellos: añadir una oferta allí, con su área correcta, es darla por revisada.
"""
from __future__ import annotations

import csv
import html
import re
import sys
import unicodedata
from pathlib import Path

AREAS = {
    "ambiente": "Medio ambiente, agro y pesca",
    "obras": "Construcción, obras y arquitectura",
    "ingenieria": "Ingeniería industrial y energía",
    "aeroespacial": "Aeronáutica, espacio y defensa",
    "tic": "Informática y telecomunicaciones",
    "admin": "Administración y gestión",
    "economia": "Economía, finanzas y estadística",
    "juridico": "Jurídico",
    "personas": "Recursos humanos, formación y PRL",
    "investigacion": "Investigación y laboratorio",
    "sanidad": "Sanidad",
    "transporte": "Transporte, náutica y logística",
    "oficios": "Oficios, operarios y mantenimiento",
    "comunicacion": "Comunicación, audiovisual y cultura",
    "comercial": "Comercial y atención al público",
    "seguridad": "Seguridad y emergencias",
}
ORDER = {key: i for i, key in enumerate(AREAS)}  # desempata en classify; para mostrarlas, BY_NAME
NONE = "ninguna"  # valor del filtro para las ofertas sin área

# Ámbito de las fuentes de un solo sector: desempata y, si el título no dice nada, da el área.
# Los centros de investigación (grupo «investigacion») cuentan como «investigacion».
SOURCE_AREAS = {
    "isdefe": "aeroespacial", "senasa": "aeroespacial", "enaire": "aeroespacial", "aena": "aeroespacial",
    "rtve": "comunicacion", "efe": "comunicacion",
    "enresa": "ingenieria", "enusa": "ingenieria", "hunosa": "ingenieria", "mayasa": "ingenieria",
    "navantia": "ingenieria",
    "puertos": "transporte", "adif": "transporte", "renfe": "transporte", "fgc": "transporte",
    "correos": "transporte",
    "sarga": "ambiente", "cetarsa": "ambiente",
    "ua": "investigacion",  # de momento solo sus plazas para proyectos de investigación
    "uhu": "investigacion",  # ídem: Personal Técnico de Apoyo a la Investigación
    "uvigo": "investigacion",  # ídem: concursos de personal de investigación
    "usc": "investigacion",  # ídem: convocatorias de personal para proyectos de investigación
    "udc": "investigacion",  # ídem: contratación con cargo a proyectos (PCTI)
    "unirioja": "investigacion",  # ídem: contratos con cargo a proyectos y de talento investigador
}
GROUP_AREAS = {"investigacion": "investigacion"}

# Contratos con cargo a un proyecto de investigación: el título es la categoría y, después, el
# nombre del proyecto (en udc, el centro). Por fuente y por formato, para no esconder otro tipo de
# plaza de la fuente.
PROJECT_TITLES = {
    "ifapa": re.compile(r"^(.+?) · "),
    "uhu": re.compile(r"^(.+?) · "),
    "udc": re.compile(r"^(.+?) · "),  # «categoría · centro»; todas son contratos PCTI
    "unirioja": re.compile(r"^(.+?) · "),
    "ua": re.compile(r"^(.+?) para colaborar con (?:el proyecto|la línea de investigación)\b"),
}


def project_category(title: str, source: str) -> str:
    """Categoría («Personal tecnólogo superior») si el título es «categoría + proyecto»; si no, «»."""
    found = PROJECT_TITLES[source].match(title) if source in PROJECT_TITLES else None
    return found.group(1) if found else ""


FRASES = [
    # nombres de organismos y fórmulas que no dicen nada del puesto
    (r"autoridad portuaria[^)]*|puertos del estado|grupo tragsa|correos express|jovenes talentos?|"
     r"(fundacion )?instituto de investigacion sanitaria[^)]*|"
     r"convocatoria (publica|externa|interna)|banco de datos|proceso libre", {}),
    # quién paga el contrato, no qué se hace («línea de investigación financiada», UA)
    (r"\bfinanciad[oa]s?\b", {}),
    # presentaciones fijas de la empresa al principio de las fichas
    (r"especializada en (la realizacion de actividades de ingenieria[^.]*medioambiental|"
     r"trabajos relacionados con el desarrollo del medio rural y conservacion de la naturaleza)|"
     r"hr excellence in research|research work environment|(seeking|looking) to recruit", {}),
    (r"contratacion de (personal|tecnic\w*|un\w*|investigador\w*)|curso? de formacion para|"
     r"curs de formacio per", {}),
    (r"administracion publica|(convocatoria (de )?)?proceso (de seleccion|selectivo)|"
     r"para la (cobertura|provision) de( \w+)? (puestos?|plazas?)( de trabajo)?( de)?|"
     r"oferta (de )?empleo publico|tasa de reposicion", {}),
    (r"derecho (mercantil|civil|penal|administrativo|laboral|constitucional|internacional|procesal|"
     r"tributario|financiero)", {"juridico": 3}),
    (r"cultivos? celular\w*", {"investigacion": 2}),  # de laboratorio, no del campo
    (r"capital humano|talento humano|\bnomin(a|as|es)\b", {"personas": 3}),
    (r"persones i organitzacio|personas y organizacion", {"personas": 3}),  # nombre del departamento
    (r"inteligencia artificial|machine learning|aprendizaje automatico|\bia\b|\bai\b",
     {"tic": 3}),
    (r"operador\w* (tecnic\w* )?(masia|parc d['’]atraccions|parque de atracciones)", {"oficios": 3}),
    (r"area de negoci de l['’]explotacio", {"comercial": 3}),
    (r"ordenacion y gestion grafica", {"obras": 3}),
    (r"artes graficas|impresion|offset|encuadernac\w*|preimpresion", {"oficios": 3}),
    (r"facturacion|cobros|tesoreria", {"economia": 3}),
    (r"planificacion y control", {"economia": 2}),
    (r"administracion y direccion de empresas|\bade\b", {"economia": 1}),
    (r"caminos,? canales y puertos", {"obras": 2}),
    (r"sanidad animal|control sanitario de fauna|recursos geneticos|desarrollo rural|"
     r"desenvolupament rural|medio rural|concentracion parcelaria|observador\w* cientific\w*",
     {"ambiente": 3}),
    (r"seguridad y salud|seguridad,? salud y bienestar|prevencion de riesgos|\bprl\b|"
     r"occupational health|salud laboral|riscos laborais|seguretat i salut|laneko arriskuen", {"personas": 3}),
    (r"(titulad\w*|tecnic\w*)( superior| medio)? (de |en )?prevencion$", {"personas": 3}),
    (r"medic\w* (del trabajo|de empresa)|metge del treball|enfermeria de empresa",
     {"sanidad": 3, "personas": 2}),
    (r"seguridad industrial|seguretat industrial", {"ingenieria": 3}),
    (r"ciberseguridad\w*|ciberseguretat|cybersecurity|seguridad de la informacion|"
     r"seguridad informatica|seguretat informatica|seguridad de (los )?sistemas de informacion", {"tic": 3}),
    (r"seguridad ferroviaria|seguretat ferroviaria", {"transporte": 3}),
    (r"servicio de seguridad|seguridad (fisica|patrimonial|privada)|control (de )?accesos|"
     r"vigilante\w*|polic\w*|bomber\w*|salvamento|socorrista\w*|emergencias|proteccion civil|"
     r"extincion de incendios|suhiltzaile\w*|servei de seguretat|tecnic\w* de (seguridad|seguretat)\b",
     {"seguridad": 3}),
    (r"atencion al usuario informatic\w*|atencio (al |a l['’])?usuari\w* informatic\w*", {"tic": 3}),
    (r"atencion (al|a la|e informacion al) (usuario|cliente|ciudadan\w*|publico|pasajero)|"
     r"atencion al visitante|atencio (al |a la |a l['’])?(usuari|client|visitant|public|ciutadania)\w*|"
     r"informacion al pasajero|agent\w* civic\w*|customer service|call ?center|"
     r"punto (de )?(atencion|informacion)", {"comercial": 3}),
    (r"sistemas? de informacion geografica|\bsig\b|teledeteccion|geomatic\w*|geodesi\w*|"
     r"fotogrametri\w*|\blidar\b|cartografi\w*|topograf\w*|hidrografi\w*", {"obras": 2, "ambiente": 1}),
    (r"soporte (cau|informatico|tecnico informatico|a usuarios|it)|servicios a usuarios|"
     r"it support|help ?desk|centro de atencion al usuario informatico", {"tic": 3}),
    (r"\bcau\b", {"tic": 1, "comercial": 1}),
    (r"(analista|tecnic\w*|administrador\w*|ingenier\w* informatic\w*) de sistemas( informaticos)?|"
     r"analistas?[ -]programador\w*|tecnologias de la informacion|sistemas de informacion|"
     r"estrategia digital|transformacion digital|administracion digital|administracio digital|"
     r"sistemas? de negocio|sistemes de negoci|sistemes critics|sistemas criticos|"
     r"tecnic\w* de (dades|datos)|desarrollo de (software|aplicaciones)|software developer|desenvolupador\w*|"
     r"analisis (de )?datos|data analy\w*|data scien\w*|cientific\w* de datos|"
     r"cabinas de almacenamiento|almacenamiento (de datos|informatico|cloud)|bases? de datos|"
     r"infraestructuras? (cis|tic|it|informatica\w*|de sistemas|de red\w*|cloud)|"
     r"arquitect\w* (de )?(software|soluciones|sistemas|cloud|datos)|arquitecturas? tic",
     {"tic": 3}),
    (r"administrador\w* (de )?(plataforma|redes|cabinas)", {"tic": 3}),
    (r"sistemas audiovisuales|imagen y sonido|informacion grafica|captacion de imagen|"
     r"efectos especiales|ambientacion|decorados|diseno grafico|disenador\w* grafic\w*|"
     r"informacion y contenidos|contenidos digitales|comunicacion social|imagen corporativa|"
     r"realizacion( \(asistencia\)| audiovisual| de (television|programas))|realizador\w*|"
     r"\biluminacion\b|profesor\w* de orquesta", {"comunicacion": 3}),
    (r"bienes culturales|bens culturals|patrimonio (cultural|historico|artistico)|"
     r"patrimoni (cultural|historic)", {"comunicacion": 3}),
    (r"ingenier\w* de (la )?edificacion|arquitect\w* tecnic\w*", {"obras": 3}),
    (r"oficial\w* (de )?(puente|maquinas)|jefe\w* de maquinas|patron\w* (de|del) "
     r"(embarcacion|litoral|cabotaje|altura|buque|pesca)\w*|marina mercante|\bm\.?m\.?",
     {"transporte": 3}),
    # gestión de un centro de investigación: puesto de gestión, también en la portada (site.research_only)
    (r"gestion de (la )?investigacion|gestion del conocimiento|research management|gestio de la recerca",
     {"admin": 3, "investigacion": 1}),
    # la formación del personal investigador (predoctoral) no es un puesto de formación
    (r"(investigador\w*|predoctoral\w*|predoc) (en|de) formacion|investigador\w* en formacio", {"investigacion": 3}),
    (r"apoyo a la investigacion|research support|suport a la recerca", {"investigacion": 3}),
    (r"grupo de investigacion|research group|grup de recerca|\bgroup\b", {"investigacion": 2}),
    (r"ensayos? clinic\w*|clinical (trial|research)|study coordinator|assaigs? clinic\w*",
     {"investigacion": 3, "sanidad": 1}),
    (r"data manager|gestor\w* de datos", {"investigacion": 1, "tic": 1}),
    (r"auxiliar de laboratorio|tecnic\w* de laboratorio|laboratory technician|"
     r"tecnic\w* de laboratori", {"investigacion": 3}),
    (r"recursos humanos|\brrhh\b|\bhr\b|human resources|recursos humans|giza baliabide\w*|"
     r"relaciones laborales|gerencia de personas|departamento de personas|"
     r"administracion de personal|seleccion y formacion|procesos de seleccion|"
     r"desarrollo de personas|organizacion,? formacion", {"personas": 3}),
    (r"cuentas a pagar|contabilidad|contable\w*|comptabilitat|accounting|accountant|"
     r"control de gestion|inversiones financieras", {"economia": 3}),
    (r"contratacion publica|contratacion y compras|licitacion\w*|expedientes? de contratacion|"
     r"contractacio publica|procurement|secretaria general|servicios generales|"
     r"operations manager|process (and|&) operations|gestor\w* de proyectos|project manager|"
     r"control documental|gestion documental|inventarios? de bienes|exp\. compras",
     {"admin": 3}),
    (r"bon govern|buen gobierno|compliance|cumplimiento normativo|responsable de cumplimiento|"
     r"asesor\w* juridic\w*", {"juridico": 3}),
    # antes que la defensa militar (Tragsa 58747, «representación y defensa de procedimientos judiciales»)
    (r"defensa (de procedimientos )?judicial\w*|defensa juridic\w*|asuntos contenciosos", {"juridico": 3}),
    (r"comunicacion ambiental", {"comunicacion": 3, "ambiente": 2}),
    (r"comunicacion de mercado|gestor\w* de productos?|product manager", {"comercial": 3}),
    (r"head of (department|unit)|jefe\w* de departamento|cap de departament", {}),
    (r"i\+d\+i|i\+d|r\+d|r&d", {"investigacion": 2}),
    (r"ciencias de la salud|ciencies de la salut", {"sanidad": 1, "investigacion": 1}),
    (r"ciencias del mar|medio marino|espacios marinos|areas marinas|reservas? de la biosfera|"
     r"red natura|biodiversidad|habitats?|restauracion (ambiental|forestal)|genetica forestal|"
     r"dominio publico (maritimo|hidraulico)|residuos|productos libres( de deforestacion)?|"
     r"deforestacion importada|especies? (exotic|invasor|amenazad|protegid)\w*", {"ambiente": 3}),
    (r"ciencias ambientales|ciencias de la naturaleza", {"ambiente": 1}),
    (r"energias? renovables?|eficiencia energetica|transicion energetica|"
     r"instalaciones electricas|ingenieria electrica|sistemas? electric\w*|equipos? electr\w*",
     {"ingenieria": 3, "ambiente": 1}),
    (r"\bgeolog[oa]s?\b", {"ingenieria": 2, "ambiente": 1}),
    (r"\bmecanic[oa]s?\b|mecanica de equipos?", {"oficios": 2, "ingenieria": 1}),
    (r"produccion ceramica|medidas radiologicas", {"oficios": 3}),
]

PALABRAS = [
    # medio ambiente, agro y pesca
    (r"\bforestal\w*|\bmontes\b|\bagronom\w*|\bagricol\w*|\bagrari\w*|\bagricultur\w*|"
     r"\bganader\w*|\bveterinari\w*|\bfitosanitari\w*|\bfauna\b|\bflora\b|\bpesca\b|"
     r"\bpesquer\w*|\bdeforestacion|\bxylella|\bjardiner\w*|\bpaisajism\w*|\bhortofrutic\w*|"
     r"\binvernadero|\bincendios?\b|\bforestry|\bfisher\w*|\bnekazaritz\w*|\bbasogintz\w*|"
     r"\bmedi ambient\w*|\bmedio ?ambient\w*|\benvironment\w*|\bingurumen\w*|\bmeteorolog\w*|"
     r"\bhidrometeorolog\w*|\bhidrometereolog\w*|\bcultivos?\b|\bplagas?\b|\bacuicultur\w*", {"ambiente": 3}),
    (r"\baguas?\b|\bhidrolog\w*|\bhidric\w*|\bacuifer\w*|\bsaneamiento|\bdepuracion|"
     r"\bcaudales|\bdeslindes?\b|\bcostas?\b|\bemisiones|\bsostenibilidad|\bambiental\w*|"
     r"\binsectos|\bdph\b", {"ambiente": 2}),
    (r"\bbiolog\w*|\bgeologia", {"ambiente": 1, "investigacion": 1}),
    # construcción, obras y arquitectura
    (r"\bobras?\b|\bobres\b|\bconstruccion|\bconstruction|\beraikuntz\w*|\bedificacion|"
     r"\bedificios|\burbanism\w*|\bplaneamiento|\bcarreteras|\bbim\b|\bdelineante\w*|"
     r"\binfraestructuras?\b|\bamianto|\barquitect\w*", {"obras": 3}),
    # ingeniería industrial y energía; aeronáutica, espacio y defensa
    (r"\bclausura|\bdesmantelamiento|\bminer[ao]s?\b|\bminas\b", {"ingenieria": 3}),
    (r"\bingenier\w*|\benginyer\w*|\bengineer\w*|\benxenei\w*|\bingeniari\w*", {"ingenieria": 1}),
    (r"\bindustrial\w*|\belectric\w*|\belectronic\w*|\bnuclear\w*|\benergia\w*|"
     r"\binstrumentacion|\bnaval\w*", {"ingenieria": 2}),
    (r"\baeronav\w*|\baereas?\b|\baeronautic\w*|\baviacion|\baviation|\baircraft|\baerospace|"
     r"\baeroespacial\w*|\bespacial\w*|\bsatelit\w*|\bgnss\b|\bnavegacion aerea|\batm\b|\bans\b|"
     r"\bcontrolador\w* aere\w*|\barmamento|\bsistemas terrestres|\bacorazad\w*|\bdefensa\b|"
     r"\bmilitar\w*|\bmisil\w*|\breservistas", {"aeroespacial": 3}),
    # tic
    (r"\binformatic\w*|\bprogramador\w*|\bdesarrollador\w*|\bdeveloper\w*|\bsoftware|"
     r"\bsoc\b|\bsap\b|\btic\b|\bict\b|\btelecomunicacion\w*|\btelecomunicacio\w*|\bphp\b|"
     r"\bjava\b|\bpython\b|\bcloud\b|\binformatika\w*|\bbioinformatic\w*|\bcis\b|\bdevops\b|"
     r"\bplatform engineer\w*",
     {"tic": 3}),
    (r"\bdigitalizacion|\bdigital\b|\bdatos\b|\bdata\b|\bsistemas\b|\bsistemes\b|\bsoporte\b|"
     r"\bsupport\b|\banalista\w*", {"tic": 1}),
    # administración y gestión
    (r"\badministrativ\w*|\badministratiu\w*|\badministrari\w*|\bsecretari[ao]\w*|"
     r"\bgrabador\w*|\boffice\b|\bfinestra unica|\bcompras\b|\bpatrimonio\b|\barchiv\w*|"
     r"\bdocumentalista", {"admin": 3}),
    (r"\bexpedientes?\b|\btramitacion|\bayudas?\b|\bsubvenciones", {"admin": 2}),
    (r"\badministracion\b|\badministracio\b", {"admin": 2}),
    (r"\bregistro\b|\binventarios?\b|\bfondos\b|\bgestion\b|\bcontratacion\b|\bdocumentacion\b",
     {"admin": 1}),
    # economía, finanzas y estadística
    (r"\bfinanc\w*|\bauditor\w*|\btesoreri\w*|\bfiscal\w*|\bpresupuest\w*|\beconomic\w*|"
     r"\beconomia\b|\bestadistic\w*|\bfundraising|\bmecenazgo|\bcomptab\w*|\bfinance\w*|"
     r"\bekonomi\w*", {"economia": 3}),
    (r"\bempresariales|\beconomicas", {"economia": 1}),
    # jurídico
    (r"\bjuridic\w*|\bletrad[oa]\w*|\babogad\w*|\badvocat\w*|\bavogad\w*|\blawyer|\blegal\b|"
     r"\bxuridic\w*|\babokatu\w*|\bsancionador\w*|\bjurist\w*", {"juridico": 3}),
    (r"\bnormativ\w*|\bderecho\b|\bdret\b|\bdereito\b|\bzuzenbide\w*|\blaw\b", {"juridico": 2}),
    # recursos humanos, formación y PRL
    (r"\bformador\w*|\bformacion\b|\bformacio\b|\btraining\b|\bseleccion\b|\bselection\b|"
     r"\brecruit\w*|\bprestakuntza\w*", {"personas": 3}),
    # investigación y laboratorio
    (r"\binvestigador\w*|\binvestigacion\b|\bresearch\w*|\brecerca\b|\bpostdoc\w*|"
     r"\bpostdoctoral\w*|\bpredoc\w*|\bikertzaile\w*|\bikerketa\w*|\bscientist|\bcientific[oa]s?\b|"
     r"\bbioestadist\w*|\bbiostatistic\w*|\binvestigacio\b", {"investigacion": 3}),
    (r"\blaboratori\w*|\blaboratory|\blab\b", {"investigacion": 2}),
    (r"\bdoctor[ae]?\b|\bphd\b|\bbiotecnolog\w*|\bbioquimic\w*|\bquimic\w*|\bgenetic\w*|"
     r"\binnovacion\w*|\binnovacio\b|\binnovation", {"investigacion": 1}),
    # sanidad
    (r"\bmedic[oa]s?\b|\bmetge\w*|\bphysician|\bmediku\w*|\benfermer\w*|\binfermer\w*|"
     r"\bnurse\w*|\berizain\w*|\benfermeir\w*|\bfisioterap\w*|\bcelador\w*|\bmatron\w*|"
     r"\bpsicolog\w*|\bodontolog\w*|\bfarmaceutic\w*|\bpharmacist|\btca[ei]\b|"
     r"\bauxiliar\w* (de |d')?(clinic|sanitari|enfermer|infermer)\w*", {"sanidad": 3}),
    (r"\bsanitari\w*|\bhospital\w*|\bclinic\w*|\bsalud\b|\bsalut\b|\bhealth\b|\bosasun\w*|"
     r"\bmedicina\b|\bfarmacia\b|\bcancer\b|\boncolog\w*|\bpneumolog\w*|\bneumolog\w*",
     {"sanidad": 1}),
    # transporte, náutica y logística
    (r"\bconductor\w*|\bcondutor\w*|\brepartidor\w*|\bchofer\w*|\bdriver\w*|\bgidari\w*|\bmaquinista\w*|"
     r"\bbuques?\b|\bembarcacion\w*|\blogistic\w*|\bferroviari\w*|\bferrocarril\w*|"
     r"\btripulante\w*|\bmarineri\w*|\bmariner[oa]?s?\b|\baeropuert\w*|\bportuari\w*|\bpuertos?\b|\bexplotacio\b|"
     r"\btransporte\w*|\btransport\b", {"transporte": 3}),
    (r"\balmacen(es|ero|eros|era|eras)?\b|\bwarehouse", {"transporte": 2, "oficios": 2}),
    # oficios, operarios y mantenimiento
    (r"\boperari[oa]\w*|\bmantenimiento|\bmanteniment\b|\bmaintenance|\bmantentze\w*|"
     r"\boficios\b|\bpeon\w*|\belectricista\w*|\bfontaner\w*|\bsoldador\w*|\blimpieza|"
     r"\bcapataz\w*|\bcocin\w*|\bcamarer\w*|\bcalefactor\w*|\bfrigorist\w*|\bclimatizacion|"
     r"\bcarpinter\w*|\bpintor\w*|\balbanil\w*|\bcerrajer\w*|\btorner[oa]s?\b|\bchapista\w*|"
     r"\bconserje\w*|\bordenanza\w*|\bmozo\w*|\bcarretiller\w*|\bmontador\w*|\bfresador\w*|"
     r"\bmecanizado|\bpaleta\b|\bplumber|\bcarpenter|\belectrician|\bfuster\w*|\blampista\w*|"
     r"\bmantenedor\w*|\barotz\w*|\biturgin\w*", {"oficios": 3}),
    (r"\bencargad[oa]\w*|\bproduccion\b|\bclasificador\w*", {"oficios": 1}),
    # comunicación, audiovisual y cultura
    (r"\bcomunicacion\b|\bcomunicacio\b|\bcommunication\w*|\bperiodist\w*|\bredactor\w*|"
     r"\beditor\w*|\bprensa\b|\baudiovisual\w*|\bcamara\b|\bsonido\b|\bmusic\w*|\bmuseo\w*|"
     r"\bbibliotec\w*|\bbiblioteconomia|\btraduct\w*|\beventos\b|\bpublicidad|\bkazetari\w*",
     {"comunicacion": 3}),
    # comercial y atención al público
    (r"\bcomercial(es)?\b|\bventas?\b|\bvendedor\w*|\bmarketing\b|\bencuestador\w*|\bencuestas?\b|"
     r"\btaquiller\w*|\binformador\w*|\brecepcionist\w*|\bteleoperador\w*|\bsales\b",
     {"comercial": 3}),
]
FRASES = [(re.compile(p), w) for p, w in FRASES]
PALABRAS = [(re.compile(p), w) for p, w in PALABRAS]

GENDER = re.compile(r"(\w)[/-](a|as|es|ora|oras|na|nes|o|os)\b")
DEGREE = re.compile(r"^(licenciad|licenciatura|graduad|grado|diplomad|diplomatura|titulad|"
                    r"titulacion|master|ingenier|arquitect|doctor)")
DEGREE_WORD = re.compile(r"\b(licenciad|licenciatura|ingenier|arquitect|graduad|grado|diplomad|"
                         r"diplomatura|titulad)")
STEM = {"licenciatura": "licenciad", "grado": "graduad", "diplomatura": "diplomad"}
ENGINEER = re.compile(r"(ingenier|enginyer|engineer|enxenei|ingeniari)")
FICHA_CHARS = 1500
MULTI_POST = re.compile(r"tasa de reposicion|oferta (de )?empleo publico")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("l·l", "ll").replace("rr.hh", "rrhh").replace("rr. hh", "rrhh")
    text = GENDER.sub(r"\1", text)          # técnico/a, titulado-a, enginyer/a
    text = GENDER.sub(r"\1", text)          # licenciado/a/graduado/a
    # fuera códigos y referencias: cualquier palabra con cifras (26-144_ss_vn, 2026/67, bc26342)
    text = " ".join(t for t in text.split() if not any(ch.isdigit() for ch in t))
    text = re.sub(r"[_–—·]", " - ", text)
    return re.sub(r"\s+", " ", text).strip()


# Las áreas tal como se muestran (filtro, avisos, feeds, bot): por nombre, sin contar tildes.
BY_NAME = sorted(AREAS.items(), key=lambda item: normalize(item[1]))


def score(text: str) -> dict[str, float]:
    """Puntos por área de un texto ya normalizado."""
    total: dict[str, float] = {}
    for rx, weights in FRASES:
        if rx.search(text):
            for area, w in weights.items():
                total[area] = total.get(area, 0) + w
            text = rx.sub(lambda m: " " * len(m.group(0)), text)
    for rx, weights in PALABRAS:
        if rx.search(text):
            for area, w in weights.items():
                total[area] = total.get(area, 0) + w
    return total


def score_title(title: str) -> dict[str, float]:
    """Títulos «titulación - función»: si la titulación es una lista genérica (muchas carreras o
    ramas) y la función ya dice el área, la lista pesa la mitad."""
    text = normalize(title)
    head, sep, tail = text.partition(" - ")
    if not sep or not DEGREE.match(head):
        return score(text)
    first, second = score(head), score(tail)
    stems = {STEM.get(m, m) for m in DEGREE_WORD.findall(head)}
    generic = len(stems) >= 3 or sum(v >= 2 for v in first.values()) >= 3
    factor = 0.5 if generic and max(second.values(), default=0) >= 2 else 1
    return {k: first.get(k, 0) * factor + second.get(k, 0) for k in set(first) | set(second)}


def multi_post(title: str) -> bool:
    """Proceso de muchos puestos publicado como oferta (tasa de reposición con plazo abierto)."""
    return bool(MULTI_POST.search(normalize(title)))


def source_area(source: str = "", group: str = "") -> str | None:
    return SOURCE_AREAS.get(source) or GROUP_AREAS.get(group)


def classify(title: str, ficha: str = "", source: str = "", group: str = "",
             top: int = 2) -> tuple[list[str], str]:
    """(áreas de más a menos segura, de dónde salen: «título», «ficha», «fuente» o «»)."""
    total = score_title(title)
    prior = source_area(source, group)
    if prior:  # desempate a favor del ámbito de la fuente; solo no llega al umbral
        total[prior] = total.get(prior, 0) + 1
    origin = "título"
    # un proceso de muchos puestos (tasa de reposición, OEP) no tiene un área: la ficha no la da
    if max(total.values(), default=0) < 2 and ficha and not multi_post(title):
        for area, points in score(normalize(ficha[:FICHA_CHARS])).items():
            total[area] = total.get(area, 0) + points * 0.5
        origin = "ficha"
    best = max(total.values(), default=0)
    if best < 2 and total.get("ingenieria", 0) >= 1 and ENGINEER.match(normalize(title)):
        total["ingenieria"] = best = 2   # «Ingeniero/a de …» sin más pistas
    project = bool(project_category(title, source))
    if best < 2:
        if project:  # el formato del título ya dice que es de investigación
            return ["investigacion"], "título"
        return ([prior], "fuente") if prior else ([], "")
    ranked = sorted(total, key=lambda k: (-total[k], ORDER[k]))  # a igualdad, orden de AREAS
    found = [k for k in ranked if total[k] >= max(2, best * 0.5)]
    if project:  # investigación siempre; el nombre del proyecto solo añade la segunda área
        found = ["investigacion"] + [k for k in found if k != "investigacion"]
    return found[:top], origin


TAGS = re.compile(r"<[^>]+>")
REFERENCE = Path(__file__).with_name("areas_referencia.csv")


def ficha_text(offer: dict) -> str:
    """Texto plano de la ficha guardada, en el orden de sus apartados."""
    parts = []
    for section in offer.get("sections") or []:
        parts.append(section.get("title") or "")
        parts.append(html.unescape(TAGS.sub(" ", section.get("html") or "")))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def offer_areas(offer: dict, group: str = "") -> tuple[list[str], str]:
    return classify(offer.get("title") or "", ficha_text(offer), offer.get("source") or "", group)


def reference(path: Path = REFERENCE) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def report(offers: list[dict], groups: dict[str, str], reviewed: set | None = None) -> str:
    """Markdown con las ofertas abiertas sin área o con la de la fuente que no estén ya revisadas
    (en areas_referencia.csv) y, de los centros de investigación y las universidades, las que quedan
    solo en «Investigación» por la ficha o salen también en la portada teniendo el área de
    investigación; vacío si no queda ninguna."""
    from . import site  # importación tardía: site importa este módulo

    if reviewed is None:
        reviewed = {(row["fuente"], row["titulo"]) for row in reference()}
    missing, by_source, placed = [], [], []
    for offer in sorted(offers, key=lambda o: (o["source"], o.get("title") or "")):
        if (offer["source"], offer.get("title")) in reviewed:
            continue
        group = groups.get(offer["source"], "")
        found, origin = offer_areas(offer, group)
        names = ", ".join(AREAS[area] for area in found)
        if not found and not multi_post(offer.get("title") or ""):  # sin área a propósito
            missing.append(offer)
        elif origin == "fuente":
            by_source.append((offer, found[0]))
        elif group not in site.RESEARCH_GROUPS:
            continue
        elif site.research_only(offer, group):
            # con título «categoría + proyecto» sale solo allí por el formato, no por el área
            if origin == "ficha" and not project_category(offer.get("title") or "", offer["source"]):
                placed.append((offer, f" → solo en «Investigación», por la ficha ({names})"))
        elif "investigacion" in found:
            placed.append((offer, f" → también en la portada ({names})"))

    def line(offer: dict, note: str = "") -> str:
        title = (offer.get("title") or "").replace("|", "/").replace("\n", " ")
        link = f"[{title}]({offer['url']})" if offer.get("url") else title
        return f"- `{offer['source']}` {link}{note}"

    if not missing and not by_source and not placed:
        return ""
    out = [
        "Ofertas abiertas que el clasificador de áreas (`empleo/areas.py`) no resuelve con el "
        "título ni con la ficha o, en los centros de investigación, decide con menos seguridad. "
        "Para cada una: si el título dice el área, añade o corrige una "
        "regla; después, añádela a `empleo/areas_referencia.csv` con su área correcta (o vacía, "
        "si no tiene) y deja de salir aquí.",
        "",
        "Este issue se actualiza solo en cada publicación y se cierra cuando la lista queda vacía.",
    ]
    if missing:
        out += ["", f"## Sin área ({len(missing)})", "", "Solo aparecen con «Todas» o «Sin área».", ""]
        out += [line(o) for o in missing]
    if by_source:
        out += ["", f"## Con el área de la fuente ({len(by_source)})", "",
                "El título no dice nada; se les ha dado el ámbito del organismo. Comprueba que encaja.", ""]
        out += [line(o, f" → {AREAS[area]}") for o, area in by_source]
    if placed:
        out += ["", f"## Centros de investigación y universidades: dónde salen ({len(placed)})", "",
                "El área decide si la oferta sale solo en «Investigación» o también en la portada. "
                "Comprueba que estas están donde deben.", ""]
        out += [line(o, note) for o, note in placed]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    from . import site  # importación tardía: site importa este módulo
    from .sources import ACTIVE

    if argv[:1] != ["informe"]:
        print("Uso: python -m empleo.areas informe [salida.md]", file=sys.stderr)
        return 2
    offers, _, _ = site.load_all(Path("data"))
    groups = {s.id: s.group for s in ACTIVE}
    text = report([o for o in offers.values() if o["status"] == "open"], groups)
    if len(argv) > 1:
        Path(argv[1]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    pending = sum(line.startswith("- `") for line in text.splitlines())
    print(f"Ofertas por revisar: {pending}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
