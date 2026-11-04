import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job } from "../api";

const ACTIVO = (j: Job) => j.estado === "pendiente" || j.estado === "ejecutando";

/** Sigue las generaciones de CV en segundo plano: consulta cada 4 s mientras haya alguna activa
 *  (y al volver a la pestaña o tras encolar una) y llama a `onTerminado` UNA vez por job al
 *  terminar, aunque haya terminado mientras la pestaña estaba cerrada. */
export function useJobs(onTerminado: (j: Job) => void) {
  const [activos, setActivos] = useState<Job[]>([]);
  const alTerminar = useRef(onTerminado);
  alTerminar.current = onTerminado;
  const notificados = useRef(new Set<number>());

  const refrescar = useCallback(async () => {
    try {
      const lista = await api.jobs();
      setActivos(lista.filter(ACTIVO));
      for (const j of lista) {
        if (!ACTIVO(j) && !notificados.current.has(j.id)) {
          notificados.current.add(j.id);
          alTerminar.current(j);
          api.jobVisto(j.id).catch(() => {});
        }
      }
    } catch {
      /* red caída o sesión vencida: el próximo ciclo reintenta */
    }
  }, []);

  const hayActivos = activos.length > 0;
  useEffect(() => {
    if (!hayActivos) return;
    const t = setInterval(refrescar, 4000);
    return () => clearInterval(t);
  }, [hayActivos, refrescar]);

  useEffect(() => {
    refrescar();
    const alVolver = () => document.visibilityState === "visible" && refrescar();
    window.addEventListener("jobs-cambio", refrescar);
    document.addEventListener("visibilitychange", alVolver);
    return () => {
      window.removeEventListener("jobs-cambio", refrescar);
      document.removeEventListener("visibilitychange", alVolver);
    };
  }, [refrescar]);

  return { activos, refrescar };
}
