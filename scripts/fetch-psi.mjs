// Takes a snapshot of the combustion investigations of NASA's Physical Sciences Informatics (PSI) repository.
// The PSI API only allows browser calls from psi.nasa.gov, so a static site cannot query it live:
// run `npm run data:psi` to refresh src/data/psi-snapshot.json, then rebuild.
import { writeFile } from 'node:fs/promises';

const API = 'https://psi.nasa.gov/geode-py/ws/repo/search?term=combustion&source=psi&type=investigation&size=200';
const OUT = new URL('../src/data/psi-snapshot.json', import.meta.url);

const clean = (v) => String(v ?? '').replace(/\s+/g, ' ').trim();
const list = (v) => String(v ?? '').split(/\s{2,}|\n/).map((s) => s.trim()).filter(Boolean);

const res = await fetch(API, { headers: { 'User-Agent': 'flame-in-freefall-snapshot' } });
if (!res.ok) throw new Error(`PSI answered ${res.status}`);
const body = await res.json();
const hits = body?.hits?.hits ?? [];
if (!hits.length) throw new Error('PSI returned no investigation');

const investigations = hits.map(({ _source: s }) => {
  const hw = s['Experiment Hardware'];
  const p = s.Person ?? {};
  return {
    accession: clean(s.Accession),
    acronym: clean(s.Acronym),
    title: clean(s.Title),
    researchArea: clean(s['Research Area']),
    subArea: clean(s['SubResearch Area']),
    platform: clean(s['Flight Platform']),
    projectType: clean(s['Project Type']),
    hardware: clean(typeof hw === 'object' && hw ? hw.Name : hw),
    // PSI returns all first names in one field and all last names in another; kept as given
    investigatorLastNames: clean(p['Last Name']),
    keywords: list(s.Keywords),
    objectives: clean(s.Objectives),
    approach: clean(s.Approach),
    impacts: clean(s['Research Impacts/Earth Benefits']),
    related: list(s['Related Investigations']),
    releaseDate: s['Public Release Date'] ? new Date(s['Public Release Date'] * 1000).toISOString().slice(0, 10) : '',
  };
}).sort((a, b) => Number(a.accession.replace(/\D/g, '')) - Number(b.accession.replace(/\D/g, '')));

const snapshot = { source: API, fetchedAt: new Date().toISOString().slice(0, 10), count: investigations.length, investigations };
await writeFile(OUT, JSON.stringify(snapshot, null, 2) + '\n');
console.log(`Saved ${investigations.length} investigations to src/data/psi-snapshot.json`);
