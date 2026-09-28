"""Source-linked commercial pump families for *screening*, not final selection.

The public literature below does not supply a project-specific duty point.
Published family maximum flow is an upper bound, never a flow at NYA TDH.
"""

from dataclasses import dataclass


US_GPM_TO_M3_H = 0.22712470704


@dataclass(frozen=True)
class PumpFamily:
    name: str
    examples: str
    hp_range: str
    rpm: str
    frequency: str
    ports: str
    published_max_m3_h: float | None
    source_url: str
    curve_url: str
    note: str


PUMP_FAMILIES = (
    PumpFamily(
        "Pentair EQ Series", "EQK500–EQK1500", "5–15 HP", "3.450 rpm",
        "60 Hz (hay variantes de 50 Hz)", "Con prefiltro: succión 6″, descarga 4″",
        800 * US_GPM_TO_M3_H,
        "https://www.pentair.com/content/dam/extranet/nam/pentair-pool/commercial/"
        "pumps/eq-series/brochure/eq-series-commercial-pump-brochure-english.pdf",
        "https://www.pentair.com/content/dam/extranet/nam/pentair-pool/commercial/"
        "pumps/eq-series/brochure/eq-series-commercial-pump-brochure-english.pdf",
        "El máximo de 800 US gpm es para la familia a condiciones no especificadas; "
        "no es caudal a la TDH de NYA."),
    PumpFamily(
        "Speck BADU Block Multi", "125/250, variantes de 20–30 HP", "5,5–30 HP",
        "1.750 rpm", "Confirmar variante local", "Según modelo: 6″–8″ de succión; salida variable",
        None,
        "https://usa.speck-pumps.com/wp-content/uploads/Flyer-BADU-Block-Multi.pdf",
        "https://usa.speck-pumps.com/wp-content/uploads/Flyer-BADU-Block-Multi.pdf",
        "La ficha publica curvas por modelo; aún no se ha digitalizado un punto Q–H "
        "fiable para la TDH de NYA."),
    PumpFamily(
        "Speck BADU Block", "Serie 150/250, 40–60 HP", "40–60 HP",
        "1.750 rpm", "Confirmar variante local", "Según configuración; consultar ficha",
        3000 * US_GPM_TO_M3_H,
        "https://usa.speck-pumps.com/badu-block/",
        "https://usa.speck-pumps.com/wp-content/uploads/"
        "Performance-Curves-BADU-Block-Normblock-40-50-60HP.pdf",
        "Hasta 3.000 US gpm es el máximo anunciado de la familia, no el caudal "
        "garantizado a la TDH de NYA."),
)


def screen_pump_families(required_flow_m3_h: float, duty_pumps: int):
    """Eliminate only families whose published *ceiling* is too low."""
    if required_flow_m3_h <= 0 or duty_pumps < 1:
        raise ValueError("Caudal y bombas en servicio deben ser positivos.")
    per_pump = required_flow_m3_h / duty_pumps
    output = []
    for family in PUMP_FAMILIES:
        ceiling = family.published_max_m3_h
        impossible = ceiling is not None and per_pump > ceiling
        output.append({
            "family": family,
            "required_per_pump_m3_h": per_pump,
            "screening": ("Descartada para esta cantidad de bombas: supera el máximo publicado"
                          if impossible else "Revisar curva Q–H a la TDH real"),
        })
    return output
