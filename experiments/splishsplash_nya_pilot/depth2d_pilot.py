"""Local comparison of two depth-averaged 2D jet layouts; not production CFD.

Run from repository root:
  streamlit run experiments/splishsplash_nya_pilot/depth2d_pilot.py --server.address 127.0.0.1 --server.port 8513
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import streamlit as st

from experiments.splishsplash_nya_pilot.depth2d_flow import (
    Flow2DInputs, _stations_at, load_nya, solve,
)
from experiments.splishsplash_nya_pilot.layout_screening import indicators
from experiments.riverflow_layout_metrics import classify_beach_core
from experiments.splishsplash_nya_pilot.scenario_store import (
    read_scenarios, record_from_settings, save_scenario, settings_from_record,
)


@st.cache_resource
def geometry():
    return load_nya()


@st.cache_resource(show_spinner="Resolviendo campo 2D y comprobando balance...")
def field(settings: Flow2DInputs):
    model, beach = geometry()
    return solve(settings, model=model, beach=beach)


def encoded(result: dict) -> dict:
    grid = result["grid"]
    polygon = grid["polygon"]
    return {"x": np.round(grid["x"], 3).tolist(),
            "y": np.round(grid["y"], 3).tolist(),
            "wet": grid["wet"].astype(int).tolist(),
            "u": np.round(result["u"], 5).tolist(),
            "v": np.round(result["v"], 5).tolist(),
            "boundary": [list(map(list, polygon.exterior.coords))] +
                        [list(map(list, ring.coords)) for ring in polygon.interiors],
            "pumps": result["pump_sites"],
            "mass": result["diagnostics"]["mass_error_max_m3_s_per_cell"]}


def drag_candidates(model, beach: tuple[int, ...]) -> list[list]:
    """Legal snap points, consistent with the layout's calm/current zoning."""
    zones = classify_beach_core(model.stations, beach, 15.0)
    selected = [(i, p) for i, p in enumerate(model.stations)
                if zones[i] == "current" and i % 4 == 0]
    chain = np.array([float(p["chainage_m"]) for _, p in selected])
    geometry = _stations_at(model, chain)
    candidates = []
    for n, s in enumerate(chain):
        offset = max(.5, float(geometry["width"][n]) / 2 - 1)
        for bank, sign in (("Interior", -1), ("Exterior", 1)):
            candidates.append([round(float(s), 1), bank,
                               round(float(geometry["x"][n] + sign * geometry["nx"][n] * offset), 3),
                               round(float(geometry["y"][n] + sign * geometry["ny"][n] * offset), 3)])
    return candidates


def validate_drag_move(index: int, chainage: float, bank: str, sites: list[dict],
                       candidates: list[list]) -> str | None:
    if not 0 <= index < len(sites) or bank not in ("Interior", "Exterior"):
        return "Bomba u orilla inválida."
    if not any(abs(s - chainage) < 1.0 and side == bank for s, side, *_ in candidates):
        return "La bomba debe quedar en una orilla permitida, fuera del núcleo ancho y calmado de la playa."
    for other, pump in enumerate(sites):
        if other == index or pump["bank"] != bank:
            continue
        distance = abs(chainage - float(pump["chainage_m"]))
        if min(distance, 536 - distance) < 12:
            return f"Muy cerca de la bomba {other + 1} en la misma orilla (mínimo exploratorio: 12 m)."
    return None


HTML = r"""
<div id="field2d">
  <div class="controls"><button id="play" type="button">Pausar</button>
    <label>Campo <select id="scenario"><option value="base">Ubicación inicial</option>
      <option value="moved">Bomba desplazada</option></select></label>
    <label>Colores <select id="colors"><option value="contrast">Contraste del escenario</option>
      <option value="absolute">Escala fija m/s</option></select></label>
    <label>Partículas <select id="particleCount"><option value="140">140</option>
      <option value="280">280</option><option value="420">420</option></select></label>
    <label>Ritmo visual <input id="pace" type="range" min="100" max="3000" step="100" value="1200"></label>
    <span id="paceValue">1200×</span>
    <button id="zoomIn" type="button">+</button><button id="zoomOut" type="button">−</button>
    <button id="reset" type="button">Ajustar vista</button></div>
  <canvas id="map" role="img" aria-label="Campo 2D de velocidad con vectores, bombas y partículas trazadoras"></canvas>
  <div id="dragHint" aria-live="polite"></div>
  <div class="legend" id="legend"></div>
  <div id="status" aria-live="polite"></div>
</div>
<style>
 #field2d{font:14px system-ui,sans-serif;color:#19324b}
 #field2d .controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:5px 0 10px}
 #field2d button,#field2d select{font:inherit;border:1px solid #a6bbca;border-radius:5px;background:white;padding:3px 7px;color:#19324b}
 #field2d label{display:flex;align-items:center;gap:6px}
 #field2d canvas{width:100%;height:620px;display:block;background:#fafcfe;border:1px solid #d4dce4;border-radius:6px;cursor:grab;touch-action:none}
 #field2d canvas.drag-pump{cursor:grabbing}
 #field2d canvas.hover-pump{cursor:move}
 #field2d canvas.pan-map{cursor:grabbing}
 #field2d #dragHint{min-height:24px;color:#62317b;font-weight:600}
 #field2d .legend{font-size:12px;margin-top:8px}
 #field2d #status{min-height:24px}
 @media(max-width:650px){#field2d canvas{height:480px}}
</style>
<script>
(() => {
 const data=__DATA__, root=document.getElementById('field2d'), canvas=root.querySelector('#map');
 const ctx=canvas.getContext('2d'), choice=root.querySelector('#scenario'),pace=root.querySelector('#pace');
 const colors=root.querySelector('#colors'), particleControl=root.querySelector('#particleCount');
 const legend=root.querySelector('#legend');
 let current=data.base, running=true, last=performance.now(), particles=[], w=0,h=0,k=1,ox=0,oy=0;
 let candidateCells=[],seedCursor=0,restarts=0,hotspots=[];
 let zoom=data.view?.zoom||1,panX=data.view?.panX||0,panY=data.view?.panY||0,drag=null;
 const dragMode=data.variantLabel==='Arrastre de bombas';
 const dragHint=root.querySelector('#dragHint');
 const dx=current.x[1]-current.x[0], nx=current.x.length,ny=current.y.length;
 particleControl.value=String(data.particleCount||280);
 root.querySelector('#scenario option[value="moved"]').textContent=data.variantLabel;
 if(dragMode){choice.value='moved';current=data.moved;
   dragHint.textContent='Arrastra un diamante morado para recolocar esa bomba. Arrastra el fondo para mover el mapa.'}
 function resize(){const r=canvas.getBoundingClientRect(),pr=window.devicePixelRatio||1;w=r.width;h=r.height;
   canvas.width=Math.round(w*pr);canvas.height=Math.round(h*pr);ctx.setTransform(pr,0,0,pr,0,0);
   k=zoom*Math.min((w-30)/(current.x[nx-1]-current.x[0]),(h-30)/(current.y[ny-1]-current.y[0]));
   ox=(w-k*(current.x[nx-1]-current.x[0]))/2+panX;
   oy=(h-k*(current.y[ny-1]-current.y[0]))/2-panY;}
 new ResizeObserver(resize).observe(canvas);resize();
 function xy(x,y){return [ox+(x-current.x[0])*k,h-oy-(y-current.y[0])*k]}
 function canvasPoint(e){const rect=canvas.getBoundingClientRect();return [e.clientX-rect.left,e.clientY-rect.top]}
 function hitPump(px,py){let best=-1,dist=13;
   for(let i=0;i<current.pumps.length;i++){
     const p=xy(...current.pumps[i].out_xy),d=Math.hypot(px-p[0],py-p[1]);
     if(d<dist){best=i;dist=d}}
   return best}
 function targetAt(px,py){let best=null,dist=40;
   for(const candidate of data.candidates){const point=xy(candidate[2],candidate[3]);
     const d=Math.hypot(px-point[0],py-point[1]);if(d<dist){best=candidate;dist=d}}
   return best}
 function dragIssue(index,target){if(!target)return 'Suelta la bomba cerca de una orilla con corriente, fuera del núcleo calmado de la playa.';
   const chain=target[0],bank=target[1];
   for(let i=0;i<current.pumps.length;i++){if(i===index||current.pumps[i].bank!==bank)continue;
     const d=Math.abs(chain-current.pumps[i].chainage_m);
     if(Math.min(d,536-d)<12)return `A menos de 12 m de la bomba ${i+1} en la misma orilla.`}
   return null}
 function maximum(){let v=0;for(let j=0;j<ny;j++)for(let i=0;i<nx;i++)if(current.wet[j][i])v=Math.max(v,Math.hypot(current.u[j][i],current.v[j][i]));return v}
 function mix(a,b,t){return Math.round(a+(b-a)*t)}
 function speedColor(s,max){const t=Math.max(0,Math.min(1,s/(colors.value==='contrast'?Math.max(max,.001):.5)));
   const stops=[[34,71,120],[47,155,191],[95,192,145],[244,202,78],[215,85,55]];
   const q=Math.min(3.999,t*4),p=Math.floor(q),f=q-p;
   return `rgb(${mix(stops[p][0],stops[p+1][0],f)},${mix(stops[p][1],stops[p+1][1],f)},${mix(stops[p][2],stops[p+1][2],f)})`}
 function updateLegend(){const max=maximum();legend.textContent=colors.value==='contrast'?
   `Colores relativos: azul = menor rapidez, rojo = mayor rapidez en ESTE escenario (máximo ${max.toFixed(3)} m/s). No son bandas de seguridad. ◆ descarga · × toma. Arrastra para mover, rueda o +/− para zoom.`:
   'Escala fija: azul 0,00 · turquesa 0,125 · verde 0,25 · amarillo 0,375 · rojo ≥0,50 m/s. ◆ descarga · × toma. Arrastra para mover, rueda o +/− para zoom.'}
 function wetAt(x,y){const i=Math.round((x-current.x[0])/dx),j=Math.round((y-current.y[0])/dx);
   return i>=0&&j>=0&&i<nx&&j<ny&&Boolean(current.wet[j][i])}
 function sample(x,y){if(!wetAt(x,y))return null;
   const fx=(x-current.x[0])/dx,fy=(y-current.y[0])/dx,i=Math.floor(fx),j=Math.floor(fy);
   let u=0,v=0,total=0;
   for(let dj=0;dj<=1;dj++)for(let di=0;di<=1;di++){
     const ii=i+di,jj=j+dj;if(ii<0||jj<0||ii>=nx||jj>=ny||!current.wet[jj][ii])continue;
     const weight=(di?fx-i:1-fx)*(dj?fy-j:1-fy);
     u+=weight*current.u[jj][ii];v+=weight*current.v[jj][ii];total+=weight}
   return total>0?[u/total,v/total]:null}
 function seed(n){candidateCells=[];for(let j=0;j<ny;j++)for(let i=0;i<nx;i++)if(current.wet[j][i])candidateCells.push([i,j]);
   particles=[];restarts=0;hotspots=[];seedCursor=19;
   for(let a=0;a<n;a++){const cell=candidateCells[(a*97+19)%candidateCells.length];
     const x=current.x[cell[0]],y=current.y[cell[1]];
     particles.push({x,y,trail:[[x,y]],moving:false,blocked:false,stillFrames:0})}}
 function restart(p){hotspots.push({x:p.x,y:p.y,life:180});if(hotspots.length>40)hotspots.shift();
   for(let tries=0;tries<candidateCells.length;tries++){
     seedCursor=(seedCursor+73)%candidateCells.length;
     const cell=candidateCells[seedCursor],x=current.x[cell[0]],y=current.y[cell[1]];
     const q=sample(x,y);if(q&&Math.hypot(q[0],q[1])>.003){
       p.x=x;p.y=y;p.trail=[[x,y]];p.blocked=false;p.moving=true;p.stillFrames=0;restarts++;return}}
   p.stillFrames=0}
 seed(Number(particleControl.value));
 function outline(){ctx.beginPath();for(const ring of current.boundary){ring.forEach((p,i)=>{const [x,y]=xy(p[0],p[1]);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.closePath()}}
 function bankTangent(x,y){let best=Infinity,tx=0,ty=0;
   for(const ring of current.boundary)for(let i=1;i<ring.length;i++){
     const a=ring[i-1],b=ring[i],vx=b[0]-a[0],vy=b[1]-a[1],len2=vx*vx+vy*vy;
     if(len2<1e-9)continue;
     const t=Math.max(0,Math.min(1,((x-a[0])*vx+(y-a[1])*vy)/len2));
     const ex=x-a[0]-t*vx,ey=y-a[1]-t*vy,d2=ex*ex+ey*ey;
     if(d2<best){best=d2;const len=Math.sqrt(len2);tx=vx/len;ty=vy/len}}
   return [tx,ty]}
 function draw(){ctx.clearRect(0,0,w,h);ctx.save();outline();ctx.clip('evenodd');
  ctx.fillStyle='#e9f4f7';ctx.fillRect(0,0,w,h);
  const sdx=dx*k;
  const max=maximum();
  for(let j=0;j<ny;j++)for(let i=0;i<nx;i++)if(current.wet[j][i]){
    const [x,y]=xy(current.x[i],current.y[j]),u=current.u[j][i],v=current.v[j][i];
    ctx.fillStyle=speedColor(Math.hypot(u,v),max);ctx.fillRect(x-sdx/2,y-sdx/2,sdx+0.5,sdx+0.5);
  }
  ctx.strokeStyle='#21394b';ctx.fillStyle='#21394b';ctx.lineWidth=1;
  for(let j=2;j<ny;j+=4)for(let i=2;i<nx;i+=4)if(current.wet[j][i]){
    const u=current.u[j][i],v=current.v[j][i],m=Math.hypot(u,v);if(m<.008)continue;
    const [x,y]=xy(current.x[i],current.y[j]);const len=Math.min(11,3+45*m);
    const ex=x+u/m*len,ey=y-v/m*len;
    ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(ex,ey);ctx.stroke();
    ctx.beginPath();ctx.arc(ex,ey,1.6,0,Math.PI*2);ctx.fill();
  }
  ctx.restore();outline();ctx.strokeStyle='#163e54';ctx.lineWidth=2.5;ctx.lineJoin='round';ctx.stroke();
  for(let index=0;index<current.pumps.length;index++){const p=current.pumps[index];
    const [x,y]=xy(p.out_xy[0],p.out_xy[1]);ctx.fillStyle='#a31967';ctx.beginPath();ctx.moveTo(x,y-5);ctx.lineTo(x+5,y);ctx.lineTo(x,y+5);ctx.lineTo(x-5,y);ctx.closePath();ctx.fill();
    if(choice.value==='moved'&&data.changed.includes(index)){
      ctx.strokeStyle='#621b9a';ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,9,0,Math.PI*2);ctx.stroke();
      ctx.fillStyle='#401263';ctx.font='bold 12px system-ui';ctx.fillText(String(index+1),x+9,y-7)}
    const q=xy(p.in_xy[0],p.in_xy[1]);ctx.strokeStyle='#a31967';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(q[0]-3,q[1]-3);ctx.lineTo(q[0]+3,q[1]+3);ctx.moveTo(q[0]+3,q[1]-3);ctx.lineTo(q[0]-3,q[1]+3);ctx.stroke()}
  if(drag?.mode==='pump'&&drag.target){const p=xy(drag.target[2],drag.target[3]);
    ctx.strokeStyle=drag.issue?'#c03232':'#621b9a';ctx.fillStyle=drag.issue?'#c03232':'#621b9a';
    ctx.lineWidth=2.5;ctx.beginPath();ctx.arc(p[0],p[1],12,0,Math.PI*2);ctx.stroke();
    ctx.font='bold 13px system-ui';ctx.fillText(String(drag.index+1),p[0]+13,p[1]-8)}
  for(const spot of hotspots){const [x,y]=xy(spot.x,spot.y);ctx.strokeStyle=`rgba(232,122,28,${spot.life/240})`;ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.stroke()}
  for(const p of particles){if(p.trail.length>1){ctx.beginPath();p.trail.forEach((q,i)=>{const a=xy(q[0],q[1]);if(i===0)ctx.moveTo(a[0],a[1]);else ctx.lineTo(a[0],a[1])});ctx.strokeStyle='rgba(255,255,255,.85)';ctx.lineWidth=2;ctx.stroke()}}
  for(const p of particles){const [x,y]=xy(p.x,p.y);ctx.fillStyle=p.blocked?'#ffd47a':'#fff';ctx.strokeStyle='#102b44';ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(x,y,3.5,0,Math.PI*2);ctx.fill();ctx.stroke()}
  if(dragMode)for(let index=0;index<current.pumps.length;index++){
    const p=current.pumps[index],point=xy(...p.out_xy);
    ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(point[0],point[1],8,0,Math.PI*2);ctx.fill();
    ctx.strokeStyle='#5d187b';ctx.lineWidth=2;ctx.stroke();
    ctx.fillStyle='#7d1a95';ctx.beginPath();ctx.moveTo(point[0],point[1]-5);
    ctx.lineTo(point[0]+5,point[1]);ctx.lineTo(point[0],point[1]+5);
    ctx.lineTo(point[0]-5,point[1]);ctx.closePath();ctx.fill();
    ctx.fillStyle='#4b0c63';ctx.font='bold 11px system-ui';ctx.fillText(String(index+1),point[0]+8,point[1]-7)}
 }
 // Pump markers use coordinates exported from the Python geometry.
 function advance(p,dt){let remaining=dt,moved=0;p.blocked=false;
   for(let n=0;n<200&&remaining>1e-6;n++){
     const q=sample(p.x,p.y);if(!q){p.blocked=true;break}
     const speed=Math.hypot(q[0],q[1]);if(speed<.0005)break;
     const step=Math.min(remaining,dx*.25/speed);
     const mid=sample(p.x+q[0]*step/2,p.y+q[1]*step/2)||q;
     const sx=mid[0]*step,sy=mid[1]*step;
     if(wetAt(p.x+sx,p.y+sy)){p.x+=sx;p.y+=sy;moved+=Math.hypot(sx,sy)}
     else if(wetAt(p.x+sx,p.y)){p.x+=sx;moved+=Math.abs(sx)}
     else if(wetAt(p.x,p.y+sy)){p.y+=sy;moved+=Math.abs(sy)}
     else {const tangent=bankTangent(p.x,p.y),along=(mid[0]*tangent[0]+mid[1]*tangent[1])*step;
       let slid=false;
       for(const fraction of [1,.5,.25]){
         const sx=tangent[0]*along*fraction,sy=tangent[1]*along*fraction;
         if(Math.hypot(sx,sy)>.001&&wetAt(p.x+sx,p.y+sy)){
           p.x+=sx;p.y+=sy;moved+=Math.hypot(sx,sy);slid=true;break}}
       if(!slid){p.blocked=true;break}}
     remaining-=step}
   p.moving=moved>.02;
   if(p.moving){p.trail.push([p.x,p.y]);if(p.trail.length>7)p.trail.shift()}}
 let frameNumber=0,alive=true;
 function status(){const moving=particles.filter(p=>p.moving).length,blocked=particles.filter(p=>p.blocked).length;
   root.querySelector('#status').textContent=`${particles.length} trazadores visibles · ${moving} avanzan ahora · ${blocked} tocan el borde · ${restarts} reinicios visuales acumulados. Los círculos ámbar marcan bloqueo reciente. Reiniciar un trazador NO significa que completó la vuelta. ${running?'':'Animación pausada.'}`}
 function frame(now){const dt=Math.min(.033,(now-last)/1000)*Number(pace.value);last=now;
   if(running){for(const p of particles){advance(p,dt);p.stillFrames=p.moving?0:p.stillFrames+1;
     if(p.stillFrames>90)restart(p)}
     for(const spot of hotspots)spot.life--;hotspots=hotspots.filter(spot=>spot.life>0)}
   draw();if(++frameNumber%20===0)status();if(alive)requestAnimationFrame(frame)}
 root.querySelector('#play').onclick=()=>{running=!running;root.querySelector('#play').textContent=running?'Pausar':'Continuar'};
 choice.onchange=()=>{current=data[choice.value];seed(Number(particleControl.value));resize();updateLegend();status()};
 colors.onchange=updateLegend;
 particleControl.onchange=()=>{seed(Number(particleControl.value));status()};
 root.querySelector('#zoomIn').onclick=()=>{zoom=Math.min(8,zoom*1.3);resize()};
 root.querySelector('#zoomOut').onclick=()=>{zoom=Math.max(.7,zoom/1.3);resize()};
 root.querySelector('#reset').onclick=()=>{zoom=1;panX=0;panY=0;resize()};
 canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.7,Math.min(8,zoom*(e.deltaY<0?1.12:1/1.12)));resize()},{passive:false});
 canvas.addEventListener('pointerdown',e=>{const [px,py]=canvasPoint(e);
   const index=dragMode?hitPump(px,py):-1;
   drag=index>=0?{mode:'pump',index,target:null,issue:null}:{mode:'pan',x:e.clientX,y:e.clientY};
   canvas.classList.toggle('drag-pump',index>=0);canvas.classList.toggle('pan-map',index<0);
   canvas.setPointerCapture(e.pointerId)});
 canvas.addEventListener('pointermove',e=>{const [px,py]=canvasPoint(e);
   if(!drag){canvas.classList.toggle('hover-pump',dragMode&&hitPump(px,py)>=0);return}
   if(drag.mode==='pan'){panX+=e.clientX-drag.x;panY+=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;resize();return}
   drag.target=targetAt(px,py);drag.issue=dragIssue(drag.index,drag.target);
   dragHint.textContent=drag.target?`Bomba ${drag.index+1} → ${drag.target[0].toFixed(1)} m · ${drag.target[1]}${drag.issue?' · '+drag.issue:' · soltar para recalcular'}`:drag.issue});
 canvas.addEventListener('pointerup',()=>{if(drag?.mode==='pump'){
     if(drag.target&&!drag.issue){dragHint.textContent='Recalculando la corriente...';
       __SEND_DROP__({id:Date.now(),index:drag.index,chainage:drag.target[0],bank:drag.target[1],
         particleCount:Number(particleControl.value),view:{zoom,panX,panY}})}
     else dragHint.textContent=drag.issue||'Posición no aceptada.'}
   drag=null;canvas.classList.remove('drag-pump','pan-map')});
 canvas.addEventListener('pointercancel',()=>{drag=null;canvas.classList.remove('drag-pump','pan-map')});
 pace.oninput=()=>root.querySelector('#paceValue').textContent=pace.value+'×';
 updateLegend();status();
 requestAnimationFrame(frame);
 return ()=>{alive=false};
})();
</script>
"""


COMPONENT_HTML = HTML.split("<style>", 1)[0]
COMPONENT_CSS = HTML.split("<style>", 1)[1].split("</style>", 1)[0]
COMPONENT_JS = (HTML.split("<script>", 1)[1].split("</script>", 1)[0]
                .replace("(() => {", "export default function(component) {", 1)
                .replace("const data=__DATA__, root=document.getElementById('field2d')",
                         "const data=component.data, root=component.parentElement.querySelector('#field2d')", 1)
                .replace("__SEND_DROP__(", "component.setTriggerValue('drop', ")
                .replace("})();", "}", 1))
def flow_component(**kwargs):
    # Register in the active Streamlit runtime. A module-level registration
    # can belong to another AppTest/session and fail when this sheet is embedded.
    component = st.components.v2.component(
        "nya_pump_drag_pilot", html=COMPONENT_HTML, css=COMPONENT_CSS, js=COMPONENT_JS)
    return component(**kwargs)


def pump_coordinates(model, result: dict) -> None:
    from experiments.splishsplash_nya_pilot.depth2d_flow import _stations_at
    for p in result["pump_sites"]:
        side = -1 if p["bank"] == "Interior" else 1
        for tag, s in (("out", p["chainage_m"]), ("in", p["intake_chainage_m"])):
            point = _stations_at(model, np.array([s]))
            offset = max(.5, point["width"][0] / 2 - 1)
            p[tag + "_xy"] = [float(point["x"][0] + side * point["nx"][0] * offset),
                                float(point["y"][0] + side * point["ny"][0] * offset)]


def metrics(result: dict) -> dict:
    wet = result["grid"]["wet"]
    speed = np.hypot(result["u"], result["v"])[wet]
    return {"mean": float(np.mean(speed)), "p95": float(np.percentile(speed, 95)),
            "slow_fraction": float(np.mean(speed < .05))}


def render_lab(*, embedded: bool = False) -> None:
    if not embedded:
        st.set_page_config(page_title="NYA · flujo 2D local", layout="wide")
        st.title("NYA · ensayo 2D de chorros y tomas")
    else:
        st.subheader("Mover bombas y observar la corriente · ensayo 2D")
        st.caption("Hoja independiente: usa el DXF de referencia y sus propios controles. "
                   "No modifica la ubicación ni los resultados del escenario principal.")
    st.caption("Campo 2D exploratorio sobre el DXF de 536 m. Arrastra una bomba, observa el cambio y compara los indicadores; las velocidades no están calibradas para compra ni seguridad.")
    with st.expander("Cómo se calcula y cómo leer el dibujo", expanded=not embedded):
        st.markdown("""1. **Caudal de cada bomba:** proviene de la curva Riverflow usada en el ensayo anterior. La toma retira ese mismo caudal y la descarga lo devuelve; así no se crea agua artificialmente.
2. **Impulso:** se aplica en la dirección elegida usando `fracción supuesta × caudal × velocidad teórica de salida`. Esa fracción NO es un dato del fabricante: es la incertidumbre principal.
3. **Corriente en el canal:** se resuelve el reparto de caudal entre celdas, con fricción de Manning equivalente del piso y las paredes y una mezcla lateral supuesta. El mapa muestra la **rapidez local**, las flechas su dirección y las partículas siguen el campo calculado. La animación acelerada no altera los números.

El borde oscuro sigue el **contorno DXF original**. ◆ es descarga y × es toma; sus lugares son conceptuales. Por defecto los colores **resaltan diferencias dentro del escenario**: rojo no significa peligro ni azul ausencia total de corriente. Puedes elegir escala fija en m/s. Mover una bomba cambia sus tomas y descarga, y se recalcula el campo completo. **No** están resueltos por separado los siete puertos, la trayectoria real de los chorros, la superficie libre ni la flotación de personas.""")
    if not embedded:
        with st.expander("Contraste local con SPlisHSPlasH · no valida 536 m"):
            root = Path(__file__).parent / "results"
            reports = [root / "sph_sections_mesh_oct14" / "summary.json",
                       root / "sph_sections_mesh_r020_thin_oct14" / "summary.json"]
            if all(path.exists() for path in reports):
                observations = [row for path in reports
                                for row in json.loads(path.read_text(encoding="utf-8"))]
                st.dataframe([{
                    "Tramo": row["section"], "Orilla": row["bank"],
                    "Radio partícula (m)": row["particle_radius_m"],
                    "Partículas": row["particle_count"],
                    "Avance 3–18 m aguas abajo (m/s)":
                        round(row["downstream_3_to_18_m"]["mean_along_m_s"], 4),
                } for row in observations], hide_index=True)
                st.warning("Estas escenas se resolvieron con la biblioteca real SPlisHSPlasH, "
                           "pero empiezan en reposo y tienen extremos cerrados. Al refinar el tamaño "
                           "de partícula cambia la orilla aparentemente favorable: el resultado "
                           "aún no converge y NO calibra este mapa ni selecciona bombas.")
            else:
                st.caption("No se encontraron los diagnósticos SPH locales; el mapa 2D no está validado.")
    model, beach = geometry()
    if embedded:
        scenarios = st.session_state.setdefault("depth2d_session_scenarios", {})
    else:
        try:
            scenarios = read_scenarios()
        except ValueError as exc:
            st.error(f"Escenarios guardados: {exc}")
            scenarios = {}
    with st.expander("Escenarios de ubicación guardados", expanded=bool(scenarios)):
        st.caption("En la app web se conservan durante esta sesión; descarga el JSON para "
                   "guardarlo y volver a importarlo. Al abrirlo se recalcula la corriente."
                   if embedded else
                   "Se guardan únicamente en este equipo los parámetros y las bombas movidas; "
                   "al abrir un escenario se vuelve a calcular la corriente.")
        if embedded:
            imported = st.file_uploader("Importar escenario JSON", type="json",
                                        key="depth2d_import_scenario")
            if imported is not None and st.button("Abrir archivo de escenario"):
                try:
                    record = json.loads(imported.getvalue().decode("utf-8"))
                    settings_from_record(record)
                    name = Path(imported.name).stem[:60]
                    if not name or name in scenarios:
                        raise ValueError("Nombre vacío o ya utilizado en esta sesión.")
                    scenarios[name] = record
                except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    st.error(f"No se pudo importar el escenario: {exc}")
                else:
                    st.session_state.loaded_scenario_notice = name
                    st.rerun()
            if scenarios:
                chosen_export = st.selectbox("Descargar escenario", list(scenarios),
                                             key="depth2d_export_choice")
                st.download_button("Descargar JSON", data=json.dumps(
                    scenarios[chosen_export], ensure_ascii=False, indent=2),
                    file_name=f"{chosen_export}.json", mime="application/json")
        if scenarios:
            selected_scenario = st.selectbox("Escenario", list(scenarios), key="depth2d_saved_choice")
            if st.button("Abrir escenario guardado"):
                try:
                    loaded = settings_from_record(scenarios[selected_scenario])
                    baseline = field(replace(loaded, site_overrides=()))
                    modified = field(loaded)
                    candidates = drag_candidates(model, beach)
                    for index, chainage, side in loaded.site_overrides:
                        issue = validate_drag_move(index, chainage, side,
                                                   modified["pump_sites"], candidates)
                        if issue:
                            raise ValueError(f"Bomba {index + 1}: {issue}")
                except ValueError as exc:
                    st.error(f"No se pudo abrir «{selected_scenario}»: {exc}")
                else:
                    st.session_state.depth2d_count = loaded.count
                    st.session_state.depth2d_coupling = round(loaded.momentum_fraction * 100)
                    st.session_state.depth2d_angle = int(loaded.nozzle_angle_deg)
                    st.session_state.depth2d_mixing = loaded.eddy_viscosity_m2_s
                    st.session_state.depth2d_floor_n = loaded.floor_manning_n
                    st.session_state.depth2d_wall_n = loaded.wall_manning_n
                    st.session_state.depth2d_comparison = "Arrastrar bombas en el mapa"
                    st.session_state.depth2d_results = (
                        baseline, modified, "Arrastrar bombas en el mapa", None)
                    st.session_state.drag_view = {}
                    st.session_state.drag_error = None
                    st.session_state.loaded_scenario_notice = selected_scenario
        else:
            st.write("Aún no hay escenarios guardados. Primero calcula y mueve las bombas en el mapa.")
    loaded_notice = st.session_state.pop("loaded_scenario_notice", None)
    if loaded_notice:
        st.success(f"Escenario «{loaded_notice}» abierto y recalculado.")
    saved_notice = st.session_state.pop("saved_scenario_notice", None)
    if saved_notice:
        st.success(f"Escenario «{saved_notice}» guardado en este equipo.")
    with st.form("scenario"):
        a, b, c, g = st.columns(4)
        count = a.selectbox("Bombas activas", [16, 20, 24, 28],
                            index=None if "depth2d_count" in st.session_state else 1,
                            key="depth2d_count")
        coupling = b.slider("Momento efectivo supuesto (%)", 5, 100,
                            value=None if "depth2d_coupling" in st.session_state else 10,
                            key="depth2d_coupling")
        angle = c.slider("Ángulo de todas las descargas (°)", -30, 30,
                         value=None if "depth2d_angle" in st.session_state else 0,
                         key="depth2d_angle")
        mixing = g.slider("Mezcla lateral supuesta (m²/s)", 0.02, 0.30,
                          value=None if "depth2d_mixing" in st.session_state else 0.08,
                          step=0.01,
                          key="depth2d_mixing")
        mn_floor, mn_wall = st.columns(2)
        floor_n = mn_floor.number_input("Manning n · piso liso (hipótesis)",
                                        min_value=0.005, max_value=0.100,
                                        value=None if "depth2d_floor_n" in st.session_state else 0.013,
                                        step=0.001, format="%.3f", key="depth2d_floor_n")
        wall_n = mn_wall.number_input("Manning n · paredes rugosas (hipótesis)",
                                      min_value=0.005, max_value=0.100,
                                      value=None if "depth2d_wall_n" in st.session_state else 0.025,
                                      step=0.001, format="%.3f", key="depth2d_wall_n")
        if embedded:
            comparison = "Arrastrar bombas en el mapa"
            chosen, chain, bank = 1, 52.0, "Exterior"
        else:
            comparison = st.selectbox("Variante para comparar",
                                      ["Mover una bomba manualmente",
                                       "Propuesta experimental de menor retorno · 20 bombas",
                                       "Cribado exploratorio · 24 bombas (sin validar por SPH)",
                                       "Arrastrar bombas en el mapa"],
                                      index=None if "depth2d_comparison" in st.session_state else 0,
                                      key="depth2d_comparison")
            d, e, f = st.columns(3)
            chosen = d.number_input("Índice de bomba a mover · solo modo manual", 1, count, 1)
            chain = e.number_input("Nueva progresiva (m) · solo modo manual", 0.0, 535.9, 52.0, 1.0)
            bank = f.selectbox("Nueva orilla · solo modo manual", ["Interior", "Exterior"], index=1)
        submitted = st.form_submit_button("Calcular ubicación inicial y variante")
    if not submitted and "depth2d_results" not in st.session_state:
        st.info("Pulsa **Calcular** para iniciar el ensayo local. Tarda algunos segundos.")
        return
    if submitted:
        base_settings = Flow2DInputs(count=count, momentum_fraction=coupling / 100,
                                     nozzle_angle_deg=angle,
                                     eddy_viscosity_m2_s=mixing,
                                     floor_manning_n=floor_n, wall_manning_n=wall_n)
        proposal_report = None
        if comparison.startswith("Propuesta") or comparison.startswith("Cribado"):
            report_count = 24 if comparison.startswith("Cribado") else 20
            if count != report_count:
                st.error(f"Esta propuesta se examinó solo con {report_count} bombas. Elige esa cantidad o usa el modo manual.")
                return
            report_path = (Path(__file__).parent / "results" /
                           ("nya_ubicacion_24_bombas_cribado_2d_manning_corregido.json"
                            if report_count == 24 else "nya_ubicacion_20_bombas_cribado_2d.json"))
            proposal_report = json.loads(report_path.read_text(encoding="utf-8"))
            moves = tuple((int(i), float(s), str(side)) for i, s, side in
                          proposal_report["settings"]["site_overrides"])
            moved_settings = replace(base_settings, site_overrides=moves)
        elif comparison.startswith("Arrastrar"):
            moved_settings = base_settings
            st.session_state.drag_view = {}
            st.session_state.drag_error = None
        else:
            moved_settings = replace(base_settings, moved_pump_index=chosen - 1,
                                      moved_chainage_m=chain, moved_bank=bank)
        try:
            baseline = field(base_settings)
            modified = field(moved_settings)
        except ValueError as exc:
            st.error(str(exc)); return
        st.session_state.depth2d_results = (baseline, modified, comparison,
                                           proposal_report)
    saved = st.session_state.depth2d_results
    if len(saved) == 2:
        baseline, modified = saved
        comparison, proposal_report = "Mover una bomba manualmente", None
    else:
        baseline, modified, comparison, proposal_report = saved
    pump_coordinates(model, baseline)
    pump_coordinates(model, modified)
    if comparison.startswith("Arrastrar"):
        st.info("**Edición directa:** acerca el mapa si lo necesitas y arrastra el diamante morado de una bomba. "
                "Al soltarlo, la posición se ajusta a una orilla válida y se recalculan la toma, descarga y corriente. "
                "Arrastrar fuera de los diamantes sigue moviendo el mapa. El botón Calcular reinicia el ensayo.")
        if st.session_state.get("drag_error"):
            st.warning(st.session_state.drag_error)
        if modified["settings"].site_overrides:
            st.dataframe([{
                "Bomba": i + 1,
                "Inicial": f"{baseline['pump_sites'][i]['chainage_m']:.1f} m · {baseline['pump_sites'][i]['bank']}",
                "Movida": f"{s:.1f} m · {side}",
            } for i, s, side in modified["settings"].site_overrides], hide_index=True)
        st.text_input("Nombre para guardar esta distribución", key="depth2d_new_scenario",
                      placeholder="Ej.: bombas en curvas y zonas anchas")
        if st.button("Guardar esta configuración"):
            try:
                name = st.session_state.depth2d_new_scenario.strip()
                if embedded:
                    if not 1 <= len(name) <= 60 or name in scenarios:
                        raise ValueError("Escribe un nombre nuevo de 1 a 60 caracteres.")
                    scenarios[name] = record_from_settings(modified["settings"])
                else:
                    save_scenario(name, modified["settings"])
            except (ValueError, OSError) as exc:
                st.error(str(exc))
            else:
                st.session_state.saved_scenario_notice = name
                st.rerun()
    bm, mm = metrics(baseline), metrics(modified)
    wet = baseline["grid"]["wet"]
    pointwise_change = np.hypot(modified["u"] - baseline["u"],
                                modified["v"] - baseline["v"])[wet]
    st.markdown(
        f"**Datos que entraron a este cálculo:** {baseline['settings'].count} bombas × "
        f"{baseline['reference']['pump_flow_each_m3_h']:.0f} m³/h por bomba; "
        f"salida agregada teórica {baseline['reference']['aggregate_nozzle_exit_speed_m_s']:.2f} m/s; "
        f"momento aplicado {baseline['settings'].momentum_fraction:.0%} del teórico; "
        f"Manning piso {baseline['settings'].floor_manning_n:.3f}, paredes {baseline['settings'].wall_manning_n:.3f}; "
        f"mezcla lateral supuesta {baseline['settings'].eddy_viscosity_m2_s:.2f} m²/s. "
        "El caudal que sale de cada bomba es exactamente el que entra por sus dos tomas. "
        "Estas entradas producen un campo de velocidad, **no** una distancia de alcance de chorro medida."
    )
    st.error("Los dos modelos exploratorios aún discrepan: la estimación previa por secciones da "
             f"{baseline['reference']['actual_typical_passage_speed_m_s']:.3f} m/s típicos de paso, "
             f"mientras este campo 2D da {bm['mean']:.3f} m/s de rapidez media espacial. "
             "No son la misma métrica ni están calibrados; ninguno confirma el número de bombas.")
    cols = st.columns(4)
    cols[0].metric("Rapidez media 2D · hipótesis", f"{bm['mean']:.3f} → {mm['mean']:.3f} m/s")
    cols[1].metric("Corriente media en sentido de vuelta", f"{baseline['diagnostics']['mean_along_channel_m_s']:.3f} → {modified['diagnostics']['mean_along_channel_m_s']:.3f} m/s")
    cols[2].metric("Área con <0,05 m/s", f"{bm['slow_fraction']:.1%} → {mm['slow_fraction']:.1%}")
    cols[3].metric("Área con retorno local", f"{baseline['diagnostics']['area_fraction_reverse_flow']:.1%} → {modified['diagnostics']['area_fraction_reverse_flow']:.1%}")
    if proposal_report is not None:
        before, after = indicators(baseline), indicators(modified)
        st.metric("Rotación horizontal 2D · indicador, no turbulencia real",
                  f"{before['core_rotation_rms_s_1']:.4f} → {after['core_rotation_rms_s_1']:.4f} s⁻¹")
        st.dataframe([{
            "Bomba": move["pump_number"],
            "Ubicación inicial": f"{move['from_chainage_m']:.1f} m · {move['from_bank']}",
            "Ubicación ensayada": f"{move['to_chainage_m']:.1f} m · {move['to_bank']}",
        } for move in proposal_report["accepted_moves"]], hide_index=True)
        st.warning(f"La propuesta cambia {len(proposal_report['accepted_moves'])} de las {proposal_report['count']} ubicaciones; "
                   "fue elegida con un modelo 2D no calibrado y supuestos de momento/mezcla. "
                   "La rotación calculada no es turbulencia 3D ni demuestra ausencia de remolinos. "
                   "Las pruebas locales en SPlisHSPlasH NO convergieron al comparar dos tamaños de partícula; "
                   "por eso no validan estas posiciones ni justifican compras. "
                   "Se mantiene el mismo caudal por unidad: este ensayo no recalcula pérdidas de tubería ni la curva de bomba tras moverla.")
    st.caption("Al mover la bomba, cambio medio del vector de corriente en las celdas: "
               f"{np.mean(pointwise_change):.4f} m/s; cambio local máximo: "
               f"{np.max(pointwise_change):.4f} m/s. Son respuestas de esta hipótesis, no mediciones de NYA.")
    changed = ([move[0] for move in modified["settings"].site_overrides]
               if comparison.startswith("Arrastrar") or proposal_report is not None
               else [modified["settings"].moved_pump_index])
    st.caption("El control **Partículas** está dentro del mapa (140, 280 o 420). "
               "Aumenta los puntos visibles, pero puede ralentizar el dibujo; "
               "no cambia el caudal, la velocidad calculada ni la precisión física.")
    payload = {"base": encoded(baseline), "moved": encoded(modified),
               "variantLabel": ("Arrastre de bombas" if comparison.startswith("Arrastrar")
                                else f"Cribado {proposal_report['count']} bombas" if proposal_report is not None
                                else "Bomba desplazada"),
               "changed": changed,
               "particleCount": st.session_state.get("depth2d_particle_count", 280),
               "candidates": drag_candidates(model, beach) if comparison.startswith("Arrastrar") else [],
               "view": st.session_state.get("drag_view", {})}
    component_result = flow_component(data=payload, on_drop_change=lambda: None,
                                      key="nya_flow_map")
    drop = getattr(component_result, "drop", None)
    if comparison.startswith("Arrastrar") and drop and drop.get("id") != st.session_state.get("last_drag_id"):
        st.session_state.last_drag_id = drop["id"]
        if drop.get("particleCount") in (140, 280, 420):
            st.session_state.depth2d_particle_count = drop["particleCount"]
        index, chainage, side = int(drop["index"]), float(drop["chainage"]), str(drop["bank"])
        issue = validate_drag_move(index, chainage, side, modified["pump_sites"], payload["candidates"])
        if issue:
            st.session_state.drag_error = issue
        else:
            overrides = {i: (s, b) for i, s, b in modified["settings"].site_overrides}
            overrides[index] = (chainage, side)
            settings = replace(modified["settings"],
                               site_overrides=tuple((i, s, b) for i, (s, b) in sorted(overrides.items())))
            try:
                updated = field(settings)
            except ValueError as exc:
                st.session_state.drag_error = str(exc)
            else:
                st.session_state.depth2d_results = (baseline, updated, comparison, None)
                st.session_state.drag_view = drop.get("view", {})
                st.session_state.drag_error = None
        st.rerun()
    st.warning("Este piloto calcula un campo bidimensional con tapa rígida y mezcla turbulenta efectiva supuesta. "
               "Los trazadores siguen ese campo y el ritmo visual está acelerado; cuando uno se atasca, "
               "se marca el punto y se reinicia visualmente para mantener la animación. Ese reinicio no es "
               "transporte físico ni una vuelta completada. No resuelve los siete puertos "
               "individuales, la superficie libre, la flotación de personas ni la longitud real del chorro. "
               "El porcentaje de momento no está medido; no usar las velocidades absolutas para compras o seguridad.")
    st.write("Malla:", baseline["diagnostics"]["wet_cells"], "celdas mojadas de 2 m; "
             "volumen discretizado aproximado",
             f"{baseline['diagnostics']['volume_m3_raster']:.0f} m³. "
             "Error máximo de balance por celda:",
             f"{max(baseline['diagnostics']['mass_error_max_m3_s_per_cell'], modified['diagnostics']['mass_error_max_m3_s_per_cell']):.1e} m³/s.")


def main() -> None:
    render_lab()


if __name__ == "__main__":
    main()
