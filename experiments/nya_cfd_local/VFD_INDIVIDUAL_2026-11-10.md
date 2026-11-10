# NYA original · sensibilidad VFD por bomba

## Pregunta y escenarios

¿Puede bajarse el VFD de bombas situadas en pasos angostos para acercar la
vuelta a 30–40 min sin dejar lentas las bahías de paso? Se compararon cinco
campos OpenFOAM de **1.200 s físicos** con el mismo
`RECORRIDO.dxf`, 20 estaciones, malla de 4.056 celdas, Manning equivalente
de piso 0,013 y paredes 0,025, playa y condiciones de borde. La referencia
de 100 % y el caso de RF-16/17/18 con caudal al 80 % ya estaban guardados.
Se ejecutaron RF-17 al 80 % y al 60 %, más RF-2/3/4 al 80 %.

El punto documental de base es 2.014 US gpm = 457,4 m³/h por CF104. Para
Las bombas a RPM reducidas se cruzaron con una curva escalada por leyes de afinidad y
el circuito local supuesto de la app: tuberías de 8 m por lado, diámetro
interior 0,303 m, K=1 en cada lado, Cd supuesto 0,85 y desnivel neto cero.
El caudal resultante se aplicó como fracción del caudal base de CFD a ambas
tomas y la descarga; la velocidad agregada de salida se redujo en la misma
proporción para respetar Q/A. El caso antiguo de tres bombas usó 80 %
directo del caudal base. Riverflow **no facilitó curvas medidas a esas RPM**
ni el circuito constructivo NYA.

| Caso | Q impuesto por bomba ajustada | Vuelta hidráulica extrapolada | Volumen lento en bahías de paso | P95 longitudinal en pasos <10 m | Mediana en playa |
| --- | ---: | ---: | ---: | ---: | ---: |
| 20 × 100 % | 457,4 m³/h | 24,53 min | **12,3 %** | 0,851 m/s | 0,229 m/s |
| RF-17 al 80 % | 365,7 m³/h | 24,90 min | 20,7 % | 0,839 m/s | 0,227 m/s |
| RF-17 al 60 % | 274,1 m³/h | 25,18 min | 23,4 % | 0,829 m/s | 0,225 m/s |
| RF-16/17/18 al 80 % | 365,9 m³/h por cada una | 25,70 min | 29,8 % | 0,812 m/s | 0,223 m/s |
| RF-2/3/4 al 80 % | 365,7 m³/h por cada una | 25,47 min | **30,4 %** | 0,819 m/s | 0,224 m/s |

Las bahías de paso son secciones de ancho ≥15 m **fuera de la playa**.
Los porcentajes son volumen de malla con avance longitudinal <0,15 m/s,
excluyendo 6 m alrededor de todas las descargas comparadas. El umbral es
diagnóstico, no un límite normativo o de seguridad. P95 es una estadística
de celdas, no la velocidad que experimentaría un bañista. La vuelta suma
longitud de 67 secciones dividida por la velocidad longitudinal media de
cada sección, manteniendo fijo el campo final; no cronometra personas.

## Verificación y decisión

`checkMesh` pasó en los tres casos nuevos. Los cinco alcanzaron 1.200 s,
mantuvieron balance de caudal impuesto y no dejaron tramos de 10 m en retorno
en los tres últimos campos. Courant máximo observado: 0,080–0,084. La mediana
longitudinal de RF-17 al 80 % fue 0,2985/0,2984/0,2984 m/s a 1.160/1.180/
1.200 s y al 60 % fue 0,2956/0,2956/0,2955 m/s. Esto apoya estabilidad de
esos indicadores, **no independencia de malla ni validación física**.

**No usar la reducción de RF-17 o de las tres bombas angostas como ajuste
general para buscar 30–40 min.** El mayor cambio individual ensayado añade
solo 0,65 min respecto de la referencia, mientras casi duplica la fracción
lenta de las bahías (12,3 → 23,4 %). El grupo de tres añade 1,17 min, pero
eleva esa fracción a 29,8 %. Se mantiene 20 × 100 % como referencia numérica
entre estas variantes; no es un ajuste de operación recomendado, ni prueba
que VFD por otras bombas no pueda ayudar. Una siguiente prueba con valor
decisorio debe escoger ubicación/orientación o geometría que conserve flujo
en bahías antes de bajar más impulso en estrechos.

Datos: `individual_vfd_comparison.json`, `stability_recheck_report.json` de
cada caso y `assets/decision_vfd_original.json`. Código:
`prepare_individual_vfd_trial.py`, `compare_individual_vfd.py` y
`export_individual_vfd_archive.py`. Los campos VTK pesados permanecen locales.

Ensayo posterior del mismo día: RF-2/3/4 al 80 % tampoco mejora el balance;
la fracción lenta de las bahías sube a 30,4 %. Su comparación directa y
control numérico están en `VFD_RF2_4_RESULT.md` y
`vfd_rf234_comparison.json`. El archivo compacto de la app integra los cinco
casos. RF-16/17/18 al 80 % se refiere a una reducción directa de **caudal
impuesto**, no a una curva VFD calculada.
