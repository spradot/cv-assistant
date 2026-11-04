import { useEffect, useState } from "react";
import { api, type EstadoAuth, type Resumen, type Usuario } from "./api";
import Ajustes from "./components/Ajustes";
import Auth from "./components/Auth";
import Consumo from "./components/Consumo";
import Documentacion from "./components/Documentacion";
import Onboarding from "./components/Onboarding";
import { DetallePostulacion, ESTADOS, NuevaPostulacion } from "./components/Postulacion";
import { Chip, Spinner } from "./components/ui";

type Vista = "postulaciones" | "documentacion" | "consumo" | "ajustes";

const VISTAS: { id: Vista; texto: string }[] = [
  { id: "postulaciones", texto: "Postulaciones" },
  { id: "documentacion", texto: "Documentación" },
  { id: "consumo", texto: "Consumo IA" },
  { id: "ajustes", texto: "Ajustes" },
];

function tokenReset(): string | null {
  const m = window.location.hash.match(/reset=([\w-]+)/);
  return m ? m[1] : null;
}

export default function App() {
  const [estado, setEstado] = useState<EstadoAuth | null>(null);
  const [usuario, setUsuario] = useState<Usuario | null>(null);

  const cargarEstado = () =>
    api.estado().then((e) => {
      setEstado(e);
      setUsuario(e.usuario);
    });

  useEffect(() => {
    cargarEstado();
    const expirada = () => cargarEstado();
    window.addEventListener("sesion-expirada", expirada);
    return () => window.removeEventListener("sesion-expirada", expirada);
  }, []);

  const salir = async () => {
    await api.logout().catch(() => {});
    await cargarEstado();
  };

  if (!estado) return <div className="flex min-h-screen items-center justify-center"><Spinner label="Cargando…" /></div>;
  const reset = tokenReset();
  if (!usuario || reset) return <Auth estado={estado} resetToken={reset} onEntrar={setUsuario} />;
  if (!usuario.onboarding_completo) return <Onboarding usuario={usuario} onListo={setUsuario} onSalir={salir} />;
  return <Principal usuario={usuario} onUsuario={setUsuario} onSalir={salir} />;
}

function Principal({ usuario, onUsuario, onSalir }: { usuario: Usuario; onUsuario: (u: Usuario) => void; onSalir: () => void }) {
  const [vista, setVista] = useState<Vista>("postulaciones");
  const [lista, setLista] = useState<Resumen[]>([]);
  const [seleccion, setSeleccion] = useState<number | null>(null);
  const [instruccionDoc, setInstruccionDoc] = useState("");
  const [filtro, setFiltro] = useState("");
  const [proveedor, setProveedor] = useState<string | null>(null);

  const recargar = () => api.listar().then(setLista).catch(() => {});
  useEffect(() => {
    recargar();
    api.config().then((c) => setProveedor(c.classifier_provider)).catch(() => {});
  }, []);

  const visibles = lista.filter((p) => p.empresa.toLowerCase().includes(filtro.toLowerCase()));

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
          <h1 className="font-bold">📋 Postulaciones</h1>
          <nav className="flex flex-wrap gap-1">
            {VISTAS.map((v) => (
              <button
                key={v.id}
                onClick={() => setVista(v.id)}
                className={`rounded-lg px-3 py-1.5 text-sm ${vista === v.id ? "bg-indigo-600 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}
              >
                {v.texto}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {proveedor && proveedor !== "jev" && (
              <span className="text-xs text-amber-600" title="Configura TYPESAFE_API_KEY en .env para usar Jev">
                ⚠ Clasificador: DeepSeek
              </span>
            )}
            <span className="text-slate-500">{usuario.nombre}</span>
            <button className="text-xs text-slate-500 hover:underline" onClick={onSalir}>
              Salir
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] p-4">
        {vista === "documentacion" && <Documentacion instruccionInicial={instruccionDoc} onInstruccionUsada={() => setInstruccionDoc("")} angulos={usuario.config.angulos} />}
        {vista === "consumo" && <Consumo />}
        {vista === "ajustes" && <Ajustes usuario={usuario} onCambio={onUsuario} />}
        {vista === "postulaciones" && (
          <div className="grid gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
            <aside className="card h-fit max-h-[calc(100vh-6rem)] space-y-2 overflow-y-auto p-2 lg:sticky lg:top-16">
              <button className="btn-primary w-full justify-center" onClick={() => setSeleccion(null)}>
                + Nueva postulación
              </button>
              <input className="input py-1" placeholder="Buscar empresa…" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
              {visibles.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setSeleccion(p.id)}
                  className={`block w-full rounded-lg px-2 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800 ${
                    seleccion === p.id ? "bg-indigo-50 dark:bg-indigo-950" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{p.empresa}</span>
                    <span className="text-xs tabular-nums text-slate-500">{p.fit_score ?? "?"}%</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <Chip ok={ESTADOS[p.estado]?.ok}>{ESTADOS[p.estado]?.texto ?? p.estado}</Chip>
                    <span className="text-[11px] text-slate-400">{p.creado_en.slice(0, 10)}</span>
                  </div>
                </button>
              ))}
              {lista.length === 0 && <p className="px-2 text-sm text-slate-500">Aún no hay postulaciones.</p>}
            </aside>

            <div>
              {seleccion === null ? (
                <NuevaPostulacion
                  onCreada={(p) => {
                    recargar();
                    setSeleccion(p.id);
                  }}
                />
              ) : (
                <DetallePostulacion
                  id={seleccion}
                  angulos={usuario.config.angulos}
                  onCambio={recargar}
                  onUsarEnDocumentacion={(instr) => {
                    setInstruccionDoc(instr);
                    setVista("documentacion");
                  }}
                />
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
