import { useState, type ReactNode } from "react";

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" />
      {label}
    </span>
  );
}

export function ErrorBox({ error, onClose }: { error: string | null; onClose?: () => void }) {
  if (!error) return null;
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
      <pre className="whitespace-pre-wrap break-words font-sans">{error}</pre>
      {onClose && (
        <button className="shrink-0 font-bold" onClick={onClose} aria-label="Cerrar">
          ×
        </button>
      )}
    </div>
  );
}

/** Ejecuta acciones async con un único estado de carga + error por componente. */
export function useAccion() {
  const [cargando, setCargando] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function correr<T>(etiqueta: string, fn: () => Promise<T>): Promise<T | undefined> {
    setCargando(etiqueta);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setCargando(null);
    }
  }
  return { cargando, error, setError, correr };
}

export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <p className="text-sm text-slate-500">Sin cambios.</p>;
  return (
    <pre className="max-h-[28rem] overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs leading-5 dark:border-slate-800 dark:bg-slate-950">
      {diff.split("\n").map((l, i) => {
        let cls = "text-slate-600 dark:text-slate-400";
        if (l.startsWith("+++") || l.startsWith("---")) cls = "font-semibold text-slate-500";
        else if (l.startsWith("+")) cls = "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-300";
        else if (l.startsWith("-")) cls = "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-300";
        else if (l.startsWith("@@")) cls = "text-indigo-600 dark:text-indigo-400";
        return (
          <div key={i} className={`whitespace-pre-wrap break-words px-1 ${cls}`}>
            {l || " "}
          </div>
        );
      })}
    </pre>
  );
}

export function Modal({ titulo, children, onClose }: { titulo: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div className="card my-8 w-full max-w-4xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-semibold">{titulo}</h3>
          <button className="text-2xl leading-none text-slate-400 hover:text-slate-600" onClick={onClose} aria-label="Cerrar">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Chip({ ok, children }: { ok: boolean | null | undefined; children: ReactNode }) {
  const cls =
    ok === true
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
      : ok === false
        ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
        : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300";
  return <span className={`chip ${cls}`}>{children}</span>;
}

export function Copiable({ label, texto }: { label: string; texto?: string }) {
  const [copiado, setCopiado] = useState(false);
  if (!texto) return null;
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        <button
          className="text-xs text-indigo-600 hover:underline dark:text-indigo-400"
          onClick={() => {
            navigator.clipboard.writeText(texto);
            setCopiado(true);
            setTimeout(() => setCopiado(false), 1200);
          }}
        >
          {copiado ? "¡Copiado!" : "Copiar"}
        </button>
      </div>
      <p className="text-sm">{texto}</p>
      {label.includes("200") && <p className="text-right text-[11px] text-slate-400">{texto.length}/200</p>}
    </div>
  );
}
