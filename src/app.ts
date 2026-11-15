// @ts-nocheck
/* Flame in Freefall — the whole experience: landing, the flight to the station, the three environments,
   the rooms with their test conditions, and the investigations panel.
   Ported as one module from the validated mock-up; it is not type-checked yet (see README, "Known limits").
   Investigation records come from the PSI snapshot in ./data. */
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { INVESTIGATIONS } from './data/investigations';
import { PredictionRoom } from './prediction/room';

export function startApp(){
const $=s=>document.querySelector(s), app=$('#app');
const prediction = new PredictionRoom(app, $('#pars'), () => requestAnimationFrame(fitBar), () => {S.side=false;drawPanel()});
let QS;try{QS=new URLSearchParams(location.search)}catch(e){QS=new URLSearchParams('')}
const EXPORT=QS.get('export')||'', HOLD=QS.has('hold');
if(EXPORT||HOLD){const LOG=[];['error','warn'].forEach(k=>{const o=console[k];console[k]=function(){LOG.push(k+': '+[].map.call(arguments,String).join(' ').slice(0,1500));fetch('/?name=log.json',{method:'POST',body:JSON.stringify(LOG.slice(0,12))});o.apply(console,arguments)}});addEventListener('error',e=>{fetch('/?name=err.json',{method:'POST',body:JSON.stringify({m:e.message,l:e.lineno,c:e.colno})})});const w=new Image();w.hidden=true;w.src='/wait?s=170';document.body.appendChild(w)}
const AX={prev:{n:'Prevention',c:'#f2a93b'},det:{n:'Detection',c:'#3fc9a5'},sup:{n:'Suppression',c:'#5fb0ff'},fun:{n:'Flame physics',c:'#a493ff'}};
const INV=INVESTIGATIONS;
const SCEN={iss:{n:'ISS',r:'21 % O\u2082 · 14.7 psi · microgravity'},moon:{n:'Lunar base',r:'34 % O\u2082 · 8.2 psi · 1/6 g'},earth:{n:'Earth',r:'21 % O\u2082 · 14.7 psi · 1 g'}};
/* each data theme sits on a real Gateway element and has its own room; `node` is the element's name in NASA's model */
const MODS=[
 {id:'prev',node:'iHAB',n:'I-Hab · Prevention',s:'Material flammability',pred:'Flame spread',f:v=>v.ax==='prev',c:'#f2a93b',seed:11,yaw:-.2},
 {id:'det',node:'NG_HALO',n:'HALO · Detection',s:'Smoke and aerosols',pred:'Time to smoke alarm',f:v=>v.ax==='det',c:'#3fc9a5',seed:23,yaw:-.08},
 {id:'sup',node:'airlock',n:'Airlock · Suppression',s:'Extinguishing agents',pred:'Extinction',f:v=>v.ax==='sup',c:'#5fb0ff',seed:37,yaw:.12},
 {id:'fun',node:'ERMXL',n:'ESPRIT · Flame physics',s:'Fundamental flame behavior',pred:'Flame size and regime',f:v=>v.ax==='fun',c:'#a493ff',seed:41,yaw:-.26},
 {id:'si',node:'Maxar_PPE',n:'PPE · SI console',s:'Global ranking and comparison',pred:'Global ranking',f:()=>true,si:1,c:'#ff7ab8',rc:'#5fb0ff',seed:53,yaw:0}];
const S={scen:'iss',mod:null,inv:null,filt:null,cmp:new Set(),par:{},side:false};
const TH={prev:'Prevention',det:'Detection',sup:'Suppression',fun:'Flame physics',si:'SI console'},
 PLACE={iss:{prev:'I-Hab',det:'HALO',sup:'Airlock',fun:'ESPRIT',si:'PPE'},moon:{prev:'Habitat',det:'Command module',sup:'Airlock',fun:'Science lab',si:'Control center'},earth:{prev:'Materials lab',det:'Sensor hall',sup:'Fire test cell',fun:'Drop tower',si:'Data center'}},
 BACK={iss:'the station',moon:'the lunar base',earth:'the campus'},nm=m=>PLACE[S.scen][m.id]+' · '+TH[m.id],sfx=()=>S.scen==='earth'?'e':'';
/* what each place changes: atmosphere set-points and gravity (fraction of Earth's) */
const ENVP={iss:{o2:21,p:1,g:0},moon:{o2:34,p:.55,g:.165},earth:{o2:21,p:1,g:1}},G=()=>ENVP[S.scen].g,
 ENOTE={iss:{prev:'No buoyancy: only the fan flow feeds the flame.',det:'Smoke does not rise: it only follows the cabin airflow.',sup:'With no buoyant flow the agent stays around the flame.',fun:'Flames are spherical and steady.',si:''},
  moon:{prev:'34 % oxygen and 1/6 g: materials ignite at lower oxygen than on Earth or the ISS.',det:'Weak buoyancy lifts smoke slowly toward the ceiling.',sup:'Oxygen-rich air: more agent is needed.',fun:'1/6 g stretches the flame slightly upward.',si:''},
  earth:{prev:'Buoyancy pulls fresh air into the flame: it spreads fast.',det:'Hot smoke rises straight to the ceiling detectors.',sup:'Buoyant flow keeps feeding the flame with fresh air.',fun:'Buoyancy makes a smaller teardrop flame that flickers.',si:''}};
function score(v,s){let b={prev:68,det:58,sup:58,fun:40}[v.ax];
 if(s==='iss'){if(v.ax==='det'||v.ax==='sup')b+=22;if(v.big)b+=12}
 else if(s==='earth'){if(v.ax==='det'||v.ax==='sup')b+=14;if(v.ax==='fun')b+=10}
 else{if(v.hi)b+=20;if(v.pg)b+=32;if(v.big)b+=6}
 return Math.max(5,Math.min(98,b))}
const ranked=f=>INV.filter(f).sort((a,b)=>score(b,S.scen)-score(a,S.scen));
const modOf=id=>MODS.find(m=>m.id===id);

/* ---------- shot geometry (shared by the live render and the pre-rendered frames) ---------- */
const V=THREE.Vector3, RM=600, RAD=Math.PI/180, DUR=3500, NF=96, NH=150, KH=12, FPSH=12, LON0=115.3125, RATE=.55, TILT=2;
const dirOf=(az,el)=>new V(Math.sin(az)*Math.cos(el),Math.sin(el),-Math.cos(az)*Math.cos(el));
const DIP0=Math.acos(RM/(RM+45));
const P0=new V(0,RM+45,0), D0=dirOf(0,-(DIP0-1.4*RAD)), EDIR=dirOf(0,-(DIP0-2.86*RAD));
const P2=new V(60,RM+112,150), D2=dirOf(15*RAD,-24*RAD), ST=P2.clone().addScaledVector(D2,46), P1=new V(-10,RM+75,85);
const SUN=new V(.55,.42,.72).normalize();
const sm=x=>x*x*(3-2*x), cl=x=>Math.max(0,Math.min(1,x));
/* camera progress: speed grows exponentially, then brakes just before the station */
const EASE=(()=>{const n=240,k=3.4,ts=.86,a=[0];let s=0;for(let i=1;i<=n;i++){const x=(i-.5)/n;s+=x<ts?Math.exp(k*x):Math.exp(k*ts)*(.5+.5*Math.cos(Math.PI*(x-ts)/(1-ts)));a.push(s)}return x=>{const f=cl(x)*n,i=Math.min(n-1,Math.floor(f));return(a[i]+(a[i+1]-a[i])*(f-i))/s}})();
/* orbit: degrees of ground track flown `sec` seconds after Ignite; the rate ramps up during the intro, then stays constant */
const spinAt=sec=>{const D=DUR/1000,u=cl(sec/D);return RATE*(D*(u*u*u-u*u*u*u/2)+Math.max(0,sec-D))};
const pp=new V(),pd=new V();
function pose(t,cam,aspect){const e=EASE(t),a=(1-e)*(1-e),b=2*(1-e)*e,c=e*e;
 pp.set(a*P0.x+b*P1.x+c*P2.x,a*P0.y+b*P1.y+c*P2.y,a*P0.z+b*P1.z+c*P2.z);
 pd.copy(D0).lerp(D2,sm(cl(e*1.2))).normalize();
 const f1=aspect<1?58:38,k=1-Math.pow(1-cl(e*1.7),2);
 cam.position.copy(pp);cam.fov=14+(f1-14)*k;cam.updateProjectionMatrix();cam.lookAt(pd.add(pp))}

/* ---------- renderer ---------- */
const gl=$('#gl'), seq=$('#seq');
function hasGL(){if(QS.has('nogl'))return false;const lab=!!(EXPORT||HOLD||QS.has('gl'));try{if(!lab&&sessionStorage.getItem('fif_nogl'))return false}catch(e){}
 try{const c=document.createElement('canvas'),o={failIfMajorPerformanceCaveat:!lab},g=c.getContext('webgl2',o)||c.getContext('webgl',o);if(!g)return false;if(lab)return true;const e=g.getExtension('WEBGL_debug_renderer_info'),n=e?String(g.getParameter(e.UNMASKED_RENDERER_WEBGL)):'';return !/llvmpipe|swiftshader|software|softpipe|basic render/i.test(n)}catch(e){return false}}
let LIVE=hasGL();
const cam=new THREE.PerspectiveCamera(38,16/9,.5,60000), inCam=new THREE.PerspectiveCamera(64,16/9,.04,60);inCam.rotation.order='YXZ';
let R,pm,scene,inScene,winRT,winCam,pivot,moonG,earthMap,anchors={},ready=false,state='landing',t0=0,tin=0,busy=false,yaw=0,pitch=0,room=null;
function setSpin(deg){if(moonG)moonG.rotation.set(-Math.PI/2+TILT*RAD,-(LON0+90+deg)*RAD,0)}
const look=new V(),camT=new V(),lookT=new V();
/*ANCH*/const ANCH={"prev":[63.76,688.56,103.44],"det":[71.09,691.2,107.13],"sup":[61.49,687.46,108.19],"fun":[68.32,689.96,111.25],"si":[76.49,692.69,110.13]};/*ANCH*/
const cv=(w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h;return c},rng=s=>()=>(s=(s*16807)%2147483647)/2147483647;
const ctex=c=>{const t=new THREE.CanvasTexture(c);t.encoding=THREE.sRGBEncoding;t.anisotropy=8;return t};
function detailTex(){const c=cv(256,256),x=c.getContext('2d'),im=x.createImageData(256,256),r=rng(5);
 for(let i=0;i<im.data.length;i+=4){const v=70+r()*r()*230;im.data[i]=im.data[i+1]=im.data[i+2]=Math.min(255,v);im.data[i+3]=255}x.putImageData(im,0,0);x.filter='blur(0.6px)';x.drawImage(c,0,0);
 const t=new THREE.CanvasTexture(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.anisotropy=8;return t}
function initLive(){
 gl.addEventListener('webglcontextlost',e=>{e.preventDefault();if(!EXPORT)toSeq()});
 R=new THREE.WebGLRenderer({canvas:gl,antialias:true,logarithmicDepthBuffer:true,preserveDrawingBuffer:!!(EXPORT||HOLD)});
 R.setPixelRatio(EXPORT?1:Math.min(devicePixelRatio||1,2));R.outputEncoding=THREE.sRGBEncoding;R.toneMapping=THREE.ACESFilmicToneMapping;R.toneMappingExposure=1.05;R.setClearColor(0x000000,1);
 scene=new THREE.Scene();inScene=new THREE.Scene();
 const sun=new THREE.DirectionalLight(0xfff3e4,3.1);sun.position.copy(SUN).multiplyScalar(100);scene.add(sun);
 const shine=new THREE.DirectionalLight(0xbfc6d0,.32);shine.position.set(0,-100,10);scene.add(shine);
 scene.add(new THREE.AmbientLight(0x2a3548,.22));
 const N=2600,pos=new Float32Array(N*3),col=new Float32Array(N*3),rnd=rng(11);
 for(let i=0;i<N;i++){const u=rnd()*2-1,th=rnd()*6.2832,q=Math.sqrt(1-u*u),b=.25+Math.pow(rnd(),3)*.9;pos[i*3]=q*Math.cos(th)*30000;pos[i*3+1]=u*30000;pos[i*3+2]=q*Math.sin(th)*30000;col[i*3]=b;col[i*3+1]=b;col[i*3+2]=b*(1+.15*(rnd()-.5))}
 const sg=starGeo=new THREE.BufferGeometry();sg.setAttribute('position',new THREE.BufferAttribute(pos,3));sg.setAttribute('color',new THREE.BufferAttribute(col,3));
 scene.add(new THREE.Points(sg,new THREE.PointsMaterial({size:1.7,sizeAttenuation:false,vertexColors:true,depthWrite:false})));
 /* reflections for the station's metal: a sun, moonlight from below, dark sky */
 pm=new THREE.PMREMGenerator(R);const es=new THREE.Scene();
 es.add(new THREE.Mesh(new THREE.SphereGeometry(100,16,8),new THREE.MeshBasicMaterial({color:0x020204,side:THREE.BackSide})));
 const sb=new THREE.Mesh(new THREE.SphereGeometry(8,16,8),new THREE.MeshBasicMaterial({color:new THREE.Color(55,53,49)}));sb.position.copy(SUN).multiplyScalar(60);es.add(sb);
 const mg=new THREE.Mesh(new THREE.CircleGeometry(90,24),new THREE.MeshBasicMaterial({color:new THREE.Color(.42,.42,.44),side:THREE.DoubleSide}));mg.position.set(0,-45,0);mg.rotation.x=Math.PI/2;es.add(mg);
 scene.environment=pm.fromScene(es,.03).texture;
 /* interior: soft shadows, reflections of a plain lit room, and a small view of the Moon for the porthole */
 R.shadowMap.enabled=true;R.shadowMap.type=THREE.PCFSoftShadowMap;const re=new THREE.Scene();re.add(new THREE.Mesh(new THREE.BoxGeometry(2.2,2.2,7),new THREE.MeshBasicMaterial({color:0x2e2f2e,side:THREE.BackSide})));
 [-.6,.6].forEach(x=>{const l=new THREE.Mesh(new THREE.BoxGeometry(.2,.02,5),new THREE.MeshBasicMaterial({color:new THREE.Color(3.2,3.1,2.9)}));l.position.set(x,1.05,0);re.add(l)});inScene.environment=pm.fromScene(re,.03).texture;
 winRT=new THREE.WebGLRenderTarget(512,512);winCam=new THREE.PerspectiveCamera(48,1,.5,60000);winCam.position.copy(P2);winCam.lookAt(dirOf(-75*RAD,-52*RAD).add(P2));
 const TL=new THREE.TextureLoader(),TOT=34;let left=TOT;const one=()=>{left--;$('#igl').textContent='Loading '+Math.round((TOT-left)/TOT*100)+' %';if(left===0)onReady()},fail=e=>{$('#igl').textContent='Load error';console.error('load failed: '+(e&&(e.message||(e.target&&e.target.src)||e.type)||e))};
 /* Moon: NASA LRO wide-angle mosaic in layers of increasing detail. Its poles lie on the camera axis, so it turns under a fixed camera and station. */
 const dt=detailTex(),aniso=R.capabilities.getMaxAnisotropy();
 moonG=new THREE.Group();scene.add(moonG);
 const layer=(file,l0,l1,b0,b1,r,ws,hs)=>{const mt=new THREE.MeshStandardMaterial({roughness:1,metalness:0,envMapIntensity:0,color:0xb9b4ac}),rp=new THREE.Vector2((l1-l0)*.83,(b1-b0)*.83);
  mt.onBeforeCompile=sh=>{sh.uniforms.detailMap={value:dt};sh.uniforms.detailRep={value:rp};sh.fragmentShader='uniform sampler2D detailMap;uniform vec2 detailRep;\n'+sh.fragmentShader.replace('#include <map_fragment>','#include <map_fragment>\n float d1=texture2D(detailMap,vUv*detailRep).r;float d2=texture2D(detailMap,vUv*detailRep*.277+.37).r;diffuseColor.rgb*=.84+.16*(d1+d2);')};
  mt.map=TL.load('moon2/'+file,one,undefined,fail);mt.map.encoding=THREE.sRGBEncoding;mt.map.anisotropy=aniso;if(file==='land.jpg')landTex=mt.map;
  moonG.add(new THREE.Mesh(new THREE.SphereGeometry(r,ws,hs,(l0+180)*RAD,(l1-l0)*RAD,(90-b1)*RAD,(b1-b0)*RAD),mt))};
 layer('base.jpg',-180,180,-90,90,RM,192,96);
 for(let k=0;k<8;k++){const a=-180+k*45,b=a+45;layer('band'+k+'.jpg',a,b,0,22.5,RM+.05,48,24);layer('north'+k+'.jpg',a,b,22.5,45,RM+.05,48,24);layer('south'+k+'.jpg',a,b,-22.5,0,RM+.05,48,24)}
 layer('land.jpg',104.0625,126.5625,5.625,25.3125,RM+.1,32,28);setSpin(0);
 earthMap=TL.load('earth1k.png',one,undefined,fail);earthMap.encoding=THREE.sRGBEncoding;const em=new THREE.SpriteMaterial({map:earthMap,depthWrite:false});
 const earth=new THREE.Sprite(em);earth.position.copy(P0).addScaledVector(EDIR,8000);const ed=2*8000*Math.tan(3.4*RAD);earth.scale.set(ed,ed,1);scene.add(earth);
 pivot=new THREE.Group();pivot.position.copy(ST);scene.add(pivot);
 new GLTFLoader().load('gateway.json',g=>{const m=gwM=g.scene,bx=new THREE.Box3().setFromObject(m),sp=bx.getBoundingSphere(new THREE.Sphere()),k=26/sp.radius;
  m.scale.setScalar(k);m.position.copy(sp.center).multiplyScalar(-k);pivot.add(m);pivot.rotation.set(.35,-2.2,.12);pivot.updateMatrixWorld(true);
  MODS.forEach(md=>{const n=m.getObjectByName(md.node);if(!n)return;const b=new THREE.Box3().setFromObject(n),c=b.getCenter(new V());const a=new THREE.Object3D();a.position.copy(pivot.worldToLocal(c));pivot.add(a);anchors[md.id]=a;n.userData.mod=md.id});
  one()},undefined,fail);
 hadTex=TL.load('moon3/hadley.jpg',one,undefined,fail);hadTex.encoding=THREE.sRGBEncoding;hadTex.anisotropy=aniso;demImg=new Image();demImg.onload=one;demImg.onerror=fail;demImg.src='moon3/hadley_dem.png';[5,8,11,14].forEach(z=>{const t=TL.load('earth3/e'+z+'.jpg',one,undefined,fail);t.encoding=THREE.sRGBEncoding;t.anisotropy=aniso;etex[z]=t});
}

/* ---------- module interiors: each module has its own room, hardware and test conditions ---------- */
const RW=2.2,RH=2.2;
const STYLE={prev:{L:7,wall:0xc4bba9,li:1,lc:0xfff0dc,cz:2.0,fz:-.75,cl:6,bags:3},det:{L:8,wall:0xa9b0b8,li:.92,lc:0xeaf2ff,cz:2.4,fz:-.4,cl:9,bags:4},sup:{L:4.6,wall:0xcdcfcd,li:1,lc:0xffffff,cz:1.45,fz:-.55,round:1},fun:{L:6,wall:0x959ca4,li:.9,lc:0xf0f5ff,cz:1.7,fz:-1,cl:5,bags:1},si:{L:5.6,wall:0x4b525c,li:.4,lc:0x9cc2ff,cz:1.5,fz:-1.3,cl:3,bags:0}};
/* conditions the user can change in each room, and the illustrative prediction they drive */
const PARS={
 prev:[{k:'heat',n:'Igniter power',u:' %',a:0,b:100,v:70},{k:'o2',n:'Oxygen',u:' %',a:16,b:40,v:30},{k:'flow',n:'Airflow',u:' cm/s',a:0,b:30,v:10}],
 det:[{k:'smoke',n:'Smoke release',u:' %',a:0,b:100,v:60},{k:'flow',n:'Cabin airflow',u:' cm/s',a:0,b:30,v:12}],
 sup:[{k:'agent',n:'CO₂ flow',u:' %',a:0,b:100,v:25},{k:'o2',n:'Oxygen',u:' %',a:16,b:40,v:30}],
 fun:[{k:'fuel',n:'Fuel flow',u:' %',a:5,b:100,v:45},{k:'o2',n:'Oxygen',u:' %',a:16,b:85,v:30},{k:'pres',n:'Pressure',u:' atm',a:.25,b:3,v:1,st:.05}],
 si:[]};
MODS.forEach(m=>{S.par[m.id]={};PARS[m.id].forEach(p=>{S.par[m.id][p.k]=p.v})});
function envDefaults(){const e=ENVP[S.scen];MODS.forEach(m=>PARS[m.id].forEach(p=>{if(p.k==='o2')S.par[m.id].o2=e.o2;if(p.k==='pres')S.par[m.id].pres=e.p}))}envDefaults();
const LOX=()=>{const g=G();return g===0?0:g<.5?-2.5:1},BUO=()=>Math.cbrt(G()),lit=P=>P.heat>30&&P.o2>=17+LOX()+(1-P.heat/100)*8, supK=P=>cl((P.o2-10)/30-P.agent/100*1.25+.1*G()),fRad=P=>(6+22*Math.sqrt(P.fuel/100))/Math.pow(P.pres,.33)/(1+.9*Math.sqrt(G()));
const PRED={
 prev:P=>lit(P)?(Math.max(.2,.6+(P.o2-21)*.12)*(1+(P.flow/30+BUO())*.8)).toFixed(1)+' mm/s':'No ignition',
 det:P=>{const fe=P.flow+25*Math.sqrt(G());return P.smoke<8?'No alarm':fe<1?'Not reached, smoke stays at the source':Math.round(100/fe*(1+(60-P.smoke)/150))+' s'},
 sup:P=>supK(P)>0?'Flame sustained':'Extinguished in '+Math.max(1,Math.round((2+9*cl((P.o2-10)/30)/(P.agent/100*1.25))*(1+.6*G()))) +' s',
 fun:P=>Math.round(fRad(P))+' mm · '+(P.o2<22&&P.fuel<35?'cool flame':P.fuel>70&&P.o2<45?'sooting':'blue, soot-free')+(G()>.5?', flickering teardrop':G()>0?', slightly stretched':', spherical')};
/* what the conditions look like: a list of glows (position in room metres relative to the experiment, size, colour, opacity). Drawn as 3D sprites live, as 2D glows over the still otherwise. */
let fxLight=1;
const FX={
 prev(P,t){const o=[],h=P.heat/100,k=cl((P.o2-16)/24),fl=P.flow/30,gq=Math.sqrt(G());fxLight=0;
  o.push({p:[.165,-.4,0],s:.035+.06*h,c:[1,.25+.5*h,.08+.55*h*h],a:.15+.85*h,add:1});
  if(lit(P)){fxLight=.5+k;const len=(.1+.34*k*(.5+fl))*(1-.35*gq);for(let i=0;i<6;i++){const u=i/5;o.push({p:[.19+u*len,-.39+.012*Math.sin(t*11+i*1.7)*(1+2*gq)+.03*u*(1-fl)+u*.2*gq*(.6+k),0],s:(.13+.15*k)*(1-.5*u)*(1+.07*Math.sin(t*27+i*2.1)),c:[1,.5+.25*(1-u),.12+.3*(1-u)],a:.8*(1-.55*u),add:1})}
   o.push({p:[.185,-.4,0],s:.07+.05*k,c:[.4,.7,1],a:.9,add:1})}return o},
 det(P,t){const o=[],d=P.smoke/100,fl=P.flow/30,gq=Math.sqrt(G()),fe=fl+.83*gq,alarm=fe>.03&&d>.08&&d*(.4+fe)>.3;fxLight=1;
  for(let i=0;i<16;i++){const u=(t*(.05+.5*fl)+i/16)%1,sp=.05+.3*u*(1-.75*fl),a1=i*2.4;o.push({p:[.2+Math.cos(a1)*sp,-.3+u*Math.min(1.1,.12+1.0*fl+.95*gq)+Math.sin(a1*1.3)*sp*(1-fl),Math.sin(a1)*sp],s:.14+.34*u,c:[.84,.87,.9],a:d*.5*(1-u*.8)})}
  o.push({p:[.2,.12,0],s:.05+.25*d,c:[1,.2,.15],a:.25+.6*d,add:1});
  [-.7,.7].forEach(z=>o.push({p:[.23,.8,z],s:alarm?.17:.05,c:alarm?[1,.15,.1]:[.3,1,.5],a:alarm?.6+.4*Math.sin(t*10):1,add:1}));return o},
 sup(P,t){const o=[],ag=P.agent/100,k=supK(P);fxLight=k;
  for(let i=0;i<8;i++){const u=(t*1.4+i/8)%1;o.push({p:[.08-u*.3,-.2+Math.sin(i*5.1)*.03*u,Math.cos(i*3.7)*.03*u],s:.05+.13*u,c:[.9,.93,.96],a:ag*.6*(1-u*.7)})}
  if(k>0){o.push({p:[-.25,-.2,0],s:(.1+.2*k)*(1+.08*Math.sin(t*25)),c:[1,.6,.25],a:.4+.6*k,add:1});o.push({p:[-.27,-.2,0],s:.05+.07*k,c:[.4,.7,1],a:.9,add:1})}
  else o.push({p:[-.25,-.14,0],s:.22,c:[.75,.78,.8],a:.25});return o},
 fun(P,t){const o=[],ox=cl((P.o2-16)/69),gq=Math.sqrt(G()),rad=Math.min(.3,(.06+.2*Math.sqrt(P.fuel/100))/Math.pow(P.pres,.33)/(1+.9*gq)),cool=P.o2<22&&P.fuel<35,soot=P.fuel>70&&P.o2<45,pu=1+.05*Math.sin(t*18);fxLight=cool?.25:.6+ox;
  if(cool)o.push({p:[.28,-.08,.38],s:rad*1.1*pu,c:[.62,.5,1],a:.35,add:1});
  else{o.push({p:[.28,-.08,.38],s:rad*1.25*pu,c:[.3+.2*ox,.62+.1*ox,1],a:.75+.25*ox,add:1});o.push({p:[.28,-.08,.385],s:rad*.45*pu,c:soot?[1,.8,.35]:[.85,.93,1],a:1,add:1});if(soot)o.push({p:[.28,-.08,.39],s:rad*.9,c:[1,.6,.2],a:.5,add:1});if(gq>0)for(let i=1;i<4;i++)o.push({p:[.28+.01*Math.sin(t*(9+i*4))*gq,-.08+rad*.5*i*gq,.385],s:rad*(1.15-.27*i)*pu,c:soot?[1,.7,.3]:[.45,.65,1],a:.6-.13*i,add:1})}return o},
 si(){fxLight=1;return[]}};
/* textures drawn on canvas */
function rackTex(seed,ac){const c=cv(2048,512),x=c.getContext('2d'),hc=cv(2048,512),hx=hc.getContext('2d'),r=rng(seed);
 const R2=(col,hh,a,b,w,h)=>{x.fillStyle=col;x.fillRect(a,b,w,h);hx.fillStyle='rgb('+hh+','+hh+','+hh+')';hx.fillRect(a,b,w,h)};
 const C2=(col,hh,a,b,rad)=>{x.fillStyle=col;x.beginPath();x.arc(a,b,rad,0,7);x.fill();hx.fillStyle='rgb('+hh+','+hh+','+hh+')';hx.beginPath();hx.arc(a,b,rad,0,7);hx.fill()};
 R2('#9fa29d',60,0,0,2048,512);const tone=['#d3d5cf','#cfcfc6','#d8d6cc','#c9ccc8'];
 for(let b=0;b<4;b++){const ox=b*512+12,w=488,kind=Math.floor(r()*3);R2(tone[Math.floor(r()*4)],128,ox,12,w,488);
  if(kind===0){for(let i=0;i<2;i++)for(let j=0;j<4;j++){const px=ox+8+i*240,py=20+j*120;R2('#8f928e',85,px,py,232,112);R2(r()<.25?'#e2dfd4':'#dcded8',150,px+3,py+3,226,106);
    R2('#5d6067',205,px+96,py+7,40,10);R2('#f1f1ec',156,px+14,py+68,96,30);R2(r()<.5?ac:'#2f5fa8',156,px+14,py+68,96,7);x.fillStyle='#555';for(let k=0;k<3;k++)x.fillRect(px+20,py+81+k*5,40+r()*40,2);
    if(r()<.3)R2('#27457f',165,px+150+r()*40,py+60+r()*20,22,22)}}
  else if(kind===1){R2('#bfc2bd',140,ox+8,20,w-16,472);R2('#0d1219',95,ox+38,48,264,154);x.fillStyle='rgba(95,176,255,.85)';for(let k=0;k<7;k++)x.fillRect(ox+52,64+k*18,60+r()*170,3);x.fillStyle=ac;x.fillRect(ox+52,186,120,5);
   for(let i=0;i<6;i++){const cx=ox+350+(i%2)*70,cy2=70+Math.floor(i/2)*60;C2('#8d9096',190,cx,cy2,19);C2('#2a2d33',80,cx,cy2,13)}
   for(let k=0;k<14;k++)R2('#6f726e',92,ox+40,248+k*9,260,3);for(let i=0;i<4;i++)C2('#3a3d44',215,ox+352+i*34,300,11);
   R2('#e9c21a',150,ox+340,360,130,36);x.fillStyle='#111';for(let k=0;k<6;k++){x.beginPath();x.moveTo(ox+340+k*20,396);x.lineTo(ox+352+k*20,360);x.lineTo(ox+362+k*20,360);x.lineTo(ox+350+k*20,396);x.fill()}
   R2('#f1f1ec',150,ox+40,410,200,60);x.fillStyle='#444';for(let k=0;k<5;k++)x.fillRect(ox+50,420+k*9,80+r()*90,2);for(let i=0;i<4;i++)for(let j=0;j<2;j++)C2('#74777c',185,ox+20+i*(w-40)/3,28+j*456,5)}
  else{for(let j=0;j<3;j++){const py=20+j*158;R2('#e4e1d6',165,ox+8,py,w-16,150);hx.fillStyle='rgb(180,180,180)';hx.fillRect(ox+30,py+20,w-60,110);x.strokeStyle='#bdb9ad';x.setLineDash([6,5]);x.lineWidth=2;x.strokeRect(ox+16,py+8,w-32,134);x.setLineDash([]);
    R2('#4a4e57',200,ox+110,py,22,150);R2('#4a4e57',200,ox+370,py,22,150);R2('#f4f4ee',185,ox+170,py+50,150,50);x.fillStyle=ac;x.fillRect(ox+170,py+50,150,8);x.fillStyle='#555';for(let k=0;k<4;k++)x.fillRect(ox+178,py+66+k*7,60+r()*70,2)}}
  R2('#85888c',100,b*512-6,0,12,512);for(let k=0;k<26;k++)C2('#4b4e54',55,b*512,10+k*20,3);
  for(let k=0;k<5;k++)R2(k%2?'#27457f':'#1e1f24',150,ox+20+r()*440,20+r()*460,16,16)}
 const im=x.getImageData(0,0,2048,512),d=im.data;for(let i=0;i<d.length;i+=4){const n=(r()-.5)*14;d[i]+=n;d[i+1]+=n;d[i+2]+=n}x.putImageData(im,0,0);
 [[0,80],[512,432]].forEach(e=>{const g=x.createLinearGradient(0,e[0],0,e[1]);g.addColorStop(0,'rgba(0,0,0,.46)');g.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=g;x.fillRect(0,Math.min(e[0],e[1]),2048,80)});
 hx.filter='blur(1.2px)';hx.drawImage(hc,0,0);const hd=hx.getImageData(0,0,2048,512).data,nc=cv(2048,512),nx=nc.getContext('2d'),ni=nx.createImageData(2048,512),nd=ni.data;
 for(let y=0;y<512;y++)for(let xx=0;xx<2048;xx++){const i=(y*2048+xx)*4,dx=(hd[(y*2048+Math.max(0,xx-1))*4]-hd[(y*2048+Math.min(2047,xx+1))*4])*.05,dy=(hd[(Math.min(511,y+1)*2048+xx)*4]-hd[(Math.max(0,y-1)*2048+xx)*4])*.05,k=1/Math.sqrt(dx*dx+dy*dy+1);nd[i]=(dx*k*.5+.5)*255;nd[i+1]=(dy*k*.5+.5)*255;nd[i+2]=(k*.5+.5)*255;nd[i+3]=255}
 nx.putImageData(ni,0,0);const nt=new THREE.CanvasTexture(nc);nt.anisotropy=8;return{map:ctex(c),normalMap:nt}}
function noisy(x,w,h,r,amt){const im=x.getImageData(0,0,w,h),d=im.data;for(let i=0;i<d.length;i+=4){const n=(r()-.5)*amt;d[i]+=n;d[i+1]+=n;d[i+2]+=n}x.putImageData(im,0,0)}
function endTex(ac){const c=cv(512,512),x=c.getContext('2d');x.fillStyle='#c9cbc6';x.fillRect(0,0,512,512);
 const rr=(a,b,w,h,r)=>{x.beginPath();x.moveTo(a+r,b);x.arcTo(a+w,b,a+w,b+h,r);x.arcTo(a+w,b+h,a,b+h,r);x.arcTo(a,b+h,a,b,r);x.arcTo(a,b,a+w,b,r);x.closePath()};
 x.fillStyle='#9a9da1';rr(96,96,320,320,60);x.fill();x.fillStyle='#07090d';rr(116,116,280,280,48);x.fill();
 for(let i=0;i<5;i++){const s=230-i*40,o=256-s/2;x.strokeStyle='rgba(190,200,215,'+(.32-i*.05)+')';x.lineWidth=5;rr(o,o,s,s,30-i*4);x.stroke()}
 x.fillStyle=ac;x.fillRect(180,60,152,14);x.fillStyle='#333';x.fillRect(196,440,120,8);return ctex(c)}
function screenTex(seed,ac){const c=cv(512,320),x=c.getContext('2d'),r=rng(seed);x.fillStyle='#0a0f18';x.fillRect(0,0,512,320);x.fillStyle='#17233a';x.fillRect(0,0,512,28);x.fillStyle='#cfe2ff';x.fillRect(12,10,120,8);
 x.strokeStyle=ac;x.lineWidth=3;x.beginPath();let y=180;for(let i=0;i<=24;i++){y+=(r()-.5)*44;y=Math.max(60,Math.min(250,y));x[i?'lineTo':'moveTo'](20+i*11,y)}x.stroke();
 for(let i=0;i<7;i++){x.fillStyle=i%3?'#3b6fb5':ac;const h=30+r()*150;x.fillRect(320+i*26,270-h,18,h)}x.fillStyle='#8fa3c4';for(let k=0;k<5;k++)x.fillRect(20,274+k*8,90+r()*160,3);return ctex(c)}
function noteTex(seed,ac){const c=cv(128,160),x=c.getContext('2d'),r=rng(seed);x.fillStyle=r()<.3?'#f3ecc4':'#f2f2ee';x.fillRect(0,0,128,160);x.fillStyle=r()<.5?ac:'#b3261e';x.fillRect(8,8,112,12);x.fillStyle='#4a4a4a';for(let k=0;k<12;k++)x.fillRect(10,30+k*10,40+r()*70,2);x.fillStyle='rgba(120,160,210,.5)';x.fillRect(40,0,48,6);return ctex(c)}
function bagTex(seed,ac){const c=cv(256,256),x=c.getContext('2d'),r=rng(seed);x.fillStyle='#e6e3d9';x.fillRect(0,0,256,256);noisy(x,256,256,r,22);
 x.strokeStyle='#bcb8ab';x.setLineDash([5,4]);x.strokeRect(10,10,236,236);x.setLineDash([]);x.fillStyle='#3c4048';x.fillRect(60,0,22,256);x.fillRect(174,0,22,256);x.fillStyle='#f7f7f3';x.fillRect(92,96,72,56);x.fillStyle=ac;x.fillRect(92,96,72,10);x.fillStyle='#444';for(let k=0;k<4;k++)x.fillRect(98,114+k*8,30+r()*30,2);return ctex(c)}
function fabricTex(css){const c=cv(128,256),x=c.getContext('2d'),r=rng(css.charCodeAt(1)*31+css.charCodeAt(3));x.fillStyle=css;x.fillRect(0,0,128,256);for(let i=0;i<9;i++){const g=x.createLinearGradient(i*15,0,i*15+15,0);g.addColorStop(0,'rgba(0,0,0,.28)');g.addColorStop(.5,'rgba(255,255,255,.1)');g.addColorStop(1,'rgba(0,0,0,.22)');x.fillStyle=g;x.fillRect(i*15,0,15,256)}noisy(x,128,256,r,16);return ctex(c)}
function padTex(){const c=cv(256,256),x=c.getContext('2d'),r=rng(91);x.fillStyle='#e8e6de';x.fillRect(0,0,256,256);noisy(x,256,256,r,14);
 for(let i=0;i<4;i++)for(let j=0;j<4;j++){const g=x.createRadialGradient(i*64+32,j*64+32,6,i*64+32,j*64+32,46);g.addColorStop(0,'rgba(255,255,255,.22)');g.addColorStop(1,'rgba(0,0,0,.2)');x.fillStyle=g;x.fillRect(i*64,j*64,64,64)}
 x.strokeStyle='#a9a69b';x.lineWidth=2;for(let i=0;i<=4;i++){x.beginPath();x.moveTo(i*64,0);x.lineTo(i*64,256);x.moveTo(0,i*64);x.lineTo(256,i*64);x.stroke()}x.fillStyle='#6f6c63';for(let i=0;i<=4;i++)for(let j=0;j<=4;j++){x.beginPath();x.arc(i*64,j*64,3,0,7);x.fill()}
 const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function ledTex(seed){const c=cv(256,512),x=c.getContext('2d'),r=rng(seed);x.fillStyle='#07090c';x.fillRect(0,0,256,512);for(let j=0;j<16;j++){x.fillStyle='#11151b';x.fillRect(8,6+j*32,240,26);for(let i=0;i<14;i++){const q=r();if(q<.35)continue;x.fillStyle=q<.8?'#3dff7a':q<.93?'#ffb02e':'#4aa3ff';x.fillRect(16+i*16,14+j*32,5,5)}x.fillStyle='#2b3038';x.fillRect(180,12+j*32,60,3)}return ctex(c)}
function dialTex(a){const c=cv(128,128),x=c.getContext('2d');x.fillStyle='#22252a';x.fillRect(0,0,128,128);x.fillStyle='#f3f3ef';x.beginPath();x.arc(64,64,58,0,7);x.fill();x.strokeStyle='#22252a';x.lineWidth=2;for(let i=0;i<=10;i++){const t=Math.PI*(.75+i*.15);x.beginPath();x.moveTo(64+Math.cos(t)*42,64+Math.sin(t)*42);x.lineTo(64+Math.cos(t)*53,64+Math.sin(t)*53);x.stroke()}
 const t=Math.PI*(.75+a*1.5);x.strokeStyle='#c0261c';x.lineWidth=4;x.beginPath();x.moveTo(64,64);x.lineTo(64+Math.cos(t)*42,64+Math.sin(t)*42);x.stroke();x.fillStyle='#22252a';x.beginPath();x.arc(64,64,6,0,7);x.fill();return ctex(c)}
function signTex(){const c=cv(256,150),x=c.getContext('2d');x.fillStyle='#e9c21a';x.fillRect(0,0,256,150);x.strokeStyle='#111';x.lineWidth=8;x.strokeRect(6,6,244,138);x.fillStyle='#111';x.font='bold 54px sans-serif';x.textAlign='center';x.fillText('HIGH O₂',128,74);x.font='bold 19px sans-serif';x.fillText('NO IGNITION SOURCES',128,116);return ctex(c)}
const M=(c,o)=>new THREE.MeshStandardMaterial(Object.assign({color:c,roughness:.6,metalness:.15},o||{}));
const bx=(w,h,d,m)=>new THREE.Mesh(new THREE.BoxGeometry(w,h,d),m);
const cy=(r,l,m,ax,r2)=>{const g=new THREE.Mesh(new THREE.CylinderGeometry(r2===undefined?r:r2,r,l,28),m);if(ax==='x')g.rotation.z=Math.PI/2;if(ax==='z')g.rotation.x=Math.PI/2;return g};
const at=(o,x,y,z)=>{o.position.set(x,y,z);return o};
const STEEL={metalness:.75,roughness:.3};
function ctrl(g,y,z,seed,ac){const q=new THREE.Group();q.add(bx(.07,.4,.56,M(0x33373e,{metalness:.5,roughness:.45})));const s=new THREE.Mesh(new THREE.PlaneGeometry(.26,.17),new THREE.MeshBasicMaterial({map:screenTex(seed,ac)}));s.rotation.y=-Math.PI/2;q.add(at(s,-.037,.08,.1));
 for(let i=0;i<4;i++)q.add(at(cy(.02,.03,M(0x15171b,{metalness:.6}),'x'),-.045,-.1,-.2+i*.075));for(let i=0;i<3;i++)q.add(at(new THREE.Mesh(new THREE.SphereGeometry(.008,10,8),new THREE.MeshBasicMaterial({color:[0x4dff88,0xffc93b,0x4dff88][i]})),-.037,.16,-.2+i*.04));g.add(at(q,RW/2-.035,y,z))}
function suit(g,x,z,ry){const q=new THREE.Group(),w=M(0xe8e8e4,{roughness:.9}),gd=M(0xc9a23a,{metalness:1,roughness:.18}),gr=M(0x8b8f95,{roughness:.8});
 q.add(at(cy(.24,.5,w,'y',.2),0,.1,0));q.add(at(new THREE.Mesh(new THREE.SphereGeometry(.19,28,20),w),0,.5,0));const vis=new THREE.Mesh(new THREE.SphereGeometry(.168,28,20,0,Math.PI*2,0,Math.PI/2),gd);vis.rotation.x=Math.PI/2;q.add(at(vis,0,.5,.05));
 q.add(at(bx(.46,.62,.2,w),0,.15,-.2));q.add(at(bx(.2,.14,.08,gr),0,.12,.24));q.add(at(cy(.2,.05,gr,'y'),0,.36,0));
 [-1,1].forEach(k=>{const a=cy(.075,.5,w,'y');a.rotation.z=k*.35;q.add(at(a,k*.33,.05,0));q.add(at(new THREE.Mesh(new THREE.SphereGeometry(.07,14,10),gr),k*.42,-.2,0));q.add(at(cy(.095,.6,w,'y'),k*.12,-.5,0));q.add(at(bx(.12,.08,.22,gr),k*.12,-.84,.03))});
 q.rotation.y=ry;g.add(at(q,x,-.05,z))}
/* the experiment in each room; z is relative to the experiment position */
const FEAT={
 prev(f,g,md){const q=new THREE.Group(),fr=M(0x8d9197,STEEL);q.add(bx(1,.34,.34,new THREE.MeshStandardMaterial({color:0xbfd4e6,transparent:true,opacity:.14,roughness:.05,depthWrite:false})));
  [-1,1].forEach(a=>[-1,1].forEach(b=>q.add(at(bx(1,.022,.022,fr),0,a*.17,b*.17))));[-.5,.5].forEach(k=>q.add(at(bx(.03,.38,.38,M(0x5c6068,STEEL)),k,0,0)));
  q.add(at(cy(.15,.1,M(0x30333a,{metalness:.5}),'x'),.6,0,0));q.add(at(cy(.05,.12,fr,'x'),.7,0,0));q.add(at(bx(.34,.006,.1,M(0xd8cfb4,{roughness:.95})),.05,0,0));q.add(at(cy(.004,.3,fr,'y'),.2,-.08,0));
  const sp=new THREE.Group();for(let i=0;i<4;i++){const b=bx(.012,.26,.05,M(0x9a9da2,STEEL));b.rotation.x=i*Math.PI/4;sp.add(b)}q.add(at(sp,.53,0,0));g.userData.spin=[{o:sp,ax:'x'}];
  const ig=new THREE.Mesh(new THREE.TorusGeometry(.02,.005,8,20),new THREE.MeshStandardMaterial({color:0x3a3a3a,emissive:0xff5a1e,emissiveIntensity:0,metalness:.8,roughness:.4}));ig.rotation.y=Math.PI/2;q.add(at(ig,-.135,0,0));q.add(at(cy(.003,.17,fr,'y'),-.135,-.085,0));g.userData.ign=ig;
  const pl=new THREE.PointLight(0xff9a4d,.8,2);pl.position.set(-.1,.1,.2);q.add(pl);g.userData.fl=pl;[-.3,.3].forEach(k=>q.add(at(bx(.05,.52,.05,fr),k,-.43,0)));q.add(at(bx(.8,.04,.4,M(0x3a3d44,{metalness:.5})),0,-.68,0));
  f.add(at(q,.3,-.4,0));ctrl(f,.05,-.05,md.seed+31,md.c);f.add(at(cy(.06,.4,M(0x2f62b0,{metalness:.4,roughness:.4}),'y'),RW/2-.14,-.55,.45));f.add(at(cy(.018,.05,fr,'y'),RW/2-.14,-.33,.45));
  [0xcfc8b4,0x6b7a8f,0x3a3d44,0xb5523a,0xe0ddd2,0x58705a,0x8c6f4e,0x2f4f7f,0xd9d9d9,0x70685c,0xa8a39a,0x444a55].forEach((c,i)=>f.add(at(bx(.02,.14,.14,new THREE.MeshStandardMaterial({map:fabricTex('#'+c.toString(16).padStart(6,'0')),roughness:.95})),-(RW/2-.05),.5-Math.floor(i/4)*.18,-.15-(i%4)*.18)));f.add(at(bx(.02,.62,.8,M(0x2b2e34)),-(RW/2-.03),.32,-.42))},
 det(f,g,md){[-.75,.65].forEach(z=>{f.add(at(bx(.24,.07,.17,M(0xe6e6e2)),.15,.845,z));f.add(at(cy(.05,.03,M(0x2b2e34),'y'),.15,.8,z))});
  f.add(at(bx(.24,.18,.24,M(0x9da1a7,STEEL)),.2,-.45,0));f.add(at(cy(.018,.56,M(0x8b8f95,STEEL),'y'),.2,-.81,0));f.add(at(cy(.03,.06,M(0x2a2d33),'y'),.2,-.34,0));f.add(at(bx(.3,.03,.3,M(0x3a3d44,{metalness:.5})),.2,-1.07,0));
  f.add(at(cy(.004,RW-.3,new THREE.MeshBasicMaterial({color:0xff3b30}),'x'),0,.12,0));[-1,1].forEach(k=>f.add(at(bx(.12,.1,.14,M(0x2a2d33,{metalness:.4})),k*(RW/2-.1),.12,0)));ctrl(f,-.25,-1.75,md.seed+31,md.c)},
 sup(f,g,md){[0,1,2].forEach(i=>{const q=new THREE.Group();q.add(cy(.075,.42,M(0xd9c21f,{metalness:.3,roughness:.45}),'y'));q.add(at(cy(.077,.05,M(0xb3261e),'y'),0,.1,0));q.add(at(cy(.03,.09,M(0x2a2d33),'y'),0,.25,0));q.add(at(cy(.012,.22,M(0x1c1e22),'x',.03),-.12,.28,0));q.add(at(bx(.17,.03,.17,M(0x8b8f95,STEEL)),0,-.1,0));f.add(at(q,RW/2-.2,-.05,-.1-i*.27))});
  f.add(at(bx(.04,.1,.9,M(0x8b8f95,STEEL)),RW/2-.1,-.05,-.37));
  const q=new THREE.Group();q.add(new THREE.Mesh(new THREE.SphereGeometry(.28,36,24),new THREE.MeshStandardMaterial({color:0xc8dcef,transparent:true,opacity:.13,roughness:.04,depthWrite:false})));
  const ring=new THREE.Mesh(new THREE.TorusGeometry(.285,.014,10,48),M(0x8d9197,STEEL));ring.rotation.x=Math.PI/2;q.add(ring);const ring2=ring.clone();ring2.rotation.x=0;q.add(ring2);
  q.add(at(cy(.012,.34,M(0x30333a,STEEL),'x'),.38,0,0));q.add(at(cy(.03,.1,M(0x8d9197,STEEL),'x'),.58,0,0));q.add(at(cy(.006,.2,M(0x8d9197,STEEL),'y'),0,-.1,0));
  const pl=new THREE.PointLight(0xffa050,.7,2);pl.position.set(0,.1,.35);q.add(pl);g.userData.fl=pl;q.add(at(cy(.02,.5,M(0x8b8f95,STEEL),'y'),0,-.53,0));q.add(at(bx(.4,.04,.4,M(0x3a3d44,{metalness:.5})),0,-.77,0));f.add(at(q,-.25,-.2,0))},
 fun(f,g,md){const q=new THREE.Group();q.add(cy(.34,.95,M(0xb9bdc3,STEEL),'x'));[-.5,.5].forEach(k=>q.add(at(cy(.37,.07,M(0x7d8188,STEEL),'x'),k,0,0)));[-.25,0,.25].forEach(k=>q.add(at(cy(.345,.02,M(0x8f949b,STEEL),'x'),k,0,0)));
  q.add(at(cy(.21,.06,M(0x6f747b,STEEL),'z'),0,0,.33));const gls=new THREE.Mesh(new THREE.CircleGeometry(.17,40),new THREE.MeshStandardMaterial({color:0x04070c,roughness:.08,metalness:.6}));gls.position.z=.362;q.add(gls);
  for(let i=0;i<10;i++){const a=i/10*6.2832;q.add(at(cy(.014,.03,M(0x3b3e44),'z'),Math.cos(a)*.19,Math.sin(a)*.19,.365))}
  const pl=new THREE.PointLight(0x5fb0ff,1.1,2.4);pl.position.set(0,0,.65);q.add(pl);g.userData.fl=pl;q.add(at(bx(.5,.5,.1,M(0x8a8e94,STEEL)),.62,0,0));f.add(at(q,RW/2-.82,-.08,0));
  [0x2f62b0,0xd8d8d8,0xc0392b].forEach((c,i)=>{f.add(at(cy(.07,.5,M(c,{metalness:.4,roughness:.4}),'y'),RW/2-.16,-.6,-.85-i*.19));f.add(at(cy(.02,.06,M(0x8d9197,STEEL),'y'),RW/2-.16,-.32,-.85-i*.19))});ctrl(f,.5,.78,md.seed+31,md.c)},
 si(f,g,md){[-1,0,1].forEach(k=>{const s=new THREE.Mesh(new THREE.PlaneGeometry(.78,.49),new THREE.MeshBasicMaterial({map:screenTex(60+k*7,'#5fb0ff')}));s.position.set(k*.74,.12,-.15+Math.abs(k)*.2);s.rotation.y=-k*.42;f.add(s);const b=bx(.83,.54,.04,M(0x15181d));b.position.copy(s.position);b.rotation.copy(s.rotation);b.translateZ(-.025);f.add(b)});
  f.add(at(bx(1.9,.05,.5,M(0x2a2e35,{metalness:.4})),0,-.3,.1));f.add(at(bx(.52,.015,.17,M(0x0f1114)),0,-.27,.2));f.add(at(bx(.1,.02,.06,M(0x0f1114)),.42,-.265,.2));[-.5,.5].forEach(k=>f.add(at(bx(.05,.8,.05,M(0x8b8f95,STEEL)),k*1.5,-.7,.1)));
  f.add(at(cy(.02,.3,M(0x8b8f95,STEEL),'y'),0,-.14,-.2));const pl=new THREE.PointLight(0x5fb0ff,.9,3.5);pl.position.set(0,.2,.4);f.add(pl)}
};
/* what makes each room its own place */
const PROPS={
 /* habitat: a crew quarter with its curtain, a sleeping bag, the galley table with food packs, towels, a plant growth box */
 prev(g,st,r){const W=RW,x0=-(W/2-.03),tx=W/2-.42,fabric=c=>new THREE.MeshStandardMaterial({map:fabricTex(c),roughness:1});
  g.add(at(bx(.05,1.55,.8,M(0x1c2027)),x0,-.05,-2.85));g.add(at(bx(.03,1.5,.5,fabric('#3d5276')),x0+.04,-.05,-2.71));[-.42,.42].forEach(k=>g.add(at(bx(.07,1.62,.05,M(0x9a9da2,STEEL)),x0+.03,-.05,-2.85+k)));
  g.add(at(cy(.13,.55,fabric('#4b5d7a'),'z'),x0+.2,.75,-2.0));[-.15,.15].forEach(k=>g.add(at(cy(.135,.03,M(0x2b2e34),'z'),x0+.2,.75,-2.0+k)));
  g.add(at(bx(.7,.03,.5,M(0xd9d6cc)),tx,-.32,.95));g.add(at(cy(.02,.72,M(0x9a9da2,STEEL),'y'),tx,-.69,.95));
  [[0xc7ccd2,-.2,.1,.8],[0xb3261e,-.02,-.08,.1],[0x3c7a4a,.14,.1,.1],[0xd9b21f,.22,-.1,.1],[0xc7ccd2,.02,.14,.8]].forEach(q=>g.add(at(bx(.12,.035,.09,M(q[0],{metalness:q[3],roughness:.35})),tx+q[1],-.285,.95+q[2])));
  g.add(at(bx(.4,.3,.3,M(0x2a2d33)),W/2-.2,.55,-2.9));const pl=new THREE.Mesh(new THREE.PlaneGeometry(.26,.24),new THREE.MeshBasicMaterial({color:0xd24bd0}));pl.rotation.y=-Math.PI/2;g.add(at(pl,W/2-.405,.55,-2.9));for(let i=0;i<5;i++)g.add(at(new THREE.Mesh(new THREE.SphereGeometry(.035,10,8),M(0x3f8a45,{roughness:.9})),W/2-.44,.47+r()*.1,-3.0+i*.05));
  ['#24385e','#8c8f94','#c8641e'].forEach((c,i)=>g.add(at(bx(.05,.3,.24,fabric(c)),W/2-.04,-.1,-1.7-i*.28)))},
 /* command module: the cabin ventilation duct that carries smoke to the detectors, its fan, and avionics bays with status lights */
 det(g,st,r,md){const W=RW,H=RH,L=st.L,d=M(0xb9bdc1,{metalness:.5,roughness:.5});
  g.add(at(bx(.6,.22,L-.5,d),0,H/2-.13,0));for(let i=0;i<7;i++){const z=-L/2+.8+i*(L-1.6)/6;g.add(at(bx(.4,.01,.22,M(0x15171b)),0,H/2-.245,z));for(let k=0;k<5;k++)g.add(at(bx(.4,.012,.012,d),0,H/2-.25,z-.09+k*.045))}
  const fan=new THREE.Group();fan.add(cy(.26,.16,M(0x30333a,{metalness:.5}),'z'));const sp=new THREE.Group();sp.add(cy(.07,.04,M(0x9a9da2,STEEL),'z'));for(let i=0;i<6;i++){const b=bx(.2,.05,.01,M(0x8b8f95,STEEL)),a=i/6*6.2832;b.rotation.z=a;b.position.set(Math.cos(a)*.13,Math.sin(a)*.13,0);sp.add(b)}fan.add(at(sp,0,0,.09));g.add(at(fan,-.6,H/2-.5,-L/2+.2));g.userData.spin=[{o:sp,ax:'z'}];
  [.9,-1.2,-2.9].forEach((z,i)=>{const t=ledTex(md.seed+70+i),m=new THREE.MeshStandardMaterial({map:t,emissiveMap:t,emissive:0xffffff,emissiveIntensity:1.1,roughness:.4,metalness:.5});g.add(at(bx(.1,1.0,.62,M(0x1d2026,{metalness:.5})),W/2-.05,.1,z));const f=new THREE.Mesh(new THREE.PlaneGeometry(.58,.96),m);f.rotation.y=-Math.PI/2;g.add(at(f,W/2-.102,.1,z));[-.26,.26].forEach(k=>g.add(at(cy(.012,.5,M(0x9a9da2,STEEL),'y'),W/2-.13,.1,z+k)))})},
 /* airlock: two spacesuits, a tool board and the high-oxygen caution by the hatch */
 sup(g,st){suit(g,-.82,-1.5,Math.PI/2);suit(g,.8,-1.85,-Math.PI/2);
  g.add(at(bx(.5,.36,.03,M(0x7b8087,{metalness:.5})),.62,.5,-st.L/2+.06));[0xb3261e,0xd9b21f,0x2f62b0,0x8b8f95].forEach((c,i)=>g.add(at(bx(.035,.2+i%2*.06,.03,M(c)),.47+i*.1,.5,-st.L/2+.09)));
  g.add(at(new THREE.Mesh(new THREE.PlaneGeometry(.36,.21),new THREE.MeshBasicMaterial({map:signTex()})),-.68,.52,-st.L/2+.02))},
 /* refuelling module: propellant tanks, the lines and valves that feed the chamber, and pressure gauges */
 fun(g,st){const W=RW,x0=-(W/2-.36),stl=M(0xb5bac0,STEEL);
  [[.32,-2.2,0xe6e6e2,0x2f62b0],[-.42,-2.2,0xe6e6e2,0xb3261e],[.32,-.75,0xd8d8d8,0x3c7a4a]].forEach(q=>{const t=new THREE.Group(),m=M(q[2],{metalness:.35,roughness:.4});t.add(cy(.3,1.0,m,'z'));[-.5,.5].forEach(k=>t.add(at(new THREE.Mesh(new THREE.SphereGeometry(.3,28,18),m),0,0,k)));t.add(cy(.305,.16,M(q[3]),'z'));[-.35,.35].forEach(k=>t.add(at(cy(.31,.03,stl,'z'),0,0,k)));g.add(at(t,x0,q[0],q[1]))});
  const pipe=pts=>g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map(p=>new V(p[0],p[1],p[2])),false,'catmullrom',.05),70,.022,10),stl));
  pipe([[x0+.1,.62,-2.2],[x0+.1,.94,-2.2],[.2,.97,-2.2],[.2,.97,st.fz],[W/2-.82,.97,st.fz],[W/2-.82,.3,st.fz]]);pipe([[x0+.1,-.12,-2.2],[x0+.34,.1,-1.8],[x0+.34,.88,-1.4],[.5,.9,-1.2],[W/2-.6,.9,st.fz],[W/2-.6,.3,st.fz]]);pipe([[x0+.1,.62,-.75],[x0+.1,.84,-.75],[.3,.86,-.8],[W/2-1.04,.86,st.fz],[W/2-1.04,.3,st.fz]]);
  [[.2,.97,-1.5],[.5,.9,-1.2],[.3,.86,-.8]].forEach(p=>{g.add(at(cy(.04,.09,M(0x6f747b,STEEL),'y'),p[0],p[1],p[2]));const w=new THREE.Mesh(new THREE.TorusGeometry(.055,.012,8,24),M(0xb3261e));w.rotation.x=Math.PI/2;g.add(at(w,p[0],p[1]-.08,p[2]))});
  g.add(at(bx(.03,.3,.7,M(0x33373e,{metalness:.5})),W/2-.02,.55,st.fz-.9));[0,1,2].forEach(i=>{const d=new THREE.Mesh(new THREE.CircleGeometry(.085,28),new THREE.MeshBasicMaterial({map:dialTex(.2+i*.3)}));d.rotation.y=-Math.PI/2;g.add(at(d,W/2-.04,.55,st.fz-1.12+i*.22))})},
 /* power and control: computing racks with status lights, floor light strips, an overhead cable tray */
 si(g,st,r,md){const W=RW,H=RH;
  [[-1,.75],[-1,-.15],[1,.75],[1,-.15]].forEach((q,i)=>{const t=ledTex(md.seed+80+i),m=new THREE.MeshStandardMaterial({map:t,emissiveMap:t,emissive:0xffffff,emissiveIntensity:1.3,roughness:.4,metalness:.5});g.add(at(bx(.34,1.9,.8,M(0x14171c,{metalness:.5,roughness:.5})),q[0]*(W/2-.17),0,q[1]));const f=new THREE.Mesh(new THREE.PlaneGeometry(.74,1.84),m);f.rotation.y=-q[0]*Math.PI/2;g.add(at(f,q[0]*(W/2-.345),0,q[1]))});
  [-1,1].forEach(k=>g.add(at(bx(.03,.02,st.L-.6,new THREE.MeshBasicMaterial({color:0x2f7dff})),k*(W/2-.36),-(H/2-.03),0)));g.add(at(bx(.5,.06,st.L-.8,M(0x24272d,{metalness:.5})),0,H/2-.2,0))}
};
function buildRoom(md){const g=new THREE.Group(),st=STYLE[md.id],id=md.id,ac=md.rc||md.c,W=RW,H=RH,L=st.L,r=rng(md.seed),gy=M(0x9a9da2,STEEL),dk=M(0x2b2e34,{metalness:.4,roughness:.5}),wh=M(0xbdbdb8),hm=M(0x2f62b0,{metalness:.5,roughness:.35});
 const lm=new THREE.MeshStandardMaterial({color:0xffffff,emissive:st.lc,emissiveIntensity:1.7*Math.max(.75,st.li)}),winDisc=rad=>new THREE.Mesh(new THREE.CircleGeometry(rad,44),new THREE.MeshBasicMaterial({map:winRT.texture}));
 const cab=(pts,col,rad,o2)=>g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map(p=>new V(p[0],p[1],p[2]))),64,rad,10),M(col,Object.assign({roughness:.8},o2||{}))));
 if(st.round){ /* airlock: a padded cylinder with ring frames, a floor grating and a round hatch whose window shows the Moon */
  const pt=padTex();pt.repeat.set(8,3);const c=new THREE.Mesh(new THREE.CylinderGeometry(1.2,1.2,L,56,1,true),new THREE.MeshStandardMaterial({map:pt,roughness:.9,color:st.wall,side:THREE.BackSide}));c.rotation.x=Math.PI/2;g.add(c);
  for(let i=0;i<=4;i++)g.add(at(new THREE.Mesh(new THREE.TorusGeometry(1.185,.035,8,72),gy),0,0,-L/2+i*L/4));
  g.add(at(bx(1.3,.03,L,M(0x70757c,{metalness:.6,roughness:.5})),0,-.99,0));for(let i=0;i<14;i++)g.add(at(bx(1.3,.012,.03,dk),0,-.972,-L/2+.2+i*(L-.4)/13));
  [-1,1].forEach(k=>{const l=bx(.12,.03,L*.72,lm);l.rotation.z=-k*.35;g.add(at(l,k*.42,1.1,0));g.add(at(cy(.017,L*.6,hm,'z'),k*1.07,.3,0))});
  const fe=new THREE.Mesh(new THREE.CircleGeometry(1.2,56),M(0xa9acaa));g.add(at(fe,0,0,-L/2));const ne=fe.clone();ne.rotation.y=Math.PI;g.add(at(ne,0,0,L/2));
  g.add(at(cy(.56,.1,M(0xd6d7d3),'z'),0,0,-L/2+.05));g.add(at(cy(.6,.04,gy,'z'),0,0,-L/2+.02));g.add(at(cy(.17,.03,dk,'z'),0,.2,-L/2+.105));g.add(at(winDisc(.14),0,.2,-L/2+.122));
  g.add(at(new THREE.Mesh(new THREE.TorusGeometry(.2,.018,8,36),gy),0,-.2,-L/2+.16));[0,1,2].forEach(i=>{const s=cy(.012,.4,gy,'x');s.rotation.z=Math.PI/2+i*Math.PI/3;g.add(at(s,0,-.2,-L/2+.16))});g.add(at(cy(.03,.08,gy,'z'),0,-.2,-L/2+.13));
  cab([[-.5,-.96,L/2-.3],[-.3,-.95,.4],[-.55,-.96,-1],[-.2,-.95,-L/2+.4]],0x2a2d33,.014);cab([[.9,.75,L/2-.3],[.95,.6,.6],[.92,.7,-.6],[.96,.55,-L/2+.4]],0xdadada,.014);
 }else{ /* rack module: four walls of racks, each with its own local frame (x along the module, y across, z into the room) */
  const walls=[[-Math.PI/2,0,Math.PI/2,0,-H/2],[Math.PI/2,0,Math.PI/2,0,H/2],[0,Math.PI/2,0,-W/2,0],[0,-Math.PI/2,0,W/2,0]].map((a,i)=>{const wg=new THREE.Group();wg.rotation.set(a[0],a[1],a[2]);wg.position.set(a[3],a[4],0);const t=rackTex(md.seed+1+i,ac);t.map.repeat.x=t.normalMap.repeat.x=L/7;t.map.wrapS=t.normalMap.wrapS=THREE.RepeatWrapping;
   wg.add(new THREE.Mesh(new THREE.PlaneGeometry(L,W),new THREE.MeshStandardMaterial({map:t.map,normalMap:t.normalMap,normalScale:new THREE.Vector2(.9,.9),roughness:.58,metalness:.05,color:st.wall})));g.add(wg);return wg});
  walls.forEach((wg,wi)=>{for(let b=0;b<=4;b++)wg.add(at(bx(.05,W-.34,.035,gy),-L/2+b*L/4,0,.017));
   for(let k=0;k<st.cl;k++){const lx=(r()-.5)*(L-.7),ly=(r()-.5)*(W-.8),t=Math.floor(r()*4);
    if(t===0){wg.add(at(bx(.24+r()*.2,.15+r()*.1,.07,wh),lx,ly,.035));wg.add(at(bx(.1,.035,.02,dk),lx,ly,.08))}
    else if(t===1){for(let i=0;i<3;i++)wg.add(at(cy(.022,.05,gy,'z'),lx+i*.07,ly,.025))}
    else if(t===2){wg.add(at(bx(.3,.2,.02,dk),lx,ly,.012));for(let i=0;i<5;i++)wg.add(at(bx(.26,.012,.012,gy),lx,ly-.07+i*.035,.026))}
    else{const p=new THREE.Mesh(new THREE.PlaneGeometry(.17,.22),new THREE.MeshStandardMaterial({map:noteTex(md.seed+wi*9+k,ac),roughness:.9}));p.rotation.z=(r()-.5)*.3;wg.add(at(p,lx,ly,.006))}}});
  const nl=Math.round(L/1.7);for(let i=0;i<nl;i++)[-.6,.6].forEach(ly=>{const lx=-L/2+1+i*(L-2)/(nl-1);walls[1].add(at(bx(.95,.19,.05,gy),lx,ly,.025));walls[1].add(at(bx(.86,.12,.02,lm),lx,ly,.056))});
  if(id!=='si')for(let i=0;i<3;i++){const t=new THREE.Mesh(new THREE.TorusGeometry(.1,.013,8,24,Math.PI),M(0xd9b21f));t.rotation.x=Math.PI/2;walls[0].add(at(t,-1.4+i*1.4,.45-i*.35,0))}
  if(id==='prev'||id==='det'){const win=new THREE.Group();win.add(new THREE.Mesh(new THREE.TorusGeometry(.24,.04,12,44),gy));win.add(at(cy(.245,.03,dk,'z'),0,0,-.01));win.add(at(winDisc(.21),0,0,.012));for(let i=0;i<8;i++){const a=i/8*6.2832;win.add(at(cy(.012,.02,dk,'z'),Math.cos(a)*.24,Math.sin(a)*.24,.045))}walls[2].add(at(win,id==='prev'?.1:-.3,.28,.02))}
  /* far end: a hatch opening with a tunnel to the next module; near end: a closed hatch */
  const ew=M(0xb2b3ae),o=.5;[[-(W/2+o)/2,0,W/2-o,H],[(W/2+o)/2,0,W/2-o,H],[0,(H/2+o)/2,2*o,H/2-o],[0,-(H/2+o)/2,2*o,H/2-o]].forEach(q=>g.add(at(bx(q[2],q[3],.08,ew),q[0],q[1],-L/2+.04)));
  [[0,o,2*o+.14,.07],[0,-o,2*o+.14,.07],[o,0,.07,2*o+.14],[-o,0,.07,2*o+.14]].forEach(q=>g.add(at(bx(q[2],q[3],.16,gy),q[0],q[1],-L/2+.08)));
  g.add(at(new THREE.Mesh(new THREE.BoxGeometry(2*o,2*o,1.5),new THREE.MeshStandardMaterial({color:0x8b8e92,roughness:.7,side:THREE.BackSide})),0,0,-L/2-.75));
  g.add(at(new THREE.Mesh(new THREE.PlaneGeometry(2*o,2*o),new THREE.MeshBasicMaterial({map:walls[3].children[0].material.map,color:0x4b5058})),0,0,-L/2-1.49));g.add(at(bx(.4,.06,.02,M(new THREE.Color(ac).getHex())),0,o+.2,-L/2+.09));
  const ne=new THREE.Mesh(new THREE.PlaneGeometry(W,H),new THREE.MeshStandardMaterial({map:endTex(ac),roughness:.7,color:st.wall}));ne.position.z=L/2;ne.rotation.y=Math.PI;g.add(ne);
  [[-1,-1],[1,-1],[-1,1],[1,1]].forEach(s=>{const b=bx(.3,.3,L,M(0x9ea2a7,{metalness:.5,roughness:.45}));b.rotation.z=Math.PI/4;g.add(at(b,s[0]*(W/2-.02),s[1]*(H/2-.02),0))});
  const rail=(x,y,z,len)=>{g.add(at(cy(.017,len,hm,'z'),x,y,z));const sx=Math.abs(x)>Math.abs(y);[-1,1].forEach(k=>g.add(at(cy(.012,.08,hm,sx?'x':'y'),x+(sx?Math.sign(x)*.04:0),y+(sx?0:Math.sign(y)*.04),z+k*(len/2-.04))))};
  for(let i=0;i<Math.floor(L/1.7);i++){const z=-L/2+1.1+i*1.6;if(id!=='si'&&id!=='fun')rail(-(W/2-.1),.25,z,.55);if(id!=='si'&&id!=='det')rail(W/2-.1,-.3,z+.5,.55);rail(id==='det'?.75:.25,H/2-.1,z+.2,.55);rail(-.4,-(H/2-.1),z+.7,.55)}
  [-1,1].forEach(k=>g.add(at(cy(.017,.5,hm,'y'),k*(o+.2),0,-L/2+.15)));
  if(id!=='det'&&id!=='si')cab([[-(W/2-.3),H/2-.22,-L/2+.2],[-(W/2-.34),H/2-.26,-1.5],[-(W/2-.3),H/2-.22,.5],[-(W/2-.36),H/2-.27,L/2-.2]],0xb9bdc3,.07,{metalness:.7,roughness:.35});
  cab([[W/2-.25,H/2-.3,-L/2+.4],[W/2-.35,H/2-.42,-1.5],[W/2-.3,H/2-.33,0],[W/2-.4,H/2-.5,1.4],[W/2-.28,H/2-.32,L/2-.4]],0xdadada,.016);
  cab([[W/2-.3,H/2-.34,-L/2+.4],[W/2-.42,H/2-.46,-1.2],[W/2-.33,H/2-.4,.3],[W/2-.45,H/2-.52,1.7],[W/2-.3,H/2-.36,L/2-.4]],0x2a2d33,.011);
  cab([[.2,-(H/2-.06),-L/2+.5],[.5,-(H/2-.1),-.5],[.1,-(H/2-.06),1.2],[.4,-(H/2-.08),L/2-.6]],0x2a2d33,.014);cab([[-.6,-(H/2-.05),-L/2+.8],[-.3,-(H/2-.07),.2],[-.7,-(H/2-.05),L/2-.9]],id==='si'?0x2f7dff:0xe2e2e2,.01);
  const fab=new THREE.MeshStandardMaterial({map:bagTex(md.seed+5,ac),roughness:.97,color:0xc4c2ba});for(let i=0;i<st.bags;i++){const b=bx(.45+r()*.25,.28+r()*.16,.4+r()*.25,fab);b.rotation.set((r()-.5)*.25,(r()-.5)*.6,(r()-.5)*.18);g.add(at(b,-(W/2-.4)+r()*.25,-(H/2-.2),st.cz-.6-i*1.15+r()*.3))}
  const lap=(side,y,z,seed)=>{const x=side*(W/2-.44),ry=-side*.5;g.add(at(cy(.012,.44,gy,'x'),side*(W/2-.22),y-.16,z-.03));g.add(at(cy(.02,.05,dk,'y'),x,y-.16,z-.03));const s=bx(.36,.24,.016,M(0x1c1f25));s.rotation.y=ry;g.add(at(s,x,y,z));
   const kb=bx(.36,.016,.24,M(0x202328));kb.rotation.y=ry;kb.position.set(x+Math.sin(ry)*.11,y-.125,z+Math.cos(ry)*.11);g.add(kb);const sc=new THREE.Mesh(new THREE.PlaneGeometry(.33,.205),new THREE.MeshBasicMaterial({map:screenTex(seed,ac)}));sc.rotation.y=ry;sc.position.set(x+Math.sin(ry)*.01,y,z+Math.cos(ry)*.01);g.add(sc)};
  if(id!=='si')lap(-1,.2,st.cz-(id==='fun'?.9:1),md.seed+7);
  if(id!=='si'){const cg=new THREE.Group();cg.add(bx(.13,.1,.17,dk));cg.add(at(cy(.04,.09,M(0x15171b,{metalness:.6}),'z'),0,0,.12));cg.add(at(cy(.012,.3,gy,'y'),0,.2,0));cg.rotation.y=.5;g.add(at(cg,W/2-.5,H/2-.48,st.cz-1.3))}
 }
 /* light: soft fill, ceiling points, and one shadow-casting spot */
 g.add(new THREE.HemisphereLight(st.lc,0x5a5f66,.1*st.li));for(let i=0;i<4;i++){const p=new THREE.PointLight(st.lc,.15*st.li,5,2);p.position.set(0,H/2-.35,-L/2+.8+i*(L-1.6)/3);g.add(p)}
 const sp=new THREE.SpotLight(st.lc,.5*st.li,11,1.2,.85,1.1);sp.position.set(.3,H/2-.14,st.cz-1);sp.target.position.set(-.05,-H/2,st.fz-.6);sp.castShadow=true;sp.shadow.mapSize.set(2048,2048);sp.shadow.bias=-.0009;sp.shadow.camera.near=.2;sp.shadow.camera.far=11;g.add(sp);g.add(sp.target);
 PROPS[id](g,st,r,md);const f=new THREE.Group();f.position.z=st.fz;g.add(f);FEAT[id](f,g,md);if(g.userData.fl)g.userData.flBase=g.userData.fl.intensity;
 g.traverse(o=>{if(o.isMesh&&o.material.isMeshStandardMaterial&&!o.material.transparent){o.receiveShadow=true;o.castShadow=o.geometry.type!=='PlaneGeometry'&&o.geometry.type!=='CircleGeometry'&&!(o.material.emissiveIntensity>1.15&&!o.material.emissiveMap)&&o.material.side!==THREE.BackSide}});return g}
function tileTex(base,joint,sz,speck){const c=cv(256,256),x=c.getContext('2d'),r=rng(3+sz);x.fillStyle=base;x.fillRect(0,0,256,256);noisy(x,256,256,r,14);for(let i=0;i<(speck||0);i++){x.fillStyle=r()<.5?'rgba(255,255,255,.22)':'rgba(30,34,40,.25)';x.fillRect(r()*256,r()*256,1.5,1.5)}x.strokeStyle=joint;x.lineWidth=sz;x.strokeRect(0,0,256,256);const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function cabTex(){const c=cv(512,256),x=c.getContext('2d');x.fillStyle='#e6e4dc';x.fillRect(0,0,512,256);for(let i=0;i<4;i++){x.strokeStyle='#a9a79e';x.lineWidth=3;x.strokeRect(i*128+4,6,120,244);x.fillStyle='#7d8188';x.fillRect(i*128+(i%2?14:100),110,12,40);x.strokeStyle='#c9c7be';x.lineWidth=2;x.beginPath();x.moveTo(i*128+4,70);x.lineTo(i*128+124,70);x.stroke()}const t=ctex(c);t.wrapS=THREE.RepeatWrapping;return t}
/* cast concrete: formwork panels, tie holes, stains */
function concTex(seed,dark){const c=cv(512,512),x=c.getContext('2d'),r=rng(seed);x.fillStyle=dark?'#6f6e6a':'#a5a39c';x.fillRect(0,0,512,512);for(let i=0;i<120;i++){const a=r()*512,b=r()*512,br=30+r()*120,g=x.createRadialGradient(a,b,0,a,b,br);g.addColorStop(0,r()<.5?'rgba(0,0,0,.1)':'rgba(255,255,255,.08)');g.addColorStop(1,'rgba(128,128,128,0)');x.fillStyle=g;x.fillRect(a-br,b-br,br*2,br*2)}noisy(x,512,512,r,22);
 x.strokeStyle='rgba(40,40,38,.45)';x.lineWidth=2;for(let i=0;i<=2;i++){x.beginPath();x.moveTo(i*256,0);x.lineTo(i*256,512);x.moveTo(0,i*256);x.lineTo(512,i*256);x.stroke()}x.fillStyle='rgba(30,30,28,.6)';for(let i=0;i<2;i++)for(let j=0;j<2;j++)[[50,60],[206,60],[50,196],[206,196]].forEach(q=>{x.beginPath();x.arc(i*256+q[0],j*256+q[1],5,0,7);x.fill()});
 for(let i=0;i<14;i++){const a=r()*512,g=x.createLinearGradient(0,0,0,150+r()*300);g.addColorStop(0,'rgba(30,28,24,.2)');g.addColorStop(1,'rgba(30,28,24,0)');x.fillStyle=g;x.fillRect(a,0,6+r()*22,512)}const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function ribTex(base){const c=cv(256,256),x=c.getContext('2d'),r=rng(19);x.fillStyle=base;x.fillRect(0,0,256,256);for(let i=0;i<256;i+=16){const g=x.createLinearGradient(i,0,i+16,0);g.addColorStop(0,'rgba(0,0,0,.24)');g.addColorStop(.35,'rgba(255,255,255,.14)');g.addColorStop(1,'rgba(0,0,0,.08)');x.fillStyle=g;x.fillRect(i,0,16,256)}noisy(x,256,256,r,10);const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function raisedTex(){const c=cv(256,256),x=c.getContext('2d'),r=rng(27);x.fillStyle='#8f959c';x.fillRect(0,0,256,256);noisy(x,256,256,r,12);x.fillStyle='rgba(20,24,30,.55)';for(let i=0;i<12;i++)for(let j=0;j<12;j++){x.beginPath();x.arc(22+i*19.3,22+j*19.3,2.6,0,7);x.fill()}x.strokeStyle='#3d434b';x.lineWidth=5;x.strokeRect(0,0,256,256);const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function hazTex(){const c=cv(256,32),x=c.getContext('2d');x.fillStyle='#e9c21a';x.fillRect(0,0,256,32);x.fillStyle='#16171a';for(let k=-1;k<9;k++){x.beginPath();x.moveTo(k*32,32);x.lineTo(k*32+16,0);x.lineTo(k*32+32,0);x.lineTo(k*32+16,32);x.fill()}const t=ctex(c);t.wrapS=THREE.RepeatWrapping;return t}
/* Earth: each prediction has its own kind of room on the campus, built around the same experiment.
   Materials lab: a bright wet lab with sample stores and an exhaust hood. Sensor hall: a tall industrial hall with a test ceiling hung under the roof.
   Fire test cell: a concrete bunker with a gas bank and an observation window. Drop tower: the foot of the shaft, with the drop tube and a capsule. Data centre: a dim aisle of racks with a video wall. */
function buildLab(md){const g=new THREE.Group(),st=STYLE[md.id],id=md.id,ac=md.rc||md.c,H=RH,L=st.L+1.2,XR=RW/2,r=rng(md.seed+3),FZ=st.fz,
  K={prev:{XL:-2.7,HC:1.1,li:1,lc:0xfff6ea},det:{XL:-3.6,HC:2.7,li:.95,lc:0xf2f6ff},sup:{XL:-2.3,HC:1.55,li:.7,lc:0xffe2c0},fun:{XL:-3,HC:2.1,li:1,lc:0xffffff},si:{XL:-2.7,HC:1.35,li:.5,lc:0x9cc2ff}}[id],XL=K.XL,HC=K.HC,WD=XR-XL,xc=(XL+XR)/2,HH=HC+H/2,yc=(HC-H/2)/2,
  gy=M(0x9a9da2,STEEL),dk=M(0x2b2e34,{metalness:.4,roughness:.5}),wht=M(0xeeede8,{roughness:.6}),top=M(0x30343a,{roughness:.3,metalness:.1}),acm=M(new THREE.Color(ac).getHex(),{roughness:.5}),red=M(0xb3261e,{roughness:.45,metalness:.3}),
  lm=new THREE.MeshStandardMaterial({color:0xffffff,emissive:K.lc,emissiveIntensity:1.25}),B=(w,h,d,m,x,y,z)=>{const o=bx(w,h,d,m);g.add(at(o,x,y,z));return o},
  pl=(w,h,m,rx,ry,x,y,z)=>{const o=new THREE.Mesh(new THREE.PlaneGeometry(w,h),m);o.rotation.set(rx,ry,0);o.position.set(x,y,z);g.add(o);return o},
  TM=(t,ru,rv,o)=>{t.repeat.set(ru,rv);return new THREE.MeshStandardMaterial(Object.assign({map:t,roughness:.85,metalness:0},o||{}))},
  shell=(wm,fm,cm,wm2)=>{pl(WD,L,fm,-Math.PI/2,0,xc,-H/2,0);pl(WD,L,cm,Math.PI/2,0,xc,HC,0);pl(L,HH,wm2||wm,0,-Math.PI/2,XR,yc,0);pl(L,HH,wm,0,Math.PI/2,XL,yc,0);pl(WD,HH,wm,0,0,xc,yc,-L/2);pl(WD,HH,wm,0,Math.PI,xc,yc,L/2)},
  screen=(w,h,seed,x,y,z,ry)=>{const o=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:screenTex(seed,ac)}));o.rotation.y=ry;g.add(at(o,x,y,z));return o},
  bench=(z0,z1,x)=>{const bl=z1-z0,zc=(z0+z1)/2,ct=cabTex();ct.repeat.x=bl/1.2;B(.62,.84,bl,new THREE.MeshStandardMaterial({map:ct,roughness:.6}),x,-H/2+.42,zc);B(.68,.04,bl+.04,top,x+.03,-H/2+.87,zc);return -H/2+.89},
  lights=(pts,spot)=>{g.add(new THREE.HemisphereLight(K.lc,0x6a6d70,.1*K.li));pts.forEach(q=>{const p=new THREE.PointLight(K.lc,q[3]*K.li,q[4]||6,2);p.position.set(q[0],q[1],q[2]);g.add(p)});const sp=new THREE.SpotLight(K.lc,.5*K.li,11,1.2,.85,1.1);sp.position.set(.3,Math.min(HC,1.3)-.14,st.cz-1);sp.target.position.set(-.05,-H/2,FZ-.6);sp.castShadow=true;sp.shadow.mapSize.set(2048,2048);sp.shadow.bias=-.0009;sp.shadow.camera.near=.2;sp.shadow.camera.far=11;g.add(sp);g.add(sp.target)};
 if(id==='prev'){ /* materials lab */
  shell(M(0xd9d4c8,{roughness:.92,metalness:0}),TM(tileTex('#b9b4a8','rgba(70,66,58,.5)',2,400),WD/.6,L/.6,{roughness:.34}),TM(tileTex('#ecebe6','#b9b9b3',5,200),WD/.6,L/.6,{roughness:.95}));
  for(let i=0;i<4;i++)[-.25,-1.75].forEach(x=>B(.58,.02,.58,lm,x,HC-.012,-L/2+1+i*(L-2)/3));
  /* frosted clerestory along the end wall, sample store below it */
  const wz=-L/2+.02;B(WD-.5,.42,.03,new THREE.MeshStandardMaterial({color:0xffffff,emissive:0xe8f2ff,emissiveIntensity:1.05}),xc,.74,wz);for(let i=0;i<=6;i++)B(.04,.46,.05,wht,XL+.25+i*(WD-.5)/6,.74,wz+.01);B(WD-.44,.04,.06,wht,xc,.52,wz+.01);B(WD-.44,.04,.06,wht,xc,.97,wz+.01);
  const dt=cabTex();dt.repeat.set(3,1);B(2.3,1.5,.5,new THREE.MeshStandardMaterial({map:dt,roughness:.6}),XL+1.25,-H/2+.75,-L/2+.27);for(let i=0;i<7;i++){const cc=['#3d5276','#8c8f94','#c8641e','#58705a','#b5523a','#d8cfb4','#2f4f7f'][i],rl=cy(.07,.5,new THREE.MeshStandardMaterial({map:fabricTex(cc),roughness:1}),'x');g.add(at(rl,XL+.4+i*.3,-H/2+1.58,-L/2+.3))}
  /* extraction hood over the rig, ducted to the ceiling */
  const hood=new THREE.Mesh(new THREE.CylinderGeometry(.16,.62,.3,4,1,true),M(0xb9bdc1,{metalness:.7,roughness:.35,side:THREE.DoubleSide}));hood.rotation.y=Math.PI/4;g.add(at(hood,.3,.6,FZ));g.add(at(cy(.13,HC-.75,M(0xb9bdc1,{metalness:.7,roughness:.35}),'y'),.3,(HC+.75)/2,FZ));
  /* wet bench: conditioning oven, balance, glassware, shelf of reagent bottles; stools */
  const by=bench(-L/2+1.1,L/2-.25,XL+.32);B(.5,.5,.6,M(0xdfe1e0,{roughness:.5}),XL+.32,by+.25,-L/2+1.7);B(.02,.3,.36,M(0x11161c,{roughness:.2}),XL+.575,by+.27,-L/2+1.7);B(.3,.08,.3,M(0x3a3f47),XL+.3,by+.04,-.3);B(.34,.34,.02,new THREE.MeshStandardMaterial({color:0xcfe4f2,transparent:true,opacity:.25,roughness:.05,depthWrite:false}),XL+.3,by+.25,-.3);
  for(let i=0;i<9;i++){const hh=.1+r()*.16;g.add(at(cy(.03+r()*.025,hh,new THREE.MeshStandardMaterial({color:[0xbfe0f2,0xf2e2a0,0xd9f0d0,0xf0c8a0][i%4],transparent:true,opacity:.5,roughness:.05,depthWrite:false}),'y'),XL+.18+r()*.3,by+hh/2,.3+i*.17))}
  B(.28,.03,L-2,wht,XL+.15,.42,.4);for(let i=0;i<Math.floor((L-2.2)/.15);i++){const hh=.1+r()*.12,c=[0x8a5a2b,0xf1f1ec,0x2f62b0,0xd9d9d4,0x3c7a4a,0xb3261e][Math.floor(r()*6)];g.add(at(r()<.6?cy(.04,hh,M(c,{roughness:.4}),'y'):bx(.1,hh,.09,M(c)),XL+.15,.435+hh/2,-L/2+1.6+i*.15))}
  [.2,1.5].forEach(z=>{g.add(at(cy(.16,.04,dk,'y'),XL+.95,-H/2+.56,z));g.add(at(cy(.025,.54,gy,'y'),XL+.95,-H/2+.28,z));g.add(at(cy(.2,.02,gy,'y'),XL+.95,-H/2+.02,z))});
  [-.75,-.1].forEach(k=>g.add(at(cy(.02,1.4,gy,'y'),-(RW/2-.03),-.4,FZ+k)));B(.012,.06,L,acm,XR-.008,.95,0);B(.05,.1,L-.6,wht,XR-.03,-.62,0);
  B(.34,.5,1.5,wht,XR-.17,.72,FZ-1.8);for(let i=0;i<3;i++){const p=new THREE.Mesh(new THREE.PlaneGeometry(.21,.28),new THREE.MeshStandardMaterial({map:noteTex(md.seed+i*5,ac),roughness:.9}));p.rotation.y=-Math.PI/2;g.add(at(p,XR-.006,.5,L/2-1-i*.33))}
  lights([[-.6,HC-.35,-L/2+.8,.14],[-.6,HC-.35,-L/2+2.9,.14],[-.6,HC-.35,L/2-2.6,.14],[-.6,HC-.35,L/2-.8,.14],[xc,.6,-L/2+.6,.4,6]])}
 else if(id==='det'){ /* sensor hall */
  const cw=TM(concTex(5),WD/3,HH/3),rw=TM(ribTex('#aab0b6'),L/1.2,1,{metalness:.5,roughness:.5});shell(TM(ribTex('#aab0b6'),WD/1.2,1,{metalness:.5,roughness:.5}),TM(concTex(8),WD/2.5,L/2.5,{roughness:.3,color:0xd0d0cc}),M(0x23272c,{roughness:.9}),rw);
  pl(L,1.1,TM(concTex(5),L/3,.4),0,-Math.PI/2,XR-.004,-H/2+.55,0);pl(L,1.1,TM(concTex(5),L/3,.4),0,Math.PI/2,XL+.004,-H/2+.55,0);pl(WD,1.1,cw,0,0,xc,-H/2+.55,-L/2+.004);
  /* roof trusses and high-bay lamps; a test ceiling hangs under them over the rig */
  for(let i=0;i<4;i++){const z=-L/2+.9+i*(L-1.8)/3;B(WD,.14,.1,gy,xc,HC-.2,z);B(WD,.06,.08,gy,xc,HC-.62,z);for(let k=0;k<7;k++){const d=bx(.05,.5,.05,gy);d.rotation.z=(k%2?1:-1)*.6;g.add(at(d,XL+.3+k*(WD-.6)/6,HC-.41,z))}g.add(at(cy(.2,.1,M(0x30333a),'y'),-1.9,HC-.75,z+.5));g.add(at(cy(.17,.02,lm,'y'),-1.9,HC-.81,z+.5))}
  B(2.1,.04,L-1.4,TM(tileTex('#ecebe6','#b9b9b3',5,200),3.5,(L-1.4)/.6,{roughness:.95}),.05,H/2+.02,-.2);[-.9,1].forEach(x=>[-L/2+.8,-.2,L/2-1.2].forEach(z=>g.add(at(cy(.012,HC-H/2,gy,'y'),x,(HC+H/2)/2,z))));B(2.16,.06,.06,gy,.05,H/2+.02,-L/2+.5);B(2.16,.06,.06,gy,.05,H/2+.02,L/2-.9);
  /* floor marking, roller door, smoke duct with fan, shelving with detector boxes, tripod */
  const hz=hazTex();hz.repeat.x=8;[-1.2,-1.32].forEach((x,i)=>B(.1,.004,L-.6,i?M(0xe9c21a,{roughness:.7}):M(0xe9c21a,{roughness:.7}),x,-H/2+.003,0));
  B(2.6,2.5,.06,TM(ribTex('#8f959b'),1,9,{metalness:.5,roughness:.5}),XL+1.6,-H/2+1.25,-L/2+.05);B(2.8,.14,.12,gy,XL+1.6,-H/2+2.57,-L/2+.07);B(.4,.16,.04,new THREE.MeshBasicMaterial({color:0x37d67a}),XL+3.4,-H/2+2.3,-L/2+.03);
  g.add(at(cy(.3,L-.8,M(0xb9bdc1,{metalness:.7,roughness:.35}),'z'),XL+.5,1.5,0));for(let i=0;i<5;i++)g.add(at(cy(.315,.05,gy,'z'),XL+.5,1.5,-L/2+.8+i*(L-1.6)/4));B(.8,.8,.7,M(0x55606b,{metalness:.5}),XL+.5,1.5,L/2-.75);
  for(let k=0;k<2;k++){const z=-L/2+1.6+k*2.6;[-.5,.5].forEach(a=>[-.22,.22].forEach(b=>B(.04,2,.04,M(0x2f62b0,{metalness:.5}),XL+.35+b,-H/2+1,z+a)));for(let j=0;j<4;j++){B(.5,.03,1.04,M(0xd8a23a,{roughness:.6}),XL+.35,-H/2+.3+j*.5,z);for(let i=0;i<3;i++)if(r()<.8)B(.34,.24+r()*.1,.26,M([0xc9b79a,0xe6e6e2,0x8c8f94][Math.floor(r()*3)],{roughness:.9}),XL+.35,-H/2+.45+j*.5,z-.34+i*.34)}}
  g.add(at(cy(.02,1.2,gy,'y'),-(RW/2-.1),-.5,FZ));[-1,1].forEach(k=>{const l=cy(.012,.7,gy,'y');l.rotation.z=k*.4;g.add(at(l,-(RW/2-.1)+k*.14,-.85,FZ))});
  B(.9,.75,.6,M(0x3a3f47,{metalness:.3}),-2.2,-H/2+.375,L/2-1.2);screen(.5,.3,md.seed+3,-2.2,-H/2+1.0,L/2-1.25,Math.PI);B(.54,.34,.03,dk,-2.2,-H/2+1.0,L/2-1.23);
  lights([[-1.9,HC-.9,-L/2+1.4,.3,8],[-1.9,HC-.9,0,.3,8],[-1.9,HC-.9,L/2-1.2,.3,8],[.1,.8,-1,.1],[.1,.8,1.4,.1]])}
 else if(id==='sup'){ /* fire test cell */
  const cw=TM(concTex(11),WD/2.4,HH/2.4),cw2=TM(concTex(13),L/2.4,HH/2.4);shell(cw,TM(concTex(17,1),WD/2,L/2,{roughness:.6}),TM(concTex(19,1),WD/2.4,L/2.4),cw2);
  /* scorch above the rig, hazard frame on the floor, drain */
  const sc=cv(256,256),sx=sc.getContext('2d'),sg=sx.createRadialGradient(128,150,10,128,128,128);sg.addColorStop(0,'rgba(10,8,6,.75)');sg.addColorStop(1,'rgba(10,8,6,0)');sx.fillStyle=sg;sx.fillRect(0,0,256,256);pl(1.8,1.8,new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(sc),transparent:true,depthWrite:false}),Math.PI/2,0,-.2,HC-.004,FZ);
  const hz=hazTex();hz.repeat.x=6;const hm=new THREE.MeshStandardMaterial({map:hz,roughness:.8});[[-.25,FZ-.75,1.6,.1],[-.25,FZ+.75,1.6,.1]].forEach(q=>B(q[2],.004,q[3],hm,q[0],-H/2+.003,q[1]));[-1.05,.55].forEach(x=>{const o=B(1.6,.004,.1,hm,x,-H/2+.003,FZ);o.rotation.y=Math.PI/2});B(.4,.006,.4,M(0x2a2d33,{metalness:.7,roughness:.5}),-.25,-H/2+.004,FZ+1.3);
  /* red suppression pipework with nozzles, caged lamps, beacon */
  [-.6,.5].forEach(x=>{g.add(at(cy(.035,L-.3,red,'z'),x,HC-.12,0));for(let i=0;i<3;i++){const z=-L/2+.8+i*(L-1.6)/2;g.add(at(cy(.015,.14,gy,'y'),x,HC-.22,z));g.add(at(cy(.04,.02,gy,'y'),x,HC-.3,z))}});g.add(at(cy(.035,1.2,red,'x'),-.05,HC-.12,-L/2+.3));
  [[-1.5,-.6],[-1.5,1.2],[.6,1.6]].forEach(q=>{B(.26,.08,.14,M(0x3a3d44,{metalness:.5}),q[0],HC-.05,q[1]);B(.22,.05,.1,new THREE.MeshStandardMaterial({color:0xffffff,emissive:0xffd9a0,emissiveIntensity:1.3}),q[0],HC-.11,q[1])});B(.12,.12,.12,new THREE.MeshStandardMaterial({color:0xff3b30,emissive:0xff2a1a,emissiveIntensity:1.6}),XR-.08,HC-.3,FZ+.9);
  /* gas bank on the outer wall */
  for(let i=0;i<6;i++){const z=-L/2+1.1+i*.3;g.add(at(cy(.115,1.35,red,'y'),XL+.2,-H/2+.68,z));g.add(at(new THREE.Mesh(new THREE.SphereGeometry(.115,18,10,0,6.3,0,1.57),red),XL+.2,-H/2+1.355,z));g.add(at(cy(.03,.12,gy,'y'),XL+.2,-H/2+1.5,z))}g.add(at(cy(.025,1.8,gy,'z'),XL+.2,-H/2+1.6,-L/2+1.85));B(.06,.5,1.9,gy,XL+.05,-H/2+.9,-L/2+1.85);B(.3,.05,1.95,M(0xe9c21a,{roughness:.7}),XL+.2,-H/2+.025,-L/2+1.85);
  /* end wall: observation window onto the control room, blast door */
  const wz=-L/2+.02;B(1.7,.7,.08,M(0x55595f,{metalness:.7,roughness:.4}),.2,.25,wz+.02);B(1.5,.52,.02,M(0x0b1118,{roughness:.08,metalness:.6}),.2,.25,wz+.07);[-.25,.2,.65].forEach((x,i)=>{const o=screen(.34,.2,md.seed+20+i,x,.25,wz+.085,0);o.material.color.setScalar(.45)});
  B(.95,1.95,.1,M(0x4d5a52,{metalness:.6,roughness:.5}),XL+.75,-H/2+.98,wz+.04);B(1.1,2.08,.06,M(0x2f3336,{metalness:.6}),XL+.75,-H/2+1.02,wz+.02);const wh=new THREE.Mesh(new THREE.TorusGeometry(.16,.02,8,28),gy);g.add(at(wh,XL+.75,-H/2+1.05,wz+.11));const sgn=new THREE.Mesh(new THREE.PlaneGeometry(.36,.21),new THREE.MeshBasicMaterial({map:signTex()}));g.add(at(sgn,XL+.75,-H/2+1.6,wz+.095));
  lights([[-1.5,HC-.3,-.6,.22,5],[-1.5,HC-.3,1.2,.22,5],[.6,HC-.3,1.6,.2,5],[.2,.3,-L/2+.4,.12,3]])}
 else if(id==='fun'){ /* foot of the drop tower */
  shell(M(0xe3e5e6,{roughness:.9,metalness:0}),M(0x2c5d8c,{roughness:.22,metalness:.05}),M(0xdfe1e2,{roughness:.95}));pl(L,.9,M(0x2c5d8c,{roughness:.6}),0,Math.PI/2,XL+.004,-H/2+.45,0);pl(WD,.9,M(0x2c5d8c,{roughness:.6}),0,0,xc,-H/2+.45,-L/2+.004);
  for(let i=0;i<3;i++)B(.5,.02,1.1,lm,-.3,HC-.012,-L/2+1.2+i*(L-2.4)/2);
  /* drop tube: flanged steel sections rising through the ceiling, access hatch and view ports */
  const tx=XL+1.15,tz=-L/2+1.35,tm=M(0xbfc4c9,{metalness:.85,roughness:.28});g.add(at(cy(.82,HH,tm,'y'),tx,yc,tz));for(let i=0;i<=5;i++)g.add(at(cy(.9,.07,M(0x7d8188,STEEL),'y'),tx,-H/2+.05+i*HH/5,tz));g.add(at(cy(1.0,.05,dk,'y'),tx,HC-.02,tz));
  const hat=bx(.55,1.2,.1,M(0x9aa0a6,{metalness:.8,roughness:.3}));hat.rotation.y=.9;g.add(at(hat,tx+.66,-H/2+.9,tz+.52));[1.75,2.35].forEach(y=>{const pw=cy(.13,.08,dk,'z');pw.rotation.y=.9;pw.rotation.x=Math.PI/2;g.add(at(pw,tx+.66,-H/2+y,tz+.52))});
  for(let i=0;i<16;i++){const a=i/16*6.2832;g.add(at(cy(.025,.06,dk,'y'),tx+Math.cos(a)*.86,-H/2+.1,tz+Math.sin(a)*.86))}
  /* drop capsule on its cradle, hoist beam with chain */
  const cz2=-1.35,cx3=-.72,am=M(0xd5d8db,{metalness:.8,roughness:.3});g.add(at(cy(.3,.95,am,'y'),cx3,-H/2+.85,cz2));const nose=new THREE.Mesh(new THREE.ConeGeometry(.3,.42,28),am);nose.rotation.x=Math.PI;g.add(at(nose,cx3,-H/2+.17,cz2));g.add(at(cy(.305,.1,M(0xe0872a,{roughness:.5}),'y'),cx3,-H/2+1.05,cz2));g.add(at(cy(.31,.04,dk,'y'),cx3,-H/2+1.34,cz2));g.add(at(cy(.03,.2,gy,'y'),cx3,-H/2+1.45,cz2));
  [0,1,2].forEach(i=>{const a=i*2.094,l=cy(.02,.5,gy,'y');l.rotation.set(Math.cos(a)*.5,0,Math.sin(a)*.5);g.add(at(l,cx3+Math.sin(a)*.3,-H/2+.22,cz2+Math.cos(a)*.3))});g.add(at(new THREE.Mesh(new THREE.TorusGeometry(.36,.02,8,32),gy),cx3,-H/2+.42,cz2).rotateX(Math.PI/2));
  B(.14,.2,L-.4,M(0xe9c21a,{metalness:.4,roughness:.5}),cx3,HC-.12,0);B(.24,.16,.3,dk,cx3,HC-.3,cz2);g.add(at(cy(.008,HC-.3-(-H/2+1.55),gy,'y'),cx3,(HC-.3-H/2+1.55)/2,cz2));
  /* control desk and bench under the chamber, gas bottles strapped to the wall */
  B(1.3,.05,.6,top,XL+.5,-H/2+.76,L/2-1.2);[-.55,.55].forEach(k=>B(.05,.76,.55,gy,XL+.5+k,-H/2+.38,L/2-1.2));[-.3,.3].forEach((k,i)=>{screen(.5,.3,md.seed+9+i,XL+.5+k,-H/2+1.08,L/2-1.38,0);B(.54,.34,.03,dk,XL+.5+k,-H/2+1.08,L/2-1.4)});
  B(1.2,.05,.9,top,XR-.7,-.47,FZ);[-.5,.5].forEach(k=>[-.38,.38].forEach(q=>B(.05,.62,.05,gy,XR-.7+k,-.79,FZ+q)));B(.012,.06,L,acm,XR-.008,.95,0);B(.34,.55,1.3,wht,XR-.17,.6,L/2-2.3);pl(L,.9,M(0x2c5d8c,{roughness:.6}),0,-Math.PI/2,XR-.004,-H/2+.45,0);for(let i=0;i<3;i++){const q=new THREE.Mesh(new THREE.PlaneGeometry(.3,.4),new THREE.MeshStandardMaterial({map:noteTex(md.seed+i*5,ac),roughness:.9}));q.rotation.y=-Math.PI/2;g.add(at(q,XR-.006,.45,L/2-3.4-i*.45))}
  lights([[-.3,HC-.4,-L/2+1.2,.2],[-.3,HC-.4,0,.2],[-.3,HC-.4,L/2-1.2,.2],[XL+1.6,.4,.6,.14,5]])}
 else{ /* data centre */
  shell(M(0x2b3038,{roughness:.8,metalness:.1}),TM(raisedTex(),WD/.6,L/.6,{roughness:.4,metalness:.2}),M(0x14171b,{roughness:.9}));
  [-1.5,.2].forEach(x=>B(.05,.02,L-.4,new THREE.MeshStandardMaterial({color:0xffffff,emissive:0x8fbcff,emissiveIntensity:1.5}),x,HC-.012,0));
  /* racks down both sides, yellow fibre tray and cable ladder overhead */
  const rack=(x,z,side,sd)=>{const t=ledTex(sd),m=new THREE.MeshStandardMaterial({map:t,emissiveMap:t,emissive:0xffffff,emissiveIntensity:1.2,roughness:.4,metalness:.5});B(.6,2.05,.62,M(0x14171c,{metalness:.5,roughness:.5}),x,-H/2+1.03,z);const f=new THREE.Mesh(new THREE.PlaneGeometry(.56,1.98),m);f.rotation.y=side*Math.PI/2;g.add(at(f,x+side*.305,-H/2+1.03,z))};
  for(let i=0;i<Math.floor((L-.6)/.66);i++)rack(XL+.32,-L/2+.65+i*.66,1,md.seed+60+i);for(let i=0;i<2;i++)rack(XR-.32,-L/2+.65+i*.66,-1,md.seed+90+i);rack(XR-.32,L/2-.6,-1,md.seed+99);
  B(.34,.06,L-.3,M(0xe9c21a,{roughness:.6}),XL+.5,HC-.14,0);B(.4,.04,L-.3,M(0x6f747b,{metalness:.6}),-.9,HC-.2,0);for(let i=0;i<9;i++)B(.4,.05,.03,gy,-.9,HC-.2,-L/2+.4+i*(L-.8)/8);
  /* video wall at the end of the aisle, floor light strips, a cooling unit */
  const wz=-L/2+.03;for(let i=0;i<3;i++)for(let j=0;j<2;j++){screen(.78,.44,md.seed+30+i*2+j,-1.55+i*.8,-.05+j*.46,wz+.03,0)}B(2.5,1.0,.05,M(0x0b0d10),-.75,.18,wz);
  [XL+.7,XR-.7].forEach(x=>B(.03,.012,L-.6,new THREE.MeshBasicMaterial({color:0x2f7dff}),x,-H/2+.008,0));B(.7,1.9,.5,M(0xc9cdd0,{metalness:.5,roughness:.5}),XR-.37,-H/2+.95,L/2-1.5);B(.5,.5,.02,dk,XR-.73,-H/2+1.4,L/2-1.5);
  lights([[-.7,HC-.3,-L/2+1,.2,5],[-.7,HC-.3,.3,.2,5],[-.7,HC-.3,L/2-1,.2,5],[-.75,.2,-L/2+.5,.35,5]])}
 const f=new THREE.Group();f.position.z=FZ;g.add(f);FEAT[id](f,g,md);if(g.userData.fl)g.userData.flBase=g.userData.fl.intensity;
 g.traverse(o=>{if(o.isMesh&&o.material.isMeshStandardMaterial&&!o.material.transparent){o.receiveShadow=true;o.castShadow=o.geometry.type!=='PlaneGeometry'&&o.geometry.type!=='CircleGeometry'&&!(o.material.emissiveIntensity>1.15&&!o.material.emissiveMap)}});return g}
function showRoom(id){
 if(EXPORT){if(room)inScene.remove(room);room=(S.scen==='earth'?buildLab:buildRoom)(modOf(id));inScene.add(room);return}
 void prediction.open(id,S.scen);
}
function roomPose(now,settled){const k=settled?1:cl((now-tin)/1600),e=1-Math.pow(1-k,3),md=modOf(S.mod),st=STYLE[S.mod],s=settled?0:1;
 inCam.position.set(Math.sin(now/2600)*.02*s,-.08+Math.sin(now/3100)*.015*s,st.cz+1.05*(1-e));inCam.rotation.set(pitch+Math.sin(now/4200)*.006*s,yaw+(md?md.yaw:0)*e,0)}
/* glows as live sprites */
const fxPool=[];let glowMap;
function fxLive(list,fz){if(!glowMap){const c=cv(128,128),x=c.getContext('2d'),g=x.createRadialGradient(64,64,0,64,64,64);g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.35,'rgba(255,255,255,.55)');g.addColorStop(1,'rgba(255,255,255,0)');x.fillStyle=g;x.fillRect(0,0,128,128);glowMap=new THREE.CanvasTexture(c)}
 while(fxPool.length<list.length){const s=new THREE.Sprite(new THREE.SpriteMaterial({map:glowMap,depthWrite:false,transparent:true}));inScene.add(s);fxPool.push(s)}
 fxPool.forEach((s,i)=>{const o=list[i];s.visible=!!o;if(!o)return;s.position.set(o.p[0],o.p[1],o.p[2]+fz);s.scale.set(o.s,o.s,1);s.material.color.setRGB(o.c[0],o.c[1],o.c[2]);s.material.opacity=o.a;s.material.blending=o.add?THREE.AdditiveBlending:THREE.NormalBlending})}
/* the same glows as 2D gradients over the still image */
function fx2d(list,fz,w,h){const c=seq.getContext('2d'),q=fit(w,h),sc=720*q.k/2/Math.tan(32*RAD);inCam.aspect=16/9;inCam.fov=64;inCam.clearViewOffset();inCam.updateProjectionMatrix();roomPose(0,true);inCam.updateMatrixWorld();inCam.matrixWorldInverse.copy(inCam.matrixWorld).invert();
 list.forEach(o=>{v3.set(o.p[0],o.p[1],o.p[2]+fz);const dz=-v3.clone().applyMatrix4(inCam.matrixWorldInverse).z;if(dz<.1)return;v3.project(inCam);const x=q.x+(v3.x*.5+.5)*1280*q.k,y=q.y+(-v3.y*.5+.5)*720*q.k,rad=Math.max(1,o.s/2*sc/dz),col=o.c.map(v=>Math.round(Math.min(1,v)*255)).join(','),a=Math.max(0,Math.min(1,o.a)),g=c.createRadialGradient(x,y,0,x,y,rad);
  g.addColorStop(0,'rgba('+col+','+a+')');g.addColorStop(.35,'rgba('+col+','+a*.55+')');g.addColorStop(1,'rgba('+col+',0)');c.globalCompositeOperation=o.add?'lighter':'source-over';c.fillStyle=g;c.fillRect(x-rad,y-rad,rad*2,rad*2)});c.globalCompositeOperation='source-over'}
/* moving parts that follow the conditions: fans, the igniter's heat, the flame's light */
function tick(){const u=room&&room.userData,P=S.par[S.mod]||{};if(!u)return;(u.spin||[]).forEach(s=>{s.o.rotation[s.ax]+=.02+(P.flow||0)*.012});if(u.ign)u.ign.material.emissiveIntensity=(P.heat||0)/100*3.2;if(u.fl)u.fl.intensity=u.flBase*fxLight}
function drawRoom(now,settled){roomPose(now,settled);R.setRenderTarget(winRT);R.render(scene,winCam);R.setRenderTarget(null);R.toneMappingExposure=.92;R.render(inScene,inCam);R.toneMappingExposure=1.05}

/* ---------- environments: the station in orbit, a base on the lunar surface, and Earth ---------- */
const NM=72,NE=63,NX=54,EDUR={moon:4200,earth:5200,x:4600},ESH={moon:['m',NM],earth:['e',NE],x:['x',NX]},MBL=new V(2,3.5,0),MBV=new V(-42,23,74),MBD=MBV.clone().sub(MBL),MBR=MBD.length(),EAP=MBV.clone().add(new V(.5,.3,-.85).normalize().multiplyScalar(9000)),ANCHM={prev:[0,8.6,0],det:[25,9.4,-11],sup:[13.5,5,18.5],fun:[35,8.4,14],si:[-24,5.6,-12]},EBL=new V(20,50,2),EBV=new V(-212,100,262),EBD=EBV.clone().sub(EBL),EBR=EBD.length(),EH=6.2e6,ANCHE={prev:[-52,24,-12],det:[-34,17,58],sup:[72,15,52],fun:[42,96,-32],si:[98,15,-46]};
let mbScene,view='iss',tr=null,starGeo,landTex,hadTex,demImg,gwM,rtA,ovScene,ovCam,ovMat,mbYaw=0,mbPit=0,ebScene,ebFog,ebDome,ebStars,ebYaw=0,ebPit=0;const ebTurb=[];const etex={},ebCam=new THREE.PerspectiveCamera(38,16/9,2,3e7);const mbCam=new THREE.PerspectiveCamera(38,16/9,1,600000),Gv=new V(),PDv=new V(),PEv=new V(),ED2=new V(),tv=new V(),tv2=new V();
const CR=[];(()=>{const r=rng(404);while(CR.length<110){const x=(r()-.5)*2300,z=(r()-.5)*2300,rad=6+r()*r()*r()*150;if(Math.hypot(x,z)<115+rad||Math.hypot(x-95,z+40)<40+rad||CR.some(c=>Math.hypot(x-c[0],z-c[1])<(rad+c[2])*1.25))continue;CR.push([x,z,rad,rad*(.14+r()*.1)])}while(CR.length<190){const a=r()*6.2832,d=52+r()*r()*420,rad=4.5+r()*r()*15,x=Math.cos(a)*d,z=Math.sin(a)*d;if(d<46+rad||CR.some(c=>Math.hypot(x-c[0],z-c[1])<(rad+c[2])*1.3))continue;CR.push([x,z,rad,rad*(.16+r()*.1)])}})();
function mbH(x,z){let h=5*Math.sin(x*.004+1)*Math.cos(z*.0035)+2.6*Math.sin(x*.013+z*.011)*Math.cos(x*.0071-z*.0163)+1.3*Math.sin(x*.031-z*.027)*Math.cos(x*.019+z*.023)+.5*Math.sin(x*.09+z*.07)*Math.cos(x*.053-z*.081)
  +46*Math.exp(-(Math.pow(x+330,2)+Math.pow(z+300,2))/36000)+24*Math.exp(-(Math.pow(x-380,2)*.35+Math.pow(z+120,2))/9000)+15*Math.exp(-(Math.pow(x+40,2)+Math.pow(z-420,2)*.5)/16000)-9*Math.exp(-(Math.pow(x-150,2)+Math.pow(z-170,2))/5200);
 for(const c of CR){const q=Math.hypot(x-c[0],z-c[1])/c[2];if(q<1.8){if(q<1)h-=c[3]*(1-q*q);h+=c[3]*.3*Math.exp(-Math.pow((q-1)/.22,2))}}
 const d=Math.hypot(x,z);return h*sm(cl((d-44)/70))*(1-sm(cl((d-900)/280)))}
/* ground textures: fine regolith with micro-craters and pebbles; a field of larger craters for the middle distance; printed layers for the domes */
function groundTex(big){const n=big?2048:1024,c=cv(n,n),x=c.getContext('2d'),r=rng(big?61:17);x.fillStyle='#646464';x.fillRect(0,0,n,n);noisy(x,n,n,r,big?26:54);for(let i=0;i<60;i++){const bx2=r()*n,by2=r()*n,br=n*(.04+r()*.14),g=x.createRadialGradient(bx2,by2,0,bx2,by2,br);g.addColorStop(0,r()<.5?'rgba(0,0,0,.16)':'rgba(255,255,255,.12)');g.addColorStop(1,'rgba(100,100,100,0)');x.fillStyle=g;x.fillRect(bx2-br,by2-br,br*2,br*2)}
 const cr=(cx,cy2,rad)=>{const g=x.createRadialGradient(cx,cy2,rad*.2,cx,cy2,rad);g.addColorStop(0,'rgba(30,30,30,.7)');g.addColorStop(.8,'rgba(55,55,55,.4)');g.addColorStop(.93,'rgba(215,215,215,.7)');g.addColorStop(1,'rgba(100,100,100,0)');x.fillStyle=g;x.beginPath();x.arc(cx,cy2,rad,0,7);x.fill();
  x.fillStyle='rgba(0,0,0,.42)';x.beginPath();x.arc(cx+rad*.22,cy2-rad*.08,rad*.62,0,7);x.fill()};
 for(let i=0;i<(big?900:130);i++)cr(r()*n,r()*n,big?2+r()*r()*r()*70:1.5+r()*r()*r()*34);
 if(!big)for(let i=0;i<500;i++){const px=r()*n,py=r()*n,s=.6+r()*1.6;x.fillStyle='rgba(30,30,30,.55)';x.fillRect(px+s,py+s*.4,s*1.6,s*.7);x.fillStyle='rgba(200,200,200,.75)';x.fillRect(px,py,s,s)}
 const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function fadeTex(){const c=cv(256,256),x=c.getContext('2d'),g=x.createRadialGradient(128,128,70,128,128,127);g.addColorStop(0,'#fff');g.addColorStop(1,'#000');x.fillStyle=g;x.fillRect(0,0,256,256);return new THREE.CanvasTexture(c)}
function layerTex(){const c=cv(256,256),x=c.getContext('2d'),r=rng(31);x.fillStyle='#8f8f8f';x.fillRect(0,0,256,256);noisy(x,256,256,r,34);for(let y=0;y<256;y+=8){x.fillStyle='rgba(0,0,0,.26)';x.fillRect(0,y,256,2);x.fillStyle='rgba(255,255,255,.12)';x.fillRect(0,y+3,256,2)}const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function cellTex(){const c=cv(128,256),x=c.getContext('2d');x.fillStyle='#0d1830';x.fillRect(0,0,128,256);x.strokeStyle='#5b6f96';x.lineWidth=1;for(let i=0;i<=8;i++){x.beginPath();x.moveTo(i*16,0);x.lineTo(i*16,256);x.stroke()}for(let j=0;j<=16;j++){x.beginPath();x.moveTo(0,j*16);x.lineTo(128,j*16);x.stroke()}return ctex(c)}
function grainTex(){const n=1024,c=cv(n,n),x=c.getContext('2d'),r=rng(23);x.fillStyle='#646464';x.fillRect(0,0,n,n);noisy(x,n,n,r,46);for(let i=0;i<50;i++){const bx2=r()*n,by2=r()*n,br=n*(.03+r()*.1),g=x.createRadialGradient(bx2,by2,0,bx2,by2,br);g.addColorStop(0,r()<.5?'rgba(0,0,0,.13)':'rgba(255,255,255,.1)');g.addColorStop(1,'rgba(100,100,100,0)');x.fillStyle=g;x.fillRect(bx2-br,by2-br,br*2,br*2)}
 for(let i=0;i<22;i++)crat(x,r()*n,r()*n,2+r()*r()*9);for(let i=0;i<260;i++){const px=r()*n,py=r()*n,q=.6+r()*1.3;x.fillStyle='rgba(30,30,30,.5)';x.fillRect(px-q*1.3,py-q*.8,q*1.6,q*.8);x.fillStyle='rgba(205,205,205,.7)';x.fillRect(px,py,q,q)}
 const t=new THREE.CanvasTexture(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.anisotropy=8;return t}
/* one crater painted for a sun low in the +x,+y corner of the picture: shaded near wall, lit far wall, bright rim */
function crat(x,cx,cy2,rad){const sa=.585,ux=Math.cos(sa),uy=Math.sin(sa);let g=x.createRadialGradient(cx,cy2,0,cx,cy2,rad);g.addColorStop(0,'rgba(40,40,40,.5)');g.addColorStop(.75,'rgba(60,60,60,.3)');g.addColorStop(1,'rgba(100,100,100,0)');x.fillStyle=g;x.beginPath();x.arc(cx,cy2,rad,0,7);x.fill();
 x.save();x.beginPath();x.arc(cx,cy2,rad*.92,0,7);x.clip();x.fillStyle='rgba(0,0,0,.36)';x.beginPath();x.arc(cx+ux*rad*.42,cy2+uy*rad*.42,rad*.74,0,7);x.fill();x.restore();
 x.lineCap='round';x.strokeStyle='rgba(225,225,225,.2)';x.lineWidth=Math.max(.8,rad*.16);x.beginPath();x.arc(cx,cy2,rad*.8,sa+Math.PI-1.05,sa+Math.PI+1.05);x.stroke();
 x.strokeStyle='rgba(225,225,225,.14)';x.lineWidth=Math.max(.6,rad*.09);x.beginPath();x.arc(cx,cy2,rad*1.04,sa-1.1,sa+1.1);x.stroke();x.strokeStyle='rgba(0,0,0,.12)';x.beginPath();x.arc(cx,cy2,rad*1.08,sa+Math.PI-.9,sa+Math.PI+.9);x.stroke()}
/* fine relief of the regolith as a normal map: overlapping small craters, clods and soft undulation, wrapped so it tiles */
function regoNormal(){const n=1024,hc=cv(n,n),hx=hc.getContext('2d'),r=rng(131),W=(f,x,y,rad)=>{for(const ox of [-n,0,n])for(const oy of [-n,0,n]){if(x+ox<-rad||x+ox>n+rad||y+oy<-rad||y+oy>n+rad)continue;f(x+ox,y+oy)}};
 hx.fillStyle='#808080';hx.fillRect(0,0,n,n);
 for(let i=0;i<260;i++){const x=r()*n,y=r()*n,rad=30+r()*120,up=r()<.5;W((a,b)=>{const g=hx.createRadialGradient(a,b,0,a,b,rad);g.addColorStop(0,up?'rgba(255,255,255,.1)':'rgba(0,0,0,.1)');g.addColorStop(1,'rgba(128,128,128,0)');hx.fillStyle=g;hx.fillRect(a-rad,b-rad,rad*2,rad*2)},x,y,rad)}
 hx.filter='blur(1.2px)';const KC=[];for(let i=0;i<300;i++){const x=r()*n,y=r()*n,q=r(),rad=3+q*q*q*q*q*q*56;if(KC.some(c=>{const ddx=Math.abs(x-c[0]),ddy=Math.abs(y-c[1]);return Math.hypot(Math.min(ddx,n-ddx),Math.min(ddy,n-ddy))<(rad+c[2])*1.45}))continue;KC.push([x,y,rad]);W((a,b)=>{let g=hx.createRadialGradient(a,b,rad*.72,a,b,rad*1.3);g.addColorStop(0,'rgba(255,255,255,0)');g.addColorStop(.45,'rgba(255,255,255,.3)');g.addColorStop(1,'rgba(255,255,255,0)');hx.fillStyle=g;hx.fillRect(a-rad*1.3,b-rad*1.3,rad*2.6,rad*2.6);
   g=hx.createRadialGradient(a,b,0,a,b,rad);g.addColorStop(0,'rgba(0,0,0,.42)');g.addColorStop(.7,'rgba(0,0,0,.24)');g.addColorStop(1,'rgba(0,0,0,0)');hx.fillStyle=g;hx.beginPath();hx.arc(a,b,rad,0,7);hx.fill()},x,y,rad*1.3)}
 for(let i=0;i<1800;i++){const x=r()*n,y=r()*n,rad=1.2+r()*r()*3.4;W((a,b)=>{const g=hx.createRadialGradient(a,b,0,a,b,rad);g.addColorStop(0,'rgba(255,255,255,.5)');g.addColorStop(1,'rgba(255,255,255,0)');hx.fillStyle=g;hx.fillRect(a-rad,b-rad,rad*2,rad*2)},x,y,rad)}
 const hd=hx.getImageData(0,0,n,n).data,nc=cv(n,n),nx=nc.getContext('2d'),ni=nx.createImageData(n,n),nd=ni.data,H=(x,y)=>hd[(((y+n)%n)*n+((x+n)%n))*4];
 for(let y=0;y<n;y++)for(let x=0;x<n;x++){const i=(y*n+x)*4,dx=(H(x-2,y)-H(x+2,y))*.016,dy=(H(x,y+2)-H(x,y-2))*.016,k=1/Math.sqrt(dx*dx+dy*dy+1);nd[i]=(dx*k*.5+.5)*255;nd[i+1]=(dy*k*.5+.5)*255;nd[i+2]=(k*.5+.5)*255;nd[i+3]=255}
 nx.putImageData(ni,0,0);const t=new THREE.CanvasTexture(nc);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.anisotropy=8;return t}
/* cladding of the surface modules: panels, seams, fasteners, a few access hatches; returned with its relief */
function hullTex(){const c=cv(1024,512),x=c.getContext('2d'),b=cv(1024,512),y=b.getContext('2d'),r=rng(59);x.fillStyle='#cfcfc9';x.fillRect(0,0,1024,512);y.fillStyle='#909090';y.fillRect(0,0,1024,512);
 for(let i=0;i<8;i++)for(let j=0;j<4;j++){const px=i*128,py=j*128,t=200+Math.floor(r()*26);x.fillStyle='rgb('+t+','+t+','+(t-5)+')';x.fillRect(px+2,py+2,124,124);y.fillStyle='#a8a8a8';y.fillRect(px+3,py+3,122,122);
  if(r()<.16){x.fillStyle='#8f949b';x.fillRect(px+30,py+34,68,60);y.fillStyle='#707070';y.fillRect(px+30,py+34,68,60);x.strokeStyle='#5c6067';x.lineWidth=2;x.strokeRect(px+30,py+34,68,60)}
  if(r()<.1){x.fillStyle='#c98a1e';x.fillRect(px+8,py+56,112,10)}
  x.fillStyle='#6f7379';[[8,8],[120,8],[8,120],[120,120],[64,8],[64,120]].forEach(q=>{x.beginPath();x.arc(px+q[0],py+q[1],2,0,7);x.fill()})}
 x.strokeStyle='rgba(60,62,66,.8)';x.lineWidth=2;y.strokeStyle='#404040';y.lineWidth=3;for(let i=0;i<=8;i++){x.beginPath();x.moveTo(i*128,0);x.lineTo(i*128,512);x.stroke();y.beginPath();y.moveTo(i*128,0);y.lineTo(i*128,512);y.stroke()}for(let j=0;j<=4;j++){x.beginPath();x.moveTo(0,j*128);x.lineTo(1024,j*128);x.stroke();y.beginPath();y.moveTo(0,j*128);y.lineTo(1024,j*128);y.stroke()}
 noisy(x,1024,512,r,12);for(let i=0;i<60;i++){const px=r()*1024,g=x.createLinearGradient(0,0,0,200+r()*300);g.addColorStop(0,'rgba(70,66,58,.12)');g.addColorStop(1,'rgba(70,66,58,0)');x.fillStyle=g;x.fillRect(px,0,4+r()*18,512)}
 const m=ctex(c),bt=new THREE.CanvasTexture(b);[m,bt].forEach(t=>{t.wrapS=t.wrapT=THREE.RepeatWrapping;t.anisotropy=8});return{map:m,bump:bt}}
/* end wall of a module: ring frame, hatch with a small window and hand wheel */
function capTex(){const c=cv(512,512),x=c.getContext('2d'),r=rng(7);x.fillStyle='#c9c9c3';x.fillRect(0,0,512,512);noisy(x,512,512,r,12);x.strokeStyle='#7c8087';x.lineWidth=14;x.beginPath();x.arc(256,256,236,0,7);x.stroke();for(let i=0;i<24;i++){const a=i/24*6.2832;x.fillStyle='#5c6067';x.beginPath();x.arc(256+Math.cos(a)*236,256+Math.sin(a)*236,4,0,7);x.fill()}
 x.fillStyle='#a4a7ab';x.beginPath();x.arc(256,256,150,0,7);x.fill();x.strokeStyle='#4f535a';x.lineWidth=8;x.stroke();x.fillStyle='#8c9096';x.beginPath();x.arc(256,256,118,0,7);x.fill();x.fillStyle='#10161f';x.beginPath();x.arc(256,214,34,0,7);x.fill();x.fillStyle='#ffd9a0';x.beginPath();x.arc(256,214,26,0,7);x.fill();
 x.strokeStyle='#3a3d44';x.lineWidth=7;x.beginPath();x.arc(256,300,30,0,7);x.stroke();for(let i=0;i<3;i++){const a=i*Math.PI/3;x.beginPath();x.moveTo(256-Math.cos(a)*30,300-Math.sin(a)*30);x.lineTo(256+Math.cos(a)*30,300+Math.sin(a)*30);x.stroke()}x.fillStyle='#c98a1e';x.fillRect(96,56,90,16);return ctex(c)}
function craterTex(){const n=4096,c=cv(n,n),x=c.getContext('2d'),r=rng(77);x.fillStyle='#686868';x.fillRect(0,0,n,n);for(let i=0;i<260;i++){const bx2=r()*n,by2=r()*n,br=n*(.01+r()*.07),g=x.createRadialGradient(bx2,by2,0,bx2,by2,br);g.addColorStop(0,r()<.5?'rgba(0,0,0,.12)':'rgba(255,255,255,.09)');g.addColorStop(1,'rgba(104,104,104,0)');x.fillStyle=g;x.fillRect(bx2-br,by2-br,br*2,br*2)}
 const KP=[];for(let i=0;i<2600;i++){const cx=r()*n,cy2=r()*n,q=r(),rad=1.4+q*q*q*q*q*34;if(Math.hypot(cx-n/2,cy2-n/2)<150+rad*2&&rad>3)continue;if(KP.some(c=>Math.hypot(cx-c[0],cy2-c[1])<(rad+c[2])*1.35))continue;KP.push([cx,cy2,rad]);crat(x,cx,cy2,rad)}const t=ctex(c);t.anisotropy=8;return t}
function sqFade(m,a){m.transparent=true;m.onBeforeCompile=sh2=>{sh2.vertexShader='varying vec2 vRaw;\n'+sh2.vertexShader.replace('#include <uv_vertex>','#include <uv_vertex>\n vRaw=uv;');sh2.fragmentShader='varying vec2 vRaw;\n'+sh2.fragmentShader.replace('#include <map_fragment>','#include <map_fragment>\n diffuseColor.a*=smoothstep(.5,'+a.toFixed(3)+',max(abs(vRaw.x-.5),abs(vRaw.y-.5)));')};return m}
function cloudTex(){const n=2048,c=cv(n,n),x=c.getContext('2d'),r=rng(5);for(let k=0;k<150;k++){const cx=r()*n,cy2=r()*n,sp=20+r()*70,m=8+Math.floor(r()*26);for(let i=0;i<m;i++){const px=cx+(r()-.5)*sp*2.4,py=cy2+(r()-.5)*sp,br=6+r()*sp*.5,g=x.createRadialGradient(px,py,0,px,py,br);g.addColorStop(0,'rgba(255,255,255,.34)');g.addColorStop(.6,'rgba(255,255,255,.16)');g.addColorStop(1,'rgba(255,255,255,0)');x.fillStyle=g;x.fillRect(px-br,py-br,br*2,br*2)}}return ctex(c)}
/* cladding of the assembly building: ribbed white panels; doors drawn as the tall inverted T of the high bays */
function wallTex(w,h,doors,flag){const c=cv(1024,1024),x=c.getContext('2d'),r=rng(w+h),sx=1024/w,sy=1024/h;x.fillStyle='#c3c6c8';x.fillRect(0,0,1024,1024);for(let i=0;i<1024;i+=5){x.fillStyle='rgba(0,0,0,'+(.03+r()*.05)+')';x.fillRect(i,0,1.5,1024)}for(let m=0;m<h;m+=9.6){x.fillStyle='rgba(0,0,0,.13)';x.fillRect(0,1024-m*sy,1024,1.5)}
 for(let i=0;i<70;i++){const px=r()*1024,g=x.createLinearGradient(0,0,0,300+r()*600);g.addColorStop(0,'rgba(60,60,55,.10)');g.addColorStop(1,'rgba(60,60,55,0)');x.fillStyle=g;x.fillRect(px,0,3+r()*14,1024)}
 x.fillStyle='rgba(0,0,0,.2)';x.fillRect(0,0,1024,10);
 (doors||[]).forEach(cx=>{const X=cx*sx,dr=(w2,y0,y1)=>{x.fillStyle='#9a9fa5';x.fillRect(X-w2*sx/2,1024-y1*sy,w2*sx,(y1-y0)*sy);x.strokeStyle='rgba(20,22,26,.75)';x.lineWidth=3;x.strokeRect(X-w2*sx/2,1024-y1*sy,w2*sx,(y1-y0)*sy)};dr(23,34,139);dr(46,0,35);x.fillStyle='rgba(20,22,26,.5)';for(let k=1;k<7;k++)x.fillRect(X-11.5*sx,1024-(34+k*15)*sy,23*sx,2);for(let k=1;k<4;k++)x.fillRect(X-23*sx+k*11.5*sx,1024-35*sy,2,35*sy);
  x.fillStyle='rgba(0,0,0,.28)';x.fillRect(X-11.5*sx,1024-139*sy,23*sx,7);x.fillRect(X-23*sx,1024-35*sy,46*sx,5)});
 if(flag){const fw=64*sx,fh=34*sy,fx=14*sx,fy=1024-150*sy;x.fillStyle='#f2f2f0';x.fillRect(fx,fy,fw,fh);x.fillStyle='#b22234';for(let k=0;k<13;k+=2)x.fillRect(fx,fy+k*fh/13,fw,fh/13);x.fillStyle='#2c3668';x.fillRect(fx,fy,fw*.4,fh*7/13);x.fillStyle='#f2f2f0';for(let j=0;j<9;j++)for(let i=0;i<(j%2?5:6);i++)x.fillRect(fx+fw*.4*((i+(j%2?1:.5))/6)-1.5,fy+fh*7/13*((j+.5)/9)-1.5,3,3)}
 return ctex(c)}
/* facade textures for the campus */
function facTex(kind,seed){const c=cv(512,256),x=c.getContext('2d'),r=rng(seed);
 if(kind==='glass'){x.fillStyle='#22303f';x.fillRect(0,0,512,256);for(let j=0;j<4;j++)for(let i=0;i<16;i++){const g=x.createLinearGradient(0,j*64,0,j*64+64);const lit=r()<.12;g.addColorStop(0,lit?'#ffe6b0':'#7fa7c9');g.addColorStop(1,lit?'#d8b878':'#3f607f');x.fillStyle=g;x.fillRect(i*32+2,j*64+4,28,50);x.fillStyle='rgba(255,255,255,.12)';x.fillRect(i*32+2,j*64+4,28,9)}for(let j=0;j<4;j++){x.fillStyle='#c9ccce';x.fillRect(0,j*64+56,512,8)}}
 else if(kind==='metal'){x.fillStyle='#c5c9cc';x.fillRect(0,0,512,256);for(let i=0;i<512;i+=8){x.fillStyle='rgba(0,0,0,.1)';x.fillRect(i,0,3,256);x.fillStyle='rgba(255,255,255,.12)';x.fillRect(i+4,0,2,256)}x.fillStyle='#2b3a4a';x.fillRect(0,40,512,34);for(let i=0;i<16;i++){x.fillStyle='#c5c9cc';x.fillRect(i*32,40,3,34)}x.fillStyle='#e0872a';x.fillRect(0,206,512,10)}
 else if(kind==='dark'){x.fillStyle='#2e3338';x.fillRect(0,0,512,256);for(let j=0;j<256;j+=6){x.fillStyle='rgba(0,0,0,.3)';x.fillRect(0,j,512,2)}for(let i=0;i<8;i++){x.fillStyle='#3d444b';x.fillRect(i*64+6,30,52,150);x.strokeStyle='#15181c';x.strokeRect(i*64+6,30,52,150)}x.fillStyle='#4aa3ff';x.fillRect(0,236,512,5)}
 else{x.fillStyle='#b8b5ad';x.fillRect(0,0,512,256);noisy(x,512,256,r,18);x.strokeStyle='rgba(60,58,52,.5)';x.lineWidth=2;for(let i=0;i<=8;i++){x.beginPath();x.moveTo(i*64,0);x.lineTo(i*64,256);x.stroke()}for(let j=0;j<=2;j++){x.beginPath();x.moveTo(0,j*128);x.lineTo(512,j*128);x.stroke()}for(let i=0;i<8;i++)if(r()<.4){x.fillStyle='#2b3a4a';x.fillRect(i*64+20,150,24,60)}for(let i=0;i<40;i++){const px=r()*512,g=x.createLinearGradient(0,0,0,120+r()*130);g.addColorStop(0,'rgba(50,48,40,.16)');g.addColorStop(1,'rgba(50,48,40,0)');x.fillStyle=g;x.fillRect(px,0,3+r()*10,256)}}
 const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function grassTex(){const n=1024,c=cv(n,n),x=c.getContext('2d'),r=rng(41);x.fillStyle='#3c5226';x.fillRect(0,0,n,n);for(let i=0;i<500;i++){const px=r()*n,py=r()*n,br=20+r()*110,g=x.createRadialGradient(px,py,0,px,py,br);g.addColorStop(0,['rgba(88,112,50,.3)','rgba(34,56,24,.34)','rgba(120,118,66,.2)'][i%3]);g.addColorStop(1,'rgba(90,120,60,0)');x.fillStyle=g;x.fillRect(px-br,py-br,br*2,br*2)}
 const im=x.getImageData(0,0,n,n),d=im.data;for(let i=0;i<d.length;i+=4){const q=(r()-.5)*34;d[i]+=q*.8;d[i+1]+=q;d[i+2]+=q*.5}x.putImageData(im,0,0);for(let i=0;i<5000;i++){x.fillStyle=r()<.6?'rgba(26,46,20,.5)':'rgba(130,150,76,.3)';x.fillRect(r()*n,r()*n,1+r()*2,1+r()*3)}const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function paveTex(){const c=cv(256,256),x=c.getContext('2d'),r=rng(8);x.fillStyle='#b9b6ae';x.fillRect(0,0,256,256);noisy(x,256,256,r,20);x.strokeStyle='rgba(80,78,70,.45)';for(let i=0;i<=8;i++){x.beginPath();x.moveTo(i*32,0);x.lineTo(i*32,256);x.moveTo(0,i*32);x.lineTo(256,i*32);x.stroke()}const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
function roadTex(lot){const c=cv(256,256),x=c.getContext('2d'),r=rng(12);x.fillStyle='#4a4c4f';x.fillRect(0,0,256,256);noisy(x,256,256,r,22);x.fillStyle='#e9e9e4';if(lot){for(let i=0;i<=8;i++)x.fillRect(i*32-1,0,3,96),x.fillRect(i*32-1,160,3,96)}else{x.fillRect(124,0,8,120);x.fillRect(6,0,5,256);x.fillRect(245,0,5,256)}const t=ctex(c);t.wrapS=t.wrapT=THREE.RepeatWrapping;return t}
/* ground height around the campus: flat where the buildings stand, rolling meadows and wooded hills further out, a lake in a hollow */
function eH(x,z){const d=Math.hypot(x,z),h=16*Math.sin(x*.0021+1)*Math.cos(z*.0017+.4)+9*Math.sin(x*.0062+z*.0043)+4*Math.sin(x*.015-z*.011)+150*Math.exp(-(Math.pow(x-700,2)+Math.pow(z+1350,2))/360000)+110*Math.exp(-(Math.pow(x+1500,2)+Math.pow(z+1100,2))/420000)+70*Math.exp(-(Math.pow(x-1700,2)+Math.pow(z-300,2))/300000)+190*Math.exp(-(Math.pow(x+300,2)*.25+Math.pow(z+2500,2))/500000)+120*Math.exp(-(Math.pow(x-2500,2)+Math.pow(z+900,2)*.3)/400000)-16*Math.exp(-(Math.pow(x+430,2)+Math.pow(z-150,2))/30000);
 return h*sm(cl((d-210)/260))*(1-sm(cl((d-2300)/600)))-16*Math.exp(-(Math.pow(x+430,2)+Math.pow(z-150,2))/30000)*(1-sm(cl((d-210)/260)))*0}
/* Earth: public imagery from the continent down to the coast, then a modelled research campus with a microgravity drop tower in a quiet wooded landscape */
/* tree shapes: a broadleaf crown made of several soft lobes, a conifer made of stacked tiers; darker toward the bottom */
function treeGeo(seed,conif){const r=rng(seed),P=[],N=[],C=[],add=(g,ox,oy,oz,sx,sy,sz)=>{const q=g.toNonIndexed().attributes.position;for(let i=0;i<q.count;i++){const x=q.getX(i),y=q.getY(i),z=q.getZ(i),l=Math.hypot(x,y,z)||1;P.push(x*sx+ox,y*sy+oy,z*sz+oz);N.push(x/l,y/l*.8+.2,z/l)}};
 if(conif)[[-.55,1,.95],[-.1,.8,.9],[.35,.58,.85],[.8,.34,.8]].forEach(q=>add(new THREE.ConeGeometry(1,1,9),0,q[0],0,q[1],q[2],q[1]));
 else{add(new THREE.IcosahedronGeometry(1,2),0,0,0,.82,.72,.82);for(let i=0;i<6;i++){const a=i/6*6.2832+r(),k=.42+r()*.24;add(new THREE.IcosahedronGeometry(1,1),Math.cos(a)*.6,(r()-.5)*.55,Math.sin(a)*.6,k,k*.9,k)}add(new THREE.IcosahedronGeometry(1,1),(r()-.5)*.3,.52,(r()-.5)*.3,.56,.5,.56)}
 for(let i=0;i<P.length;i+=3){const k=.5+.5*cl((P[i+1]+.9)/1.7);C.push(k,k,k)}const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(P,3));g.setAttribute('color',new THREE.Float32BufferAttribute(C,3));if(conif)g.computeVertexNormals();else g.setAttribute('normal',new THREE.Float32BufferAttribute(N,3));return g}
/* gable roof, unit size: ridge along x */
function gableGeo(){const g=new THREE.BufferGeometry(),v=[-.5,0,-.5,.5,0,-.5,.5,0,.5,-.5,0,.5,-.5,1,0,.5,1,0];g.setAttribute('position',new THREE.Float32BufferAttribute([0,1,2,0,2,3,3,2,5,3,5,4,1,0,4,1,4,5,0,3,4,2,1,5].reduce((a,i)=>a.concat(v.slice(i*3,i*3+3)),[]),3));g.computeVertexNormals();return g}
/* land use around the campus, painted from above on one picture laid over the terrain: field patchwork, village plots and streets, farm tracks.
   Also returns what the 3D objects need: where fields and the village are (no forest there), hedge lines, house and barn positions. */
function landUse(road){const n=2048,c=cv(n,n),x=c.getContext('2d'),r=rng(313),K=n/6400,px=v=>(v+3200)*K,zones=[],hedges=[],houses=[],barns=[],FC=['#a8975a','#5f7f38','#3f662c','#77603f','#b3a53e','#8c9a5a','#9c8650','#4d7632'];
 const zone=(cx,cz,w,h,ang)=>{const Z={cx,cz,w,h,ang,cs:Math.cos(ang),sn:Math.sin(ang)};zones.push(Z);x.save();x.translate(px(cx),px(cz));x.rotate(ang);const W=(a,b)=>[cx+a*Z.cs-b*Z.sn,cz+a*Z.sn+b*Z.cs];
  const split=(x0,z0,x1,z1,d)=>{const w2=x1-x0,h2=z1-z0;if(d>5||(w2<300&&h2<300)||(d>1&&r()<.12)){const col=FC[Math.floor(r()*FC.length)];x.fillStyle=col;x.fillRect(x0*K+1.5,z0*K+1.5,w2*K-3,h2*K-3);x.strokeStyle='rgba(0,0,0,.13)';x.lineWidth=1;const hz=r()<.5;for(let t=4;t<(hz?h2:w2)*K;t+=3){x.beginPath();if(hz){x.moveTo(x0*K+2,z0*K+t);x.lineTo(x1*K-2,z0*K+t)}else{x.moveTo(x0*K+t,z0*K+2);x.lineTo(x0*K+t,z1*K-2)}x.stroke()}
     if(r()<.07&&w2>120&&h2>120)barns.push(W((x0+x1)/2,(z0+z1)/2).concat(ang+(hz?0:1.57)));return}
   if(w2>h2){const m=x0+w2*(.35+r()*.3);hedges.push(W(m,z0).concat(W(m,z1)));split(x0,z0,m,z1,d+1);split(m,z0,x1,z1,d+1)}else{const m=z0+h2*(.35+r()*.3);hedges.push(W(x0,m).concat(W(x1,m)));split(x0,z0,x1,m,d+1);split(x0,m,x1,z1,d+1)}};
  x.fillStyle='#3d5a2a';x.fillRect(-w/2*K,-h/2*K,w*K,h*K);split(-w/2,-h/2,w/2,h/2,0);[[-w/2,-h/2,w/2,-h/2],[w/2,-h/2,w/2,h/2],[w/2,h/2,-w/2,h/2],[-w/2,h/2,-w/2,-h/2]].forEach(q=>hedges.push(W(q[0],q[1]).concat(W(q[2],q[3]))));x.restore()};
 zone(-2150,-150,1250,1100,.18);zone(-1050,1500,1500,1000,-.12);zone(1250,1250,1500,1150,.3);zone(1500,-900,1100,900,-.25);zone(-900,-1500,1100,800,.1);
 /* village along the access road: plots, side streets, houses facing the streets */
 const VC=[-1080,455],street=(pts,wd)=>{x.strokeStyle='#55575a';x.lineWidth=wd*K;x.lineJoin=x.lineCap='round';x.beginPath();pts.forEach((q,i)=>x[i?'lineTo':'moveTo'](px(q[0]),px(q[1])));x.stroke()},
  row=(a,b,off,side)=>{const L=Math.hypot(b[0]-a[0],b[1]-a[1]),ux=(b[0]-a[0])/L,uz=(b[1]-a[1])/L;for(let t=14;t<L-10;t+=19+r()*9){if(r()<.12)continue;const o=off+r()*5,hx=a[0]+ux*t-uz*o*side,hz=a[1]+uz*t+ux*o*side;houses.push([hx,hz,Math.atan2(-uz,ux)]);x.fillStyle=r()<.5?'#86a657':'#789a4c';x.fillRect(px(hx)-4,px(hz)-4,8,8)}};
 [[VC[0],VC[1],370,250,.35],[600,-385,230,150,-.58]].forEach(q=>{x.save();x.translate(px(q[0]),px(q[1]));x.rotate(q[4]);x.scale(1,q[3]/q[2]);const g=x.createRadialGradient(0,0,q[2]*K*.55,0,0,q[2]*K);g.addColorStop(0,'rgba(104,134,66,1)');g.addColorStop(1,'rgba(104,134,66,0)');x.fillStyle=g;x.beginPath();x.arc(0,0,q[2]*K,0,7);x.fill();x.restore()});
 const main=[];for(let i=0;i<=40;i++){const q=road.getPoint(.2+i/40*.42);if(q.x<-700&&q.x>-1450)main.push([q.x,q.z])}
 const S1=[[-1010,420],[-960,250],[-1000,90]],S2=[[-1150,490],[-1210,650],[-1120,760]],S3=[[-880,372],[-800,470],[-820,600]];const S4=[[400,-250],[600,-380],[790,-500]],S5=[[600,-380],[650,-270]];[S1,S2,S3,S4,S5].forEach(q=>street(q,6));
 for(let i=0;i<main.length-1;i++){row(main[i],main[i+1],15,1);row(main[i],main[i+1],15,-1)}[S1,S2,S3,S4,S5].forEach(q=>{for(let i=0;i<q.length-1;i++){row(q[i],q[i+1],13,1);row(q[i],q[i+1],13,-1)}});
 x.fillStyle='#c9c4b4';x.beginPath();x.arc(px(-1060),px(440),9*K+3,0,7);x.fill();
 /* farm tracks */
 x.strokeStyle='#9c8a66';x.lineWidth=2;[[[-1450,640],[-1800,300],[-2150,-150]],[[-1120,760],[-1050,1100],[-1050,1500]],[[-20,104],[420,620],[1250,1250]],[[150,-90],[820,-520],[1500,-900]],[[-90,-110],[-520,-900],[-900,-1500]]].forEach(q=>{x.beginPath();q.forEach((v,i)=>x[i?'lineTo':'moveTo'](px(v[0]),px(v[1])));x.stroke()});
 const t=ctex(c);t.anisotropy=8;const inZone=(X,Z,m)=>zones.some(z=>{const a=(X-z.cx)*z.cs+(Z-z.cz)*z.sn,b=-(X-z.cx)*z.sn+(Z-z.cz)*z.cs;return Math.abs(a)<z.w/2+m&&Math.abs(b)<z.h/2+m}),inVil=(X,Z)=>{const a=(X-VC[0])*.94+(Z-VC[1])*.34,b=-(X-VC[0])*.34+(Z-VC[1])*.94;return a*a/(380*380)+b*b/(260*260)<1||Math.pow((X-600)/240,2)+Math.pow((Z+385)/170,2)<1};
 return{tex:t,inZone,inVil,hedges,houses,barns,VC}}
/* campus ground from above: lawns, a ring road, paved court, aprons, paths, marked car park, helipad */
function campusTex(){const W=2096,H=1568,c=cv(W,H),x=c.getContext('2d'),r=rng(77),k=8,X=v=>(v-22+131)*k,Z=v=>(v-8+98)*k,rc=(x0,z0,x1,z1,col)=>{x.fillStyle=col;x.fillRect(X(x0),Z(z0),(x1-x0)*k,(z1-z0)*k)},ln=(pts,wd,col)=>{x.strokeStyle=col;x.lineWidth=wd*k;x.lineJoin=x.lineCap='round';x.beginPath();pts.forEach((q,i)=>x[i?'lineTo':'moveTo'](X(q[0]),Z(q[1])));x.stroke()};
 x.fillStyle='#57793a';x.fillRect(0,0,W,H);for(let i=0;i<900;i++){const a=r()*W,b=r()*H,br=20+r()*90,g=x.createRadialGradient(a,b,0,a,b,br);g.addColorStop(0,r()<.5?'rgba(110,140,70,.25)':'rgba(50,80,36,.25)');g.addColorStop(1,'rgba(80,110,50,0)');x.fillStyle=g;x.fillRect(a-br,b-br,br*2,br*2)}
 const A='#4b4d50',P='#b5b1a7',Cn='#9d9a92';
 ln([[-96,-78],[140,-78],[140,92],[-96,92],[-96,-78]],7,A);ln([[-20,106],[-20,92]],8,A);ln([[-20,92],[-20,40],[10,8],[42,8]],6.5,A);ln([[42,8],[140,8]],6.5,A);ln([[10,8],[-96,8]],6.5,A);ln([[62,8],[62,-78]],6,A);
 rc(-92,-30,-12,6,P);rc(-90,8,-50,36,P);x.fillStyle=P;x.beginPath();x.arc(X(42),Z(-32),31*k,0,7);x.fill();rc(-62,40,-6,76,Cn);rc(54,36,116,68,Cn);rc(74,-62,124,-28,Cn);rc(-80,76,40,100,A);rc(98,52,134,72,Cn);rc(-104,-72,-78,-46,Cn);rc(118,-84,148,-58,Cn);
 /* paving joints */
 x.strokeStyle='rgba(70,68,60,.28)';x.lineWidth=1;for(let i=0;i<W;i+=16){x.beginPath();x.moveTo(i,0);x.lineTo(i,H);x.stroke()}for(let j=0;j<H;j+=16){x.beginPath();x.moveTo(0,j);x.lineTo(W,j);x.stroke()}
 /* re-cover what must stay plain: lawns and asphalt drawn again over the joints */
 x.globalCompositeOperation='source-over';[[-10,12,36,34],[-48,-74,56,-44],[124,14,136,46],[-94,40,-66,74],[70,-22,134,2]].forEach(q=>{rc(q[0],q[1],q[2],q[3],'#5d8040');for(let i=0;i<40;i++){x.fillStyle=r()<.5?'rgba(120,150,76,.3)':'rgba(46,76,34,.3)';x.fillRect(X(q[0]+r()*(q[2]-q[0])),Z(q[1]+r()*(q[3]-q[1])),10+r()*30,10+r()*30)}});
 ln([[-96,-78],[140,-78],[140,92],[-96,92],[-96,-78]],6.4,A);ln([[-20,106],[-20,40],[10,8],[140,8]],6,A);ln([[10,8],[-96,8]],6,A);ln([[62,8],[62,-78]],5.5,A);rc(-80,76,40,100,A);
 x.setLineDash([18,18]);ln([[-96,-78],[140,-78],[140,92],[-96,92],[-96,-78]],.18,'#e8e6dc');ln([[-20,106],[-20,40],[10,8],[140,8]],.18,'#e8e6dc');x.setLineDash([]);
 x.fillStyle='#ecebe4';for(let i=0;i<=44;i++){x.fillRect(X(-79+i*2.7)-1,Z(77),2,5.2*k);x.fillRect(X(-79+i*2.7)-1,Z(93.6),2,5.2*k)}
 ln([[-52,6],[-52,2]],2.5,P);ln([[-30,36],[-30,40]],2.5,P);ln([[42,-1],[42,8]],3,P);ln([[10,-32],[-12,-20]],3,P);ln([[72,36],[72,8]],3,P);ln([[98,-28],[98,8]],3,P);
 x.strokeStyle='#e9c21a';x.lineWidth=3;x.strokeRect(X(56),Z(38),58*k,28*k);x.fillStyle='#8e8b83';x.beginPath();x.arc(X(122),Z(-5),9*k,0,7);x.fill();x.strokeStyle='#f1f0ea';x.lineWidth=5;x.beginPath();x.arc(X(122),Z(-5),7.4*k,0,7);x.stroke();x.fillStyle='#f1f0ea';x.font='bold '+(9*k)+'px sans-serif';x.textAlign='center';x.textBaseline='middle';x.fillText('H',X(122),Z(-4.6));
 const im=x.getImageData(0,0,W,H),d=im.data;for(let i=0;i<d.length;i+=4){const q=(r()-.5)*16;d[i]+=q;d[i+1]+=q;d[i+2]+=q}x.putImageData(im,0,0);const t=ctex(c);t.anisotropy=8;return t}
function buildEarth(){ebScene=new THREE.Scene();ebScene.environment=scene.environment;ebFog=new THREE.Fog(0xc4d6e8,1e7,2e7);ebScene.fog=ebFog;const eroad=new THREE.CatmullRomCurve3([[-20,102],[-30,128],[-80,152],[-240,172],[-520,330],[-900,380],[-1500,640],[-2600,820]].map(q=>new V(q[0],0,q[1]))),SZ={5:8797467,8:1099683,11:137460,14:17183},RE=6371000,add=o=>{ebScene.add(o);return o},sh=o=>{o.traverse(m=>{if(m.isMesh){m.castShadow=true;m.receiveShadow=true}});ebScene.add(o);return o};
 [5,8,11,14].forEach((z,i)=>{const sz=SZ[z],n=z<=11?96:1,g=new THREE.PlaneGeometry(sz,sz,n,n);g.rotateX(-Math.PI/2);if(z<=11){const p=g.attributes.position;for(let j=0;j<p.count;j++){const X=p.getX(j),Z=p.getZ(j),d=Math.hypot(X,Z)||1,th=d/RE,k=RE*Math.sin(th)/d;p.setXYZ(j,X*k,-RE*(1-Math.cos(th)),Z*k)}}
  const m=new THREE.MeshBasicMaterial({map:etex[z],depthWrite:false,toneMapped:false});if(i>0)sqFade(m,.44);const o=new THREE.Mesh(g,m);o.renderOrder=i-10;o.position.y=i*.02-30;ebScene.add(o)});
 const dg=new THREE.SphereGeometry(1,40,28),dp=dg.attributes.position,dc=new Float32Array(dp.count*3);for(let j=0;j<dp.count;j++){const t=Math.pow(Math.max(0,dp.getY(j)),.38);dc[j*3]=.62+(.09-.62)*t;dc[j*3+1]=.74+(.27-.74)*t;dc[j*3+2]=.88+(.66-.88)*t}dg.setAttribute('color',new THREE.BufferAttribute(dc,3));
 ebDome=new THREE.Mesh(dg,new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.BackSide,depthTest:false,depthWrite:false,fog:false,toneMapped:false}));ebDome.renderOrder=-100;ebDome.frustumCulled=false;ebScene.add(ebDome);
 ebStars=new THREE.Points(starGeo,new THREE.PointsMaterial({size:1.7,sizeAttenuation:false,vertexColors:true,depthWrite:false,depthTest:false,fog:false,blending:THREE.AdditiveBlending,transparent:true}));ebStars.renderOrder=-99;ebStars.frustumCulled=false;ebScene.add(ebStars);
 const ct=cloudTex();[[90000,2400,-8000,-15000,1],[1500000,9500,200000,-150000,.8]].forEach((q,i)=>{const m=sqFade(new THREE.MeshBasicMaterial({map:ct,depthWrite:false,side:THREE.DoubleSide,opacity:q[4],toneMapped:false,fog:false}),.3),o=new THREE.Mesh(new THREE.PlaneGeometry(q[0],q[0]),m);o.rotation.x=-Math.PI/2;o.position.set(q[2],q[1],q[3]);o.renderOrder=5+i;ebScene.add(o)});
 const sun=new THREE.DirectionalLight(0xfff1dc,1.55);sun.position.set(-330,420,400);sun.castShadow=true;sun.shadow.mapSize.set(4096,4096);const sc=sun.shadow.camera;sc.left=-340;sc.right=340;sc.top=340;sc.bottom=-340;sc.near=50;sc.far=1600;sun.shadow.bias=-.0006;ebScene.add(sun);ebScene.add(new THREE.HemisphereLight(0xbcd4f0,0x55603f,.42));
 const LU=landUse(eroad);
 /* terrain */
 const NS=260,tg=new THREE.PlaneGeometry(6400,6400,NS,NS);tg.rotateX(-Math.PI/2);const pa=tg.attributes.position,ua=tg.attributes.uv,wp=v=>Math.sign(v)*Math.pow(Math.abs(v)/3200,1.7)*3200;for(let i=0;i<pa.count;i++){const x=wp(pa.getX(i)),z=wp(pa.getZ(i));pa.setXYZ(i,x,eH(x,z),z);ua.setXY(i,x/6400+.5,.5-z/6400)}tg.computeVertexNormals();
 const gt=grassTex();gt.repeat.set(90,90);gt.anisotropy=8;const gm=sqFade(new THREE.MeshStandardMaterial({map:gt,roughness:1,metalness:0,envMapIntensity:0,color:0xd8d8c8}),.3),ob=gm.onBeforeCompile;gm.onBeforeCompile=q=>{ob(q);q.uniforms.tDet={value:gt};q.uniforms.tLu={value:LU.tex};q.fragmentShader='uniform sampler2D tDet;uniform sampler2D tLu;\n'+q.fragmentShader.replace('#include <map_fragment>','#include <map_fragment>\n float dd=(.55+.7*texture2D(tDet,vRaw*5.3).g);diffuseColor.rgb*=dd*(.7+.5*texture2D(tDet,vRaw.yx*1.7+.3).g);vec4 lu=texture2D(tLu,vRaw);diffuseColor.rgb=mix(diffuseColor.rgb,pow(lu.rgb,vec3(2.2))*(.5+.4*dd),lu.a);')};
 const ter=new THREE.Mesh(tg,gm);ter.renderOrder=-2;ter.receiveShadow=true;ebScene.add(ter);
 const lake=new THREE.Mesh(new THREE.CircleGeometry(230,48),new THREE.MeshBasicMaterial({color:0x2a4a5e}));lake.rotation.x=-Math.PI/2;lake.scale.y=.7;add(at(lake,-430,-5.5,150)).receiveShadow=true;
 /* trees: forest clumps away from fields and houses, hedgerows along the field edges, garden trees in the village */
 const r=rng(207),NB=9000,NC=3600,lm=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1,envMapIntensity:0}),tm2=new THREE.MeshStandardMaterial({color:0x3a2c20,roughness:1,envMapIntensity:0}),tk=new THREE.CylinderGeometry(.1,.16,1,6),crown=treeGeo(3,0),
  IB=[new THREE.InstancedMesh(crown,lm,NB),new THREE.InstancedMesh(treeGeo(8,0),lm,NB)],IC=new THREE.InstancedMesh(treeGeo(5,1),lm,NC),IT=new THREE.InstancedMesh(tk,tm2,NB*2+NC),mm=new THREE.Matrix4(),qq=new THREE.Quaternion(),col=new THREE.Color(),UP=new V(0,1,0),nb=[0,0];let nc=0,nt=0;
 const RS=[];for(let i=0;i<=120;i++){const q=eroad.getPoint(i/120);RS.push([q.x,q.z])}const onRoad=(x,z,m)=>RS.some(q=>Math.abs(q[0]-x)<m+30&&Math.hypot(q[0]-x,q[1]-z)<m),dens=(x,z)=>.5+.5*Math.sin(x*.004+1.3)*Math.cos(z*.0047)+.35*Math.sin(x*.011-z*.009),
  tree=(x,z,conif,hh)=>{if(Math.hypot(x+430,(z-150)/.7)<245||onRoad(x,z,9))return;const y=eH(x,z);qq.setFromAxisAngle(UP,r()*6.28);
   if(conif){if(nc>=NC)return;mm.compose(new V(x,y+hh*.6,z),qq,new V(hh*.2,hh*.42,hh*.2));IC.setMatrixAt(nc,mm);IC.setColorAt(nc,col.setHSL(.36+r()*.05,.42+r()*.12,.022+r()*.02));nc++}
   else{const k=r()<.5?0:1;if(nb[k]>=NB)return;const sc=hh*(.3+r()*.06);mm.compose(new V(x,y+hh*.62,z),qq,new V(sc,sc*(.9+r()*.25),sc));IB[k].setMatrixAt(nb[k],mm);IB[k].setColorAt(nb[k],col.setHSL(.23+r()*.1,.42+r()*.2,.03+r()*.03));nb[k]++}
   mm.compose(new V(x,y+hh*.22,z),qq,new V(hh*.1,hh*.46,hh*.1));IT.setMatrixAt(nt++,mm)};
 for(let i=0;i<90000&&nb[0]+nb[1]+nc<10500;i++){const a=r()*6.2832,d=150+Math.pow(r(),1.4)*3000,x=Math.cos(a)*d,z=Math.sin(a)*d;if(Math.abs(x-22)<140&&Math.abs(z-8)<108)continue;if(LU.inZone(x,z,8)||LU.inVil(x,z))continue;if(d>330&&dens(x,z)<.42+r()*.3)continue;tree(x,z,r()<.3,9+r()*9)}
 LU.hedges.forEach(h=>{const L=Math.hypot(h[2]-h[0],h[3]-h[1]);if(r()<.25)return;for(let t=4;t<L;t+=7+r()*9){if(r()<.2)continue;tree(h[0]+(h[2]-h[0])*t/L+(r()-.5)*3,h[1]+(h[3]-h[1])*t/L+(r()-.5)*3,0,6+r()*6)}});
 for(let i=0;i<380;i++){const a=r()*6.28,d=Math.sqrt(r()),v2=i>260,x=(v2?600:LU.VC[0])+Math.cos(a)*d*(v2?210:350),z=(v2?-385:LU.VC[1])+Math.sin(a)*d*(v2?140:230);if(LU.houses.some(h=>Math.hypot(h[0]-x,h[1]-z)<11))continue;tree(x,z,r()<.15,6+r()*6)}
 IB[0].count=nb[0];IB[1].count=nb[1];IC.count=nc;IT.count=nt;[IB[0],IB[1],IC,IT].forEach(o=>{o.castShadow=true;o.receiveShadow=true;o.frustumCulled=false;ebScene.add(o)});
 /* village: houses with gable roofs along the streets, a church, barns and silos out in the fields, wind turbines on the far hill */
 const HN=LU.houses.length+LU.barns.length+2,ub=new THREE.BoxGeometry(1,1,1),ug=gableGeo(),wm=new THREE.MeshStandardMaterial({color:0xffffff,roughness:.9,envMapIntensity:0}),HB=new THREE.InstancedMesh(ub,wm,HN),HR=new THREE.InstancedMesh(ug,wm,HN),WC=[0xe9e2d0,0xf1eee6,0xd8c7a8,0xb5654a,0xe0d8c8,0xc9b79a],RC=[0x8c3b2a,0x9a4a33,0x5a5f66,0x70382a,0x4a4e55];let hn=0;
 const house=(x,z,ry,w,h,d,wc,rc2,rh)=>{const y=eH(x,z);qq.setFromAxisAngle(UP,ry);mm.compose(new V(x,y+h/2-.3,z),qq,new V(w,h,d));HB.setMatrixAt(hn,mm);HB.setColorAt(hn,col.setHex(wc));mm.compose(new V(x,y+h-.3,z),qq,new V(w*1.06,rh,d*1.1));HR.setMatrixAt(hn,mm);HR.setColorAt(hn,col.setHex(rc2));hn++};
 LU.houses.forEach(h=>house(h[0],h[1],h[2],8+r()*4,4.6+r()*2.4,6.5+r()*2,WC[Math.floor(r()*WC.length)],RC[Math.floor(r()*RC.length)],2.6+r()*1.2));
 LU.barns.forEach(b=>{house(b[0],b[1],b[2],26,7,13,0x8a3f30,0x6b7076,4.5);const sl=cy(3,13,M(0xc9cdd0,{metalness:.6,roughness:.4}),'y');sh(at(sl,b[0]+Math.cos(b[2])*18,eH(b[0],b[1])+6.5,b[1]-Math.sin(b[2])*18));const cp=new THREE.Mesh(new THREE.ConeGeometry(3.1,2.4,20),M(0xa9adb1,{metalness:.6,roughness:.4}));sh(at(cp,sl.position.x,sl.position.y+7.7,sl.position.z))});
 house(-1060,440,.35,24,9,10,0xd9d2c0,0x5a5f66,5);HB.count=HR.count=hn;[HB,HR].forEach(o=>{o.castShadow=true;o.receiveShadow=true;o.frustumCulled=false;ebScene.add(o)});
 const chy=eH(-1048,446);sh(at(bx(6,24,6,M(0xd9d2c0,{roughness:.9})),-1044,chy+12,452));const spire=new THREE.Mesh(new THREE.ConeGeometry(4.6,13,4),M(0x4a4e55,{roughness:.8}));spire.rotation.y=Math.PI/4+.35;sh(at(spire,-1044,chy+30.5,452));
 [[1620,-360],[1770,-250],[1880,-400],[1700,-520]].forEach((q,i)=>{const y=eH(q[0],q[1]),wt=M(0xeeeeea,{roughness:.5}),G=new THREE.Group();G.add(at(new THREE.Mesh(new THREE.CylinderGeometry(1.3,2.4,92,16),wt),0,46,0));G.add(at(bx(7,3,3,wt),1,93,0));const hub=new THREE.Group();for(let k=0;k<3;k++){const bl=bx(1.6,44,.5,wt);bl.position.y=22;const arm=new THREE.Group();arm.add(bl);arm.rotation.x=k*2.094+i;hub.add(arm)}hub.position.set(-3,93,0);G.add(hub);G.rotation.y=.7;sh(at(G,q[0],y,q[1]));ebTurb.push(hub)});
 /* access road */
 const rt=roadTex(0),RP=180,rp=[],ru=[],ri=[];for(let i=0;i<=RP;i++){const t=i/RP,pnt=eroad.getPoint(t),tg2=eroad.getTangent(t),nx=-tg2.z,nz=tg2.x;[-4,4].forEach((o,k)=>{const x=pnt.x+nx*o,z=pnt.z+nz*o;rp.push(x,Math.max(eH(x,z),eH(pnt.x,pnt.z))+.4,z);ru.push(k,t*100)});if(i<RP){const a=i*2;ri.push(a,a+1,a+2,a+1,a+3,a+2)}}
 const rg=new THREE.BufferGeometry();rg.setAttribute('position',new THREE.Float32BufferAttribute(rp,3));rg.setAttribute('uv',new THREE.Float32BufferAttribute(ru,2));rg.setIndex(ri);rg.computeVertexNormals();const road=new THREE.Mesh(rg,new THREE.MeshStandardMaterial({map:rt,roughness:.9,envMapIntensity:0,side:THREE.DoubleSide}));road.receiveShadow=true;ebScene.add(road);
 /* campus ground */
 const pv=new THREE.Mesh(new THREE.PlaneGeometry(262,196),new THREE.MeshStandardMaterial({map:campusTex(),roughness:.95,envMapIntensity:0}));pv.rotation.x=-Math.PI/2;pv.receiveShadow=true;add(at(pv,22,.14,8));
 for(let i=0;i<88;i++){if(r()<.28)continue;const cx=-77.65+(i%44)*2.7,cz=i<44?79.6:96.2,cc=M([0xc7ccd2,0x1d2026,0x8a1f1f,0x2f4f7f,0xe8e8e4,0x55606b,0x9aa0a6][Math.floor(r()*7)],{metalness:.6,roughness:.3}),car=new THREE.Group();car.add(at(bx(1.85,.7,4.3,cc),0,.62,0));car.add(at(bx(1.65,.55,2.2,M(0x10161f,{metalness:.7,roughness:.15})),0,1.22,-.2));sh(at(car,cx,.2,cz))}
 /* perimeter fence and gatehouse */
 const fm=M(0x6f747b,{metalness:.6,roughness:.5}),fence=(x0,z0,x1,z1)=>{const L=Math.hypot(x1-x0,z1-z0),ry=Math.atan2(-(z1-z0),x1-x0);[1.2,2.2].forEach(y=>{const b=bx(L,.08,.08,fm);b.rotation.y=ry;add(at(b,(x0+x1)/2,y,(z0+z1)/2))});for(let t=0;t<=L;t+=6){add(at(bx(.12,2.4,.12,fm),x0+(x1-x0)*t/L,1.2,z0+(z1-z0)*t/L))}};
 fence(-107,-88,151,-88);fence(151,-88,151,104);fence(151,104,-12,104);fence(-28,104,-107,104);fence(-107,104,-107,-88);sh(at(bx(5,3.4,4,M(0xe4e5e2,{roughness:.6})),-9,1.7,99));sh(at(bx(6,.3,5,M(0x55606b)),-9,3.5,99));sh(at(bx(8,.16,.16,M(0xd23b2e)),-20,1.3,103.5));
 /* buildings */
 const T=(k,sd,ru2,rv)=>{const t=facTex(k,sd);t.repeat.set(ru2,rv);t.anisotropy=8;return new THREE.MeshStandardMaterial({map:t,roughness:k==='glass'?.25:.8,metalness:k==='glass'?.55:.1,envMapIntensity:k==='glass'?1:.2})},roofM=M(0x8f9296,{roughness:.9,metalness:0,envMapIntensity:.1}),steel=M(0x9a9da2,STEEL),white=M(0xdcddd9,{roughness:.6}),
  block=(x,z,w,h,d,k,sd,ry)=>{const u=k==='glass'?16:k==='metal'?20:32,G=new THREE.Group(),b=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),[T(k,sd,d/u,k==='glass'?h/14.5:1),T(k,sd,d/u,k==='glass'?h/14.5:1),roofM,roofM,T(k,sd,w/u,k==='glass'?h/14.5:1),T(k,sd,w/u,k==='glass'?h/14.5:1)]);G.add(at(b,0,h/2,0));G.add(at(bx(w+.8,.5,d+.8,white),0,h+.25,0));G.add(at(bx(w+.5,.5,d+.5,M(0x6f6c66,{roughness:.9})),0,.25,0));G.rotation.y=ry||0;sh(at(G,x,0,z));return G},
  hvac=(G,x,y,z,n)=>{for(let i=0;i<n;i++){G.add(at(bx(3.2,1.8,2.4,M(0xb9bdc1,{metalness:.5,roughness:.5})),x+i*4.6,y+.9,z));G.add(at(cy(.9,.3,M(0x30333a),'y'),x+i*4.6,y+1.9,z))}},
  pvr=(G,x,y,z,nx,nz)=>{const m=M(0x1b2a4a,{metalness:.8,roughness:.25,envMapIntensity:1});for(let i=0;i<nx;i++)for(let j=0;j<nz;j++){const p2=bx(3.4,.08,1.8,m);p2.rotation.x=.3;G.add(at(p2,x+i*3.8,y+.6,z+j*2.7))}};
 const ml=block(-52,-12,72,17,28,'glass',1);hvac(ml,-24,17.5,-6,5);ml.add(at(bx(20,6,12,T('concrete',3,1,1)),20,20.5,4));pvr(ml,-33,17.5,3,8,3);block(-70,22,34,9,22,'concrete',2);ml.add(at(bx(16,.5,7,white),-4,4.6,17.5));[-10,2].forEach(xx=>ml.add(at(cy(.25,4.6,steel,'y'),xx,2.3,20)));
 const sh2=block(-34,58,48,12,28,'metal',4);sh2.add(at(bx(40,1.6,5,M(0x9fb6c8,{metalness:.6,roughness:.2})),0,13.2,0));sh2.add(at(bx(9,7,.3,M(0x6f747b,STEEL)),-10,3.5,14.1));pvr(sh2,-21,12.5,5,11,3);pvr(sh2,-21,12.5,-12,11,3);
 const ft=block(72,52,26,10,20,'concrete',5);ft.add(at(cy(1.5,26,M(0xb9bdc1,{metalness:.6,roughness:.45}),'y'),8,13,-4));ft.add(at(cy(1.9,1.2,M(0x8a1f1f),'y'),8,25.6,-4));
 [0,1,2].forEach(i=>{const tk2=new THREE.Group(),m=M(0xe9e9e5,{roughness:.4,metalness:.3});tk2.add(cy(2.2,9,m,'x'));[-4.5,4.5].forEach(k=>tk2.add(at(new THREE.Mesh(new THREE.SphereGeometry(2.2,24,16),m),k,0,0)));[-3,3].forEach(k=>tk2.add(at(bx(.6,2.4,3.6,steel),k,-2.2,0)));sh(at(tk2,106,3.6,56+i*6))});
 sh(at(bx(26,.5,1.6,steel),88,7,46));[78,88,98].forEach(xx=>sh(at(bx(.5,7,.5,steel),xx,3.5,46)));sh(at(cy(.35,26,M(0xd9b21f),'x'),88,7.6,46));
 const cx2=cv(256,512),xx2=cx2.getContext('2d');xx2.fillStyle='#cfccc4';xx2.fillRect(0,0,256,512);noisy(xx2,256,512,rng(6),14);for(let j=0;j<512;j+=20){xx2.fillStyle='rgba(60,58,52,.22)';xx2.fillRect(0,j,256,1.5)}for(let j=30;j<500;j+=46){xx2.fillStyle='#26323f';xx2.fillRect(120,j,14,26)}const tt=ctex(cx2);tt.wrapS=THREE.RepeatWrapping;tt.repeat.set(4,1);
 const tw=new THREE.Group();tw.add(at(new THREE.Mesh(new THREE.CylinderGeometry(5.2,6.4,118,40),new THREE.MeshStandardMaterial({map:tt,roughness:.85,envMapIntensity:.15})),0,59,0));tw.add(at(cy(7.4,3,white,'y'),0,117,0));tw.add(at(new THREE.Mesh(new THREE.CylinderGeometry(2.2,7,13,24),M(0x9fc0d8,{metalness:.7,roughness:.12,envMapIntensity:1.2})),0,125,0));tw.add(at(cy(.25,10,steel,'y'),0,136,0));const tb=glow('rgba(255,70,50,.95)',5);tb.position.set(0,141.5,0);tw.add(tb);
 tw.add(at(new THREE.Mesh(new THREE.CylinderGeometry(17,17,11,48),T('glass',7,8,.8)),0,5.5,0));tw.add(at(cy(17.6,.6,white,'y'),0,11.3,0));tw.add(at(bx(3,96,3,M(0x8f949b,STEEL)),-7,50,0));sh(at(tw,42,0,-32));
 const dcb=block(98,-46,38,10,24,'dark',9);hvac(dcb,-13,10.5,-5,6);hvac(dcb,-13,10.5,4,6);dcb.add(at(cy(.3,9,steel,'y'),15,15,8));const dq=[];for(let i=0;i<=10;i++){const t=i/10;dq.push(new THREE.Vector2(t*3,t*t*1.1))}const dish=new THREE.Mesh(new THREE.LatheGeometry(dq,32),M(0xe6e7e3,{side:THREE.DoubleSide,roughness:.5}));dish.rotation.set(-.8,0,.5);dcb.add(at(dish,15,20,8));[0,1].forEach(i=>sh(at(bx(7,3,3,M(0x55606b,{metalness:.4})),86+i*10,1.5,-26)));
 /* workshop, office annex, substation */
 const ws=block(116,62,32,8,16,'metal',12);pvr(ws,-13,8.5,-4,7,3);block(-91,-59,24,11,22,'glass',14);hvac(block(-91,-59,0.1,0.1,0.1,'concrete',15),-6,11.5,0,3);
 [0,1,2].forEach(i=>{sh(at(bx(4,3.4,3,M(0x7d848c,{metalness:.5,roughness:.5})),124+i*8,1.7,-71));[-.9,.9].forEach(k=>sh(at(cy(.25,1.6,M(0xd9d4c8),'y'),124+i*8+k,4.2,-71)))});
 /* court: lamp posts, flagpoles, rows of trees along the drive and around the forecourt */
 [[-10,34],[30,34],[70,20],[-40,-40],[60,-70],[110,10],[-90,40],[-60,88],[0,88],[30,60],[130,-40],[-30,-70]].forEach(q=>{sh(at(cy(.14,8,steel,'y'),q[0],4,q[1]));sh(at(bx(1.6,.2,.5,M(0x2b2e34)),q[0]+.6,8,q[1]))});
 [-14,-10,-6].forEach((xx,i)=>{sh(at(cy(.1,11,steel,'y'),xx,5.5,-28));sh(at(bx(.05,1.4,2.2,M([0x2f62b0,0xe8e8e4,0xb3261e][i],{roughness:.8})),xx,10.2,-26.8))});
 const ct2=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1,envMapIntensity:0,color:new THREE.Color().setHSL(.27,.5,.07)});[[2,24],[14,30],[-4,16],[20,18],[-84,70],[-92,52],[128,22],[130,38],[10,-56],[40,-66],[-30,-60],[-12,58],[-12,70],[-26,24],[-26,34],[-14,50],[84,-12],[104,-10],[126,-14],[78,-8]].concat([0,1,2,3,4,5,6,7].map(i=>[-88+i*9,2])).concat([0,1,2,3,4,5].map(i=>[76+i*11,14])).forEach(q=>{const hh=7+r()*4,c1=new THREE.Mesh(crown,ct2);c1.scale.setScalar(hh*.32);sh(at(c1,q[0],hh*.62,q[1]));sh(at(cy(hh*.022,hh*.44,tm2,'y'),q[0],hh*.22,q[1]))})}
function buildBase(){mbScene=new THREE.Scene();mbScene.environment=scene.environment;const Y=new V(0,1,0),sh=o=>{o.traverse(m=>{if(m.isMesh){m.castShadow=m.receiveShadow=true}});mbScene.add(o);return o},flat=o=>{o.rotation.x=-Math.PI/2;return o},GT=0x9b9892;
 /* far ground: the real Hadley-Apennine region (Apollo 15 site), its relief from LOLA altimetry and its image from the LRO mosaic; the base sits on the mare plain below the mountains */
 const SZ=213000,dc=cv(256,256),dx=dc.getContext('2d');dx.drawImage(demImg,0,0,256,256);const dd=dx.getImageData(0,0,256,256).data,U0=.516,V0=.484,hAt=(u,v)=>{const fx=cl(u)*255,fy=cl(v)*255,x0=Math.floor(fx),y0=Math.floor(fy),x1=Math.min(255,x0+1),y1=Math.min(255,y0+1),a=fx-x0,b=fy-y0,g=(x,y)=>dd[(y*256+x)*4];return((g(x0,y0)*(1-a)+g(x1,y0)*a)*(1-b)+(g(x0,y1)*(1-a)+g(x1,y1)*a)*b)/255*5879-2821},h0=hAt(U0,V0);
 const fg=new THREE.PlaneGeometry(SZ,SZ,255,255);fg.rotateX(-Math.PI/2);const fp=fg.attributes.position;for(let i=0;i<fp.count;i++){const x=fp.getX(i),z=fp.getZ(i),u=x/SZ+.5,v=z/SZ+.5,d=Math.hypot(x-(U0-.5)*SZ,z-(V0-.5)*SZ);fp.setY(i,(hAt(u,v)-h0)*1.25*sm(cl((d-2500)/9000)))}fg.computeVertexNormals();
 const far=new THREE.Mesh(fg,new THREE.MeshBasicMaterial());far.position.set(-(U0-.5)*SZ,-30,-(V0-.5)*SZ);mbScene.add(far);
 const grain=grainTex(),edge=(m,a,b,k1,k2)=>{m.transparent=a<9;m.onBeforeCompile=sh2=>{sh2.uniforms.tDet={value:grain};sh2.vertexShader='varying vec2 vRaw;\n'+sh2.vertexShader.replace('#include <uv_vertex>','#include <uv_vertex>\n vRaw=uv;');sh2.fragmentShader='varying vec2 vRaw;\nuniform sampler2D tDet;\n'+sh2.fragmentShader.replace('#include <map_fragment>','#include <map_fragment>\n diffuseColor.rgb*=(texture2D(tDet,vRaw*'+k1.toFixed(2)+').g*1.5+texture2D(tDet,vRaw.yx*'+k2.toFixed(2)+'+.37).g*.5)*1.28;\n'+(a<9?' diffuseColor.a*=smoothstep('+b.toFixed(3)+','+a.toFixed(3)+',distance(vRaw,vec2(.5)));':''))};return m};
 far.material=edge(new THREE.MeshStandardMaterial({map:hadTex,roughness:1,metalness:0,envMapIntensity:0,color:0x8c8c8c}),9,9,97,29);
 const mt=groundTex(1);mt.repeat.set(2,2);const mid=flat(new THREE.Mesh(new THREE.RingGeometry(850,6000,96,8),edge(new THREE.MeshStandardMaterial({map:mt,roughness:1,metalness:0,envMapIntensity:0,color:new THREE.Color(GT).multiplyScalar(2.2)}),.22,.5,61,17)));mid.renderOrder=1;mid.receiveShadow=true;mbScene.add(at(mid,0,-.4,0));
 const NS=420,tg=new THREE.PlaneGeometry(2400,2400,NS,NS);tg.rotateX(-Math.PI/2);const pa=tg.attributes.position,ua=tg.attributes.uv,wp=v=>Math.sign(v)*Math.pow(Math.abs(v)/1200,1.9)*1200;for(let i=0;i<pa.count;i++){const x=wp(pa.getX(i)),z=wp(pa.getZ(i));pa.setXYZ(i,x,mbH(x,z),z);ua.setXY(i,x/2400+.5,.5-z/2400)}tg.computeVertexNormals();
 const rn=regoNormal();rn.repeat.set(34,34);const alb=craterTex(),gm=edge(new THREE.MeshStandardMaterial({normalMap:rn,normalScale:new THREE.Vector2(1,1),roughness:1,metalness:0,envMapIntensity:0,color:0x2f2e2c}),.36,.47,53,13.7),obc=gm.onBeforeCompile;gm.onBeforeCompile=sh2=>{obc(sh2);sh2.uniforms.tAlb={value:alb};sh2.fragmentShader='uniform sampler2D tAlb;\n'+sh2.fragmentShader.replace('#include <map_fragment>','#include <map_fragment>\n diffuseColor.rgb*=.45+texture2D(tAlb,vRaw).g*1.42;')};
 const ground=mbGround=new THREE.Mesh(tg,gm);ground.renderOrder=2;ground.receiveShadow=true;mbScene.add(ground);
 const sun=new THREE.DirectionalLight(0xfff3e4,3.4);sun.position.set(300,135,200);sun.castShadow=true;sun.shadow.mapSize.set(4096,4096);const sc=sun.shadow.camera;sc.left=-150;sc.right=150;sc.top=150;sc.bottom=-150;sc.near=10;sc.far=900;sun.shadow.bias=-.0005;mbScene.add(sun);mbScene.add(new THREE.AmbientLight(0x35404f,.22));
 mbScene.add(new THREE.Points(starGeo,new THREE.PointsMaterial({size:1.7,sizeAttenuation:false,vertexColors:true,depthWrite:false})));
 const ea=new THREE.Sprite(new THREE.SpriteMaterial({map:earthMap,depthWrite:false}));ea.position.copy(EAP);ea.scale.set(620,620,1);ea.renderOrder=3;mbScene.add(ea);
 const rk=new THREE.IcosahedronGeometry(1,1),rm=new THREE.MeshStandardMaterial({color:0x3e3e41,roughness:1,flatShading:true,envMapIntensity:0}),rr=rng(88);for(let i=0;i<320;i++){const a=rr()*6.283,d=18+rr()*rr()*380,x=Math.cos(a)*d,z=Math.sin(a)*d,k=.1+rr()*rr()*rr()*1.4,b=new THREE.Mesh(rk,rm);b.scale.set(k,k*.6,k*(.7+rr()*.6));b.rotation.set(rr()*3,rr()*3,rr()*3);b.position.set(x,mbH(x,z)+k*.2,z);b.castShadow=b.receiveShadow=true;mbScene.add(b)}
 const lt=layerTex();lt.repeat.set(1,6);const rego=new THREE.MeshStandardMaterial({map:lt,bumpMap:lt,bumpScale:.5,roughness:1,metalness:0,envMapIntensity:0,color:0xa9a6a0}),white=M(0xdedfdb,{metalness:.2,roughness:.55}),foil=M(0xc9a23a,{metalness:1,roughness:.34}),dark=M(0x26292e,{metalness:.5,roughness:.5}),steel=M(0x8f949b,STEEL),warm=new THREE.MeshBasicMaterial({color:0xffd9a0});
 const link=(a,b,r,m)=>{const A=new V(a[0],a[1],a[2]),B=new V(b[0],b[1],b[2]),c=new THREE.Mesh(new THREE.CylinderGeometry(r,r,A.distanceTo(B),28),m||rego);c.position.copy(A).add(B).multiplyScalar(.5);c.quaternion.setFromUnitVectors(Y,B.clone().sub(A).normalize());return sh(c)};
 /* a surface base: pressurised shells half sunk into the regolith and covered with printed-regolith shielding, joined by tunnels lying on the ground */
 const ht=hullTex(),hull=(ru,rv)=>{const m=ht.map.clone(),b=ht.bump.clone();[m,b].forEach(t=>{t.needsUpdate=true;t.repeat.set(ru,rv)});return new THREE.MeshStandardMaterial({map:m,bumpMap:b,bumpScale:.06,roughness:.62,metalness:.25,envMapIntensity:.5})},cap=new THREE.MeshStandardMaterial({map:capTex(),roughness:.6,metalness:.25,envMapIntensity:.4}),
  hcyl=(x,z,ry,len,rad,yc)=>{const c=new THREE.Mesh(new THREE.CylinderGeometry(rad,rad,len,56,1),[hull(Math.max(2,Math.round(rad*1.3)),Math.max(1,Math.round(len/7))),cap,cap]);c.rotation.z=Math.PI/2;const G=new THREE.Group();G.add(c);G.rotation.y=ry;sh(at(G,x,yc,z));return G},
  mound=(x,z,ry,sx,sy,sz)=>{const m=new THREE.Mesh(new THREE.SphereGeometry(1,56,20,0,6.2832,0,Math.PI/2),rego);m.scale.set(sx,sy,sz);m.rotation.y=ry;sh(at(m,x,-.3,z))},
  win=(G,x,y,z,ry)=>{const w=new THREE.Mesh(new THREE.PlaneGeometry(1.5,.7),warm);w.rotation.y=ry;G.add(at(w,x,y,z));const f=bx(1.8,1,.12,dark);f.rotation.y=ry;f.position.set(x-Math.sin(ry)*.08,y,z-Math.cos(ry)*.08);G.add(f)},
  lamp=(x,z,h2)=>{sh(at(cy(.09,h2,steel,'y'),x,h2/2,z));sh(at(bx(.5,.16,.3,dark),x,h2,z));const q=glow('rgba(255,225,170,.9)',1.6);q.position.set(x,h2-.1,z);mbScene.add(q);const p2=new THREE.PointLight(0xffe2b0,.7,26);p2.position.set(x,h2-.4,z);mbScene.add(p2)};
 /* habitat: a long shell under a shielding mound, both end walls exposed */
 const hab=hcyl(0,0,.32,24,4.2,2.5);[-1,1].forEach(k=>{[-1.9,1.9].forEach(zz=>win(hab,k*8.6,3.6,zz*1.0+(zz>0?2.33:-2.33),zz>0?0:Math.PI))});
 [-12.3,12.3].forEach(k=>{const q=new THREE.Group();q.add(at(bx(.5,.3,4.6,steel),0,-2.2,0));[-1.9,1.9].forEach(zz=>q.add(at(bx(.4,2.6,.4,steel),0,-1.2,zz)));q.position.set(k,0,0);hab.add(q)});
 /* command module: a drum with a ring of windows under a domed roof, on a sunk foundation with a berm */
 const cm=new THREE.Group();cm.add(at(new THREE.Mesh(new THREE.CylinderGeometry(4.6,4.9,6.4,56),hull(8,1)),0,3.0,0));const dome=new THREE.Mesh(new THREE.SphereGeometry(4.6,56,18,0,6.2832,0,Math.PI/2),hull(8,2));dome.scale.y=.42;cm.add(at(dome,0,6.2,0));
 const gl2=cv(512,64),gx=gl2.getContext('2d');gx.fillStyle='#1a2330';gx.fillRect(0,0,512,64);for(let i=0;i<16;i++){gx.fillStyle=i%5===2?'#5b6a7d':'#ffd9a0';gx.fillRect(i*32+4,10,24,44)}const gt2=ctex(gl2);cm.add(at(new THREE.Mesh(new THREE.CylinderGeometry(4.66,4.66,1.0,56,1,true),new THREE.MeshStandardMaterial({map:gt2,emissiveMap:gt2,emissive:0xffffff,emissiveIntensity:.9,roughness:.3,metalness:.4})),0,4.7,0));
 cm.add(at(new THREE.Mesh(new THREE.TorusGeometry(4.75,.14,8,56),steel),0,5.3,0).rotateX(Math.PI/2));cm.add(at(new THREE.Mesh(new THREE.TorusGeometry(4.75,.14,8,56),steel),0,4.1,0).rotateX(Math.PI/2));
 cm.add(at(cy(.14,6,steel,'y'),1.6,10.5,-.8));const dp=[];for(let i=0;i<=10;i++){const t=i/10;dp.push(new THREE.Vector2(t*2.2,t*t*.8))}const dish=new THREE.Mesh(new THREE.LatheGeometry(dp,36),M(0xe6e7e3,{side:THREE.DoubleSide,metalness:.2,roughness:.5}));dish.rotation.set(-.7,0,.5);cm.add(at(dish,1.6,13.4,-.8));cm.add(at(cy(.05,3,steel,'y'),-1.8,9.2,1));const bc=glow('rgba(255,70,50,.95)',1.6);bc.position.set(-1.8,10.8,1);cm.add(bc);sh(at(cm,25,0,-11));

 /* airlock: a short shell at ground level, hatch facing out onto a porch with steps and rails */
 const al=hcyl(12,16.5,-1.15,7,2.3,2.2);const po=new THREE.Group();po.add(at(bx(3.4,.22,4,steel),5.2,-1.4,0));[0,1,2,3].forEach(i=>po.add(at(bx(.7,.18,3,steel),7.2+i*.7,-1.55-i*.2,0)));[-1.9,1.9].forEach(zz=>{po.add(at(bx(3.4,.08,.08,M(0xd9b21f)),5.2,-.3,zz));[3.7,5.2,6.7].forEach(xx=>po.add(at(bx(.08,1.1,.08,M(0xd9b21f)),xx,-.85,zz)))});al.add(po);
 /* tunnels between the shells, lying on the ground, with collar rings */
 const tun=(a,b)=>{link(a,b,1.25,hull(4,2));[.12,.5,.88].forEach(t=>{const A=new V(a[0],a[1],a[2]),B=new V(b[0],b[1],b[2]),c=new THREE.Mesh(new THREE.TorusGeometry(1.32,.11,8,32),steel);c.position.copy(A).lerp(B,t);c.lookAt(B);sh(c)})};
 tun([9.5,1.5,-3.6],[20.8,1.5,-9.2]);tun([5.5,1.5,3.6],[10.6,1.5,13.4]);tun([14.2,1.5,19.4],[24.5,1.5,14.2]);tun([-9.8,1.5,-3.6],[-19.5,1.5,-9.4]);
 /* science lab: an inflatable shell on a low cradle, with a regolith berm on its sunward side */
 link([27,3.9,14],[43,3.9,14],3.8,white);[27,43].forEach(x=>{const e=new THREE.Mesh(new THREE.SphereGeometry(3.8,32,20),white);e.scale.x=.55;sh(at(e,x,3.9,14))});for(let i=0;i<7;i++){const t=new THREE.Mesh(new THREE.TorusGeometry(3.84,.14,8,44),M(0xb8bbb6));t.rotation.y=Math.PI/2;sh(at(t,28+i*2.33,3.9,14))}
 [30,35,40].forEach(x=>{sh(at(bx(.6,1.2,8.2,steel),x,.5,14));mbScene.add(at(bx(1.9,.75,.1,warm),x,4.9,17.74));sh(at(bx(2.3,1.1,.12,dark),x,4.9,17.66))});
 /* control centre: a vaulted shell half sunk in the ground beside the power field */
 const cc=hcyl(-24,-12,1.25,13,4.2,.4);[-1,1].forEach(k=>win(cc,k*2.4,3.1,4.05,0));
 lamp(6,26,6);lamp(-12,10,6);lamp(18,-22,6);lamp(-33,-2,6);
 const pl=new THREE.PointLight(0xffd9a0,1.0,40);pl.position.set(10,5,22);mbScene.add(pl);
 /* power: tracking arrays with cell grids, a radiator, batteries, cables on the ground */
 const ct=cellTex();[-50,-42,-34].forEach((x,i)=>{const z=14-i*6;sh(at(cy(.24,5.1,steel,'y'),x,2.55,z));sh(at(bx(1.2,.5,1.2,dark),x,.25,z));sh(at(bx(.7,.5,.7,dark),x,5.25,z));const p=bx(6,10,.16,new THREE.MeshStandardMaterial({map:ct,metalness:.7,roughness:.28}));p.rotation.set(-.2,-.9,0);sh(at(p,x,10.6,z));const fr=bx(6.3,.2,.3,steel);fr.rotation.copy(p.rotation);fr.position.set(x,5.6,z);sh(fr)});
 [0,1,2].forEach(i=>{sh(at(bx(2.4,1.5,1.6,hull(2,1)),-36-i*2.9,.75,-22));sh(at(bx(2.5,.12,1.7,foil),-36-i*2.9,1.56,-22))});sh(at(bx(.15,4,8,M(0xeeeeea,{roughness:.4})),-40,2.6,-30));[-33.5,-26.5].forEach(z=>sh(at(cy(.1,1.2,steel,'y'),-40,.6,z+0)));
 const cabl=pts=>sh(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts.map(p=>new V(p[0],.12,p[1]))),50,.13,6),dark));cabl([[-42,8],[-36,0],[-31,-6],[-27,-9]]);cabl([[-38,-22],[-33,-19],[-29,-16],[-27,-14]]);cabl([[-50,14],[-46,4],[-38,-4],[-29,-10]]);
 ovScene=new THREE.Scene();ovCam=new THREE.OrthographicCamera(-1,1,1,-1,0,1);ovMat=new THREE.MeshBasicMaterial({transparent:true,depthTest:false,depthWrite:false,toneMapped:false});ovScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2,2),ovMat));mkRT()}
function glow(col,size){const c=cv(128,128),x=c.getContext('2d'),g=x.createRadialGradient(64,64,0,64,64,64);g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.25,col);g.addColorStop(1,'rgba(0,0,0,0)');x.fillStyle=g;x.fillRect(0,0,128,128);const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:ctex(c),blending:THREE.AdditiveBlending,depthWrite:false,transparent:true}));sp.scale.set(size,size,1);return sp}
function signN(n){const c=cv(256,128),x=c.getContext('2d');x.fillStyle='#e6e7e3';x.fillRect(0,0,256,128);x.fillStyle='#1c1f25';x.font='bold 70px sans-serif';x.textAlign='center';x.fillText(n,128,88);return ctex(c)}
function mkRT(){if(!ovMat)return;const s=R.getDrawingBufferSize(new THREE.Vector2());if(rtA)rtA.dispose();rtA=new THREE.WebGLRenderTarget(s.x,s.y);ovMat.map=rtA.texture}
/* cross-dissolve between two renders, so a change of place never cuts to black */
function blend(A,B,w){if(w<=0){B();return}if(w>=1){A();return}R.setRenderTarget(rtA);A();R.setRenderTarget(null);B();ovMat.opacity=w;R.autoClear=false;R.render(ovScene,ovCam);R.autoClear=true}
function envInit(){Gv.copy(P2).addScaledVector(dirOf(15*RAD,-62*RAD),130).normalize().multiplyScalar(RM);PDv.copy(P2).lerp(Gv,.8);PEv.copy(P2).add(tv.set(-75,8,10));ED2.copy(P0).addScaledVector(EDIR,8000).sub(PEv).normalize()}
/* the base camera: e = 0 looks straight down from 64 km, e = 1 is the viewpoint beside the base; distance shrinks geometrically so the descent feels continuous */
let dive=null,mbGround=null;
function sitePose(cm,L,D,R0,H,yw0,pt,e,now){const on=e>=1?1:0,dist=Math.exp(Math.log(H)+(Math.log(R0)-Math.log(H))*e),yw=(yw0+(now?Math.sin(now/9000)*.06:0))*on;
 tv.set(.04,1,.06).lerp(tv2.copy(D).normalize(),Math.pow(e,1.5)).normalize();const c=Math.cos(yw),s=Math.sin(yw),x=tv.x*c-tv.z*s,z=tv.x*s+tv.z*c;tv.set(x,Math.max(.06,tv.y+pt*on),z).normalize();cm.position.copy(L).addScaledVector(tv,dist);cm.lookAt(L);if(dive&&dive.c===cm){const k=cl((performance.now()-dive.t0)/800);cm.position.lerp(dive.p,k*k*k*.82);cm.lookAt(tv2.copy(L).lerp(dive.p,cl(k*2.5)))}return dist}
function mbPose(e,now){const d=sitePose(mbCam,MBL,MBD,MBR,64000,mbYaw,mbPit,e,now);if(mbGround)mbGround.material.normalScale.setScalar(1-.93*sm(cl((d-110)/380)))}
/* Earth camera: same geometric approach from 6 200 km; sky, haze and stars follow the altitude so the atmosphere appears on the way down */
function ebPose(e,now){const d=sitePose(ebCam,EBL,EBD,EBR,EH,ebYaw,ebPit,e,now);if(!ebScene)return;const a=1-sm(cl((Math.log(Math.max(1,ebCam.position.y))-Math.log(9000))/(Math.log(140000)-Math.log(9000))));
 ebCam.near=Math.max(2,d*.02);ebCam.far=d*30+4e5;ebCam.updateProjectionMatrix();ebFog.near=d*1.5+400;ebFog.far=Math.max(d*40,60000);ebFog.color.setRGB(.62*a,.74*a,.88*a);ebDome.position.copy(ebCam.position);ebDome.scale.setScalar(ebCam.far*.5);ebDome.material.color.setScalar(a);ebStars.position.copy(ebCam.position);ebStars.scale.setScalar(d*2/30000);ebStars.material.color.setScalar(1-a);ebStars.visible=a<.98;if(now)ebTurb.forEach(h=>{h.rotation.x=now/1400})}
/* one deterministic shot per change of environment; u runs 0 to 1 */
function renderEnv(k,u,now){const asp=EXPORT?16/9:app.clientWidth/app.clientHeight,f0=asp<1?58:38,toEarth=e=>{cam.position.copy(P2).lerp(PEv,e);cam.fov=f0+(11-f0)*e;cam.updateProjectionMatrix();tv.copy(D2).lerp(ED2,e).normalize().add(cam.position);cam.lookAt(tv)},orb=()=>R.render(scene,cam),loc=()=>R.render(mbScene,mbCam),loe=()=>R.render(ebScene,ebCam);mbCam.aspect=asp;ebCam.aspect=asp;ebCam.fov=f0;
 if(k==='earth'){const z=sm(cl((u-.3)/.3)),b=cl((u-.44)/.56),w=1-sm(cl((u-.47)/.17));if(w>0){toEarth(sm(cl(u/.36)));cam.fov*=Math.pow(.12,z);cam.updateProjectionMatrix()}ebPose(1-Math.pow(1-b,2.4),now);blend(orb,loe,w);return}
 if(k==='moon'){const a=cl(u/.44),b=cl((u-.3)/.7),w=1-sm(cl((u-.3)/.16));if(w>0){cam.position.copy(P2).lerp(PDv,a*a);cam.fov=f0;cam.updateProjectionMatrix();tv.copy(ST).lerp(Gv,sm(cl(a*1.3)));cam.lookAt(tv)}
  mbCam.fov=f0;mbCam.updateProjectionMatrix();mbPose(1-Math.pow(1-b,2.4),now);blend(orb,loc,w);return}
 const e=sm(cl(u/.5)),b=cl((u-.42)/.58),w=1-sm(cl((u-.44)/.16));if(w>0){mbPose(1,0);tv.copy(MBL).sub(mbCam.position).normalize().lerp(tv2.copy(EAP).sub(mbCam.position).normalize(),e).normalize().add(mbCam.position);mbCam.fov=f0*Math.pow(1.25/f0,e);mbCam.updateProjectionMatrix();mbCam.lookAt(tv)}ebPose(1-Math.pow(1-b,2.4),now);blend(loc,loe,w)}
function mpos(id,w,h){if(view==='earth'){if(!LIVE){ebCam.aspect=16/9;ebCam.fov=38;ebCam.updateProjectionMatrix();ebPose(1,0);ebCam.updateMatrixWorld()}return scr(v3.fromArray(ANCHE[id]),w,h,ebCam)}if(view==='moon'){if(!LIVE){mbCam.aspect=16/9;mbCam.fov=38;mbCam.updateProjectionMatrix();mbPose(1,0);mbCam.updateMatrixWorld()}return scr(v3.fromArray(ANCHM[id]),w,h,mbCam)}const p=anchorPos(id);return p?scr(p,w,h,cam):null}
function setEnv(k){if(tr||busy||state!=='hub'||k===view||!SCEN[k])return;S.scen=k;envDefaults();drawSeg();drawTags();if(CALM){view=k;return}const pair=[view,k].sort().join('-'),kind=pair==='earth-moon'?'x':pair==='iss-moon'?'moon':'earth',rev=kind==='x'?view==='earth':view!=='iss';
 tr={i:0,t0:performance.now(),steps:[{k:kind,rev:rev,to:k,d:EDUR[kind]}]};app.classList.add('going')}

/* ---------- pre-rendered frames, used when WebGL is unavailable: 9 frames per sheet ---------- */
const sheets={i:[],o:[],m:[],e:[],x:[]},rooms={};let lastKey='';
const fr=(k,i)=>{const im=sheets[k][Math.floor(i/9)],j=i%9;return im&&im.naturalWidth?{im:im,sx:(j%3)*1280,sy:Math.floor(j/3)*720,key:k+i}:null};
function initSeq(){gl.hidden=true;seq.hidden=false;let n=0;const p2=i=>String(i).padStart(2,'0'),ni=Math.ceil(NF/9),no=Math.ceil(NH/9);
 for(let i=0;i<ni;i++){const im=new Image();im.onload=im.onerror=()=>{n++;$('#igl').textContent='Loading '+Math.round(n/ni*100)+' %';if(n===ni){onReady();for(let j=0;j<no;j++){const h=new Image();h.src='frames/s'+p2(j)+'.jpg';sheets.o.push(h)}for(let j=0;j<Math.ceil(NM/9);j++){const h=new Image();h.src='frames/ma'+p2(j)+'.jpg';sheets.m.push(h)}for(let j=0;j<Math.ceil(NE/9);j++){const h=new Image();h.src='frames/ea'+p2(j)+'.jpg';sheets.e.push(h)}for(let j=0;j<Math.ceil(NX/9);j++){const h=new Image();h.src='frames/xa'+p2(j)+'.jpg';sheets.x.push(h)}MODS.forEach(m=>['','e'].forEach(e=>{const q=new Image();q.src='rooms/'+m.id+'3'+e+'.jpg';rooms[m.id+e]=q}))}};im.src='frames/r'+p2(i)+'.jpg';sheets.i.push(im)}}
let zoomF=1,zl=1,spin0=0;const CALM=matchMedia('(prefers-reduced-motion:reduce)').matches;
function fit(w,h){const k=Math.max(w/1280,h/720)*zoomF;return{k:k,x:(w-1280*k)/2,y:(h-720*k)/2}}
function drawPair(a,b,f){if(!a)return;const two=b&&f>.02,key=a.key+(two?f.toFixed(2):'')+zoomF.toFixed(4);if(key===lastKey)return;lastKey=key;const w=app.clientWidth,h=app.clientHeight,d=Math.min(devicePixelRatio||1,2);
 if(seq.width!==Math.round(w*d)||seq.height!==Math.round(h*d)){seq.width=Math.round(w*d);seq.height=Math.round(h*d)}const c=seq.getContext('2d'),q=fit(w,h);c.setTransform(d,0,0,d,0,0);c.fillStyle='#000';c.fillRect(0,0,w,h);
 c.drawImage(a.im,a.sx,a.sy,1280,720,q.x,q.y,1280*q.k,720*q.k);if(two){c.globalAlpha=f;c.drawImage(b.im,b.sx,b.sy,1280,720,q.x,q.y,1280*q.k,720*q.k);c.globalAlpha=1}}

function onReady(){if(LIVE){envInit();buildBase();buildEarth()}ready=true;$('#ignite').disabled=false;$('#igl').textContent='Simulate';if(EXPORT)return doExport();if(QS.has('hub')){if(SCEN[QS.get('env')]){S.scen=view=QS.get('env');envDefaults();drawSeg();drawTags()}enter(true);if(QS.get('open'))setTimeout(()=>enterRoom(QS.get('open')),300)}if(HOLD)setTimeout(()=>fetch('/done'),+QS.get('hold')||2600)}
function size(){const w=app.clientWidth,h=app.clientHeight;if(LIVE){R.setSize(w,h,false);mkRT();cam.aspect=inCam.aspect=w/h;cam.updateProjectionMatrix();inCam.fov=w<h?84:64;inCam.updateProjectionMatrix()}else{cam.aspect=16/9;cam.fov=38;cam.updateProjectionMatrix();lastKey=''}}
const v3=new V();
function scr(p,w,h,c){p.project(c||cam);if(LIVE)return[(p.x*.5+.5)*w,(-p.y*.5+.5)*h,p.z];const f=fit(w,h);return[f.x+(p.x*.5+.5)*1280*f.k,f.y+(-p.y*.5+.5)*720*f.k,p.z]}
function anchorPos(id){if(LIVE){const a=anchors[id];if(!a)return null;return a.getWorldPosition(v3)}if(!ANCH||!ANCH[id])return null;return v3.fromArray(ANCH[id])}
const pf={n:0,s:0,c:0,l:0,k:0,b:0,f:0};
function toSeq(){if(!LIVE)return;LIVE=false;try{sessionStorage.setItem('fif_nogl','1')}catch(e){}ready=false;tr=null;dive=null;const b=$('#ignite');b.disabled=true;$('#igl').textContent='Loading';if(state==='inside')leaveRoom();if(state!=='landing'){view='iss';S.scen='iss';envDefaults();drawSeg();drawTags();app.classList.remove('going');state='hub'}initSeq();size()}
/* the landing must show the Moon: if the 3D canvas stays black where the ground is, the textures did not make it to the graphics card */
function blackCheck(){const g=R.getContext(),W=g.drawingBufferWidth,H=g.drawingBufferHeight,px=new Uint8Array(4);let sum=0;[[.5,.08],[.3,.14],[.72,.05],[.5,.2]].forEach(q=>{g.readPixels(Math.floor(W*q[0]),Math.floor(H*q[1]),1,1,g.RGBA,g.UNSIGNED_BYTE,px);sum+=px[0]+px[1]+px[2]});return sum<24}
if(QS.has('notr')){const st=document.createElement('style');st.textContent='*{transition:none!important;animation:none!important}';document.head.appendChild(st)}
const RAF=QS.has('tick')?f=>setTimeout(()=>f(performance.now()),40):f=>requestAnimationFrame(f);
function frame(now){RAF(frame);const w=app.clientWidth,h=app.clientHeight;if(EXPORT)return;
 /* a 3D view that cannot hold about 18 images per second is replaced by the pre-rendered one */
 if(state!=='inside'&&LIVE&&!HOLD&&!QS.has('gl')&&ready&&pf.n<90){const dt=now-pf.l;pf.l=now;if(dt<1500){pf.n++;if(pf.n>12){pf.s+=dt;pf.c++}if(pf.n===90&&pf.s/pf.c>55){toSeq();return}}}
 const sec=state==='landing'?0:(now-t0)/1000;let t=state==='landing'?0:state==='intro'?sec*1000/DUR:1;
 if(state==='intro'&&t>=1){state='hub';look.copy(ST);camT.copy(P2);lookT.copy(ST)}
 if(state==='intro'&&t>.8)app.classList.remove('pre');
 /* the landing is never still: a slow drift of the view, the ground creeping by, twinkling stars */
 const sw=CALM?0:state==='landing'?1:state==='intro'?Math.max(0,1-t*5):0;if(state==='landing'){zl=1+.045*(.5-.5*Math.cos(now/5200))*sw;spin0+=.0005*sw;drawTw(now,w,h)}zoomF=state==='landing'?zl:state==='intro'?1+(zl-1)*sw:1;
 if(state==='inside')return; // The verified prediction room owns its render loop.
 let env=null,eu=1;if(state==='hub'){if(tr){const st=tr.steps[tr.i];let u=(now-tr.t0)/st.d;if(u>=1){u=1;view=st.to;tr.i++;tr.t0=now;if(tr.i>=tr.steps.length){tr=null;app.classList.remove('going')}}env=st.k;eu=st.rev?1-u:u}else if(view!=='iss'){env=view;eu=1}}
 if(env){if(LIVE){setSpin(spin0+spinAt(sec));renderEnv(env,eu,now)}else{const n=ESH[env][1],q=eu*(n-1),i=Math.floor(q),k=ESH[env][0];drawPair(fr(k,i),fr(k,Math.min(n-1,i+1)),q-i)}}
 else if(LIVE){setSpin(spin0+spinAt(sec));
  if(state==='hub'){cam.position.lerp(camT,.09);look.lerp(lookT,.09);const f=cam.aspect<1?58:38;if(cam.fov!==f){cam.fov=f;cam.updateProjectionMatrix()}cam.lookAt(look)}else{pose(t,cam,cam.aspect);if(sw){cam.position.y+=Math.sin(now/4300)*.9*sw;cam.position.x+=Math.sin(now/6100)*1.5*sw;cam.fov*=1-.03*sw*(.5-.5*Math.cos(now/5200));cam.updateProjectionMatrix()}}
  R.render(scene,cam);if(state==='landing'&&ready&&(!HOLD||QS.has('sw')||QS.has('chk'))&&!QS.has('gl')&&pf.k<6&&++pf.f%20===0){pf.k++;pf.b=blackCheck()?pf.b+1:0;if(QS.has('chk')&&pf.k===3)gl.toBlob(b=>fetch('/?name=chk.jpg',{method:'POST',body:b}),'image/jpeg',.8);if(pf.b>=2||QS.has('sw')){toSeq();return}}}
 else{if(state==='hub'){const q=Math.max(0,sec-DUR/1000)*FPSH,j=Math.floor(q);drawPair(fr('o',(KH+j)%NH)||fr('i',NF-1),fr('o',(KH+j+1)%NH),q-j)}else{const q=cl(t)*(NF-1),i=Math.floor(q);drawPair(fr('i',i),fr('i',Math.min(NF-1,i+1)),q-i)}
  cam.position.copy(P2);cam.lookAt(ST);cam.updateMatrixWorld()}
 const showM=state==='hub'&&!tr;MODS.forEach(m=>{const el=document.querySelector('.mk[data-id="'+m.id+'"]');if(!el)return;const q=showM?mpos(m.id,w,h):null;if(!q){el.style.visibility='hidden';return}el.style.left=q[0]+'px';el.style.top=q[1]+'px';el.style.visibility=q[2]<1?'visible':'hidden';el.classList.toggle('dn',q[1]<310)})}
const TW=[];(()=>{const r=rng(77);for(let i=0;i<110;i++)TW.push([r(),r()*.56,.3+r()*.7,1800+r()*4200,r()*6.28,r()<.12])})();
function drawTw(now,w,h){const cvs=$('#tw'),d=Math.min(devicePixelRatio||1,2);if(cvs.width!==Math.round(w*d)||cvs.height!==Math.round(h*d)){cvs.width=Math.round(w*d);cvs.height=Math.round(h*d)}const c=cvs.getContext('2d');c.setTransform(d,0,0,d,0,0);c.clearRect(0,0,w,h);
 const free=(x,y)=>Math.hypot(x-w/2,y-h*.396)>h*.275;
 TW.forEach(s=>{const x=s[0]*w,y=s[1]*h;if(!free(x,y))return;const a=s[2]*(CALM?.6:.5+.5*Math.sin(now/s[3]*6.28+s[4]));if(a<.05)return;c.fillStyle='rgba(235,242,255,'+a.toFixed(2)+')';c.beginPath();c.arc(x,y,s[5]?1.5:.9,0,6.3);c.fill();if(s[5]&&a>.6){c.fillRect(x-5,y-.4,10,.8);c.fillRect(x-.4,y-5,.8,10)}});
 if(!CALM){const u=(now/16000)%1.25,x=(u*1.1-.05)*w,y=h*(.1+.06*u);if(free(x,y)){const g=c.createLinearGradient(x-46,y-3,x,y);g.addColorStop(0,'rgba(255,255,255,0)');g.addColorStop(1,'rgba(255,255,255,.8)');c.strokeStyle=g;c.lineWidth=1.2;c.beginPath();c.moveTo(x-46,y-2.6);c.lineTo(x,y);c.stroke();c.fillStyle='#fff';c.beginPath();c.arc(x,y,1.4,0,6.3);c.fill()}}}
$('#qm').addEventListener('click',e=>{const l=$('#legal');l.hidden=!l.hidden;e.currentTarget.setAttribute('aria-expanded',String(!l.hidden))});
let drag=null;
gl.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,m:0};gl.setPointerCapture(e.pointerId)});
gl.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;drag.m+=Math.abs(dx)+Math.abs(dy);
 if(state==='inside'){yaw=Math.max(-1.2,Math.min(1.2,yaw+dx*.004));pitch=Math.max(-.5,Math.min(.5,pitch+dy*.003))}else if(state==='hub'&&!tr&&view==='moon'){mbYaw=Math.max(-1.5,Math.min(1.5,mbYaw+dx*.005));mbPit=Math.max(-.12,Math.min(.5,mbPit+dy*.003))}else if(state==='hub'&&!tr&&view==='earth'){ebYaw=Math.max(-1.5,Math.min(1.5,ebYaw+dx*.005));ebPit=Math.max(-.2,Math.min(.5,ebPit+dy*.003))}else if(state==='hub'&&!tr&&view==='iss'&&pivot)pivot.rotation.y+=dx*.006});
gl.addEventListener('pointerup',e=>{const d=drag;drag=null;if(!d||d.m>5||state!=='hub'||view!=='iss'||tr)return;const r=gl.getBoundingClientRect(),p=new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),rc=new THREE.Raycaster();rc.setFromCamera(p,cam);
 const hit=rc.intersectObject(pivot,true)[0];if(hit){let o=hit.object;while(o&&!o.userData.mod)o=o.parent;if(o)enterRoom(o.userData.mod)}});

/* frame export for the pre-rendered fallback (local tooling only) */
async function doExport(){R.setSize(1280,720,false);mkRT();cam.aspect=inCam.aspect=16/9;inCam.fov=64;inCam.updateProjectionMatrix();const blob=()=>new Promise(r=>gl.toBlob(r,'image/jpeg',.86)),put=(n,b)=>fetch('/?name='+n,{method:'POST',body:b}),p3=i=>String(i).padStart(3,'0');
 if(EXPORT==='hub'){for(let j=0;j<NH+KH;j++){setSpin(spinAt(DUR/1000+(j-KH)/FPSH));pose(1,cam,16/9);R.render(scene,cam);await put('g'+p3(j)+'.jpg',await blob())}}
 else if(EXPORT==='env'){setSpin(spinAt(DUR/1000));const ON=QS.get('only'),SK=+QS.get('skip')||1;for(const q of [['moon','m',NM],['earth','e',NE],['x','x',NX]]){if(ON&&ON!==q[0])continue;for(let i=0;i<q[2];i++){if(i%SK&&i!==q[2]-1)continue;renderEnv(q[0],i/(q[2]-1),0);await put(q[1]+p3(i)+'.jpg',await blob())}}}
 else if(EXPORT==='view'){let i=0;for(const az of [15,45,80,-40])for(const el of [-30,-50]){setSpin(spinAt(DUR/1000+(+QS.get('t')||0)));cam.position.copy(P2);cam.fov=60;cam.updateProjectionMatrix();cam.lookAt(dirOf(az*RAD,el*RAD).add(P2));R.render(scene,cam);await put('v'+p3(i++)+'.jpg',await blob())}}
 else if(EXPORT==='rooms'){if(QS.get('env')){S.scen=QS.get('env');envDefaults()}for(const m of MODS){S.mod=m.id;showRoom(m.id);setSpin(spinAt(DUR/1000+8));fxLive([],0);tick();drawRoom(0,true);await put('room_'+m.id+sfx()+'.jpg',await blob());fxLive(FX[m.id](S.par[m.id],0),STYLE[m.id].fz);tick();drawRoom(0,true);await put('view_'+m.id+sfx()+'.jpg',await blob())}}
 else{const n=+QS.get('n')||NF;for(let i=0;i<n;i++){const t=i/(n-1);setSpin(spinAt(t*DUR/1000));pose(t,cam,16/9);R.render(scene,cam);await put('f'+p3(i)+'.jpg',await blob())}
  const o={};Object.keys(anchors).forEach(k=>{o[k]=anchors[k].getWorldPosition(new V()).toArray().map(x=>+x.toFixed(2))});await put('anchors.json',JSON.stringify(o))}
 await fetch('/done')}

/* ---------- UI ---------- */
function drawSeg(){$('#env').innerHTML=Object.keys(SCEN).map(k=>'<button class="ev" data-s="'+k+'" aria-pressed="'+(S.scen===k)+'"><span class="et"><b>'+SCEN[k].n+'</b><small>'+SCEN[k].r+'</small></span><img src="env/'+k+'.jpg" alt=""></button>').join('')}
function drawTags(){const best=MODS.filter(m=>!m.si).map(m=>({m:m,s:ranked(m.f)[0]?score(ranked(m.f)[0],S.scen):0})).sort((a,b)=>b.s-a.s)[0];
 $('#tags').innerHTML=MODS.map(m=>'<button class="mk'+(best&&best.m===m?' top':'')+'" data-id="'+m.id+'" style="--c:'+m.c+'" aria-label="'+m.pred+', '+nm(m)+'"><span class="ex">!</span><span class="pv"><img src="rooms/v_'+m.id+sfx()+'.jpg" alt=""><span class="pn"><b>'+m.pred+'</b><span>'+nm(m)+(best&&best.m===m?' · most relevant':'')+'</span></span></span></button>').join('')}
/* the conditions panel of the room, and its prediction */
const fmt=(v,p)=>(p.st?(+v).toFixed(2):Math.round(v))+p.u;
function upPred(){const m=modOf(S.mod),el=$('#predv');if(m&&PRED[m.id]&&el)el.textContent=PRED[m.id](S.par[m.id])}
function fitBar(){$('#inbar').style.bottom=app.clientWidth>760?'76px':''}
function drawPars(){const el=$('#pars');if(state!=='inside'){el.hidden=true;return}prediction.drawPanel();requestAnimationFrame(fitBar)}
app.addEventListener('input',e=>{const k=e.target.dataset&&e.target.dataset.par;if(!k||!S.mod)return;const p=PARS[S.mod].find(x=>x.k===k);S.par[S.mod][k]=+e.target.value;$('#v-'+k).textContent=fmt(+e.target.value,p);upPred()});
function card(v,i){const s=score(v,S.scen);return '<button class="card" data-inv="'+v.id+'"><span class="rk">'+(i+1)+'</span><b>'+v.id+'</b><span class="sc">'+s+'<span class="meter"><u style="width:'+s+'%"></u></span></span><span class="meta"><span class="dot" style="background:'+AX[v.ax].c+'"></span>'+AX[v.ax].n+' · '+v.fuel+' · '+v.psi+'</span></button>'+
 '<label class="cmp"><input type="checkbox" id="c-'+v.psi+'" data-cmp="'+v.id+'"'+(S.cmp.has(v.id)?' checked':'')+'> Compare</label>'}
function why(v){if(v.pg)return 'The electric field mimics partial gravity, the closest available stand-in for lunar or Martian conditions.';if(v.hi)return 'It covers elevated oxygen or large-scale burning, the conditions that make exploration atmospheres more flammable.';
 if(v.ax==='det')return 'Smoke behaves differently without buoyancy, which changes how detectors must be placed and tuned.';if(v.ax==='sup')return 'It measures how well dilution agents put out a flame when there is no buoyant flow.';return 'It supplies flame-behavior data that predictive fire models are built on.'}
function drawPanel(){const p=$('#panel'),tb=$('#ptab');if(!S.mod||state!=='inside'){p.classList.remove('open');app.classList.remove('has-panel');tb.hidden=true;return}if(!S.side){p.classList.remove('open');app.classList.remove('has-panel');tb.hidden=false;return}tb.hidden=true;const m=modOf(S.mod);
 if(S.inv){const v=INV.find(x=>x.id===S.inv),s=score(v,S.scen);
  p.innerHTML='<div class="ph"><div><h2>'+v.id+'</h2><p>'+v.name+'</p></div><button class="x" data-close aria-label="Hide this panel">×</button></div><div class="pb">'+
   '<button class="back" data-back>← '+nm(m)+'</button>'+
   '<div class="si"><h3>SI summary · sample text</h3>Relevance for '+SCEN[S.scen].n+': <b>'+s+' / 100</b>. '+why(v)+'</div>'+
   '<dl class="kv"><dt>Objective</dt><dd>'+v.obj+'</dd><dt>Focus</dt><dd><span class="dot" style="background:'+AX[v.ax].c+'"></span>'+AX[v.ax].n+'</dd><dt>Fuel</dt><dd>'+v.fuel+'</dd><dt>Variables</dt><dd>'+v.cond+'</dd><dt>Hardware</dt><dd>'+v.hw+'</dd><dt>Platform</dt><dd>'+v.plat+'</dd></dl>'+
   '<div><div class="sec">Citation</div><div class="cite">'+v.cite+'</div></div>'+
   '<a class="link" href="'+v.url+'" target="_blank" rel="noopener">Open in the PSI repository</a></div>'}
 else{const list=ranked(v=>m.f(v)&&(!S.filt||v.ax===S.filt)),axs=Array.from(new Set(INV.filter(m.f).map(v=>v.ax)));
  p.innerHTML='<div class="ph"><div><h2>'+nm(m)+'</h2><p>'+m.s+' · ranked for '+SCEN[S.scen].n+'</p></div><button class="x" data-close aria-label="Hide this panel">×</button></div><div class="pb">'+
   (axs.length>1?'<div class="filters">'+axs.map(a=>'<button data-f="'+a+'" aria-pressed="'+(S.filt===a)+'"><span class="dot" style="background:'+AX[a].c+'"></span>'+AX[a].n+'</button>').join('')+'</div>':'')+
   list.map(card).join('')+'<div class="note">Scores are illustrative. The real ranking comes from the SI pipeline over PSI records.</div></div>'}
 p.classList.add('open');app.classList.add('has-panel')}
const fade=v=>{$('#fade').style.opacity=v};
/* go inside a module: fly at it, dip to black, open on its room */
function enterRoom(id){const m=modOf(id);if(!m||busy||state!=='hub')return;busy=true;app.classList.add('going');S.mod=id;S.inv=null;S.filt=null;S.side=false;drawTags();const w=app.clientWidth,h=app.clientHeight,q=mpos(id,w,h);
 if(LIVE){const p=view==='iss'&&anchorPos(id);if(p){lookT.copy(p);camT.copy(P2).sub(p).normalize().multiplyScalar(9).add(p)}else if(view!=='iss')dive={c:view==='moon'?mbCam:ebCam,p:new V().fromArray((view==='moon'?ANCHM:ANCHE)[id]),t0:performance.now()}}
 else if(q){seq.style.transformOrigin=q[0]+'px '+q[1]+'px';seq.style.transition='transform .8s cubic-bezier(.5,0,.9,.5)';seq.style.transform='scale(3.2)'}
 setTimeout(()=>fade(1),430);
 setTimeout(()=>{state='inside';tin=performance.now();yaw=pitch=0;app.classList.add('inside');$('#inbar').hidden=false;drawSwi();dive=null;
  showRoom(id);if(!LIVE){lastKey='';seq.style.transition='none';seq.style.transformOrigin='50% 50%';seq.style.transform='scale(1.14)';requestAnimationFrame(()=>requestAnimationFrame(()=>{seq.style.transition='transform 1.9s cubic-bezier(.2,.7,.2,1)';seq.style.transform='none'}))}
  drawPanel();drawPars();fade(0);busy=false},800)}
function leaveRoom(){prediction.close();app.classList.remove('going');state='hub';S.mod=null;S.inv=null;app.classList.remove('inside');$('#inbar').hidden=true;dive=null;drawPanel();drawPars();drawTags();
 if(LIVE){cam.position.copy(P2);look.copy(ST);camT.copy(P2);lookT.copy(ST)}else{lastKey='';seq.style.transition='none';seq.style.transform='none'}}
function exitRoom(){if(busy||state!=='inside')return;busy=true;fade(1);setTimeout(()=>{leaveRoom();fade(0);busy=false},380)}
function drawSwi(){$('#back').innerHTML='<span class="ba" aria-hidden="true">←</span><span class="bt"><small>Back to</small><b>'+BACK[S.scen].replace(/^the /,'').replace(/^./,c=>c.toUpperCase())+'</b></span>';$('#swi').innerHTML=MODS.map(m=>'<button class="sw" data-go="'+m.id+'" style="--c:'+m.c+'" aria-pressed="'+(S.mod===m.id)+'" aria-label="'+nm(m)+'"><img src="rooms/v_'+m.id+sfx()+'.jpg" alt=""><span class="sl"><b>'+TH[m.id]+'</b><small>'+PLACE[S.scen][m.id]+'</small></span></button>').join('')}
/* hop straight from one room to another */
function switchRoom(id){if(busy||state!=='inside'||id===S.mod||!modOf(id))return;busy=true;fade(1);setTimeout(()=>{S.mod=id;S.inv=null;S.filt=null;tin=performance.now();yaw=pitch=0;showRoom(id);if(!LIVE)lastKey='';drawPanel();drawPars();drawSwi();fade(0);busy=false},380)}
function drawTray(){const t=$('#tray'),n=S.cmp.size;t.hidden=n<2;t.innerHTML=n+' selected <button data-open-cmp>Compare</button>'}
function drawSheet(){const vs=INV.filter(v=>S.cmp.has(v.id)),rows=[['Focus',v=>AX[v.ax].n],['Fuel',v=>v.fuel],['Variables',v=>v.cond],['Hardware',v=>v.hw],['Platform',v=>v.plat],['Relevance · '+SCEN[S.scen].n,v=>score(v,S.scen)+' / 100']];
 $('#sheet').innerHTML='<div class="box"><div style="display:flex;align-items:center;gap:10px"><h2 style="margin:0;font-size:16px">Side by side</h2><button class="ghost" style="margin-left:auto" data-close-cmp>Close</button></div><div class="tw" style="margin-top:10px"><table><thead><tr><th></th>'+vs.map(v=>'<th>'+v.id+'</th>').join('')+'</tr></thead><tbody>'+
  rows.map(r=>'<tr><th>'+r[0]+'</th>'+vs.map(v=>'<td>'+r[1](v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div></div>';$('#sheet').hidden=false}
app.addEventListener('click',e=>{const t=e.target.closest('button,a,input');if(!t)return;const d=t.dataset;
 if(d.s)setEnv(d.s)
 else if(d.go)switchRoom(d.go)
 else if(d.id){if(matchMedia('(hover: none)').matches&&!t.classList.contains('open')){document.querySelectorAll('.mk.open').forEach(x=>x.classList.remove('open'));t.classList.add('open')}else enterRoom(d.id)}
 else if(d.inv){S.inv=d.inv;drawPanel()}
 else if('back' in d){S.inv=null;drawPanel()}
 else if('close' in d){S.side=false;drawPanel()}
 else if(t.id==='ptab'){prediction.setPanelOpen(false);S.side=true;drawPanel()}
 else if(t.id==='back')exitRoom()
 else if(d.f){S.filt=S.filt===d.f?null:d.f;drawPanel()}
 else if(d.cmp){t.checked?S.cmp.add(d.cmp):S.cmp.delete(d.cmp);drawTray()}
 else if('openCmp' in d)drawSheet()
 else if('closeCmp' in d)$('#sheet').hidden=true});

/* ---------- intro ---------- */
function enter(fast){const L=$('#landing');L.classList.add('go');setTimeout(()=>{L.hidden=true},fast?0:600);
 if(fast||matchMedia('(prefers-reduced-motion:reduce)').matches){state='hub';t0=performance.now()-DUR;cam.position.copy(P2);look.copy(ST);camT.copy(P2);lookT.copy(ST);app.classList.remove('pre')}
 else{state='intro';t0=performance.now()}}
$('#ignite').addEventListener('click',()=>{if(ready&&state==='landing')enter(false)});
$('#replay').addEventListener('click',()=>{if(busy)return;if(state==='inside')leaveRoom();tr=null;view='iss';S.scen='iss';envDefaults();drawSeg();drawTags();app.classList.remove('going');state='landing';lastKey='';const L=$('#landing');L.hidden=false;app.classList.add('pre');requestAnimationFrame(()=>L.classList.remove('go'))});

drawSeg();drawTags();
if(LIVE){try{initLive();if(QS.has('early')){cam.aspect=16/9;for(const az of [15,45,80,-40]){cam.position.copy(P2);cam.fov=60;cam.updateProjectionMatrix();cam.lookAt(dirOf(az*RAD,-40*RAD).add(P2));R.render(scene,cam)}}}catch(e){$('#igl').textContent='3D error'}}else initSeq();
size();addEventListener('resize',size);addEventListener('resize',fitBar);RAF(frame);
}
