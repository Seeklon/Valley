import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { defaultCase, environmentCases, FAMILY_NAMES, INCIDENT_NAMES, loadCase, loadIndex, ROOM_FAMILY } from './catalog';
import type { Environment, Room } from './catalog';
import { issInteriorPose, issPeakFrame, issSampleState, issToWorld } from './iss-poc';
import type { IssCase, IssCaseEntry, IssIndex } from './iss-poc';
import { createIssStationWorld } from './iss-station';
import { createIssPocOverlay } from './overlay';
import type { IssOverlayOptions } from './overlay';
import './room.css';

const escape = (value: unknown) => String(value).replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[c]!);

function disposeWorld(world: THREE.Scene) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  world.traverse(object => {
    const mesh = object as THREE.Mesh;
    if (mesh.geometry) geometries.add(mesh.geometry);
    if (mesh.material) (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach(m => materials.add(m));
    const light = object as THREE.DirectionalLight;
    (light.shadow?.map as THREE.WebGLRenderTarget | null)?.dispose();
  });
  materials.forEach(material => {
    Object.values(material).forEach(value => { if (value instanceof THREE.Texture) textures.add(value); });
    material.dispose();
  });
  textures.forEach(texture => texture.dispose());
  geometries.forEach(geometry => geometry.dispose());
  world.clear();
}

/** Interior-only integration. The original site's exterior and NASA panels own their lifecycle. */
export class PredictionRoom {
  private host = document.createElement('div');
  private status = document.createElement('div');
  private renderer?: THREE.WebGLRenderer;
  private camera = new THREE.PerspectiveCamera(61, 1, 0.025, 250);
  private controls?: OrbitControls;
  private station?: ReturnType<typeof createIssStationWorld>;
  private overlay?: ReturnType<typeof createIssPocOverlay>;
  private index?: IssIndex;
  private data?: IssCase;
  private entries: IssCaseEntry[] = [];
  private environment: Environment = 'iss';
  private controller?: AbortController;
  private revision = 0;
  private observer: ResizeObserver;
  private raf = 0;
  private frameIndex = 0;
  private playing = false;
  private nextFrameAt = 0;
  private dirty = true;
  private overview = false;
  private geometryOnly = false;
  private options: IssOverlayOptions = { display: 'prediction', heat: true, smoke: true };
  private yaw = 0;
  private pitch = 0;
  private drag?: { x: number; y: number };
  private message = 'Loading the verified model export…';

  constructor(private app: HTMLElement, private panel: HTMLElement, private panelChanged: () => void) {
    this.host.id = 'prediction-room';
    this.host.hidden = true;
    this.host.dataset.mode = 'recorded-inference';
    this.status.className = 'ml-status';
    this.status.setAttribute('role', 'status');
    this.host.append(this.status);
    app.insertBefore(this.host, app.querySelector('#fade'));
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(app);
    panel.addEventListener('change', event => this.handleChange(event));
    panel.addEventListener('input', event => {
      const input = event.target as HTMLInputElement;
      if (input.id !== 'ml-time' || !this.data) return;
      this.playing = false;
      this.setFrame(Number(input.value));
    });
    panel.addEventListener('click', event => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-ml-action]');
      if (!button || !this.data || this.host.hidden) return;
      switch (button.dataset.mlAction) {
        case 'play':
          if (this.geometryOnly) return;
          if (this.frameIndex === this.data.frames.length - 1) this.setFrame(0);
          this.playing = !this.playing;
          this.nextFrameAt = performance.now();
          break;
        case 'reset': this.configureCamera(); break;
        case 'view': this.overview = !this.overview; this.configureCamera(); break;
      }
      this.updateReadout();
    });
  }

  async open(room: Room, environment: Environment) {
    this.close();
    this.environment = environment;
    this.host.hidden = false;
    this.panel.hidden = false;
    this.panel.classList.add('ml-controls');
    this.geometryOnly = false;
    this.message = 'Loading the verified model export…';
    this.setStatus(this.message);
    this.drawPanel();
    const revision = ++this.revision;
    this.controller = new AbortController();
    try {
      // Refresh the index on entry: a newly validated retraining can be installed separately.
      const index = await loadIndex(this.controller.signal);
      if (revision !== this.revision) return;
      this.index = index;
      this.entries = environmentCases(index, environment);
      this.geometryOnly = this.entries.length === 0;
      if (this.geometryOnly) this.entries = environmentCases(index, 'iss');
      const entry = defaultCase(index, this.entries, ROOM_FAMILY[room]);
      if (!entry) throw new Error('No compatible geometry in this model export.');
      await this.select(entry.id);
    } catch (error) { this.fail(error, revision); }
  }

  close() {
    ++this.revision;
    this.controller?.abort();
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.releaseScene();
    if (this.controls) this.controls.enabled = false;
    this.drag = undefined;
    this.index = undefined;
    this.entries = [];
    this.data = undefined;
    this.host.hidden = true;
    for (const key of ['caseId', 'modelSha', 'timeS', 'heatCount', 'smokeCount', 'state']) delete this.host.dataset[key];
    this.panel.classList.remove('ml-controls');
  }

  private releaseScene() {
    this.overlay?.dispose();
    this.overlay = undefined;
    if (this.station) disposeWorld(this.station.world);
    this.station = undefined;
    this.data = undefined;
    this.renderer?.clear();
  }

  private setStatus(message: string, error = false) {
    this.status.textContent = message;
    this.status.hidden = !message;
    this.host.dataset.state = message ? error ? 'error' : 'loading' : 'ready';
  }

  private fail(error: unknown, revision: number) {
    if (revision !== this.revision || (error instanceof DOMException && error.name === 'AbortError')) return;
    this.releaseScene();
    this.message = error instanceof Error ? error.message : 'Unable to load the model export.';
    this.setStatus(this.message, true);
    this.drawPanel();
  }

  private async select(id: string) {
    const entry = this.entries.find(item => item.id === id);
    if (!entry || !this.index) return;
    this.controller?.abort();
    this.controller = new AbortController();
    const revision = ++this.revision;
    this.playing = false;
    this.releaseScene();
    delete this.host.dataset.caseId;
    delete this.host.dataset.timeS;
    this.message = 'Loading geometry and verified predictions…';
    this.setStatus(this.message);
    this.drawPanel();
    try {
      const data = await loadCase(entry, this.index, this.controller.signal);
      if (revision !== this.revision) return;
      this.initRenderer();
      this.data = data;
      this.station = createIssStationWorld(data);
      this.overlay = createIssPocOverlay(data, this.index.model, data.scene);
      this.station.world.add(this.overlay.group);
      this.overview = false;
      this.frameIndex = this.geometryOnly ? 0 : issPeakFrame(data);
      this.configureCamera();
      this.host.dataset.caseId = data.id;
      this.host.dataset.modelSha = this.index.model.weights_sha256;
      this.host.dataset.geometryOnly = String(this.geometryOnly);
      this.setStatus('');
      this.drawPanel();
      this.resize();
      this.setFrame(this.frameIndex);
      this.animate();
    } catch (error) { this.fail(error, revision); }
  }

  private initRenderer() {
    if (this.renderer) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.6));
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.physicallyCorrectLights = true;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    const canvas = renderer.domElement;
    canvas.tabIndex = 0;
    canvas.setAttribute('aria-label', 'Predicted heat and smoke in 3D. Drag to look, use arrow keys or WASD / ZQSD to move.');
    this.host.insertBefore(canvas, this.status);
    this.renderer = renderer;
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.addEventListener('change', () => { this.dirty = true; });
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      canvas.focus({ preventScroll: true });
      this.drag = { x: event.clientX, y: event.clientY };
      if (!this.overview) canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', event => {
      if (!this.drag || this.overview) return;
      this.yaw -= (event.clientX - this.drag.x) * 0.004;
      this.pitch = THREE.MathUtils.clamp(this.pitch - (event.clientY - this.drag.y) * 0.004, -1.35, 1.35);
      this.drag = { x: event.clientX, y: event.clientY };
      this.look();
    });
    const release = (event: PointerEvent) => {
      this.drag = undefined;
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    };
    canvas.addEventListener('pointerup', release);
    canvas.addEventListener('pointercancel', release);
    canvas.addEventListener('keydown', event => this.move(event));
    canvas.addEventListener('webglcontextlost', event => {
      event.preventDefault();
      this.playing = false;
      this.setStatus('3D context interrupted. Leave and re-enter the room to retry.', true);
    });
  }

  private look() {
    const direction = new THREE.Vector3(Math.sin(this.yaw) * Math.cos(this.pitch), Math.sin(this.pitch), -Math.cos(this.yaw) * Math.cos(this.pitch));
    this.camera.lookAt(this.camera.position.clone().add(direction));
    this.dirty = true;
  }

  private configureCamera() {
    if (!this.data || !this.controls || !this.station) return;
    const [width, depth, height] = this.data.scene.bounds_m;
    const span = Math.max(width, depth, height);
    this.controls.enabled = this.overview;
    this.station.setCutaway(this.overview);
    if (this.overview) {
      this.controls.target.set(width / 2, height * 0.42, -depth / 2);
      this.camera.position.set(width / 2 + span * 0.65, height + span * 0.45, span * 0.35);
      this.controls.minDistance = span * 0.2;
      this.controls.maxDistance = span * 4;
      this.camera.lookAt(this.controls.target);
      this.controls.update();
    } else {
      const pose = issInteriorPose(this.data);
      this.camera.position.set(...issToWorld(pose.position_m));
      const direction = new THREE.Vector3(...issToWorld(pose.target_m)).sub(this.camera.position).normalize();
      this.yaw = Math.atan2(direction.x, -direction.z);
      this.pitch = Math.asin(direction.y);
      this.look();
    }
    this.dirty = true;
  }

  private move(event: KeyboardEvent) {
    if (!this.data || this.overview || event.altKey || event.ctrlKey || event.metaKey) return;
    const key = event.key.toLowerCase();
    const forward = ['arrowup', 'w', 'z'].includes(key) ? 1 : ['arrowdown', 's'].includes(key) ? -1 : 0;
    const side = ['arrowright', 'd'].includes(key) ? 1 : ['arrowleft', 'a', 'q'].includes(key) ? -1 : 0;
    if (!forward && !side) return;
    event.preventDefault();
    const direction = this.camera.getWorldDirection(new THREE.Vector3());
    direction.y = 0;
    direction.normalize();
    const right = new THREE.Vector3().crossVectors(direction, new THREE.Vector3(0, 1, 0)).normalize();
    const next = this.camera.position.clone().addScaledVector(direction, forward * 0.15).addScaledVector(right, side * 0.15);
    const [width, depth] = this.data.scene.bounds_m;
    next.x = THREE.MathUtils.clamp(next.x, 0.1, width - 0.1);
    next.z = THREE.MathUtils.clamp(next.z, -depth + 0.1, -0.1);
    const blocked = this.data.scene.objects.some(object => {
      if (object.role === 'decoration') return false;
      const [x, y, z] = issToWorld(object.center_m);
      return Math.abs(next.x - x) < object.size_m[0] / 2 + 0.1
        && Math.abs(next.y - y) < object.size_m[2] / 2 + 0.1
        && Math.abs(next.z - z) < object.size_m[1] / 2 + 0.1;
    });
    if (!blocked) { this.camera.position.copy(next); this.look(); }
  }

  private resize() {
    if (!this.renderer || this.host.hidden) return;
    const width = Math.max(1, this.app.clientWidth), height = Math.max(1, this.app.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.overlay?.setViewportHeight(height * this.renderer.getPixelRatio());
    this.dirty = true;
  }

  private animate() {
    cancelAnimationFrame(this.raf);
    const render = (now: number) => {
      if (this.host.hidden) return;
      if (this.playing && this.data && now >= this.nextFrameAt) {
        if (this.frameIndex < this.data.frames.length - 1) {
          const frame = this.data.frames[this.frameIndex];
          const next = this.data.frames[this.frameIndex + 1];
          this.nextFrameAt = now + Math.max(40, (next.time_s - frame.time_s) * 1000);
          this.setFrame(this.frameIndex + 1);
        } else { this.playing = false; this.updateReadout(); }
      }
      if (this.controls?.enabled) this.controls.update();
      if (this.dirty && this.station && this.renderer && this.data) {
        this.renderer.render(this.station.world, this.camera);
        this.host.dataset.cameraPosition = this.camera.position.toArray().map(n => n.toFixed(5)).join(',');
        this.host.dataset.cameraDirection = this.camera.getWorldDirection(new THREE.Vector3()).toArray().map(n => n.toFixed(5)).join(',');
        this.host.dataset.drawCalls = String(this.renderer.info.render.calls);
        this.host.dataset.triangles = String(this.renderer.info.render.triangles);
        this.host.dataset.sourceNdc = new THREE.Vector3(...issToWorld(this.data.conditions.source_position_m)).project(this.camera).toArray().map(n => n.toFixed(5)).join(',');
        this.dirty = false;
      }
      this.raf = requestAnimationFrame(render);
    };
    this.raf = requestAnimationFrame(render);
  }

  private setFrame(index: number) {
    if (!this.data || !this.index) return;
    this.frameIndex = Math.max(0, Math.min(this.data.frames.length - 1, index));
    const frame = this.data.frames[this.frameIndex];
    this.overlay?.setFrame(frame, { ...this.options,
      heat: this.options.heat && !this.geometryOnly, smoke: this.options.smoke && !this.geometryOnly });
    this.host.dataset.timeS = String(frame.time_s);
    this.host.dataset.display = this.options.display;
    this.host.dataset.heatVisible = String(this.options.heat && !this.geometryOnly);
    this.host.dataset.smokeVisible = String(this.options.smoke && !this.geometryOnly);
    this.dirty = true;
    this.updateReadout();
  }

  private updateReadout() {
    if (!this.data || !this.index) return;
    const frame = this.data.frames[this.frameIndex];
    const input = this.panel.querySelector<HTMLInputElement>('#ml-time');
    if (input) input.value = String(this.frameIndex);
    const time = this.panel.querySelector('#ml-time-label');
    if (time) time.textContent = `${frame.time_s.toFixed(1)} / ${this.data.frames[this.data.frames.length - 1].time_s.toFixed(0)} s`;
    const play = this.panel.querySelector('[data-ml-action="play"]');
    if (play) { play.textContent = this.playing ? 'Pause' : 'Play'; play.setAttribute('aria-pressed', String(this.playing)); }
    const view = this.panel.querySelector('[data-ml-action="view"]');
    if (view) view.textContent = this.overview ? 'POV' : 'Overview';
    const counts = { heat: 0, smoke: 0 };
    if (!this.geometryOnly) for (const channel of ['heat', 'smoke'] as const) {
      this.data.sample_positions_m.forEach((_, point) => {
        const state = issSampleState(frame, point, channel, this.data!.conditions.ambient_temperature_c, this.index!.model);
        if (state && (this.options.display === 'reference' ? state.truth : this.options.display === 'errors' ? state.truth || state.predicted : state.predicted)) counts[channel]++;
      });
    }
    this.host.dataset.heatCount = String(counts.heat);
    this.host.dataset.smokeCount = String(counts.smoke);
    const output = this.panel.querySelector('#ml-counts');
    if (output) output.textContent = this.geometryOnly ? 'No prediction for these gravity conditions'
      : `${counts.heat} heat · ${counts.smoke} smoke samples`;
    const legend = this.panel.querySelector('#ml-legend');
    if (legend) legend.innerHTML = this.options.display === 'errors'
      ? '<i class="ml-dot ml-correct"></i>Detected <i class="ml-dot ml-missed"></i>Missed <i class="ml-dot ml-false"></i>False alarm'
      : '<i class="ml-dot ml-heat"></i>Heat <i class="ml-dot ml-smoke"></i>Smoke';
  }

  drawPanel() {
    if (this.host.hidden) return;
    this.panel.classList.add('ml-controls');
    if (!this.data || !this.index) {
      this.panel.innerHTML = `<h3>Model prediction</h3><div class="envn">${escape(this.message)}</div><div class="note">Saved model outputs · no training in the browser</div>`;
      this.panelChanged();
      return;
    }
    const data = this.data, entry = this.entries.find(item => item.id === data.id)!;
    const families = [...new Set(this.entries.map(item => item.family))];
    const cases = this.entries.filter(item => item.family === entry.family);
    const option = (value: string, label: string, selected: boolean) => `<option value="${escape(value)}"${selected ? ' selected' : ''}>${escape(label)}</option>`;
    const conditions = data.conditions;
    const environmentLabel = this.environment === 'earth' ? 'Earth · 1 g'
      : this.environment === 'moon' ? 'Moon · 0.17 g' : 'Microgravity';
    this.panel.innerHTML = `<h3>${this.geometryOnly ? 'Geometry preview' : 'Model prediction'}</h3>
      <div class="envl">${environmentLabel}${this.geometryOnly ? ' · predictions unavailable' : ` · ${conditions.oxygen_percent ?? 21}% O₂`}</div>
      ${this.geometryOnly ? '<div class="envn">Interior geometry only. This export has no cases for these gravity conditions; heat and smoke predictions are disabled.</div>' : ''}
      <label for="ml-family">Compartment</label><select id="ml-family">${families.map(family => option(family, FAMILY_NAMES[family] ?? family, family === entry.family)).join('')}</select>
      <label for="ml-scenario">Recorded scenario</label><select id="ml-scenario">${cases.map(item => option(item.id, `${INCIDENT_NAMES[item.incident_type ?? ''] ?? item.incident_type ?? 'Incident'} · ${((item.airflow_m_s ?? 0) * 100).toFixed(0)} cm/s · ${item.id.replace(item.family + '-', '')} · ${item.split}`, item.id === data.id)).join('')}</select>
      <div class="ml-conditions">${escape(conditions.power_w === 0 ? 'No-fire control' : INCIDENT_NAMES[conditions.incident_type] ?? conditions.incident_type)} · ${conditions.power_w ?? 0} W · ${(conditions.airflow_m_s * 100).toFixed(0)} cm/s airflow</div>
      <label for="ml-display">Layer</label><select id="ml-display"${this.geometryOnly ? ' disabled' : ''}>${[['prediction', 'ML prediction'], ['reference', 'FDS reference'], ['errors', 'Misses and false alarms']].map(([value, label]) => option(value, label, this.options.display === value)).join('')}</select>
      <div class="ml-layers"><label><input id="ml-heat" type="checkbox"${this.options.heat ? ' checked' : ''}${this.geometryOnly ? ' disabled' : ''}> Heat</label><label><input id="ml-smoke" type="checkbox"${this.options.smoke ? ' checked' : ''}${this.geometryOnly ? ' disabled' : ''}> Smoke</label></div>
      <label for="ml-time"><span>Timeline</span><b id="ml-time-label"></b></label><input id="ml-time" type="range" min="0" max="${data.frames.length - 1}" step="1" value="${this.frameIndex}"${this.geometryOnly ? ' disabled' : ''}>
      <div class="ml-actions"><button class="ghost" data-ml-action="play"${this.geometryOnly ? ' disabled' : ''}>Play</button><button class="ghost" data-ml-action="view">Overview</button><button class="ghost" data-ml-action="reset">Reset view</button></div>
      <div class="pred"><span id="ml-legend"></span><b id="ml-counts"></b></div>
      <div class="note">Drag to look · arrows / WASD / ZQSD to move</div>
      <details><summary>Model &amp; conditions</summary><div class="note">Recorded ML inference, synthetic FDS data. Conditional on the selected electrical source; not ignition probability. Heat and smoke are classified samples, not predicted temperature or density. Geometry is illustrative of spacecraft interiors.<br>Weights: ${escape(this.index.model.weights_sha256.slice(0, 12))}<br>Case: ${escape(data.id)}<br>Gravity: ${conditions.gravity_g} g · ${conditions.ambient_temperature_c} °C<br>Materials: ${escape([...new Set(data.scene.objects.map(object => object.material_id))].join(', '))}<br>Changing scenario may also change source, materials and geometry.</div></details>`;
    this.updateReadout();
    this.panelChanged();
  }

  private handleChange(event: Event) {
    if (this.host.hidden || !this.index) return;
    const input = event.target as HTMLInputElement;
    if (input.id === 'ml-family') {
      const entry = defaultCase(this.index, this.entries, input.value);
      if (entry) void this.select(entry.id);
    } else if (input.id === 'ml-scenario') void this.select(input.value);
    else if (input.id === 'ml-display' && ['prediction', 'reference', 'errors'].includes(input.value)) {
      this.options.display = input.value as IssOverlayOptions['display'];
      this.setFrame(this.frameIndex);
    } else if (input.id === 'ml-heat' || input.id === 'ml-smoke') {
      this.options[input.id === 'ml-heat' ? 'heat' : 'smoke'] = input.checked;
      this.setFrame(this.frameIndex);
    }
  }
}
