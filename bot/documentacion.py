"""Gestión de la documentación del perfil (la fuente de verdad para generar CVs): cargar un
CV o una descripción para crearla/enriquecerla, y editar, simplificar o eliminar secciones.
Nada se escribe sin que el usuario vea el diff y lo apruebe, y cada escritura deja un respaldo.

Ahorro de tokens:
- perfil_para_ia(): lo que se manda a la IA excluye las secciones que el usuario marcó como
  "no enviar" (registros, protocolos, notas internas) y normaliza espacios/separadores.
- Las ediciones con IA devuelven SOLO las secciones que cambian (aplicar_cambios), no el
  documento completo: antes cada cambio de una línea costaba reescribir ~16k caracteres."""

import io
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import yaml
from pypdf import PdfReader

from bot import llm
from bot.config import PROJECT_ROOT, README_PATH
from bot.llm import compacto, con_perfil

BACKUP_DIR = PROJECT_ROOT / "backups_readme"


# ---------- lectura / escritura con respaldo ----------

def leer(ruta: Path = README_PATH) -> str:
    return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


def guardar(contenido: str, ruta: Path = README_PATH, backup_dir: Path = BACKUP_DIR) -> str | None:
    """Respalda la versión actual y escribe la nueva. Devuelve el nombre del respaldo."""
    respaldo = None
    if ruta.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        respaldo = f"README_{datetime.now():%Y%m%d_%H%M%S}.md"
        (backup_dir / respaldo).write_text(leer(ruta), encoding="utf-8")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido.rstrip() + "\n", encoding="utf-8")
    return respaldo


def listar_respaldos(backup_dir: Path = BACKUP_DIR) -> list[str]:
    if not backup_dir.exists():
        return []
    return sorted((p.name for p in backup_dir.glob("README_*.md")), reverse=True)


def leer_respaldo(nombre: str, backup_dir: Path = BACKUP_DIR) -> str:
    ruta = (backup_dir / nombre).resolve()
    if ruta.parent != backup_dir.resolve() or not ruta.exists():
        raise FileNotFoundError(nombre)
    return ruta.read_text(encoding="utf-8")


# ---------- secciones ----------

@dataclass
class Seccion:
    indice: int
    nivel: int
    titulo: str
    inicio: int  # línea del header (0-based)
    fin: int     # exclusivo: hasta el próximo header de nivel igual o superior
    contenido: str


_HEADER = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def secciones(contenido: str) -> list[Seccion]:
    """Secciones jerárquicas: un '## X' incluye sus '### hijos'. Ignora '#' dentro de
    bloques de código (ej. comentarios de YAML)."""
    lineas = contenido.splitlines()
    headers = []
    en_codigo = False
    for i, linea in enumerate(lineas):
        if linea.lstrip().startswith("```"):
            en_codigo = not en_codigo
            continue
        m = None if en_codigo else _HEADER.match(linea)
        if m:
            headers.append((i, len(m.group(1)), m.group(2)))

    resultado = []
    for n, (inicio, nivel, titulo) in enumerate(headers):
        fin = len(lineas)
        for inicio_sig, nivel_sig, _ in headers[n + 1:]:
            if nivel_sig <= nivel:
                fin = inicio_sig
                break
        resultado.append(
            Seccion(n, nivel, titulo, inicio, fin, "\n".join(lineas[inicio:fin]).strip("\n"))
        )
    return resultado


def secciones_dict(contenido: str) -> list[dict]:
    return [asdict(s) for s in secciones(contenido)]


def _buscar(contenido: str, indice: int, titulo: str) -> Seccion:
    lista = secciones(contenido)
    if indice >= len(lista) or lista[indice].titulo != titulo:
        raise ValueError("La documentación cambió desde que la cargaste — recarga e intenta de nuevo.")
    return lista[indice]


def _normalizar(contenido: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", contenido).strip() + "\n"


def reemplazar_seccion(contenido: str, indice: int, titulo: str, nuevo_bloque: str) -> str:
    """nuevo_bloque vacío = eliminar la sección (con sus subsecciones)."""
    sec = _buscar(contenido, indice, titulo)
    lineas = contenido.splitlines()
    nuevas = nuevo_bloque.strip("\n").splitlines() if nuevo_bloque.strip() else []
    if nuevas:
        nuevas.append("")  # separación con el próximo header
    return _normalizar("\n".join(lineas[: sec.inicio] + nuevas + lineas[sec.fin:]))


def perfil_para_ia(contenido: str, excluidas: list[str] | None = None) -> str:
    """Versión del documento que se envía a la IA: sin las secciones excluidas (por título,
    con sus subsecciones), sin separadores '---' ni líneas en blanco repetidas."""
    lineas = contenido.splitlines()
    quitar = set()
    for s in secciones(contenido):
        if excluidas and s.titulo in excluidas:
            quitar.update(range(s.inicio, s.fin))
    resultado = [l.rstrip() for i, l in enumerate(lineas) if i not in quitar and l.strip() != "---"]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(resultado)).strip()


def aplicar_cambios(contenido: str, cambios: list[dict]) -> str:
    """Aplica una lista de cambios por sección devuelta por la IA:
    {"titulo": header existente | null, "contenido": markdown completo de la sección (con su header)
    o "" para eliminarla, "despues_de": título tras el cual insertar una sección nueva (opcional)}."""
    for cambio in cambios:
        if not isinstance(cambio, dict):
            continue
        titulo = (cambio.get("titulo") or "").strip().lstrip("#").strip()
        bloque = _sin_fence(str(cambio.get("contenido") or ""))
        actuales = secciones(contenido)
        existente = next((s for s in actuales if s.titulo == titulo), None) if titulo else None
        if existente:
            contenido = reemplazar_seccion(contenido, existente.indice, existente.titulo, bloque)
        elif bloque:
            despues = (cambio.get("despues_de") or "").strip().lstrip("#").strip()
            ancla = next((s for s in actuales if s.titulo == despues), None)
            lineas = contenido.splitlines()
            pos = ancla.fin if ancla else len(lineas)
            contenido = _normalizar("\n".join(lineas[:pos] + ["", *bloque.splitlines(), ""] + lineas[pos:]))
    return contenido


_FORMATO_CAMBIOS = (
    'Responde SOLO un JSON {"cambios": [{"titulo": título EXACTO del header existente a reemplazar '
    '(sin los #) o null si es una sección nueva, "contenido": markdown COMPLETO de la sección resultante '
    'empezando por su header (mismo nivel de #), o "" para eliminarla, "despues_de": solo para secciones '
    "nuevas, título de la sección tras la cual va}]}. Incluye SOLO las secciones que cambian — no repitas "
    "las que quedan igual. Si cambias una subsección (###), reemplaza solo esa, no su sección padre. "
    "Mantén el formato (tablas, bullets). No inventes información."
)


def editar_documento(contenido_actual: str, instruccion: str, datos_extra: str = "", operacion: str = "editar_documento") -> str:
    """Edición global por instrucción en lenguaje natural. Devuelve el documento completo
    resultante (sin guardar), pero la IA solo escribe las secciones que cambian."""
    data = llm.chat(
        operacion,
        [
            {
                "role": "system",
                "content": "Mantienes el documento de perfil profesional (markdown) de un candidato, fuente de verdad "
                "para generar CVs. Si la instrucción menciona una certificación aprobada, actualízala en TODAS las "
                "secciones donde aparezca como agendada/pendiente. " + _FORMATO_CAMBIOS,
            },
            {
                "role": "user",
                "content": f"DOCUMENTO ACTUAL:\n{contenido_actual}\n\n{datos_extra}INSTRUCCIÓN:\n{instruccion}",
            },
        ],
        json_mode=True,
    )
    cambios = data.get("cambios") if isinstance(data, dict) else None
    return aplicar_cambios(contenido_actual, cambios if isinstance(cambios, list) else [])


_ACCIONES_IA = {
    "simplificar": (
        "Simplifica esta sección: más corta y directa, sin redundancias ni relleno, conservando TODOS "
        "los datos factuales relevantes (cifras, fechas, stack, logros)."
    ),
    "reescribir": (
        "Reescribe esta sección para que sea más clara y útil como fuente de verdad para generar CVs: "
        "bullets concretos, logros con números, stack explícito. Sin inventar nada."
    ),
    "modificar": "Aplica la instrucción del usuario sobre esta sección.",
}


def editar_seccion_ia(contenido: str, indice: int, titulo: str, accion: str, instruccion: str = "") -> str:
    """Devuelve el documento completo con la sección editada por IA (sin guardar). Solo se
    envía la sección, no el documento entero."""
    if accion not in _ACCIONES_IA:
        raise ValueError(f"Acción desconocida: {accion}")
    sec = _buscar(contenido, indice, titulo)
    tarea = _ACCIONES_IA[accion]
    if instruccion.strip():
        tarea += f"\n\nINSTRUCCIÓN DEL USUARIO:\n{instruccion.strip()}"
    nuevo = llm.chat(
        f"seccion_{accion}",
        [
            {
                "role": "system",
                "content": "Editas UNA sección del documento de perfil profesional de un candidato (markdown). "
                "Responde SOLO con el markdown crudo de la sección resultante — empezando por su mismo header "
                "(mismo nivel de #), sin bloques ``` y sin comentarios. Mantén el formato. No inventes información.",
            },
            {"role": "user", "content": f"TAREA:\n{tarea}\n\nSECCIÓN ACTUAL:\n{sec.contenido}"},
        ],
        temperature=0.2,
    )
    return reemplazar_seccion(contenido, indice, titulo, _sin_fence(nuevo))


# ---------- carga de CV / onboarding ----------

def extraer_texto_cv(nombre_archivo: str, datos: bytes) -> str:
    ext = nombre_archivo.lower().rsplit(".", 1)[-1] if "." in nombre_archivo else ""
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(datos))
        texto = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif ext == "docx":
        from docx import Document

        doc = Document(io.BytesIO(datos))
        partes = [p.text for p in doc.paragraphs]
        for tabla in doc.tables:
            for fila in tabla.rows:
                partes.append(" | ".join(c.text for c in fila.cells))
        texto = "\n".join(partes)
    elif ext in ("yaml", "yml"):
        data = yaml.safe_load(datos.decode("utf-8"))
        cv = data.get("cv", data) if isinstance(data, dict) else data
        texto = compacto(cv)
    elif ext in ("txt", "md", "markdown", "json"):
        texto = datos.decode("utf-8", errors="replace")
    else:
        raise ValueError("Formato no soportado. Usa PDF, DOCX, YAML (rendercv), TXT o MD.")
    # Menos tokens: colapsa espacios y líneas vacías que dejan los extractores de PDF/DOCX.
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto).strip()
    if len(texto) < 100:
        raise ValueError(
            "Se extrajo muy poco texto del archivo — si es un PDF escaneado (imagen), "
            "conviértelo a texto o sube el DOCX/YAML."
        )
    return texto


_PROMPT_NUEVO = """\
Crea el documento de perfil profesional (markdown) de un candidato a partir de su CV y/o la \
descripción que escribió. Será la fuente de verdad para generar CVs adaptados a cada oferta, \
así que debe ser factual, completo y conciso (bullets, sin prosa de relleno). Estructura:

# Perfil profesional — <nombre>
## Perfil consolidado  (tabla | Campo | Valor | con nombre, email, teléfono, ubicación, años de \
experiencia, título/egreso, rol objetivo, idiomas, certificaciones)
## Preferencias de búsqueda  (roles objetivo y roles que NO busca, modalidad, ubicación, pretensión \
salarial — si no hay datos, "⚠️ Por completar")
## Experiencia  (un ### por cargo: "Cargo — Empresa (fechas)", **Stack:**, **Logros:** con todas las cifras)
## Educación
## Certificaciones
## Proyectos / Portafolio  (solo si hay)
## Idiomas

No inventes nada que no esté en el CV o la descripción. Si la descripción contradice al CV, usa la \
descripción (es más reciente) y márcalo con "⚠️ revisar". Responde SOLO con el markdown, sin ``` ni comentarios."""


def crear_documentacion(texto_cv: str = "", descripcion: str = "") -> str:
    """Onboarding / modo 'reemplazar': crea una documentación nueva (no guarda)."""
    partes = []
    if texto_cv.strip():
        partes.append(f"CV:\n{texto_cv.strip()}")
    if descripcion.strip():
        partes.append(f"DESCRIPCIÓN DEL CANDIDATO:\n{descripcion.strip()}")
    if not partes:
        raise ValueError("Carga un CV o escribe una descripción.")
    texto = llm.chat(
        "crear_documentacion",
        [{"role": "system", "content": _PROMPT_NUEVO}, {"role": "user", "content": "\n\n".join(partes)}],
    )
    return _sin_fence(texto) + "\n"


def cv_a_documentacion(texto_cv: str, documentacion_actual: str, modo: str) -> str:
    """modo: 'fusionar' (agrega lo nuevo a la documentación actual, solo las secciones que
    cambian) o 'reemplazar' (documentación nueva solo desde el CV). No guarda."""
    if modo != "fusionar" or not documentacion_actual.strip():
        return crear_documentacion(texto_cv)
    return editar_documento(
        documentacion_actual,
        "Integra en el documento la información del CV cargado que NO esté ya documentada (experiencias, "
        "logros con cifras, stack, certificaciones, educación, idiomas, datos de contacto). No elimines "
        "información existente: si el CV contradice algo, conserva lo del documento y agrega al lado "
        '"⚠️ Discrepancia con CV cargado: ..." para que el usuario decida.',
        datos_extra=f"CV CARGADO:\n{texto_cv}\n\n",
        operacion="fusionar_cv",
    )


# ---------- sugerencias a partir de una oferta ----------

def sugerencias_desde_oferta(perfil: str, oferta_texto: str, faltantes: list[str]) -> list[dict]:
    """Qué le falta o sobra a la documentación para calzar mejor con este tipo de oferta —
    formulado como instrucciones que el usuario confirma. Usa el mismo prefijo (perfil +
    oferta) que el resto de llamadas de la postulación, así que casi todo el input sale de caché."""
    data = llm.chat(
        "sugerencias_documentacion",
        con_perfil(
            perfil,
            f"OFERTA LABORAL:\n{oferta_texto}\n\n"
            f"KEYWORDS DE LA OFERTA QUE NO APARECIERON EN EL CV:\n{compacto(faltantes)}\n\n"
            "TAREA: propón 3 a 5 mejoras AL DOCUMENTO DE PERFIL (no al CV) para que futuros CVs calcen mejor "
            "con ofertas de este tipo: experiencia o stack poco documentado, logros sin cifras, secciones "
            "ruidosas para simplificar, información obsoleta para eliminar. Si no está documentado, formúlalo "
            'como pregunta. Sé breve. Responde SOLO un JSON {"sugerencias": [{"titulo": máx. 8 palabras, "tipo": '
            '"agregar"|"modificar"|"simplificar"|"eliminar", "detalle": máx. 20 palabras, "instruccion": máx. 40 '
            "palabras, lista para aplicar, con [COMPLETAR] donde el usuario deba aportar datos}]}.",
        ),
        json_mode=True,
        temperature=0.2,
    )
    lista = data.get("sugerencias") if isinstance(data, dict) else None
    if not isinstance(lista, list):
        return []
    return [
        {k: str(s.get(k, "")) for k in ("titulo", "tipo", "detalle", "instruccion")}
        for s in lista
        if isinstance(s, dict)
    ]


def _sin_fence(texto: str) -> str:
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.split("\n", 1)[1] if "\n" in texto else ""
        if texto.rstrip().endswith("```"):
            texto = texto.rstrip()[:-3]
    return texto.strip()


def estimar_tokens(texto: str) -> int:
    """Estimación rápida para mostrar en la UI (~3.5 caracteres por token en español)."""
    return round(len(texto) / 3.5)

