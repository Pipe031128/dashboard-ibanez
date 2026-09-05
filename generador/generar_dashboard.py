"""
generar_dashboard.py
Los Ibáñez Supermercados – Generador de Dashboards
Procesa archivos de Rentabilidad (.txt) y Nómina (.xlsx) y genera un HTML interactivo.
"""

import os, sys, re, csv, json, logging
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

import pandas as pd

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
PDV_NAMES = {
    '001': 'Ortiz', '002': 'Carepa', '003': 'Obrero', '004': 'Nueva Colonia',
    '005': 'Chigorodo', '006': 'Terminal', '007': 'Lopez', '008': 'Turbo',
}
EXCLUIR_MARGEN = {'CARNES ATENDIDAS EXPENDIO', 'PANADERIA Y RESPOSTERIA "LOS IBANEZ"', 'PANADERIA Y REPOSTERIA "LOS IBANEZ"'}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger(__name__)

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def fmt_cop(n):
    return f"${int(n):,}".replace(',', '.')

def parse_money(val):
    if not val: return 0.0
    c = str(val).strip().replace('$', '').replace('.', '').replace(',', '.')
    try: return float(c)
    except: return 0.0

def parse_margin(val):
    if val is None: return None
    try: return float(str(val).strip().replace(',', '.'))
    except: return None

def iso_date(fecha_str):
    """Convert d/MM/YYYY → YYYY-MM-DD"""
    parts = fecha_str.split('/')
    if len(parts) == 3:
        day, mon, yr = int(parts[0]), int(parts[1]), parts[2]
        return f"{yr}-{mon:02d}-{day:02d}"
    return fecha_str

def build_calendar(year, month):
    """Return dict of ISO date → {tipo, label} for full month."""
    FESTIVOS_COL = {
        (1, 1): 'Año Nuevo', (5, 1): 'Día del Trabajo',
        (7, 20): 'Independencia', (8, 7): 'Batalla de Boyacá',
        (12, 8): 'Inmaculada Concepción', (12, 25): 'Navidad',
    }
    # Easter-based 2026: Easter = April 5
    EASTER_BASED_2026 = {
        '2026-04-02': 'Jueves Santo',
        '2026-04-03': 'Viernes Santo',
        '2026-05-14': 'Ascensión',
        '2026-06-04': 'Corpus Christi',
        '2026-06-12': 'Sagrado Corazón',
    }
    cal = {}
    d = date(year, month, 1)
    while d.month == month:
        iso = d.strftime('%Y-%m-%d')
        dow = d.weekday()
        fijo = FESTIVOS_COL.get((month, d.day))
        easter = EASTER_BASED_2026.get(iso)
        if fijo or easter:
            cal[iso] = {'tipo': 'holiday', 'label': fijo or easter}
        elif dow == 5:
            cal[iso] = {'tipo': 'saturday', 'label': 'Sábado'}
        elif dow == 6:
            cal[iso] = {'tipo': 'sunday', 'label': 'Domingo'}
        else:
            cal[iso] = {'tipo': 'weekday', 'label': d.strftime('%a')}
        d += timedelta(days=1)
    return cal

# ─── VENTAS PARSER ────────────────────────────────────────────────────────────
def parse_ventas(txt_path, items_cat, items_name):
    log.info(f"Procesando ventas: {txt_path.name}")
    totals = defaultdict(float)
    margins_all = defaultdict(list)
    daily = defaultdict(lambda: defaultdict(float))
    daily_margin = defaultdict(lambda: defaultdict(list))
    cat_data = defaultdict(lambda: defaultdict(lambda: {
        'ventas': 0.0, 'margins': [],
        'products': defaultdict(lambda: {'name': '', 'ventas': 0.0, 'margins': []})
    }))

    with open(txt_path, 'r', encoding='ascii', errors='replace') as f:
        reader = csv.reader(f, delimiter='\t')
        header = [c.strip().lower().replace('﻿','') for c in next(reader)]
        # Detectar índices de columnas por nombre de encabezado
        def ci(names):
            for n in names:
                for i, h in enumerate(header):
                    if n in h: return i
            return None
        iCO  = ci(['c.o.'])
        iFec = ci(['fecha'])
        iItm = ci(['item'])
        iSub = ci(['valor subtotal local'])
        iMgn = ci(['rgen promedio', 'margen promedio'])
        if any(x is None for x in [iCO, iFec, iItm, iSub, iMgn]):
            log.warning(f"No se pudieron detectar columnas en {txt_path.name}. Header: {header}")
            return {}
        log.info(f"  Columnas detectadas → CO:{iCO} Fecha:{iFec} Item:{iItm} Subtotal:{iSub} Margen:{iMgn}")
        for row in reader:
            if len(row) <= max(iCO, iFec, iItm, iSub, iMgn): continue
            co = row[iCO].strip()
            if co not in PDV_NAMES: continue
            fecha = row[iFec].strip()
            iid = row[iItm].strip()
            sub = parse_money(row[iSub])
            mgn = parse_margin(row[iMgn])
            cat = items_cat.get(iid, 'Sin categoría')

            totals[co] += sub
            fk = iso_date(fecha)
            daily[co][fk] += sub

            if cat not in EXCLUIR_MARGEN and mgn and 0 < mgn < 95:
                margins_all[co].append(mgn)
                daily_margin[co][fk].append(mgn)

            cd = cat_data[co][cat]
            cd['ventas'] += sub
            if mgn is not None: cd['margins'].append(mgn)
            pd_ = cd['products'][iid]
            pd_['name'] = items_name.get(iid, iid)
            pd_['ventas'] += sub
            if mgn is not None: pd_['margins'].append(mgn)

    # Detect month/year from dates
    all_dates = sorted(set(d for co in daily for d in daily[co]))
    if all_dates:
        sample = date.fromisoformat(all_dates[0])
        cal = build_calendar(sample.year, sample.month)
        all_month_dates = sorted(cal.keys())
    else:
        cal = {}
        all_month_dates = all_dates

    grand_total = sum(totals.values())
    ventas_sin = {co: sum(cd['ventas'] for c, cd in cat_data[co].items()
                          if c not in EXCLUIR_MARGEN) for co in PDV_NAMES}

    data = {}
    for co, name in PDV_NAMES.items():
        avg_m = sum(margins_all[co]) / len(margins_all[co]) if margins_all[co] else 0
        daily_avg_m = {d: (sum(daily_margin[co][d]) / len(daily_margin[co][d])
                          if daily_margin[co][d] else None)
                       for d in daily[co]}

        daily_out = []
        for iso in all_month_dates:
            v = daily[co].get(iso, 0)
            m = daily_avg_m.get(iso)
            meta = cal.get(iso, {'tipo': 'weekday', 'label': ''})
            daily_out.append({
                'date': iso,
                'label': iso[8:] + '/' + iso[5:7],
                'ventas': round(v),
                'margin': round(m, 2) if m is not None else None,
                'tipo': meta['tipo'],
                'day_label': meta['label'],
            })

        cats_out = []
        for cat, cd in cat_data[co].items():
            cat_m = [m for m in cd['margins'] if 0 < m < 95]
            cat_avg_m = sum(cat_m) / len(cat_m) if cat_m else 0
            cat_has_anomaly = any(m >= 95 for m in cd['margins'])
            prods = []
            for piid, pd_ in cd['products'].items():
                pm = pd_['margins']
                p_avg = sum(pm) / len(pm) if pm else 0
                p_has99 = any(m >= 95 for m in pm)
                prods.append({'id': piid, 'name': pd_['name'][:42],
                              'ventas': round(pd_['ventas']),
                              'avg_margin': round(p_avg, 1), 'has_99': p_has99})
            prods.sort(key=lambda x: -x['ventas'])
            cats_out.append({
                'cat': cat[:38], 'ventas': round(cd['ventas']),
                'avg_margin': round(cat_avg_m, 1),
                'excluded': cat in EXCLUIR_MARGEN,
                'has_anomaly': cat_has_anomaly,
                'products': prods[:30],
            })
        cats_out.sort(key=lambda x: -x['ventas'])

        data[co] = {
            'name': name,
            'total': round(totals.get(co, 0)),
            'total_sin': round(ventas_sin.get(co, 0)),
            'avg_margin': round(avg_m, 2),
            'share': round(totals.get(co, 0) / grand_total * 100, 1) if grand_total else 0,
            'daily': daily_out,
            'categories': cats_out,
            'top_items': sorted(
                [{'name': cat_data[co][c]['products'][iid]['name'][:38],
                  'ventas': round(cat_data[co][c]['products'][iid]['ventas'])}
                 for c in cat_data[co] for iid in cat_data[co][c]['products']],
                key=lambda x: -x['ventas'])[:5],
        }
    data['_meta'] = {'cal': cal, 'all_dates': all_month_dates,
                     'periodo': txt_path.stem}
    return data

# ─── NÓMINA PARSER ────────────────────────────────────────────────────────────
def parse_nominas(nomina_dir, year, month):
    """Parse all Nomina NNN - YYMM.xlsx files for given month/year (recursive)."""
    log.info(f"Procesando nóminas en: {nomina_dir}")
    # Filename format: NominaNNN - YYMM.xlsx  (e.g. Nomina001 - 2604.xlsx → year=26, month=04)
    pattern = re.compile(r'Nomina(\d{3})\s*-\s*(\d{2})(\d{2})\.xlsx', re.IGNORECASE)
    mm = f"{month:02d}"
    yy = str(year)[2:]

    nom_data = {}
    for fpath in sorted(Path(nomina_dir).rglob('Nomina*.xlsx')):
        m = pattern.match(fpath.name)
        if not m: continue
        pdv_id, file_yy, file_mm = m.group(1), m.group(2), m.group(3)  # YY then MM
        if file_mm != mm or file_yy != yy: continue
        if pdv_id not in PDV_NAMES: continue

        log.info(f"  Leyendo {fpath.name}")
        df = pd.read_excel(fpath, header=0)
        # Usar todas las filas sin filtro
        df_cargo = df.copy()

        total_dev = float(df_cargo['Devengo'].sum())
        total_ded = float(df_cargo['Deducción'].sum())
        n_emp = int(df_cargo['Tercero'].nunique())

        by_cargo = (df_cargo.groupby('Cargo movimiento')
                    .agg(devengo=('Devengo', 'sum'),
                         deduccion=('Deducción', 'sum'),
                         empleados=('Tercero', 'nunique'))
                    .reset_index()
                    .sort_values('devengo', ascending=False))

        # Top devengo concepts
        by_concepto = (df_cargo[df_cargo['Devengo'] > 0]
                       .groupby('Descripción Concepto')['Devengo']
                       .sum().sort_values(ascending=False).head(8))

        nom_data[pdv_id] = {
            'name': PDV_NAMES[pdv_id],
            'total_devengo': round(total_dev),
            'total_deduccion': round(total_ded),
            'neto': round(total_dev - total_ded),
            'n_empleados': n_emp,
            'costo_por_emp': round(total_dev / n_emp) if n_emp > 0 else 0,
            'by_cargo': [
                {'cargo': r['Cargo movimiento'],
                 'devengo': round(float(r['devengo'])),
                 'deduccion': round(float(r['deduccion'])),
                 'empleados': int(r['empleados'])}
                for _, r in by_cargo.iterrows()
            ],
            'by_concepto': {k: round(float(v)) for k, v in by_concepto.items()},
        }

    # Fill missing PDVs with zeros
    for co in PDV_NAMES:
        if co not in nom_data:
            nom_data[co] = {
                'name': PDV_NAMES[co], 'total_devengo': 0, 'total_deduccion': 0,
                'neto': 0, 'n_empleados': 0, 'costo_por_emp': 0,
                'by_cargo': [], 'by_concepto': {},
            }
    return nom_data

# ─── COMPRAS PARSER ───────────────────────────────────────────────────────────
def parse_compras(txt_path):
    log.info(f"Procesando compras: {txt_path.name}")
    totals      = defaultdict(float)
    daily       = defaultdict(lambda: defaultdict(float))
    proveedores = defaultdict(float)
    pdv_prov    = defaultdict(lambda: defaultdict(float))
    pdv_items   = defaultdict(lambda: defaultdict(float))

    with open(txt_path, 'r', encoding='ascii', errors='replace') as f:
        reader = csv.reader(f, delimiter='\t')
        next(reader)  # skip header
        for row in reader:
            if len(row) < 10: continue
            co   = row[1].strip()
            if co not in PDV_NAMES: continue
            fecha_raw = row[0].strip()
            prov = row[3].strip()
            item = row[4].strip()
            # Separar código del nombre del ítem (formato: "CODIGO NOMBRE")
            parts = item.split(' ', 1)
            item_name = parts[1].strip() if len(parts) > 1 else item

            try:
                val = float(str(row[9]).strip().replace('$','').replace('.','').replace(',','.'))
            except:
                val = 0.0
            if val <= 0: continue

            try:
                fk = iso_date(fecha_raw)
            except:
                fk = fecha_raw

            totals[co]             += val
            daily[co][fk]          += val
            proveedores[prov]      += val
            pdv_prov[co][prov]     += val
            pdv_items[co][item_name] += val

    # Detectar mes del calendario desde fechas
    all_dates = sorted(set(d for co in daily for d in daily[co]))
    if all_dates:
        sample = date.fromisoformat(all_dates[0])
        cal    = build_calendar(sample.year, sample.month)
        all_month_dates = sorted(cal.keys())
    else:
        cal = {}
        all_month_dates = all_dates

    grand_total = sum(totals.values())

    data = {}
    for co, name in PDV_NAMES.items():
        daily_out = []
        for iso in all_month_dates:
            v    = daily[co].get(iso, 0)
            meta = cal.get(iso, {'tipo': 'weekday', 'label': ''})
            daily_out.append({'date': iso,
                               'label': iso[8:]+'/'+iso[5:7],
                               'valor': round(v),
                               'tipo':  meta['tipo'],
                               'day_label': meta['label']})

        top_prov  = sorted(pdv_prov[co].items(),  key=lambda x: -x[1])[:15]
        top_items = sorted(pdv_items[co].items(), key=lambda x: -x[1])[:15]

        data[co] = {
            'name':      name,
            'total':     round(totals.get(co, 0)),
            'share':     round(totals.get(co, 0) / grand_total * 100, 1) if grand_total else 0,
            'daily':     daily_out,
            'top_prov':  [{'name': p[:45], 'valor': round(v)} for p, v in top_prov],
            'top_items': [{'name': n[:48], 'valor': round(v)} for n, v in top_items],
        }

    # Top proveedores globales
    top_global = sorted(proveedores.items(), key=lambda x: -x[1])[:20]
    data['_meta'] = {
        'cal': cal,
        'all_dates': all_month_dates,
        'grand_total': round(grand_total),
        'top_prov_global': [{'name': p[:50], 'valor': round(v)} for p, v in top_global],
    }
    return data

# ─── ITEMS LOADER ─────────────────────────────────────────────────────────────
def load_items(linea_dir):
    items_cat = {}
    items_name = {}
    for fpath in Path(linea_dir).glob('*.txt'):
        log.info(f"Cargando catálogo de ítems: {fpath.name}")
        with open(fpath, 'r', encoding='latin-1', errors='replace') as f:
            for row in csv.reader(f, delimiter='\t'):
                if len(row) < 5: continue
                iid = row[0].strip()
                items_name[iid] = row[2].strip()
                cat = row[4].strip()
                if ' - ' in cat: cat = cat.split(' - ', 1)[1].strip()
                items_cat[iid] = cat
        break  # only first file
    log.info(f"  {len(items_cat)} ítems cargados")
    return items_cat, items_name

# ─── HTML BUILDER ─────────────────────────────────────────────────────────────
def build_html(ventas_data, nom_data, periodo_label, compras_data=None):
    """Combine ventas + nomina + compras data into a single interactive HTML dashboard."""

    combined = {'ventas': ventas_data, 'nomina': nom_data, 'compras': compras_data or {}}
    js_data = json.dumps(combined, ensure_ascii=True, separators=(',', ':'))

    chartjs_path = Path(__file__).parent / 'chart.umd.min.js'
    chartjs_inline = chartjs_path.read_text(encoding='utf-8')

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Los Ibáñez – {periodo_label}</title>
<script>{chartjs_inline}</script>
<style>
:root{{
  --bg:#0f1117;--surface:#1a1d27;--surface2:#222636;--surface3:#2a2e42;
  --border:#2e3248;--accent:#4f6ef7;--accent2:#38c9a0;--accent3:#f7a54f;
  --accent4:#e05d7a;--text:#e8eaf6;--text2:#8b90b0;
  --green:#38c9a0;--red:#e05d7a;--yellow:#f7d04f;--purple:#a855f7;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}}
.header{{background:linear-gradient(135deg,#1a1d27,#222636);border-bottom:1px solid var(--border);
  padding:16px 28px;display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:200}}
.hlogo{{width:36px;height:36px;background:var(--accent);border-radius:8px;display:flex;
  align-items:center;justify-content:center;font-size:15px;font-weight:800;margin-right:12px}}
.htitle{{font-size:17px;font-weight:700}}
.hsub{{font-size:11px;color:var(--text2);margin-top:2px}}
.periodo{{background:var(--surface2);border:1px solid var(--border);padding:5px 12px;
  border-radius:18px;font-size:12px;color:var(--text2)}}

/* TABS */
.tab-bar{{display:flex;gap:4px;padding:18px 28px 0;border-bottom:1px solid var(--border);background:var(--surface)}}
.tab-btn{{padding:9px 20px;border:none;background:transparent;color:var(--text2);cursor:pointer;
  font-size:13px;font-weight:500;border-bottom:2px solid transparent;transition:all .2s}}
.tab-btn:hover{{color:var(--text)}}
.tab-btn.active{{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}}
.tab-content{{display:none}}.tab-content.active{{display:block}}

.main{{padding:22px 28px;max-width:1600px;margin:0 auto}}
.kpi-row{{display:grid;gap:12px;margin-bottom:20px}}
.kpi-row-5{{grid-template-columns:repeat(5,1fr)}}
.kpi-row-4{{grid-template-columns:repeat(4,1fr)}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:15px 17px;position:relative;overflow:hidden}}
.kpi::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px}}
.kpi.c1::before{{background:var(--accent)}}.kpi.c2::before{{background:var(--accent2)}}
.kpi.c3::before{{background:var(--accent3)}}.kpi.c4::before{{background:var(--accent4)}}
.kpi.c5::before{{background:var(--yellow)}}.kpi.c6::before{{background:var(--purple)}}
.kpi-label{{font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px}}
.kpi-val{{font-size:19px;font-weight:700;line-height:1.1}}
.kpi-sub{{font-size:11px;color:var(--text2);margin-top:3px}}

.pdv-nav{{display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap}}
.pdv-btn{{padding:6px 14px;border-radius:8px;border:1px solid var(--border);background:var(--surface);
  color:var(--text2);cursor:pointer;font-size:12px;font-weight:500;transition:all .2s}}
.pdv-btn:hover{{border-color:var(--accent);color:var(--text)}}
.pdv-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}}

.breadcrumb{{display:flex;align-items:center;gap:7px;margin-bottom:14px;font-size:12px;color:var(--text2)}}
.bc-link{{cursor:pointer;color:var(--accent)}}.bc-link:hover{{text-decoration:underline}}
.bc-current{{color:var(--text);font-weight:600}}

.row{{display:grid;gap:15px;margin-bottom:15px}}
.r2{{grid-template-columns:1fr 1fr}}.r3{{grid-template-columns:2fr 1fr}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px}}
.card-title{{font-size:11px;font-weight:600;color:var(--text2);text-transform:uppercase;
  letter-spacing:.7px;margin-bottom:13px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}}

.chart-wrap{{position:relative}}
.h250{{height:250px}}.h280{{height:280px}}.h200{{height:200px}}.h170{{height:170px}}.h160{{height:160px}}

.toggle{{display:flex;background:var(--surface2);border:1px solid var(--border);border-radius:7px;overflow:hidden;margin-bottom:11px}}
.tog{{padding:5px 11px;font-size:11px;cursor:pointer;color:var(--text2);transition:all .15s}}
.tog.active{{background:var(--accent);color:#fff;font-weight:600}}

.tbl{{width:100%;border-collapse:collapse}}
.tbl th{{font-size:10px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;
  padding:6px 9px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}}
.tbl td{{padding:8px 9px;border-bottom:1px solid rgba(46,50,72,.4);font-size:12px;vertical-align:middle}}
.tbl tr:last-child td{{border-bottom:none}}
.tbl tbody tr{{cursor:pointer;transition:background .15s}}
.tbl tbody tr:hover td{{background:var(--surface2)}}
.tbl tbody tr.selected td{{background:rgba(79,110,247,.1)}}
.tbl tbody tr.selected td:first-child{{border-left:2px solid var(--accent)}}

.bar-t{{height:7px;background:var(--surface2);border-radius:4px;overflow:hidden;min-width:55px}}
.bar-f{{height:100%;border-radius:4px}}
.pill{{padding:2px 7px;border-radius:7px;font-size:10px;font-weight:600;white-space:nowrap;display:inline-block}}
.pg{{background:rgba(56,201,160,.15);color:var(--green)}}
.py{{background:rgba(247,208,79,.15);color:var(--yellow)}}
.pr{{background:rgba(224,93,122,.15);color:var(--red)}}
.pp{{background:rgba(168,85,247,.15);color:var(--purple);font-size:9px}}
.pw{{background:rgba(247,165,79,.15);color:var(--accent3);font-size:9px}}

.prod-panel{{background:var(--surface2);border:1px solid var(--border);border-radius:11px;
  padding:16px;margin-top:11px;animation:fi .2s ease}}
@keyframes fi{{from{{opacity:0;transform:translateY(-5px)}}to{{opacity:1;transform:translateY(0)}}}}
.pp-title{{font-size:12px;font-weight:700;margin-bottom:11px;display:flex;align-items:center;gap:7px}}
.pp-close{{margin-left:auto;cursor:pointer;color:var(--text2);font-size:15px;padding:2px 5px;border-radius:4px}}
.pp-close:hover{{background:var(--surface3);color:var(--text)}}

.item-list{{display:flex;flex-direction:column;gap:5px}}
.item-row{{display:flex;align-items:center;gap:8px;padding:6px 8px;background:var(--surface2);border-radius:7px}}
.item-rank{{width:19px;height:19px;border-radius:4px;display:flex;align-items:center;
  justify-content:center;font-size:9px;font-weight:700;flex-shrink:0}}

.note{{font-size:10px;color:var(--purple);margin-top:5px;opacity:.8}}

.cal-leg{{display:inline-flex;gap:10px;align-items:center}}
.cl-item{{display:flex;align-items:center;gap:4px;font-size:10px;color:var(--text2)}}
.cl-dot{{width:9px;height:9px;border-radius:2px}}

@media(max-width:1100px){{.kpi-row-5,.kpi-row-4{{grid-template-columns:repeat(3,1fr)}}.r2,.r3{{grid-template-columns:1fr}}}}
@media(max-width:700px){{.main{{padding:12px}}.kpi-row-5,.kpi-row-4{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body>

<div class="header">
  <div style="display:flex;align-items:center">
    <div class="hlogo">LI</div>
    <div>
      <div class="htitle">Los Ibáñez Supermercados</div>
      <div class="hsub">Dashboard Gerencial</div>
    </div>
  </div>
  <div class="periodo">📅 {periodo_label}</div>
</div>

<div class="tab-bar">
  <button class="tab-btn active" onclick="showTab('ventas')">📊 Ventas &amp; Rentabilidad</button>
  <button class="tab-btn" onclick="showTab('nomina')">👥 Nómina</button>
  <button class="tab-btn" onclick="showTab('compras')">🛒 Compras a Proveedores</button>
  <button class="tab-btn" onclick="showTab('productividad')">⚡ Productividad</button>
  <button class="tab-btn" onclick="showTab('alertas')">🚨 Alertas</button>
</div>

<!-- ══════════ TAB VENTAS ══════════ -->
<div id="tab-ventas" class="tab-content active">
<div class="main">
  <div id="vKpiRow" class="kpi-row kpi-row-5"></div>
  <div class="pdv-nav" id="vNav"></div>
  <div id="vBread" class="breadcrumb" style="display:none"></div>

  <div id="vAll">
    <div class="row r2">
      <div class="card">
        <div class="card-title">📊 Ventas por PDV
          <div class="toggle" style="margin-left:auto;margin-bottom:0">
            <div class="tog active" id="togCon" onclick="setToggle('con')">Con carnicería</div>
            <div class="tog" id="togSin" onclick="setToggle('sin')">Sin carnicería</div>
          </div>
        </div>
        <div class="chart-wrap h250"><canvas id="cBarAll"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">🥧 Participación</div>
        <div class="chart-wrap h250"><canvas id="cDonut"></canvas></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:15px">
      <div class="card-title">📈 Evolución Diaria – Todos los PDV
        <span class="cal-leg" style="margin-left:auto">
          <span class="cl-item"><span class="cl-dot" style="background:rgba(224,93,122,.35)"></span>Festivo</span>
          <span class="cl-item"><span class="cl-dot" style="background:rgba(247,165,79,.18)"></span>Sábado</span>
          <span class="cl-item"><span class="cl-dot" style="background:rgba(247,208,79,.13)"></span>Domingo</span>
        </span>
      </div>
      <div class="chart-wrap h280"><canvas id="cLineAll"></canvas></div>
    </div>
    <div class="row r2">
      <div class="card">
        <div class="card-title">🎯 Margen Promedio por PDV
          <span style="font-size:9px;color:var(--purple);font-weight:400;text-transform:none">(excl. carnicería y panadería)</span>
        </div>
        <div class="chart-wrap h200"><canvas id="cMarginAll"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">📋 Resumen Ejecutivo</div>
        <div style="overflow-x:auto"><table class="tbl" id="vOvTable"></table></div>
        <div class="note">* Margen excluye Carnes Atendidas Expendio y Panadería Los Ibáñez (sin costo)</div>
      </div>
    </div>
  </div>

  <div id="vPdv" style="display:none">
    <div class="row r2">
      <div class="card">
        <div class="card-title">📈 Ventas Diarias
          <span class="cal-leg" style="margin-left:auto">
            <span class="cl-item"><span class="cl-dot" style="background:rgba(224,93,122,.35)"></span>Festivo</span>
            <span class="cl-item"><span class="cl-dot" style="background:rgba(247,165,79,.18)"></span>Sáb</span>
            <span class="cl-item"><span class="cl-dot" style="background:rgba(247,208,79,.13)"></span>Dom</span>
          </span>
        </div>
        <div class="chart-wrap h280"><canvas id="cDailyPdv"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">📉 Margen Diario
          <span style="font-size:9px;color:var(--purple);font-weight:400;text-transform:none">(excl. carnicería y panadería)</span>
        </div>
        <div class="chart-wrap h280"><canvas id="cMarginPdv"></canvas></div>
      </div>
    </div>
    <div class="row">
      <div class="card">
        <div class="card-title">🏷️ Ventas por Línea —
          <span id="vCatTitle" style="color:var(--text);font-weight:700;text-transform:none;font-size:12px">
            clic en una línea para ver sus productos
          </span>
        </div>
        <div style="overflow-x:auto">
          <table class="tbl">
            <thead><tr><th>Línea</th><th>Ventas</th><th>Participación</th><th>Margen</th><th>Estado</th></tr></thead>
            <tbody id="vCatBody"></tbody>
          </table>
        </div>
        <div id="vProdPanel" style="display:none" class="prod-panel">
          <div class="pp-title"><span>📦</span><span id="vProdTitle"></span>
            <span class="pp-close" onclick="closeProd()">✕</span></div>
          <div style="overflow-x:auto">
            <table class="tbl">
              <thead><tr><th>#</th><th>Producto</th><th>Ventas</th><th>% línea</th><th>Margen</th><th>Alerta</th></tr></thead>
              <tbody id="vProdBody"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
    <div class="row r2">
      <div class="card">
        <div class="card-title">🏆 Top 5 Productos</div>
        <div class="item-list" id="vTopItems"></div>
      </div>
      <div class="card">
        <div class="card-title">📊 Top 8 Líneas</div>
        <div class="chart-wrap h170"><canvas id="cCatBar"></canvas></div>
      </div>
    </div>
  </div>
</div>
</div>

<!-- ══════════ TAB NÓMINA ══════════ -->
<div id="tab-nomina" class="tab-content">
<div class="main">
  <div id="nKpiRow" class="kpi-row kpi-row-4"></div>
  <div class="pdv-nav" id="nNav"></div>
  <div id="nBread" class="breadcrumb" style="display:none"></div>

  <div id="nAll">
    <div class="row r2">
      <div class="card">
        <div class="card-title">💰 Devengo Total por PDV</div>
        <div class="chart-wrap h250"><canvas id="nBarAll"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">👤 Empleados por PDV</div>
        <div class="chart-wrap h250"><canvas id="nEmpBar"></canvas></div>
      </div>
    </div>
    <div class="row r2">
      <div class="card">
        <div class="card-title">💵 Costo Promedio por Empleado</div>
        <div class="chart-wrap h200"><canvas id="nCostEmp"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">📋 Resumen de Nómina</div>
        <div style="overflow-x:auto"><table class="tbl" id="nOvTable"></table></div>
      </div>
    </div>
  </div>

  <div id="nPdv" style="display:none">
    <div class="row r2">
      <div class="card">
        <div class="card-title">💰 Devengo por Cargo</div>
        <div class="chart-wrap h280"><canvas id="nCargoBars"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">🥧 Distribución por Cargo</div>
        <div class="chart-wrap h280"><canvas id="nCargoDonut"></canvas></div>
      </div>
    </div>
    <div class="row r2">
      <div class="card">
        <div class="card-title">📋 Detalle por Cargo</div>
        <div style="overflow-x:auto"><table class="tbl" id="nCargoTable"></table></div>
      </div>
      <div class="card">
        <div class="card-title">📑 Top Conceptos de Devengo</div>
        <div class="chart-wrap h200"><canvas id="nConceptoBar"></canvas></div>
      </div>
    </div>
  </div>
</div>
</div>

<!-- ══════════ TAB COMPRAS ══════════ -->
<div id="tab-compras" class="tab-content">
<div class="main">
  <div id="cKpiRow" class="kpi-row kpi-row-4"></div>
  <div class="pdv-nav" id="cNav"></div>
  <div id="cBread" class="breadcrumb" style="display:none"></div>

  <div id="cAll">
    <div class="row r2">
      <div class="card">
        <div class="card-title">🛒 Compras por PDV</div>
        <div class="chart-wrap h250"><canvas id="cBarAll2"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">🥧 Participación en Compras</div>
        <div class="chart-wrap h250"><canvas id="cDonut2"></canvas></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:15px">
      <div class="card-title">📈 Evolución Diaria de Compras — Todos los PDV</div>
      <div class="chart-wrap h280"><canvas id="cLineAll2"></canvas></div>
    </div>
    <div class="row r2">
      <div class="card">
        <div class="card-title">🏭 Top 10 Proveedores Globales</div>
        <div class="chart-wrap h280"><canvas id="cProvGlobal"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">📋 Resumen Compras por PDV</div>
        <div style="overflow-x:auto"><table class="tbl" id="cOvTable"></table></div>
      </div>
    </div>
  </div>

  <div id="cPdv" style="display:none">
    <div class="row r2">
      <div class="card">
        <div class="card-title">📈 Compras Diarias</div>
        <div class="chart-wrap h280"><canvas id="cDailyPdv2"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">🏭 Top Proveedores del PDV</div>
        <div class="chart-wrap h280"><canvas id="cProvPdv"></canvas></div>
      </div>
    </div>
    <div class="row r2">
      <div class="card">
        <div class="card-title">📦 Top Productos Comprados</div>
        <div style="overflow-x:auto"><table class="tbl" id="cItemTable"></table></div>
      </div>
      <div class="card">
        <div class="card-title">🏭 Detalle Proveedores</div>
        <div style="overflow-x:auto"><table class="tbl" id="cProvTable"></table></div>
      </div>
    </div>
  </div>
</div>
</div>

<!-- ══════════ TAB PRODUCTIVIDAD ══════════ -->
<div id="tab-productividad" class="tab-content">
<div class="main">
  <div id="pKpiRow" class="kpi-row kpi-row-4"></div>
  <div class="row r2" style="margin-bottom:15px">
    <div class="card">
      <div class="card-title">💼 Ventas por Empleado por PDV</div>
      <div class="chart-wrap h250"><canvas id="pVentasEmp"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">📉 % Nómina sobre Ventas por PDV</div>
      <div class="chart-wrap h250"><canvas id="pNomPct"></canvas></div>
    </div>
  </div>
  <div class="card" style="margin-bottom:15px">
    <div class="card-title">📊 Ventas vs Nómina por PDV</div>
    <div class="chart-wrap h280"><canvas id="pVsNom"></canvas></div>
  </div>
  <div class="card">
    <div class="card-title">🏆 Ranking de Eficiencia por PDV</div>
    <div style="overflow-x:auto"><table class="tbl" id="pTable"></table></div>
  </div>
</div>
</div>

<!-- ══════════ TAB ALERTAS ══════════ -->
<div id="tab-alertas" class="tab-content">
<div class="main">

  <!-- Semáforo nómina -->
  <div class="card" style="margin-bottom:15px">
    <div class="card-title">🚦 Semáforo de Nómina por PDV
      <span style="margin-left:auto;display:flex;gap:10px;font-size:10px;font-weight:400;text-transform:none">
        <span style="color:var(--green)">● &lt;8% Verde</span>
        <span style="color:var(--yellow)">● 8–12% Amarillo</span>
        <span style="color:var(--red)">● &gt;12% Rojo</span>
      </span>
    </div>
    <div id="aSemaforo" style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px"></div>
  </div>

  <!-- Alertas de margen -->
  <div class="card" style="margin-bottom:15px">
    <div class="card-title">📉 Alertas de Margen por PDV</div>
    <div id="aMargen" style="display:flex;flex-direction:column;gap:10px"></div>
  </div>

  <!-- Días críticos -->
  <div class="card" style="margin-bottom:15px">
    <div class="card-title">📅 5 Días Críticos del Mes
      <span style="font-size:10px;color:var(--text2);font-weight:400;text-transform:none;margin-left:6px">(excluye festivos y domingos)</span>
    </div>
    <div style="overflow-x:auto"><table class="tbl" id="aDiasCriticos"></table></div>
  </div>

  <!-- Ranking eficiencia -->
  <div class="card">
    <div class="card-title">🏆 Ranking de Eficiencia Global
      <span style="font-size:10px;color:var(--text2);font-weight:400;text-transform:none;margin-left:6px">(margen + % nómina + ventas/empleado)</span>
    </div>
    <div style="overflow-x:auto"><table class="tbl" id="aRanking"></table></div>
  </div>

</div>
</div>

<script id="allData" type="application/json">{js_data}</script>
<script>
const ALL = JSON.parse(document.getElementById('allData').textContent);
const VD = ALL.ventas;
const ND = ALL.nomina;
const CD = ALL.compras;
const PDV_ORDER = ['001','002','003','004','005','006','007','008'];
const COLORS = ['#4f6ef7','#38c9a0','#f7a54f','#e05d7a','#a855f7','#f7d04f','#06b6d4','#84cc16'];
const CAT_COLORS = ['#4f6ef7','#38c9a0','#f7a54f','#e05d7a','#a855f7','#f7d04f','#06b6d4','#84cc16','#fb923c','#f472b6'];

let charts={{}}, togMode='con', curVPdv='all', curNPdv='all', selCatIdx=null;

function dc(id){{if(charts[id]){{charts[id].destroy();delete charts[id];}}}}
function fmt(n){{
  if(n>=1e9)return'$'+(n/1e9).toFixed(2)+'B';
  if(n>=1e6)return'$'+(n/1e6).toFixed(1)+'M';
  if(n>=1e3)return'$'+(n/1e3).toFixed(0)+'K';
  return'$'+Math.round(n).toLocaleString('es-CO');
}}
function fmtFull(n){{return'$'+Math.round(n).toLocaleString('es-CO');}}
function mPill(m,excl){{
  if(excl)return'<span class="pill pp">SIN COSTO</span>';
  if(!m&&m!==0)return'<span class="pill" style="color:var(--text2)">—</span>';
  if(m>=95)return`<span class="pill pr">${{m.toFixed(1)}}%</span>`;
  if(m>=22)return`<span class="pill pg">${{m.toFixed(1)}}%</span>`;
  if(m>=18)return`<span class="pill py">${{m.toFixed(1)}}%</span>`;
  return`<span class="pill pr">${{m.toFixed(1)}}%</span>`;
}}

// Calendar plugin
const calBg={{id:'calBg',beforeDraw(chart,a,opts){{
  if(!opts||!opts.zones)return;
  const{{ctx,chartArea:{{left,top,right,bottom}},scales:{{x}}}}=chart;
  if(!x)return;
  opts.zones.forEach(z=>{{
    if(z.idx>=x.ticks.length)return;
    const w=x.getPixelForTick(1)-x.getPixelForTick(0);
    const x1=x.getPixelForTick(z.idx)-w/2;
    const x2=x1+w;
    ctx.save();ctx.fillStyle=z.color;
    ctx.fillRect(Math.max(x1,left),top,Math.min(x2,right)-Math.max(x1,left),bottom-top);
    ctx.restore();
  }});
}}}};
Chart.register(calBg);

function calZones(daily){{
  return daily.map((d,i)=>{{
    if(d.tipo==='holiday')return{{idx:i,color:'rgba(224,93,122,.18)'}};
    if(d.tipo==='saturday')return{{idx:i,color:'rgba(247,165,79,.10)'}};
    if(d.tipo==='sunday')return{{idx:i,color:'rgba(247,208,79,.08)'}};
    return null;
  }}).filter(Boolean);
}}
function ttMeta(daily){{const m={{}};daily.forEach(d=>m[d.label]={{tipo:d.tipo,dl:d.day_label}});return m;}}
function ttTitle(lbl,meta){{
  const m=meta[lbl];if(!m)return lbl;
  if(m.tipo==='holiday')return`${{lbl}} 🔴 ${{m.dl}}`;
  if(m.tipo==='saturday')return`${{lbl}} 🟡 Sábado`;
  if(m.tipo==='sunday')return`${{lbl}} 🟡 Domingo`;
  return lbl;
}}

// ══════════ VENTAS ══════════
function initVKpis(){{
  const grand=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total||0),0);
  const grandSin=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total_sin||0),0);
  const wavg=PDV_ORDER.reduce((s,id)=>s+(VD[id].avg_margin||0)*(VD[id].total_sin||0),0)/Math.max(grandSin,1);
  const best=PDV_ORDER.reduce((a,b)=>(VD[a].total||0)>(VD[b].total||0)?a:b);
  const topM=PDV_ORDER.reduce((a,b)=>(VD[a].avg_margin||0)>(VD[b].avg_margin||0)?a:b);
  document.getElementById('vKpiRow').innerHTML=`
    <div class="kpi c1"><div class="kpi-label">Ventas Totales</div><div class="kpi-val">${{fmtFull(grand)}}</div><div class="kpi-sub">Todos los PDV</div></div>
    <div class="kpi c6"><div class="kpi-label">Sin Carnicería</div><div class="kpi-val">${{fmtFull(grandSin)}}</div><div class="kpi-sub">Excl. líneas sin costo</div></div>
    <div class="kpi c2"><div class="kpi-label">Margen Prom.*</div><div class="kpi-val">${{wavg.toFixed(2)}}%</div><div class="kpi-sub">Excl. líneas sin costo</div></div>
    <div class="kpi c3"><div class="kpi-label">Mejor PDV</div><div class="kpi-val">${{VD[best].name}}</div><div class="kpi-sub">${{fmtFull(VD[best].total)}}</div></div>
    <div class="kpi c4"><div class="kpi-label">Mayor Margen*</div><div class="kpi-val">${{VD[topM].name}}</div><div class="kpi-sub">${{(VD[topM].avg_margin||0).toFixed(2)}}%</div></div>`;
}}

function buildVNav(){{
  const nav=document.getElementById('vNav');nav.innerHTML='';
  const a=document.createElement('button');
  a.className='pdv-btn active';a.dataset.id='all';a.textContent='🏪 Todos';
  a.onclick=()=>selectVPdv('all');nav.appendChild(a);
  PDV_ORDER.forEach((id,i)=>{{
    const b=document.createElement('button');b.className='pdv-btn';b.dataset.id=id;
    b.innerHTML=`<span style="color:${{COLORS[i]}};margin-right:3px">●</span>${{id}} ${{VD[id].name}}`;
    b.onclick=()=>selectVPdv(id);nav.appendChild(b);
  }});
}}

function selectVPdv(id){{
  document.querySelectorAll('#vNav .pdv-btn').forEach(b=>b.classList.toggle('active',b.dataset.id===id));
  curVPdv=id;selCatIdx=null;
  document.getElementById('vAll').style.display=id==='all'?'':'none';
  document.getElementById('vPdv').style.display=id!=='all'?'':'none';
  document.getElementById('vBread').style.display=id!=='all'?'flex':'none';
  if(id==='all')renderVAll();else renderVPdv(id);
}}

function setToggle(mode){{
  togMode=mode;
  document.getElementById('togCon').classList.toggle('active',mode==='con');
  document.getElementById('togSin').classList.toggle('active',mode==='sin');
  dc('cBarAll');renderVBarAll();
}}

function renderVAll(){{
  renderVBarAll();
  // Donut
  dc('cDonut');
  charts.cDonut=new Chart(document.getElementById('cDonut'),{{
    type:'doughnut',
    data:{{labels:PDV_ORDER.map(id=>VD[id].name),
      datasets:[{{data:PDV_ORDER.map(id=>VD[id].total||0),backgroundColor:COLORS,borderWidth:2,borderColor:'#1a1d27'}}]}},
    options:{{plugins:{{legend:{{position:'right',labels:{{color:'#8b90b0',font:{{size:11}},padding:9}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{VD[PDV_ORDER[ctx.dataIndex]].share}}%`}}}}}},cutout:'60%'}}
  }});
  // Line all
  dc('cLineAll');
  const allDates=(VD._meta?.all_dates)||[];
  const daily0=VD['001'].daily;
  const zones=calZones(daily0);const meta=ttMeta(daily0);
  charts.cLineAll=new Chart(document.getElementById('cLineAll'),{{
    type:'line',
    data:{{labels:daily0.map(d=>d.label),datasets:PDV_ORDER.map((id,i)=>{{
      const map={{}};VD[id].daily.forEach(d=>map[d.date]=d.ventas);
      return{{label:VD[id].name,data:daily0.map(d=>(map[d.date]||0)/1e6),
        borderColor:COLORS[i],backgroundColor:'transparent',borderWidth:2,pointRadius:0,tension:.3}};
    }})}},
    options:{{plugins:{{calBg:{{zones}},
      legend:{{position:'bottom',labels:{{color:'#8b90b0',font:{{size:10}},boxWidth:9,padding:7}}}},
      tooltip:{{callbacks:{{title:ctx=>ttTitle(ctx[0].label,meta),label:ctx=>` ${{VD[PDV_ORDER[ctx.datasetIndex]].name}}: $${{ctx.raw.toFixed(1)}}M`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>v+'M'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  // Margin
  dc('cMarginAll');
  const margins=PDV_ORDER.map(id=>VD[id].avg_margin||0);
  const mc=margins.map(m=>m>=21?'#38c9a0bb':m>=19?'#f7a54fbb':'#e05d7abb');
  charts.cMarginAll=new Chart(document.getElementById('cMarginAll'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>VD[id].name),
      datasets:[{{label:'Margen %',data:margins,backgroundColor:mc,borderColor:mc.map(c=>c.slice(0,-2)),borderWidth:2,borderRadius:5}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{ctx.raw.toFixed(2)}}%`}}}}}},
      scales:{{x:{{min:14,ticks:{{color:'#8b90b0',callback:v=>v+'%'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  // Overview table
  const sorted=[...PDV_ORDER].sort((a,b)=>(VD[b].total||0)-(VD[a].total||0));
  document.getElementById('vOvTable').innerHTML=`<thead><tr><th>#</th><th>PDV</th><th>Ventas</th><th>Sin Carn.</th><th>Part.</th><th>Margen*</th></tr></thead>
  <tbody>${{sorted.map((id,i)=>{{const d=VD[id];const col=COLORS[PDV_ORDER.indexOf(id)];
    const mc2=d.avg_margin>=21?'pg':d.avg_margin>=19?'py':'pr';
    return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
      <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{id}} ${{d.name}}</strong></td>
      <td>${{fmtFull(d.total||0)}}</td><td style="color:var(--text2)">${{fmtFull(d.total_sin||0)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px">
        <div class="bar-t" style="width:80px"><div class="bar-f" style="width:${{d.share||0}}%;background:${{col}}"></div></div>
        <span>${{d.share||0}}%</span></div></td>
      <td><span class="pill ${{mc2}}">${{(d.avg_margin||0).toFixed(2)}}%</span></td></tr>`;
  }}).join('')}}</tbody>`;
}}

function renderVBarAll(){{
  const vals=PDV_ORDER.map(id=>togMode==='con'?(VD[id].total||0):(VD[id].total_sin||0));
  charts.cBarAll=new Chart(document.getElementById('cBarAll'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>VD[id].name),
      datasets:[{{label:'Ventas',data:vals,backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
}}

function renderVPdv(id){{
  const d=VD[id];const col=COLORS[PDV_ORDER.indexOf(id)];
  document.getElementById('vBread').innerHTML=
    `<span class="bc-link" onclick="selectVPdv('all')">🏪 Todos</span>
     <span style="color:var(--border)">›</span><span class="bc-current">PDV ${{id}} – ${{d.name}}</span>`;
  document.getElementById('vCatTitle').textContent='clic en una línea para ver sus productos';
  closeProd();
  const zones=calZones(d.daily);const meta=ttMeta(d.daily);
  const labels=d.daily.map(x=>x.label);const ventas=d.daily.map(x=>x.ventas/1e6);
  dc('cDailyPdv');
  charts.cDailyPdv=new Chart(document.getElementById('cDailyPdv'),{{
    type:'bar',data:{{labels,datasets:[
      {{type:'bar',label:'Ventas',data:ventas,backgroundColor:col+'44',borderColor:col,borderWidth:1.5,borderRadius:4}},
      {{type:'line',label:'Tendencia',data:ventas,borderColor:col,borderWidth:2.5,pointRadius:0,tension:.4,fill:false}}
    ]}},
    options:{{plugins:{{calBg:{{zones}},legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},
      tooltip:{{callbacks:{{title:ctx=>ttTitle(ctx[0].label,meta),label:ctx=>` $${{ctx.raw.toFixed(1)}}M`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>v+'M'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('cMarginPdv');
  charts.cMarginPdv=new Chart(document.getElementById('cMarginPdv'),{{
    type:'line',data:{{labels,datasets:[
      {{label:'Margen %',data:d.daily.map(x=>x.margin),borderColor:'#38c9a0',
        backgroundColor:'rgba(56,201,160,.1)',borderWidth:2,fill:true,tension:.3,
        pointRadius:3,pointHoverRadius:5,
        pointBackgroundColor:d.daily.map(x=>x.tipo==='holiday'?'#e05d7a':x.tipo==='saturday'?'#f7a54f':x.tipo==='sunday'?'#f7d04f':'#38c9a0'),
        pointBorderColor:'transparent'}},
      {{label:'Promedio',data:labels.map(()=>d.avg_margin),borderColor:'#f7a54f',
        borderWidth:1.5,borderDash:[5,5],pointRadius:0}}
    ]}},
    options:{{plugins:{{calBg:{{zones}},legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},
      tooltip:{{callbacks:{{title:ctx=>ttTitle(ctx[0].label,meta),label:ctx=>ctx.datasetIndex===0?` ${{ctx.raw!==null?ctx.raw.toFixed(2)+'%':'Sin datos'}}`:`Prom: ${{ctx.raw.toFixed(2)}}%`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>v+'%'}},grid:{{color:'rgba(46,50,72,.5)'}},suggestedMin:14,suggestedMax:32}}}}}}
  }});
  // Cat table
  const total=d.total||1;
  document.getElementById('vCatBody').innerHTML=d.categories.map((cat,i)=>{{
    const pct=(cat.ventas/total*100).toFixed(1);
    const anom=(!cat.excluded&&cat.has_anomaly)?'<span class="pill pw">⚠ 99%</span>':'';
    const excl=cat.excluded?'<span class="pill pp">SIN COSTO</span>':'';
    const sel=selCatIdx===i?' selected':'';
    return`<tr class="${{sel}}" onclick="toggleCat(${{i}})" data-idx="${{i}}">
      <td><strong>${{cat.cat}}</strong></td><td>${{fmtFull(cat.ventas)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px">
        <div class="bar-t" style="width:80px"><div class="bar-f" style="width:${{Math.min(parseFloat(pct),100)}}%;background:${{CAT_COLORS[i%10]}}"></div></div>
        <span style="color:var(--text2);font-size:10px">${{pct}}%</span></div></td>
      <td>${{mPill(cat.avg_margin,cat.excluded)}}</td>
      <td style="display:flex;gap:3px;flex-wrap:wrap">${{excl}}${{anom}}</td></tr>`;
  }}).join('');
  // Top items
  document.getElementById('vTopItems').innerHTML=d.top_items.map((item,i)=>`
    <div class="item-row">
      <div class="item-rank" style="background:${{COLORS[i]}};min-width:19px;height:19px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700">${{i+1}}</div>
      <div style="flex:1;font-size:11px">${{item.name}}</div>
      <div style="font-size:11px;color:var(--accent2);font-weight:600">${{fmt(item.ventas)}}</div>
    </div>`).join('');
  // Cat bar
  dc('cCatBar');const top8=d.categories.slice(0,8);
  charts.cCatBar=new Chart(document.getElementById('cCatBar'),{{
    type:'bar',data:{{labels:top8.map(c=>c.cat.length>18?c.cat.slice(0,16)+'…':c.cat),
      datasets:[{{label:'Ventas',data:top8.map(c=>c.ventas/1e6),
        backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` $${{ctx.raw.toFixed(1)}}M`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>v+'M'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
}}

function toggleCat(idx){{
  if(selCatIdx===idx){{selCatIdx=null;closeProd();
    document.querySelectorAll('#vCatBody tr').forEach(r=>r.classList.remove('selected'));
    document.getElementById('vCatTitle').textContent='clic en una línea para ver sus productos';return;}}
  selCatIdx=idx;
  document.querySelectorAll('#vCatBody tr').forEach(r=>r.classList.toggle('selected',parseInt(r.dataset.idx)===idx));
  const cat=VD[curVPdv].categories[idx];
  document.getElementById('vCatTitle').textContent=cat.cat;
  document.getElementById('vProdTitle').textContent=`${{cat.cat}} — ${{cat.products.length}} productos`;
  const ct=cat.ventas||1;
  document.getElementById('vProdBody').innerHTML=cat.products.map((p,i)=>{{
    const pct=(p.ventas/ct*100).toFixed(1);
    let al='';
    if(p.has_99)al='<span class="pill pr">⚠ 99%</span>';
    else if(p.avg_margin>=35&&!cat.excluded)al='<span class="pill pw">↑ Alto</span>';
    else if(p.avg_margin>0&&p.avg_margin<5)al='<span class="pill pr">↓ Bajo</span>';
    return`<tr><td style="color:${{CAT_COLORS[i%10]}};font-weight:700">${{i+1}}</td>
      <td><strong>${{p.name}}</strong></td><td>${{fmtFull(p.ventas)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px">
        <div class="bar-t" style="width:70px"><div class="bar-f" style="width:${{Math.min(parseFloat(pct),100)}}%;background:${{CAT_COLORS[i%10]}}"></div></div>
        <span style="font-size:10px;color:var(--text2)">${{pct}}%</span></div></td>
      <td>${{mPill(p.avg_margin,cat.excluded)}}</td><td>${{al}}</td></tr>`;
  }}).join('');
  document.getElementById('vProdPanel').style.display='';
  setTimeout(()=>document.getElementById('vProdPanel').scrollIntoView({{behavior:'smooth',block:'nearest'}}),50);
}}
function closeProd(){{
  document.getElementById('vProdPanel').style.display='none';
  selCatIdx=null;
  document.querySelectorAll('#vCatBody tr').forEach(r=>r.classList.remove('selected'));
}}

// ══════════ NÓMINA ══════════
function initNKpis(){{
  const grand=PDV_ORDER.reduce((s,id)=>s+(ND[id]?.total_devengo||0),0);
  const totalEmp=PDV_ORDER.reduce((s,id)=>s+(ND[id]?.n_empleados||0),0);
  const avgCost=totalEmp>0?grand/totalEmp:0;
  const topN=PDV_ORDER.reduce((a,b)=>(ND[a]?.total_devengo||0)>(ND[b]?.total_devengo||0)?a:b);
  document.getElementById('nKpiRow').innerHTML=`
    <div class="kpi c1"><div class="kpi-label">Devengo Total</div><div class="kpi-val">${{fmtFull(grand)}}</div><div class="kpi-sub">Todos los PDV</div></div>
    <div class="kpi c2"><div class="kpi-label">Total Empleados</div><div class="kpi-val">${{totalEmp}}</div><div class="kpi-sub">Activos en el período</div></div>
    <div class="kpi c3"><div class="kpi-label">Costo / Empleado</div><div class="kpi-val">${{fmtFull(avgCost)}}</div><div class="kpi-sub">Promedio grupo</div></div>
    <div class="kpi c4"><div class="kpi-label">Mayor Nómina</div><div class="kpi-val">${{ND[topN].name}}</div><div class="kpi-sub">${{fmtFull(ND[topN].total_devengo||0)}}</div></div>`;
}}

function buildNNav(){{
  const nav=document.getElementById('nNav');nav.innerHTML='';
  const a=document.createElement('button');
  a.className='pdv-btn active';a.dataset.id='all';a.textContent='🏪 Todos';
  a.onclick=()=>selectNPdv('all');nav.appendChild(a);
  PDV_ORDER.forEach((id,i)=>{{
    const b=document.createElement('button');b.className='pdv-btn';b.dataset.id=id;
    b.innerHTML=`<span style="color:${{COLORS[i]}};margin-right:3px">●</span>${{id}} ${{ND[id].name}}`;
    b.onclick=()=>selectNPdv(id);nav.appendChild(b);
  }});
}}

function selectNPdv(id){{
  document.querySelectorAll('#nNav .pdv-btn').forEach(b=>b.classList.toggle('active',b.dataset.id===id));
  curNPdv=id;
  document.getElementById('nAll').style.display=id==='all'?'':'none';
  document.getElementById('nPdv').style.display=id!=='all'?'':'none';
  document.getElementById('nBread').style.display=id!=='all'?'flex':'none';
  if(id==='all')renderNAll();else renderNPdv(id);
}}

function renderNAll(){{
  dc('nBarAll');
  charts.nBarAll=new Chart(document.getElementById('nBarAll'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>ND[id].name),
      datasets:[
        {{label:'Devengo',data:PDV_ORDER.map(id=>ND[id].total_devengo||0),backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}},
        {{label:'Deducción',data:PDV_ORDER.map(id=>ND[id].total_deduccion||0),backgroundColor:'rgba(224,93,122,.4)',borderColor:'#e05d7a',borderWidth:1.5,borderRadius:5}}
      ]}},
    options:{{plugins:{{legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('nEmpBar');
  charts.nEmpBar=new Chart(document.getElementById('nEmpBar'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>ND[id].name),
      datasets:[{{label:'Empleados',data:PDV_ORDER.map(id=>ND[id].n_empleados||0),
        backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{ctx.raw}} empleados`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',stepSize:1}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('nCostEmp');
  charts.nCostEmp=new Chart(document.getElementById('nCostEmp'),{{
    type:'bar',
    data:{{labels:PDV_ORDER.map(id=>ND[id].name),
      datasets:[{{label:'Costo/Empleado',data:PDV_ORDER.map(id=>ND[id].costo_por_emp||0),
        backgroundColor:COLORS.map(c=>c+'99'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  // Overview table
  const sorted=[...PDV_ORDER].sort((a,b)=>(ND[b].total_devengo||0)-(ND[a].total_devengo||0));
  document.getElementById('nOvTable').innerHTML=`<thead><tr><th>#</th><th>PDV</th><th>Devengo</th><th>Deducción</th><th>Empleados</th><th>Costo/Emp</th></tr></thead>
  <tbody>${{sorted.map((id,i)=>{{const d=ND[id];const col=COLORS[PDV_ORDER.indexOf(id)];
    return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
      <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{id}} ${{d.name}}</strong></td>
      <td><strong>${{fmtFull(d.total_devengo||0)}}</strong></td>
      <td style="color:var(--red)">${{fmtFull(d.total_deduccion||0)}}</td>
      <td>${{d.n_empleados||0}}</td><td>${{fmtFull(d.costo_por_emp||0)}}</td></tr>`;
  }}).join('')}}</tbody>`;
}}

function renderNPdv(id){{
  const d=ND[id];const col=COLORS[PDV_ORDER.indexOf(id)];
  document.getElementById('nBread').innerHTML=
    `<span class="bc-link" onclick="selectNPdv('all')">🏪 Todos</span>
     <span style="color:var(--border)">›</span><span class="bc-current">PDV ${{id}} – ${{d.name}}</span>`;
  const cargos=d.by_cargo||[];
  dc('nCargoBars');
  charts.nCargoBars=new Chart(document.getElementById('nCargoBars'),{{
    type:'bar',
    data:{{labels:cargos.map(c=>c.cargo.length>18?c.cargo.slice(0,16)+'…':c.cargo),
      datasets:[
        {{label:'Devengo',data:cargos.map(c=>c.devengo),backgroundColor:col+'bb',borderColor:col,borderWidth:2,borderRadius:5}},
        {{label:'Deducción',data:cargos.map(c=>c.deduccion),backgroundColor:'rgba(224,93,122,.4)',borderColor:'#e05d7a',borderWidth:1.5,borderRadius:5}}
      ]}},
    options:{{indexAxis:'y',plugins:{{legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
  dc('nCargoDonut');
  charts.nCargoDonut=new Chart(document.getElementById('nCargoDonut'),{{
    type:'doughnut',
    data:{{labels:cargos.map(c=>c.cargo),
      datasets:[{{data:cargos.map(c=>c.devengo),backgroundColor:CAT_COLORS,borderWidth:2,borderColor:'#1a1d27'}}]}},
    options:{{plugins:{{legend:{{position:'right',labels:{{color:'#8b90b0',font:{{size:10}},padding:8}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{fmtFull(ctx.raw)}}`}}}}}},cutout:'55%'}}
  }});
  document.getElementById('nCargoTable').innerHTML=`<thead><tr><th>Cargo</th><th>Devengo</th><th>Deducción</th><th>Empleados</th><th>Costo/Emp</th></tr></thead>
  <tbody>${{cargos.map((c,i)=>`<tr>
    <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{CAT_COLORS[i%10]}};margin-right:6px"></span><strong>${{c.cargo}}</strong></td>
    <td>${{fmtFull(c.devengo)}}</td><td style="color:var(--red)">${{fmtFull(c.deduccion)}}</td>
    <td>${{c.empleados}}</td><td>${{fmtFull(Math.round(c.devengo/Math.max(c.empleados,1)))}}</td></tr>`).join('')}}</tbody>`;
  dc('nConceptoBar');
  const conc=Object.entries(d.by_concepto||{{}}).slice(0,8);
  charts.nConceptoBar=new Chart(document.getElementById('nConceptoBar'),{{
    type:'bar',data:{{labels:conc.map(([k])=>k.length>20?k.slice(0,18)+'…':k),
      datasets:[{{label:'Devengo',data:conc.map(([,v])=>v),
        backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
}}

// ══════════ PRODUCTIVIDAD ══════════
function initProductividad(){{
  const grandVentas = PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total||0),0);
  const grandEmp    = PDV_ORDER.reduce((s,id)=>s+(ND[id]?.n_empleados||0),0);
  const grandNom    = PDV_ORDER.reduce((s,id)=>s+(ND[id]?.total_devengo||0),0);
  const ventasPorEmp = grandEmp>0 ? grandVentas/grandEmp : 0;
  const nomPct       = grandVentas>0 ? grandNom/grandVentas*100 : 0;

  const bestVE  = PDV_ORDER.reduce((a,b)=>{{
    const va=(VD[a]?.total||0)/Math.max(ND[a]?.n_empleados||1,1);
    const vb=(VD[b]?.total||0)/Math.max(ND[b]?.n_empleados||1,1);
    return va>vb?a:b;
  }});
  const bestNP  = PDV_ORDER.reduce((a,b)=>{{
    const pa=(ND[a]?.total_devengo||0)/Math.max(VD[a]?.total||1,1)*100;
    const pb=(ND[b]?.total_devengo||0)/Math.max(VD[b]?.total||1,1)*100;
    return pa<pb?a:b;
  }});

  document.getElementById('pKpiRow').innerHTML=`
    <div class="kpi c1"><div class="kpi-label">Ventas por Empleado</div><div class="kpi-val">${{fmtFull(ventasPorEmp)}}</div><div class="kpi-sub">Grupo completo</div></div>
    <div class="kpi c2"><div class="kpi-label">% Nómina / Ventas</div><div class="kpi-val">${{nomPct.toFixed(2)}}%</div><div class="kpi-sub">Grupo completo</div></div>
    <div class="kpi c3"><div class="kpi-label">Mejor Ventas/Emp</div><div class="kpi-val">${{VD[bestVE].name}}</div><div class="kpi-sub">${{fmtFull((VD[bestVE]?.total||0)/Math.max(ND[bestVE]?.n_empleados||1,1))}}</div></div>
    <div class="kpi c4"><div class="kpi-label">Menor % Nómina</div><div class="kpi-val">${{VD[bestNP].name}}</div><div class="kpi-sub">${{((ND[bestNP]?.total_devengo||0)/Math.max(VD[bestNP]?.total||1,1)*100).toFixed(2)}}%</div></div>`;

  // Barras: Ventas por empleado
  dc('pVentasEmp');
  const veVals = PDV_ORDER.map(id=>(VD[id]?.total||0)/Math.max(ND[id]?.n_empleados||1,1));
  charts.pVentasEmp=new Chart(document.getElementById('pVentasEmp'),{{
    type:'bar',
    data:{{labels:PDV_ORDER.map(id=>VD[id].name),
      datasets:[{{label:'Ventas/Empleado',data:veVals,
        backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});

  // Barras: % nómina sobre ventas
  dc('pNomPct');
  const npVals = PDV_ORDER.map(id=>(ND[id]?.total_devengo||0)/Math.max(VD[id]?.total||1,1)*100);
  const npColors = npVals.map(v=>v<8?'#38c9a0bb':v<12?'#f7a54fbb':'#e05d7abb');
  charts.pNomPct=new Chart(document.getElementById('pNomPct'),{{
    type:'bar',
    data:{{labels:PDV_ORDER.map(id=>VD[id].name),
      datasets:[{{label:'% Nómina/Ventas',data:npVals,
        backgroundColor:npColors,borderColor:npColors.map(c=>c.slice(0,-2)),borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{ctx.raw.toFixed(2)}}%`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>v+'%'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});

  // Barras agrupadas: Ventas vs Nómina
  dc('pVsNom');
  charts.pVsNom=new Chart(document.getElementById('pVsNom'),{{
    type:'bar',
    data:{{labels:PDV_ORDER.map(id=>VD[id].name),
      datasets:[
        {{label:'Ventas',data:PDV_ORDER.map(id=>VD[id]?.total||0),
          backgroundColor:'#4f6ef7bb',borderColor:'#4f6ef7',borderWidth:2,borderRadius:4}},
        {{label:'Nómina',data:PDV_ORDER.map(id=>ND[id]?.total_devengo||0),
          backgroundColor:'#e05d7abb',borderColor:'#e05d7a',borderWidth:2,borderRadius:4}}
      ]}},
    options:{{plugins:{{legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});

  // Tabla ranking por ventas/empleado
  const ranked=[...PDV_ORDER].sort((a,b)=>{{
    const va=(VD[a]?.total||0)/Math.max(ND[a]?.n_empleados||1,1);
    const vb=(VD[b]?.total||0)/Math.max(ND[b]?.n_empleados||1,1);
    return vb-va;
  }});
  document.getElementById('pTable').innerHTML=`
    <thead><tr><th>#</th><th>PDV</th><th>Ventas Totales</th><th>Empleados</th><th>Nómina Total</th><th>Ventas/Empleado</th><th>Nómina % Ventas</th></tr></thead>
    <tbody>${{ranked.map((id,i)=>{{
      const col=COLORS[PDV_ORDER.indexOf(id)];
      const ve=(VD[id]?.total||0)/Math.max(ND[id]?.n_empleados||1,1);
      const np=(ND[id]?.total_devengo||0)/Math.max(VD[id]?.total||1,1)*100;
      const npCls=np<8?'pg':np<12?'py':'pr';
      return`<tr>
        <td style="color:${{col}};font-weight:700">#${{i+1}}</td>
        <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{id}} ${{VD[id].name}}</strong></td>
        <td>${{fmtFull(VD[id]?.total||0)}}</td>
        <td>${{ND[id]?.n_empleados||0}}</td>
        <td>${{fmtFull(ND[id]?.total_devengo||0)}}</td>
        <td style="font-weight:600;color:var(--accent2)">${{fmtFull(ve)}}</td>
        <td><span class="pill ${{npCls}}">${{np.toFixed(2)}}%</span></td></tr>`;
    }}).join('')}}</tbody>`;
}}

// ══════════ ALERTAS ══════════
function initAlertas(){{
  // ── 1. Semáforo nómina
  const semHtml = PDV_ORDER.map((id,i)=>{{
    const np=(ND[id]?.total_devengo||0)/Math.max(VD[id]?.total||1,1)*100;
    const col=np<8?'var(--green)':np<12?'var(--yellow)':'var(--red)';
    const bg=np<8?'rgba(56,201,160,.1)':np<12?'rgba(247,208,79,.1)':'rgba(224,93,122,.1)';
    const icon=np<8?'✅':np<12?'⚠️':'🔴';
    return`<div style="background:${{bg}};border:1px solid ${{col}};border-radius:12px;padding:16px;text-align:center">
      <div style="font-size:22px;margin-bottom:6px">${{icon}}</div>
      <div style="font-size:11px;color:var(--text2);margin-bottom:4px">${{id}} ${{VD[id].name}}</div>
      <div style="font-size:24px;font-weight:800;color:${{col}}">${{np.toFixed(1)}}%</div>
      <div style="font-size:10px;color:var(--text2);margin-top:3px">nómina/ventas</div>
    </div>`;
  }}).join('');
  document.getElementById('aSemaforo').innerHTML=semHtml;

  // ── 2. Alertas de margen
  const groupAvgM=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.avg_margin||0),0)/PDV_ORDER.length;
  const margenHtml=PDV_ORDER.map(id=>{{
    const m=VD[id]?.avg_margin||0;
    const diff=m-groupAvgM;
    const isRed=diff<-2, isYellow=diff>=-2&&diff<0;
    if(!isRed&&!isYellow)return'';
    const col=isRed?'var(--red)':'var(--yellow)';
    const bg=isRed?'rgba(224,93,122,.08)':'rgba(247,208,79,.08)';
    const border=isRed?'rgba(224,93,122,.4)':'rgba(247,208,79,.4)';
    const icon=isRed?'🔴':'⚠️';
    const label=isRed?'Por debajo del promedio del grupo':'Cerca del promedio del grupo';
    // Lines with 99% margin
    const lines99=(VD[id]?.categories||[])
      .filter(c=>c.has_anomaly)
      .map(c=>`<span style="background:rgba(168,85,247,.15);color:var(--purple);padding:2px 7px;border-radius:5px;font-size:10px;margin:2px">${{c.cat}}</span>`)
      .join('');
    return`<div style="background:${{bg}};border:1px solid ${{border}};border-radius:10px;padding:14px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span style="font-size:16px">${{icon}}</span>
        <strong style="color:${{col}}">${{id}} ${{VD[id].name}}</strong>
        <span style="color:var(--text2);font-size:12px">Margen: <strong style="color:${{col}}">${{m.toFixed(2)}}%</strong> (prom. grupo: ${{groupAvgM.toFixed(2)}}% | dif: ${{diff.toFixed(2)}}%)</span>
        <span style="font-size:11px;color:var(--text2);margin-left:4px">${{label}}</span>
      </div>
      ${{lines99?`<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:3px;align-items:center">
        <span style="font-size:10px;color:var(--text2);margin-right:4px">Líneas sin costo (99%):</span>${{lines99}}</div>`:''}}</div>`;
  }}).filter(Boolean).join('');
  document.getElementById('aMargen').innerHTML=margenHtml||
    `<div style="color:var(--green);padding:10px">✅ Todos los PDV tienen margen dentro del rango normal.</div>`;

  // ── 3. Días críticos (excluye festivos y domingos)
  const cal=VD._meta?.cal||{{}};
  // Sumar ventas de todos los PDVs por día
  const dailyTotal={{}};
  PDV_ORDER.forEach(id=>{{(VD[id]?.daily||[]).forEach(d=>{{
    dailyTotal[d.date]=(dailyTotal[d.date]||{{ventas:0,tipo:d.tipo,label:d.label,date:d.date}});
    dailyTotal[d.date].ventas+=d.ventas;
  }});}});
  const habil=Object.values(dailyTotal).filter(d=>d.tipo!=='holiday'&&d.tipo!=='sunday'&&d.ventas>0);
  const avgHabil=habil.reduce((s,d)=>s+d.ventas,0)/Math.max(habil.length,1);
  const criticos=[...habil].sort((a,b)=>a.ventas-b.ventas).slice(0,5);

  document.getElementById('aDiasCriticos').innerHTML=`
    <thead><tr><th>#</th><th>Fecha</th><th>Día</th><th>Ventas totales</th><th>vs Prom. hábil</th><th>PDV más afectado</th></tr></thead>
    <tbody>${{criticos.map((d,i)=>{{
      const diff=d.ventas-avgHabil;
      const pct=(diff/avgHabil*100).toFixed(1);
      // PDV with lowest sales that day
      const worst=PDV_ORDER.reduce((a,b)=>{{
        const va=(VD[a]?.daily||[]).find(x=>x.date===d.date)?.ventas||0;
        const vb=(VD[b]?.daily||[]).find(x=>x.date===d.date)?.ventas||0;
        return va<vb?a:b;
      }});
      const dayLabel=d.label||d.date;
      const calInfo=cal[d.date]||{{}};
      const tipoBadge=d.tipo==='saturday'?'<span class="pill py" style="font-size:9px">Sáb</span>':'';
      return`<tr>
        <td style="color:var(--red);font-weight:700">#${{i+1}}</td>
        <td><strong>${{d.date}}</strong></td>
        <td>${{dayLabel}} ${{tipoBadge}}</td>
        <td style="color:var(--red)">${{fmtFull(d.ventas)}}</td>
        <td><span class="pill pr">${{pct}}%</span></td>
        <td><span style="color:${{COLORS[PDV_ORDER.indexOf(worst)]}}">${{worst}} ${{VD[worst].name}}</span></td></tr>`;
    }}).join('')}}</tbody>`;

  // ── 4. Ranking de eficiencia
  // Umbrales: margen >= groupAvgM → verde, >= groupAvgM-2 → amarillo, else rojo
  // nomPct < 8 → verde, < 12 → amarillo, else rojo
  // ventasEmp: calc median, > median → verde, > median*0.85 → amarillo, else rojo
  const veVals=PDV_ORDER.map(id=>(VD[id]?.total||0)/Math.max(ND[id]?.n_empleados||1,1));
  const veMedian=[...veVals].sort((a,b)=>a-b)[Math.floor(veVals.length/2)];

  const scored=PDV_ORDER.map((id,i)=>{{
    const m=VD[id]?.avg_margin||0;
    const np=(ND[id]?.total_devengo||0)/Math.max(VD[id]?.total||1,1)*100;
    const ve=veVals[i];
    const sm=m>=groupAvgM?1:m>=groupAvgM-2?0:-1;
    const sn=np<8?1:np<12?0:-1;
    const sv=ve>=veMedian?1:ve>=veMedian*0.85?0:-1;
    const score=sm+sn+sv;
    return{{id,score,m,np,ve,sm,sn,sv}};
  }}).sort((a,b)=>b.score-a.score);

  function scorePill(s){{
    if(s===1)return'<span class="pill pg">+1</span>';
    if(s===0)return'<span class="pill py"> 0</span>';
    return'<span class="pill pr">−1</span>';
  }}
  function totalBadge(s){{
    const col=s>=2?'var(--green)':s>=0?'var(--yellow)':'var(--red)';
    const bg=s>=2?'rgba(56,201,160,.15)':s>=0?'rgba(247,208,79,.15)':'rgba(224,93,122,.15)';
    return`<span style="background:${{bg}};color:${{col}};padding:3px 10px;border-radius:8px;font-weight:800;font-size:13px">${{s>0?'+':''}}${{s}}</span>`;
  }}

  document.getElementById('aRanking').innerHTML=`
    <thead><tr><th>#</th><th>PDV</th><th>Score</th><th>Margen</th><th>% Nómina</th><th>Ventas/Emp</th></tr></thead>
    <tbody>${{scored.map((r,i)=>{{
      const col=COLORS[PDV_ORDER.indexOf(r.id)];
      return`<tr>
        <td style="color:${{col}};font-weight:700">#${{i+1}}</td>
        <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{r.id}} ${{VD[r.id].name}}</strong></td>
        <td>${{totalBadge(r.score)}}</td>
        <td>${{scorePill(r.sm)}} ${{r.m.toFixed(2)}}%</td>
        <td>${{scorePill(r.sn)}} ${{r.np.toFixed(2)}}%</td>
        <td>${{scorePill(r.sv)}} ${{fmtFull(r.ve)}}</td></tr>`;
    }}).join('')}}</tbody>`;
}}

// ══════════ COMPRAS ══════════
let curCPdv='all';

function initCKpis(){{
  if(!CD||!CD._meta)return;
  const grand=CD._meta.grand_total||0;
  const grandV=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total||0),0);
  const pct=grandV>0?grand/grandV*100:0;
  const top=PDV_ORDER.reduce((a,b)=>(CD[a]?.total||0)>(CD[b]?.total||0)?a:b,'001');
  const nProv=new Set(CD._meta.top_prov_global?.map(p=>p.name)||[]).size;
  document.getElementById('cKpiRow').innerHTML=`
    <div class="kpi c1"><div class="kpi-label">Compras Totales</div><div class="kpi-val">${{fmtFull(grand)}}</div><div class="kpi-sub">Todos los PDV</div></div>
    <div class="kpi c3"><div class="kpi-label">% Compras / Ventas</div><div class="kpi-val">${{pct.toFixed(1)}}%</div><div class="kpi-sub">Relación compra-venta</div></div>
    <div class="kpi c2"><div class="kpi-label">Mayor Comprador</div><div class="kpi-val">${{CD[top]?.name||'—'}}</div><div class="kpi-sub">${{fmtFull(CD[top]?.total||0)}}</div></div>
    <div class="kpi c4"><div class="kpi-label">Top Proveedores</div><div class="kpi-val">${{nProv}}</div><div class="kpi-sub">En el período</div></div>`;
}}

function buildCNav(){{
  if(!CD||!CD._meta)return;
  const nav=document.getElementById('cNav');nav.innerHTML='';
  const a=document.createElement('button');
  a.className='pdv-btn active';a.dataset.id='all';a.textContent='🏪 Todos';
  a.onclick=()=>selectCPdv('all');nav.appendChild(a);
  PDV_ORDER.forEach((id,i)=>{{
    if(!CD[id])return;
    const b=document.createElement('button');b.className='pdv-btn';b.dataset.id=id;
    b.innerHTML=`<span style="color:${{COLORS[i]}};margin-right:3px">●</span>${{id}} ${{CD[id].name}}`;
    b.onclick=()=>selectCPdv(id);nav.appendChild(b);
  }});
}}

function selectCPdv(id){{
  document.querySelectorAll('#cNav .pdv-btn').forEach(b=>b.classList.toggle('active',b.dataset.id===id));
  curCPdv=id;
  document.getElementById('cAll').style.display=id==='all'?'':'none';
  document.getElementById('cPdv').style.display=id!=='all'?'':'none';
  document.getElementById('cBread').style.display=id!=='all'?'flex':'none';
  if(id==='all')renderCAll();else renderCPdv(id);
}}

function renderCAll(){{
  if(!CD||!CD._meta)return;
  // Barras por PDV
  dc('cBarAll2');
  charts.cBarAll2=new Chart(document.getElementById('cBarAll2'),{{
    type:'bar',
    data:{{labels:PDV_ORDER.map(id=>CD[id]?.name||id),
      datasets:[{{label:'Compras',data:PDV_ORDER.map(id=>CD[id]?.total||0),
        backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  // Donut
  dc('cDonut2');
  charts.cDonut2=new Chart(document.getElementById('cDonut2'),{{
    type:'doughnut',
    data:{{labels:PDV_ORDER.map(id=>CD[id]?.name||id),
      datasets:[{{data:PDV_ORDER.map(id=>CD[id]?.total||0),backgroundColor:COLORS,borderWidth:2,borderColor:'#1a1d27'}}]}},
    options:{{plugins:{{legend:{{position:'right',labels:{{color:'#8b90b0',font:{{size:11}},padding:9}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{CD[PDV_ORDER[ctx.dataIndex]]?.share||0}}%`}}}}}},cutout:'60%'}}
  }});
  // Línea diaria todos los PDV
  dc('cLineAll2');
  const ref=CD[PDV_ORDER.find(id=>CD[id]?.daily?.length>0)||'001'];
  if(ref?.daily){{
    const zones=calZones(ref.daily);
    const meta=ttMeta(ref.daily);
    charts.cLineAll2=new Chart(document.getElementById('cLineAll2'),{{
      type:'line',
      data:{{labels:ref.daily.map(d=>d.label),datasets:PDV_ORDER.map((id,i)=>{{
        const map={{}};(CD[id]?.daily||[]).forEach(d=>map[d.label]=d.valor);
        return{{label:CD[id]?.name||id,data:ref.daily.map(d=>(map[d.label]||0)/1e6),
          borderColor:COLORS[i],backgroundColor:'transparent',borderWidth:2,pointRadius:0,tension:.3}};
      }})}},
      options:{{plugins:{{calBg:{{zones}},
        legend:{{position:'bottom',labels:{{color:'#8b90b0',font:{{size:10}},boxWidth:9,padding:7}}}},
        tooltip:{{callbacks:{{label:ctx=>` ${{CD[PDV_ORDER[ctx.datasetIndex]]?.name}}: $${{ctx.raw.toFixed(1)}}M`}}}}}},
        scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
          y:{{ticks:{{color:'#8b90b0',callback:v=>v+'M'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
    }});
  }}
  // Top proveedores globales
  dc('cProvGlobal');
  const topG=(CD._meta.top_prov_global||[]).slice(0,10);
  charts.cProvGlobal=new Chart(document.getElementById('cProvGlobal'),{{
    type:'bar',
    data:{{labels:topG.map(p=>p.name.length>28?p.name.slice(0,26)+'…':p.name),
      datasets:[{{label:'Compras',data:topG.map(p=>p.valor),
        backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
  // Tabla resumen
  const grandV=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total||0),0);
  const sorted=[...PDV_ORDER].sort((a,b)=>(CD[b]?.total||0)-(CD[a]?.total||0));
  document.getElementById('cOvTable').innerHTML=`<thead><tr><th>#</th><th>PDV</th><th>Compras</th><th>Part.</th><th>% vs Ventas</th></tr></thead>
  <tbody>${{sorted.map((id,i)=>{{
    const d=CD[id]||{{}};const col=COLORS[PDV_ORDER.indexOf(id)];
    const venta=VD[id]?.total||1;
    const pct=d.total?d.total/venta*100:0;
    const pcls=pct<70?'pg':pct<90?'py':'pr';
    return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
      <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{id}} ${{d.name||''}}</strong></td>
      <td>${{fmtFull(d.total||0)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px">
        <div class="bar-t" style="width:80px"><div class="bar-f" style="width:${{d.share||0}}%;background:${{col}}"></div></div>
        <span>${{d.share||0}}%</span></div></td>
      <td><span class="pill ${{pcls}}">${{pct.toFixed(1)}}%</span></td></tr>`;
  }}).join('')}}</tbody>`;
}}

function renderCPdv(id){{
  const d=CD[id];if(!d)return;
  const col=COLORS[PDV_ORDER.indexOf(id)];
  document.getElementById('cBread').innerHTML=
    `<span class="bc-link" onclick="selectCPdv('all')">🏪 Todos</span>
     <span style="color:var(--border)">›</span><span class="bc-current">PDV ${{id}} – ${{d.name}}</span>`;
  // Gráfico diario
  const zones=calZones(d.daily);const meta=ttMeta(d.daily);
  dc('cDailyPdv2');
  charts.cDailyPdv2=new Chart(document.getElementById('cDailyPdv2'),{{
    type:'bar',
    data:{{labels:d.daily.map(x=>x.label),datasets:[
      {{type:'bar',label:'Compras',data:d.daily.map(x=>x.valor/1e6),backgroundColor:col+'44',borderColor:col,borderWidth:1.5,borderRadius:4}},
      {{type:'line',label:'Tendencia',data:d.daily.map(x=>x.valor/1e6),borderColor:col,borderWidth:2,pointRadius:0,tension:.4,fill:false}}
    ]}},
    options:{{plugins:{{calBg:{{zones}},legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},
      tooltip:{{callbacks:{{title:ctx=>ttTitle(ctx[0].label,meta),label:ctx=>` $${{ctx.raw.toFixed(1)}}M`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>v+'M'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  // Top proveedores del PDV
  dc('cProvPdv');
  const tp=d.top_prov.slice(0,10);
  charts.cProvPdv=new Chart(document.getElementById('cProvPdv'),{{
    type:'bar',
    data:{{labels:tp.map(p=>p.name.length>25?p.name.slice(0,23)+'…':p.name),
      datasets:[{{label:'Compras',data:tp.map(p=>p.valor),
        backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
  // Tabla ítems
  const total=d.total||1;
  document.getElementById('cItemTable').innerHTML=`<thead><tr><th>#</th><th>Producto</th><th>Compras</th><th>% PDV</th></tr></thead>
  <tbody>${{d.top_items.map((it,i)=>{{
    const pct=(it.valor/total*100).toFixed(1);
    return`<tr><td style="color:${{CAT_COLORS[i%10]}};font-weight:700">${{i+1}}</td>
      <td>${{it.name}}</td><td>${{fmtFull(it.valor)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px">
        <div class="bar-t" style="width:70px"><div class="bar-f" style="width:${{Math.min(parseFloat(pct),100)}}%;background:${{CAT_COLORS[i%10]}}"></div></div>
        <span style="font-size:10px;color:var(--text2)">${{pct}}%</span></div></td></tr>`;
  }}).join('')}}</tbody>`;
  // Tabla proveedores
  document.getElementById('cProvTable').innerHTML=`<thead><tr><th>#</th><th>Proveedor</th><th>Compras</th><th>% PDV</th></tr></thead>
  <tbody>${{d.top_prov.map((p,i)=>{{
    const pct=(p.valor/total*100).toFixed(1);
    return`<tr><td style="color:${{CAT_COLORS[i%10]}};font-weight:700">${{i+1}}</td>
      <td><strong>${{p.name}}</strong></td><td>${{fmtFull(p.valor)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px">
        <div class="bar-t" style="width:70px"><div class="bar-f" style="width:${{Math.min(parseFloat(pct),100)}}%;background:${{CAT_COLORS[i%10]}}"></div></div>
        <span style="font-size:10px;color:var(--text2)">${{pct}}%</span></div></td></tr>`;
  }}).join('')}}</tbody>`;
}}

// ── TAB SWITCHING
function showTab(t){{
  document.querySelectorAll('.tab-btn').forEach((b,i)=>b.classList.toggle('active',['ventas','nomina','compras','productividad','alertas'][i]===t));
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
  if(t==='ventas'&&curVPdv==='all')renderVAll();
  if(t==='nomina'&&curNPdv==='all')renderNAll();
  if(t==='compras'&&curCPdv==='all')renderCAll();
  if(t==='productividad')initProductividad();
  if(t==='alertas')initAlertas();
}}

// ── BOOT
initVKpis();buildVNav();renderVAll();
initNKpis();buildNNav();
initCKpis();buildCNav();
</script>
</body>
</html>"""
    return html

# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────
def generate(ventas_path: Path, nomina_dir: Path, linea_dir: Path, output_dir: Path,
             year_override: int = None, month_override: int = None, compras_dir: Path = None):
    """Full pipeline: parse → combine → write HTML.

    year_override / month_override: cuando se pasan, se usan para buscar nóminas
    en vez de inferir el mes desde el archivo de ventas (útil cuando el watcher
    detecta una nómina y conoce el período exacto por el nombre del archivo).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    items_cat, items_name = load_items(linea_dir)
    ventas_data = parse_ventas(ventas_path, items_cat, items_name)

    # Detect month/year from the ventas data dates
    all_dates = ventas_data.get('_meta', {}).get('all_dates', [])
    if all_dates:
        first = date.fromisoformat(all_dates[0])
        year_ventas, month_ventas = first.year, first.month
        meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                 'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        periodo_label = f"{meses[month_ventas-1]} {year_ventas}"
    else:
        year_ventas, month_ventas = None, None
        periodo_label = ventas_path.stem

    # Usar override si se proporcionó (desde el watcher vía nombre de nómina),
    # de lo contrario usar el mes detectado desde el archivo de ventas
    year  = year_override  or year_ventas
    month = month_override or month_ventas
    if year_override and month_override:
        meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                 'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        periodo_label = f"{meses[month-1]} {year}"
        log.info(f"Período forzado por nombre de nómina: {periodo_label}")

    nom_data = parse_nominas(nomina_dir, year, month)

    # Buscar archivo de compras del mismo mes
    compras_data = None
    if compras_dir:
        mes_names = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        mes_name = mes_names[month-1] if month else None
        candidates = []
        if mes_name:
            candidates = list((compras_dir / mes_name).glob('Compras*.txt'))
        if not candidates:
            candidates = list(compras_dir.rglob('Compras*.txt'))
        if candidates:
            compras_data = parse_compras(candidates[0])
            log.info(f"Compras cargadas: {candidates[0].name}")
        else:
            log.warning("No se encontró archivo de compras")

    html = build_html(ventas_data, nom_data, periodo_label, compras_data)

    # Output filename: Dashboard_MMYYYY.html
    out_name = f"Dashboard_{month:02d}{year}.html"
    out_path = output_dir / out_name
    out_path.write_text(html, encoding='utf-8')
    log.info(f"✅ Dashboard generado: {out_path}")
    return out_path


if __name__ == '__main__':
    base = Path(__file__).parent.parent
    RENTABILIDAD_DIR = base / 'Rentabilidad' / '2026'
    NOMINA_DIR       = base / 'Nomina'        / '2026'
    COMPRAS_DIR      = base / 'Compras'       / '2026'
    LINEA_DIR        = base / 'Linea Items'
    out_dir          = base / 'Dashboards'

    if len(sys.argv) >= 2:
        ventas_p = Path(sys.argv[1])
    else:
        # Buscar recursivamente el archivo Ventas*.txt más reciente
        candidates = sorted(RENTABILIDAD_DIR.rglob('Ventas*.txt'),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            log.error(f"No se encontró ningún archivo Ventas*.txt en {RENTABILIDAD_DIR}")
            sys.exit(1)
        ventas_p = candidates[0]
        log.info(f"Archivo de ventas detectado: {ventas_p.relative_to(base)}")

    generate(ventas_p, NOMINA_DIR, LINEA_DIR, out_dir, compras_dir=COMPRAS_DIR)
