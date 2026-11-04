"""Filtro rápido de fit usando Jev (TypeSafe System One) — decisiones tipadas, no texto libre."""

from functools import lru_cache

from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

from bot.config import TYPESAFE_API_KEY
import time

from bot import llm
from bot.tipos import Clasificacion, Preferencias


_CRITERIOS_FIT = [
    "No calza: falta un requisito excluyente clave o el rol es de otra disciplina",
    "Calce parcial: cumple lo esencial pero hay brechas importantes",
    "Calce fuerte: cumple los requisitos excluyentes y la mayoría de los deseables",
]


@lru_cache
def _get_client() -> TypeSafeClient:
    return TypeSafeClient(api_key=TYPESAFE_API_KEY)


def clasificar(oferta_texto: str, perfil_resumen: str, preferencias: Preferencias) -> Clasificacion:
    state = (
        f"PERFIL DEL CANDIDATO:\n{perfil_resumen}\n\n"
        f"OFERTA LABORAL:\n{oferta_texto}"
    )

    inicio = time.perf_counter()
    response = _get_client().system_one(
        state=state,
        questions={
            "fit": Score(
                instructions="Qué tan bien calza el candidato con esta oferta, "
                "considerando requisitos excluyentes, stack, seniority y modalidad",
                criteria=_CRITERIOS_FIT,
            ),
            "cumple_excluyentes": Noul(
                instructions="El candidato cumple TODOS los requisitos excluyentes/obligatorios listados en la oferta",
            ),
            "banda_salarial_ok": Noul(
                instructions="La banda salarial de la oferta (si se menciona) es igual o superior al piso "
                f"del candidato: {preferencias.piso_salarial}. "
                "Si la oferta no menciona sueldo, responde afirmativo (no se puede descartar por esto).",
            ),
            "modalidad_ok": Noul(
                instructions=f"La modalidad/ubicación calza con las preferencias del candidato: {preferencias.modalidad}",
            ),
            "angulo": Choice(
                instructions="Qué ángulo de CV conviene usar para esta oferta",
                criteria=preferencias.angulos_o_default(),
            ),
            "recomendacion": Choice(
                instructions="Decisión final: ¿conviene postular a esta oferta?",
                criteria={
                    "postular": "Cumple excluyentes y al menos banda salarial o modalidad son aceptables",
                    "descartar": "Falta un excluyente clave, o banda salarial y modalidad son ambas malas",
                },
            ),
        },
    )

    llm.registrar("clasificar", "jev", ms=int((time.perf_counter() - inicio) * 1000))

    razones_partes = []
    if response.answers["cumple_excluyentes"].noul < 0.5:
        razones_partes.append("no cumple requisitos excluyentes")
    if response.answers["banda_salarial_ok"].noul < 0.5:
        razones_partes.append("banda salarial bajo el piso")
    if response.answers["modalidad_ok"].noul < 0.5:
        razones_partes.append("modalidad/ubicación no calza")
    if not razones_partes:
        razones_partes.append("cumple los criterios clave del perfil")

    return Clasificacion(
        # Score devuelve el nivel esperado de la rúbrica (0 .. n-1), no una probabilidad 0-1:
        # se normaliza a 0-100 dividiendo por el nivel máximo.
        fit_score=round(response.answers["fit"].score / (len(_CRITERIOS_FIT) - 1) * 100, 1),
        cumple_excluyentes=response.answers["cumple_excluyentes"].noul >= 0.5,
        banda_salarial_ok=response.answers["banda_salarial_ok"].noul >= 0.5,
        modalidad_ok=response.answers["modalidad_ok"].noul >= 0.5,
        angulo=response.answers["angulo"].choice,
        recomendacion=response.answers["recomendacion"].choice,
        razones="; ".join(razones_partes),
    )
