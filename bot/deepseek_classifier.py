"""Clasificador de fit usando DeepSeek con salida JSON forzada — reemplazo de Jev cuando no
hay TYPESAFE_API_KEY. Misma interfaz (Clasificacion) que jev_client.clasificar, así que
bot/classifier.py puede intercambiarlos sin tocar el grafo.

Diferencia real con Jev: esto es un LLM generativo pidiendo JSON (segundos, no ms,
y unos centavos por llamada), no un modelo de decisión tipada nativo."""

from bot import llm
from bot.tipos import Clasificacion, Preferencias

_SYSTEM_PROMPT = """\
Eres un clasificador de fit laboral. Debes responder SOLO un objeto JSON válido, sin \
markdown ni texto adicional, con exactamente estas claves:

- "fit_score": número 0-100. 0 = no calza en absoluto, 100 = calce perfecto con los \
requisitos excluyentes, stack, seniority y modalidad.
- "cumple_excluyentes": true/false — el candidato cumple TODOS los requisitos \
excluyentes/obligatorios listados en la oferta.
- "banda_salarial_ok": true/false — la banda salarial de la oferta (si se menciona) es \
igual o superior al piso del candidato: <PISO>. Si la oferta no menciona sueldo, responde \
true (no se puede descartar por esto).
- "modalidad_ok": true/false — la modalidad/ubicación calza: <MODALIDAD>.
- "angulo": uno de <ANGULOS>.
- "recomendacion": "postular" si cumple excluyentes y al menos banda salarial o modalidad \
son aceptables; "descartar" si falta un excluyente clave, o banda y modalidad son ambas malas.
- "razones": string corto (máx. 3 frases) explicando la decisión.

Sé estricto con los requisitos excluyentes: si la oferta pide algo que el candidato no \
tiene y lo marca como obligatorio/excluyente, "cumple_excluyentes" debe ser false.
"""


def clasificar(oferta_texto: str, perfil_resumen: str, preferencias: Preferencias) -> Clasificacion:
    angulos = preferencias.angulos_o_default()
    sistema = (
        _SYSTEM_PROMPT.replace("<PISO>", preferencias.piso_salarial)
        .replace("<MODALIDAD>", preferencias.modalidad)
        .replace("<ANGULOS>", ", ".join(f'"{k}" ({v})' for k, v in angulos.items()))
    )
    data = llm.chat(
        "clasificar",
        [
            {"role": "system", "content": sistema},
            {"role": "user", "content": f"PERFIL DEL CANDIDATO:\n{perfil_resumen}\n\nOFERTA LABORAL:\n{oferta_texto}"},
        ],
        json_mode=True,
    )
    angulo = data.get("angulo")
    return Clasificacion(
        fit_score=float(data["fit_score"]),
        cumple_excluyentes=bool(data["cumple_excluyentes"]),
        banda_salarial_ok=bool(data["banda_salarial_ok"]),
        modalidad_ok=bool(data["modalidad_ok"]),
        angulo=angulo if angulo in angulos else next(iter(angulos)),
        recomendacion=data["recomendacion"],
        razones=data["razones"],
    )
