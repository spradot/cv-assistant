"""Actualiza README.md (la fuente de verdad del perfil) a partir de una instrucción
en lenguaje natural por Telegram, ej. 'Aprobé el AI-103 en septiembre 2026'.
El llamador (telegram_bot.py) siempre muestra el diff y pide aprobación antes de
sobrescribir — este archivo alimenta todas las postulaciones futuras.

La IA devuelve solo las secciones que cambian (bot/documentacion.editar_documento) y el
documento completo se arma localmente: antes reescribía el archivo entero en cada cambio."""

from bot.documentacion import editar_documento


def actualizar_readme(contenido_actual: str, instruccion: str) -> str:
    return editar_documento(contenido_actual, instruccion)
