"""Export a geometry-only Riverflow route animation for the widened NYA DXF."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.orchestrator import LazyRiverModel  # noqa: E402
from core.riverflow_supplier_photo import ASSETS, load_supplier_photo  # noqa: E402


HTML = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font:14px system-ui,-apple-system,Segoe UI,sans-serif;color:#17324d;margin:0;background:white}
.wrap{max-width:1180px;margin:auto;padding:8px 12px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
button{border:1px solid #9bb8d4;background:white;border-radius:6px;padding:6px 12px;cursor:pointer;color:#17324d}
button:hover{background:#eaf5ff}input{vertical-align:middle}
.note{color:#52677c;font-size:12px;margin:3px 0 10px}
canvas{display:block;width:100%;height:660px;border:1px solid #d8e6f0;border-radius:8px;touch-action:none;cursor:grab}
canvas.drag{cursor:grabbing}
</style></head><body><div class="wrap">
<div class="bar"><strong>Recorrido Riverflow · 20 sectores aproximados</strong>
<button id="toggle">Pausar</button><button id="reset">Restablecer vista</button>
<label>Reproducción <input id="speed" type="range" min="0.5" max="3" value="1" step="0.25"></label>
<span id="speedLabel">1×</span></div>
<div class="note">Puntos azules: trazadores visuales sobre el DXF, en sentido antihorario. Círculos naranja: sectores del plano Riverflow. Arrastre para desplazar; rueda para ampliar. La reproducción no representa velocidades CFD, chorros ni tiempo real de vuelta.</div>
<canvas id="river"></canvas></div>
<script>
const data=__PAYLOAD__;
const canvas=document.getElementById('river'), ctx=canvas.getContext('2d');
const toggle=document.getElementById('toggle'), reset=document.getElementById('reset');
const speed=document.getElementById('speed'), speedLabel=document.getElementById('speedLabel');
let width=0,height=0,zoom=1,panX=0,panY=0,playing=true,phase=0,last=0,drag=null;
const box=data.bounds, cx=(box[0]+box[2])/2, cy=(box[1]+box[3])/2;
let base=1;
function resize(){const rect=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
  width=rect.width;height=rect.height;canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
  ctx.setTransform(dpr,0,0,dpr,0,0);base=Math.min((width-65)/(box[2]-box[0]),(height-45)/(box[3]-box[1]));draw();}
function screen(p){return [width/2+(p[0]-cx)*base*zoom+panX,height/2-(p[1]-cy)*base*zoom+panY]}
function path(points){ctx.beginPath();points.forEach((p,i)=>{const q=screen(p);if(i)ctx.lineTo(q[0],q[1]);else ctx.moveTo(q[0],q[1])});ctx.closePath()}
function sample(s){const route=data.center, L=data.length; s=((s%L)+L)%L;
  let lo=0,hi=route.length-1;while(lo+1<hi){const mid=(lo+hi)>>1;if(route[mid][0]<=s)lo=mid;else hi=mid}
  const a=route[lo],b=route[hi],t=(s-a[0])/(b[0]-a[0]||1);
  const x=a[1]+t*(b[1]-a[1]),y=a[2]+t*(b[2]-a[2]),w=a[3]+t*(b[3]-a[3]);
  const dx=b[1]-a[1],dy=b[2]-a[2],norm=Math.hypot(dx,dy)||1;
  return [x,y,w,-dy/norm,dx/norm]}
function draw(){if(!width)return;ctx.clearRect(0,0,width,height);ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);
  path(data.outer);ctx.fillStyle='#d8f3ff';ctx.fill();ctx.strokeStyle='#2c5269';ctx.lineWidth=2;ctx.stroke();
  path(data.inner);ctx.fillStyle='white';ctx.fill();ctx.stroke();
  ctx.save();ctx.beginPath();for(const poly of [data.outer,data.inner]){poly.forEach((p,i)=>{const q=screen(p);if(i)ctx.lineTo(q[0],q[1]);else ctx.moveTo(q[0],q[1])});ctx.closePath()}ctx.clip('evenodd');
  for(let i=0;i<145;i++){const s=(phase+i*data.length/145)%data.length,v=sample(s);
    const lane=((i%5)-2)*0.06*v[2],q=screen([v[0]+v[3]*lane,v[1]+v[4]*lane]);
    ctx.beginPath();ctx.arc(q[0],q[1],Math.max(1.7,2.5*zoom**0.3),0,Math.PI*2);
    ctx.fillStyle=i%7===0?'#087ba4':'#3da8c9';ctx.fill()}
  ctx.restore();
  for(const item of data.pumps){const p=sample(item[1]);
    const bankOffset=(item[2]==='Exterior'?-0.35:0.35)*p[2];
    const q=screen([p[0]+p[3]*bankOffset,p[1]+p[4]*bankOffset]);
    ctx.beginPath();ctx.arc(q[0],q[1],5.5,0,Math.PI*2);ctx.fillStyle='#ea580c';ctx.fill();
    ctx.strokeStyle='white';ctx.lineWidth=1.5;ctx.stroke();
    ctx.font='bold 12px system-ui';ctx.lineWidth=3;ctx.strokeStyle='white';ctx.strokeText(String(item[0]),q[0]+7,q[1]-7);
    ctx.fillStyle='#713f12';ctx.fillText(String(item[0]),q[0]+7,q[1]-7)}
  ctx.fillStyle='#36536c';ctx.font='12px system-ui';ctx.fillText('Playa principal · inicio y fin',12,height-12);
}
function tick(t){if(last&&playing)phase=(phase+Math.min((t-last)/1000,0.05)*data.length/38*Number(speed.value))%data.length;
  last=t;draw();requestAnimationFrame(tick)}
toggle.onclick=()=>{playing=!playing;toggle.textContent=playing?'Pausar':'Reproducir'};
reset.onclick=()=>{zoom=1;panX=panY=0;draw()};
speed.oninput=()=>{speedLabel.textContent=speed.value+'×'};
canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY,panX,panY];canvas.setPointerCapture(e.pointerId);canvas.classList.add('drag')});
canvas.addEventListener('pointermove',e=>{if(!drag)return;panX=drag[2]+e.clientX-drag[0];panY=drag[3]+e.clientY-drag[1];draw()});
canvas.addEventListener('pointerup',()=>{drag=null;canvas.classList.remove('drag')});
canvas.addEventListener('pointercancel',()=>{drag=null;canvas.classList.remove('drag')});
canvas.addEventListener('wheel',e=>{e.preventDefault();const rect=canvas.getBoundingClientRect(),px=e.clientX-rect.left,py=e.clientY-rect.top;
  const factor=e.deltaY<0?1.12:1/1.12,next=Math.max(0.65,Math.min(8,zoom*factor));
  panX=px-width/2-(px-width/2-panX)*next/zoom;
  panY=py-height/2-(py-height/2-panY)*next/zoom;zoom=next;draw()},{passive:false});
new ResizeObserver(resize).observe(canvas);resize();requestAnimationFrame(tick);
</script></body></html>"""


def main() -> None:
    layout = load_supplier_photo()
    source = ROOT / "assets" / "cfd_supplier20" / "wide_source.dxf"
    if hashlib.sha256(source.read_bytes()).hexdigest() != layout["wide_sha"]:
        raise ValueError("DXF de la animación diferente del plano de comparación")
    model = LazyRiverModel()
    model.load_dxf(str(source))
    model.build_centerline(target_length_m=536)
    origin = np.asarray(model.loader.outer_polygon.centroid.coords[0], dtype=float)
    scale = model.geometry.scale_m_per_unit

    def coords(polygon):
        vertices = np.asarray(polygon.exterior.coords, dtype=float)
        return np.round((vertices - origin) * scale, 3).tolist()

    outer = coords(model.loader.outer_polygon)
    inner = coords(model.loader.inner_polygon)
    stations = model.stations
    center = [[round(float(station["chainage_m"]), 3),
               round((float(station["x"]) - origin[0]) * scale, 3),
               round((float(station["y"]) - origin[1]) * scale, 3),
               round(float(station["width_m"]), 3)] for station in stations]
    if center[0][0] != 0 or abs(center[-1][0] - 536) > 1:
        raise ValueError("El eje del DXF no cierra el recorrido de 536 m")
    vertices = np.asarray(outer)
    payload = {"length": 536, "outer": outer, "inner": inner, "center": center,
               "bounds": [float(vertices[:, 0].min()), float(vertices[:, 1].min()),
                          float(vertices[:, 0].max()), float(vertices[:, 1].max())],
               "pumps": [[item["supplier_number"], item["chainage_m_approx"], item["bank"]]
                         for item in layout["positions"]]}
    html = HTML.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    output = ASSETS / "route_animation.html"
    output.write_text(html, encoding="utf-8")
    print(f"{output}: {len(outer)} + {len(inner)} wall vertices, "
          f"{len(center)} stations, {len(payload['pumps'])} sectors")


if __name__ == "__main__":
    main()
