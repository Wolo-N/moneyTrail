"""Analítica derivada de los movimientos: tendencias, comercios, suscripciones
y comparaciones mes a mes.

Todo se calcula en una sola pasada sobre las transacciones (son cientos, no
millones) y en `Decimal`; la conversión a float ocurre sólo al serializar a
JSON. Los flujos internos (transferencias entre cuentas propias y pagos de
tarjeta) nunca cuentan como ingreso ni gasto: ya se contaron en el consumo
original.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal

from . import db
from .models import Kind

EXPENSE_KINDS = (str(Kind.EXPENSE), str(Kind.TAX), str(Kind.FEE), str(Kind.INTEREST), str(Kind.FX))
INTERNAL_KINDS = (str(Kind.TRANSFER_INTERNAL), str(Kind.CARD_PAYMENT))
UNCATEGORIZED = "Sin categorizar"
SAVINGS_TOP = "Ahorro"  # gastos que en realidad son ahorro (compra de dólares)

# Palabras/tokens que no identifican al comercio: números de referencia, de
# cupón o de terminal, que si no separarían 'RAPPI 6248' de 'RAPPI 6249'.
_REF_TOKEN_RE = re.compile(r"\b\w*\d{4,}\w*\b")
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _is_ref_code(segment: str) -> bool:
    """¿Es un código de referencia y no parte del nombre del comercio?

    Los pasarelas de pago cuelgan un identificador de la operación después de
    un '*' ('AUDIBLE*D394Z77J3', 'AUDIBLE*GI2KN71A3'): cambia en cada cobro,
    así que sin sacarlo el mismo servicio se cuenta como dos comercios
    distintos. Se reconoce por mezclar letras con varios dígitos.
    """
    digits = sum(c.isdigit() for c in segment)
    return len(segment) >= 5 and digits >= 2 and any(c.isalpha() for c in segment)


def merchant_key(description: str, counterparty: str = "") -> str:
    """Nombre normalizado del comercio: agrupa 'RAPPI 624875624875', 'Rappi' y
    'RAPPI 707314707314' bajo la misma entidad."""
    base = (counterparty or "").strip() or (description or "").strip()
    cleaned = _REF_TOKEN_RE.sub(" ", base.upper())
    tokens = []
    for token in cleaned.split():
        # Los segmentos separados por '*' se evalúan por separado: 'MERPAGO*BETTIGA'
        # conserva las dos partes, 'AUDIBLE*GI2KN71A3' pierde sólo la referencia.
        kept = [seg for seg in token.split("*") if seg and not _is_ref_code(seg)]
        if kept and _HAS_LETTER_RE.search("".join(kept)):
            tokens.append("*".join(kept))
    return " ".join(tokens).strip(" -·*") or base.upper() or "(sin descripción)"


# Transferencias a personas: los bancos las escriben como '<CUIT> - NOMBRE'
# o directamente 'APELLIDO, NOMBRE'.
_PERSON_TRANSFER_RE = re.compile(r"^\s*(\d{8,11}\s*-\s*\S|[A-ZÑÁÉÍÓÚ][\w'ÑÁÉÍÓÚ]+\s*,\s*[A-ZÑÁÉÍÓÚ])")


def known_merchants(conn: sqlite3.Connection) -> dict[str, str]:
    """Comercio normalizado → categoría más usada, entre lo ya categorizado."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in conn.execute("SELECT description, counterparty, category FROM tx WHERE category IS NOT NULL"):
        counts[merchant_key(r["description"], r["counterparty"])][r["category"]] += 1
    return {m: max(cats, key=cats.get) for m, cats in counts.items()}


def suggest_category(
    description: str, counterparty: str, known: dict[str, str], available: list[str]
) -> str | None:
    """Mejor apuesta para un gasto sin categorizar, o None si no hay señal.

    Primero mira si ese mismo comercio ya fue clasificado antes; si no, detecta
    las transferencias a personas, que son el grueso de lo que queda suelto.
    """
    key = merchant_key(description, counterparty)
    if key in known:
        return known[key]
    text = (counterparty or description or "").strip()
    if _PERSON_TRANSFER_RE.match(text) or _PERSON_TRANSFER_RE.match(description or ""):
        for candidate in ("Transferencias a terceros", "Transferencias"):
            if candidate in available:
                return candidate
    return None


def to_ars(amount: Decimal, currency: str, usd_rate: Decimal) -> Decimal:
    return amount * usd_rate if currency == "USD" else amount


def _split_category(category: str | None) -> tuple[str, str | None]:
    if not category:
        return UNCATEGORIZED, None
    top, _, sub = category.partition("/")
    return top, (sub or None)


def _month_range(start: str, end: str) -> list[str]:
    """Meses 'YYYY-MM' inclusive entre dos meses, sin huecos."""
    months = []
    y, m = int(start[:4]), int(start[5:7])
    while f"{y:04d}-{m:02d}" <= end:
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def build_insights(
    conn: sqlite3.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
    usd_rate: Decimal = Decimal(1),
    top_n: int = 6,
) -> dict:
    """Todo lo que la UI necesita para explicar el período elegido.

    Las series mensuales cubren *toda* la historia (para ver la tendencia),
    mientras que los rankings y comparaciones se limitan al período pedido.
    """
    all_rows = db.fetch_txs(conn)
    in_range = [
        r
        for r in all_rows
        if (date_from is None or r["date"] >= date_from) and (date_to is None or r["date"] <= date_to)
    ]

    monthly = _monthly_series(all_rows, usd_rate)
    coverage = month_coverage(conn)
    recurring = _recurring(all_rows, usd_rate)
    cat_totals, cat_by_month, months_in_range = _category_stats(in_range, usd_rate)
    merchants = _merchant_stats(in_range, usd_rate)

    income = sum((v["income"] for v in monthly if v["month"] in months_in_range), Decimal(0))
    expense = sum((v["expense"] for v in monthly if v["month"] in months_in_range), Decimal(0))
    savings_like = sum((c["total"] for c in cat_totals if c["top"] == SAVINGS_TOP), Decimal(0))
    uncategorized = sum((c["total"] for c in cat_totals if c["top"] == UNCATEGORIZED), Decimal(0))

    days = _days_covered(in_range)
    return {
        "period": {"from": date_from, "to": date_to, "days": days, "months": months_in_range},
        "totals": {
            "income": float(income),
            "expense": float(expense),
            "savings": float(income - expense),
            "savings_rate": float(round((income - expense) / income * 100, 1)) if income else None,
            "daily_burn": float(round(expense / days, 2)) if days else 0.0,
            "savings_like": float(savings_like),
            "real_expense": float(expense - savings_like),
            "uncategorized": float(uncategorized),
            "uncategorized_share": float(round(uncategorized / expense * 100, 1)) if expense else 0.0,
            "n_transactions": len(in_range),
        },
        "monthly": [
            {
                "month": m["month"],
                "income": float(m["income"]),
                "expense": float(m["expense"]),
                "savings": float(m["income"] - m["expense"]),
                "savings_rate": float(round((m["income"] - m["expense"]) / m["income"] * 100, 1))
                if m["income"]
                else None,
                # Un mes al que le falta un extracto no es comparable con el resto
                "complete": coverage.get(m["month"], False),
            }
            for m in monthly
        ],
        "categories": _serialize_categories(cat_totals, expense),
        "category_by_month": _stacked_series(cat_by_month, cat_totals, top_n),
        "category_mom": _mom_comparison(all_rows, months_in_range, usd_rate, coverage),
        "merchants": merchants[:20],
        "recurring": recurring,
        # Sobre toda la historia, no sólo el período: una suscripción cobrada
        # el mes pasado se sigue pagando aunque no caiga en el rango elegido.
        "subscriptions": subscriptions(conn, all_rows, usd_rate, recurring),
        "biggest": _biggest(in_range, usd_rate),
    }


def month_coverage(conn: sqlite3.Connection) -> dict[str, bool]:
    """Por mes: ¿están todos los extractos, o falta alguna cuenta?

    Importa mucho para no leer mal los números: un mes al que le falta el
    resumen del banco donde entra el sueldo parece un mes catastrófico, cuando
    en realidad es un mes incompleto. La UI los marca en vez de compararlos.
    """
    periods = conn.execute("SELECT account_id, period_start, period_end FROM statement").fetchall()
    if not periods:
        return {}
    # Una cuenta sólo "debe" resúmenes desde el mes en que aparece por primera
    # vez: la que abriste en junio no tiene por qué cubrir abril. Sin esto,
    # con cuentas que arrancan en fechas distintas ningún mes sería completo.
    first_seen: dict[int, str] = {}
    for p in periods:
        acc = p["account_id"]
        first_seen[acc] = min(first_seen.get(acc, "9999-99"), p["period_start"][:7])

    months = _month_range(min(p["period_start"] for p in periods)[:7], max(p["period_end"] for p in periods)[:7])
    coverage = {}
    for month in months:
        expected = {acc for acc, since in first_seen.items() if since <= month}
        present = {p["account_id"] for p in periods if p["period_start"][:7] <= month <= p["period_end"][:7]}
        coverage[month] = expected.issubset(present)
    return coverage


def _days_covered(rows: list[sqlite3.Row]) -> int:
    dates = [r["date"] for r in rows]
    if not dates:
        return 0
    d0, d1 = date.fromisoformat(min(dates)), date.fromisoformat(max(dates))
    return (d1 - d0).days + 1


def _monthly_series(rows: list[sqlite3.Row], usd_rate: Decimal) -> list[dict]:
    buckets: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"income": Decimal(0), "expense": Decimal(0)})
    for r in rows:
        if r["kind"] in INTERNAL_KINDS:
            continue
        value = to_ars(db.amount(r), r["currency"], usd_rate)
        month = r["date"][:7]
        if r["kind"] == str(Kind.INCOME) and value > 0:
            buckets[month]["income"] += value
        elif r["kind"] in EXPENSE_KINDS and value < 0:
            buckets[month]["expense"] += -value
    if not buckets:
        return []
    # Rellenar los meses sin movimientos para que la serie no mienta con saltos
    return [
        {"month": m, "income": buckets[m]["income"], "expense": buckets[m]["expense"]}
        for m in _month_range(min(buckets), max(buckets))
    ]


def _category_stats(
    rows: list[sqlite3.Row], usd_rate: Decimal
) -> tuple[list[dict], dict[str, dict[str, Decimal]], list[str]]:
    totals: dict[str, dict] = {}
    by_month: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    months: set[str] = set()
    for r in rows:
        months.add(r["date"][:7])
        if r["kind"] not in EXPENSE_KINDS:
            continue
        value = to_ars(db.amount(r), r["currency"], usd_rate)
        if value >= 0:
            continue
        top, sub = _split_category(r["category"])
        name = r["category"] or UNCATEGORIZED
        entry = totals.setdefault(name, {"category": name, "top": top, "sub": sub, "total": Decimal(0), "n": 0})
        entry["total"] += -value
        entry["n"] += 1
        by_month[top][r["date"][:7]] += -value
    ordered = sorted(totals.values(), key=lambda c: -c["total"])
    return ordered, by_month, sorted(months)


def _serialize_categories(cat_totals: list[dict], expense: Decimal) -> list[dict]:
    return [
        {
            "category": c["category"],
            "top": c["top"],
            "sub": c["sub"],
            "total": float(c["total"]),
            "n": c["n"],
            "avg": float(round(c["total"] / c["n"], 2)) if c["n"] else 0.0,
            "share": float(round(c["total"] / expense * 100, 1)) if expense else 0.0,
        }
        for c in cat_totals
    ]


def _stacked_series(
    by_month: dict[str, dict[str, Decimal]], cat_totals: list[dict], top_n: int
) -> dict:
    """Serie apilada por mes: las `top_n` categorías de nivel 1 más grandes y
    el resto agrupado en 'Otras', para que el gráfico no se vuelva ilegible."""
    if not by_month:
        return {"months": [], "series": []}
    tops_by_size: list[str] = []
    for c in cat_totals:  # ya viene ordenado por monto
        if c["top"] not in tops_by_size:
            tops_by_size.append(c["top"])
    months = sorted({m for buckets in by_month.values() for m in buckets})
    months = _month_range(months[0], months[-1])
    keep, rest = tops_by_size[:top_n], tops_by_size[top_n:]
    series = [
        {"name": top, "values": [float(by_month[top].get(m, Decimal(0))) for m in months]} for top in keep
    ]
    if rest:
        series.append(
            {
                "name": "Otras",
                "values": [float(sum(by_month[t].get(m, Decimal(0)) for t in rest)) for m in months],
            }
        )
    return {"months": months, "series": series}


def _mom_comparison(
    rows: list[sqlite3.Row],
    months_in_range: list[str],
    usd_rate: Decimal,
    coverage: dict[str, bool] | None = None,
) -> dict:
    """Gasto por categoría del último mes completo vs el mes anterior.

    Se elige el último mes *completo* a propósito: comparar contra un mes al
    que le faltan extractos (o que recién empezó) muestra caídas del 100% en
    todas las categorías y no dice nada.
    """
    if not months_in_range:
        return {"current_month": None, "previous_month": None, "rows": [], "partial": False}
    coverage = coverage or {}
    complete = [m for m in months_in_range if coverage.get(m, True)]
    current = complete[-1] if complete else months_in_range[-1]
    previous = _prev_month(current)
    buckets: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"current": Decimal(0), "previous": Decimal(0)})
    for r in rows:
        month = r["date"][:7]
        if month not in (current, previous) or r["kind"] not in EXPENSE_KINDS:
            continue
        value = to_ars(db.amount(r), r["currency"], usd_rate)
        if value >= 0:
            continue
        buckets[r["category"] or UNCATEGORIZED]["current" if month == current else "previous"] += -value
    out = []
    for name, vals in buckets.items():
        cur, prev = vals["current"], vals["previous"]
        out.append(
            {
                "category": name,
                "current": float(cur),
                "previous": float(prev),
                "delta": float(cur - prev),
                "delta_pct": float(round((cur - prev) / prev * 100, 1)) if prev else None,
            }
        )
    return {
        "current_month": current,
        "previous_month": previous,
        "partial": not coverage.get(current, True),
        "rows": sorted(out, key=lambda r: -abs(r["delta"])),
    }


def _merchant_stats(rows: list[sqlite3.Row], usd_rate: Decimal) -> list[dict]:
    buckets: dict[str, dict] = {}
    for r in rows:
        if r["kind"] not in EXPENSE_KINDS:
            continue
        value = to_ars(db.amount(r), r["currency"], usd_rate)
        if value >= 0:
            continue
        key = merchant_key(r["description"], r["counterparty"])
        entry = buckets.setdefault(
            key, {"merchant": key, "total": Decimal(0), "n": 0, "last_date": "", "categories": set()}
        )
        entry["total"] += -value
        entry["n"] += 1
        entry["last_date"] = max(entry["last_date"], r["date"])
        if r["category"]:
            entry["categories"].add(r["category"])
    return [
        {
            "merchant": e["merchant"],
            "total": float(e["total"]),
            "n": e["n"],
            "avg": float(round(e["total"] / e["n"], 2)),
            "last_date": e["last_date"],
            "category": sorted(e["categories"])[0] if e["categories"] else None,
        }
        for e in sorted(buckets.values(), key=lambda e: -e["total"])
    ]


def _recurring(rows: list[sqlite3.Row], usd_rate: Decimal, min_months: int = 2) -> list[dict]:
    """Gastos que vuelven todos los meses, en dos sabores:

    - **fijo**: mismo comercio y prácticamente el mismo importe (suscripciones,
      abonos, cocheras). Acá viven los aumentos silenciosos, por eso se calcula
      cuánto cambió el último importe contra el primero.
    - **variable**: mismo comercio todos los meses pero importe distinto
      (delivery, transporte). No es una suscripción, es un hábito — y suele
      pesar más que las suscripciones juntas.

    Alcanza con verlo en 2 meses distintos: con pocos meses importados exigir 3
    dejaría la sección vacía justo cuando más sirve.
    """
    buckets: dict[str, list[tuple[str, Decimal, str | None]]] = defaultdict(list)
    for r in rows:
        # Sin impuestos: se repiten siempre y no son un gasto que se decida.
        if r["kind"] not in EXPENSE_KINDS or r["kind"] == str(Kind.TAX):
            continue
        value = to_ars(db.amount(r), r["currency"], usd_rate)
        if value >= 0:
            continue
        buckets[merchant_key(r["description"], r["counterparty"])].append((r["date"], -value, r["category"]))

    out = []
    for merchant, entries in buckets.items():
        months = sorted({d[:7] for d, _, _ in entries})
        if len(months) < min_months:
            continue
        entries.sort()
        amounts = [amount for _, amount, _ in entries]
        avg = sum(amounts) / len(amounts)
        spread = (max(amounts) - min(amounts)) / avg if avg else Decimal(0)
        per_month = Decimal(len(entries)) / len(months)
        # Un cargo fijo se cobra ~una vez por mes y por un importe parecido. El
        # umbral de dispersión es holgado a propósito: una suscripción que
        # aumentó de $50 a $60 sigue siendo un cargo fijo — de hecho es
        # exactamente el caso que queremos mostrar.
        fixed = spread <= Decimal("0.25") and per_month <= 2
        first_amount, last_amount = entries[0][1], entries[-1][1]
        categories = [c for _, _, c in entries if c]
        out.append(
            {
                "merchant": merchant,
                "kind": "fijo" if fixed else "variable",
                "months": len(months),
                "n": len(entries),
                "last_date": entries[-1][0],
                "avg_amount": float(round(avg, 2)),
                "monthly_cost": float(round(sum(amounts) / len(months), 2)),
                "total": float(sum(amounts)),
                "category": categories[0] if categories else None,
                # Sólo tiene sentido para cargos fijos: en los variables el
                # cambio entre dos compras cualesquiera no dice nada.
                "change_pct": float(round((last_amount - first_amount) / first_amount * 100, 1))
                if fixed and first_amount
                else None,
            }
        )
    return sorted(out, key=lambda e: -e["monthly_cost"])


# Servicios que se cobran solos todos los meses. La lista cubre lo habitual;
# lo que falte se detecta igual si el cargo es fijo y se repite, o si vos lo
# categorizaste como 'Suscripciones'.
_SUBSCRIPTION_RE = re.compile(
    r"NETFLIX|DISNEY|PARAMOUNT|STAR\+|HBO|MAX\b|SPOTIFY|DEEZER|TIDAL|CRUNCHYROLL|MUBI|"
    r"APPLE|ICLOUD|ITUNES|YOUTUBE|PRIME VIDEO|AMAZON|AUDIBLE|KINDLE|"
    r"ANTHROPIC|CLAUDE|OPENAI|CHATGPT|GEMINI|COPILOT|GITHUB|NOTION|DROPBOX|GOOGLE ONE|"
    r"ADOBE|CANVA|FIGMA|MICROSOFT|OFFICE 365|ZOOM|"
    r"PLAYSTATION|XBOX|NINTENDO|STEAM|TWITCH|"
    r"LINKEDIN|DUOLINGO|STRAVA|MEDIUM|SUBSTACK|PATREON|"
    r"SMARTFIT|SPORTCLUB|GIMNASIO|MEGATLON",
    re.IGNORECASE,
)


def subscriptions(
    conn: sqlite3.Connection, rows: list[sqlite3.Row], usd_rate: Decimal, recurring: list[dict]
) -> list[dict]:
    """Lo que se paga todos los meses: streaming, software, abonos.

    Se juntan tres señales, porque ninguna sola alcanza: el comercio está en la
    lista conocida, vos lo categorizaste como 'Suscripciones', o el importe se
    repite fijo mes a mes. Un servicio visto una sola vez también aparece — con
    un mes importado, Disney+ figura una vez y sigue siendo una suscripción.
    """
    fixed = {r["merchant"] for r in recurring if r["kind"] == "fijo"}
    buckets: dict[str, dict] = {}
    latest = max((r["date"] for r in rows), default="")

    for r in rows:
        # Los impuestos (IVA, sellos, ingresos brutos) se repiten todos los
        # meses pero no son un servicio que se pueda dar de baja: son la
        # consecuencia de otros gastos, no una decisión propia.
        if r["kind"] not in EXPENSE_KINDS or r["kind"] == str(Kind.TAX):
            continue
        raw = db.amount(r)
        if raw >= 0:
            continue
        merchant = merchant_key(r["description"], r["counterparty"])
        category = r["category"] or ""
        is_sub = (
            _SUBSCRIPTION_RE.search(f"{r['description']} {r['counterparty']}")
            or category.startswith("Suscripciones")
            or merchant in fixed
        )
        if not is_sub:
            continue
        entry = buckets.setdefault(
            merchant,
            {
                "merchant": merchant, "category": category or None, "currency": r["currency"],
                "amounts": [], "dates": [], "months": set(), "mixed_currency": False,
            },
        )
        if entry["currency"] != r["currency"]:
            entry["mixed_currency"] = True
        entry["amounts"].append((r["date"], -raw, r["currency"]))
        entry["dates"].append(r["date"])
        entry["months"].add(r["date"][:7])
        entry["category"] = entry["category"] or (category or None)

    out = []
    for entry in buckets.values():
        entry["amounts"].sort()
        months = max(len(entry["months"]), 1)
        total_ars = sum(to_ars(a, c, usd_rate) for _, a, c in entry["amounts"])
        last_date = max(entry["dates"])
        first_amount, last_amount = entry["amounts"][0][1], entry["amounts"][-1][1]
        # Un servicio sin cargos en el último mes y medio de datos puede estar
        # dado de baja; se marca en vez de seguir sumándolo como si estuviera vivo.
        active = _within_days(last_date, latest, 45)
        out.append(
            {
                "merchant": entry["merchant"],
                "category": entry["category"],
                "currency": entry["currency"] if not entry["mixed_currency"] else "ARS",
                "last_amount": float(last_amount),
                "monthly_cost": float(round(total_ars / months, 2)),
                "yearly_cost": float(round(total_ars / months * 12, 2)),
                "months": len(entry["months"]),
                "n": len(entry["amounts"]),
                "last_date": last_date,
                "active": active,
                "change_pct": float(round((last_amount - first_amount) / first_amount * 100, 1))
                if first_amount and len(entry["months"]) > 1
                else None,
            }
        )
    return sorted(out, key=lambda s: (not s["active"], -s["monthly_cost"]))


def _within_days(day: str, reference: str, days: int) -> bool:
    if not day or not reference:
        return True
    return (date.fromisoformat(reference) - date.fromisoformat(day)).days <= days


def _biggest(rows: list[sqlite3.Row], usd_rate: Decimal, limit: int = 10) -> list[dict]:
    expenses = []
    for r in rows:
        if r["kind"] not in EXPENSE_KINDS:
            continue
        value = to_ars(db.amount(r), r["currency"], usd_rate)
        if value >= 0:
            continue
        expenses.append(
            {
                "date": r["date"],
                "description": r["description"],
                "counterparty": r["counterparty"],
                "account": r["account_label"],
                "category": r["category"],
                "amount": float(-value),
                "original": f"{r['amount']} {r['currency']}",
            }
        )
    return sorted(expenses, key=lambda e: -e["amount"])[:limit]
