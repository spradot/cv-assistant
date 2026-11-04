"""Validación ATS real: no le pedimos a un LLM que "simule" un ATS (no es como
funcionan) — hacemos lo mismo que hace un ATS de verdad:
1) extraer el texto del PDF tal cual lo vería el parser (pypdf, la misma familia
   de librerías que usan la mayoría de los ATS reales), y
2) medir cobertura determinística de las palabras clave de la oferta contra ese
   texto extraído. Las palabras clave las identifica DeepSeek al generar el CV
   (es una tarea de comprensión, ahí sí rinde un LLM); la cobertura es matemática,
   no hay nada que "opinar"."""

import re
import unicodedata
from dataclasses import dataclass

from pypdf import PdfReader


@dataclass
class ResultadoATS:
    parseo_ok: bool
    detalle_parseo: str
    cobertura: float  # 0-1
    keywords_presentes: list[str]
    keywords_faltantes: list[str]


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def extraer_texto_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def contar_paginas(pdf_path: str) -> int:
    return len(PdfReader(pdf_path).pages)


def llenado_ultima_pagina(pdf_path: str) -> float:
    """Fracción (0-1) de la altura de la última página que ocupa el contenido, medida con la
    posición real del texto más bajo. Mecánico, igual que contar_paginas: es lo que permite
    detectar un CV de 1 página que deja un tercio en blanco."""
    pagina = PdfReader(pdf_path).pages[-1]
    alto = float(pagina.mediabox.height)
    y_min = [alto]

    def visitor(texto, cm, tm, fuente, tamano):
        if texto.strip():
            y_min[0] = min(y_min[0], tm[5] * cm[3] + cm[5])  # y del texto en coordenadas de página

    pagina.extract_text(visitor_text=visitor)
    return max(0.0, min(1.0, (alto - y_min[0]) / alto))


def _validar_parseo(texto: str) -> tuple[bool, str]:
    if len(texto.strip()) < 200:
        return False, "El PDF extrae muy poco texto — probable layout basado en imágenes/tablas que rompe el parser ATS."
    if "@" not in texto:
        return False, "No se detectó el email en el texto extraído — puede estar en un ícono o elemento gráfico no legible por ATS."
    if len(re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{3,}", texto)) < 30:
        return False, "El texto extraído parece corrupto o con muy pocas palabras reales."
    return True, "El texto se extrae limpio: nombre, contacto y contenido legibles como texto plano."


def evaluar(pdf_path: str, keywords_ats: list[str]) -> ResultadoATS:
    texto_extraido = extraer_texto_pdf(pdf_path)
    parseo_ok, detalle = _validar_parseo(texto_extraido)

    texto_norm = _normalizar(texto_extraido)
    presentes, faltantes = [], []
    for kw in keywords_ats:
        if _normalizar(kw) in texto_norm:
            presentes.append(kw)
        else:
            faltantes.append(kw)

    cobertura = len(presentes) / len(keywords_ats) if keywords_ats else 1.0

    return ResultadoATS(
        parseo_ok=parseo_ok,
        detalle_parseo=detalle,
        cobertura=round(cobertura, 2),
        keywords_presentes=presentes,
        keywords_faltantes=faltantes,
    )
