from dataclasses import dataclass

from bot.config import MODALIDAD, PISO_SALARIAL


@dataclass
class Clasificacion:
    fit_score: float          # 0-100
    cumple_excluyentes: bool
    banda_salarial_ok: bool
    modalidad_ok: bool
    angulo: str                # DE_ES, DS_ES, DE_EN
    recomendacion: str         # "postular" | "descartar"
    razones: str


# Valores por defecto de piso salarial y modalidad: salen de .env (PISO_SALARIAL, MODALIDAD).
PISO_SALARIAL_DEFAULT = PISO_SALARIAL
MODALIDAD_DEFAULT = MODALIDAD
ANGULOS_DEFAULT = {
    "DE_ES": "Data Engineer, en español",
    "DE_EN": "Data Engineer, en inglés (oferta internacional o exige inglés)",
    "DS_ES": "Data Science / ML / analítica avanzada, en español",
}


@dataclass
class Preferencias:
    piso_salarial: str = PISO_SALARIAL_DEFAULT
    modalidad: str = MODALIDAD_DEFAULT
    angulos: dict | None = None  # código -> descripción; None = ANGULOS_DEFAULT

    def angulos_o_default(self) -> dict:
        return self.angulos or ANGULOS_DEFAULT


# Secciones del README original que no aportan a generar CVs (registro de CVs, protocolo de
# chat, convenciones de archivos): ~43% del documento. No se envían a la IA.
SECCIONES_EXCLUIDAS_DEFAULT = [
    "Instrucciones de uso",
    "Convención de nombres de archivos",
    "Configuración global obligatoria (todos los YAMLs)",
    "CVs generados (registro)",
    "Protocolo para iniciar un nuevo chat",
]
