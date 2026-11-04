import { useEffect, useMemo, useState } from "react";
import { api, type CvBase, type Docs, type Propuesta, type Seccion } from "../api";
import { DiffView, ErrorBox, Modal, Spinner, useAccion } from "./ui";

type Props = {
  /** Instrucción precargada desde una sugerencia de una postulación (paso 6). */
  instruccionInicial: string;
  onInstruccionUsada: () => void;
  /** Ángulos (idioma/enfoque) del usuario, para elegir en cuál generar el CV base. */
  angulos: Record<string, string>;
};

export default function Documentacion({ instruccionInicial, onInstruccionUsada, angulos }: Props) {
  const [docs, setDocs] = useState<Docs | null>(null);
  const [seleccion, setSeleccion] = useState<number | null>(null);
  const [propuesta, setPropuesta] = useState<(Propuesta & { titulo: string }) | null>(null);
  const [instruccion, setInstruccion] = useState("");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [modo, setModo] = useState("fusionar");
  const [vistaCompleta, setVistaCompleta] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const { cargando, error, setError, correr } = useAccion();

  const recargar = () => correr("Cargando", async () => setDocs(await api.docs()));
  useEffect(() => {
    recargar();
  }, []);

  useEffect(() => {
    if (instruccionInicial) {
      setInstruccion(instruccionInicial);
      onInstruccionUsada();
    }
  }, [instruccionInicial]);

  const seccion = useMemo(
    () => (seleccion !== null ? docs?.secciones[seleccion] ?? null : null),
    [docs, seleccion],
  );

  async function proponer(titulo: string, fn: () => Promise<Propuesta>) {
    const p = await correr(titulo, fn);
    if (!p) return;
    if (p.sin_cambios) {
      setAviso("La IA no propuso cambios.");
      return;
    }
    setPropuesta({ ...p, titulo });
  }

  async function aplicar(contenido: string) {
    const r = await correr("Guardando", () => api.docsGuardar(contenido));
    if (!r) return;
    setDocs(r);
    setPropuesta(null);
    setSeleccion(null);
    setAviso(`Documentación guardada.${r.respaldo ? ` Respaldo: ${r.respaldo}` : ""}`);
  }

  if (!docs) return <div className="p-6">{cargando ? <Spinner label="Cargando documentación…" /> : <ErrorBox error={error} />}</div>;

  return (
    <div className="space-y-4">
      <ErrorBox error={error} onClose={() => setError(null)} />
      {aviso && (
        <div className="flex justify-between rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
          {aviso}
          <button onClick={() => setAviso(null)}>×</button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm dark:border-slate-800 dark:bg-slate-900">
        <span>
          🤖 Se envían a la IA <b className="tabular-nums">~{docs.tokens_ia.toLocaleString("es-CL")} tokens</b> de perfil por llamada
        </span>
        <span className="text-slate-500">
          ({docs.caracteres_ia.toLocaleString("es-CL")} de {docs.caracteres_total.toLocaleString("es-CL")} caracteres
          {docs.excluidas_ia.length > 0 && ` · ${docs.excluidas_ia.length} sección(es) excluida(s)`})
        </span>
        <span className="text-xs text-slate-400">Excluye secciones que no aportan a tus CVs (registros, notas internas) para ahorrar.</span>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Cargar CV */}
        <div className="card space-y-3">
          <h2 className="font-semibold">Cargar CV a la documentación</h2>
          <p className="text-sm text-slate-500">
            PDF, DOCX, YAML de rendercv, TXT o MD. La IA extrae la información y te muestra los cambios antes de guardar.
          </p>
          <input
            type="file"
            accept=".pdf,.docx,.yaml,.yml,.txt,.md"
            className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700 dark:file:bg-indigo-950 dark:file:text-indigo-300"
            onChange={(e) => setArchivo(e.target.files?.[0] ?? null)}
          />
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={modo === "fusionar"} onChange={() => setModo("fusionar")} />
              Fusionar con la documentación actual
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={modo === "reemplazar"} onChange={() => setModo("reemplazar")} />
              Crear documentación nueva
            </label>
          </div>
          <button
            className="btn-primary"
            disabled={!archivo || !!cargando}
            onClick={() => archivo && proponer("Documentación desde CV", () => api.docsUpload(archivo, modo))}
          >
            Procesar CV con IA
          </button>
        </div>

        {/* Instrucción global */}
        <div className="card space-y-3">
          <h2 className="font-semibold">Actualizar con IA</h2>
          <p className="text-sm text-slate-500">
            Ej: «Aprobé el DP-800 en septiembre 2026, sácalo de agendado» o «Agrega que uso Databricks en un proyecto personal».
          </p>
          <textarea className="input h-24" value={instruccion} onChange={(e) => setInstruccion(e.target.value)} />
          <button
            className="btn-primary"
            disabled={!instruccion.trim() || !!cargando}
            onClick={() => proponer("Cambio con IA", () => api.docsInstruccion(instruccion))}
          >
            Proponer cambio
          </button>
        </div>
        <CvBaseCard angulos={angulos} deshabilitado={!!cargando} correr={correr} />
      </div>

      {cargando && <Spinner label={`${cargando}… (las llamadas a la IA pueden tardar)`} />}

      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        {/* Índice */}
        <nav className="card max-h-[70vh] overflow-y-auto p-2">
          <div className="flex items-center justify-between px-2 py-1">
            <span className="label mb-0">Secciones</span>
            <button className="text-xs text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setVistaCompleta(true)}>
              Editar todo
            </button>
          </div>
          {docs.secciones.map((s) => (
            <button
              key={s.indice}
              onClick={() => setSeleccion(s.indice)}
              className={`block w-full truncate rounded-md px-2 py-1 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${
                seleccion === s.indice ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" : ""
              }`}
              style={{ paddingLeft: `${(s.nivel - 1) * 12 + 8}px` }}
              title={docs.excluidas_ia.includes(s.titulo) ? `${s.titulo} (no se envía a la IA)` : s.titulo}
            >
              <span className={docs.excluidas_ia.includes(s.titulo) ? "text-slate-400 line-through" : ""}>{s.titulo}</span>
            </button>
          ))}
          {docs.respaldos.length > 0 && (
            <details className="mt-3 px-2">
              <summary className="label cursor-pointer">Respaldos ({docs.respaldos.length})</summary>
              {docs.respaldos.slice(0, 20).map((r) => (
                <button
                  key={r}
                  className="block w-full truncate py-0.5 text-left text-xs text-slate-500 hover:text-indigo-600"
                  onClick={() =>
                    proponer(`Restaurar ${r}`, async () => api.docsDiff((await api.docsRespaldo(r)).contenido))
                  }
                >
                  {r}
                </button>
              ))}
            </details>
          )}
        </nav>

        {/* Sección */}
        <div className="card">
          {seccion ? (
            <EditorSeccion
              key={`${seccion.indice}-${seccion.titulo}`}
              seccion={seccion}
              deshabilitado={!!cargando}
              excluida={docs.excluidas_ia.includes(seccion.titulo)}
              onExcluir={(excluir) => correr("Guardando", async () => setDocs(await api.docsExcluir(seccion.titulo, excluir)))}
              onAccion={(accion, extra) =>
                proponer(`${accion[0].toUpperCase()}${accion.slice(1)}: ${seccion.titulo}`, () =>
                  api.docsSeccion({ indice: seccion.indice, titulo: seccion.titulo, accion, ...extra }),
                )
              }
            />
          ) : (
            <p className="text-sm text-slate-500">
              Selecciona una sección para editarla, simplificarla, reescribirla con IA o eliminarla. Las secciones incluyen sus
              subsecciones.
            </p>
          )}
        </div>
      </div>

      {vistaCompleta && (
        <EditorCompleto
          contenido={docs.contenido}
          onClose={() => setVistaCompleta(false)}
          onProponer={(nuevo) => {
            setVistaCompleta(false);
            proponer("Edición manual", () => api.docsDiff(nuevo));
          }}
        />
      )}

      {propuesta && <ModalPropuesta propuesta={propuesta} cargando={!!cargando} onAplicar={aplicar} onClose={() => setPropuesta(null)} />}
    </div>
  );
}

function EditorSeccion({
  seccion,
  deshabilitado,
  excluida,
  onExcluir,
  onAccion,
}: {
  seccion: Seccion;
  deshabilitado: boolean;
  excluida: boolean;
  onExcluir: (excluir: boolean) => void;
  onAccion: (accion: string, extra?: { instruccion?: string; contenido?: string }) => void;
}) {
  const [texto, setTexto] = useState(seccion.contenido);
  const [instr, setInstr] = useState("");
  const editado = texto !== seccion.contenido;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold">{seccion.titulo}</h2>
        <label
          className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400"
          title="Las secciones excluidas siguen en tu documentación, pero no se mandan a la IA al analizar ofertas ni generar CVs."
        >
          <input type="checkbox" checked={!excluida} disabled={deshabilitado} onChange={(e) => onExcluir(!e.target.checked)} />
          Enviar a la IA (~{Math.round(seccion.contenido.length / 3.5)} tokens)
        </label>
        <button className="btn-ghost" disabled={deshabilitado} onClick={() => onAccion("simplificar")}>
          ✂️ Simplificar
        </button>
        <button className="btn-ghost" disabled={deshabilitado} onClick={() => onAccion("reescribir")}>
          ✨ Reescribir
        </button>
        <button
          className="btn-danger"
          disabled={deshabilitado}
          onClick={() => confirm(`¿Eliminar «${seccion.titulo}» y sus subsecciones? (verás el diff antes de guardar)`) && onAccion("eliminar")}
        >
          🗑 Eliminar
        </button>
      </div>
      <textarea className="input h-[45vh] font-mono text-xs leading-5" value={texto} onChange={(e) => setTexto(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={!editado || deshabilitado} onClick={() => onAccion("editar", { contenido: texto })}>
          Revisar edición manual
        </button>
        {editado && (
          <button className="btn-ghost" onClick={() => setTexto(seccion.contenido)}>
            Descartar edición
          </button>
        )}
      </div>
      <div className="flex gap-2">
        <input
          className="input"
          placeholder="Modificar esta sección con IA: ej. «deja solo los 3 logros más fuertes»"
          value={instr}
          onChange={(e) => setInstr(e.target.value)}
        />
        <button className="btn-primary shrink-0" disabled={!instr.trim() || deshabilitado} onClick={() => onAccion("modificar", { instruccion: instr })}>
          Aplicar IA
        </button>
      </div>
    </div>
  );
}

function EditorCompleto({ contenido, onClose, onProponer }: { contenido: string; onClose: () => void; onProponer: (c: string) => void }) {
  const [texto, setTexto] = useState(contenido);
  return (
    <Modal titulo="Editar documentación completa" onClose={onClose}>
      <textarea className="input h-[65vh] font-mono text-xs leading-5" value={texto} onChange={(e) => setTexto(e.target.value)} />
      <div className="mt-3 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={texto === contenido} onClick={() => onProponer(texto)}>
          Revisar cambios
        </button>
      </div>
    </Modal>
  );
}

function ModalPropuesta({
  propuesta,
  cargando,
  onAplicar,
  onClose,
}: {
  propuesta: Propuesta & { titulo: string };
  cargando: boolean;
  onAplicar: (c: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"diff" | "editar">("diff");
  const [texto, setTexto] = useState(propuesta.propuesto);
  return (
    <Modal titulo={propuesta.titulo} onClose={onClose}>
      {propuesta.caracteres_extraidos !== undefined && (
        <p className="mb-2 text-sm text-slate-500">{propuesta.caracteres_extraidos} caracteres extraídos del CV.</p>
      )}
      <div className="mb-2 flex gap-1 text-sm">
        {(["diff", "editar"] as const).map((t) => (
          <button
            key={t}
            className={`rounded-md px-3 py-1 ${tab === t ? "bg-slate-200 font-medium dark:bg-slate-800" : "text-slate-500"}`}
            onClick={() => setTab(t)}
          >
            {t === "diff" ? "Cambios" : "Ajustar antes de guardar"}
          </button>
        ))}
      </div>
      {tab === "diff" ? (
        <DiffView diff={texto === propuesta.propuesto ? propuesta.diff : "(editado a mano — revisa en la otra pestaña)"} />
      ) : (
        <textarea className="input h-[28rem] font-mono text-xs leading-5" value={texto} onChange={(e) => setTexto(e.target.value)} />
      )}
      <div className="mt-3 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>
          Cancelar
        </button>
        <button className="btn-primary" disabled={cargando} onClick={() => onAplicar(texto)}>
          {cargando ? "Guardando…" : "✅ Aplicar y guardar"}
        </button>
      </div>
    </Modal>
  );
}

function CvBaseCard({
  angulos,
  deshabilitado,
  correr,
}: {
  angulos: Record<string, string>;
  deshabilitado: boolean;
  correr: <T>(titulo: string, fn: () => Promise<T>) => Promise<T | undefined>;
}) {
  const [base, setBase] = useState<CvBase | null>(null);
  const [angulo, setAngulo] = useState(Object.keys(angulos)[0] ?? "");
  const [texto, setTexto] = useState("");
  const [diff, setDiff] = useState("");
  const [tab, setTab] = useState<"yaml" | "diff">("yaml");
  const [paginas, setPaginas] = useState<number | null>(null);

  useEffect(() => {
    correr("Cargando CV base", async () => {
      const b = await api.cvBase();
      setBase(b);
      setTexto(b.cv_yaml ?? "");
    });
  }, []);

  const editado = texto !== (base?.cv_yaml ?? "");

  async function borrador() {
    if (editado && !confirm("Tienes cambios sin renderizar en el YAML. ¿Reemplazarlos por un borrador nuevo de la IA?")) return;
    const r = await correr("Generando borrador del CV base", () => api.cvBaseBorrador(angulo));
    if (!r) return;
    setTexto(r.cv_yaml);
    setDiff(r.diff);
    setTab(r.diff ? "diff" : "yaml");
  }

  async function renderizar() {
    const r = await correr("Renderizando CV base", () => api.cvBaseRender(texto, angulo));
    if (!r) return;
    setBase(r);
    setTexto(r.cv_yaml ?? texto);
    setPaginas(r.paginas ?? null);
    setDiff("");
    setTab("yaml");
  }

  return (
    <div className="card space-y-3 md:col-span-2">
      <h2 className="font-semibold">CV base</h2>
      <p className="text-sm text-slate-500">
        Tu CV general, como punto de partida. La IA arma un borrador desde tu documentación (sin inventar lo que falte); lo revisas
        y editas como YAML y, al renderizarlo a PDF, queda guardado como tu CV base vigente.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {Object.keys(angulos).length > 1 && (
          <select className="input w-auto" value={angulo} onChange={(e) => setAngulo(e.target.value)}>
            {Object.entries(angulos).map(([k, v]) => (
              <option key={k} value={k}>
                {k} — {v}
              </option>
            ))}
          </select>
        )}
        <button className="btn-ghost" disabled={deshabilitado} onClick={borrador}>
          {base?.cv_yaml || texto ? "🤖 Regenerar borrador con IA" : "🤖 Generar borrador con IA"}
        </button>
        <button className="btn-primary" disabled={deshabilitado || !texto.trim()} onClick={renderizar}>
          Renderizar PDF y guardar como base
        </button>
        {base?.version && (
          <a className="btn-ghost" href={api.cvBasePdfUrl(base.version, true)}>
            ⬇ PDF
          </a>
        )}
        {paginas !== null && <span className="text-xs text-slate-500">{paginas} página(s)</span>}
        {editado && <span className="text-xs text-amber-600">Sin renderizar</span>}
      </div>
      {texto && (
        <div className="grid gap-3 xl:grid-cols-2">
          <div className="space-y-2">
            <div className="flex gap-1 text-sm">
              {(["yaml", "diff"] as const).map((t) => (
                <button
                  key={t}
                  disabled={t === "diff" && !diff}
                  className={`rounded-md px-3 py-1 disabled:opacity-40 ${tab === t ? "bg-slate-200 font-medium dark:bg-slate-800" : "text-slate-500"}`}
                  onClick={() => setTab(t)}
                >
                  {t === "yaml" ? "YAML editable" : "Cambios vs. base actual"}
                </button>
              ))}
            </div>
            {tab === "yaml" ? (
              <textarea className="input h-[75vh] font-mono text-xs leading-5" value={texto} onChange={(e) => setTexto(e.target.value)} />
            ) : (
              <DiffView diff={diff} />
            )}
          </div>
          {base?.version ? (
            <iframe key={base.version} title="CV base" src={api.cvBasePdfUrl(base.version)} className="h-[80vh] w-full rounded-lg bg-white" />
          ) : (
            <p className="text-sm text-slate-500">Aún no hay PDF: renderiza el YAML para verlo aquí.</p>
          )}
        </div>
      )}
    </div>
  );
}
