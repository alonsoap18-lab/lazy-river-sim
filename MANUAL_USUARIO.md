# Manual de usuario — módulo Riverflow de Lazy River Selvatura NYA

**Versión documentada:** código revisado el 29 de septiembre de 2026; la hoja de decisión se incorpora con esta actualización.
**Dirección:** https://lazy-river-sim-qdstdmhyadagfmdatkeat5.streamlit.app/
**Proyecto base:** recorrido antihorario de 536 m, trazado del archivo `RECORRIDO.dxf`, profundidad inicial de 1,20 m. Todos estos valores pueden cambiarse como escenarios; no son planos aprobados.

## 1. Qué hace el módulo Riverflow y qué no hace

El módulo Riverflow permite explorar, en fase de anteproyecto, cómo el trazado DXF, la profundidad, las unidades Riverflow, la resistencia del canal y la filtración afectan el volumen, el caudal requerido, las velocidades teóricas y los tiempos de vuelta. Para abrirlo, elija **Riverflow** en el selector de modelo de la barra izquierda.

Representa unidades Riverflow junto al canal, su curva caudal–TDH publicada y un circuito local editable. Trata la planta de filtración como otro sistema. El movimiento longitudinal del río depende de una **fracción de energía útil supuesta, no medida en NYA**. No se deben sumar el caudal de descarga local y el caudal de filtración.

Es un **modelo preliminar de sensibilidad**, no diseño ejecutivo, CFD validado, certificación sanitaria o de seguridad, ni lista de compra aprobada. Un color verde o un estado «OK» solo cumple el criterio simplificado de esa pantalla.

### Convenciones y unidades

| Término | Significado | Unidad |
|---|---|---|
| DXF | Plano de los dos contornos del río; la capa esperada es `PAREDES`. | — |
| Progresiva o *chainage* | Distancia desde el inicio del recorrido, aumentando en sentido antihorario. | m |
| Área de sección, A | Superficie transversal ocupada por agua. No es el área en planta. | m² |
| Volumen, V | Agua estimada en el canal a la profundidad/propuesta de playa escogida. | m³ |
| Caudal, Q | Volumen que circula por unidad de tiempo. | m³/h o m³/s |
| Velocidad Q/A | Promedio idealizado de una sección. Puede diferir de una trayectoria o del valor local del mapa. | m/s |
| Tiempo de vuelta | Tiempo para recorrer los 536 m bajo las velocidades calculadas. | min |
| Manning n | Parámetro de resistencia del piso y paredes; mayor n implica más fricción. | s/m^(1/3) |
| TDH | Altura dinámica total o carga requerida a una bomba en su circuito. | m o ft |
| K de accesorio | Pérdida concentrada adimensional de una toma, codo, salida u otro elemento. | — |
| HP de placa | Potencia nominal del motor, no consumo eléctrico instantáneo. | HP |
| Recambio/turnover | Tiempo para enviar a los filtros un volumen equivalente al del río. **No** significa vaciar y volver a llenar. | h |
| N−1 | Prueba de capacidad cuando falla una unidad activa. | — |

### Orden recomendado para trabajar

1. Seleccionar **Riverflow** en la barra izquierda.
2. Cargar el DXF actualizado; si no se carga, se utiliza `RECORRIDO.dxf` incluido. Confirmar longitud real, escala y profundidad.
3. Definir el escenario de propulsión y anotar cuáles datos son medidos, de ficha técnica o supuestos.
4. Revisar **Resultado del escenario**, **Hidráulica**, el mapa y **Hoja de decisión**. Comparar la vuelta media con las velocidades por sección y las trayectorias, sin exigir que sean números idénticos: representan magnitudes diferentes.
5. Analizar **Filtración guiada** y, si se dispone de fichas, **Filtración avanzada**. La filtración es independiente de la propulsión.
6. Comparar alternativas sin cambiar varios parámetros a la vez. Guardar externamente la configuración y las hipótesis usadas.

## 2. Barra lateral: datos que se ingresan

| Control | Qué se coloca | Qué cambia y cómo leerlo |
|---|---|---|
| **Plano DXF (capa PAREDES)** | Archivo `.dxf` con los dos contornos cerrados del río. | Cambia estaciones, anchos, volumen, mapa, fricción y tratamiento. Sin archivo usa el DXF incluido. No contiene cotas sumergidas ni detalle real de la playa. |
| **Longitud de referencia para escalar DXF** | Longitud medida del recorrido; base 536 m. | Escala **longitud y anchos juntos**. No es un ancho fijo. Si el DXF ya está a escala real, corroborar el factor mostrado en el mapa. |
| **Profundidad de agua** | Profundidad del canal principal; base 1,20 m. | Modifica área, volumen, velocidad, vuelta, resistencia y Q de filtración. No define por sí sola la pendiente de salida a arena. |
| **Zona calma desde ancho** | Umbral de ancho; base 15 m. | Clasifica los tramos más anchos como bahías/entradas a playa para el análisis. **No crea** una playa nueva ni garantiza corriente calma. |
| **Acabado propuesto de paredes** | Piedra impermeabilizada, concreto texturizado o personalizado. | Cambia los valores iniciales de Manning de paredes. Son hipótesis; definir material y rugosidad final después. |
| **Manning n · piso liso** | Valor entre 0,010 y 0,035; base 0,013. | Afecta la resistencia del fondo y, en este modelo, la corriente y la vuelta mediante el balance energético supuesto. |
| **Manning n · paredes de corriente / playa** | Rugosidad por tipo de sección; base según acabado. | Se combina con el piso ponderando perímetro mojado. Mayor n reduce la corriente prevista bajo el supuesto de energía útil fija. La «pared de playa» aplica a secciones anchas, no mide la textura real de cada margen. |
| **Aplicar cotas proporcionales al DXF** | Activar el perfil preliminar de la playa principal. | Solo el mayor ensanchamiento recibe un tramo plano y una rampa; las otras bahías siguen profundas. Cambia volumen, área, resistencia, vuelta y filtración. El DXF no trae cotas de fondo. |
| **Fracción plana de playa** | Porcentaje del ancho extra que conserva 1,20 m de profundidad; base 62 %, equivalente aproximadamente a 16 de 26 m. | El ancho restante recibe la rampa. Se adapta proporcionalmente al DXF sin inventar metros fuera del plano. |
| **Pendiente de rampa de playa** | Pendiente propuesta; base 6,5 %. | Si no alcanza cota de arena seca, la app muestra la profundidad restante en el borde DXF. Con los valores iniciales quedan aproximadamente 0,64 m: no es una salida seca validada. |
| **Objetivo de tiempo por vuelta** | Meta de operación; base 40 min. | Calcula Q longitudinal **requerido** y diferencia respecto al escenario. No hace que las bombas suministren automáticamente ese caudal. |
| **Unidades activas** | Cantidad de Riverflow operando; base 19. | Afecta descarga local total, potencia útil supuesta, corriente y vuelta. No equivale a bombas de filtración. |
| **Unidades de reserva** | Equipos adicionales apagados; base 1. | Suman HP nominal instalado, pero **no** aportan caudal en el escenario normal. |
| **Lectura de curva H–Q** | Puntos visibles de la foto o recta entre dos anclas. | Los puntos rotulados son 2.440 US gpm a 4 ft y 1.220 US gpm a 10 ft. Los intermedios leídos de la foto son aproximados; ambas opciones permiten ver sensibilidad. No extrapolar fuera del rango disponible. |
| **Velocidad del variador** | Porcentaje de RPM de prueba, 50–100 %. | Aplica leyes de afinidad aproximadas a caudal y carga. No son curvas verificadas a cada RPM ni permite calcular consumo eléctrico real. |
| **Resolver circuito local por unidad** | Activado: cruza curva H–Q con pérdidas calculadas. Desactivado: usa TDH manual. | Evita tratar el caudal de placa como caudal real, pero los datos del circuito NYA siguen siendo supuestos. |
| **Longitud succión / descarga** | Metros de tubería de **una** unidad, no suma de todas. | Afecta pérdidas Darcy–Weisbach y el punto de operación. Introducir longitudes reales cuando exista plano. |
| **Diámetro interior succión / descarga** | Diámetro hidráulico real en m; referencia inicial ≈0,303 m para PVC Sch 40 nominal 12″. | Afecta velocidad y fricción de tubería. No escribir 12 ni usar diámetro exterior. La referencia no fija material NYA. |
| **K tomas/accesorios, K descarga y K salida** | Suma de coeficientes adimensionales de cada circuito local. | Afecta TDH y caudal por unidad. Todos son hipótesis iniciales; cambiar de salida «7 puertos» a «3 puertos» **no** modifica K automáticamente. |
| **Editar tuberías y pérdidas por unidad** | Tabla RF-01, RF-02, etc. con longitudes, diámetros interiores y K propios. | Calcula un punto H–Q por unidad y suma sus caudales para el escenario activo. Las matrices que cambian la cantidad de unidades siguen suponiendo un circuito común. |
| **Desnivel neto del circuito** | Diferencia de nivel que la bomba debe superar, en m. Base 0. | Añade carga local. Un río cerrado no implica que cualquier circuito de toma/descarga tenga desnivel neto exactamente cero. |
| **TDH local manual a plena velocidad** | Valor en **ft** cuando el circuito automático está desactivado. | Selecciona Q en la curva Riverflow. No sumar esta TDH a la pérdida longitudinal del río; son circuitos distintos. |
| **Energía útil para mover el río** | Fracción supuesta de potencia hidráulica que sostiene la corriente; base 2 %. | Es uno de los datos **más inciertos**. Cambia considerablemente Q longitudinal y vuelta. No proviene de Riverflow ni de medición NYA; siempre comparar varios valores. |
| **Salida propuesta** | 7 puertos o manifold de 3 puertos. | Registra la opción en equipos. No recalcula pérdidas por sí sola; para ello editar K con fundamento. |
| **Ubicación de unidades** | Automática o lista manual de progresivas en m. | La automática evita zonas clasificadas como calmas. La manual exige una posición por unidad y puede situarlas en una bahía; aparece aviso. Cambia el acoplamiento geométrico supuesto y el mapa. |
| **Orientación de descargas** | Ángulo común o una lista por unidad; 0° sigue el sentido antihorario. | Influye en eficacia propuesta y campo 2D; no reproduce el chorro real. Valores positivos se inclinan hacia la margen elegida para la unidad. |
| **Margen por unidad** | E = exterior del circuito DXF; I = interior, una letra por RF. | Cambia el esquema 2D/3D y el reparto lateral hipotético. No cambia por sí sola el caudal longitudinal ni certifica que esa orilla sea segura. El exterior de una curva puede ser E o I. |
| **Recirculación de filtración** | Horas por volumen equivalente; base 4 h. | Q filtración = volumen/horas. No cambia el caudal Riverflow ni representa agua nueva del pozo. La elección sanitaria final debe confirmarse para Liberia. |

### Cómo leer el resumen Riverflow

- **Volumen DXF + perfil:** agua aproximada dentro del río. No incluye automáticamente tanque de compensación.
- **Meta de vuelta / Q requerido:** objetivo y caudal longitudinal idealizado necesario para alcanzarlo.
- **Vuelta media V/Q:** volumen dividido entre corriente equivalente supuesta. Es un indicador de renovación longitudinal, no el tiempo de una persona en una orilla concreta.
- **Caudal de unidades:** suma de descargas locales de las bombas Riverflow estimada por su curva. Puede ser muy distinto de la **corriente longitudinal equivalente**; **no se deben igualar ni sumar**.
- **Vuelta central 2D:** trayectoria del campo lateral conceptual. Puede diferir de V/Q porque describe otra ruta y una distribución hipotética.
- **Motores activos · placa:** 10 HP por unidad activa. No es kW consumidos, costo anual ni curva de potencia.
- **Filtración separada:** caudal que debe pasar por filtros, no por las unidades de propulsión.
- **Q por unidad según curva:** con circuito común es el caudal estimado de cada unidad; con circuitos individuales la métrica muestra un promedio y la tabla de Hidráulica da el valor de cada RF. El total es la suma de todas las unidades activas, no el caudal que atraviesa una sección completa del canal.

## 3. Qué hace cada pestaña

### Hoja de decisión (primera pestaña)

Es el punto de partida recomendado. Distingue geometría y curva disponible de los
resultados que todavía dependen del 2 % supuesto. La **comprobación de impulso
ideal** no usa ese porcentaje: calcula el mayor impulso longitudinal posible si
toda la TDH local se convirtiera en velocidad de descarga sin pérdidas y lo
compara con el arrastre Manning a la meta. El «mínimo optimista de vuelta» es
una cota favorable, **no** una predicción. Si ni ese límite llega a la meta,
la configuración requiere revisión; si llega, no demuestra que la instalación
real lo consiga. Tampoco evalúa seguridad de tomas, salidas o bañistas.
El porcentaje de impulso ideal no es el mismo concepto que el 2 % de energía
útil; no deben igualarse ni restarse.

### Plano 2D · conceptual

Muestra paredes del DXF, playa principal proporcional, bombas locales, tomas, descargas y un campo de velocidad coloreado. El primer gráfico de sección muestra la cota propuesta del fondo; las métricas comparan el volumen uniforme y el volumen con playa.

Controles: **Mostrar montaje conceptual** agrega símbolos de instalación; **Colorear campo 2D** enciende/apaga el color; **Auditar secciones perpendiculares** compara anchos y área integrada del modelo frente al contorno DXF; **Intervalo de auditoría** define cada cuántos metros se revisa, **no** el ancho del río. La diferencia de áreas y las secciones señaladas indican geometría por revisar. El mapa no predice remolinos ni variación real de una orilla a otra.

**Resultados de esta página:** «Área por secciones» es la suma aproximada de áreas obtenidas de los cortes; «Área del contorno DXF» es el área en planta del dibujo; «Diferencia de áreas» ayuda a detectar discordancias de geometría y muestreo. «Campo 2D mín–máx» resume las velocidades del campo conceptual, no mediciones. «Residuo numérico de caudal» expresa cuánto se desvía el caudal reconstruido de la condición que el modelo intentó conservar; un residuo pequeño verifica consistencia interna, **no** exactitud física. «Mayor distancia de canal a una unidad» identifica el tramo de corriente más alejado de una instalación propuesta; no demuestra por sí sola falta de empuje.

**Comparar ubicación de bombas:** muestra la distribución activa, otra equilibrada por distancia/fricción y una tercera que examina curvas. La tabla de curvas identifica la margen exterior de cada giro, que no siempre coincide con la margen exterior del circuito. El botón de prueba aplica posiciones y márgenes editables; la comparación visual mantiene el mismo caudal longitudinal para aislar el cambio de ubicación. Ninguna alternativa calcula alcance real del chorro, turbulencia o seguridad de succión.

### Explicación

Cuenta la cadena DXF → volumen → curva local → corriente supuesta → tiempo de vuelta. Resalta la fracción de energía útil desconocida y separa hechos de hipótesis. Úsela para explicar un escenario a otra persona; no como aprobación técnica.

### Hidráulica

Presenta Manning compuesto por sección, fricción longitudinal, comparación con la meta, Froude equivalente y perfil de velocidades Q/A. Si está activo el circuito local, muestra su intersección H–Q, pérdidas de succión, descarga, accesorios y salida. Si está desactivado, usa la TDH manual. La pérdida del **canal** no es la TDH local de **cada bomba**.

**Lectura de indicadores:** «Pérdida canal · escenario» es la resistencia longitudinal estimada con la corriente actual; «Pérdida canal · meta» usa la corriente necesaria para llegar al objetivo de vuelta. «Froude equivalente máx.» compara inercia y gravedad en las secciones idealizadas; no caracteriza olas locales ni seguridad de bañistas. «Punto de operación» es la intersección de la curva aproximada y las pérdidas locales **ingresadas**. «Velocidad en succión/descarga» corresponde a la tubería, no a la velocidad del agua donde flotan las personas. «V equivalente Q/A medio» es caudal longitudinal equivalente dividido entre área media; no tiene por qué coincidir con el promedio espacial de velocidades o el tiempo de una trayectoria.

Incluye tiempos en canal de corriente y bahías, curvas H–Q, tiempos de tres carriles conceptuales y sensibilidad a distintos porcentajes de energía útil. Las «unidades para meta» son aritmética bajo estos supuestos, no una orden de compra. La tabla de trazabilidad explica qué salida depende de cada entrada.

### Recorrido ilustrativo

Reproduce una vuelta en sentido antihorario sobre el campo conceptual. Los puntos
representan **personas con chaleco salvavidas o barra de espuma que se dejan
llevar pasivamente**; no flotadores independientes. No se modelan patadas,
braceo, resistencia corporal, viento ni interacción entre personas. **Velocidad
de reproducción** (60×, 120×, 300× o 600×) cambia solo la animación: no altera
RPM, Q ni tiempo físico. No evalúa seguridad.

### Ensayo 2D · dependiente del 2 %

Ensayo separado del mapa principal. **Hereda el Q longitudinal calculado con el
2 % supuesto**, por lo que no verifica ese porcentaje. Prueba reparto lateral
con advección, mezcla y arrastre Manning linealizado. **No** recalcula la
cantidad de bombas ni resuelve CFD completo.

| Control | Significado |
|---|---|
| Margen supuesta de la playa | Interior o exterior del giro horario. El DXF no identifica en cuál está la rampa sumergida. |
| Mezcla lateral supuesta (m²/s) | Parámetro turbulento efectivo; valores mayores tienden a suavizar diferencias entre carriles. No está medido. |
| Impulso longitudinal local supuesto (mm/s²) | Intensidad exploratoria de las descargas en el ensayo, **no** fuerza certificada del equipo. |
| Longitud de influencia por unidad (m) | Distancia sobre la que se distribuye ese impulso supuesto. |
| Ejecutar y comparar | Calcula mapa de colores, vuelta del carril fijo central, caudal conservado y perfil frente al mapa conceptual. |
| Comprobar estabilidad con malla más fina | Repite con más celdas y compara el tiempo central. Si cambia mucho, la resolución numérica es insuficiente; si cambia poco, los supuestos físicos siguen sin validar. |

El tiempo del piloto sigue un **carril de fracción lateral fija**; el mapa anterior sigue líneas de corriente conceptuales. Por eso una diferencia entre ambos tiempos **no** es un error aritmético automático ni una corrección validada.

### Simulación 2D experimental

Prueba numérica independiente que rasteriza el contorno DXF y calcula un
**arranque transitorio desde agua en reposo** con conservación de agua y momento
promediado en profundidad. Usa las áreas y Manning del escenario actual, el
caudal/TDH estimado de cada Riverflow y las posiciones y orientaciones editadas.
No utiliza el 2 % de energía útil para calcular el campo; en su lugar pide un
**porcentaje supuesto de impulso ideal que llega al agua**. Estos porcentajes
representan magnitudes diferentes y no se comparan entre sí.

| Control | Significado |
|---|---|
| Impulso ideal que llega al agua (%) | Hipótesis de cuánto momento de descarga se transfiere al agua; no es dato Riverflow ni calibración NYA. |
| Arranque simulado (min) | Minutos físicos desde reposo; no es tiempo de vuelta ni estado estacionario. |
| Tamaño de celda (m) | Resolución de la malla. Un mapa que cambia mucho al refinarla no es numéricamente confiable. |
| Mezcla horizontal (m²/s) | Difusión exploratoria; no está medida. |
| Ejecutar simulación | Lanza el cálculo solo a petición para evitar demoras en cada edición. Si cambia cualquier entrada que afecta el resultado, la app oculta el mapa anterior hasta volver a ejecutar. |

Muestra el mapa experimental y el conceptual actual **con la misma escala de
colores**, pero no se deben restar directamente: uno es un arranque desde reposo
y el otro es un escenario de corriente supuestamente sostenida. El balance de
agua y Courant comprueban aspectos numéricos, **no** la realidad física. La
simulación no representa tomas emparejadas, geometría de boquillas, pendiente
lateral real de la playa, turbulencia resuelta ni movimiento de personas; no
calcula vuelta, seguridad o selección de equipos. La hoja de decisión y los
cálculos de filtración permanecen independientes de esta prueba.

### Filtración guiada

Primer paso para entender el tratamiento sin cargar curvas. Presenta **volumen ÷ tiempo de tratamiento = Q filtración**. El único control propio es **Bombas de filtración activas para comparar**: divide el Q total entre bombas operativas y muestra la necesidad por bomba si una falla sin reemplazo. Ese segundo valor no demuestra que las restantes puedan subir su caudal.

La tabla de Pentair EQ y Speck BADU hace **preselección por máximos publicados de familia**. Si la demanda supera un máximo publicado, descarta esa familia; si no, solo dice «revisar curva Q–H a la TDH real». El ejemplo Waterco M5000 de 5,0 m² ilustra el número aritmético de filtros con la tasa de prueba definida en Filtración avanzada; no aprueba un filtro específico.

### Filtración avanzada

Permite probar capacidad de equipos, contingencia N−1, retrolavado y un tramo de tubería. **Ningún caudal de propulsión se cuenta como filtrado.** La referencia de 6 h citada en la app requiere confirmar la clasificación sanitaria del lazy river; 4 h es el escenario inicial NYA, no una autorización.

| Dato a ingresar | Qué significa / qué produce |
|---|---|
| Tasa de filtración de prueba (m/h) | Q/área = velocidad superficial de paso por filtro. Base 20 m/h como hipótesis; no es límite final. |
| Área efectiva por filtro candidato (m²) | Área publicada por fabricante. Cero = desconocida. Junto con la tasa da un **mínimo aritmético activo** sin redundancia. |
| Bombas de reserva adicionales | Unidades instaladas aparte de las activas seleccionadas en Filtración guiada. |
| Caudal comprobado por bomba con filtro sucio | Caudal verificable a la TDH de la planta en condición desfavorable. Cero = desconocido; sin este dato no hay aprobación de capacidad ni N−1. |
| La reserva arranca al fallar una activa | Marcar solo si existe control/transferencia y reserva equivalente. |
| Filtros instalados / fuera de servicio | Sirven para comprobar área disponible y operación degradada. Si están en cero, la app solicita datos. |
| Tasa y duración de retrolavado | Valores de ficha técnica; con el área del filtro calculan caudal instantáneo y **agua por un evento**, sin enjuague. No es consumo diario del pozo. |
| Filtros simultáneos en lavado | Número lavándose a la vez; cambia el caudal y volumen del evento. |
| Caudal, diámetro interior y longitud de un tramo | Definen una **sola** tubería para calcular velocidad y pérdida Darcy–Weisbach. Cero = pendiente. |
| Rugosidad absoluta (mm) y suma K | Material y accesorios de ese tramo; afectan las pérdidas. No calculan la TDH total de la planta. |

La tabla de equipos enumera bombas de recirculación, filtros, desinfección/pH, tanque de compensación, instrumentación y manejo del agua de lavado. **Agua de pozo** = llenado inicial y reposición de pérdidas; **Q filtración** = agua del mismo río circulando repetidamente.

**Lectura de resultados:** «Área total de filtración» = Q objetivo/tasa de prueba; «Filtros activos mínimos» = área total/área efectiva de cada filtro, redondeado hacia arriba. «Reparto requerido entre bombas activas» y «Una bomba fuera (N−1)» expresan **demanda**, no capacidad. Las filas de capacidad solo pueden cambiar a comprobadas cuando se ingresa un caudal sustentado por curva para la condición de filtro sucio. El retrolavado indica caudal y volumen de un evento, sin incluir enjuague ni frecuencia de lavado. La pérdida de una tubería es solo la del tramo ingresado, no la TDH de toda la planta.

### Escenarios

Compara el actual con una alternativa manteniendo el mismo DXF y profundidad. Entradas: **unidades activas alternativas**, **variador alternativo**, **horas de filtración alternativas** y **filtros fuera de servicio alternativos**. Si cambia el número de unidades, la alternativa se distribuye automáticamente; no se copia una lista manual de longitud distinta. Los dos mapas usan la misma escala de color.

La **matriz de sensibilidad** (activar casilla) cruza tres cantidades de unidades, tres RPM y tres factores de K (75, 100 y 125 % del K ingresado). **Energía útil para matriz** multiplica la hipótesis principal por 0,5/1/2; **Hipótesis K para mapa** escoge qué capa visualizar. Verde significa que la trayectoria lenta cumple la meta **bajo esas hipótesis**; rojo que no; sin color significa fuera de la curva disponible. La potencia hidráulica mostrada no es consumo eléctrico.

### Hoja de decisión

Reúne en una tabla y una gráfica tres lecturas del **mismo escenario de geometría, unidades, orientación, variador, circuito local, Manning y filtración**: conservadora, configuración actual y favorable. No son predicciones probabilísticas. La conservadora usa la mitad de la fracción de energía útil ingresada; la favorable usa el doble. La configuración actual reproduce exactamente los resultados principales de la app. Para variar K y RPM se usa la matriz de la pestaña «Escenarios»; la hoja principal los mantiene fijos, evitando extrapolar la curva al formar estos tres casos.

El límite adicional de impulso ideal no sustituye esos tres escenarios ni
calibra el 2 %. Solo permite descartar una meta físicamente imposible bajo sus
supuestos optimistas; un resultado favorable no autoriza compras.

La tabla distingue **Q descarga local**, **corriente longitudinal**, **vuelta volumétrica V/Q** y **vuelta de la trayectoria más lenta 2D**. Si el circuito actual no tiene un punto dentro de la curva, la app detiene el cálculo antes de la hoja en vez de extrapolar. «Meta alcanzada bajo hipótesis» **no** es aprobación de compra ni garantía de 40 minutos.

Debajo se muestra el tratamiento como circuito independiente: volumen, horas de recirculación, Q requerido por filtros, necesidad por bomba y estados de capacidad normal, N−1 y filtros. «Dato requerido» indica que la capacidad no está demostrada. La tabla de origen distingue DXF, datos publicados e hipótesis NYA. La comprobación de coherencia verifica cuatro igualdades aritméticas (descarga, vuelta V/Q, filtración y Q meta); superar esa prueba no valida las hipótesis físicas.

### Equipos

Lista unidades RF-01, RF-02, etc., progresiva, margen, caudal estimado, 10 HP de placa y tipo de salida. **Descargar listado CSV** exporta ese escenario, incluidos los caudales individuales si se editaron sus circuitos. Resume unidades activas/de reserva e infraestructura por prever: estación mecánica local, área eléctrica protegida y planta de tratamiento separada. El plano Riverflow recibido es de otro proyecto, no es plano de construcción NYA.

### Planos e instalación

Abre los documentos originales publicados por Riverflow para una instalación de 4 ft con siete puertos, el montaje de la boquilla y la guía eléctrica. El plano de 3 ft aparece solo como comparativo. El esquema dentro de la app es propio, funcional y **no está a escala**; ninguna cota de esos ejemplos reemplaza un plano de NYA.

La tabla **Auditoría de cálculos que aún faltan** muestra qué simplifica la app y qué dato falta para pasar a un cálculo verificable: dos ramas de succión, pérdidas y longitudes reales, efecto de la boquilla, acoplamiento de la corriente, viabilidad de montaje y demanda eléctrica. Sus cifras de longitudes, K, salida y porcentaje reflejan los controles actuales. Esta pestaña **no altera el DXF ni cambia por sí misma los resultados hidráulicos**.

### Referencias

Audita qué viene de la foto/curva Riverflow, qué es interpolado y qué sigue sin publicar; compara hipótesis NYA con otros ríos sin inventar caudales ausentes. Incluye esquema de instalación y los documentos de referencia cargados. No transfiera cotas de esos planos a NYA sin revisar el sitio.

## 4. Relaciones clave entre los datos de Riverflow

| Cambio manual | Se espera que cambie | No debe interpretarse como |
|---|---|---|
| Longitud, anchos del DXF o profundidad | Áreas, volumen, velocidades, tiempo y Q de filtración; a menudo fricción. | Medición definitiva del fondo o volumen del tanque. |
| Perfil de playa y Manning del piso/paredes | Volumen o fricción, corriente longitudinal supuesta y vuelta. | Calibración física de la descarga o curva completa de bomba. |
| Unidades Riverflow activas, RPM y pérdidas K | Punto local estimado, Q de descarga, energía útil supuesta, corriente y vuelta. | Aumento de Q filtrado. |
| Posición u orientación de unidades | Acoplamiento geométrico hipotético, campo de velocidades y trayectorias. | Predicción validada de chorros y remolinos. |
| Fracción de energía útil | Corriente longitudinal y vuelta calculadas. | Eficiencia comprobada para NYA. |
| Horas de filtración | Q necesario a través de filtros. | Caudal de Riverflow, consumo diario o agua nueva. |
| Número de bombas de filtración | Q **requerido** por bomba y prueba N−1 teórica. | Capacidad comprobada sin curva a TDH con filtro sucio. |
| Mostrar mapa o velocidad de reproducción | Visualización. | Cambio del sistema físico. |

Ejemplo aritmético con un escenario de **6.400 m³**: a **4 h**, los filtros necesitarían aproximadamente **1.600 m³/h** en conjunto. Con **8 bombas activas**, la necesidad es **200 m³/h por bomba**. Estos tres números no indican que una bomba comercial pueda entregar 200 m³/h a la TDH real ni que deban extraerse 1.600 m³/h de un pozo.

## 5. Datos pendientes y decisiones que sí permite hoy

La app permite **comparar sensibilidad**, descartar combinaciones evidentemente insuficientes bajo supuestos declarados, localizar ensanchamientos, estimar órdenes de magnitud de volumen/filtración, preparar espacio para infraestructura y formular rangos de unidades. **Todavía no permite cerrar compras, seguridad de succión, potencia eléctrica, presupuesto operativo ni diseño ejecutivo.**

Para pasar de hipótesis a decisiones de ingeniería se requiere al menos: confirmación de escala y cotas del DXF; perfil longitudinal y fondo de playa; margen real de entradas a arena; longitudes/diámetros/accesorios de cada instalación; TDH de tratamiento con filtro sucio y curvas de bombas/filtros a ese punto; calidad/capacidad del pozo, tanque y efluentes; criterios sanitarios de Costa Rica; verificación eléctrica; medición posterior o simulación hidráulica detallada calibrada de curvas, playas y tomas. En ausencia de esos datos, mantener **varios escenarios** y documentar cada supuesto.

**Regla práctica:** una cifra obtenida de una ficha a un punto concreto es más confiable que un máximo de familia; un máximo de familia es más confiable que un K o porcentaje supuesto; ninguno sustituye la verificación del equipo instalado en NYA.
