# NYA original · sensibilidad de caudal en tres pasos angostos

## Pregunta y método

Se comparó el caso guardado `qa_original_reference20_dt05` con
`qa_original_narrow3_q80_consistent_dt05`. Ambos usan `RECORRIDO.dxf`, las
mismas 20 posiciones CF104, malla de 4.056 celdas, profundidad, condiciones
de borde y 1.200 s físicos. Solo las unidades 16, 17 y 18, situadas cerca de
las progresivas 382, 406 y 430 m (anchos DXF aproximados 4,9, 4,9 y 4,1 m),
se prescribieron al 80 % del caudal de referencia. Sus dos tomas y descarga
mantienen balance de masa y la velocidad de salida agregada también baja al
80 %, coherente con `Q/A`. Es una sensibilidad de **caudal impuesto**, no
una predicción de VFD ni de la curva H–Q instalada.

Una primera corrida `qa_original_narrow3_q80_dt05` redujo solo el caudal y
dejó la velocidad de descarga a 4,73 m/s. Se marcó inválida y no se usa en
esta comparación. No se repitió la referencia.

## Resultado final a 1.200 s físicos

| Indicador | 20 unidades de referencia | Tres unidades a 80 % | Cambio |
| --- | ---: | ---: | ---: |
| Mediana longitudinal en pasajes <10 m | 0,610 m/s | 0,581 m/s | −0,029 m/s |
| Percentil 95 en pasajes <10 m | 0,865 m/s | 0,827 m/s | −0,038 m/s |
| Mediana en zona 360–445 m | 0,792 m/s | 0,757 m/s | −0,035 m/s |
| Mediana en zonas anchas ≥15 m | 0,197 m/s | 0,189 m/s | −0,008 m/s |
| Celdas anchas bajo 0,15 m/s | 21,4 % | 29,3 % | +7,9 puntos |
| Celdas con retorno longitudinal <−0,02 m/s | 0 % | 0 % | 0 |
| Velocidad mínima media de 67 secciones | 0,168 m/s | 0,160 m/s | −0,008 m/s |
| Vuelta hidráulica extrapolada por 67 secciones | 24,53 min | 25,70 min | +1,17 min |

La fila anterior de «zonas anchas» incluye la playa principal y cuenta celdas
sin ponderarlas por tamaño. Para la decisión de flujo de paso se hizo una
segunda lectura **sobre los mismos campos guardados**: separa la playa de las
bahías anchas de circulación, excluye los 6 m alrededor de cada descarga de
ambos casos y pondera cada celda por su volumen real de malla. No es otra
corrida ni una medición de la velocidad de pasajeros.

| Región fuera de descargas | Referencia 20 | Tres a 80 % | Lectura |
| --- | ---: | ---: | --- |
| Bahías de paso ≥15 m: mediana longitudinal | 0,177 m/s | 0,167 m/s | Baja |
| Bahías de paso ≥15 m: volumen bajo 0,15 m/s | **12,3 %** | **29,8 %** | Empeora +17,5 puntos |
| Pasajes <10 m: percentil 95 longitudinal | 0,851 m/s | 0,812 m/s | Baja 0,040 m/s |
| Playa principal: mediana longitudinal | 0,229 m/s | 0,223 m/s | Cambio pequeño |
| Playa principal: percentil 95 longitudinal | 0,502 m/s | 0,476 m/s | Persisten áreas rápidas en el modelo |

Los porcentajes nuevos son **fracciones del volumen de malla dentro de cada
región**, no fracciones del caudal, del área de playa ni de usuarios. El umbral
0,15 m/s es diagnóstico; no es un límite de seguridad. La mediana de playa
también revela que el modelo no la hace inequívocamente calma en todo su
ancho. Esta distinción entre playa y bahías de paso debe mantenerse en la hoja
de decisión antes de comparar nuevas ubicaciones.

El máximo Courant observado fue 0,080 (<0,2 solicitado), `checkMesh` pasó y
la mediana longitudinal fue 0,2913, 0,2912 y 0,2912 m/s a 1.160, 1.180 y
1.200 s. No hubo tramos de 10 m con mediana menor que −0,02 m/s en esos
tres campos. Esto comprueba estabilidad de estos indicadores al final del
ensayo, no independencia de malla ni validez física completa.

## Decisión

**Descartar la reducción uniforme de 20 % en las tres bombas angostas como
mejora general.** Baja algo la rapidez en los estrechos, pero en las bahías
anchas de paso eleva de 12,3 a 29,8 % el volumen lento. La lectura anterior
de 21,4 a 29,3 % mezclaba la playa con esas bahías. Solo alarga la vuelta
hidráulica extrapolada 1,17 min; aún queda por debajo de la intención de
30–40 min. No aparece retorno persistente en esta malla.

La siguiente comparación con valor decisorio debería modificar dirección y
reparto de las siete salidas en una estación crítica y comprobar balance,
paredes y sensibilidad de malla antes de trasladar un efecto al circuito
completo. Este ensayo global todavía agrega los siete puertos y usa
`2014 US gpm` por bomba como punto documental, no como punto de operación
NYA verificado. Sus tiempos no son trayectorias de usuarios con chaleco.

Visual interactivo: `narrow_flow_sensitivity_profile.html`. Datos:
`narrow_flow_sensitivity_comparison.json`, los reportes
`stability_recheck_report.json` de ambos casos y los campos VTK guardados.
Preparación y análisis: `prepare_narrow_flow_sensitivity.py` y
`compare_narrow_flow_sensitivity.py`.
