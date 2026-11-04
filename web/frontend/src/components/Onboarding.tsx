import { useState } from "react";
import { api, type Usuario } from "../api";
import { PreferenciasForm } from "./Preferencias";
import { ErrorBox, Modal, Spinner, useAccion } from "./ui";

type Paso = 1 | 2 | 3;

export default function Onboarding({ usuario, onListo, onSalir }: { usuario: Usuario; onListo: (u: Usuario) => void; onSalir: () => void }) {
  const [paso, setPaso] = useState<Paso>(1);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [usarPrueba, setUsarPrueba] = useState(false);
  const [descripcion, setDescripcion] = useState("");
  const [documento, setDocumento] = useState("");
  const [verPrueba, setVerPrueba] = useState<string | null>(null);
  const { cargando, error, setError, correr } = useAccion();

  const hayFuente = !!archivo || usarPrueba || descripcion.trim().length >= 40;

  async function generar() {
    const r = await correr("Armando tu documentación", () => api.onboardingDoc({ archivo, usarPrueba: usarPrueba && !archivo, descripcion }));
    if (r) {
      setDocumento(r.propuesto);
      setPaso(2);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Hola, {usuario.nombre.split(" ")[0]} 👋</h1>
          <p className="text-sm text-slate-500">Armemos la documentación de tu perfil: es la fuente de verdad para analizar ofertas y generar tus CVs.</p>
        </div>
        <button className="text-xs text-slate-500 hover:underline" onClick={onSalir}>
          Salir
        </button>
      </header>

      <ol className="flex gap-2 text-sm">
        {["Tu información", "Revisar documentación", "Preferencias"].map((t, i) => (
          <li
            key={t}
            className={`flex-1 rounded-lg px-3 py-2 ${paso === i + 1 ? "bg-indigo-600 text-white" : paso > i + 1 ? "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300" : "bg-slate-100 text-slate-500 dark:bg-slate-800"}`}
          >
            {i + 1}. {t}
          </li>
        ))}
      </ol>

      <ErrorBox error={error} onClose={() => setError(null)} />

      {paso === 1 && (
        <div className="card space-y-4">
          <div>
            <h2 className="font-semibold">Tu CV base</h2>
            <p className="text-sm text-slate-500">PDF, DOCX, YAML de rendercv, TXT o MD. Puedes combinarlo con una descripción.</p>
            <input
              type="file"
              accept=".pdf,.docx,.yaml,.yml,.txt,.md"
              className="mt-2 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700 dark:file:bg-indigo-950 dark:file:text-indigo-300"
              onChange={(e) => {
                setArchivo(e.target.files?.[0] ?? null);
                setUsarPrueba(false);
              }}
            />
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={usarPrueba}
                disabled={!!archivo}
                onChange={(e) => setUsarPrueba(e.target.checked)}
              />
              No tengo uno a mano: usar un CV de prueba para explorar la plataforma
              <button
                type="button"
                className="text-xs text-indigo-600 hover:underline dark:text-indigo-400"
                onClick={async () => setVerPrueba((await correr("Cargando", api.cvPrueba))?.texto ?? null)}
              >
                (ver)
              </button>
            </label>
          </div>
          <div>
            <h2 className="font-semibold">Descripción (opcional si subes un CV)</h2>
            <p className="text-sm text-slate-500">
              Lo que no está en el CV: logros con cifras, stack que manejas, qué roles buscas y cuáles no, sueldo esperado, modalidad.
            </p>
            <textarea
              className="input mt-2 h-36"
              placeholder="Ej: Llevo 4 años como analista de datos. En mi trabajo actual migré 40 reportes a Power BI… Busco roles de Analytics Engineer, no BI puro. Pretensión 2.2M líquido, híbrido en Santiago."
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3">
            <button className="btn-primary" disabled={!hayFuente || !!cargando} onClick={generar}>
              ✨ Generar documentación
            </button>
            {cargando && <Spinner label="La IA está armando tu perfil (~10-20 s)…" />}
          </div>
        </div>
      )}

      {paso === 2 && (
        <div className="card space-y-3">
          <h2 className="font-semibold">Revisa y corrige</h2>
          <p className="text-sm text-slate-500">
            Edita lo que haga falta. Las marcas ⚠️ indican datos por completar o contradicciones. Siempre podrás editarla después en «Documentación».
          </p>
          <textarea className="input h-[55vh] font-mono text-xs leading-5" value={documento} onChange={(e) => setDocumento(e.target.value)} />
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={() => setPaso(1)}>
              ← Volver
            </button>
            <button className="btn-primary" disabled={!documento.trim()} onClick={() => setPaso(3)}>
              Continuar →
            </button>
          </div>
        </div>
      )}

      {paso === 3 && (
        <div className="card space-y-3">
          <h2 className="font-semibold">Preferencias de búsqueda</h2>
          <PreferenciasForm
            usuario={usuario}
            textoBoton={cargando ? "Guardando…" : "✅ Terminar"}
            deshabilitado={!!cargando}
            onGuardar={async (prefs) => {
              const u = await correr("Guardando", () => api.onboardingCompletar(documento, prefs));
              if (u) onListo(u);
            }}
          />
          <button className="btn-ghost" onClick={() => setPaso(2)}>
            ← Volver
          </button>
        </div>
      )}

      {verPrueba && (
        <Modal titulo="CV de prueba (persona ficticia)" onClose={() => setVerPrueba(null)}>
          <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap font-sans text-sm">{verPrueba}</pre>
        </Modal>
      )}
    </div>
  );
}
