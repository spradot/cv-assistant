import { useEffect, useState } from "react";
import { api, type FilaUso } from "../api";
import { ErrorBox, Spinner, useAccion } from "./ui";

const NOMBRES: Record<string, string> = {
  clasificar: "Clasificar oferta",
  generar_cv: "Generar CV",
  generar_cv_faltantes: "Generar CV (campos faltantes)",
  reparar_cv: "Reparar CV (rendercv)",
  condensar_cv: "Condensar a 1 página",
  ajustar_cv: "Ajustar CV",
  recomendaciones_ats: "Recomendaciones ATS",
  sugerencias_documentacion: "Sugerencias de documentación",
  editar_documento: "Editar documentación",
  fusionar_cv: "Fusionar CV en documentación",
  crear_documentacion: "Crear documentación",
  seccion_simplificar: "Simplificar sección",
  seccion_reescribir: "Reescribir sección",
  seccion_modificar: "Modificar sección",
  pregunta_abierta: "Pregunta abierta (Telegram)",
};

const n = (x?: number) => (x ?? 0).toLocaleString("es-CL");

export default function Consumo() {
  const [dias, setDias] = useState(30);
  const [datos, setDatos] = useState<{ por_operacion: FilaUso[]; recientes: FilaUso[] } | null>(null);
  const { cargando, error, correr } = useAccion();

  useEffect(() => {
    correr("Cargando", async () => setDatos(await api.uso(dias)));
  }, [dias]);

  if (!datos) return <div className="card">{cargando ? <Spinner label="Cargando…" /> : <ErrorBox error={error} />}</div>;

  const ds = datos.por_operacion.filter((f) => f.proveedor === "deepseek");
  const total = {
    llamadas: datos.por_operacion.reduce((a, f) => a + (f.llamadas ?? 0), 0),
    entrada: ds.reduce((a, f) => a + (f.prompt ?? 0), 0),
    cache: ds.reduce((a, f) => a + (f.cache ?? 0), 0),
    salida: ds.reduce((a, f) => a + (f.salida ?? 0), 0),
  };
  const jev = datos.por_operacion.find((f) => f.proveedor === "jev");

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="mr-auto text-lg font-semibold">Consumo de IA</h2>
        <select className="input w-auto" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
          <option value={1}>Últimas 24 h</option>
          <option value={7}>Últimos 7 días</option>
          <option value={30}>Últimos 30 días</option>
          <option value={365}>Último año</option>
        </select>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat titulo="Llamadas" valor={n(total.llamadas)} detalle={jev ? `${jev.llamadas} con Jev (~${Math.round(jev.ms)} ms)` : undefined} />
        <Stat titulo="Tokens de entrada" valor={n(total.entrada)} detalle="DeepSeek" />
        <Stat
          titulo="Desde caché"
          valor={total.entrada ? `${Math.round((total.cache / total.entrada) * 100)}%` : "—"}
          detalle={`${n(total.cache)} tokens a precio reducido`}
        />
        <Stat titulo="Tokens de salida" valor={n(total.salida)} detalle="la parte más cara" />
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500 dark:bg-slate-800/50">
            <tr>
              <th className="px-3 py-2">Operación</th>
              <th className="px-3 py-2 text-right">Llamadas</th>
              <th className="px-3 py-2 text-right">Entrada</th>
              <th className="px-3 py-2 text-right">Caché</th>
              <th className="px-3 py-2 text-right">Salida</th>
              <th className="px-3 py-2 text-right">Prom. por llamada</th>
              <th className="px-3 py-2 text-right">Latencia</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {datos.por_operacion.map((f) => (
              <tr key={f.operacion + f.proveedor}>
                <td className="px-3 py-2">
                  {NOMBRES[f.operacion] ?? f.operacion}
                  {f.proveedor === "jev" && <span className="chip ml-2 bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">Jev</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{n(f.llamadas)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{f.proveedor === "jev" ? "—" : n(f.prompt)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {f.prompt ? `${Math.round(((f.cache ?? 0) / f.prompt) * 100)}%` : "—"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {f.proveedor === "jev" ? "—" : n(f.salida)}
                  {!!f.razonamiento && <span className="block text-[11px] text-amber-600">{n(f.razonamiento)} razonamiento</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {f.llamadas && f.proveedor !== "jev" ? n(Math.round(((f.prompt ?? 0) + (f.salida ?? 0)) / f.llamadas)) : "—"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{(f.ms / 1000).toFixed(1)} s</td>
              </tr>
            ))}
            {datos.por_operacion.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-slate-500">
                  Sin llamadas en este período.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {datos.recientes.length > 0 && (
        <details className="card">
          <summary className="label cursor-pointer">Últimas {datos.recientes.length} llamadas</summary>
          <table className="mt-2 w-full text-xs">
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {datos.recientes.map((r, i) => (
                <tr key={i}>
                  <td className="py-1 text-slate-500">{r.creado_en?.replace("T", " ")}</td>
                  <td className="py-1">{NOMBRES[r.operacion] ?? r.operacion}</td>
                  <td className="py-1 text-right tabular-nums">
                    {r.proveedor === "jev" ? "Jev" : `${n(r.prompt_tokens)} in (${n(r.cache_hit_tokens)} caché) · ${n(r.completion_tokens)} out`}
                  </td>
                  <td className="py-1 text-right tabular-nums">{((r.ms ?? 0) / 1000).toFixed(1)} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function Stat({ titulo, valor, detalle }: { titulo: string; valor: string; detalle?: string }) {
  return (
    <div className="card">
      <div className="label">{titulo}</div>
      <div className="text-2xl font-bold tabular-nums">{valor}</div>
      {detalle && <div className="text-xs text-slate-500">{detalle}</div>}
    </div>
  );
}
