# NYA · tiempo de vuelta, turbulencia y retornos (ensayo local)

Se extendieron cuatro corridas OpenFOAM hasta **1200 segundos físicos** con la misma malla de 4056 celdas, geometría DXF, Manning equivalente (n_piso=0.013, n_pared=0.025) y caudal de referencia de **2014 US gpm por CF104**. Solo cambió la cantidad/posición indicada en cada escenario. La corrida de 600 s produjo retornos transitorios que desaparecieron posteriormente; por tanto, los mapas de 600 s no deben usarse para evaluar remolinos persistentes.

| Escenario | Vuelta hidráulica proyectada | Mediana zonas ≥15 m | Celdas anchas <0,15 m/s | Mediana pasajes <10 m | Mediana k RANS |
|---|---:|---:|---:|---:|---:|
| 16, quitar cuatro de pasajes angostos | 28,88 min | 0,176 m/s | 37,5 % | 0,515 m/s | 0,0110 m²/s² |
| 19, quitar una de pasaje angosto | 25,58 min | 0,190 m/s | 28,8 % | 0,583 m/s | 0,0122 m²/s² |
| 20, distribución de referencia | 24,50 min | 0,198 m/s | 21,4 % | 0,610 m/s | 0,0124 m²/s² |
| 21, añadir una en bahía | 24,22 min | 0,199 m/s | 23,1 % | 0,618 m/s | 0,0127 m²/s² |

La meta de 30–40 minutos equivale a 0,298–0,223 m/s como velocidad efectiva para 536 m. El tiempo mostrado se calcula con la **velocidad longitudinal firmada, media por volumen, en 67 secciones de 8 m**: Σ(8 m / velocidad media de sección) / 60. Es una extrapolación del campo a 1200 s mantenido constante durante una vuelta. No es el tiempo de una persona con chaleco o barra foam y no incorpora trayectorias laterales, paradas o interacción entre personas.

## Retornos y remolinos

En las cuatro corridas a 1200 s, **ninguna de las 4056 celdas** tuvo componente longitudinal menor que −0,02 m/s. A 600 s sí había retornos locales en la primera bahía: eran transitorios. La derivada local del campo medio conserva giro (percentil 95 de indicador de giro de ~0,022–0,024 s⁻¹), pero esto **no prueba remolinos cerrados persistentes**. La malla y las descargas agregadas no resuelven los siete puertos, la capa junto a pared, la superficie libre ni vórtices pequeños.

## Turbulencia modelada y estabilidad

Se recuperaron de las mismas corridas los campos RANS k y epsilon. Con 20 bombas, la mediana de k pasó de 0,0044 m²/s² a 600 s a 0,01245 m²/s² a 1200 s. Entre 1140 y 1200 s cambió solo −0,06 %; el tiempo hidráulico cambió +0,03 %. Las corridas de 19 y 21 mostraron cambios de k inferiores a 0,05 % en ese intervalo. La de 16 aún cambió +3,25 % en k y +0,39 % en tiempo, por lo que necesita más evolución antes de tratarla como igualmente estable.

La intensidad calculada con I=√(2k/3)/|U| fue ~25,7 % de mediana entre las celdas de 20 bombas con |U|≥0,15 m/s; en la primera bahía fue ~41 %. Es **intensidad calculada por el modelo k-ε, no medición**. Su valor absoluto no establece un umbral de seguridad: el ensayo usa paredes slip y fricción de Manning aplicada como resistencia volumétrica.

## Decisión provisional

Entre las cuatro opciones, **20 bombas mantienen el mejor compromiso** de este modelo: reducen la fracción de zonas anchas lentas respecto de 16 y 19. La bomba 21 no mejora ese indicador y aumenta levemente la turbulencia modelada en la primera bahía. Las 16 se acercan al tiempo meta, pero dejan demasiada zona ancha lenta. Ninguna logra simultáneamente 30–40 minutos y avance suficientemente uniforme. No se recomienda comprar una cantidad definitiva ni certificar seguridad basándose en esta malla.

El siguiente ensayo debe mantener la cantidad como variable y modificar la **orientación y distribución de la descarga de siete puertos, junto con la velocidad VFD por estación**, para disminuir los pasajes rápidos sin dejar sin avance las bahías. Después se requiere una malla más fina en curvas, paredes, playa, tomas y descargas, y repetir el análisis de convergencia.

Visuales: [cuatro mapas de velocidad a 1200 s](extended_16_19_20_21_velocity_maps.html), [k y giro a 1200 s](extended20_k_and_spin_maps.html). Datos: [comparación reproducible](extended_16_19_20_21_comparison.json). Código: analyze_extended_comparison.py y visualize_extended_maps.py.
