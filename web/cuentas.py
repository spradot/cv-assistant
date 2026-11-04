"""Usuarios, sesiones y recuperación de contraseña por correo, más el "espacio" de cada
usuario (dónde vive su documentación, respaldos y PDFs, y sus preferencias).

- Datos: Postgres (Supabase). Archivos: Supabase Storage, bajo `usuarios/<id>/` (ver web/storage.py).
- Contraseñas: PBKDF2-SHA256 (stdlib), 390k iteraciones, salt por usuario.
- Sesión: token aleatorio en cookie httpOnly; en la DB solo se guarda su hash.
- Recuperación: si hay SMTP configurado se envía un link de un solo uso (1 h).
- El PRIMER usuario registrado es el admin (solo cambia quién ve el consumo global en el futuro;
  todos los espacios son idénticos y están aislados por usuario)."""

import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from bot import pg
from bot.tipos import Preferencias
from web import storage

DURACION_SESION = timedelta(days=30)
DURACION_RESET = timedelta(hours=1)
_ITERACIONES = 390_000

SMTP_HOST = os.environ.get("SMTP_HOST") or None
SMTP_PORT = int(os.environ.get("SMTP_PORT") or 587)
SMTP_USER = os.environ.get("SMTP_USER") or None
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or None
SMTP_FROM = os.environ.get("SMTP_FROM") or SMTP_USER
APP_URL = (os.environ.get("APP_URL") or (f"https://{os.environ['VERCEL_URL']}" if os.environ.get("VERCEL_URL") else "http://127.0.0.1:8000")).rstrip("/")
PERMITIR_REGISTRO = (os.environ.get("PERMITIR_REGISTRO") or "true").lower() not in ("0", "false", "no")
# Si está definido, registrarse (incluida la primera cuenta) exige este código: con la web pública
# evita que cualquiera con la URL cree cuentas y consuma los créditos de IA.
CODIGO_INVITACION = os.environ.get("CODIGO_INVITACION") or None

ANGULOS_NUEVOS = {
    "ES": "CV en español",
    "EN": "CV en inglés (oferta internacional o que exige inglés)",
}

_NOMBRE_RESPALDO = re.compile(r"README_\d{8}_\d{6}\.md")


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERACIONES)
    return f"pbkdf2_sha256${_ITERACIONES}${salt}${dk.hex()}"


def _verificar_password(password: str, almacenado: str) -> bool:
    try:
        _, iteraciones, salt, esperado = almacenado.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iteraciones))
        return hmac.compare_digest(dk.hex(), esperado)
    except ValueError:
        return False


# ---------- límite de intentos (por IP, en Postgres: sirve entre instancias serverless) ----------

LIMITES = {"login": (10, 15 * 60), "registro": (5, 60 * 60), "olvide": (5, 60 * 60), "reset": (10, 60 * 60)}


def limitar(accion: str, ip: str) -> int | None:
    """Registra un intento. Si ya se superó el máximo devuelve los minutos de espera (y no registra)."""
    maximo, ventana = LIMITES[accion]
    with pg.conn() as c:
        c.execute("DELETE FROM intentos_limite WHERE creado_en < now() - interval '1 day'")
        fila = c.execute(
            "SELECT COUNT(*)::int n, EXTRACT(EPOCH FROM now() - MIN(creado_en))::float edad FROM intentos_limite "
            "WHERE accion = %s AND ip = %s AND creado_en > now() - make_interval(secs => %s)",
            (accion, ip, ventana),
        ).fetchone()
        if fila["n"] >= maximo:
            return int((ventana - (fila["edad"] or 0)) // 60) + 1
        c.execute("INSERT INTO intentos_limite (accion, ip) VALUES (%s, %s)", (accion, ip))
    return None


# ---------- usuario / espacio ----------

@dataclass
class Usuario:
    id: int
    username: str
    email: str | None
    nombre: str
    es_admin: bool
    onboarding_completo: bool
    config: dict = field(default_factory=dict)

    # --- archivos (Supabase Storage) ---
    def clave(self, *partes: str) -> str:
        return "/".join(["usuarios", str(self.id), *partes])

    @property
    def clave_doc(self) -> str:
        return self.clave("perfil.md")

    @property
    def carpeta_respaldos(self) -> str:
        return self.clave("respaldos")

    @property
    def destino_render(self) -> dict:
        """rendercv necesita archivos locales: se renderiza en un directorio temporal y el PDF
        resultante se sube a Storage (el disco de Vercel es efímero y de solo escritura en /tmp)."""
        base = Path(tempfile.gettempdir()) / "postulaciones" / str(self.id)
        return {"yaml_dir": base / "YAML", "pdf_dir": base / "procesados", "prefijo": self.prefijo_pdf}

    @property
    def prefijo_pdf(self) -> str:
        base = unicodedata.normalize("NFKD", self.config.get("nombre_archivo") or self.nombre)
        base = "".join(c for c in base if not unicodedata.combining(c))  # Muñoz -> Munoz
        limpio = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
        return limpio[:40] or "CV"

    def subir_pdf(self, ruta_local: str | Path) -> str:
        """Sube un PDF renderizado a Storage y devuelve su clave."""
        ruta = Path(ruta_local)
        clave = self.clave("procesados", ruta.name)
        storage.subir(clave, ruta.read_bytes(), "application/pdf")
        return clave

    # --- documentación (perfil) con respaldo ---
    def leer_doc(self) -> str:
        datos = storage.descargar(self.clave_doc)
        return datos.decode("utf-8") if datos is not None else ""

    def guardar_doc(self, contenido: str) -> str | None:
        """Respalda la versión actual y escribe la nueva. Devuelve el nombre del respaldo."""
        respaldo = None
        actual = storage.descargar(self.clave_doc)
        if actual is not None:
            respaldo = f"README_{datetime.now():%Y%m%d_%H%M%S}.md"
            storage.subir(f"{self.carpeta_respaldos}/{respaldo}", actual, "text/markdown; charset=utf-8")
        storage.subir(self.clave_doc, (contenido.rstrip() + "\n").encode("utf-8"), "text/markdown; charset=utf-8")
        return respaldo

    def listar_respaldos(self) -> list[str]:
        return sorted((f["name"] for f in storage.listar(self.carpeta_respaldos) if _NOMBRE_RESPALDO.fullmatch(f["name"])), reverse=True)

    def leer_respaldo(self, nombre: str) -> str:
        datos = storage.descargar(f"{self.carpeta_respaldos}/{nombre}") if _NOMBRE_RESPALDO.fullmatch(nombre) else None
        if datos is None:
            raise FileNotFoundError(nombre)
        return datos.decode("utf-8")

    def perfil_ia(self) -> str:
        from bot import documentacion

        return documentacion.perfil_para_ia(self.leer_doc(), self.excluidas_ia)

    # --- preferencias ---
    @property
    def preferencias(self) -> Preferencias:
        return Preferencias(
            piso_salarial=self.config.get("piso_salarial") or "no especificado (no descartes por sueldo)",
            modalidad=self.config.get("modalidad") or "cualquier modalidad",
            angulos=self.config.get("angulos") or ANGULOS_NUEVOS,
        )

    @property
    def excluidas_ia(self) -> list[str]:
        return list(self.config.get("excluidas_ia") or [])

    def publico(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "nombre": self.nombre,
            "es_admin": self.es_admin,
            "onboarding_completo": self.onboarding_completo,
            "config": {
                "nombre_archivo": self.config.get("nombre_archivo") or self.nombre,
                "piso_salarial": self.config.get("piso_salarial") or "",
                "modalidad": self.config.get("modalidad") or "",
                "angulos": self.config.get("angulos") or ANGULOS_NUEVOS,
                "excluidas_ia": self.excluidas_ia,
            },
        }


def _de_fila(f) -> Usuario:
    return Usuario(
        id=f["id"],
        username=f["username"],
        email=f["email"],
        nombre=f["nombre"],
        es_admin=f["es_admin"],
        onboarding_completo=f["onboarding_completo"],
        config=f["config"] or {},
    )


def obtener(user_id: int) -> Usuario | None:
    with pg.conn() as c:
        f = c.execute("SELECT * FROM usuarios WHERE id = %s", (user_id,)).fetchone()
    return _de_fila(f) if f else None


def hay_usuarios() -> bool:
    with pg.conn() as c:
        return c.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None


def validar_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")


def registrar(username: str, password: str, nombre: str, email: str | None, codigo: str | None = None) -> Usuario:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise ValueError("Usuario: 3-40 caracteres, solo letras, números, punto, guion o guion bajo.")
    validar_password(password)
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
        raise ValueError("Email inválido.")
    es_admin = not hay_usuarios()
    if not es_admin and not PERMITIR_REGISTRO:
        raise PermissionError("El registro de nuevos usuarios está deshabilitado.")
    if CODIGO_INVITACION and not hmac.compare_digest((codigo or "").strip(), CODIGO_INVITACION):
        raise PermissionError("Código de invitación incorrecto.")

    config: dict = {"nombre_archivo": nombre.strip()}
    with pg.conn() as c:
        try:
            fila = c.execute(
                "INSERT INTO usuarios (username, email, nombre, password_hash, es_admin, config) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (
                    username,
                    (email or "").strip() or None,
                    nombre.strip() or username,
                    _hash_password(password),
                    es_admin,
                    Jsonb(config),
                ),
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise ValueError("Ese nombre de usuario ya existe.")
    return _de_fila(fila)


def autenticar(username: str, password: str) -> Usuario | None:
    with pg.conn() as c:
        f = c.execute(
            "SELECT * FROM usuarios WHERE lower(username) = lower(%s) OR (email IS NOT NULL AND lower(email) = lower(%s))",
            (username.strip(), username.strip()),
        ).fetchone()
    if f is None:
        _hash_password(password)  # mismo costo que un login válido (no revela si el usuario existe)
        return None
    return _de_fila(f) if _verificar_password(password, f["password_hash"]) else None


_CAMPOS_ACTUALIZABLES = {"config", "email", "onboarding_completo", "nombre"}


def actualizar(user_id: int, **campos) -> Usuario:
    if not campos or not set(campos) <= _CAMPOS_ACTUALIZABLES:
        raise ValueError(f"Campos no actualizables: {set(campos) - _CAMPOS_ACTUALIZABLES}")
    if "config" in campos:
        campos["config"] = Jsonb(campos["config"])
    asignaciones = ", ".join(f"{c} = %s" for c in campos)
    with pg.conn() as c:
        c.execute(f"UPDATE usuarios SET {asignaciones} WHERE id = %s", (*campos.values(), user_id))
    return obtener(user_id)


def cambiar_password(user_id: int, actual: str | None, nueva: str) -> None:
    validar_password(nueva)
    with pg.conn() as c:
        f = c.execute("SELECT password_hash FROM usuarios WHERE id = %s", (user_id,)).fetchone()
        if actual is not None and not _verificar_password(actual, f["password_hash"]):
            raise ValueError("La contraseña actual no es correcta.")
        c.execute("UPDATE usuarios SET password_hash = %s WHERE id = %s", (_hash_password(nueva), user_id))
        c.execute("DELETE FROM sesiones WHERE user_id = %s", (user_id,))


# ---------- sesiones ----------

def crear_sesion(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with pg.conn() as c:
        c.execute("DELETE FROM sesiones WHERE expira < now()")
        c.execute(
            "INSERT INTO sesiones (token_hash, user_id, expira) VALUES (%s, %s, %s)",
            (_sha(token), user_id, datetime.now().astimezone() + DURACION_SESION),
        )
    return token


def usuario_de_sesion(token: str | None) -> Usuario | None:
    if not token:
        return None
    with pg.conn() as c:
        f = c.execute(
            "SELECT u.* FROM sesiones s JOIN usuarios u ON u.id = s.user_id WHERE s.token_hash = %s AND s.expira > now()",
            (_sha(token),),
        ).fetchone()
    return _de_fila(f) if f else None


def cerrar_sesion(token: str | None) -> None:
    if token:
        with pg.conn() as c:
            c.execute("DELETE FROM sesiones WHERE token_hash = %s", (_sha(token),))


# ---------- recuperación de contraseña ----------

def smtp_configurado() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def solicitar_reset(usuario_o_email: str) -> None:
    """No revela si el usuario existe: siempre termina sin error visible."""
    if not smtp_configurado():
        raise RuntimeError("La recuperación por correo no está configurada (SMTP_* en las variables de entorno).")
    with pg.conn() as c:
        f = c.execute(
            "SELECT * FROM usuarios WHERE lower(username) = lower(%s) OR lower(email) = lower(%s)",
            (usuario_o_email.strip(), usuario_o_email.strip()),
        ).fetchone()
        if f is None or not f["email"]:
            return
        token = secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO resets_password (token_hash, user_id, expira) VALUES (%s, %s, %s)",
            (_sha(token), f["id"], datetime.now().astimezone() + DURACION_RESET),
        )
    _enviar_correo(
        f["email"],
        "Recupera tu contraseña — Postulaciones",
        f"Hola {f['nombre']},\n\nPara crear una nueva contraseña abre este link (válido por 1 hora):\n\n"
        f"{APP_URL}/#reset={token}\n\nSi no lo pediste, ignora este correo.",
    )


def confirmar_reset(token: str, nueva: str) -> None:
    validar_password(nueva)
    with pg.conn() as c:
        f = c.execute(
            "UPDATE resets_password SET usado = true WHERE token_hash = %s AND NOT usado AND expira > now() RETURNING user_id",
            (_sha(token),),
        ).fetchone()
    if f is None:
        raise ValueError("El link expiró o ya se usó. Pide uno nuevo.")
    cambiar_password(f["user_id"], None, nueva)


def avisar(usuario: Usuario, asunto: str, cuerpo: str) -> None:
    """Correo opcional al usuario (si hay SMTP y email). Nunca rompe el flujo que lo llama."""
    if not (smtp_configurado() and usuario.email):
        return
    try:
        _enviar_correo(usuario.email, asunto, cuerpo)
    except Exception:
        logging.getLogger(__name__).warning("no se pudo enviar el aviso a %s", usuario.username, exc_info=True)


def _enviar_correo(destino: str, asunto: str, cuerpo: str) -> None:
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = destino
    msg["Subject"] = asunto
    msg.set_content(cuerpo)
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD or "")
            s.send_message(msg)
