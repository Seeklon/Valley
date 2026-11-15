/* Investigations shown in the side panel.
   Facts (accession, title, platform, hardware, objectives) come from the PSI snapshot.
   The theme, the short labels and the relevance flags are our own reading of each record: the PSI API has no such fields. */
import snapshot from './psi-snapshot.json';

export type Theme = 'prev' | 'det' | 'sup' | 'fun';

export interface Investigation {
  /** short name shown on the card: the PSI acronym, or the accession when PSI gives none */
  id: string;
  /** PSI accession, e.g. "PSI-98" */
  psi: string;
  name: string;
  ax: Theme;
  fuel: string;
  hw: string;
  plat: string;
  obj: string;
  /** what the experiment varies, in a few words */
  cond: string;
  /** large-scale burning */
  big?: 1;
  /** elevated oxygen or other exploration-atmosphere conditions */
  hi?: 1;
  /** partial-gravity stand-in */
  pg?: 1;
  cite: string;
  url: string;
}

interface Curated {
  id?: string;
  ax: Theme;
  fuel: string;
  cond: string;
  big?: 1;
  hi?: 1;
  pg?: 1;
}

/* Our classification, by accession. Records not listed fall back to a keyword reading (see `guess`). */
const CURATED: Record<string, Curated> = {
  'PSI-98': { id: 'Saffire-I', ax: 'prev', fuel: 'Solid', cond: 'Large fabric sample, cabin airflow', big: 1, hi: 1 },
  'PSI-99': { id: 'Saffire-II', ax: 'prev', fuel: 'Solid', cond: 'Several material samples', big: 1, hi: 1 },
  'PSI-100': { id: 'Saffire-III', ax: 'prev', fuel: 'Solid', cond: 'Large sample, airflow', big: 1, hi: 1 },
  'PSI-25': { ax: 'prev', fuel: 'Solid', cond: 'Oxygen level, airflow speed', hi: 1 },
  'PSI-26': { ax: 'prev', fuel: 'Solid', cond: 'Airflow speed, sample shape' },
  'PSI-20': { ax: 'prev', fuel: 'Gas', cond: 'Material properties, still air', hi: 1 },
  'PSI-62': { id: 'Flame spread model', ax: 'prev', fuel: 'Solid (model)', cond: 'Concurrent-flow flame spread, simulated' },
  'PSI-102': { ax: 'det', fuel: 'Smoke', cond: 'Smoke source, particle size' },
  'PSI-101': { ax: 'det', fuel: 'Smoke', cond: 'Fire-retardant material added' },
  'PSI-47': { id: 'DAFT', ax: 'det', fuel: 'Dust and aerosol', cond: 'Airborne particle counts' },
  'PSI-115': { id: 'SAME data study', ax: 'det', fuel: 'Smoke (model)', cond: 'Aerosol growth, simulated from SAME data' },
  'PSI-69': { ax: 'sup', fuel: 'Liquid droplets', cond: 'CO₂ and helium dilution' },
  'PSI-68': { ax: 'sup', fuel: 'Liquid droplets', cond: 'Fuel type, atmosphere' },
  'PSI-39': { ax: 'fun', fuel: 'Liquid droplets', cond: 'Pressure from 0.25 to 5 atm' },
  'PSI-117': { id: 'Cool-flame perturbation', ax: 'fun', fuel: 'Liquid droplets', cond: 'External thermo-convective perturbation' },
  'PSI-142': { id: 'Cool-flame transitions', ax: 'fun', fuel: 'Liquid droplets', cond: 'Radiative extinction, cool-flame onset' },
  'PSI-159': { ax: 'fun', fuel: 'Gas', cond: 'Oxidizer up to 85 % O₂', hi: 1 },
  'PSI-22': { id: 'ACME E-FIELD', ax: 'fun', fuel: 'Gas', cond: 'Field strength', pg: 1 },
  'PSI-10': { id: 'ACME Flame Design', ax: 'fun', fuel: 'Gas', cond: 'Dilution, flow rate, pressure' },
  'PSI-21': { ax: 'fun', fuel: 'Gas', cond: 'Fuel dilution, coflow speed' },
  'PSI-23': { ax: 'fun', fuel: 'Gas', cond: 'Flow rate, dilution' },
  'PSI-106': { ax: 'fun', fuel: 'Gas', cond: 'Fuel, flow speed' },
  'PSI-107': { ax: 'fun', fuel: 'Gas', cond: 'Fuel, co-flow speed' },
  'PSI-60': { id: 'SPICE data study', ax: 'fun', fuel: 'Gas (model)', cond: 'Computed against SPICE flames' },
};

type Raw = (typeof snapshot.investigations)[number];

function guess(r: Raw): Curated {
  const t = `${r.title} ${r.subArea} ${r.keywords.join(' ')}`.toLowerCase();
  const ax: Theme = /smoke|aerosol|detect/.test(t) ? 'det' : /extinguish|suppress/.test(t) ? 'sup' : /flammab|spread|material|fire safety/.test(t) ? 'prev' : 'fun';
  const fuel = /droplet/.test(t) ? 'Liquid droplets' : /smoke|aerosol/.test(t) ? 'Smoke' : /solid|fabric|material/.test(t) ? 'Solid' : 'Gas';
  return { ax, fuel, cond: r.subArea || 'See the PSI record' };
}

const PLATFORM: Record<string, string> = {
  'International Space Station (ISS)': 'ISS',
  'Cygnus Spacecraft': 'Cygnus',
  'Not Applicable': 'Ground / analysis',
  '': 'Ground / analysis',
};

/** first sentences of a PSI text field, kept under `max` characters */
function lead(text: string, max = 260): string {
  const parts = text.split(/(?<=[.!?])\s+/);
  let out = '';
  for (const s of parts) {
    if (out && (out + ' ' + s).length > max) break;
    out = out ? out + ' ' + s : s;
  }
  return out.length > max ? out.slice(0, max - 1).trimEnd() + '…' : out;
}

/* The PSI search for "combustion" also returns a few records from other research areas; only combustion science is kept. */
export const INVESTIGATIONS: Investigation[] = snapshot.investigations
  .filter((r) => r.researchArea === 'Combustion Science')
  .map((r) => {
    const c = CURATED[r.accession] ?? guess(r);
    const id = c.id ?? (r.acronym || r.accession);
    return {
      id,
      psi: r.accession,
      name: r.title,
      ax: c.ax,
      fuel: c.fuel,
      hw: r.hardware || 'Not listed in PSI',
      plat: PLATFORM[r.platform] ?? r.platform,
      obj: lead(r.objectives) || 'Not listed in PSI',
      cond: c.cond,
      big: c.big,
      hi: c.hi,
      pg: c.pg,
      cite: `${r.title} (${r.accession}). NASA Physical Sciences Informatics repository, psi.nasa.gov. Record read on ${snapshot.fetchedAt}.`,
      url: `https://psi.nasa.gov/physci/repo/search?q=${encodeURIComponent(r.accession)}`,
    };
  });

export const SNAPSHOT_DATE: string = snapshot.fetchedAt;
