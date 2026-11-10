# Resultado CFD · VFD RF-2, RF-3 y RF-4

Corrida del 10 de noviembre de 2026 sobre el **DXF original de NYA**.

## Comparación controlada

Las RF-2, RF-3 y RF-4 están a unos 50, 74 y 110 m, en pasos de 5,4, 5,7 y
5,0 m de ancho. Se redujeron las tres al 80 % de VFD estimado. Cada una
inyecta 365,7 m³/h en el CFD, frente a 457,4 m³/h en la referencia. El punto
de operación a VFD parcial deriva de leyes de afinidad y un circuito local
**supuesto**, no de una curva medida por Riverflow.

Ambos casos usan el mismo DXF, malla de 4.056 celdas, 20 estaciones,
Manning equivalente de piso 0,013 / paredes 0,025, playa y 1.200 s físicos.
Se comprobó que malla, geometría y `controlDict` son idénticos; solo cambian
las fuentes de tomas/descargas y la velocidad de salida de esas tres bombas.
Las métricas de paso excluyen 6 m alrededor de todas las descargas.

| Indicador | 20 × 100 % | RF-2/3/4 al 80 % |
| --- | ---: | ---: |
| Vuelta hidráulica proyectada | 24,53 min | 25,47 min |
| Volumen lento en bahías de paso (<0,15 m/s) | 12,3 % | **30,4 %** |
| P95 longitudinal en pasos <10 m | 0,851 m/s | 0,819 m/s |
| Mediana longitudinal en playa | 0,229 m/s | 0,224 m/s |
| Volumen con retorno <−0,02 m/s | 0,0 % | 0,0 % |
| Sección de 8 m más lenta | 0,168 m/s | 0,159 m/s |

`checkMesh` dio `Mesh OK.` y `foamRun` completó el tiempo pedido. Courant
máximo observado: 0,081. La mediana longitudinal de los últimos tres campos
(1.160, 1.180 y 1.200 s) fue 0,2924 m/s en cada uno y no hubo medianas de
tramos de 10 m en retorno. Esto apoya estabilidad temporal de esos
indicadores; no prueba independencia de malla ni exactitud física.

## Decisión

**Descartar esta reducción conjunta como ajuste general para estabilizar el
flujo.** El P95 estrecho baja solo 0,032 m/s y la vuelta proyectada aumenta
0,94 min, mientras el volumen lento de las bahías sube 18,1 puntos. Conviene
comparar ubicación/orientación e impulso localizado en bahías antes de
reducir más VFD de bombas en pasos angostos. No se deduce de esta corrida un
ajuste definitivo ni una cantidad de compra.

La vuelta se extrapola del campo final por secciones; no cronometra personas.
El umbral de 0,15 m/s es diagnóstico, no una norma de seguridad. Las tomas y
siete puertos se representan como fuentes agregadas, sin resolver la forma
individual de cada chorro ni la superficie libre.

Datos auditables: `vfd_rf234_comparison.json`,
`qa_vfd_rf2_3_4_80_dt05/stability_recheck_report.json` y
`assets/decision_vfd_original.json`. Los campos VTK pesados quedan locales.
