import { useEffect, useState } from "react";
import { api, type Job, type Postulacion as P, type RecomendacionATS, type SugerenciaDoc } from "../api";
import { Chip, Copiable, DiffView, ErrorBox, Modal, Spinner, useAccion } from "./ui";

type Preview = { titulo: string; accion: string; cv_yaml: string; diff: string };

export const ESTADOS: Record<string, { texto: string; ok: boolean | null }> = {
  analizado: { texto: "Analizada", ok: null },
  descartado: { texto: "No postular", ok: false },
  generado: { texto: "CV listo", ok: null },
  aprobado: { texto: "Aprobada", ok: true },
  descartado_tras_revision: { texto: "Descartada", ok: false },
};

// ---------- Paso 1: nueva postulación ----------

export function NuevaPostulacion({ onCreada }: { onCreada: (p: P) => void }) {
  const [empresa, setEmpresa] = useState("");
  const [oferta, setOferta] = useState("");
  const { cargando, error, setError, correr } = useAccion();

  return (
    <div className="card space-y-3">
      <h2 className="text-lg font-semibold">Nueva postulación</h2>
      <ErrorBox error={error} onClose={() => setError(null)} />
      <div>
        <label className="label">Empresa</label>
        <input className="input" placeholder="Ej: Falabella Retail" value={empresa} onChange={(e) => setEmpresa(e.target.value)} />
      </div>
      <div>
        <label className="label">Descripción del cargo (JD)</label>
        <textarea
          className="input h-80"
          placeholder="Pega aquí el texto completo de la oferta…"
          value={oferta}
          onChange={(e) => setOferta(e.target.value)}
        />
        <p className="mt-1 text-right text-xs text-slate-400">{oferta.length} caracteres</p>
      </div>
      <div className="flex items-center gap-3">
        <button
          className="btn-primary"
          disabled={!empresa.trim() || oferta.trim().length < 50 || !!cargando}
          onClick={async () => {
            const p = await correr("Analizando", () => api.crear(empresa, oferta));
            if (p) onCreada(p);
          }}
        >
          🔎 Analizar con Jev
        </button>
        {cargando && <Spinner label="Clasificando fit…" />}
      </div>
    </div>
  );
}

// ---------- Detalle (pasos 2-6) ----------

export function DetallePostulacion({
  id,
  angulos,
  onCambio,
  onUsarEnDocumentacion,
  job,
  refresco,
}: {
  id: number;
  angulos: Record<string, string>;
  onCambio: () => void;
  onUsarEnDocumentacion: (instruccion: string) => void;
  /** Generación en segundo plano de esta postulación (si hay una activa). */
  job?: Job;
  /** Sube cuando termina un job: recarga el detalle. */
  refresco: number;
}) {
  const [p, setP] = useState<P | null>(null);
  const [verOferta, setVerOferta] = useState(false);
  const [editarYaml, setEditarYaml] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [ajuste, setAjuste] = useState("");
  const [recs, setRecs] = useState<RecomendacionATS[] | null>(null);
  const [elegidas, setElegidas] = useState<Set<string>>(new Set());
  const [sugerencias, setSugerencias] = useState<SugerenciaDoc[] | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const { cargando, error, setError, correr } = useAccion();

  useEffect(() => {
    setP(null);
    setRecs(null);
    setSugerencias(null);
    correr("Cargando", async () => setP(await api.obtener(id)));
  }, [id]);

  // Un job de generación terminó: recarga el detalle sin parpadeo (no vacía `p`).
  useEffect(() => {
    if (refresco > 0) api.obtener(id).then(setP).catch(() => {});
  }, [refresco]);

  useEffect(() => {
    const r = p?.ats_recomendaciones ?? null;
    setRecs(r);
    setElegidas(new Set((r ?? []).filter((x) => x.respaldada).map((x) => x.keyword)));
  }, [p?.ats_recomendaciones, p?.actualizado_en]);

  async function actualizar(etiqueta: string, fn: () => Promise<P>) {
    const nuevo = await correr(etiqueta, fn);
    if (nuevo) {
      setP(nuevo);
      onCambio();
    }
    return nuevo;
  }

  /** Paso 5: la IA propone el CV ajustado; se muestra el diff y solo al confirmar se renderiza. */
  async function previsualizar(titulo: string, instruccion: string) {
    if (!p) return false;
    setAviso(null);
    const r = await correr("Preparando propuesta", () => api.ajustarPreview(p.id, instruccion));
    if (!r) return false;
    if (r.sin_cambios) {
      setAviso("La IA no propuso cambios para esa instrucción.");
      return false;
    }
    setPreview({ titulo, accion: `${titulo}: ${instruccion}`, cv_yaml: r.cv_yaml, diff: r.diff });
    return true;
  }

  if (!p) return <div className="card">{cargando ? <Spinner label="Cargando…" /> : <ErrorBox error={error} />}</div>;

  const descartar = p.recomendacion !== "postular";
  const cobertura = p.ats_cobertura != null ? Math.round(p.ats_cobertura * 100) : null;
  const generando = !!job && (job.estado === "pendiente" || job.estado === "ejecutando");
  const ocupado = !!cargando || generando;

  /** La generación tarda (IA + render): se encola y la app avisa al terminar (ver hooks/useJobs). */
  async function encolarGeneracion(feedback?: string) {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    const r = await correr("Encolando", () => api.generar(p!.id, feedback));
    if (r) window.dispatchEvent(new Event("jobs-cambio"));
    return !!r;
  }

  return (
    <div className="space-y-4">
      <ErrorBox error={error} onClose={() => setError(null)} />
      {aviso && (
        <div className="flex justify-between rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {aviso}
          <button onClick={() => setAviso(null)}>×</button>
        </div>
      )}
      {cargando && cargando !== "Cargando" && (
        <div className="sticky top-2 z-10 card border-indigo-300 py-2 dark:border-indigo-800">
          <Spinner label={cargando === "Encolando" ? "Encolando…" : `${cargando}… (DeepSeek + rendercv pueden tardar 30-90 s)`} />
        </div>
      )}
      {generando && (
        <div className="sticky top-2 z-10 card border-indigo-300 py-2 dark:border-indigo-800">
          <Spinner label={`Generando el CV en segundo plano${job?.etapa ? ` — ${job.etapa}` : ""}…`} />
          <p className="mt-1 text-xs text-slate-500">
            Puedes seguir usando la app: te avisaremos aquí cuando esté listo (y por correo, si está configurado).
          </p>
        </div>
      )}

      {/* Paso 2-3: clasificación */}
      <section className="card space-y-3">
        <div className="flex flex-wrap items-start gap-3">
          <div className="mr-auto">
            <h2 className="text-xl font-semibold">{p.empresa_original || p.empresa}</h2>
            <p className="text-xs text-slate-500">
              Analizada {p.creado_en.replace("T", " ")} · clasificador: <b>{p.clasificador === "jev" ? "Jev (TypeSafe)" : "DeepSeek (fallback de Jev)"}</b>
            </p>
          </div>
          <Chip ok={ESTADOS[p.estado]?.ok}>{ESTADOS[p.estado]?.texto ?? p.estado}</Chip>
        </div>

        <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
          <div className={`rounded-xl p-3 text-center ${descartar ? "bg-red-50 dark:bg-red-950" : "bg-emerald-50 dark:bg-emerald-950"}`}>
            <div className="text-4xl font-bold tabular-nums">{p.fit_score ?? "?"}%</div>
            <div className="text-xs uppercase tracking-wide text-slate-500">fit</div>
            <div className={`mt-1 text-sm font-semibold ${descartar ? "text-red-700 dark:text-red-300" : "text-emerald-700 dark:text-emerald-300"}`}>
              {descartar ? "✋ No postular" : "✅ Postular"}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1.5">
              <Chip ok={p.cumple_excluyentes}>{p.cumple_excluyentes ? "Cumple excluyentes" : "No cumple excluyentes"}</Chip>
              <Chip ok={p.banda_salarial_ok}>{p.banda_salarial_ok ? "Banda salarial OK" : "Banda bajo el piso"}</Chip>
              <Chip ok={p.modalidad_ok}>{p.modalidad_ok ? "Modalidad OK" : "Modalidad no calza"}</Chip>
            </div>
            <p className="text-sm">
              <span className="label inline">Razones: </span>
              {p.razones}
            </p>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="label mb-0">Ángulo del CV</span>
              <select
                className="input w-auto py-1"
                value={p.angulo ?? "DE_ES"}
                disabled={ocupado}
                onChange={(e) => actualizar("Cambiando ángulo", () => api.angulo(p.id, e.target.value))}
              >
                {Object.entries(angulos).map(([k, v]) => (
                  <option key={k} value={k}>
                    {k} · {v}
                  </option>
                ))}
                {p.angulo && !(p.angulo in angulos) && <option value={p.angulo}>{p.angulo}</option>}
              </select>
              <button className="text-xs text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setVerOferta(true)}>
                Ver JD
              </button>
            </div>
          </div>
        </div>

        {!p.cv && (
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-3 dark:border-slate-800">
            <button className={descartar ? "btn-ghost" : "btn-primary"} disabled={ocupado} onClick={() => encolarGeneracion()}>
              📄 {descartar ? "Generar CV de todos modos" : "Generar CV ajustado"}
            </button>
            {descartar && <span className="text-xs text-slate-500">La recomendación es no postular — puedes hacer una excepción consciente.</span>}
          </div>
        )}
      </section>

      {/* Paso 4: CV + comentarios */}
      {p.cv && (
        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="card p-2">
            <iframe
              key={p.actualizado_en}
              title="CV"
              src={api.pdfUrl(p.id, p.actualizado_en)}
              className="h-[80vh] w-full rounded-lg bg-white"
            />
          </div>

          <div className="space-y-4">
            <div className="card space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">Comentarios para el portal</h3>
                <a className="btn-ghost" href={api.pdfUrl(p.id, p.actualizado_en, true)}>
                  ⬇ PDF
                </a>
              </div>
              <Copiable label="Banda salarial sugerida" texto={p.banda_salarial} />
              <Copiable label="Pretensión de renta" texto={p.pretension_renta} />
              <Copiable label="Experiencia (200c)" texto={p.experiencia_200} />
              <Copiable label="Habilidades (200c)" texto={p.habilidades_200} />
              <Copiable label="Disponibilidad" texto={p.disponibilidad} />
              <Copiable label="Modalidad preferida" texto={p.modalidad_preferida} />
            </div>

            {/* ATS */}
            <div className="card space-y-3">
              <h3 className="font-semibold">Análisis ATS</h3>
              <div className="flex flex-wrap gap-1.5">
                <Chip ok={(p.paginas ?? 1) <= 1}>
                  {p.paginas} página{p.paginas !== 1 ? "s" : ""}
                </Chip>
                <Chip ok={p.ats_parseo_ok}>{p.ats_parseo_ok ? "Parseo OK" : "Parseo con problemas"}</Chip>
                <Chip ok={cobertura != null ? cobertura >= 70 : null}>Cobertura {cobertura}%</Chip>
              </div>
              {!p.ats_parseo_ok && <p className="text-xs text-red-600">{p.ats_detalle_parseo}</p>}
              <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                <div
                  className={`h-full ${cobertura != null && cobertura >= 70 ? "bg-emerald-500" : "bg-amber-500"}`}
                  style={{ width: `${cobertura ?? 0}%` }}
                />
              </div>
              <div className="flex flex-wrap gap-1">
                {(p.ats_keywords_presentes ?? []).map((k) => (
                  <Chip key={k} ok>
                    {k}
                  </Chip>
                ))}
                {(p.ats_keywords_faltantes ?? []).map((k) => (
                  <Chip key={k} ok={false}>
                    {k}
                  </Chip>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Paso 5: modificar CV con recomendaciones ATS */}
      {p.cv && (
        <section className="card space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="mr-auto font-semibold">Mejorar el CV</h3>
            {p.n_versiones > 0 && (
              <button className="btn-ghost" disabled={ocupado} onClick={() => actualizar("Restaurando versión anterior", () => api.deshacer(p.id))}>
                ↩ Deshacer ({p.n_versiones})
              </button>
            )}
            <button className="btn-ghost" disabled={ocupado} onClick={() => setEditarYaml(true)}>
              {"</>"} Editar YAML
            </button>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="label mb-0">Recomendaciones ATS</span>
              <button
                className="btn-ghost"
                disabled={ocupado || !(p.ats_keywords_faltantes ?? []).length}
                onClick={async () => {
                  const r = await correr("Analizando keywords faltantes", () => api.atsRecomendaciones(p.id));
                  if (r) {
                    setRecs(r);
                    setElegidas(new Set(r.filter((x) => x.respaldada).map((x) => x.keyword)));
                  }
                }}
              >
                🤖 {recs ? "Volver a analizar" : "Obtener recomendaciones"}
              </button>
              {!(p.ats_keywords_faltantes ?? []).length && <span className="text-xs text-emerald-600">Todas las keywords están cubiertas.</span>}
            </div>
            {recs && recs.length > 0 && (
              <>
                <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                  {recs.map((r) => (
                    <li key={r.keyword} className="flex gap-3 p-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={elegidas.has(r.keyword)}
                        onChange={(e) => {
                          const s = new Set(elegidas);
                          e.target.checked ? s.add(r.keyword) : s.delete(r.keyword);
                          setElegidas(s);
                        }}
                      />
                      <div>
                        <div className="flex items-center gap-2">
                          <b>{r.keyword}</b>
                          <Chip ok={r.respaldada}>{r.respaldada ? "respaldada por tu perfil" : "brecha real"}</Chip>
                        </div>
                        <p className="text-slate-600 dark:text-slate-400">{r.recomendacion}</p>
                      </div>
                    </li>
                  ))}
                </ul>
                <button
                  className="btn-primary"
                  disabled={ocupado || elegidas.size === 0}
                  onClick={() => {
                    const instr =
                      "Incorpora estas keywords de la oferta en el CV, siguiendo cada recomendación:\n" +
                      recs
                        .filter((r) => elegidas.has(r.keyword))
                        .map((r) => `- ${r.keyword}: ${r.recomendacion}`)
                        .join("\n");
                    previsualizar("Recomendaciones ATS", instr);
                  }}
                >
                  👁 Previsualizar {elegidas.size} recomendación{elegidas.size !== 1 ? "es" : ""}
                </button>
              </>
            )}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <span className="label">Ajuste puntual (mantiene el resto del CV)</span>
              <textarea
                className="input h-20"
                placeholder="Ej: destaca más la experiencia con SAP y acorta el resumen"
                value={ajuste}
                onChange={(e) => setAjuste(e.target.value)}
              />
              <button
                className="btn-primary"
                disabled={ocupado || !ajuste.trim()}
                onClick={async () => (await previsualizar("Ajuste IA", ajuste)) && setAjuste("")}
              >
                👁 Previsualizar ajuste
              </button>
            </div>
            <div className="space-y-2">
              <span className="label">Regenerar desde cero (con feedback opcional)</span>
              <textarea
                className="input h-20"
                placeholder="Ej: enfoca el CV en Analytics Engineering y dbt"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
              />
              <button className="btn-ghost" disabled={ocupado} onClick={async () => (await encolarGeneracion(feedback)) && setFeedback("")}>
                🔄 Regenerar
              </button>
            </div>
          </div>

          {(p.historial ?? []).length > 0 && (
            <details>
              <summary className="label cursor-pointer">Historial de cambios ({p.historial!.length})</summary>
              <ol className="mt-1 space-y-0.5 text-xs text-slate-500">
                {p.historial!.map((h, i) => (
                  <li key={i}>
                    {i + 1}. {h.accion.split("\n")[0]} — ATS {Math.round(h.ats_cobertura * 100)}%, {h.paginas} pág.
                  </li>
                ))}
              </ol>
            </details>
          )}
        </section>
      )}

      {/* Paso 6: mejorar la documentación para otras opciones */}
      <section className="card space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="mr-auto font-semibold">Mejorar la documentación a partir de esta oferta</h3>
          <button className="btn-ghost" disabled={ocupado} onClick={async () => setSugerencias((await correr("Buscando mejoras", () => api.sugerenciasDoc(p.id))) ?? null)}>
            💡 {sugerencias ? "Volver a sugerir" : "Sugerir cambios"}
          </button>
        </div>
        <p className="text-sm text-slate-500">
          Qué agregar, modificar, simplificar o eliminar del perfil para que los próximos CVs calcen mejor con ofertas de este tipo. Nada se
          guarda sin que veas el diff.
        </p>
        {sugerencias && (
          <ul className="space-y-2">
            {sugerencias.map((s, i) => (
              <li key={i} className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
                <div className="flex flex-wrap items-center gap-2">
                  <Chip ok={s.tipo === "eliminar" ? false : s.tipo === "agregar" ? true : null}>{s.tipo}</Chip>
                  <b className="mr-auto">{s.titulo}</b>
                  <button className="btn-ghost py-1" onClick={() => onUsarEnDocumentacion(s.instruccion)}>
                    Llevar a Documentación →
                  </button>
                </div>
                <p className="mt-1 text-slate-600 dark:text-slate-400">{s.detalle}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Decisión */}
      <section className="card flex flex-wrap items-center gap-2">
        <span className="mr-auto text-sm text-slate-500">¿Vas a postular con este CV?</span>
        <button className="btn-danger" disabled={ocupado || p.estado === "descartado_tras_revision"} onClick={() => actualizar("Guardando", () => api.decision(p.id, "descartar"))}>
          ❌ Descartar
        </button>
        <button className="btn-primary" disabled={ocupado || !p.cv || p.estado === "aprobado"} onClick={() => actualizar("Guardando", () => api.decision(p.id, "aprobar"))}>
          ✅ Aprobar
        </button>
      </section>

      {verOferta && (
        <Modal titulo="Descripción del cargo" onClose={() => setVerOferta(false)}>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap font-sans text-sm">{p.oferta_texto}</pre>
        </Modal>
      )}
      {preview && (
        <ModalPreview
          preview={preview}
          onClose={() => setPreview(null)}
          onConfirmar={async (yamlFinal, editado) => {
            setPreview(null);
            await actualizar("Renderizando el CV", () => api.yaml(p.id, yamlFinal, preview.accion + (editado ? " (editado a mano)" : "")));
          }}
        />
      )}
      {editarYaml && (
        <EditorYaml
          inicial={p.cv_yaml ?? ""}
          onClose={() => setEditarYaml(false)}
          onGuardar={async (y) => {
            setEditarYaml(false);
            await actualizar("Renderizando YAML", () => api.yaml(p.id, y, "Edición manual del YAML"));
          }}
        />
      )}
    </div>
  );
}

function EditorYaml({ inicial, onClose, onGuardar }: { inicial: string; onClose: () => void; onGuardar: (y: string) => void }) {
  const [texto, setTexto] = useState(inicial);
  return (
    <Modal titulo="Editar contenido del CV (bloque cv de rendercv)" onClose={onClose}>
      <p className="mb-2 text-xs text-slate-500">El diseño (márgenes, fuentes, tema) sale siempre de design_canonico.yaml: aquí solo se edita el contenido.</p>
      <textarea className="input h-[65vh] font-mono text-xs leading-5" value={texto} onChange={(e) => setTexto(e.target.value)} spellCheck={false} />
      <div className="mt-3 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={texto === inicial} onClick={() => onGuardar(texto)}>
          Renderizar PDF
        </button>
      </div>
    </Modal>
  );
}

function ModalPreview({
  preview,
  onClose,
  onConfirmar,
}: {
  preview: Preview;
  onClose: () => void;
  onConfirmar: (yaml: string, editado: boolean) => void;
}) {
  const [tab, setTab] = useState<"diff" | "editar">("diff");
  const [texto, setTexto] = useState(preview.cv_yaml);
  const editado = texto !== preview.cv_yaml;
  return (
    <Modal titulo={`Vista previa — ${preview.titulo}`} onClose={onClose}>
      <p className="mb-2 text-sm text-slate-500">
        Revisa los cambios que propone la IA. El PDF se genera solo cuando confirmas; si cancelas, el CV queda como estaba.
      </p>
      <div className="mb-2 flex gap-1 text-sm">
        {(["diff", "editar"] as const).map((t) => (
          <button
            key={t}
            className={`rounded-md px-3 py-1 ${tab === t ? "bg-slate-200 font-medium dark:bg-slate-800" : "text-slate-500"}`}
            onClick={() => setTab(t)}
          >
            {t === "diff" ? "Cambios" : "Ajustar antes de renderizar"}
          </button>
        ))}
      </div>
      {tab === "diff" ? (
        <DiffView diff={editado ? "(editado a mano — revisa en la otra pestaña)" : preview.diff} />
      ) : (
        <textarea className="input h-[28rem] font-mono text-xs leading-5" spellCheck={false} value={texto} onChange={(e) => setTexto(e.target.value)} />
      )}
      <div className="mt-3 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>
          Descartar propuesta
        </button>
        <button className="btn-primary" onClick={() => onConfirmar(texto, editado)}>
          📄 Generar PDF con estos cambios
        </button>
      </div>
    </Modal>
  );
}
