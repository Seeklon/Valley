import { useState } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  Box,
  CheckCircle2,
  Cpu,
  Database,
  FileText,
  Microscope,
  ShieldCheck,
  Wind,
} from 'lucide-react';
import { format, usableModel } from '../data';
import type { ModelInfo, Scene, Source } from '../types';
import { ModelConsistency, ModelDomain, ModelEvaluation } from './ModelDetails';

function safeUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value, window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function ObservationsTable({ value }: { value: unknown }) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const rows = Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    : [];
  const normalized = query.toLocaleLowerCase('fr').trim();
  const filtered = rows.filter((row) =>
    `${row.test_id ?? ''} ${row.material ?? ''}`.toLocaleLowerCase('fr').includes(normalized),
  );
  const count = Math.max(1, Math.ceil(filtered.length / 12));
  const shown = filtered.slice(page * 12, page * 12 + 12);
  if (!rows.length) return <p className="field-help">Aucune observation structurée disponible.</p>;
  return (
    <div className="observations-browser">
      <div className="observations-toolbar">
        <input
          className="text-input"
          aria-label="Filtrer les observations par matériau ou identifiant"
          placeholder="Rechercher un matériau ou un essai…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(0);
            setSelected(null);
          }}
        />
        <span>
          {filtered.length} / {rows.length} entrées
        </span>
      </div>
      <div className="observations-scroll">
        <table>
          <thead>
            <tr>
              <th>Essai / ligne source</th>
              <th>Matériau décrit</th>
              <th>O₂ initial</th>
              <th>Écoulement</th>
              <th>Combustion</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => (
              <tr key={`${row.test_id}-${index}`}>
                <td>
                  <button className="observation-select" onClick={() => setSelected(row)}>
                    {String(row.test_id ?? 'Sans identifiant')}
                  </button>
                  <small>Ligne {String(row.csv_line ?? '—')}</small>
                </td>
                <td>{String(row.material ?? 'Non renseigné')}</td>
                <td>{format(row.oxygen_initial_percent, 1)} %</td>
                <td>{format(row.airflow_m_s, 3)} m/s</td>
                <td>{format(row.burn_time_s, 1)} s</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && <p className="field-help">Aucune entrée ne correspond à cette recherche.</p>}
      </div>
      <div className="observations-pagination">
        <span>« — » : mesure absente du tableau importé.</span>
        <button disabled={page === 0} onClick={() => setPage(page - 1)}>
          Précédent
        </button>
        <span>
          {page + 1} / {count}
        </span>
        <button disabled={page >= count - 1} onClick={() => setPage(page + 1)}>
          Suivant
        </button>
      </div>
      {selected && (
        <div className="observation-detail">
          <div>
            <strong>Entrée source : {String(selected.test_id ?? '')}</strong>
            <button onClick={() => setSelected(null)}>Fermer</button>
          </div>
          <pre>{JSON.stringify(selected, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

export function ModelsView({ models, connected }: { models: ModelInfo[]; connected: boolean }) {
  return (
    <div className="library-view">
      <div className="section-intro">
        <span className="eyebrow cyan-text">REGISTRE DES MODÈLES</span>
        <h1>Des prédictions, avec leurs preuves.</h1>
        <p>
          Les poids chargés, leur domaine d’utilisation déclaré et les mesures de validation sont fournis par
          le poste de calcul.
        </p>
      </div>
      {!models.length ? (
        <div className="large-empty panel">
          <Cpu size={40} strokeWidth={1} />
          <h2>{connected ? 'Aucun modèle entraîné disponible' : 'Registre momentanément inaccessible'}</h2>
          <p>
            {connected
              ? 'Lorsqu’un entraînement est validé et ses poids enregistrés, le modèle apparaît ici. Les simulations physiques restent indépendantes de ce registre.'
              : 'Reconnectez le poste de calcul pour consulter les modèles effectivement chargés.'}
          </p>
        </div>
      ) : (
        <div className="model-list">
          {models.map((model) => (
            <article className="panel model-card" key={model.id}>
              <div className="model-header">
                <span className="model-icon">
                  <Cpu size={24} />
                </span>
                <span className={`status-chip ${usableModel(model) ? 'success' : ''}`}>
                  <span className="status-dot" />
                  {usableModel(model) ? 'Poids chargés' : (model.status ?? 'Non chargé')}
                </span>
              </div>
              <h2>{model.name ?? model.id}</h2>
              <code>{model.id}</code>
              {model.description && <p>{model.description}</p>}
              {model.kind === 'spatial_mlp' && (
                <p>Prédit les champs 3D au cours du temps et leurs métriques.</p>
              )}
              {model.kind === 'scalar_forest' && (
                <p>Prédit les courbes de métriques. Aucun champ 3D n’est produit par ce modèle.</p>
              )}
              <ModelConsistency model={model} />
              <div className="model-section">
                <h3>
                  <ShieldCheck size={14} /> Domaine d’utilisation
                </h3>
                <ModelDomain domain={model.domain} />
              </div>
              <div className="model-section">
                <h3>
                  <CheckCircle2 size={14} /> Évaluation conservée
                </h3>
                <ModelEvaluation model={model} />
              </div>
              {model.scientific_status && <p className="model-note">{model.scientific_status}</p>}
              <details className="raw-details">
                <summary>Voir les métadonnées complètes</summary>
                <pre>{JSON.stringify(model, null, 2)}</pre>
              </details>
            </article>
          ))}
        </div>
      )}
      <div className="info-strip">
        <Microscope size={20} />
        <p>
          La fidélité à un simulateur et l’accord avec une expérience sont deux évaluations distinctes. Les
          résultats synthétiques conservent leur provenance.
        </p>
      </div>
    </div>
  );
}

export function SourcesView({ sources }: { sources: Source[] }) {
  return (
    <div className="library-view">
      <div className="section-intro">
        <span className="eyebrow cyan-text">BIBLIOTHÈQUE EXPÉRIMENTALE</span>
        <h1>Remonter du résultat à la source.</h1>
        <p>
          Expériences, documents et observations NASA conservés avec leur provenance. Une référence
          documentaire ne constitue pas une validation du simulateur.
        </p>
      </div>
      {!sources.length ? (
        <div className="large-empty panel">
          <Database size={40} strokeWidth={1} />
          <h2>Aucune source chargée</h2>
          <p>
            Le service doit fournir les références importées et leurs observations. Aucune donnée
            expérimentale n’est générée par l’interface.
          </p>
        </div>
      ) : (
        <div className="source-list">
          {sources.map((source, index) => (
            <article className="panel source-card" key={source.id ?? index}>
              <span className="source-number">{String(index + 1).padStart(2, '0')}</span>
              <div className="source-content">
                <div className="source-kicker">
                  <FileText size={13} />
                  {source.id ?? 'SOURCE DOCUMENTAIRE'}
                  {source.status && (
                    <span>
                      {source.status === 'experimental_inventory' ? 'INVENTAIRE EXPÉRIMENTAL' : source.status}
                    </span>
                  )}
                </div>
                <h2>{source.name ?? source.title ?? 'Référence'}</h2>
                {source.description && <p>{source.description}</p>}
                {source.doi && <code>DOI {source.doi}</code>}
                {source.observations !== undefined && (
                  <details className="raw-details">
                    <summary>
                      Explorer les observations importées
                      {Array.isArray(source.observations) ? ` (${source.observations.length})` : ''}
                    </summary>
                    <ObservationsTable value={source.observations} />
                  </details>
                )}
                <details className="raw-details">
                  <summary>Provenance & métadonnées</summary>
                  <pre>
                    {JSON.stringify(
                      Object.fromEntries(Object.entries(source).filter(([key]) => key !== 'observations')),
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </div>
              {safeUrl(source.url) && (
                <a
                  className="icon-link"
                  href={safeUrl(source.url)}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Ouvrir la source ${source.name ?? source.title ?? index + 1}`}
                >
                  <ArrowUpRight size={19} />
                </a>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function ScenePreview({ scene, index }: { scene: Scene; index: number }) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <div className={`scene-diagram variant-${index}`}>
      {!loaded && (
        <div className="room-grid" aria-hidden="true">
          <div className="room-outline">
            <i />
            <i />
            <i />
            <i />
            <i />
            <span>
              <Wind size={30} />
            </span>
          </div>
        </div>
      )}
      {!failed && (
        <img
          className={`scene-preview-image ${loaded ? 'loaded' : ''}`}
          src={scene.preview_url ?? scene.asset_url.replace(/\.glb$/, '-overview.png')}
          alt={`Rendu Blender de ${scene.name}`}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      )}
      <span>{String(index + 1).padStart(2, '0')}</span>
      <span className="diagram-label">{loaded ? 'RENDU DE LA SCÈNE BLENDER' : 'SCHÉMA DE LA VARIANTE'}</span>
    </div>
  );
}

export function ScenesView({
  scenes,
  selectedId,
  onSelect,
}: {
  scenes: Scene[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="library-view">
      <div className="section-intro">
        <span className="eyebrow cyan-text">ENVIRONNEMENTS DE CALCUL</span>
        <h1>Une géométrie. Des conditions explicites.</h1>
        <p>
          Chaque scène associe son modèle Blender, ses matériaux, ses ouvertures et ses capteurs dans le même
          repère physique.
        </p>
      </div>
      {!scenes.length ? (
        <div className="large-empty panel">
          <Box size={40} strokeWidth={1} />
          <h2>Catalogue indisponible</h2>
          <p>Les scènes seront affichées quand le service sera connecté.</p>
        </div>
      ) : (
        <div className="scene-library-grid">
          {scenes.map((scene, index) => (
            <article className="panel scene-card" key={scene.id}>
              <ScenePreview scene={scene} index={index} />
              <div className="scene-card-body">
                <div className="source-kicker">
                  {scene.id}
                  <span>{scene.id === selectedId ? 'SÉLECTIONNÉE' : 'SCÈNE 3D'}</span>
                </div>
                <h2>{scene.name}</h2>
                <p>{scene.description}</p>
                <dl className="scene-specs">
                  <div>
                    <dt>Dimensions</dt>
                    <dd>{scene.bounds_m.map((n) => format(n, 1)).join(' × ')} m</dd>
                  </div>
                  <div>
                    <dt>Objets physiques</dt>
                    <dd>{scene.objects.filter((object) => object.role !== 'decoration').length}</dd>
                  </div>
                  <div>
                    <dt>Ventilation / capteurs</dt>
                    <dd>
                      {scene.vents.length} / {scene.sensors.length}
                    </dd>
                  </div>
                </dl>
                <div className="scene-card-actions">
                  <button className="button secondary" onClick={() => onSelect(scene.id)}>
                    Ouvrir le laboratoire <ArrowUpRight size={15} />
                  </button>
                  <a
                    href={scene.asset_url}
                    download
                    className="icon-link"
                    title="Télécharger le GLB"
                    aria-label={`Télécharger ${scene.name} au format GLB`}
                  >
                    <ArrowDownToLine size={16} />
                  </a>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
