"""Bot de Telegram: recibe la oferta, corre el grafo, pausa para tu revisión
y aplica tu decisión (aprobar / ajustar / descartar)."""

import asyncio
import difflib
import logging
import re

from langgraph.types import Command
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import ats_check, db
from bot.config import PROJECT_ROOT, README_PATH, TELEGRAM_ALLOWED_USER_ID, TELEGRAM_BOT_TOKEN, require_telegram
from bot.graph import construir_grafo
from bot.qa import responder as responder_pregunta
from bot.readme_editor import actualizar_readme

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
# httpx loguea cada request en INFO con la URL completa, que incluye el token del bot.
logging.getLogger("httpx").setLevel(logging.WARNING)

grafo = construir_grafo()

ESPERANDO_EMPRESA = "esperando_empresa"
ACUMULANDO_OFERTA = "acumulando_oferta"
ESPERANDO_FEEDBACK = "esperando_feedback"
ESPERANDO_ACTUALIZACION = "esperando_actualizacion"


def _nombre_archivo(texto: str) -> str:
    """Nombre de empresa saneado para usar en nombres de archivo (sin espacios, tildes ni símbolos raros)."""
    limpio = re.sub(r"[^A-Za-z0-9]+", "", texto)
    return limpio[:40] or "SinNombre"


def _solo_dueno(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user is None or update.effective_user.id != TELEGRAM_ALLOWED_USER_ID:
            return
        return await func(update, context)

    return wrapper


def _config(chat_id: int) -> dict:
    return {"configurable": {"thread_id": str(chat_id)}}


async def _correr_grafo(chat_id: int, payload):
    """Ejecuta el grafo (bloqueante: llamadas HTTP a Jev/DeepSeek/rendercv) en un hilo aparte."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: grafo.invoke(payload, _config(chat_id)))


def _extraer_interrupcion(resultado: dict):
    interrupciones = resultado.get("__interrupt__")
    return interrupciones[0].value if interrupciones else None


@_solo_dueno
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/nueva para empezar una postulación.\n"
        "Te pregunto la empresa, luego pégame la oferta (puede ser en varios mensajes si es larga) "
        "y mandas /fin cuando termines de pegarla.\n"
        "Filtro el fit primero, y si vale la pena, genero el CV + campos para el portal.\n\n"
        "/actualizar para avisarme algo nuevo de tu perfil (ej. una cert que aprobaste) — "
        "te muestro el diff del README antes de guardarlo.\n\n"
        "/revisar si un envío se cortó (ej. timeout subiendo el PDF) y quieres recuperar "
        "la revisión pendiente sin reprocesar todo.\n\n"
        "Si me escribes sin ningún flujo activo, lo tomo como pregunta abierta sobre tu perfil "
        "o la última oferta/CV que procesamos en este chat."
    )


@_solo_dueno
async def cmd_actualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instruccion = " ".join(context.args) if context.args else None
    if instruccion:
        await _procesar_actualizacion_readme(update, context, instruccion)
        return
    context.user_data["estado"] = ESPERANDO_ACTUALIZACION
    await update.message.reply_text(
        "¿Qué cambió en tu perfil? (ej: 'Aprobé el AI-103 en septiembre 2026, sácalo de agendado')"
    )


async def _procesar_actualizacion_readme(update: Update, context: ContextTypes.DEFAULT_TYPE, instruccion: str):
    original = README_PATH.read_text(encoding="utf-8")
    await update.message.reply_text("Editando README.md...")
    loop = asyncio.get_running_loop()
    nuevo = await loop.run_in_executor(None, lambda: actualizar_readme(original, instruccion))

    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(), nuevo.splitlines(), fromfile="antes", tofile="después", lineterm=""
        )
    )
    if not diff.strip():
        await update.message.reply_text("No detecté cambios que aplicar.")
        return

    context.user_data["readme_propuesto"] = nuevo
    botones = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Aplicar", callback_data="readme:aplicar"),
                InlineKeyboardButton("❌ Cancelar", callback_data="readme:cancelar"),
            ]
        ]
    )
    if len(diff) > 3500:
        diff_path = PROJECT_ROOT / "_ultimo_diff_readme.txt"
        diff_path.write_text(diff, encoding="utf-8")
        with open(diff_path, "rb") as f:
            await update.message.reply_document(f, filename="diff_readme.txt", reply_markup=botones)
    else:
        await update.message.reply_text(f"```diff\n{diff}\n```", parse_mode="Markdown", reply_markup=botones)


@_solo_dueno
async def cmd_nueva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["estado"] = ESPERANDO_EMPRESA
    await update.message.reply_text("¿Nombre de la empresa? (se usa para nombrar los archivos)")


@_solo_dueno
async def cmd_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("estado") != ACUMULANDO_OFERTA:
        await update.message.reply_text("No hay una oferta en curso. Manda /nueva para empezar.")
        return

    partes = context.user_data.pop("oferta_partes", [])
    empresa = context.user_data.pop("empresa")
    context.user_data["estado"] = None
    oferta_texto = "\n".join(partes)

    if not oferta_texto.strip():
        await update.message.reply_text("No recibí texto de oferta. Manda /nueva para reintentar.")
        return

    await update.message.reply_text(
        f"Clasificando fit para {empresa} ({len(oferta_texto)} caracteres de oferta)..."
    )
    resultado = await _correr_grafo(
        update.effective_chat.id, {"empresa": empresa, "oferta_texto": oferta_texto}
    )
    await _procesar_resultado(update, context, resultado)


@_solo_dueno
async def recibir_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    estado = context.user_data.get("estado")

    if estado == ESPERANDO_EMPRESA:
        context.user_data["empresa"] = _nombre_archivo(texto)
        context.user_data["oferta_partes"] = []
        context.user_data["estado"] = ACUMULANDO_OFERTA
        await update.message.reply_text(
            "Perfecto. Ahora pégame el texto de la oferta — si Telegram la corta en varios "
            "mensajes no hay problema, los voy juntando. Cuando termines, manda /fin."
        )
        return

    if estado == ACUMULANDO_OFERTA:
        context.user_data["oferta_partes"].append(texto)
        total = sum(len(p) for p in context.user_data["oferta_partes"])
        await update.message.reply_text(f"+{len(texto)} caracteres agregados (total {total}). Sigue pegando o manda /fin.")
        return

    if estado == ESPERANDO_FEEDBACK:
        context.user_data["estado"] = None
        await update.message.reply_text("Ajustando el CV con tu feedback...")
        resultado = await _correr_grafo(
            update.effective_chat.id,
            Command(resume={"accion": "ajustar", "feedback": texto}),
        )
        await _procesar_resultado(update, context, resultado)
        return

    if estado == ESPERANDO_ACTUALIZACION:
        context.user_data["estado"] = None
        await _procesar_actualizacion_readme(update, context, texto)
        return

    # Sin flujo activo: se trata como pregunta abierta sobre el perfil o la última
    # oferta/CV procesada en este chat (no hay ambigüedad con /nueva porque esa siempre
    # requiere el comando explícito).
    await _responder_pregunta_abierta(update, context, texto)


async def _responder_pregunta_abierta(update: Update, context: ContextTypes.DEFAULT_TYPE, pregunta: str):
    perfil = README_PATH.read_text(encoding="utf-8")
    chat_id = str(update.effective_chat.id)

    # Busca en la DB (no en memoria del proceso) si la pregunta menciona una empresa ya
    # procesada, y arma contexto real desde ahí — esto sobrevive reinicios del bot, a
    # diferencia de guardar solo "la última oferta" en context.user_data.
    contexto_partes = []
    pregunta_norm = pregunta.lower()
    for empresa in db.empresas_conocidas():
        if empresa.lower() in pregunta_norm:
            for fila in db.buscar_por_empresa(empresa, limit=1):
                contexto_partes.append(
                    f"Empresa: {fila['empresa']}\n"
                    f"Estado: {fila['estado']}\n"
                    f"Fit: {fila['fit_score']}%\n"
                    f"Recomendación: {fila['recomendacion']}\n"
                    f"Razones: {fila['razones']}\n"
                    f"Banda salarial: {fila['banda_salarial']}\n"
                    f"Oferta:\n{fila['oferta_texto']}"
                )
    contexto_oferta = "\n\n---\n\n".join(contexto_partes) or None

    historial = db.historial_conversacion(chat_id)
    respuesta = await asyncio.get_running_loop().run_in_executor(
        None, lambda: responder_pregunta(pregunta, perfil, contexto_oferta, historial)
    )
    db.guardar_turno(chat_id, "user", pregunta)
    db.guardar_turno(chat_id, "assistant", respuesta)
    await update.message.reply_text(respuesta)


async def _procesar_resultado(update: Update, context: ContextTypes.DEFAULT_TYPE, resultado: dict):
    interrupcion = _extraer_interrupcion(resultado)

    if interrupcion is None:
        # Terminó sin pasar por revisión: fue descartado en la clasificación, o aprobado/descartado ya
        if resultado.get("decision_final") == "aprobado":
            db.registrar_postulacion(
                empresa=resultado["empresa"],
                angulo=resultado["angulo"],
                fit_score=resultado["fit_score"],
                recomendacion=resultado["recomendacion"],
                razones=resultado["razones"],
                banda_salarial=resultado.get("banda_salarial"),
                oferta_texto=resultado.get("oferta_texto"),
                pdf_path=resultado.get("pdf_path"),
                estado="aprobado",
            )
            await update.message.reply_text("Guardado como aprobado. ✅")
        else:
            razones = resultado.get("razones", "sin detalle")
            fit = resultado.get("fit_score", "?")
            # Se persiste en la DB (no solo en user_data) porque user_data se pierde cada vez
            # que el proceso del bot se reinicia — y así una pregunta futura tipo "¿por qué
            # descartaron X?" se puede responder aunque haya pasado un reinicio de por medio.
            db.registrar_postulacion(
                empresa=resultado.get("empresa", "Desconocida"),
                angulo=resultado.get("angulo"),
                fit_score=resultado.get("fit_score"),
                recomendacion=resultado.get("recomendacion", "descartar"),
                razones=razones,
                oferta_texto=resultado.get("oferta_texto"),
                estado="descartado",
            )
            await update.message.reply_text(
                f"Descartado (fit {fit}%). Razones: {razones}"
            )
        return

    await _enviar_revision(update.message, context, interrupcion)


async def _enviar_revision(message, context: ContextTypes.DEFAULT_TYPE, interrupcion: dict):
    """Manda el PDF + resumen + botones de una revisión pendiente. Separado de
    _procesar_resultado para poder reusarlo desde /revisar cuando el envío falló la
    primera vez (ej. timeout subiendo el PDF) y el grafo se quedó pausado esperando."""
    context.user_data["ultimo_pdf"] = interrupcion["pdf_path"]
    db.registrar_postulacion(
        empresa=interrupcion["empresa"],
        angulo=interrupcion.get("angulo"),
        fit_score=interrupcion["fit_score"],
        recomendacion="postular",
        banda_salarial=interrupcion["banda_salarial"],
        oferta_texto=interrupcion.get("oferta_texto"),
        pdf_path=interrupcion["pdf_path"],
        estado="pendiente_revision",
    )
    botones = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Aprobar", callback_data="cv:aprobar"),
                InlineKeyboardButton("✏️ Ajustar", callback_data="cv:ajustar"),
                InlineKeyboardButton("❌ Descartar", callback_data="cv:descartar"),
            ]
        ]
    )
    with open(interrupcion["pdf_path"], "rb") as pdf:
        await message.reply_document(pdf, filename=interrupcion["pdf_path"].split("\\")[-1])

    ats_icono = "✅" if interrupcion["ats_parseo_ok"] and interrupcion["ats_cobertura"] >= 0.7 else "⚠️"
    faltantes = interrupcion["ats_keywords_faltantes"]
    ats_linea = f"{ats_icono} ATS: parseo {'ok' if interrupcion['ats_parseo_ok'] else 'CON PROBLEMAS'}, cobertura keywords {interrupcion['ats_cobertura']*100:.0f}%"
    if faltantes:
        ats_linea += f"\n  Faltan: {', '.join(faltantes)}"

    # .get() con recálculo: una revisión pausada de antes de agregar este chequeo no trae
    # "paginas" en el payload guardado del checkpoint.
    paginas = interrupcion.get("paginas")
    if paginas is None:
        paginas = ats_check.contar_paginas(interrupcion["pdf_path"])
    paginas_icono = "✅" if paginas <= 1 else "⚠️"
    paginas_linea = f"{paginas_icono} Largo: {paginas} página{'s' if paginas != 1 else ''}"

    texto_resumen = (
        f"*{interrupcion['empresa']}* — fit {interrupcion['fit_score']}%\n\n"
        f"*Banda salarial:* {interrupcion['banda_salarial']}\n"
        f"*Experiencia (200c):* {interrupcion['experiencia_200']}\n"
        f"*Habilidades (200c):* {interrupcion['habilidades_200']}\n\n"
        f"{paginas_linea}\n"
        f"{ats_linea}"
    )
    await message.reply_text(texto_resumen, parse_mode="Markdown", reply_markup=botones)


@_solo_dueno
async def cmd_revisar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recupera una revisión que se quedó pausada (ej. el envío del PDF falló por timeout
    de red) sin tener que volver a correr todo el pipeline desde cero."""
    snapshot = grafo.get_state(_config(update.effective_chat.id))
    if not snapshot.interrupts:
        await update.message.reply_text("No hay ninguna revisión pendiente. Manda /nueva para empezar una.")
        return
    await _enviar_revision(update.message, context, snapshot.interrupts[0].value)


@_solo_dueno
async def click_boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    namespace, _, accion = query.data.partition(":")

    if namespace == "readme":
        await _click_readme(query, context, accion)
        return

    if accion == "ajustar":
        context.user_data["estado"] = ESPERANDO_FEEDBACK
        await query.message.reply_text("¿Qué quieres que ajuste?")
        return

    resultado = await _correr_grafo(
        update.effective_chat.id, Command(resume={"accion": accion, "feedback": None})
    )
    interrupcion = _extraer_interrupcion(resultado)
    if interrupcion is None:
        if accion == "aprobar":
            db.registrar_postulacion(
                empresa=resultado["empresa"],
                angulo=resultado["angulo"],
                fit_score=resultado["fit_score"],
                recomendacion=resultado["recomendacion"],
                razones=resultado["razones"],
                banda_salarial=resultado.get("banda_salarial"),
                oferta_texto=resultado.get("oferta_texto"),
                pdf_path=resultado.get("pdf_path"),
                estado="aprobado",
            )
            await query.message.reply_text("Guardado como aprobado. ✅")
        else:
            db.registrar_postulacion(
                empresa=resultado.get("empresa", "Desconocida"),
                angulo=resultado.get("angulo"),
                fit_score=resultado.get("fit_score"),
                recomendacion=resultado.get("recomendacion"),
                razones=resultado.get("razones"),
                banda_salarial=resultado.get("banda_salarial"),
                oferta_texto=resultado.get("oferta_texto"),
                pdf_path=resultado.get("pdf_path"),
                estado="descartado_tras_revision",
            )
            await query.message.reply_text("Descartado. ❌")


async def _click_readme(query, context: ContextTypes.DEFAULT_TYPE, accion: str):
    if accion == "aplicar":
        nuevo = context.user_data.pop("readme_propuesto", None)
        if nuevo is None:
            await query.message.reply_text("Esta propuesta ya expiró, manda /actualizar de nuevo.")
            return
        README_PATH.write_text(nuevo, encoding="utf-8")
        await query.message.reply_text("README.md actualizado. ✅")
    else:
        context.user_data.pop("readme_propuesto", None)
        await query.message.reply_text("Cambio descartado.")


async def manejador_errores(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error no manejado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        await context.bot.send_message(
            update.effective_chat.id,
            f"⚠️ Algo falló: {context.error}\n\nRevisa bot.log para el detalle completo.",
        )


def main():
    require_telegram()
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .read_timeout(30)
        .connect_timeout(15)
        .write_timeout(30)
        .media_write_timeout(60)  # el default (~5s) es muy corto para subir el PDF del CV
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("nueva", cmd_nueva))
    app.add_handler(CommandHandler("fin", cmd_fin))
    app.add_handler(CommandHandler("actualizar", cmd_actualizar))
    app.add_handler(CommandHandler("revisar", cmd_revisar))
    app.add_handler(CallbackQueryHandler(click_boton))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_mensaje))
    app.add_error_handler(manejador_errores)
    logger.info("Bot corriendo (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
