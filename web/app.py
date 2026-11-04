"""Versión web del bot de postulaciones (multiusuario).

Mismo pipeline que el bot de Telegram (bot/), expuesto como API + una SPA en React:
- Cuentas: usuario/contraseña, recuperación por correo (si hay SMTP), onboarding inicial.
- Documentación: la fuente de verdad del perfil, cargable desde un CV o una descripción y
  editable por secciones (manual o con IA), siempre con diff + aprobación + respaldo.
- Postulaciones: pegar JD → clasificar con Jev → generar CV en PDF con rendercv + comentarios
  → chequeo ATS → ajustes con PREVIEW antes de renderizar → aprobar/descartar.
- Consumo: cada llamada a la IA queda registrada (tokens, aciertos de caché, latencia).

Datos en Postgres y archivos en Supabase Storage (ver supabase/migrations y web/storage.py).
Local: python -m web (http://127.0.0.1:8000). Producción: Vercel (api/index.py + vercel.json)."""

import difflib
import logging
import re
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bot import ats_check, documentacion, llm
from bot.classifier import clasificar
from bot.config import CLASSIFIER_PROVIDER, DEEPSEEK_MODEL
from bot.deepseek_client import ajustar_cv, generar_contenido, generar_cv_base, pide_proyectos, recomendaciones_ats
from bot.graph import _sanear_cv as sanear_cv, renderizar_cv
from web import cuentas, jobs, storage, store
from web.cuentas import Usuario

_AQUI = Path(__file__).resolve().parent
_STATIC = _AQUI / "static"
_CV_PRUEBA = _AQUI / "cv_prueba.md"
_MAX_VERSIONES = 15
_COOKIE = "sesion"

# Sin /docs ni /openapi.json: con la web pública no hace falta publicar el mapa de la API.
app = FastAPI(title="Postulaciones", docs_url=None, redoc_url=None, openapi_url=None)

def _ip(request: Request) -> str:
    # Detrás de Vercel/proxies la IP real viene en X-Forwarded-For (primer valor).
    reenviada = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return reenviada or (request.client.host if request.client else "?")


def _limitar(request: Request, accion: str) -> None:
    espera = cuentas.limitar(accion, _ip(request))
    if espera is not None:
        raise HTTPException(429, f"Demasiados intentos. Espera {espera} minutos.")


@app.exception_handler(storage.StorageError)
def _error_storage(request: Request, e: storage.StorageError):
    logging.getLogger(__name__).error("Storage: %s", e)
    return JSONResponse({"detail": "No se pudo acceder al almacenamiento de archivos."}, status_code=502)


# ---------- autenticación ----------

@app.middleware("http")
async def _sesion(request: Request, call_next):
    """Resuelve el usuario de la cookie y lo deja en el contextvar de bot.llm, para que el
    consumo de cada llamada a la IA quede atribuido a quien la hizo."""
    es_api = request.url.path.startswith("/api/")
    usuario = cuentas.usuario_de_sesion(request.cookies.get(_COOKIE)) if es_api else None
    request.state.usuario = usuario
    token = llm.usuario_actual.set(usuario.id if usuario else None)
    try:
        if es_api and not request.url.path.startswith(("/api/auth/", "/api/internal/")) and usuario is None:
            return JSONResponse({"detail": "No autenticado"}, status_code=401)
        return await call_next(request)
    finally:
        llm.usuario_actual.reset(token)


def actual(request: Request) -> Usuario:
    if request.state.usuario is None:
        raise HTTPException(401, "No autenticado")
    return request.state.usuario


def _set_cookie(request: Request, response: Response, token: str) -> None:
    # Secure solo si la conexión llegó por https (Vercel); en http://127.0.0.1 el navegador la descartaría.
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    response.set_cookie(
        _COOKIE, token, httponly=True, samesite="lax", max_age=int(cuentas.DURACION_SESION.total_seconds()), secure=https,
    )


class Registro(BaseModel):
    username: str
    password: str
    nombre: str
    email: str | None = None
    codigo: str | None = None


class Login(BaseModel):
    username: str
    password: str


class Olvide(BaseModel):
    usuario: str


class Reset(BaseModel):
    token: str
    password: str


class CambioPassword(BaseModel):
    actual: str
    nueva: str


@app.get("/api/auth/estado")
def auth_estado(request: Request):
    primer = not cuentas.hay_usuarios()
    return {
        "usuario": request.state.usuario.publico() if request.state.usuario else None,
        "smtp": cuentas.smtp_configurado(),
        "registro": primer or cuentas.PERMITIR_REGISTRO,
        "primer_usuario": primer,
        "requiere_codigo": bool(cuentas.CODIGO_INVITACION),
    }


@app.post("/api/auth/registro")
def auth_registro(body: Registro, request: Request, response: Response):
    _limitar(request, "registro")
    try:
        u = cuentas.registrar(body.username, body.password, body.nombre, body.email, body.codigo)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _set_cookie(request, response, cuentas.crear_sesion(u.id))
    return u.publico()


@app.post("/api/auth/login")
def auth_login(body: Login, request: Request, response: Response):
    _limitar(request, "login")
    u = cuentas.autenticar(body.username, body.password)
    if u is None:
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    _set_cookie(request, response, cuentas.crear_sesion(u.id))
    return u.publico()


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    cuentas.cerrar_sesion(request.cookies.get(_COOKIE))
    response.delete_cookie(_COOKIE)
    return {"ok": True}


@app.post("/api/auth/olvide")
def auth_olvide(body: Olvide, request: Request):
    _limitar(request, "olvide")
    try:
        cuentas.solicitar_reset(body.usuario)
    except RuntimeError as e:
        raise HTTPException(501, str(e))
    return {"ok": True, "mensaje": "Si el usuario existe y tiene email, te enviamos un link para recuperar la contraseña."}


@app.post("/api/auth/reset")
def auth_reset(body: Reset, request: Request):
    _limitar(request, "reset")
    try:
        cuentas.confirmar_reset(body.token, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/cuenta/password")
def cuenta_password(body: CambioPassword, request: Request, response: Response, u: Usuario = Depends(actual)):
    try:
        cuentas.cambiar_password(u.id, body.actual, body.nueva)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _set_cookie(request, response, cuentas.crear_sesion(u.id))  # se cerraron todas las sesiones: abre una nueva
    return {"ok": True}


class Preferencias(BaseModel):
    nombre_archivo: str | None = None
    piso_salarial: str | None = None
    modalidad: str | None = None
    angulos: dict[str, str] | None = None
    email: str | None = None


@app.post("/api/cuenta/preferencias")
def cuenta_preferencias(body: Preferencias, u: Usuario = Depends(actual)):
    config = dict(u.config)
    for campo in ("nombre_archivo", "piso_salarial", "modalidad"):
        valor = getattr(body, campo)
        if valor is not None:
            config[campo] = valor.strip()
    if body.angulos is not None:
        angulos = {re.sub(r"[^A-Za-z0-9_]", "", k)[:12]: v.strip() for k, v in body.angulos.items() if k.strip() and v.strip()}
        angulos.pop("", None)
        if not angulos:
            raise HTTPException(400, "Define al menos un ángulo de CV.")
        config["angulos"] = angulos
    campos = {"config": config}
    if body.email is not None:
        campos["email"] = body.email.strip() or None
    return cuentas.actualizar(u.id, **campos).publico()


# ---------- helpers ----------

def _nombre_archivo(texto: str) -> str:
    """Mismo saneado que el bot: nombre de empresa apto para nombres de archivo."""
    limpio = re.sub(r"[^A-Za-z0-9]+", "", texto)
    return limpio[:40] or "SinNombre"


def _diff(antes: str, despues: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            antes.splitlines(), despues.splitlines(), fromfile="actual", tofile="propuesto", lineterm=""
        )
    )


def _propuesta(antes: str, despues: str) -> dict:
    return {"propuesto": despues, "diff": _diff(antes, despues), "sin_cambios": antes.strip() == despues.strip()}


def _yaml(cv: dict) -> str:
    return yaml.dump(cv, allow_unicode=True, sort_keys=False, width=1000)


def _cargar(u: Usuario, pid: int) -> dict:
    p = store.obtener(u.id, pid)
    if p is None:
        raise HTTPException(404, "Postulación no encontrada")
    return p


def _datos(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in ("id", "empresa", "estado", "creado_en", "actualizado_en")}


def _publica(p: dict) -> dict:
    """Lo que ve el frontend: sin el historial completo de versiones del CV (pesado)."""
    salida = {k: v for k, v in p.items() if k != "versiones"}
    salida["n_versiones"] = len(p.get("versiones", []))
    salida["cv_yaml"] = _yaml(p["cv"]) if p.get("cv") else None
    return salida


def _apilar_version(datos: dict) -> None:
    if datos.get("cv"):
        versiones = datos.setdefault("versiones", [])
        versiones.append({"cv": datos["cv"], "ats_cobertura": datos.get("ats_cobertura")})
        datos["versiones"] = versiones[-_MAX_VERSIONES:]


def _aplicar_render(u: Usuario, p: dict, cv: dict, accion: str, apilar: bool = True) -> dict:
    """Renderiza un `cv`, re-mide ATS con las keywords originales de la oferta y guarda la
    versión anterior para poder deshacer."""
    cv_final, yaml_content, pdf_local, paginas = renderizar_cv(cv, p["angulo"], p["empresa"], **u.destino_render)
    ats = ats_check.evaluar(pdf_local, p.get("ats_keywords", []))
    pdf_path = u.subir_pdf(pdf_local)  # clave en Storage
    datos = _datos(p)
    if apilar:
        _apilar_version(datos)
    datos.update(
        cv=cv_final,
        yaml_content=yaml_content,
        pdf_path=pdf_path,
        paginas=paginas,
        ats_parseo_ok=ats.parseo_ok,
        ats_detalle_parseo=ats.detalle_parseo,
        ats_cobertura=ats.cobertura,
        ats_keywords_presentes=ats.keywords_presentes,
        ats_keywords_faltantes=ats.keywords_faltantes,
        ats_recomendaciones=None,  # quedaron obsoletas con el CV nuevo
    )
    datos.setdefault("historial", []).append({"accion": accion, "ats_cobertura": ats.cobertura, "paginas": paginas})
    store.guardar(u.id, p["id"], "generado", datos)
    return _publica(_cargar(u, p["id"]))


# ---------- página ----------

@app.get("/")
def index():
    if not (_STATIC / "index.html").exists():
        raise HTTPException(503, "Falta compilar el frontend: cd web/frontend && npm install && npm run build")
    return FileResponse(_STATIC / "index.html")


@app.get("/api/config")
def config(u: Usuario = Depends(actual)):
    return {"classifier_provider": CLASSIFIER_PROVIDER, "modelo": DEEPSEEK_MODEL}


@app.get("/api/uso")
def uso(dias: int = 30, u: Usuario = Depends(actual)):
    return llm.resumen_uso(u.id, dias)


# ---------- onboarding ----------

class CompletarOnboarding(BaseModel):
    contenido: str
    preferencias: Preferencias


@app.get("/api/onboarding/cv-prueba")
def onboarding_cv_prueba(u: Usuario = Depends(actual)):
    return {"texto": _CV_PRUEBA.read_text(encoding="utf-8")}


@app.post("/api/onboarding/documentacion")
def onboarding_documentacion(
    archivo: UploadFile | None = File(None),
    usar_prueba: bool = Form(False),
    descripcion: str = Form(""),
    u: Usuario = Depends(actual),
):
    texto_cv = ""
    if archivo is not None and archivo.filename:
        try:
            texto_cv = documentacion.extraer_texto_cv(archivo.filename, archivo.file.read())
        except ValueError as e:
            raise HTTPException(400, str(e))
    elif usar_prueba:
        texto_cv = _CV_PRUEBA.read_text(encoding="utf-8")
    try:
        propuesto = documentacion.crear_documentacion(texto_cv, descripcion)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"propuesto": propuesto, "caracteres_extraidos": len(texto_cv)}


@app.post("/api/onboarding/completar")
def onboarding_completar(body: CompletarOnboarding, u: Usuario = Depends(actual)):
    if not body.contenido.strip():
        raise HTTPException(400, "La documentación no puede quedar vacía.")
    u.guardar_doc(body.contenido)
    cuenta_preferencias(body.preferencias, u)
    return cuentas.actualizar(u.id, onboarding_completo=True).publico()


# ---------- documentación ----------

class Instruccion(BaseModel):
    instruccion: str


class AccionSeccion(BaseModel):
    indice: int
    titulo: str
    accion: str  # simplificar | reescribir | modificar | eliminar | editar
    instruccion: str = ""
    contenido: str = ""  # para "editar" (edición manual)


class Contenido(BaseModel):
    contenido: str


class Exclusion(BaseModel):
    titulo: str
    excluir: bool


def _docs(u: Usuario) -> dict:
    contenido = u.leer_doc()
    perfil = documentacion.perfil_para_ia(contenido, u.excluidas_ia)
    return {
        "contenido": contenido,
        "secciones": documentacion.secciones_dict(contenido),
        "respaldos": u.listar_respaldos(),
        "excluidas_ia": u.excluidas_ia,
        "caracteres_total": len(contenido),
        "caracteres_ia": len(perfil),
        "tokens_ia": documentacion.estimar_tokens(perfil),
    }


@app.get("/api/docs")
def docs_obtener(u: Usuario = Depends(actual)):
    return _docs(u)


@app.post("/api/docs/excluir")
def docs_excluir(body: Exclusion, u: Usuario = Depends(actual)):
    """Marca/desmarca una sección para no enviarla a la IA (ahorra tokens en cada llamada)."""
    excluidas = [t for t in u.excluidas_ia if t != body.titulo]
    if body.excluir:
        excluidas.append(body.titulo)
    u = cuentas.actualizar(u.id, config={**u.config, "excluidas_ia": excluidas})
    return _docs(u)


@app.post("/api/docs/upload")
def docs_cargar_cv(archivo: UploadFile = File(...), modo: str = Form("fusionar"), u: Usuario = Depends(actual)):
    try:
        texto = documentacion.extraer_texto_cv(archivo.filename or "", archivo.file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    actual_doc = u.leer_doc()
    propuesto = documentacion.cv_a_documentacion(texto, actual_doc, modo)
    return {**_propuesta(actual_doc, propuesto), "caracteres_extraidos": len(texto)}


@app.post("/api/docs/instruccion")
def docs_instruccion(body: Instruccion, u: Usuario = Depends(actual)):
    actual_doc = u.leer_doc()
    return _propuesta(actual_doc, documentacion.editar_documento(actual_doc, body.instruccion))


@app.post("/api/docs/seccion")
def docs_seccion(body: AccionSeccion, u: Usuario = Depends(actual)):
    actual_doc = u.leer_doc()
    try:
        if body.accion == "eliminar":
            propuesto = documentacion.reemplazar_seccion(actual_doc, body.indice, body.titulo, "")
        elif body.accion == "editar":
            propuesto = documentacion.reemplazar_seccion(actual_doc, body.indice, body.titulo, body.contenido)
        else:
            propuesto = documentacion.editar_seccion_ia(
                actual_doc, body.indice, body.titulo, body.accion, body.instruccion
            )
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _propuesta(actual_doc, propuesto)


@app.post("/api/docs/diff")
def docs_diff(body: Contenido, u: Usuario = Depends(actual)):
    """Diff de una propuesta armada en el cliente (edición manual completa, restaurar respaldo)."""
    return _propuesta(u.leer_doc(), body.contenido)


@app.post("/api/docs/guardar")
def docs_guardar(body: Contenido, u: Usuario = Depends(actual)):
    if not body.contenido.strip():
        raise HTTPException(400, "La documentación no puede quedar vacía.")
    respaldo = u.guardar_doc(body.contenido)
    return {**_docs(u), "respaldo": respaldo}


@app.get("/api/docs/respaldos/{nombre}")
def docs_respaldo(nombre: str, u: Usuario = Depends(actual)):
    try:
        return {"contenido": u.leer_respaldo(nombre)}
    except FileNotFoundError:
        raise HTTPException(404, "Respaldo no encontrado")


_EMPRESA_CV_BASE = "CVBase"  # nombre reservado del render: los PDFs salen como <prefijo>_CVBase_CV.pdf


class CvBase(BaseModel):
    angulo: str | None = None


class CvBaseYaml(CvBase):
    cv_yaml: str


def _clave_pdf_cv_base(u: Usuario) -> str:
    return u.clave("procesados", f"{u.prefijo_pdf}_{_EMPRESA_CV_BASE}_CV.pdf")


def _clave_yaml_cv_base(u: Usuario) -> str:
    return u.clave("cv_base.yaml")


def _estado_cv_base(u: Usuario, **extra) -> dict:
    datos = storage.descargar(_clave_yaml_cv_base(u))
    return {
        "cv_yaml": datos.decode("utf-8") if datos is not None else None,
        "version": storage.modificado(_clave_pdf_cv_base(u)),
        **extra,
    }


@app.get("/api/docs/cv-base")
def docs_cv_base_obtener(u: Usuario = Depends(actual)):
    """El CV base vigente (YAML guardado + si ya tiene PDF)."""
    return _estado_cv_base(u)


@app.post("/api/docs/cv-base/borrador")
def docs_cv_base_borrador(body: CvBase, u: Usuario = Depends(actual)):
    """La IA arma un borrador del CV base desde la documentación. NO renderiza ni guarda: el
    usuario lo revisa/edita como YAML y recién ahí lo renderiza (/render)."""
    perfil = u.perfil_ia()
    if not perfil.strip():
        raise HTTPException(400, "Primero completa tu documentación de perfil.")
    angulos = u.preferencias.angulos_o_default()
    angulo = body.angulo or next(iter(angulos))
    if angulo not in angulos:
        raise HTTPException(400, "Ángulo inválido")
    try:
        cv = generar_cv_base(perfil, store.referencia_cv(u.id, angulo))
    except ValueError as e:
        raise HTTPException(502, str(e))
    cv = sanear_cv(cv)
    actual_yaml = _estado_cv_base(u)["cv_yaml"] or ""
    nuevo = _yaml(cv)
    return {"cv_yaml": nuevo, "angulo": angulo, "diff": _diff(actual_yaml, nuevo) if actual_yaml else ""}


@app.post("/api/docs/cv-base/render")
def docs_cv_base_render(body: CvBaseYaml, u: Usuario = Depends(actual)):
    """Renderiza el YAML confirmado a PDF y lo guarda como el CV base vigente."""
    try:
        cv = yaml.safe_load(body.cv_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"YAML inválido: {e}")
    if not isinstance(cv, dict) or not isinstance(cv.get("sections"), dict):
        raise HTTPException(400, "El YAML debe ser el objeto `cv` (name, sections, ...).")
    angulos = u.preferencias.angulos_o_default()
    angulo = body.angulo if body.angulo in angulos else next(iter(angulos))
    try:
        cv, _, pdf_local, paginas = renderizar_cv(cv, angulo, _EMPRESA_CV_BASE, **u.destino_render)
    except RuntimeError as e:
        raise HTTPException(400, f"rendercv rechazó el CV:\n{e}")
    storage.subir(_clave_pdf_cv_base(u), Path(pdf_local).read_bytes(), "application/pdf")
    storage.subir(_clave_yaml_cv_base(u), _yaml(cv).encode("utf-8"), "text/yaml; charset=utf-8")
    return _estado_cv_base(u, paginas=paginas)


def _pdf_response(clave: str, nombre: str, descargar: bool) -> Response:
    datos = storage.descargar(clave)
    if datos is None:
        raise HTTPException(404, "Aún no hay PDF")
    return Response(
        datos,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{"attachment" if descargar else "inline"}; filename="{nombre}"'},
    )


@app.get("/api/docs/cv-base/pdf")
def docs_cv_base_pdf(descargar: bool = False, u: Usuario = Depends(actual)):
    clave = _clave_pdf_cv_base(u)
    return _pdf_response(clave, clave.rpartition("/")[2], descargar)


# ---------- postulaciones ----------

class NuevaPostulacion(BaseModel):
    empresa: str
    oferta_texto: str


class Generar(BaseModel):
    feedback: str | None = None


class CvYaml(BaseModel):
    cv_yaml: str
    accion: str | None = None  # descripción para el historial (ej. "Ajuste IA: ...")


class Decision(BaseModel):
    accion: str  # aprobar | descartar


class Angulo(BaseModel):
    angulo: str


@app.get("/api/postulaciones")
def postulaciones_listar(u: Usuario = Depends(actual)):
    return store.listar(u.id)


@app.post("/api/postulaciones")
def postulaciones_crear(body: NuevaPostulacion, u: Usuario = Depends(actual)):
    """Pasos 1-3: pegar JD, analizar con Jev, clasificar postular/descartar."""
    if len(body.oferta_texto.strip()) < 50:
        raise HTTPException(400, "Pega el texto completo de la oferta.")
    perfil = u.perfil_ia()
    if not perfil.strip():
        raise HTTPException(400, "Primero completa tu documentación de perfil.")
    empresa = _nombre_archivo(body.empresa)
    resultado = clasificar(body.oferta_texto.strip(), perfil, u.preferencias)
    datos = {
        "empresa_original": body.empresa,
        "oferta_texto": body.oferta_texto.strip(),
        "clasificador": CLASSIFIER_PROVIDER,
        "fit_score": resultado.fit_score,
        "cumple_excluyentes": resultado.cumple_excluyentes,
        "banda_salarial_ok": resultado.banda_salarial_ok,
        "modalidad_ok": resultado.modalidad_ok,
        "angulo": resultado.angulo,
        "recomendacion": resultado.recomendacion,
        "razones": resultado.razones,
    }
    estado = "analizado" if resultado.recomendacion == "postular" else "descartado"
    pid = store.crear(u.id, empresa, estado, datos)
    return _publica(_cargar(u, pid))


@app.get("/api/postulaciones/{pid}")
def postulaciones_obtener(pid: int, u: Usuario = Depends(actual)):
    return _publica(_cargar(u, pid))


@app.delete("/api/postulaciones/{pid}")
def postulaciones_eliminar(pid: int, u: Usuario = Depends(actual)):
    p = _cargar(u, pid)
    store.eliminar(u.id, pid)
    if (p.get("pdf_path") or "").startswith(u.clave("procesados") + "/"):
        storage.eliminar([p["pdf_path"]])
    return {"ok": True}


@app.post("/api/postulaciones/{pid}/angulo")
def postulaciones_angulo(pid: int, body: Angulo, u: Usuario = Depends(actual)):
    p = _cargar(u, pid)
    if body.angulo not in u.preferencias.angulos_o_default():
        raise HTTPException(400, "Ángulo inválido")
    datos = _datos(p)
    datos["angulo"] = body.angulo
    store.guardar(u.id, pid, p["estado"], datos)
    return _publica(_cargar(u, pid))


def _generar_cv(u: Usuario, p: dict, feedback: str | None, etapa=lambda texto: None) -> None:
    """Paso 4: generar CV completo (desde cero) + comentarios para el portal + ATS, y guardarlo en la
    postulación. Es lento (varias llamadas a IA + renders), por eso corre en un job (ver /generar).
    Se puede forzar aunque la recomendación sea 'descartar' (excepción consciente)."""
    destino = u.destino_render
    etapa("Generando el contenido con IA")
    contenido = generar_contenido(
        oferta_texto=p["oferta_texto"],
        perfil_readme=u.perfil_ia(),
        cv_referencia=store.referencia_cv(u.id, p["angulo"]),
        empresa=p["empresa"],
        feedback_usuario=feedback,
    )
    etapa("Renderizando y ajustando a 1 página")
    try:
        cv, yaml_content, pdf_local, paginas = renderizar_cv(
            contenido.cv, p["angulo"], p["empresa"], perfil=u.perfil_ia(), oferta=p["oferta_texto"],
            proyectos=pide_proyectos(feedback), **destino
        )
    except RuntimeError as e:
        raise RuntimeError(f"rendercv falló tras 3 intentos de reparación:\n{e}")
    etapa("Chequeo ATS y guardado")
    ats = ats_check.evaluar(pdf_local, contenido.keywords_ats)
    pdf_path = u.subir_pdf(pdf_local)  # clave en Storage
    datos = _datos(p)
    _apilar_version(datos)
    datos.update(
        cv=cv,
        yaml_content=yaml_content,
        banda_salarial=contenido.banda_salarial,
        experiencia_200=contenido.experiencia_200,
        habilidades_200=contenido.habilidades_200,
        pretension_renta=contenido.pretension_renta,
        disponibilidad=contenido.disponibilidad,
        modalidad_preferida=contenido.modalidad_preferida,
        pdf_path=pdf_path,
        paginas=paginas,
        ats_keywords=contenido.keywords_ats,
        ats_parseo_ok=ats.parseo_ok,
        ats_detalle_parseo=ats.detalle_parseo,
        ats_cobertura=ats.cobertura,
        ats_keywords_presentes=ats.keywords_presentes,
        ats_keywords_faltantes=ats.keywords_faltantes,
        ats_recomendaciones=None,
    )
    datos.setdefault("historial", []).append(
        {"accion": "Regenerado con feedback: " + feedback if feedback else "CV generado",
         "ats_cobertura": ats.cobertura, "paginas": paginas}
    )
    store.guardar(u.id, p["id"], "generado", datos)


def _base_url(request: Request) -> str:
    """URL pública desde la que se llama al worker (tras el proxy de Vercel usa los headers reenviados)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host.split(',')[0].strip()}"


@app.post("/api/postulaciones/{pid}/generar", status_code=202)
def postulaciones_generar(pid: int, body: Generar, request: Request, u: Usuario = Depends(actual)):
    """Encola la generación y responde al tiro; el avance y el aviso final salen de GET /api/jobs.
    Si ya hay una generación en curso para esta postulación, devuelve esa (no duplica el costo)."""
    p = _cargar(u, pid)
    if not u.perfil_ia().strip():
        raise HTTPException(400, "Primero completa tu documentación de perfil.")
    job, nuevo = jobs.encolar(u.id, p["id"], {"feedback": body.feedback})
    if nuevo:
        jobs.despachar(_base_url(request), job["id"])
    return {"job": {**job, "empresa": p["empresa"]}}


def _mensaje_error(e: Exception) -> str:
    if isinstance(e, HTTPException):
        return str(e.detail)[:600]
    if isinstance(e, RuntimeError):
        return str(e)[:600]
    return f"Error inesperado ({type(e).__name__}): {str(e)[:300]}"


@app.post("/api/internal/jobs/{job_id}/ejecutar")
def jobs_ejecutar(job_id: int, x_job_token: str | None = Header(None)):
    """Worker: lo invoca el propio servidor (firmado con HMAC), no el navegador. Corre en su propia
    invocación de la función, así que tiene su propio límite de duración."""
    if not jobs.token_valido(job_id, x_job_token):
        raise HTTPException(403, "Token inválido")
    job = jobs.reclamar(job_id)
    if job is None:  # ya lo tomó otro worker o terminó
        return {"ok": True, "ignorado": True}
    u = cuentas.obtener(job["user_id"])
    token_uso = llm.usuario_actual.set(job["user_id"])  # atribuye el consumo de IA al usuario
    p = None
    try:
        p = store.obtener(job["user_id"], job["postulacion_id"])
        if u is None or p is None:
            raise RuntimeError("La postulación o el usuario ya no existen.")
        with jobs.Latido(job_id):
            _generar_cv(u, p, (job["params"] or {}).get("feedback"), lambda texto: jobs.etapa(job_id, texto))
        jobs.terminar(job_id)
        error = None
    except Exception as e:
        logging.getLogger(__name__).exception("job %s falló", job_id)
        error = _mensaje_error(e)
        jobs.terminar(job_id, error)
    finally:
        llm.usuario_actual.reset(token_uso)
    if u is not None and p is not None:
        cuentas.avisar(
            u,
            f"CV de {p['empresa']}: {'no se pudo generar' if error else 'listo'}",
            f"Hola {u.nombre},\n\n" + (f"No se pudo generar el CV para {p['empresa']}:\n{error}" if error else f"Tu CV para {p['empresa']} está listo.")
            + f"\n\nAbre la app: {cuentas.APP_URL}",
        )
    return {"ok": True, "error": error}


@app.get("/api/jobs")
def jobs_listar(request: Request, u: Usuario = Depends(actual)):
    """Estado de las generaciones activas y de las terminadas que aún no se notificaron. También recupera
    jobs atascados (ver web/jobs.py)."""
    lista, reintentar = jobs.visibles(u.id)
    for job_id in reintentar[:1]:  # de a uno por consulta: cada despacho espera ~2 s
        jobs.despachar(_base_url(request), job_id)
    return lista


@app.post("/api/jobs/{job_id}/visto")
def jobs_visto(job_id: int, u: Usuario = Depends(actual)):
    jobs.marcar_visto(u.id, job_id)
    return {"ok": True}


@app.post("/api/postulaciones/{pid}/ats-recomendaciones")
def postulaciones_ats_recomendaciones(pid: int, u: Usuario = Depends(actual)):
    p = _cargar(u, pid)
    if not p.get("cv"):
        raise HTTPException(400, "Primero genera el CV.")
    recs = recomendaciones_ats(p.get("ats_keywords_faltantes", []), p["cv"], u.perfil_ia(), p["oferta_texto"])
    datos = _datos(p)
    datos["ats_recomendaciones"] = recs
    store.guardar(u.id, pid, p["estado"], datos)
    return recs


@app.post("/api/postulaciones/{pid}/ajustar/preview")
def postulaciones_ajustar_preview(pid: int, body: Instruccion, u: Usuario = Depends(actual)):
    """Paso 5: la IA propone el CV ajustado SIN renderizar. El frontend muestra el diff, el
    usuario puede editarlo, y recién al confirmar se renderiza vía /yaml."""
    p = _cargar(u, pid)
    if not p.get("cv"):
        raise HTTPException(400, "Primero genera el CV.")
    cv = ajustar_cv(p["cv"], body.instruccion, u.perfil_ia(), p["oferta_texto"])
    antes, despues = _yaml(p["cv"]), _yaml(cv)
    return {"cv_yaml": despues, "diff": _diff(antes, despues), "sin_cambios": antes == despues}


@app.post("/api/postulaciones/{pid}/yaml")
def postulaciones_yaml(pid: int, body: CvYaml, u: Usuario = Depends(actual)):
    """Renderiza un `cv` confirmado por el usuario (preview de un ajuste IA o edición manual).
    El diseño sigue saliendo de design_canonico.yaml."""
    p = _cargar(u, pid)
    try:
        cv = yaml.safe_load(body.cv_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"YAML inválido: {e}")
    if not isinstance(cv, dict):
        raise HTTPException(400, "El YAML debe ser el objeto `cv` (name, sections, ...).")
    try:
        return _aplicar_render(u, p, cv, (body.accion or "Edición manual del YAML")[:300])
    except RuntimeError as e:
        raise HTTPException(400, f"rendercv rechazó el CV:\n{e}")


@app.post("/api/postulaciones/{pid}/deshacer")
def postulaciones_deshacer(pid: int, u: Usuario = Depends(actual)):
    p = _cargar(u, pid)
    versiones = p.get("versiones", [])
    if not versiones:
        raise HTTPException(400, "No hay versiones anteriores.")
    anterior = versiones.pop()
    p = {**p, "versiones": versiones}
    return _aplicar_render(u, p, anterior["cv"], "Deshacer: versión anterior restaurada", apilar=False)


@app.post("/api/postulaciones/{pid}/sugerencias-doc")
def postulaciones_sugerencias_doc(pid: int, u: Usuario = Depends(actual)):
    """Paso 6: qué agregar/modificar/simplificar/eliminar en la documentación para calzar
    mejor con ofertas de este tipo."""
    p = _cargar(u, pid)
    return documentacion.sugerencias_desde_oferta(u.perfil_ia(), p["oferta_texto"], p.get("ats_keywords_faltantes", []))


@app.post("/api/postulaciones/{pid}/decision")
def postulaciones_decision(pid: int, body: Decision, u: Usuario = Depends(actual)):
    p = _cargar(u, pid)
    if body.accion not in ("aprobar", "descartar"):
        raise HTTPException(400, "Acción inválida")
    estado = "aprobado" if body.accion == "aprobar" else "descartado_tras_revision"
    datos = _datos(p)
    store.guardar(u.id, pid, estado, datos)
    return _publica(_cargar(u, pid))


@app.get("/api/postulaciones/{pid}/pdf")
def postulaciones_pdf(pid: int, descargar: bool = False, u: Usuario = Depends(actual)):
    p = _cargar(u, pid)
    clave = p.get("pdf_path") or ""
    if not clave.startswith(u.clave("procesados") + "/"):  # solo PDFs del propio usuario
        raise HTTPException(404, "Aún no hay PDF")
    return _pdf_response(clave, clave.rpartition("/")[2], descargar)


# build de Vite (web/frontend → web/static); en desarrollo se usa `npm run dev` con proxy a /api
# En Vercel los estáticos los sirve la CDN (outputDirectory); este montaje es solo para desarrollo local.
if (_STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC / "assets"), name="assets")
