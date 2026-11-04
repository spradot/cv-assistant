import { useState } from "react";
import { api, type Usuario } from "../api";
import { PreferenciasForm } from "./Preferencias";
import { ErrorBox, useAccion } from "./ui";

export default function Ajustes({ usuario, onCambio }: { usuario: Usuario; onCambio: (u: Usuario) => void }) {
  const [email, setEmail] = useState(usuario.email ?? "");
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [nueva2, setNueva2] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const { cargando, error, setError, correr } = useAccion();

  return (
    <div className="mx-auto grid max-w-5xl gap-4 md:grid-cols-[1fr_20rem]">
      <div className="card space-y-3">
        <h2 className="text-lg font-semibold">Preferencias</h2>
        <ErrorBox error={error} onClose={() => setError(null)} />
        {aviso && <p className="rounded-lg bg-emerald-50 p-2 text-sm text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">{aviso}</p>}
        <PreferenciasForm
          key={usuario.id + JSON.stringify(usuario.config)}
          usuario={usuario}
          textoBoton="Guardar preferencias"
          deshabilitado={!!cargando}
          onGuardar={async (p) => {
            const u = await correr("Guardando", () => api.preferencias(p));
            if (u) {
              onCambio(u);
              setAviso("Preferencias guardadas.");
            }
          }}
        />
      </div>

      <div className="space-y-4">
        <div className="card space-y-2">
          <h3 className="font-semibold">Cuenta</h3>
          <p className="text-sm">
            <span className="text-slate-500">Usuario:</span> {usuario.username}
            {usuario.es_admin && <span className="chip ml-2 bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300">admin</span>}
          </p>
          <label className="label">Email (recuperación de contraseña)</label>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button
            className="btn-ghost"
            disabled={!!cargando || email === (usuario.email ?? "")}
            onClick={async () => {
              const u = await correr("Guardando", () => api.preferencias({ email }));
              if (u) {
                onCambio(u);
                setAviso("Email actualizado.");
              }
            }}
          >
            Guardar email
          </button>
        </div>

        <form
          className="card space-y-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (nueva !== nueva2) return setError("Las contraseñas nuevas no coinciden.");
            const r = await correr("Cambiando", () => api.cambiarPassword(actual, nueva));
            if (r) {
              setActual("");
              setNueva("");
              setNueva2("");
              setAviso("Contraseña actualizada. Se cerraron las demás sesiones.");
            }
          }}
        >
          <h3 className="font-semibold">Cambiar contraseña</h3>
          <input className="input" type="password" placeholder="Actual" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} required />
          <input className="input" type="password" placeholder="Nueva (mín. 8)" autoComplete="new-password" minLength={8} value={nueva} onChange={(e) => setNueva(e.target.value)} required />
          <input className="input" type="password" placeholder="Repite la nueva" autoComplete="new-password" value={nueva2} onChange={(e) => setNueva2(e.target.value)} required />
          <button className="btn-ghost" disabled={!!cargando}>
            Cambiar
          </button>
        </form>
      </div>
    </div>
  );
}
