"""Generación y ajuste de CV + campos de postulación con DeepSeek.

El LLM SOLO genera el contenido (`cv`, como JSON) — nunca el diseño. bot/design.py junta
ese contenido con el bloque de diseño fijo (design_canonico.yaml) para armar el YAML final.
Esto también evita que el LLM tenga que producir YAML crudo: como todo llega como JSON
(response_format=json_object), no hay riesgo de valores sin comillas rompiendo el parser.

Ahorro de tokens (ver bot/llm.py para la parte de caché):
- El CV de referencia se manda como ESQUELETO (textos recortados, 2 entradas por sección):
  solo se usa para copiar estructura, el contenido completo era puro gasto.
- Ajustar / condensar devuelven solo las secciones que cambian (un "parche"), no el CV
  entero: la salida es la parte más cara y más lenta de cada llamada.
- JSON compacto (sin indentación) en todo lo que se envía."""

import copy
import dataclasses
from dataclasses import dataclass

from bot import llm
from bot.llm import compacto, con_perfil

_TAREA_GENERAR = """\
TAREA: arma la postulación a la oferta de arriba. Genera SOLO un objeto JSON válido con estas claves exactas:

- "cv": objeto con la MISMA estructura de claves/tipos que el ESQUELETO de referencia (el esqueleto solo muestra la forma: la CANTIDAD de secciones, entradas y bullets la decides tú). Los datos personales (name, email, phone, location, social_networks) salen del perfil.
PASO 1 — antes de escribir, deduce de la oferta el TIPO DE CARGO y la seniority, y adapta el CV a ese tipo:
  · Consultoría / gestión de proyectos / operaciones / negocio: bullets orientados a impacto y alcance (cliente o industria, tamaño del problema, metodología, entregable, resultado con cifra); destaca liderazgo de equipos o stakeholders, metodologías (BPMN, Lean, etc.) y herramientas de análisis.
  · Técnico (datos, software, ingeniería): stack y arquitectura primero, logros medibles por sistema.
  · Analista / junior: formación, herramientas y proyectos pesan más; semi-senior/senior: alcance y liderazgo.
  Ordena secciones y bullets según lo que ese cargo valora, y usa el vocabulario de la oferta.
HEADLINE: agrega la clave "headline" en `cv`, una línea (máx. 70 caracteres) con el título del cargo al que apunta la oferta, SOLO si el perfil lo respalda (si no, el cargo propio más cercano + área), p. ej. "Data Engineer · Pipelines ETL en Azure".
RESUMEN: describe quién es el candidato y qué domina (perfil, años, especialidad, logros clave), con el vocabulario de la oferta. NUNCA menciones la empresa, el cargo al que postula ni frases de intención ("busco aportar", "me interesa", "postulo a"): el resumen es del candidato, no una carta de presentación.
PASO 2 — OBJETIVO DE DENSIDAD: el CV es de 1 página y debe quedar LLENA (≈95% de la altura; hoy el error típico es dejar 30-35% en blanco). Para lograrlo usa TODO el material relevante del perfil: Resumen de 3-4 líneas; 4-6 bullets en cada experiencia relevante (2-3 en la antigua o menos relevante), cada bullet de 1-2 líneas con cifra o alcance concreto; Habilidades en 3-5 categorías; y las secciones que el perfil respalde (Educación con distinción/programa si existe, Certificaciones, Idiomas; Idiomas y Habilidades como entradas {label, details}, p. ej. {"label": "Inglés", "details": "C1"}; omite Idiomas si solo tiene la lengua nativa del CV). NO incluyas una sección de Proyectos (ni "Proyectos destacados"): solo si el usuario la pide expresamente en el ajuste. No dejes fuera datos del perfil relevantes a la oferta solo por brevedad. Nunca inventes: si el perfil no lo dice, no va — en particular NO agregues a Habilidades herramientas, metodologías o niveles que solo aparecen en la oferta (p. ej. requisitos "deseables") si el perfil no los respalda; y no subas el nivel declarado (nada de "experto" si el perfil dice "avanzado"). Sin relleno vacío ni bullets repetidos.
- "banda_salarial": banda sugerida en texto corto (líquido CLP si es Chile, USD/año si es internacional).
- "experiencia_200": resumen de experiencia para portales, MÁXIMO 190 caracteres.
- "habilidades_200": resumen de stack para portales, MÁXIMO 190 caracteres.
- "pretension_renta": una línea con la cifra a declarar.
- "disponibilidad": una línea corta.
- "modalidad_preferida": una línea corta.
- "keywords_ats": 8 a 15 términos EXACTOS de la oferta (herramientas, certificaciones, metodologías, \
títulos de cargo) que un ATS buscaría. Cópialos tal cual, sin traducir.
"""

_FORMATO_PARCHE = (
    'Responde SOLO un JSON {"secciones": {<nombre exacto de sección>: <lista COMPLETA de entradas nueva '
    'de esa sección, o null para eliminarla>}, "campos": {<clave de nivel superior distinta de sections>: '
    "<valor nuevo>}} incluyendo ÚNICAMENTE lo que cambia — todo lo demás queda igual. Mantén exactamente "
    "las mismas claves y tipos de las entradas existentes."
)

# Estructura neutra para usuarios que todavía no tienen CVs propios renderizados.
ESQUELETO_NEUTRO = {
    "name": "<del perfil>",
    "headline": "<título profesional, máx. 70 caracteres>",
    "location": "<del perfil>",
    "email": "<del perfil>",
    "phone": "<del perfil, formato internacional +56...>",
    "social_networks": [{"network": "LinkedIn", "username": "<usuario>"}],
    "sections": {
        "Resumen": ["<3-4 líneas orientadas a la oferta>"],
        "Habilidades": [{"label": "<categoría>", "details": "<herramientas separadas por coma>"}],
        "Experiencia Laboral": [
            {
                "company": "<empresa>",
                "position": "<cargo>",
                "location": "<ciudad>",
                "start_date": "2023-06",
                "end_date": "present",
                "highlights": ["<logro con cifra>", "<logro>"],
            }
        ],
        "Educación": [
            {"institution": "<universidad>", "area": "<carrera>", "degree": "<título>", "start_date": "2016-03", "end_date": "2021-12"}
        ],
        "Certificaciones": [{"label": "<certificación>", "details": "<emisor, fecha>"}],
    },
}


@dataclass
class ContenidoGenerado:
    cv: dict
    banda_salarial: str
    experiencia_200: str
    habilidades_200: str
    pretension_renta: str
    disponibilidad: str
    modalidad_preferida: str
    keywords_ats: list[str]


def quitar_proyectos(cv: dict) -> dict:
    """Las secciones de Proyectos solo van si el usuario las pide: el modelo las agrega solo
    (y a veces a medias). Se quitan de forma determinista, sin depender de que obedezca el prompt."""
    secciones = {n: e for n, e in (cv.get("sections") or {}).items() if "proyecto" not in n.lower()}
    return {**cv, "sections": secciones} if "sections" in cv else cv


def pide_proyectos(feedback: str | None) -> bool:
    return "proyecto" in (feedback or "").lower()


def esqueleto(cv: dict) -> dict:
    """Reduce un CV real a su estructura: datos personales como placeholder, máx. 2 entradas
    por sección y 2 bullets por entrada, textos recortados. ~70% menos tokens que el CV entero."""

    def recortar(valor, profundidad=0):
        if isinstance(valor, str):
            return valor if len(valor) <= 50 else valor[:50] + "…"
        if isinstance(valor, list):
            return [recortar(v, profundidad + 1) for v in valor[:2]]
        if isinstance(valor, dict):
            return {k: recortar(v, profundidad + 1) for k, v in valor.items()}
        return valor

    if not cv:
        return ESQUELETO_NEUTRO
    resultado = {k: ("<del perfil>" if isinstance(v, str) else recortar(v)) for k, v in cv.items() if k != "sections"}
    resultado["sections"] = {nombre: recortar(entradas) for nombre, entradas in (cv.get("sections") or {}).items()}
    return resultado


def generar_contenido(
    oferta_texto: str,
    perfil_readme: str,
    cv_referencia: dict,
    empresa: str,
    feedback_usuario: str | None = None,
) -> ContenidoGenerado:
    user_prompt = (
        f"OFERTA LABORAL ({empresa}):\n{oferta_texto}\n\n"
        f"ESQUELETO DE REFERENCIA (solo estructura, no copies su contenido):\n{compacto(esqueleto(cv_referencia))}\n\n"
        f"{_TAREA_GENERAR}"
    )
    if feedback_usuario:
        user_prompt += f"\nAJUSTE PEDIDO POR EL USUARIO SOBRE LA VERSIÓN ANTERIOR:\n{feedback_usuario}\n"

    mensajes = con_perfil(perfil_readme, user_prompt)
    campos_requeridos = [f.name for f in dataclasses.fields(ContenidoGenerado)]
    data = _pedir_json_completo(mensajes, campos_requeridos)

    data["experiencia_200"] = _recortar(str(data.get("experiencia_200", "")), 200)
    data["habilidades_200"] = _recortar(str(data.get("habilidades_200", "")), 200)
    # El modelo a veces agrega claves extra al JSON (ya pasó: devolvió un "type" suelto) —
    # se filtra a los campos que ContenidoGenerado realmente espera en vez de pasar **data a ciegas.
    campos_validos = set(campos_requeridos)
    contenido = ContenidoGenerado(**{k: v for k, v in data.items() if k in campos_validos})
    if not pide_proyectos(feedback_usuario) and isinstance(contenido.cv, dict):
        contenido.cv = quitar_proyectos(contenido.cv)
    return contenido


_TAREA_CV_BASE = """\
TAREA: arma el CV BASE del candidato (no hay oferta): un CV general, sólido y neutro que sirva de punto de partida para adaptarlo después a cada postulación. Genera SOLO un objeto JSON válido con la clave "cv": un objeto con la MISMA estructura de claves/tipos que el ESQUELETO de referencia (la CANTIDAD de secciones, entradas y bullets la decides tú).
- Datos personales (name, email, phone, location, social_networks) tal como están en el perfil; si un dato falta o aparece como "⚠️ Por completar", OMITE la clave. Nunca inventes datos de contacto.
- "headline": título profesional de una línea bajo el nombre (máx. 70 caracteres, p. ej. "Administrativo · Inventario y Activos Fijos"): usa el "Rol objetivo" del perfil si lo declara; si no, el cargo más reciente/relevante + 1-2 áreas de especialidad, siempre respaldado por el perfil. Sin adjetivos ni frases de intención.
- Resumen: UN solo párrafo (una única cadena) de 2-3 líneas: quién es, años de experiencia y 2-3 fortalezas distintivas. NO repitas lo que ya dicen la experiencia, las habilidades o la educación (nada de recorrer cargo por cargo ni listar cursos). Si el perfil no declara un rol objetivo, deduce el eje del CV de la experiencia más reciente y relevante. NUNCA frases de intención ("busco", "me interesa").
- Habilidades en 3-5 categorías con lo que el perfil respalda (herramientas, programas, licencias); no subas niveles declarados.
- Experiencia Laboral en orden cronológico inverso, con 3-5 bullets en las experiencias recientes (2-3 en las antiguas), de 1-2 líneas, con verbo de acción y alcance concreto; usa las cifras que el perfil traiga, sin inventar ninguna. Fechas "AAAA" o "AAAA-MM"; el cargo vigente con end_date "present".
- Educación (también estudios técnicos o congelados, indicándolo), Certificaciones/Cursos e Idiomas/Programas como entradas {"label", "details"} cuando el perfil los tenga; en Certificaciones, "details" solo si el perfil da año o emisor (si no, omite la clave y deja solo "label"). Cada dato va en UNA sola sección: no repitas en Habilidades lo que ya está en Certificaciones (licencias, cursos). Idiomas: omite la sección si el único idioma es el nativo (el CV ya está en ese idioma). Omite toda sección sin respaldo en el perfil y NO incluyas Proyectos si el perfil no tiene.
- El CV es de 1 página y debe quedar bien lleno (≈90% de la altura), sin relleno vacío ni bullets repetidos.
"""


def generar_cv_base(perfil_readme: str, cv_referencia: dict | None = None) -> dict:
    """CV genérico a partir de la documentación, sin oferta: sirve de punto de partida y de
    referencia estructural. Devuelve el bloque `cv` (el diseño lo pone bot/design.py)."""
    data = llm.chat(
        "generar_cv_base",
        con_perfil(
            perfil_readme,
            f"ESQUELETO DE REFERENCIA (solo estructura, no copies su contenido):\n{compacto(esqueleto(cv_referencia or {}))}\n\n"
            f"{_TAREA_CV_BASE}",
        ),
        json_mode=True,
        temperature=0.3,
    )
    cv = data.get("cv") if isinstance(data, dict) else None
    if not isinstance(cv, dict) or not cv.get("sections"):
        raise ValueError("La IA no devolvió un CV válido. Intenta de nuevo.")
    return quitar_proyectos(cv) if "proyecto" not in perfil_readme.lower() else cv


def _pedir_json_completo(mensajes: list[dict], campos_requeridos: list[str], intentos: int = 2) -> dict:
    """El JSON mode de DeepSeek no garantiza que todas las claves pedidas vengan — ya pasó \
que omitió "experiencia_200" completo. Si falta alguna, se piden SOLO las faltantes (no el JSON \
completo de nuevo, que duplicaba el costo de salida) y se combinan."""
    data = llm.chat("generar_cv", mensajes, json_mode=True, temperature=0.3)
    for _ in range(intentos - 1):
        faltantes = [c for c in campos_requeridos if c not in data]
        if not faltantes:
            return data
        extra = llm.chat(
            "generar_cv_faltantes",
            mensajes
            + [
                {"role": "assistant", "content": compacto(data)},
                {"role": "user", "content": f"Faltaron estas claves obligatorias: {', '.join(faltantes)}. Responde un JSON SOLO con ellas."},
            ],
            json_mode=True,
            temperature=0.3,
        )
        data.update({k: v for k, v in extra.items() if k in faltantes})
    return data


def _aplicar_parche(cv: dict, data: dict) -> dict:
    """Combina un parche {"secciones": {...}, "campos": {...}} con el cv original."""
    if not isinstance(data, dict):
        return cv
    nuevo = copy.deepcopy(cv)
    if isinstance(data.get("cv"), dict):  # el modelo devolvió el CV completo igual
        return data["cv"]
    for clave, valor in (data.get("campos") or {}).items():
        if clave != "sections":
            nuevo[clave] = valor
    secciones = nuevo.setdefault("sections", {})
    for nombre, entradas in (data.get("secciones") or {}).items():
        if entradas is None:
            secciones.pop(nombre, None)
        elif isinstance(entradas, list):
            secciones[nombre] = entradas
    return nuevo


def reparar_cv_rendercv(cv: dict, error_rendercv: str) -> dict:
    """rendercv puede rechazar el `cv` por su propio esquema (ej. un campo que espera una \
lista y recibió un diccionario). Como el diseño ya no es parte de lo que el LLM toca, el \
único origen posible de un error de esquema es el contenido — se le pasa el error real de \
vuelta a DeepSeek para que corrija solo eso (como parche)."""
    data = llm.chat(
        "reparar_cv",
        [
            {
                "role": "system",
                "content": (
                    "Eres un experto en el esquema `cv` de rendercv. Se te da un `cv` (JSON) que rendercv "
                    "rechazó y el error exacto. Corrige únicamente lo que el error señala, sin cambiar contenido "
                    "factual. " + _FORMATO_PARCHE
                ),
            },
            {"role": "user", "content": f"CV:\n{compacto(cv)}\n\nERROR DE RENDERCV:\n{error_rendercv[-3000:]}"},
        ],
        json_mode=True,
    )
    return _aplicar_parche(cv, data)


def expandir_a_una_pagina(cv: dict, llenado: float, perfil_readme: str, oferta_texto: str) -> dict:
    """El CV cabe en 1 página pero deja espacio en blanco (`llenado` = fracción de la hoja usada,
    medida en el PDF real). Contrapartida de condensar_a_una_pagina: se le pide al modelo que
    incorpore detalle del PERFIL (nunca inventado) hasta llenar la hoja."""
    libre = max(0, round((0.95 - llenado) * 100))
    lineas = max(2, round((0.94 - llenado) * 60))  # ~60 líneas de texto por hoja
    data = llm.chat(
        "expandir_cv",
        con_perfil(
            perfil_readme,
            f"OFERTA LABORAL:\n{oferta_texto}\n\nCV ACTUAL:\n{compacto(cv)}\n\n"
            f"TAREA: el CV ocupa solo el {round(llenado * 100)}% de la hoja: queda ~{libre}% en blanco. Enriquécelo "
            "con información REAL del perfil, priorizando lo más relevante a la oferta y al tipo de cargo: "
            "1) más bullets (hasta 5-6 en las experiencias principales) con alcance, metodología, herramientas y "
            "cifras que el perfil ya contiene; 2) secciones que el perfil respalde y falten (Idiomas, "
            "Certificaciones, detalle de Educación como distinción o programa; NO agregues Proyectos); 3) detalle "
            "en Habilidades y un Resumen más completo (3-4 líneas) SIN mencionar la empresa ni el cargo ni frases de intención (\"busco aportar\"). No inventes nada (ni habilidades que solo estén en la oferta) ni repitas bullets. Formato por "
            "sección: Habilidades/Idiomas/Certificaciones = entradas {label, details}; Experiencia = "
            "{company, position, location, start_date, end_date, highlights}; Educación = {institution, area, "
            "degree, start_date, end_date, highlights} (sus textos van en highlights, nunca en details). "
            f"Agrega en total ≈{lineas} líneas de texto (un bullet de 2 líneas = 2; una entrada de Idiomas = 1): "
            f"no más, o el CV pasará de 1 página. {_FORMATO_PARCHE}",
        ),
        json_mode=True,
        temperature=0.3,
    )
    return _aplicar_parche(cv, data)


def condensar_a_una_pagina(cv: dict, paginas_actuales: int, exceso: float | None = None) -> dict:
    """El PDF ya renderizó bien pero ocupa más de 1 página. Se verifica mecánicamente (contando páginas del PDF real) y se le pide a DeepSeek que recorte contenido del `cv`. `exceso` = fracción de hoja que desborda a la página siguiente (medida en el PDF): permite pedir un recorte del tamaño justo en vez de "recorta algo"."""
    medida = ""
    if exceso:
        lineas = max(2, round(exceso * 60) + 2)  # ~60 líneas por hoja; +2 de holgura
        medida = f"Desborda ~{lineas} líneas de texto: recorta aproximadamente eso, ni mucho menos ni mucho más. "
    data = llm.chat(
        "condensar_cv",
        [
            {
                "role": "system",
                "content": (
                    f"Eres un editor de CVs. Este `cv` ocupa {paginas_actuales} páginas y debe quedar en 1. {medida}"
                    "Recorta en este orden: 1) bullets redundantes o de roles antiguos/menos relevantes, 2) acorta "
                    "bullets largos a 1-2 líneas, 3) entradas de Proyectos/Certificaciones menos relevantes (NUNCA "
                    "las certificaciones principales del candidato). Conserva Idiomas, Educación y el resumen. "
                    "No inventes ni cambies datos. " + _FORMATO_PARCHE
                ),
            },
            {"role": "user", "content": compacto(cv)},
        ],
        json_mode=True,
        temperature=0.2,
    )
    return _aplicar_parche(cv, data)


def ajustar_cv(cv: dict, instruccion: str, perfil_readme: str, oferta_texto: str) -> dict:
    """Ajuste incremental sobre el `cv` ya generado (a diferencia de generar_contenido con
    feedback, que regenera todo desde cero y puede deshacer cambios que el usuario ya aprobó).
    Devuelve el cv propuesto — la web lo muestra como preview antes de renderizar."""
    data = llm.chat(
        "ajustar_cv",
        con_perfil(
            perfil_readme,
            f"OFERTA LABORAL:\n{oferta_texto}\n\nCV ACTUAL:\n{compacto(cv)}\n\n"
            "TAREA: aplica la instrucción de abajo sobre el CV de forma quirúrgica. Si pide incorporar una "
            "keyword, intégrala con naturalidad SOLO si el perfil la respalda. El CV debe seguir cabiendo en "
            f"1 página: si agregas algo, acorta otra cosa menos relevante. {_FORMATO_PARCHE}\n\n"
            f"INSTRUCCIÓN:\n{instruccion}",
        ),
        json_mode=True,
        temperature=0.2,
    )
    return _aplicar_parche(cv, data)


def recomendaciones_ats(
    keywords_faltantes: list[str], cv: dict, perfil_readme: str, oferta_texto: str
) -> list[dict]:
    """Para cada keyword de la oferta que el ATS no encontró en el PDF, evalúa si el perfil la
    respalda (y cómo incorporarla honestamente) o si es una brecha real. Devuelve
    [{"keyword", "respaldada", "recomendacion"}]."""
    if not keywords_faltantes:
        return []
    data = llm.chat(
        "recomendaciones_ats",
        con_perfil(
            perfil_readme,
            f"OFERTA LABORAL:\n{oferta_texto}\n\nCV ACTUAL:\n{compacto(cv)}\n\n"
            f"KEYWORDS DE LA OFERTA QUE NO APARECEN EN EL CV:\n{compacto(keywords_faltantes)}\n\n"
            'TAREA: responde SOLO un JSON {"recomendaciones": [{"keyword": tal cual, "respaldada": true si el '
            'perfil respalda esa habilidad (directa o con un equivalente honesto), "recomendacion": máx. 2 frases '
            "cortas: dónde y cómo incorporarla con la redacción de la oferta, o por qué es una brecha real y qué "
            "equivalente honesto existe}]}.",
        ),
        json_mode=True,
    )
    recomendaciones = data.get("recomendaciones") if isinstance(data, dict) else None
    if not isinstance(recomendaciones, list):
        return []
    return [
        {
            "keyword": str(r.get("keyword", "")),
            "respaldada": bool(r.get("respaldada")),
            "recomendacion": str(r.get("recomendacion", "")),
        }
        for r in recomendaciones
        if isinstance(r, dict)
    ]


def _recortar(texto: str, limite: int) -> str:
    """El LLM no cuenta caracteres de forma confiable — esto es el candado real.
    Corta en el último espacio antes del límite para no partir una palabra a la mitad."""
    if len(texto) <= limite:
        return texto
    recorte = texto[:limite]
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return recorte.rstrip(",.;: ")
