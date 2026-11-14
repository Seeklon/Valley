import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('pause de la campagne de scénarios', () => {
  it.each([true, false])('transmet explicitement paused=%s sans créer de calcul', async (paused) => {
    const response = { progress: null, pause_requested: paused };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(response)));
    vi.stubGlobal('fetch', fetchMock);
    expect(await api.pauseIncidentCampaign(paused)).toEqual(response);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/incidents/campaign/pause?paused=${paused}`);
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('question facultative de l’interprétation préventive', () => {
  const response = {
    summary: 'Synthèse du serveur',
    method: 'extractive',
    model: null,
    evidence_ids: [],
    limitations: [],
  };

  it.each(['', ' \t\n '])(
    'laisse le serveur appliquer sa question par défaut pour une saisie vide (%j)',
    async (question) => {
      const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(response)));
      vi.stubGlobal('fetch', fetchMock);

      expect(await api.preventionInterpret('analysis-id', 'component-id', question)).toEqual(response);
      expect(fetchMock.mock.calls[0][0]).toBe('/api/prevention/interpret');
      expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
        analysis_id: 'analysis-id',
        component_id: 'component-id',
      });
    },
  );

  it('transmet la question renseignée sans espaces de bord', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(response)));
    vi.stubGlobal('fetch', fetchMock);

    await api.preventionInterpret('analysis-id', 'component-id', '  Quelles limites pour ce fil ?  ');
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).question).toBe(
      'Quelles limites pour ce fil ?',
    );
  });
});
