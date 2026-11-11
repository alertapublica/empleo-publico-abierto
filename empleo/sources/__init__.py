"""Registro de fuentes del portal."""
from .canal import CanalSource
from .cesce import CesceSource
from .centinela import SentinelSource
from .cetarsa import CetarsaSource
from .cimus import CimusSource
from .cnic import CnicSource
from .ciqus import CiqusSource
from .cofivacasa import CofivacasaSource
from .efe import EfeSource
from .enresa import EnresaSource
from .enusa import EnusaSource
from .etsa import EtsaSource
from .fgc import FgcSource
from .fgv import FgvSource
from .fisevi import FiseviSource
from .fnmt import FnmtSource
from .fundanet import FISABIO, IDIBELL, IDIVAL
from .fundesalud import FundesaludSource
from .gesplan import GesplanSource
from .gpex import GpexSource
from .hunosa import HunosaSource
from .ibsal import IbsalSource
from .idisna import IdisnaSource
from .imib import ImibSource
from .irycis import IrycisSource
from .mayasa import MayasaSource
from .isdefe import IsdefeSource
from .lafe import LaFeSource
from .mercasa import MercasaSource
from .mercasturias import MercasturiasSource
from .navarrabiomed import NavarrabiomedSource
from .pfsrv import AENA, ENAIRE
from .puertos import PuertosSource
from .rtve import RtveSource
from .sarga import SargaSource
from .senasa import SenasaSource
from .serpa import SerpaSource
from .sepi import SepiSource
from .sepides import SepidesSource
from .successfactors import SuccessFactorsSource
from .tragsa import TragsaSource
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
ADIF = SentinelSource(
    id="adif", name="ADIF y ADIF Alta Velocidad", homepage="https://www.adif.es/empleo",
    page="https://www.adif.es/empleo/oferta-empleo-publico/plazo-solicitud-abierto",
    empty_text="no hay ninguna oferta de empleo público",
)
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
    "estatal": [ENAIRE, AENA, PuertosSource(), SenasaSource(), IsdefeSource(), FnmtSource(), CesceSource(), MercasturiasSource(), ADIF, RENFE],
    "autonomica": [FgcSource(), FgvSource(), GpexSource(), GesplanSource(), SargaSource(), SerpaSource(), CanalSource()],
    "investigacion": [
        IDIBELL, FISABIO, IDIVAL, IdisnaSource(), IbsalSource(), NavarrabiomedSource(), FundesaludSource(),
        LaFeSource(), CiqusSource(), CimusSource(), FiseviSource(), ImibSource(), IrycisSource(), CnicSource(),
    ],
}
for _group, _sources in CATALOG.items():
    for _source in _sources:
        _source.group = _group

ACTIVE = [source for sources in CATALOG.values() for source in sources]

# Empresas previstas: se muestran como «próximamente» hasta tener su módulo.
PLANNED = []
