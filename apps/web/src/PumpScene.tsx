import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { Scenario } from './api';
import type { EngineeringMetrics, Telemetry } from './engineering';
import type { ComponentHighlight, ComponentId } from './alerts';

interface Props {
  scenario: Scenario;
  telemetry: Telemetry | null;
  metrics: EngineeringMetrics;
  playing: boolean;
  resetToken: number;
  rendererFactory?: () => THREE.WebGLRenderer;
  componentHighlights?: ComponentHighlight[];
  onComponentClick?: (componentId: ComponentId) => void;
}

const defaultRendererFactory = () => new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'low-power' });

function cylinderAlongX(radiusTop: number, radiusBottom: number, length: number, material: THREE.Material) {
  const geometry = new THREE.CylinderGeometry(radiusTop, radiusBottom, length, 32, 1);
  geometry.rotateZ(Math.PI / 2);
  return new THREE.Mesh(geometry, material);
}

export function PumpScene({ scenario, telemetry, metrics, playing, resetToken, rendererFactory, componentHighlights = [], onComponentClick }: Props) {
  const [reducedMotion, setReducedMotion] = useState(false);
  const hostRef = useRef<HTMLDivElement>(null);
  const displayState = useRef({ scenario, telemetry, metrics, playing, resetToken, reducedMotion: false, componentHighlights, onComponentClick });
  displayState.current = { scenario, telemetry, metrics, playing, resetToken, reducedMotion, componentHighlights, onComponentClick };
  const [renderError, setRenderError] = useState(false);

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const update = () => setReducedMotion(query?.matches ?? false);
    update();
    query?.addEventListener?.('change', update);
    return () => query?.removeEventListener?.('change', update);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = (rendererFactory ?? defaultRendererFactory)();
    } catch {
      setRenderError(true);
      return;
    }
    setRenderError(false);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(host.clientWidth, host.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    host.replaceChildren(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#151b20');
    const camera = new THREE.PerspectiveCamera(38, host.clientWidth / Math.max(host.clientHeight, 1), 0.1, 80);
    camera.position.set(5.2, 4.2, 7.8);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.65, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.minDistance = 5;
    controls.maxDistance = 14;
    controls.maxPolarAngle = Math.PI * 0.49;

    scene.add(new THREE.HemisphereLight('#dce3e6', '#263139', 2.0));
    const key = new THREE.DirectionalLight('#f1f0ea', 3.2);
    key.position.set(4, 8, 5);
    scene.add(key);
    const rim = new THREE.DirectionalLight('#a2abb2', 2.2);
    rim.position.set(-5, 3, -5);
    scene.add(rim);

    const mat = (color: string, metalness = 0.35, roughness = 0.4) => new THREE.MeshStandardMaterial({ color, metalness, roughness });
    const baseMat = mat('#343d44', 0.62, 0.38);
    const motorMat = mat('#59636b', 0.5, 0.36);
    const steelMat = mat('#a2abb2', 0.78, 0.28);
    const casingMat = mat('#c96324', 0.48, 0.34);
    const darkMat = mat('#232b31', 0.62, 0.32);
    const accentMat = mat('#e87932', 0.32, 0.34);
    const root = new THREE.Group();
    scene.add(root);
    const components = new Map<ComponentId, THREE.Group>();
    const componentGroup = (id: ComponentId) => { const group = new THREE.Group(); group.userData.componentId = id; components.set(id, group); root.add(group); return group; };
    componentGroup('motor'); const motorGroup = components.get('motor')!;
    componentGroup('shaft'); const shaftGroup = components.get('shaft')!;
    componentGroup('bearing'); const bearingGroup = components.get('bearing')!;
    componentGroup('casing'); const casingGroup = components.get('casing')!;
    componentGroup('impeller'); const impellerGroup = components.get('impeller')!;
    root.userData.componentId = 'pump';

    const addBox = (parent: THREE.Object3D, size: [number, number, number], position: [number, number, number], material: THREE.Material) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
      mesh.position.set(...position);
      parent.add(mesh);
      return mesh;
    };
    addBox(root, [5.4, 0.2, 2.15], [0, 0.05, 0], baseMat);
    addBox(root, [2.35, 0.15, 1.65], [-1.25, 0.24, 0], darkMat);
    // Motor body and cooling fins.
    const motor = cylinderAlongX(0.74, 0.74, 1.95, motorMat);
    motor.position.set(-1.55, 1.22, 0);
    motorGroup.add(motor);
    for (let i = 0; i < 9; i += 1) {
      const fin = cylinderAlongX(0.8, 0.8, 0.065, steelMat);
      fin.position.set(-2.35 + i * 0.2, 1.22, 0);
      motorGroup.add(fin);
    }
    const motorCap = cylinderAlongX(0.52, 0.52, 0.13, darkMat);
    motorCap.position.set(-2.57, 1.22, 0);
    motorGroup.add(motorCap);

    const shaft = cylinderAlongX(0.115, 0.115, 1.25, steelMat);
    shaft.position.set(-0.37, 1.22, 0);
    shaftGroup.add(shaft);
    const wearMat = mat('#c8d0d5', 0.75, 0.25);
    for (const x of [-0.68, 0.13]) {
      const bearing = cylinderAlongX(0.36, 0.36, 0.3, wearMat);
      bearing.position.set(x, 1.22, 0);
      bearingGroup.add(bearing);
      const bearingCore = cylinderAlongX(0.2, 0.2, 0.32, darkMat);
      bearingCore.position.set(x, 1.22, 0);
      bearingGroup.add(bearingCore);
    }
    // Volute casing, axial inlet, and radial discharge.
    const casing = new THREE.Mesh(new THREE.TorusGeometry(0.92, 0.31, 18, 40), casingMat);
    casing.position.set(0.55, 1.35, 0);
    casing.rotation.y = Math.PI / 2;
    casingGroup.add(casing);
    const casingCore = new THREE.Mesh(new THREE.SphereGeometry(0.68, 28, 20), casingMat);
    casingCore.position.set(0.55, 1.35, 0);
    casingGroup.add(casingCore);
    const inlet = cylinderAlongX(0.39, 0.39, 0.95, steelMat);
    inlet.position.set(1.5, 1.35, 0);
    casingGroup.add(inlet);
    const inletLip = cylinderAlongX(0.52, 0.52, 0.12, accentMat);
    inletLip.position.set(1.98, 1.35, 0);
    casingGroup.add(inletLip);
    const outlet = new THREE.Mesh(new THREE.CylinderGeometry(0.31, 0.31, 1.15, 28), steelMat);
    outlet.position.set(0.55, 2.23, 0);
    casingGroup.add(outlet);
    const outletFlange = new THREE.Mesh(new THREE.CylinderGeometry(0.48, 0.48, 0.13, 32), accentMat);
    outletFlange.position.set(0.55, 2.82, 0);
    casingGroup.add(outletFlange);

    // Impeller sits in the volute plane; rotation follows shaft speed around X.
    const impeller = new THREE.Group();
    impeller.position.set(0.2, 1.35, 0);
    impellerGroup.add(impeller);
    impeller.userData.componentId = 'impeller';
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.62, 24), steelMat);
    hub.rotation.z = Math.PI / 2;
    impeller.add(hub);
    const eye = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.12, 28), accentMat);
    eye.rotation.z = Math.PI / 2;
    eye.position.x = 0.35;
    impeller.add(eye);
    for (let i = 0; i < 7; i += 1) {
      const blade = new THREE.Mesh(new THREE.BoxGeometry(0.09, 0.7, 0.13), steelMat);
      const angle = (i / 7) * Math.PI * 2;
      blade.position.set(0, Math.cos(angle) * 0.42, Math.sin(angle) * 0.42);
      blade.rotation.x = -angle + 0.24;
      impeller.add(blade);
    }
    // A small transparent inspection window reveals the impeller.
    const windowMat = new THREE.MeshStandardMaterial({ color: '#a2abb2', transparent: true, opacity: 0.2, roughness: 0.24, metalness: 0.16, side: THREE.DoubleSide });
    const inspection = new THREE.Mesh(new THREE.CircleGeometry(0.75, 40), windowMat);
    inspection.position.set(0.55, 1.35, 0.275);
    casingGroup.add(inspection);

    // Cavitation bubbles are a visual cue tied to the selected synthetic regime.
    const bubbles = new THREE.Group();
    const bubbleMat = new THREE.MeshStandardMaterial({ color: '#d6dde1', transparent: true, opacity: 0.58, roughness: 0.18, metalness: 0.08 });
    for (let i = 0; i < 16; i += 1) {
      const bubble = new THREE.Mesh(new THREE.SphereGeometry(0.045 + (i % 3) * 0.012, 8, 6), bubbleMat);
      const angle = i * 2.4;
      bubble.position.set(0.52, 1.35 + Math.cos(angle) * (0.62 + (i % 4) * 0.08), Math.sin(angle) * (0.62 + (i % 4) * 0.08));
      bubbles.add(bubble);
    }
    bubbles.visible = displayState.current.scenario === 'cavitation';
    casingGroup.add(bubbles);

    const highlightHelpers = new Map<ComponentId, THREE.Box3Helper>();
    for (const [id, group] of components) {
      if (!group.children.length) continue;
      const bounds = new THREE.Box3().setFromObject(group);
      if (bounds.isEmpty()) continue;
      const helper = new THREE.Box3Helper(bounds, '#e3ad4c');
      helper.visible = false;
      const lineMaterial = helper.material as THREE.LineBasicMaterial;
      lineMaterial.transparent = true;
      lineMaterial.depthTest = false;
      helper.renderOrder = 10;
      scene.add(helper);
      highlightHelpers.set(id, helper);
    }

    const floorMat = new THREE.MeshStandardMaterial({ color: '#1b2126', roughness: 0.9 });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.08;
    scene.add(floor);
    const grid = new THREE.GridHelper(18, 36, '#4a555e', '#343d44');
    grid.position.y = -0.07;
    scene.add(grid);

    let raf = 0;
    let last = performance.now();
    let angle = 0;
    let elapsed = 0;
    let currentOmega = 0;
    let seenResetToken = resetToken;
    let activeScenario = displayState.current.scenario;
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      const dt = Math.min((now - last) / 1000, 0.08);
      last = now;
      elapsed += dt;
      const state = displayState.current;
      const activeHighlights = new Map(state.componentHighlights.map((item) => [item.componentId, item.severity]));
      for (const [id, helper] of highlightHelpers) {
        const severity = activeHighlights.get(id);
        helper.visible = Boolean(severity);
        if (severity) {
          helper.box.setFromObject(components.get(id)!);
          const lineMaterial = helper.material as THREE.LineBasicMaterial;
          lineMaterial.color.set(severity === 'critical' ? '#d94c48' : '#e3ad4c');
          lineMaterial.opacity = 0.68 + Math.sin(elapsed * 3) * 0.12;
        }
      }
      if (state.resetToken !== seenResetToken) {
        seenResetToken = state.resetToken;
        camera.position.set(5.2, 4.2, 7.8);
        controls.target.set(0, 0.65, 0);
      }
      if (state.scenario !== activeScenario) {
        activeScenario = state.scenario;
        motorMat.color.set(activeScenario === 'overheating' ? '#e87932' : '#59636b');
        wearMat.color.set(activeScenario === 'bearing_wear' ? '#e3ad4c' : '#a2abb2');
        bubbles.visible = activeScenario === 'cavitation';
      }
      const shouldAnimate = state.playing && !state.reducedMotion;
      if (shouldAnimate) {
        const targetOmega = state.metrics.angularVelocityRadS ?? 0;
        currentOmega += (targetOmega - currentOmega) * Math.min(1, dt * 1.8);
        angle += currentOmega * dt;
        impeller.rotation.x = angle;
        const vibrationAmplitude = Math.min(state.metrics.vibrationIntensity ?? 0, 1) * 0.022;
        const vibrationMotion = activeScenario === 'bearing_wear' || activeScenario === 'imbalance' ? vibrationAmplitude : 0;
        root.position.y = Math.sin(elapsed * 18) * vibrationMotion;
        root.rotation.z = activeScenario === 'imbalance' ? Math.sin(elapsed * 7) * vibrationAmplitude * 0.32 : 0;
        if (activeScenario === 'cavitation') bubbles.rotation.x += dt * 0.18;
      } else {
        root.position.y = 0;
        root.rotation.z = 0;
      }
      controls.update();
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(draw);
    const resize = new ResizeObserver(() => {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (width < 1 || height < 1) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    });
    resize.observe(host);
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 'r' && !event.ctrlKey && !event.metaKey && document.activeElement === renderer.domElement) {
        camera.position.set(5.2, 4.2, 7.8);
        controls.target.set(0, 0.65, 0);
        controls.update();
      }
    };
    window.addEventListener('keydown', onKey);
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const onPointerDown = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(root.children, true)[0]?.object;
      let node: THREE.Object3D | null | undefined = hit;
      while (node && !node.userData.componentId) node = node.parent;
      if (node?.userData.componentId) displayState.current.onComponentClick?.(node.userData.componentId as ComponentId);
    };
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    return () => {
      cancelAnimationFrame(raf);
      resize.disconnect();
      window.removeEventListener('keydown', onKey);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      controls.dispose();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [rendererFactory]);

  return (
    <div className="scene-wrap">
      <div className="scene-canvas" ref={hostRef} aria-label="Interactive procedural centrifugal pump model" />
      {renderError && (
        <div className="scene-fallback" role="status">
          <div className="fallback-icon">◉</div>
          <strong>3D view unavailable</strong>
          <span>This browser or device could not create a WebGL graphics context. Telemetry and simulation controls remain available.</span>
        </div>
      )}
      <div className="scene-topline"><span className="live-dot" /> SIMULATION RESPONSE <span className="scene-sep">/</span> {scenario.replaceAll('_', ' ').toUpperCase()}</div>
      <div className="scene-labels" aria-label="Pump component labels">
        {([['motor', 'Drive motor'], ['bearing', 'Bearings'], ['casing', 'Volute casing'], ['shaft', 'Shaft'], ['impeller', 'Impeller']] as [ComponentId, string][]).map(([id, label]) => <button key={id} className={componentHighlights.some((item) => item.componentId === id) ? 'highlighted' : ''} onClick={() => onComponentClick?.(id)}><i className={`label-${id}`} /> {label}</button>)}
      </div>
      <div className="scene-hint">DRAG TO ORBIT <span>·</span> SCROLL TO ZOOM</div>
    </div>
  );
}
