# NYA original · orientación de RF-5 y RF-6 en la primera bahía

Ensayo local del 13 de noviembre de 2026. **Resultado: descartar el giro
hipotético de 15° hacia el centro** como mejora general de este modelo.

## Cambio aislado

Se mantuvieron el DXF original, 20 CF104, 2.014 US gpm (457,4 m³/h) por
unidad, la malla de 4.056 celdas, la profundidad y playa, Manning equivalente
de piso 0,013 / paredes 0,025 y los 1.200 s físicos. RF-5 (≈146 m, margen
interior) y RF-6 (≈164 m, margen exterior) conservaron su caudal y rapidez
agregada de salida de 4,729 m/s. Solo sus vectores de descarga se giraron
15° desde la tangente local hacia el eje del canal. Se verificó que DXF,
`fvModels`, malla y `controlDict` son idénticos a la referencia.

El giro es una **hipótesis del chorro agregado**; no representa siete
puertos orientados geométricamente ni una indicación del fabricante.

## Resultado comparable

Las métricas excluyen 6 m alrededor de todas las descargas de ambos casos.
Bahía 135–178 m; el porcentaje lento es volumen con componente longitudinal
menor a 0,15 m/s. La vuelta suma longitud/velocidad media por sección del
campo final: no cronometra personas.

| Indicador | Referencia | RF-5/6 hacia centro 15° |
| --- | ---: | ---: |
| Vuelta hidráulica proyectada | 24,53 min | 24,56 min |
| Volumen lento en todas las bahías de paso | 12,26 % | 13,52 % |
| P95 en pasos angostos | 0,851 m/s | 0,851 m/s |
| Volumen con retorno <−0,02 m/s | 0,0 % | 0,0 % |
| Mediana en bahía 135–178 m | 0,179 m/s | 0,176 m/s |
| Mitad izquierda de esa bahía, volumen lento | 19,2 % | 24,2 % |
| Mitad derecha de esa bahía, volumen lento | 7,9 % | 5,4 % |

El giro desplaza algo de avance hacia la mitad que ya era más rápida y
agrava la mitad lenta. No alarga la vuelta de forma útil ni reduce el P95
de los pasos angostos. La mejora de la mitad derecha por sí sola no apoya
esa orientación.

## Comprobaciones y alcance

`checkMesh` dio `Mesh OK.` y `foamRun` completó 1.200 s. El Courant máximo
fue 0,084. La mediana longitudinal de los campos a 1.160, 1.180 y 1.200 s
fue 0,3007 m/s en los tres; no hubo medianas de tramos de 10 m en retorno.
Esto apoya estabilidad temporal de esas métricas, pero no independencia de
malla ni validación física. La malla gruesa, descargas agregadas y ausencia
de superficie libre limitan la lectura de chorros, remolinos y seguridad.

**Decisión:** conservar la referencia de 20 bombas como comparador, sin
convertirla en cantidad de compra. No aplicar el giro de 15° a la app ni
seguir probando ángulos arbitrarios en esta malla. El siguiente estudio útil
debe partir del perfil de anchos y de la distribución transversal del flujo,
con una geometría de descarga más fiel antes de recomendar posición o VFD.

Datos: `orientation_bay05_06_global.json`,
`bay05_06_orientation_comparison.json`,
`qa_bay05_06_inward15_dt05/stability_recheck_report.json`.
Código: `prepare_bay_orientation_trial.py` y `compare_bay_orientation.py`.
Los campos VTK pesados permanecen locales.
