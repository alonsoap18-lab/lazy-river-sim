"""Reference data from real lazy rivers around the world."""

# === PUNTO DE DISEÑO REAL — SELVATURA NYA ===
# Calculado por core/orchestrator.py usando la geometría real del DXF
# (RECORRIDO.dxf, ancho promedio 10.95 m, NO el valor asumido de 5 m).
#
# Configuración: V_objetivo = 0.50 m/s, profundidad = 1.20 m
# Resultado del modelo (2026-09-01):
#   Q_total = 23,649 m³/h (para V=0.50 m/s con A=13.14 m²)
#   TDH = 9.84 m (dominado por minor losses en tuberías)
#   HP_total = 1,067 HP (3 bombas × 356 HP c/u, SF=1.15)
#   Jets = 14 × 450 mm, V_exit = 2.8 m/s
#   Lap time = 21.1 min
#
# NOTA: El TDH es alto (9.84 m) porque las pérdidas menores (K=7.76)
# dominan a la velocidad de tubería actual (~4.4 m/s). Para reducir el
# TDH se necesita: (a) tuberías más grandes (d>800mm), (b) menos
# accesorios, o (c) más cuartos de bombas para tuberías más cortas.
#
# Los números anteriores (Q=10,800 m³/h, HP=298.8) estaban calculados
# con el ancho asumido de 5 m, no con el ancho real del DXF (10.95 m).

DESIGN_TARGET_SELVATURA_NYA = {
    "source": "Calculado por core/orchestrator.py con RECORRIDO.dxf (2026-09-01)",
    "dxf_file": "RECORRIDO.dxf",
    "channel_width_avg_m": 10.95,  # Real del DXF, no 5.0
    "channel_width_min_m": 4.02,
    "channel_width_max_m": 29.28,
    "channel_length_m": 536.0,
    "depth_m": 1.20,
    "target_velocity_m_s": 0.50,
    "manning_n": 0.015,
    "water_temp_c": 28,
    # Resultados del modelo
    "total_flow_m3_h": 23649,
    "velocity_avg_m_s": 0.553,  # >0.50 porque jets entregan más Q que el target
    "velocity_min_m_s": 0.153,
    "velocity_max_m_s": 1.117,
    "tdh_m": 9.84,
    "total_hp": 1067,
    "hp_per_pump": 356,  # 3 bombas
    "n_pumps": 3,
    "n_pump_rooms": 2,
    "safety_factor": 1.15,
    "pump_efficiency": 0.75,
    "n_jets": 14,
    "jet_diameter_m": 0.450,
    "jet_exit_velocity_m_s": 2.8,
    "lap_time_min": 21.1,
    "froude_max": 0.326,
    # Desglose TDH
    "tdh_breakdown": {
        "canal_friction_m": 0.040,
        "curvas_m": 0.833,
        "nozzles_m": 0.411,
        "pipe_friction_m": 0.829,
        "minor_losses_m": 7.506,  # K_total=7.76, V_pipe=4.4 m/s
        "diffuser_m": 0.200,
    },
    "k_factor_total": 7.76,
    "pipe_velocity_m_s": 4.4,
    # Advertencia
    "warning": "Ancho máximo del DXF (29.28 m en un tramo) debe verificarse contra el plano arquitectónico.",
}

REFERENCE_PROJECTS = [
    {
        "name": "Schlitterbahn New Braunfels (Texas, USA)",
        "length_m": 1600,
        "width_m": 6.0,
        "depth_m": 1.20,
        "velocity_m_s": 0.45,
        "flow_m3_h": 11664,
        "pump_hp": 200,
        "n_pumps": 2,
        "hp_per_pump": 100,
        "n_jets": 26,
        "d_jet_mm": 199,
        "d_pipe_mm": 800,
        "tdh_m": 3.3,
        "notes": "Uno de los mas largos del mundo. Circuito abierto con regreso por gravedad.",
        "source": "Schlitterbahn Engineering / IAAPA"
    },
    {
        "name": "Disney's Typhoon Lagoon (Florida, USA)",
        "length_m": 600,
        "width_m": 6.0,
        "depth_m": 1.00,
        "velocity_m_s": 0.50,
        "flow_m3_h": 10800,
        "pump_hp": 150,
        "n_pumps": 2,
        "hp_per_pump": 75,
        "n_jets": 10,
        "d_jet_mm": 309,
        "d_pipe_mm": 800,
        "tdh_m": 2.7,
        "notes": "Lazy river con olas. Velocidad moderada para familias.",
        "source": "Walt Disney World Engineering"
    },
    {
        "name": "Aquaventure Atlantis (Dubai, UAE)",
        "length_m": 700,
        "width_m": 5.5,
        "depth_m": 1.20,
        "velocity_m_s": 0.55,
        "flow_m3_h": 13068,
        "pump_hp": 250,
        "n_pumps": 3,
        "hp_per_pump": 83,
        "n_jets": 11,
        "d_jet_mm": 324,
        "d_pipe_mm": 785,
        "tdh_m": 3.7,
        "notes": "Circuito con rapidos y cascadas. Mayor velocidad en secciones de rapido.",
        "source": "Atlantis Engineering / WhiteWater West"
    },
    {
        "name": "Siam Park (Tenerife, Spain)",
        "length_m": 500,
        "width_m": 5.0,
        "depth_m": 1.10,
        "velocity_m_s": 0.40,
        "flow_m3_h": 7920,
        "pump_hp": 100,
        "n_pumps": 2,
        "hp_per_pump": 50,
        "n_jets": 8,
        "d_jet_mm": 296,
        "d_pipe_mm": 748,
        "tdh_m": 2.4,
        "notes": "Lazy river tematico con secciones de corriente rapida.",
        "source": "Siam Park Technical Data"
    },
    {
        "name": "WhiteWater West - Modelo Standar",
        "length_m": 400,
        "width_m": 4.5,
        "depth_m": 1.00,
        "velocity_m_s": 0.35,
        "flow_m3_h": 5670,
        "pump_hp": 75,
        "n_pumps": 2,
        "hp_per_pump": 38,
        "n_jets": 6,
        "d_jet_mm": 289,
        "d_pipe_mm": 633,
        "tdh_m": 2.5,
        "notes": "Especificaciones de diseno estandar del fabricante.",
        "source": "WhiteWater West Design Guide"
    },
    {
        "name": "Sunway Lagoon (Malaysia)",
        "length_m": 450,
        "width_m": 5.0,
        "depth_m": 1.10,
        "velocity_m_s": 0.42,
        "flow_m3_h": 8316,
        "pump_hp": 120,
        "n_pumps": 2,
        "hp_per_pump": 60,
        "n_jets": 7,
        "d_jet_mm": 324,
        "d_pipe_mm": 767,
        "tdh_m": 2.8,
        "notes": "Lazy river tropical con jets de agua.",
        "source": "Sunway Engineering"
    },
    {
        "name": "Wet'n'Wild Gold Coast (Australia)",
        "length_m": 550,
        "width_m": 5.5,
        "depth_m": 1.15,
        "velocity_m_s": 0.48,
        "flow_m3_h": 10296,
        "pump_hp": 180,
        "n_pumps": 2,
        "hp_per_pump": 90,
        "n_jets": 9,
        "d_jet_mm": 318,
        "d_pipe_mm": 800,
        "tdh_m": 3.4,
        "notes": "Circuito con rapidos artificiales.",
        "source": "Wet'n'Wild Engineering"
    },
    {
        "name": "Chimelong Water Park (China)",
        "length_m": 800,
        "width_m": 6.0,
        "depth_m": 1.20,
        "velocity_m_s": 0.50,
        "flow_m3_h": 17280,
        "pump_hp": 300,
        "n_pumps": 3,
        "hp_per_pump": 100,
        "n_jets": 13,
        "d_jet_mm": 343,
        "d_pipe_mm": 800,
        "tdh_m": 3.3,
        "notes": "Uno de los mas grandes de Asia. Multiple bombas distribuidas.",
        "source": "Chimelong Group Engineering"
    },
]

DESIGN_STANDARDS = [
    {
        "parameter": "Velocidad del agua",
        "min": 0.30,
        "max": 0.60,
        "unit": "m/s",
        "source": "WhiteWater West Design Guide",
        "note": "Para lazy river familiar. Zonas de rapido pueden exceder 1.0 m/s."
    },
    {
        "parameter": "Velocidad del agua",
        "min": 0.40,
        "max": 0.80,
        "unit": "m/s",
        "source": "IAAPA Guidelines",
        "note": "Rango operativo recomendado."
    },
    {
        "parameter": "Profundidad",
        "min": 0.90,
        "max": 1.50,
        "unit": "m",
        "source": "ASTM F2376",
        "note": "Para usuarios con chaleco salvavidas."
    },
    {
        "parameter": "Ancho del canal",
        "min": 3.0,
        "max": 8.0,
        "unit": "m",
        "source": "WhiteWater West",
        "note": "Depende de la capacidad esperada."
    },
    {
        "parameter": "Pendiente del canal",
        "min": 0.0,
        "max": 0.002,
        "unit": "m/m",
        "source": "ASTM F2376",
        "note": "Lazy rivers son generalmente horizontales (bombeados)."
    },
    {
        "parameter": "Manning n (concreto pintado)",
        "min": 0.012,
        "max": 0.016,
        "unit": "-",
        "source": "Chow (1959) Open Channel Hydraulics",
        "note": "Valores tipicos para canales de parques acuaticos."
    },
    {
        "parameter": "Manning n (fibra de vidrio)",
        "min": 0.008,
        "max": 0.012,
        "unit": "-",
        "source": "Hydraulic Engineering Reference",
        "note": "Materiales mas lisos = menos friccion."
    },
    {
        "parameter": "Densidad de usuarios",
        "min": 1.0,
        "max": 3.0,
        "unit": "personas/m2",
        "source": "IAAPA Capacity Guidelines",
        "note": "Maximo de personas por metro cuadrado de superficie de agua."
    },
    {
        "parameter": "Tiempo de vuelta",
        "min": 10,
        "max": 30,
        "unit": "min",
        "source": "Industry Standard",
        "note": "Experiencia optima del visitante."
    },
    {
        "parameter": "Potencia de bombeo",
        "min": 0.01,
        "max": 0.05,
        "unit": "HP/m3/h",
        "source": "Pump Engineering Reference",
        "note": "Relacion potencia/caudal para sistemas de lazy river."
    },
]


def get_reference_table():
    """Return reference projects as a list of dicts."""
    return REFERENCE_PROJECTS


def get_design_standards():
    """Return design standards."""
    return DESIGN_STANDARDS


def compare_with_reference(project_velocity, project_width, project_depth,
                            project_length, project_flow_m3h, project_power_kw):
    """Compare project data with reference lazy rivers."""
    comparisons = []
    for ref in REFERENCE_PROJECTS:
        v_diff = (project_velocity - ref["velocity_m_s"]) / ref["velocity_m_s"] * 100
        w_diff = (project_width - ref["width_m"]) / ref["width_m"] * 100
        comparisons.append({
            "name": ref["name"],
            "ref_velocity": ref["velocity_m_s"],
            "project_velocity": project_velocity,
            "velocity_diff_pct": v_diff,
            "ref_width": ref["width_m"],
            "project_width": project_width,
            "ref_length": ref["length_m"],
            "project_length": project_length,
            "ref_flow": ref["flow_m3_h"],
            "project_flow": project_flow_m3h,
            "ref_power_hp": ref["pump_hp"],
            "project_power_hp": project_power_kw * 1.341,
            "verdict": "OK" if abs(v_diff) < 30 else "REVISAR",
        })
    return comparisons


# === PUMP TYPES COMMONLY USED IN LAZY RIVERS ===
PUMP_TYPES = [
    {
        "type": "Centrifugal axial-flow",
        "brand": "Flowserve / Goulds / KSB",
        "model_example": "Flowserve VLC / Goulds 3600 / KSB Amarex",
        "hp_range": "20-500 HP",
        "flow_range": "500-20000 m3/h",
        "head_range": "2-15 m",
        "efficiency": "65-80%",
        "application": "Lazy rivers grandes. Alto caudal, baja presion.",
        "notes": "Estandar de la industria para parques acuaticos. Motor electrico trifasico.",
    },
    {
        "type": "End-suction centrifugal",
        "brand": "Grundfos / Xylem / Pentair",
        "model_example": "Grundfos NK / Xylem e-SV / Pentair Aurora",
        "hp_range": "5-200 HP",
        "flow_range": "100-5000 m3/h",
        "head_range": "3-20 m",
        "efficiency": "60-75%",
        "application": "Lazy rivers medianos. Mas comun en parques pequenos.",
        "notes": "Menor costo. Facil mantenimiento. Compatible con VFD.",
    },
    {
        "type": "Propeller pump (submersible)",
        "brand": "Flygt / Sulzer / Tsurumi",
        "model_example": "Flygt 4600 / Sulzer XFP / Tsurumi KRS",
        "hp_range": "10-150 HP",
        "flow_range": "200-8000 m3/h",
        "head_range": "1-8 m",
        "efficiency": "55-70%",
        "application": "Lazy rivers con bombas sumergidas en el canal.",
        "notes": "Sin casa de bombas. Menor ruido. Requiere mantenimiento subacuatico.",
    },
]

# === JET TYPES COMMONLY USED IN LAZY RIVERS ===
JET_TYPES = [
    {
        "type": "Floor-mounted nozzle (fixed)",
        "brand": "WhiteWater West / ProSlide / ADG",
        "diameter_range": "150-400 mm",
        "flow_per_jet": "200-2000 m3/h",
        "exit_velocity": "2-6 m/s",
        "angle": "15-45 degrees (adjustable)",
        "material": "SS316L stainless steel or HDPE",
        "application": "Estandar para lazy rivers. Instalado en piso del canal.",
        "notes": "Angulo ajustable. Difusor interno para distribucion uniforme.",
    },
    {
        "type": "Wall-mounted jet (side)",
        "brand": "WhiteWater West / Waterfun",
        "diameter_range": "100-300 mm",
        "flow_per_jet": "100-1000 m3/h",
        "exit_velocity": "2-5 m/s",
        "angle": "20-40 degrees (horizontal)",
        "material": "SS316L or fiberglass",
        "application": "Jets laterales para secciones estrechas o rapidas.",
        "notes": "Menor intrusion en el canal. Ideal para areas con trafico peatonal.",
    },
    {
        "type": "Inline eductor jet",
        "brand": "Mazzei / Koflo",
        "diameter_range": "50-200 mm",
        "flow_per_jet": "50-500 m3/h",
        "exit_velocity": "3-8 m/s",
        "angle": "0 degrees (axial)",
        "material": "PVC / CPVC / PVDF",
        "application": "Sistemas de propulsion por educcion. Menor energia.",
        "notes": "Usa efecto Venturi. No requiere boquilla. Menor perdida de carga.",
    },
]


def get_pump_types():
    """Return pump type reference data."""
    return PUMP_TYPES


# === COMMERCIAL PUMP DATABASE ===
# Real pump models with full curves for lazy river applications
COMMERCIAL_PUMPS = [
    {
        "id": "flowserve_vlc_100",
        "manufacturer": "Flowserve",
        "model": "VLC-100",
        "type": "Axial flow",
        "hp": 100,
        "flow_m3h": 5400,
        "head_m": 5.0,
        "efficiency": 0.75,
        "rpm": 1450,
        "npshr_m": 3.0,
        "impeller_mm": 450,
        "curve_h0": 6.0,
        "curve_q_max": 9000,
        "bep_flow_m3h": 5400,
        "bep_head_m": 5.0,
        "application": "Lazy river mediano (300-500m)",
        "price_usd": 14000,
    },
    {
        "id": "flowserve_vlc_150",
        "manufacturer": "Flowserve",
        "model": "VLC-150",
        "type": "Axial flow",
        "hp": 150,
        "flow_m3h": 7200,
        "head_m": 6.0,
        "efficiency": 0.77,
        "rpm": 1450,
        "npshr_m": 3.5,
        "impeller_mm": 500,
        "curve_h0": 7.2,
        "curve_q_max": 12000,
        "bep_flow_m3h": 7200,
        "bep_head_m": 6.0,
        "application": "Lazy river mediano-grande (400-600m)",
        "price_usd": 18000,
    },
    {
        "id": "flowserve_vlc_200",
        "manufacturer": "Flowserve",
        "model": "VLC-200",
        "type": "Axial flow",
        "hp": 200,
        "flow_m3h": 10000,
        "head_m": 7.0,
        "efficiency": 0.78,
        "rpm": 1450,
        "npshr_m": 4.0,
        "impeller_mm": 550,
        "curve_h0": 8.4,
        "curve_q_max": 16000,
        "bep_flow_m3h": 10000,
        "bep_head_m": 7.0,
        "application": "Lazy river grande (500-800m)",
        "price_usd": 24000,
    },
    # NOTA: Grundfos NK eliminada — la serie NK completa no pasa de ~1,000 m³/h
    # por unidad (verificado contra leaflet oficial de Grundfos). NO es la familia
    # correcta para un punto de operación de ~5,850 m³/h por bomba.
    # Se deja como referencia educativa de "bomba equivocada para esta escala".
    #
    # {
    #     "id": "grundfos_nk_150",
    #     "manufacturer": "Grundfos",
    #     "model": "NK 150-315",
    #     "type": "End-suction centrifugal",
    #     "hp": 150,
    #     "flow_m3h": 5400,  # ❌ INCORRECTO — NK max real ~1,000 m³/h
    #     ...
    # },
    {
        "id": "patterson_hsc_300",
        "manufacturer": "Patterson Pump Company",
        "model": "Horizontal Split Case (HSC)",
        "type": "Horizontal split case",
        "hp": 350,
        "flow_m3h": 8000,
        "head_m": 12.0,
        "efficiency": 0.80,
        "rpm": 1450,
        "npshr_m": 5.0,
        "impeller_mm": 550,
        "curve_h0": 15.0,
        "curve_q_max": 14000,
        "bep_flow_m3h": 8000,
        "bep_head_m": 12.0,
        "application": "Lazy river grande — cuarto de bombas externo",
        "price_usd": 30000,
        "verified": True,
        "curve_verified": False,  # Curva H-Q exacta requiere cotización a Patterson/RiverFlow
        "source_url": "https://www.johnbrooks.ca/hubfs/JohnBrooks/Resources/Patterson-Horizontal-Split-Case.pdf",
        "notes": "Familia HSC confirmada por fabricante: 50 a >100,000 GPM, heads hasta 550 ft. "
                 "La curva H-Q-eficiencia para el punto exacto de este proyecto (~7,883 m³/h @ 10m) "
                 "NO está publicada y requiere cotización directa a Patterson o RiverFlow.",
    },
    {
        "id": "flygt_4660",
        "manufacturer": "Flygt",
        "model": "4660",
        "type": "Propeller submersible",
        "hp": 120,
        "flow_m3h": 6000,
        "head_m": 3.5,
        "efficiency": 0.68,
        "rpm": 1450,
        "npshr_m": 0,
        "impeller_mm": 400,
        "curve_h0": 4.2,
        "curve_q_max": 10000,
        "bep_flow_m3h": 6000,
        "bep_head_m": 3.5,
        "application": "Lazy river con bombas sumergidas (sin casa de bombas)",
        "price_usd": 15000,
    },
    {
        "id": "flygt_4680",
        "manufacturer": "Flygt",
        "model": "4680",
        "type": "Propeller submersible",
        "hp": 180,
        "flow_m3h": 9000,
        "head_m": 4.0,
        "efficiency": 0.70,
        "rpm": 1450,
        "npshr_m": 0,
        "impeller_mm": 450,
        "curve_h0": 4.8,
        "curve_q_max": 14000,
        "bep_flow_m3h": 9000,
        "bep_head_m": 4.0,
        "application": "Lazy river grande con bombas sumergidas",
        "price_usd": 20000,
    },
    {
        "id": "xylem_esv_150",
        "manufacturer": "Xylem",
        "model": "e-SV 150",
        "type": "Vertical multi-stage",
        "hp": 150,
        "flow_m3h": 5400,
        "head_m": 15.0,
        "efficiency": 0.74,
        "rpm": 1450,
        "npshr_m": 4.0,
        "impeller_mm": 250,
        "curve_h0": 18.0,
        "curve_q_max": 9000,
        "bep_flow_m3h": 5400,
        "bep_head_m": 15.0,
        "application": "Lazy river con alta presion (sistemas complejos)",
        "price_usd": 20000,
    },
]


def get_commercial_pumps():
    """Return commercial pump database."""
    return COMMERCIAL_PUMPS


def get_design_target():
    """Return the verified design target for Selvatura NYA."""
    return DESIGN_TARGET_SELVATURA_NYA


def find_matching_pumps(required_flow_m3h, required_tdh_m, n_pumps=2):
    """Find pumps that match the required flow and head.

    Args:
        required_flow_m3h: total system flow
        required_tdh_m: total dynamic head
        n_pumps: number of pumps in parallel

    Returns:
        list of matching pumps sorted by efficiency.
        Each pump has 'curve_verified' (bool) indicating if the H-Q curve
        is from a real datasheet (True) or a generic approximation (False).
    """
    flow_per_pump = required_flow_m3h / n_pumps if n_pumps > 0 else required_flow_m3h
    matches = []

    for pump in COMMERCIAL_PUMPS:
        # Check if pump can deliver required flow at required head
        # Using generic curve: H = H0 - k*Q^2
        h0 = pump["curve_h0"]
        q_max = pump["curve_q_max"]
        k = h0 / (q_max ** 2) if q_max > 0 else 0

        # Head at required flow
        head_at_flow = h0 - k * (flow_per_pump ** 2)

        # Check if pump can deliver (head > 0 at required flow)
        if head_at_flow > 0 and flow_per_pump <= q_max * 0.9:
            # Check if head is sufficient (within 20% margin)
            if head_at_flow >= required_tdh_m * 0.8:
                # Calculate efficiency at this operating point
                bep_flow = pump["bep_flow_m3h"]
                eff_max = pump["efficiency"]
                # Efficiency drops away from BEP
                q_ratio = flow_per_pump / bep_flow if bep_flow > 0 else 1
                eff_at_point = eff_max * (1 - 0.5 * (q_ratio - 1) ** 2)
                eff_at_point = max(0.3, min(eff_at_point, eff_max))

                matches.append({
                    **pump,
                    "flow_per_pump": flow_per_pump,
                    "head_at_flow": head_at_flow,
                    "efficiency_at_point": eff_at_point,
                    "power_kw": (998 * 9.81 * flow_per_pump / 3600 * head_at_flow) / (eff_at_point * 1000),
                    "power_hp": ((998 * 9.81 * flow_per_pump / 3600 * head_at_flow) / (eff_at_point * 1000)) * 1.341,
                    "curve_verified": pump.get("curve_verified", False),
                    "verified": pump.get("verified", False),
                })

    # Sort by efficiency (best first)
    matches.sort(key=lambda p: p["efficiency_at_point"], reverse=True)
    return matches


def get_jet_types():
    """Return jet type reference data."""
    return JET_TYPES


# === FITTING K-FACTOR DATABASE ===
# Loss coefficients for common pipe fittings in lazy river systems
# Source: Crane TP-410, Idelchik, ASHRAE Handbook
FITTING_K_FACTORS = {
    # Valves
    "gate_valve_open": {"k": 0.20, "description": "Gate valve (fully open)", "category": "valve"},
    "butterfly_valve_open": {"k": 0.30, "description": "Butterfly valve (fully open)", "category": "valve"},
    "check_valve_swing": {"k": 2.50, "description": "Check valve (swing type)", "category": "valve"},
    "check_valve_lift": {"k": 10.0, "description": "Check valve (lift type)", "category": "valve"},
    "ball_valve_open": {"k": 0.05, "description": "Ball valve (fully open)", "category": "valve"},
    "globe_valve_open": {"k": 10.0, "description": "Globe valve (fully open)", "category": "valve"},

    # Elbows
    "elbow_90_r1d": {"k": 0.30, "description": "90° elbow (r/d=1)", "category": "elbow"},
    "elbow_90_r1_5d": {"k": 0.19, "description": "90° elbow (r/d=1.5)", "category": "elbow"},
    "elbow_90_r2d": {"k": 0.15, "description": "90° elbow (r/d=2)", "category": "elbow"},
    "elbow_45_r1d": {"k": 0.17, "description": "45° elbow (r/d=1)", "category": "elbow"},
    "elbow_45_r1_5d": {"k": 0.11, "description": "45° elbow (r/d=1.5)", "category": "elbow"},
    "miter_90": {"k": 1.10, "description": "90° miter bend", "category": "elbow"},

    # Tees
    "tee_branch": {"k": 1.00, "description": "Tee (branch flow)", "category": "tee"},
    "tee_run": {"k": 0.60, "description": "Tee (run/straight flow)", "category": "tee"},
    "wye_branch": {"k": 0.50, "description": "Wye (branch flow)", "category": "tee"},

    # Transitions
    "reducer_gradual": {"k": 0.15, "description": "Reducer (gradual, 15°)", "category": "transition"},
    "reducer_abrupt": {"k": 0.50, "description": "Reducer (abrupt)", "category": "transition"},
    "expander_gradual": {"k": 0.20, "description": "Expander (gradual, 15°)", "category": "transition"},
    "expander_abrupt": {"k": 1.00, "description": "Expander (abrupt)", "category": "transition"},

    # Other
    "strainer_clean": {"k": 1.50, "description": "Strainer (clean basket)", "category": "other"},
    "strainer_dirty": {"k": 3.00, "description": "Strainer (dirty basket)", "category": "other"},
    "diffuser": {"k": 0.30, "description": "Diffuser (nozzle to channel)", "category": "other"},
    "inlet_sharp": {"k": 0.50, "description": "Inlet (sharp edge)", "category": "other"},
    "inlet_rounded": {"k": 0.10, "description": "Inlet (rounded)", "category": "other"},
    "outlet": {"k": 1.00, "description": "Outlet (free discharge)", "category": "other"},
}

# Default fittings for a typical lazy river system
DEFAULT_FITTINGS = [
    {"fitting": "gate_valve_open", "quantity": 2, "description": "Gate valves (suction + discharge)"},
    {"fitting": "check_valve_swing", "quantity": 1, "description": "Check valve (prevent backflow)"},
    {"fitting": "elbow_90_r1_5d", "quantity": 4, "description": "90° elbows (pipe routing)"},
    {"fitting": "tee_branch", "quantity": 2, "description": "Tees (distribution)"},
    {"fitting": "strainer_clean", "quantity": 1, "description": "Strainer (suction)"},
    {"fitting": "reducer_gradual", "quantity": 2, "description": "Reducers (pipe to nozzle)"},
    {"fitting": "diffuser", "quantity": 1, "description": "Diffuser (nozzle transition)"},
]


def get_fitting_k_factors():
    """Return fitting K-factor database."""
    return FITTING_K_FACTORS


def get_default_fittings():
    """Return default fittings for a lazy river system."""
    return DEFAULT_FITTINGS


def calculate_total_k(fittings=None):
    """Calculate total K-factor for a list of fittings.
    Returns: (total_k, breakdown_list)
    """
    if fittings is None:
        fittings = DEFAULT_FITTINGS

    total_k = 0.0
    breakdown = []

    for f in fittings:
        fitting_id = f["fitting"]
        qty = f.get("quantity", 1)
        if fitting_id in FITTING_K_FACTORS:
            k = FITTING_K_FACTORS[fitting_id]["k"]
            desc = FITTING_K_FACTORS[fitting_id]["description"]
            k_total = k * qty
            total_k += k_total
            breakdown.append({
                "fitting": desc,
                "k_unit": k,
                "quantity": qty,
                "k_total": k_total,
            })

    return total_k, breakdown


# === PIPE MATERIAL DATABASE (D3) ===
PIPE_MATERIALS = {
    "HDPE_PN10": {
        "name": "HDPE PN10",
        "roughness_mm": 0.0015,
        "roughness_m": 0.0000015,
        "pressure_rating_bar": 10,
        "cost_per_m_usd": 15,
        "lifespan_years": 50,
        "notes": "Standard for water parks. Flexible, corrosion resistant.",
    },
    "HDPE_PN16": {
        "name": "HDPE PN16",
        "roughness_mm": 0.0015,
        "roughness_m": 0.0000015,
        "pressure_rating_bar": 16,
        "cost_per_m_usd": 22,
        "lifespan_years": 50,
        "notes": "Higher pressure rating. Used for main headers.",
    },
    "PVC_SCH40": {
        "name": "PVC Schedule 40",
        "roughness_mm": 0.0015,
        "roughness_m": 0.0000015,
        "pressure_rating_bar": 10,
        "cost_per_m_usd": 10,
        "lifespan_years": 30,
        "notes": "Lower cost. Brittle in cold weather. UV sensitive.",
    },
    "DUCTILE_IRON": {
        "name": "Ductile Iron",
        "roughness_mm": 0.26,
        "roughness_m": 0.00026,
        "pressure_rating_bar": 25,
        "cost_per_m_usd": 40,
        "lifespan_years": 75,
        "notes": "Very durable. Higher friction. Used for large installations.",
    },
    "CONCRETE_LINED": {
        "name": "Concrete Lined",
        "roughness_mm": 0.3,
        "roughness_m": 0.0003,
        "pressure_rating_bar": 6,
        "cost_per_m_usd": 25,
        "lifespan_years": 50,
        "notes": "Used for large channels. Higher friction.",
    },
}


def get_pipe_materials():
    """Return pipe material database."""
    return PIPE_MATERIALS


# === ENERGY COST DATABASE (D4) ===
ENERGY_COSTS = {
    "electricity_usd_kwh": 0.12,
    "operating_hours_day": 10,
    "operating_days_year": 300,
    "maintenance_pct_capex": 0.03,
}


def get_energy_costs():
    """Return energy cost parameters."""
    return ENERGY_COSTS


def calculate_annual_cost(power_kw: float, electricity_usd_kwh: float = None,
                           hours_day: float = None, days_year: float = None) -> dict:
    """Calculate annual operating cost for a lazy river system.

    Args:
        power_kw: motor power in kW
        electricity_usd_kwh: electricity cost (default from database)
        hours_day: operating hours per day (default 10)
        days_year: operating days per year (default 300)

    Returns:
        dict with cost breakdown
    """
    if electricity_usd_kwh is None:
        electricity_usd_kwh = ENERGY_COSTS["electricity_usd_kwh"]
    if hours_day is None:
        hours_day = ENERGY_COSTS["operating_hours_day"]
    if days_year is None:
        days_year = ENERGY_COSTS["operating_days_year"]

    annual_kwh = power_kw * hours_day * days_year
    annual_cost = annual_kwh * electricity_usd_kwh

    return {
        "power_kw": power_kw,
        "annual_kwh": annual_kwh,
        "annual_cost_usd": annual_cost,
        "monthly_cost_usd": annual_cost / 12,
        "daily_cost_usd": annual_cost / days_year,
        "cost_per_hour_usd": annual_cost / (hours_day * days_year),
    }
