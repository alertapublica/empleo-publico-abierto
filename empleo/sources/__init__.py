"""Registro de fuentes del portal."""
import re

from .andalucia import AndaluciaSource
from .apb import ApbSource
from .canal import CanalSource
from .ccma import CcmaSource
from .cesce import CesceSource
from .centinela import SentinelSource
from .cetarsa import CetarsaSource
from .cimus import CimusSource
from .ciber import CiberSource
from .cnic import CnicSource
from .cesga import CesgaSource
from .ciqus import CiqusSource
from .cofivacasa import CofivacasaSource
from .efe import EfeSource
from .emacsa import EmacsaSource
from .emasesa import EmasesaSource
from .emt import EmtSource
from .enresa import EnresaSource
from .enusa import EnusaSource
from .etsa import EtsaSource
from .fgc import FgcSource
from .fgv import FgvSource
from .fibao import FibaoSource
from .fisevi import FiseviSource
from .fnmt import FnmtSource
from .fundanet import FISABIO, IDIBELL, IDIVAL, IMAS12
from .fundesalud import FundesaludSource
from .gesplan import GesplanSource
from .gpex import GpexSource
from .hunosa import HunosaSource
from .ibsal import IbsalSource
from .idibaps import IdibapsSource
from .ifapa import IfapaSource
from .idisna import IdisnaSource
from .idisba import IdisbaSource
from .iisaragon import IisAragonSource
from .iisgm import IisgmSource
from .imdea import ImdeaEnergiaSource
from .imib import ImibSource
from .irycis import IrycisSource
from .mayasa import MayasaSource
from .irb import IrbSource
from .isdefe import IsdefeSource
from .lafe import LaFeSource
from .mercasa import MercasaSource
from .mercasturias import MercasturiasSource
from .navarrabiomed import NavarrabiomedSource
from .ofertastrabajo import GaliciaSurSource, IdisSource
from .pfsrv import AENA, ENAIRE
from .puertos import PuertosSource
from .rtve import RtveSource
from .sarga import SargaSource
from .senasa import SenasaSource
from .serpa import SerpaSource
from .sepi import SepiSource
from .sepides import SepidesSource
from .successfactors import SuccessFactorsSource
from .tmb import TmbSource
from .tragsa import TragsaSource
from .ua import UaSource
from .uco import UcoSource
from .uji import UjiSource
from .udc import UdcSource
from .uhu import UhuSource
from .unirioja import UniriojaSource
from .upf import UpfSource
from .usc import UscSource
from .uvigo import UvigoSource
from .veiasa import VeiasaSource
from .zarzuela import ZarzuelaSource

CORREOS = SuccessFactorsSource(
    id="correos", name="Grupo Correos", host="https://empleo.correos.com", company="Correos",
    categories=[
        ("practicas", "/go/Programa-J%C3%B3venes-Talentos/4508201/"),
        (None, "/go/Perfiles-Corporativos/9700001/"),
        (None, "/go/Ofertas-publicadas/4331401/"),
    ],
)
NAVANTIA = SuccessFactorsSource(
    id="navantia", name="Navantia", host="https://empleo.navantia.es", company="Navantia",
    categories=[
        (None, "/go/Ofertas-de-empleo/9308355/"),
        ("practicas", "/go/Becas-y-Pr%C3%A1cticas/9308455/"),
    ],
)
BSM = SuccessFactorsSource(
    id="bsm", name="BSM (Barcelona de Serveis Municipals)", host="https://creix.bsmsa.cat", company="BSM",
    categories=[(None, "/go/Totes-les-vacants/9231655/")], location="Barcelona",
)
BSM.scope, BSM.text_lang = "Cataluña", "ca"
# Bolsas sin vacante activa («aquesta inscripció no correspon a una vacant activa») y fichas con varios
# perfiles distintos (sala, cuina i pastisseria de la Masia del Tibidabo).
BSM.not_a_post = re.compile(r"no correspon a una vacant activa|Posicions i funcions generals", re.I)
ADIF = SentinelSource(
    id="adif", name="ADIF y ADIF Alta Velocidad", homepage="https://www.adif.es/empleo",
    page="https://www.adif.es/empleo/oferta-empleo-publico/plazo-solicitud-abierto",
    empty_text="no hay ninguna oferta de empleo público",
)
FURIOJA = SentinelSource(
    id="furioja", name="Fundación de la Universidad de La Rioja",
    homepage="https://fundacion.unirioja.es/transparencia/ofertas-empleo",
    page="https://fundacion.unirioja.es/transparencia/ofertas-empleo",
    empty_text="No hay ofertas de empleo abiertas en este momento",
)
FURIOJA.scope = "La Rioja"
RENFE = SentinelSource(
    id="renfe", name="Renfe", homepage="https://empleo.renfe.com/",
    page="https://empleo.renfe.com/search/",
    empty_text="no hay ninguna vacante acorde a esta categoría en período de inscripción",
)

# Catálogo por grupos (claves de GROUPS), en el orden en que se muestran.
CATALOG = {
    "sepi": [
        SepiSource(), TragsaSource(), EfeSource(), CORREOS, NAVANTIA, EnusaSource(), RtveSource(),
        EnresaSource(), EtsaSource(), CetarsaSource(), CofivacasaSource(),
        ZarzuelaSource(), MercasaSource(), HunosaSource(), SepidesSource(), MayasaSource(),
    ],
    "estatal": [ENAIRE, AENA, PuertosSource(), ApbSource(), SenasaSource(), IsdefeSource(), FnmtSource(), CesceSource(), MercasturiasSource(), ADIF, RENFE],
    "autonomica": [FgcSource(), FgvSource(), GpexSource(), GesplanSource(), SargaSource(), SerpaSource(), CanalSource(), VeiasaSource(), CcmaSource(), AndaluciaSource()],
    "local": [TmbSource(), EmtSource(), BSM, EmasesaSource(), EmacsaSource()],
    "investigacion": [
        CiberSource(), IDIBELL, IdibapsSource(), FISABIO, IDIVAL, IdisnaSource(), IdisbaSource(), IbsalSource(), NavarrabiomedSource(), FundesaludSource(), IisAragonSource(),
        LaFeSource(), IrbSource(), CiqusSource(), CimusSource(), FiseviSource(), ImibSource(), IrycisSource(), CnicSource(),
        IdisSource(), GaliciaSurSource(), FibaoSource(), IMAS12, CesgaSource(), IisgmSource(), ImdeaEnergiaSource(), IfapaSource(), FURIOJA,
    ],
    "universidades": [UaSource(), UhuSource(), UvigoSource(), UscSource(), UdcSource(), UpfSource(), UniriojaSource(),
                      UcoSource(), UjiSource()],
}
for _group, _sources in CATALOG.items():
    for _source in _sources:
        _source.group = _group

ACTIVE = [source for sources in CATALOG.values() for source in sources]

# Fuentes que comparten servidor, o por prudencia la misma plataforma alojada sin confirmar que sea la
# misma máquina: se leen una tras otra, nunca a la vez. Las demás van solas. El Worker de relay/ no
# cuenta: cada petición es independiente y lo que importa es el servidor de destino.
# Al dar de alta una fuente, añádela aquí si comparte servidor con otra.
SHARED_SERVER = {
    "junta-andalucia": ("andalucia", "ifapa", "veiasa"),  # mismo host; Veiasa, misma red (217.12.19.0/24)
    "usc": ("ciqus", "cimus", "usc"),  # usc.gal: www, ciqus y cimus, sin confirmar que sea la misma máquina
    "successfactors": ("correos", "navantia", "fgc", "bsm", "renfe"),
    "fundanet": ("idibell", "fisabio", "idival", "imas12"),
    "seleccion": ("isdefe", "canal"),
    "pfsrv": ("enaire", "aena"),
    "ofertastrabajo": ("idis", "galiciasur"),
}
for _key, _ids in SHARED_SERVER.items():
    for _source in ACTIVE:
        if _source.id in _ids:
            _source.concurrency_group = _key

# Empresas previstas: se muestran como «próximamente» hasta tener su módulo.
PLANNED = []
