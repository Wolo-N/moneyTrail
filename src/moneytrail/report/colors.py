"""Paleta del Sankey (dataviz reference palette, validada) en modo claro y
oscuro. El color sigue al rol del nodo, no a su posición; las categorías de
gasto toman los slots categóricos restantes en orden fijo por tamaño y el
sobrante cae en gris."""

from __future__ import annotations

ROLE_COLORS_LIGHT = {
    "income": "#008300",  # slot 4 (green)
    "account": "#2a78d6",  # slot 1 (blue)
    "savings": "#1baf7a",  # slot 2 (aqua)
    "opening": "#898781",  # muted ink
    "internal": "#898781",
}
ROLE_COLORS_DARK = {
    "income": "#008300",
    "account": "#3987e5",
    "savings": "#199e70",
    "opening": "#898781",
    "internal": "#898781",
}
EXPENSE_SLOTS_LIGHT = ["#eda100", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834", "#0d366b", "#104281"]
EXPENSE_SLOTS_DARK = ["#c98500", "#9085e9", "#e66767", "#d55181", "#d95926", "#6da7ec", "#5598e7"]
MUTED = "#898781"


def expense_top_colors(data, dark: bool = False) -> dict[str, str]:
    """Asigna un slot fijo a cada categoría top de gasto, ordenadas por monto
    (estable dentro de un período; el color sigue a la entidad)."""
    slots = EXPENSE_SLOTS_DARK if dark else EXPENSE_SLOTS_LIGHT
    tops = sorted(
        {n for n, role in data.node_roles.items() if role == "expense_top"},
        key=lambda n: -sum(v for (s, d), v in data.flows.items() if d == n),
    )
    return {top: (slots[i] if i < len(slots) else MUTED) for i, top in enumerate(tops)}


def node_color(data, label: str, top_colors: dict[str, str], dark: bool = False) -> str:
    role = data.node_roles[label]
    if role == "expense_top":
        return top_colors[label]
    if role == "expense_sub":
        return top_colors.get(label.split(" · ")[0], MUTED)
    return (ROLE_COLORS_DARK if dark else ROLE_COLORS_LIGHT)[role]
