import { useState, type FormEvent } from "react";
import { api, type EstadoAuth, type Usuario } from "../api";
import { ErrorBox, useAccion } from "./ui";

type Modo = "login" | "registro" | "olvide" | "reset";

export default function Auth({ estado, resetToken, onEntrar }: { estado: EstadoAuth; resetToken: string | null; onEntrar: (u: Usuario) => void }) {
  const [modo, setModo] = useState<Modo>(resetToken ? "reset" : estado.primer_usuario ? "registro" : "login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [codigo, setCodigo] = useState("");
  const [mensaje, setMensaje] = useState<string | null>(null);
  const { cargando, error, setError, correr } = useAccion();

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setMensaje(null);
    if ((modo === "registro" || modo === "reset") && password !== password2) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    if (modo === "login") {
      const u = await correr("Ingresando", () => api.login(username, password));
      if (u) onEntrar(u);
    } else if (modo === "registro") {
      const u = await correr("Creando cuenta", () => api.registro({ username, password, nombre, email: email || undefined, codigo: codigo || undefined }));
      if (u) onEntrar(u);
    } else if (modo === "olvide") {
      const r = await correr("Enviando", () => api.olvide(username));
      if (r) setMensaje(r.mensaje);
    } else if (modo === "reset" && resetToken) {
      const r = await correr("Guardando", () => api.reset(resetToken, password));
      if (r) {
        history.replaceState(null, "", "/");
        setMensaje("Contraseña actualizada. Ya puedes ingresar.");
        setModo("login");
        setPassword("");
        setPassword2("");
      }
    }
  }

  const titulos: Record<Modo, string> = {
    login: "Ingresar",
    registro: estado.primer_usuario ? "Crear la cuenta administradora" : "Crear cuenta",
    olvide: "Recuperar contraseña",
    reset: "Nueva contraseña",
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={enviar} className="card w-full max-w-sm space-y-3">
        <div className="text-center">
          <div className="text-3xl">📋</div>
          <h1 className="text-lg font-semibold">{titulos[modo]}</h1>
          {modo === "registro" && estado.primer_usuario && (
            <p className="mt-1 text-xs text-slate-500">
              La primera cuenta es la administradora. Después podrás cargar tu CV para crear tu perfil.
            </p>
          )}
        </div>
        <ErrorBox error={error} onClose={() => setError(null)} />
        {mensaje && <p className="rounded-lg bg-emerald-50 p-2 text-sm text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">{mensaje}</p>}

        {modo !== "reset" && (
          <div>
            <label className="label">{modo === "olvide" ? "Usuario o email" : "Usuario"}</label>
            <input className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </div>
        )}
        {modo === "registro" && (
          <>
            {estado.requiere_codigo && (
              <div>
                <label className="label">Código de invitación</label>
                <input className="input" value={codigo} onChange={(e) => setCodigo(e.target.value)} required />
              </div>
            )}
            <div>
              <label className="label">Nombre completo</label>
              <input className="input" autoComplete="name" value={nombre} onChange={(e) => setNombre(e.target.value)} required />
            </div>
            <div>
              <label className="label">Email {estado.smtp ? "(para recuperar la contraseña)" : "(opcional)"}</label>
              <input className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
          </>
        )}
        {modo !== "olvide" && (
          <div>
            <label className="label">Contraseña</label>
            <input
              className="input"
              type="password"
              autoComplete={modo === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={modo === "login" ? undefined : 8}
              required
            />
          </div>
        )}
        {(modo === "registro" || modo === "reset") && (
          <div>
            <label className="label">Repite la contraseña</label>
            <input className="input" type="password" autoComplete="new-password" value={password2} onChange={(e) => setPassword2(e.target.value)} required />
          </div>
        )}

        <button className="btn-primary w-full justify-center" disabled={!!cargando}>
          {cargando ? `${cargando}…` : titulos[modo]}
        </button>

        <div className="flex flex-wrap justify-between gap-2 text-xs">
          {modo !== "login" && (
            <button type="button" className="text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setModo("login")}>
              Ya tengo cuenta
            </button>
          )}
          {modo === "login" && estado.registro && (
            <button type="button" className="text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setModo("registro")}>
              Crear cuenta
            </button>
          )}
          {modo === "login" && estado.smtp && (
            <button type="button" className="text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setModo("olvide")}>
              ¿Olvidaste tu contraseña?
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
