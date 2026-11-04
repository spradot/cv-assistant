import { useState } from "react";
import type { PreferenciasInput, Usuario } from "../api";

/** Preferencias que usa el clasificador (Jev) y el generador de CV. Se comparte entre el
 * onboarding y la vista de Ajustes. */
export function PreferenciasForm({
  usuario,
  textoBoton,
  deshabilitado,
  onGuardar,
}: {
  usuario: Usuario;
  textoBoton: string;
  deshabilitado?: boolean;
  onGuardar: (p: PreferenciasInput) => void;
}) {
  const [nombreArchivo, setNombreArchivo] = useState(usuario.config.nombre_archivo);
  const [piso, setPiso] = useState(usuario.config.piso_salarial);
  const [modalidad, setModalidad] = useState(usuario.config.modalidad);
  const [angulos, setAngulos] = useState<[string, string][]>(Object.entries(usuario.config.angulos));

  return (
    <div className="space-y-3">
      <div>
        <label className="label">Nombre para los archivos PDF</label>
        <input className="input" value={nombreArchivo} onChange={(e) => setNombreArchivo(e.target.value)} />
        <p className="mt-1 text-xs text-slate-500">Ej: «Valentina Muñoz» → Valentina_Munoz_Empresa_CV.pdf</p>
      </div>
      <div>
        <label className="label">Piso salarial</label>
        <input
          className="input"
          placeholder="Ej: 2.0M CLP líquido en Chile, o USD 55k/año si es remoto internacional"
          value={piso}
          onChange={(e) => setPiso(e.target.value)}
        />
      </div>
      <div>
        <label className="label">Modalidad y ubicación aceptables</label>
        <input
          className="input"
          placeholder="Ej: híbrido a máx 40 min de Providencia, o remoto completo"
          value={modalidad}
          onChange={(e) => setModalidad(e.target.value)}
        />
        <p className="mt-1 text-xs text-slate-500">Jev usa estos dos campos para decidir si conviene postular.</p>
      </div>
      <div>
        <label className="label">Ángulos de CV</label>
        <p className="mb-2 text-xs text-slate-500">
          Variantes de CV entre las que elige el clasificador según la oferta (ej. por rol o idioma). El código va en el nombre del archivo.
        </p>
        <div className="space-y-2">
          {angulos.map(([codigo, desc], i) => (
            <div key={i} className="flex gap-2">
              <input
                className="input w-28 font-mono"
                placeholder="DE_ES"
                value={codigo}
                onChange={(e) => setAngulos(angulos.map((a, j) => (j === i ? [e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""), a[1]] : a)))}
              />
              <input
                className="input"
                placeholder="Data Engineer, en español"
                value={desc}
                onChange={(e) => setAngulos(angulos.map((a, j) => (j === i ? [a[0], e.target.value] : a)))}
              />
              <button
                type="button"
                className="btn-ghost"
                disabled={angulos.length <= 1}
                onClick={() => setAngulos(angulos.filter((_, j) => j !== i))}
                aria-label="Quitar"
              >
                ×
              </button>
            </div>
          ))}
          <button type="button" className="text-xs text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setAngulos([...angulos, ["", ""]])}>
            + Agregar ángulo
          </button>
        </div>
      </div>
      <button
        className="btn-primary"
        disabled={deshabilitado || !angulos.some(([c, d]) => c && d)}
        onClick={() =>
          onGuardar({
            nombre_archivo: nombreArchivo,
            piso_salarial: piso,
            modalidad,
            angulos: Object.fromEntries(angulos.filter(([c, d]) => c && d)),
          })
        }
      >
        {textoBoton}
      </button>
    </div>
  );
}
