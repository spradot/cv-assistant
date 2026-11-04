export type Seccion = {
  indice: number;
  nivel: number;
  titulo: string;
  inicio: number;
  fin: number;
  contenido: string;
};

export type Docs = {
  contenido: string;
  secciones: Seccion[];
  respaldos: string[];
  respaldo?: string | null;
  excluidas_ia: string[];
  caracteres_total: number;
  caracteres_ia: number;
  tokens_ia: number;
};

export type ConfigUsuario = {
  nombre_archivo: string;
  piso_salarial: string;
  modalidad: string;
  angulos: Record<string, string>;
  excluidas_ia: string[];
};

export type Usuario = {
  id: number;
  username: string;
  email: string | null;
  nombre: string;
  es_admin: boolean;
  onboarding_completo: boolean;
  config: ConfigUsuario;
};

export type EstadoAuth = { usuario: Usuario | null; smtp: boolean; registro: boolean; primer_usuario: boolean; requiere_codigo: boolean };

export type FilaUso = {
  operacion: string;
  proveedor: string;
  llamadas?: number;
  prompt?: number;
  cache?: number;
  salida?: number;
  razonamiento?: number;
  ms: number;
  prompt_tokens?: number;
  cache_hit_tokens?: number;
  completion_tokens?: number;
  reasoning_tokens?: number;
  creado_en?: string;
};

export type PreviewCV = { cv_yaml: string; diff: string; sin_cambios: boolean };

export type PreferenciasInput = Partial<Omit<ConfigUsuario, "excluidas_ia">> & { email?: string };

export type Propuesta = { propuesto: string; diff: string; sin_cambios: boolean; caracteres_extraidos?: number };

export type CvBase = { cv_yaml: string | null; version: number | null; paginas?: number };
export type BorradorCvBase = { cv_yaml: string; angulo: string; diff: string };

export type RecomendacionATS = { keyword: string; respaldada: boolean; recomendacion: string };

export type SugerenciaDoc = { titulo: string; tipo: string; detalle: string; instruccion: string };

export type Resumen = {
  id: number;
  empresa: string;
  estado: string;
  fit_score: number | null;
  recomendacion: string | null;
  angulo: string | null;
  ats_cobertura: number | null;
  creado_en: string;
  actualizado_en: string;
};

export type Postulacion = Resumen & {
  empresa_original: string;
  oferta_texto: string;
  clasificador: string;
  cumple_excluyentes: boolean;
  banda_salarial_ok: boolean;
  modalidad_ok: boolean;
  razones: string;
  cv?: Record<string, unknown> | null;
  cv_yaml?: string | null;
  pdf_path?: string;
  paginas?: number;
  banda_salarial?: string;
  experiencia_200?: string;
  habilidades_200?: string;
  pretension_renta?: string;
  disponibilidad?: string;
  modalidad_preferida?: string;
  ats_keywords?: string[];
  ats_keywords_presentes?: string[];
  ats_keywords_faltantes?: string[];
  ats_parseo_ok?: boolean;
  ats_detalle_parseo?: string;
  ats_recomendaciones?: RecomendacionATS[] | null;
  historial?: { accion: string; ats_cobertura: number; paginas: number }[];
  n_versiones: number;
};

export type Job = {
  id: number;
  postulacion_id: number;
  empresa: string;
  estado: "pendiente" | "ejecutando" | "listo" | "error";
  etapa: string | null;
  error: string | null;
};

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const res = await fetch(url, init);
  if (res.status === 401 && !url.startsWith("/api/auth/")) {
    window.dispatchEvent(new Event("sesion-expirada"));
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (data.detail) msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* respuesta sin JSON */
    }
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  estado: () => req<EstadoAuth>("GET", "/api/auth/estado"),
  login: (username: string, password: string) => req<Usuario>("POST", "/api/auth/login", { username, password }),
  registro: (body: { username: string; password: string; nombre: string; email?: string; codigo?: string }) =>
    req<Usuario>("POST", "/api/auth/registro", body),
  logout: () => req<{ ok: boolean }>("POST", "/api/auth/logout"),
  olvide: (usuario: string) => req<{ mensaje: string }>("POST", "/api/auth/olvide", { usuario }),
  reset: (token: string, password: string) => req<{ ok: boolean }>("POST", "/api/auth/reset", { token, password }),
  cambiarPassword: (actual: string, nueva: string) => req<{ ok: boolean }>("POST", "/api/cuenta/password", { actual, nueva }),
  preferencias: (body: PreferenciasInput) => req<Usuario>("POST", "/api/cuenta/preferencias", body),
  uso: (dias = 30) => req<{ por_operacion: FilaUso[]; recientes: FilaUso[] }>("GET", `/api/uso?dias=${dias}`),

  cvPrueba: () => req<{ texto: string }>("GET", "/api/onboarding/cv-prueba"),
  onboardingDoc: (opts: { archivo?: File | null; usarPrueba?: boolean; descripcion?: string }) => {
    const fd = new FormData();
    if (opts.archivo) fd.append("archivo", opts.archivo);
    fd.append("usar_prueba", String(!!opts.usarPrueba));
    fd.append("descripcion", opts.descripcion ?? "");
    return req<{ propuesto: string; caracteres_extraidos: number }>("POST", "/api/onboarding/documentacion", fd);
  },
  onboardingCompletar: (contenido: string, preferencias: PreferenciasInput) =>
    req<Usuario>("POST", "/api/onboarding/completar", { contenido, preferencias }),

  config: () => req<{ classifier_provider: string; modelo: string }>("GET", "/api/config"),

  docs: () => req<Docs>("GET", "/api/docs"),
  docsUpload: (archivo: File, modo: string) => {
    const fd = new FormData();
    fd.append("archivo", archivo);
    fd.append("modo", modo);
    return req<Propuesta>("POST", "/api/docs/upload", fd);
  },
  docsInstruccion: (instruccion: string) => req<Propuesta>("POST", "/api/docs/instruccion", { instruccion }),
  docsSeccion: (body: { indice: number; titulo: string; accion: string; instruccion?: string; contenido?: string }) =>
    req<Propuesta>("POST", "/api/docs/seccion", body),
  docsExcluir: (titulo: string, excluir: boolean) => req<Docs>("POST", "/api/docs/excluir", { titulo, excluir }),
  docsDiff: (contenido: string) => req<Propuesta>("POST", "/api/docs/diff", { contenido }),
  docsGuardar: (contenido: string) => req<Docs>("POST", "/api/docs/guardar", { contenido }),
  docsRespaldo: (nombre: string) => req<{ contenido: string }>("GET", `/api/docs/respaldos/${encodeURIComponent(nombre)}`),

  cvBase: () => req<CvBase>("GET", "/api/docs/cv-base"),
  cvBaseBorrador: (angulo?: string) => req<BorradorCvBase>("POST", "/api/docs/cv-base/borrador", { angulo: angulo || null }),
  cvBaseRender: (cv_yaml: string, angulo?: string) => req<CvBase>("POST", "/api/docs/cv-base/render", { cv_yaml, angulo: angulo || null }),
  cvBasePdfUrl: (version: string | number, descargar = false) =>
    `/api/docs/cv-base/pdf?v=${encodeURIComponent(String(version))}${descargar ? "&descargar=true" : ""}`,

  listar: () => req<Resumen[]>("GET", "/api/postulaciones"),
  crear: (empresa: string, oferta_texto: string) => req<Postulacion>("POST", "/api/postulaciones", { empresa, oferta_texto }),
  obtener: (id: number) => req<Postulacion>("GET", `/api/postulaciones/${id}`),
  eliminar: (id: number) => req<{ ok: boolean }>("DELETE", `/api/postulaciones/${id}`),
  angulo: (id: number, angulo: string) => req<Postulacion>("POST", `/api/postulaciones/${id}/angulo`, { angulo }),
  generar: (id: number, feedback?: string) => req<{ job: Job }>("POST", `/api/postulaciones/${id}/generar`, { feedback: feedback || null }),
  jobs: () => req<Job[]>("GET", "/api/jobs"),
  jobVisto: (id: number) => req<{ ok: boolean }>("POST", `/api/jobs/${id}/visto`),
  atsRecomendaciones: (id: number) => req<RecomendacionATS[]>("POST", `/api/postulaciones/${id}/ats-recomendaciones`),
  ajustarPreview: (id: number, instruccion: string) =>
    req<PreviewCV>("POST", `/api/postulaciones/${id}/ajustar/preview`, { instruccion }),
  yaml: (id: number, cv_yaml: string, accion?: string) => req<Postulacion>("POST", `/api/postulaciones/${id}/yaml`, { cv_yaml, accion }),
  deshacer: (id: number) => req<Postulacion>("POST", `/api/postulaciones/${id}/deshacer`),
  sugerenciasDoc: (id: number) => req<SugerenciaDoc[]>("POST", `/api/postulaciones/${id}/sugerencias-doc`),
  decision: (id: number, accion: "aprobar" | "descartar") => req<Postulacion>("POST", `/api/postulaciones/${id}/decision`, { accion }),
  pdfUrl: (id: number, version: string, descargar = false) =>
    `/api/postulaciones/${id}/pdf?v=${encodeURIComponent(version)}${descargar ? "&descargar=true" : ""}`,
};
