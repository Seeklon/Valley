import type {
  Campaign,
  CampaignRequest,
  Catalog,
  Health,
  Insight,
  ModelInfo,
  Run,
  RunConfig,
  Source,
} from './types';
import type {
  PreventionCatalog,
  PreventionConfig,
  PreventionEvidence,
  PreventionInterpretation,
  PreventionResult,
} from './prevention';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options: RequestInit = {}, timeoutMs = 20_000): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    signal: options.signal
      ? AbortSignal.any([options.signal, AbortSignal.timeout(timeoutMs)])
      : AbortSignal.timeout(timeoutMs),
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  if (!response.ok) {
    let detail = `Le service a retourné une erreur ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: unknown; message?: string };
      detail = typeof body.detail === 'string' ? body.detail : (body.message ?? detail);
      if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((entry: { loc?: unknown[]; msg?: unknown }) => {
            const field = Array.isArray(entry.loc) ? entry.loc.slice(1).join('.') : '';
            return `${field ? `${field} : ` : ''}${typeof entry.msg === 'string' ? entry.msg : 'Valeur invalide'}`;
          })
          .join(' · ');
      }
    } catch {
      /* Keep HTTP error, not a parse failure. */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>('/health'),
  scenes: () => request<Catalog>('/scenes'),
  models: async () => {
    const response = await request<ModelInfo[] | { models: ModelInfo[] }>('/models');
    return Array.isArray(response) ? response : (response.models ?? []);
  },
  sources: async () => {
    const response = await request<Source[] | { sources: Source[] }>('/sources');
    return Array.isArray(response) ? response : (response.sources ?? []);
  },
  launch: (config: RunConfig) => request<Run>('/runs', { method: 'POST', body: JSON.stringify(config) }),
  run: (id: string, signal?: AbortSignal) => request<Run>(`/runs/${encodeURIComponent(id)}`, { signal }),
  cancel: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  exportUrl: (id: string) => `/api/runs/${encodeURIComponent(id)}/export`,
  launchCampaign: (config: CampaignRequest) =>
    request<Campaign>('/campaigns', { method: 'POST', body: JSON.stringify(config) }),
  campaign: (id: string, signal?: AbortSignal) =>
    request<Campaign>(`/campaigns/${encodeURIComponent(id)}`, { signal }),
  cancelCampaign: (id: string) =>
    request<Campaign>(`/campaigns/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  campaignExportUrl: (id: string) => `/api/campaigns/${encodeURIComponent(id)}/export`,
  insights: (config: RunConfig, question: string, signal?: AbortSignal) =>
    request<Insight>(
      '/insights',
      { method: 'POST', body: JSON.stringify({ config, question }), signal },
      120_000,
    ),
  preventionCatalog: (signal?: AbortSignal) => request<PreventionCatalog>('/prevention/catalog', { signal }),
  preventionAnalyze: (config: PreventionConfig, signal?: AbortSignal) =>
    request<PreventionResult>(
      '/prevention/analyze',
      { method: 'POST', body: JSON.stringify(config), signal },
      60_000,
    ),
  preventionEvidence: (componentId: string, config: PreventionConfig, signal?: AbortSignal) => {
    const query = new URLSearchParams({
      component_id: componentId,
      gravity_g: String(config.gravity_g),
      oxygen_percent: String(config.oxygen_percent),
      airflow_m_s: String(config.airflow_m_s),
      pressure_pa: String(config.pressure_pa),
    });
    return request<PreventionEvidence>(`/prevention/evidence?${query}`, { signal });
  },
  preventionInterpret: (analysisId: string, componentId: string, question: string, signal?: AbortSignal) =>
    request<PreventionInterpretation>(
      '/prevention/interpret',
      {
        method: 'POST',
        body: JSON.stringify({
          analysis_id: analysisId,
          component_id: componentId,
          question: question.trim() || undefined,
        }),
        signal,
      },
      120_000,
    ),
  preventionExportUrl: (id: string) => `/api/prevention/analyses/${encodeURIComponent(id)}/export`,
};

export function messageOf(error: unknown): string {
  if (error instanceof Error) {
    if (error.name === 'TimeoutError')
      return 'Le service met trop de temps à répondre. Le calcul peut continuer sur le poste de travail.';
    if (error instanceof TypeError)
      return 'Connexion au service impossible. Vérifiez que le poste de calcul est disponible.';
    return error.message;
  }
  return 'Une erreur inattendue est survenue.';
}
