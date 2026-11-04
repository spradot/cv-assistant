"""Preguntas abiertas sobre el perfil o la última oferta/CV procesada en el chat.
Sin estructura de salida ni pipeline — un chat directo con DeepSeek usando README.md
como contexto, más la última oferta/CV si hay una reciente en la conversación."""

from bot import llm

_SYSTEM_PROMPT = """\
Eres el asistente de postulaciones de Samuel Prado. Respondes preguntas abiertas sobre su \
perfil (README.md, que es la fuente de verdad) y, si se te da, sobre la última oferta laboral \
u oferta/CV que se procesó en esta conversación. Responde en español, directo y conciso — sin \
inventar datos que no estén en el contexto dado. Si la pregunta requiere generar o modificar un \
CV, o registrar un cambio de perfil, dile al usuario que use /nueva o /actualizar para eso — tu \
rol aquí es solo responder preguntas, no ejecutar acciones."""


def responder(
    pregunta: str,
    perfil_readme: str,
    contexto_oferta: str | None = None,
    historial: list[dict] | None = None,
) -> str:
    """`historial` es una lista de turnos previos [{"role": "user"/"assistant", "content": ...}]
    en orden cronológico, persistidos en sqlite (bot/db.py) — así una pregunta de seguimiento
    ("¿y con esa banda igual me conviene?") tiene memoria real de lo que se dijo antes, y esa
    memoria sobrevive un reinicio del proceso del bot."""
    contexto_sistema = _SYSTEM_PROMPT
    if contexto_oferta:
        contexto_sistema += f"\n\nCONTEXTO DE OFERTA(S) RELEVANTE(S) A LA PREGUNTA:\n{contexto_oferta}"

    mensajes = [{"role": "system", "content": f"{contexto_sistema}\n\nPERFIL (README.md):\n{perfil_readme}"}]
    mensajes.extend(historial or [])
    mensajes.append({"role": "user", "content": pregunta})

    return llm.chat("pregunta_abierta", mensajes, temperature=0.3)
