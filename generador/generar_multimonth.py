"""
generar_multimonth.py
Cagir – Dashboard multi-mes 2026
Genera un único HTML con selector de mes (Abril–Agosto).
Reutiliza todos los parsers de generar_dashboard.py.
"""
import sys, json, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import generar_dashboard as gd

BASE          = Path(__file__).parent.parent
RENT_DIR      = BASE / 'Rentabilidad' / '2026'
NOMINA_DIR    = BASE / 'Nomina'       / '2026'
COMPRAS_DIR   = BASE / 'Compras'      / '2026'
INVENTARIO_DIR= BASE / 'Inventario'   / '2026'
LINEA_DIR     = BASE / 'Linea Items'
OUTPUT_DIR    = BASE / 'Dashboards'

MESES = ['Abril', 'Mayo', 'Junio', 'Julio', 'Agosto']

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s  %(levelname)s  %(message)s',
                    datefmt='%H:%M:%S')
log = logging.getLogger(__name__)


def parse_inventario(txt_path):
    """
    Columnas: Referencia | Desc.item | Bodega | Ubicación | Lote | U.M. | Existencia
    Devuelve dict por PDV con top_items, total_skus, total_unidades,
    y _meta con top_items_global y evolucion (para comparativo).
    """
    import csv, re
    PDV_NAMES = gd.PDV_NAMES

    pdv_items = {}   # {co: {ref: {name, unidades, um}}}

    def parse_num(s):
        s = s.strip().replace('.', '').replace(',', '.')
        try: return float(s)
        except: return 0.0

    with open(txt_path, encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f, delimiter='\t')
        header = next(reader, None)
        for row in reader:
            if len(row) < 7: continue
            ref   = row[0].strip()
            name  = row[1].strip()
            co    = row[2].strip().lstrip('0') or '0'
            co    = co.zfill(3)
            um    = row[5].strip()
            exist = parse_num(row[6])
            if not ref or exist == 0: continue
            if co not in pdv_items:
                pdv_items[co] = {}
            if ref not in pdv_items[co]:
                pdv_items[co][ref] = {'name': name, 'unidades': 0.0, 'um': um}
            pdv_items[co][ref]['unidades'] += exist

    result = {}
    global_items = {}

    for co, items in pdv_items.items():
        sorted_items = sorted(items.items(), key=lambda x: -x[1]['unidades'])
        total_u = sum(v['unidades'] for v in items.values())
        top = [{'ref': k, 'name': v['name'], 'unidades': v['unidades'], 'um': v['um']}
               for k, v in sorted_items[:20]]
        result[co] = {
            'name': PDV_NAMES.get(co, co),
            'total_skus': len(items),
            'total_unidades': total_u,
            'top_items': top,
            'all_items': [{'ref': k, 'name': v['name'], 'unidades': v['unidades'], 'um': v['um']}
                          for k, v in sorted_items[:200]],
        }
        for ref, v in items.items():
            if ref not in global_items:
                global_items[ref] = {'name': v['name'], 'unidades': 0.0, 'um': v['um']}
            global_items[ref]['unidades'] += v['unidades']

    top_global = sorted(global_items.items(), key=lambda x: -x[1]['unidades'])[:20]
    result['_meta'] = {
        'top_items_global': [{'ref': k, 'name': v['name'], 'unidades': v['unidades']} for k, v in top_global],
        'total_skus': len(global_items),
        'total_unidades': sum(v['unidades'] for v in global_items.values()),
        'pdvs_con_datos': list(pdv_items.keys()),
    }
    log.info(f"  Inventario: {len(global_items)} SKUs únicos | {sum(v['unidades'] for v in global_items.values()):.0f} unidades totales")
    return result


def load_all_months():
    items_cat, items_name = gd.load_items(LINEA_DIR)
    all_data = {}

    for mes in MESES:
        ventas_path = RENT_DIR / mes / 'Ventas PDVs.txt'
        if not ventas_path.exists():
            log.warning(f"No se encontró ventas de {mes}, se omite.")
            continue
        log.info(f"=== {mes} ===")
        ventas = gd.parse_ventas(ventas_path, items_cat, items_name)

        # Detectar año/mes desde fechas
        all_dates = ventas.get('_meta', {}).get('all_dates', [])
        if all_dates:
            from datetime import date
            first = date.fromisoformat(all_dates[0])
            year, month = first.year, first.month
        else:
            year, month = 2026, MESES.index(mes) + 4

        nomina = gd.parse_nominas(NOMINA_DIR, year, month)

        compras_path = COMPRAS_DIR / mes / 'Compras PDVs.txt'
        compras = gd.parse_compras(compras_path) if compras_path.exists() else {}

        inv_path = INVENTARIO_DIR / mes / 'Inventario PDVs.txt'
        inventario = parse_inventario(inv_path) if inv_path.exists() else {}

        all_data[mes] = {'ventas': ventas, 'nomina': nomina, 'compras': compras, 'inventario': inventario}
        total_v = sum(ventas.get(co, {}).get('total', 0) for co in gd.PDV_NAMES)
        total_n = sum(nomina.get(co, {}).get('total_devengo', 0) for co in gd.PDV_NAMES)
        log.info(f"  Ventas: ${total_v/1e9:.3f}B  Nómina: ${total_n/1e6:.1f}M")

    return all_data


def build_html(all_data):
    meses_disponibles = [m for m in MESES if m in all_data]
    mes_default = meses_disponibles[-1]  # el más reciente

    js_data = json.dumps(all_data, ensure_ascii=True, separators=(',', ':'))

    chartjs_path = Path(__file__).parent / 'chart.umd.min.js'
    chartjs_inline = chartjs_path.read_text(encoding='utf-8')

    meses_js = json.dumps(meses_disponibles, ensure_ascii=True)

    # Tomo el HTML de un mes individual como base y lo adapto
    # Reutilizo build_html de generar_dashboard pero lo modifico para multi-mes
    sample_ventas = all_data[mes_default]['ventas']
    sample_nomina = all_data[mes_default]['nomina']
    sample_compras = all_data[mes_default]['compras']

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Cagir – 2026</title>
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
.mes-selector{{display:flex;gap:6px;align-items:center}}
.mes-pill{{padding:6px 14px;border-radius:18px;border:1.5px solid var(--border);
  background:var(--surface2);color:var(--text2);cursor:pointer;font-size:12px;
  font-weight:500;transition:all .2s;user-select:none}}
.mes-pill:hover{{border-color:var(--accent);color:var(--text)}}
.mes-pill.active{{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}}
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
    <div class="hlogo">CG</div>
    <div>
      <div class="htitle">Cagir</div>
      <div class="hsub">Dashboard Gerencial 2026</div>
    </div>
  </div>
  <div class="mes-selector" id="mesSel"></div>
</div>

<div class="tab-bar">
  <button class="tab-btn active" onclick="showTab('ventas')">📊 Ventas &amp; Rentabilidad</button>
  <button class="tab-btn" onclick="showTab('nomina')">👥 Nómina</button>
  <button class="tab-btn" onclick="showTab('compras')">🛒 Compras a Proveedores</button>
  <button class="tab-btn" onclick="showTab('productividad')">⚡ Productividad</button>
  <button class="tab-btn" onclick="showTab('inventario')">📦 Inventario</button>
  <button class="tab-btn" onclick="showTab('alertas')">🚨 Alertas</button>
</div>

<!-- TAB VENTAS -->
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
        <div class="note">* Margen excluye Carnes Atendidas Expendio y Panadería (líneas sin costo cargado)</div>
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
        <div class="card-title">📉 Margen Diario<span style="font-size:9px;color:var(--purple);font-weight:400;text-transform:none">(excl. carnicería y panadería)</span></div>
        <div class="chart-wrap h280"><canvas id="cMarginPdv"></canvas></div>
      </div>
    </div>
    <div class="row">
      <div class="card">
        <div class="card-title">🏷️ Ventas por Línea —
          <span id="vCatTitle" style="color:var(--text);font-weight:700;text-transform:none;font-size:12px">clic en una línea para ver sus productos</span>
        </div>
        <div style="overflow-x:auto">
          <table class="tbl"><thead><tr><th>Línea</th><th>Ventas</th><th>Participación</th><th>Margen</th><th>Estado</th></tr></thead>
          <tbody id="vCatBody"></tbody></table>
        </div>
        <div id="vProdPanel" style="display:none" class="prod-panel">
          <div class="pp-title"><span>📦</span><span id="vProdTitle"></span><span class="pp-close" onclick="closeProd()">✕</span></div>
          <div style="overflow-x:auto">
            <table class="tbl"><thead><tr><th>#</th><th>Producto</th><th>Ventas</th><th>% línea</th><th>Margen</th><th>Alerta</th></tr></thead>
            <tbody id="vProdBody"></tbody></table>
          </div>
        </div>
      </div>
    </div>
    <div class="row r2">
      <div class="card"><div class="card-title">🏆 Top 5 Productos</div><div class="item-list" id="vTopItems"></div></div>
      <div class="card"><div class="card-title">📊 Top 8 Líneas</div><div class="chart-wrap h170"><canvas id="cCatBar"></canvas></div></div>
    </div>
  </div>
</div>
</div>

<!-- TAB NÓMINA -->
<div id="tab-nomina" class="tab-content">
<div class="main">
  <div id="nKpiRow" class="kpi-row kpi-row-4"></div>
  <div class="pdv-nav" id="nNav"></div>
  <div id="nBread" class="breadcrumb" style="display:none"></div>
  <div id="nAll">
    <div class="row r2">
      <div class="card"><div class="card-title">💰 Devengo Total por PDV</div><div class="chart-wrap h250"><canvas id="nBarAll"></canvas></div></div>
      <div class="card"><div class="card-title">👤 Empleados por PDV</div><div class="chart-wrap h250"><canvas id="nEmpBar"></canvas></div></div>
    </div>
    <div class="row r2">
      <div class="card"><div class="card-title">💵 Costo Promedio por Empleado</div><div class="chart-wrap h200"><canvas id="nCostEmp"></canvas></div></div>
      <div class="card"><div class="card-title">📋 Resumen de Nómina</div><div style="overflow-x:auto"><table class="tbl" id="nOvTable"></table></div></div>
    </div>
  </div>
  <div id="nPdv" style="display:none">
    <div class="row r2">
      <div class="card"><div class="card-title">💰 Devengo por Cargo</div><div class="chart-wrap h280"><canvas id="nCargoBars"></canvas></div></div>
      <div class="card"><div class="card-title">🥧 Distribución por Cargo</div><div class="chart-wrap h280"><canvas id="nCargoDonut"></canvas></div></div>
    </div>
    <div class="row r2">
      <div class="card"><div class="card-title">📋 Detalle por Cargo</div><div style="overflow-x:auto"><table class="tbl" id="nCargoTable"></table></div></div>
      <div class="card"><div class="card-title">📑 Top Conceptos de Devengo</div><div class="chart-wrap h200"><canvas id="nConceptoBar"></canvas></div></div>
    </div>
  </div>
</div>
</div>

<!-- TAB COMPRAS -->
<div id="tab-compras" class="tab-content">
<div class="main">
  <div id="cKpiRow" class="kpi-row kpi-row-4"></div>
  <div class="pdv-nav" id="cNav"></div>
  <div id="cBread" class="breadcrumb" style="display:none"></div>
  <div id="cAll">
    <div class="row r2">
      <div class="card"><div class="card-title">🛒 Compras por PDV</div><div class="chart-wrap h250"><canvas id="cBarAll2"></canvas></div></div>
      <div class="card"><div class="card-title">🥧 Participación en Compras</div><div class="chart-wrap h250"><canvas id="cDonut2"></canvas></div></div>
    </div>
    <div class="card" style="margin-bottom:15px">
      <div class="card-title">📈 Evolución Diaria de Compras</div>
      <div class="chart-wrap h280"><canvas id="cLineAll2"></canvas></div>
    </div>
    <div class="row r2">
      <div class="card"><div class="card-title">🏭 Top 10 Proveedores Globales</div><div class="chart-wrap h280"><canvas id="cProvGlobal"></canvas></div></div>
      <div class="card"><div class="card-title">📋 Resumen Compras por PDV</div><div style="overflow-x:auto"><table class="tbl" id="cOvTable"></table></div></div>
    </div>
  </div>
  <div id="cPdv" style="display:none">
    <div class="row r2">
      <div class="card"><div class="card-title">📈 Compras Diarias</div><div class="chart-wrap h280"><canvas id="cDailyPdv2"></canvas></div></div>
      <div class="card"><div class="card-title">🏭 Top Proveedores del PDV</div><div class="chart-wrap h280"><canvas id="cProvPdv"></canvas></div></div>
    </div>
    <div class="row r2">
      <div class="card"><div class="card-title">📦 Top Productos Comprados</div><div style="overflow-x:auto"><table class="tbl" id="cItemTable"></table></div></div>
      <div class="card"><div class="card-title">🏭 Detalle Proveedores</div><div style="overflow-x:auto"><table class="tbl" id="cProvTable"></table></div></div>
    </div>
  </div>
</div>
</div>

<!-- TAB PRODUCTIVIDAD -->
<div id="tab-productividad" class="tab-content">
<div class="main">
  <div id="pKpiRow" class="kpi-row kpi-row-4"></div>
  <div class="row r2" style="margin-bottom:15px">
    <div class="card"><div class="card-title">💼 Ventas por Empleado por PDV</div><div class="chart-wrap h250"><canvas id="pVentasEmp"></canvas></div></div>
    <div class="card"><div class="card-title">📉 % Nómina sobre Ventas por PDV</div><div class="chart-wrap h250"><canvas id="pNomPct"></canvas></div></div>
  </div>
  <div class="card" style="margin-bottom:15px">
    <div class="card-title">📊 Ventas vs Nómina por PDV</div>
    <div class="chart-wrap h280"><canvas id="pVsNom"></canvas></div>
  </div>
  <div class="card"><div class="card-title">🏆 Ranking de Eficiencia por PDV</div><div style="overflow-x:auto"><table class="tbl" id="pTable"></table></div></div>
</div>
</div>

<!-- TAB INVENTARIO -->
<div id="tab-inventario" class="tab-content">
<div class="main">
  <div id="iKpiRow" class="kpi-row kpi-row-4"></div>
  <div class="pdv-nav" id="iNav"></div>
  <div id="iBread" class="breadcrumb" style="display:none"></div>

  <!-- Vista todos los PDV -->
  <div id="iAll">
    <div class="row r2">
      <div class="card">
        <div class="card-title">📊 Unidades por PDV</div>
        <div class="chart-wrap h250"><canvas id="iBarAll"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">🥧 Participación en Inventario</div>
        <div class="chart-wrap h250"><canvas id="iDonut"></canvas></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:15px">
      <div class="card-title">📈 Evolución del Inventario Total (Unidades)
        <span style="margin-left:auto;font-size:10px;color:var(--text2);font-weight:400;text-transform:none">Inventario final de cada mes</span>
      </div>
      <div class="chart-wrap h250"><canvas id="iLineEvo"></canvas></div>
    </div>
    <div class="row r2">
      <div class="card">
        <div class="card-title">🏆 Top 15 Ítems por Existencia (Global)</div>
        <div class="chart-wrap h280"><canvas id="iTopGlobal"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">📋 Resumen por PDV</div>
        <div style="overflow-x:auto"><table class="tbl" id="iOvTable"></table></div>
      </div>
    </div>
  </div>

  <!-- Vista PDV individual -->
  <div id="iPdv" style="display:none">
    <div class="row r2">
      <div class="card">
        <div class="card-title">📊 Top 15 Ítems del PDV</div>
        <div class="chart-wrap h280"><canvas id="iBarPdv"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">📈 Evolución Inventario del PDV (Meses)</div>
        <div class="chart-wrap h280"><canvas id="iLinePdv"></canvas></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">📋 Todos los Ítems del PDV
        <input id="iSearch" type="text" placeholder="Buscar ítem..." oninput="filterInv()"
          style="margin-left:auto;padding:4px 10px;border-radius:6px;border:1px solid var(--border);
          background:var(--surface2);color:var(--text);font-size:12px;width:200px">
      </div>
      <div style="overflow-x:auto;max-height:420px;overflow-y:auto">
        <table class="tbl" id="iAllTable"></table>
      </div>
    </div>
  </div>
</div>
</div>

<!-- TAB ALERTAS -->
<div id="tab-alertas" class="tab-content">
<div class="main">
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
  <div class="card" style="margin-bottom:15px">
    <div class="card-title">📉 Alertas de Margen por PDV</div>
    <div id="aMargen" style="display:flex;flex-direction:column;gap:10px"></div>
  </div>
  <div class="card" style="margin-bottom:15px">
    <div class="card-title">📅 5 Días Críticos del Mes
      <span style="font-size:10px;color:var(--text2);font-weight:400;text-transform:none;margin-left:6px">(excluye festivos y domingos)</span>
    </div>
    <div style="overflow-x:auto"><table class="tbl" id="aDiasCriticos"></table></div>
  </div>
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
const ALLMONTHS = JSON.parse(document.getElementById('allData').textContent);
const MESES = {meses_js};
const PDV_ORDER = ['001','002','003','004','005','006','007','008'];
const COLORS = ['#4f6ef7','#38c9a0','#f7a54f','#e05d7a','#a855f7','#f7d04f','#06b6d4','#84cc16'];
const CAT_COLORS = ['#4f6ef7','#38c9a0','#f7a54f','#e05d7a','#a855f7','#f7d04f','#06b6d4','#84cc16','#fb923c','#f472b6'];

let curMes = MESES[MESES.length-1];
let VD, ND, CD;
let charts={{}}, togMode='con', curVPdv='all', curNPdv='all', curCPdv='all', selCatIdx=null;
let curTab = 'ventas';

function setMesData(){{
  VD = ALLMONTHS[curMes].ventas;
  ND = ALLMONTHS[curMes].nomina;
  CD = ALLMONTHS[curMes].compras || {{}};
}}

// ── Selector de mes
function buildMesSel(){{
  document.getElementById('mesSel').innerHTML = MESES.map(m=>
    `<div class="mes-pill${{m===curMes?' active':''}}" data-mes="${{m}}" onclick="cambiarMes(this.dataset.mes)">${{m}} 2026</div>`
  ).join('');
}}
function cambiarMes(m){{
  curMes=m; curVPdv='all'; curNPdv='all'; curCPdv='all'; selCatIdx=null;
  setMesData();
  buildMesSel();
  destroyAllCharts();
  renderTab(curTab);
}}
function destroyAllCharts(){{
  Object.keys(charts).forEach(k=>{{if(charts[k]){{charts[k].destroy();delete charts[k];}}}});
}}

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
  dc('cDonut');
  charts.cDonut=new Chart(document.getElementById('cDonut'),{{
    type:'doughnut',
    data:{{labels:PDV_ORDER.map(id=>VD[id].name),
      datasets:[{{data:PDV_ORDER.map(id=>VD[id].total||0),backgroundColor:COLORS,borderWidth:2,borderColor:'#1a1d27'}}]}},
    options:{{plugins:{{legend:{{position:'right',labels:{{color:'#8b90b0',font:{{size:11}},padding:9}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{VD[PDV_ORDER[ctx.dataIndex]].share}}%`}}}}}},cutout:'60%'}}
  }});
  dc('cLineAll');
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
      {{label:'Promedio',data:labels.map(()=>d.avg_margin),borderColor:'#f7a54f',borderWidth:1.5,borderDash:[5,5],pointRadius:0}}
    ]}},
    options:{{plugins:{{calBg:{{zones}},legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},
      tooltip:{{callbacks:{{title:ctx=>ttTitle(ctx[0].label,meta),label:ctx=>ctx.datasetIndex===0?` ${{ctx.raw!==null?ctx.raw.toFixed(2)+'%':'Sin datos'}}`:`Prom: ${{ctx.raw.toFixed(2)}}%`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>v+'%'}},grid:{{color:'rgba(46,50,72,.5)'}},suggestedMin:14,suggestedMax:32}}}}}}
  }});
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
  document.getElementById('vTopItems').innerHTML=d.top_items.map((item,i)=>`
    <div class="item-row">
      <div class="item-rank" style="background:${{COLORS[i]}};min-width:19px;height:19px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700">${{i+1}}</div>
      <div style="flex:1;font-size:11px">${{item.name}}</div>
      <div style="font-size:11px;color:var(--accent2);font-weight:600">${{fmt(item.ventas)}}</div>
    </div>`).join('');
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
  document.getElementById('vProdPanel').style.display='none';selCatIdx=null;
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
  const a=document.createElement('button');a.className='pdv-btn active';a.dataset.id='all';a.textContent='🏪 Todos';
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
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('nEmpBar');
  charts.nEmpBar=new Chart(document.getElementById('nEmpBar'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>ND[id].name),
      datasets:[{{label:'Empleados',data:PDV_ORDER.map(id=>ND[id].n_empleados||0),backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{ctx.raw}} empleados`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',stepSize:1}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('nCostEmp');
  charts.nCostEmp=new Chart(document.getElementById('nCostEmp'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>ND[id].name),
      datasets:[{{label:'Costo/Empleado',data:PDV_ORDER.map(id=>ND[id].costo_por_emp||0),backgroundColor:COLORS.map(c=>c+'99'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  const sorted=[...PDV_ORDER].sort((a,b)=>(ND[b].total_devengo||0)-(ND[a].total_devengo||0));
  document.getElementById('nOvTable').innerHTML=`<thead><tr><th>#</th><th>PDV</th><th>Devengo</th><th>Deducción</th><th>Empleados</th><th>Costo/Emp</th></tr></thead>
  <tbody>${{sorted.map((id,i)=>{{const d=ND[id];const col=COLORS[PDV_ORDER.indexOf(id)];
    return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
      <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{id}} ${{d.name}}</strong></td>
      <td><strong>${{fmtFull(d.total_devengo||0)}}</strong></td><td style="color:var(--red)">${{fmtFull(d.total_deduccion||0)}}</td>
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
    type:'bar',data:{{labels:cargos.map(c=>c.cargo.length>18?c.cargo.slice(0,16)+'…':c.cargo),
      datasets:[
        {{label:'Devengo',data:cargos.map(c=>c.devengo),backgroundColor:col+'bb',borderColor:col,borderWidth:2,borderRadius:5}},
        {{label:'Deducción',data:cargos.map(c=>c.deduccion),backgroundColor:'rgba(224,93,122,.4)',borderColor:'#e05d7a',borderWidth:1.5,borderRadius:5}}
      ]}},
    options:{{indexAxis:'y',plugins:{{legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
  dc('nCargoDonut');
  charts.nCargoDonut=new Chart(document.getElementById('nCargoDonut'),{{
    type:'doughnut',data:{{labels:cargos.map(c=>c.cargo),
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
      datasets:[{{label:'Devengo',data:conc.map(([,v])=>v),backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
}}

// ══════════ COMPRAS ══════════
function initCKpis(){{
  if(!CD||!CD._meta)return;
  const grand=CD._meta.grand_total||0;
  const grandV=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total||0),0);
  const pct=grandV>0?grand/grandV*100:0;
  const top=PDV_ORDER.reduce((a,b)=>(CD[a]?.total||0)>(CD[b]?.total||0)?a:b,'001');
  const nProv=(CD._meta.top_prov_global||[]).length;
  document.getElementById('cKpiRow').innerHTML=`
    <div class="kpi c1"><div class="kpi-label">Compras Totales</div><div class="kpi-val">${{fmtFull(grand)}}</div><div class="kpi-sub">Todos los PDV</div></div>
    <div class="kpi c3"><div class="kpi-label">% Compras / Ventas</div><div class="kpi-val">${{pct.toFixed(1)}}%</div><div class="kpi-sub">Relación compra-venta</div></div>
    <div class="kpi c2"><div class="kpi-label">Mayor Comprador</div><div class="kpi-val">${{CD[top]?.name||'—'}}</div><div class="kpi-sub">${{fmtFull(CD[top]?.total||0)}}</div></div>
    <div class="kpi c4"><div class="kpi-label">Top Proveedores</div><div class="kpi-val">${{nProv}}</div><div class="kpi-sub">En el período</div></div>`;
}}
function buildCNav(){{
  if(!CD||!CD._meta)return;
  const nav=document.getElementById('cNav');nav.innerHTML='';
  const a=document.createElement('button');a.className='pdv-btn active';a.dataset.id='all';a.textContent='🏪 Todos';
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
  dc('cBarAll2');
  charts.cBarAll2=new Chart(document.getElementById('cBarAll2'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>CD[id]?.name||id),
      datasets:[{{label:'Compras',data:PDV_ORDER.map(id=>CD[id]?.total||0),backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('cDonut2');
  charts.cDonut2=new Chart(document.getElementById('cDonut2'),{{
    type:'doughnut',data:{{labels:PDV_ORDER.map(id=>CD[id]?.name||id),
      datasets:[{{data:PDV_ORDER.map(id=>CD[id]?.total||0),backgroundColor:COLORS,borderWidth:2,borderColor:'#1a1d27'}}]}},
    options:{{plugins:{{legend:{{position:'right',labels:{{color:'#8b90b0',font:{{size:11}},padding:9}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{CD[PDV_ORDER[ctx.dataIndex]]?.share||0}}%`}}}}}},cutout:'60%'}}
  }});
  dc('cLineAll2');
  const ref=CD[PDV_ORDER.find(id=>CD[id]?.daily?.length>0)||'001'];
  if(ref?.daily){{
    const zones=calZones(ref.daily);const meta=ttMeta(ref.daily);
    charts.cLineAll2=new Chart(document.getElementById('cLineAll2'),{{
      type:'line',
      data:{{labels:ref.daily.map(d=>d.label),datasets:PDV_ORDER.map((id,i)=>{{
        const map={{}};(CD[id]?.daily||[]).forEach(d=>map[d.label]=d.valor);
        return{{label:CD[id]?.name||id,data:ref.daily.map(d=>(map[d.label]||0)/1e6),
          borderColor:COLORS[i],backgroundColor:'transparent',borderWidth:2,pointRadius:0,tension:.3}};
      }})}},
      options:{{plugins:{{calBg:{{zones}},legend:{{position:'bottom',labels:{{color:'#8b90b0',font:{{size:10}},boxWidth:9,padding:7}}}},
        tooltip:{{callbacks:{{label:ctx=>` ${{CD[PDV_ORDER[ctx.datasetIndex]]?.name}}: $${{ctx.raw.toFixed(1)}}M`}}}}}},
        scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
          y:{{ticks:{{color:'#8b90b0',callback:v=>v+'M'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
    }});
  }}
  dc('cProvGlobal');
  const topG=(CD._meta.top_prov_global||[]).slice(0,10);
  charts.cProvGlobal=new Chart(document.getElementById('cProvGlobal'),{{
    type:'bar',data:{{labels:topG.map(p=>p.name.length>28?p.name.slice(0,26)+'…':p.name),
      datasets:[{{label:'Compras',data:topG.map(p=>p.valor),backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
  const grandV=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total||0),0);
  const sorted=[...PDV_ORDER].sort((a,b)=>(CD[b]?.total||0)-(CD[a]?.total||0));
  document.getElementById('cOvTable').innerHTML=`<thead><tr><th>#</th><th>PDV</th><th>Compras</th><th>Part.</th><th>% vs Ventas</th></tr></thead>
  <tbody>${{sorted.map((id,i)=>{{const d=CD[id]||{{}};const col=COLORS[PDV_ORDER.indexOf(id)];
    const pct=d.total?(d.total/(VD[id]?.total||1)*100):0;
    const pcls=pct<70?'pg':pct<90?'py':'pr';
    return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
      <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{id}} ${{d.name||''}}</strong></td>
      <td>${{fmtFull(d.total||0)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px"><div class="bar-t" style="width:80px"><div class="bar-f" style="width:${{d.share||0}}%;background:${{col}}"></div></div><span>${{d.share||0}}%</span></div></td>
      <td><span class="pill ${{pcls}}">${{pct.toFixed(1)}}%</span></td></tr>`;
  }}).join('')}}</tbody>`;
}}
function renderCPdv(id){{
  const d=CD[id];if(!d)return;const col=COLORS[PDV_ORDER.indexOf(id)];
  document.getElementById('cBread').innerHTML=
    `<span class="bc-link" onclick="selectCPdv('all')">🏪 Todos</span>
     <span style="color:var(--border)">›</span><span class="bc-current">PDV ${{id}} – ${{d.name}}</span>`;
  const zones=calZones(d.daily);const meta=ttMeta(d.daily);
  dc('cDailyPdv2');
  charts.cDailyPdv2=new Chart(document.getElementById('cDailyPdv2'),{{
    type:'bar',data:{{labels:d.daily.map(x=>x.label),datasets:[
      {{type:'bar',label:'Compras',data:d.daily.map(x=>x.valor/1e6),backgroundColor:col+'44',borderColor:col,borderWidth:1.5,borderRadius:4}},
      {{type:'line',label:'Tendencia',data:d.daily.map(x=>x.valor/1e6),borderColor:col,borderWidth:2,pointRadius:0,tension:.4,fill:false}}
    ]}},
    options:{{plugins:{{calBg:{{zones}},legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},
      tooltip:{{callbacks:{{title:ctx=>ttTitle(ctx[0].label,meta),label:ctx=>` $${{ctx.raw.toFixed(1)}}M`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',font:{{size:9}},maxTicksLimit:30}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>v+'M'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('cProvPdv');const tp=d.top_prov.slice(0,10);
  charts.cProvPdv=new Chart(document.getElementById('cProvPdv'),{{
    type:'bar',data:{{labels:tp.map(p=>p.name.length>25?p.name.slice(0,23)+'…':p.name),
      datasets:[{{label:'Compras',data:tp.map(p=>p.valor),backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});
  const total=d.total||1;
  document.getElementById('cItemTable').innerHTML=`<thead><tr><th>#</th><th>Producto</th><th>Compras</th><th>% PDV</th></tr></thead>
  <tbody>${{d.top_items.map((it,i)=>{{const pct=(it.valor/total*100).toFixed(1);
    return`<tr><td style="color:${{CAT_COLORS[i%10]}};font-weight:700">${{i+1}}</td><td>${{it.name}}</td><td>${{fmtFull(it.valor)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px"><div class="bar-t" style="width:70px"><div class="bar-f" style="width:${{Math.min(parseFloat(pct),100)}}%;background:${{CAT_COLORS[i%10]}}"></div></div>
      <span style="font-size:10px;color:var(--text2)">${{pct}}%</span></div></td></tr>`;
  }}).join('')}}</tbody>`;
  document.getElementById('cProvTable').innerHTML=`<thead><tr><th>#</th><th>Proveedor</th><th>Compras</th><th>% PDV</th></tr></thead>
  <tbody>${{d.top_prov.map((p,i)=>{{const pct=(p.valor/total*100).toFixed(1);
    return`<tr><td style="color:${{CAT_COLORS[i%10]}};font-weight:700">${{i+1}}</td><td><strong>${{p.name}}</strong></td><td>${{fmtFull(p.valor)}}</td>
      <td><div style="display:flex;align-items:center;gap:5px"><div class="bar-t" style="width:70px"><div class="bar-f" style="width:${{Math.min(parseFloat(pct),100)}}%;background:${{CAT_COLORS[i%10]}}"></div></div>
      <span style="font-size:10px;color:var(--text2)">${{pct}}%</span></div></td></tr>`;
  }}).join('')}}</tbody>`;
}}

// ══════════ PRODUCTIVIDAD ══════════
function initProductividad(){{
  const grandVentas=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.total||0),0);
  const grandEmp=PDV_ORDER.reduce((s,id)=>s+(ND[id]?.n_empleados||0),0);
  const grandNom=PDV_ORDER.reduce((s,id)=>s+(ND[id]?.total_devengo||0),0);
  const ventasPorEmp=grandEmp>0?grandVentas/grandEmp:0;
  const nomPct=grandVentas>0?grandNom/grandVentas*100:0;
  const bestVE=PDV_ORDER.reduce((a,b)=>{{
    const va=(VD[a]?.total||0)/Math.max(ND[a]?.n_empleados||1,1);
    const vb=(VD[b]?.total||0)/Math.max(ND[b]?.n_empleados||1,1);
    return va>vb?a:b;
  }});
  const bestNP=PDV_ORDER.reduce((a,b)=>{{
    const pa=(ND[a]?.total_devengo||0)/Math.max(VD[a]?.total||1,1)*100;
    const pb=(ND[b]?.total_devengo||0)/Math.max(VD[b]?.total||1,1)*100;
    return pa<pb?a:b;
  }});
  document.getElementById('pKpiRow').innerHTML=`
    <div class="kpi c1"><div class="kpi-label">Ventas por Empleado</div><div class="kpi-val">${{fmtFull(ventasPorEmp)}}</div><div class="kpi-sub">Grupo completo</div></div>
    <div class="kpi c2"><div class="kpi-label">% Nómina / Ventas</div><div class="kpi-val">${{nomPct.toFixed(2)}}%</div><div class="kpi-sub">Grupo completo</div></div>
    <div class="kpi c3"><div class="kpi-label">Mejor Ventas/Emp</div><div class="kpi-val">${{VD[bestVE].name}}</div><div class="kpi-sub">${{fmtFull((VD[bestVE]?.total||0)/Math.max(ND[bestVE]?.n_empleados||1,1))}}</div></div>
    <div class="kpi c4"><div class="kpi-label">Menor % Nómina</div><div class="kpi-val">${{VD[bestNP].name}}</div><div class="kpi-sub">${{((ND[bestNP]?.total_devengo||0)/Math.max(VD[bestNP]?.total||1,1)*100).toFixed(2)}}%</div></div>`;
  dc('pVentasEmp');
  const veVals=PDV_ORDER.map(id=>(VD[id]?.total||0)/Math.max(ND[id]?.n_empleados||1,1));
  charts.pVentasEmp=new Chart(document.getElementById('pVentasEmp'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>VD[id].name),datasets:[{{label:'Ventas/Empleado',data:veVals,backgroundColor:COLORS.map(c=>c+'bb'),borderColor:COLORS,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('pNomPct');
  const npVals=PDV_ORDER.map(id=>(ND[id]?.total_devengo||0)/Math.max(VD[id]?.total||1,1)*100);
  const npColors=npVals.map(v=>v<8?'#38c9a0bb':v<12?'#f7a54fbb':'#e05d7abb');
  charts.pNomPct=new Chart(document.getElementById('pNomPct'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>VD[id].name),datasets:[{{label:'% Nómina/Ventas',data:npVals,backgroundColor:npColors,borderColor:npColors.map(c=>c.slice(0,-2)),borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{ctx.raw.toFixed(2)}}%`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',callback:v=>v+'%'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
  dc('pVsNom');
  charts.pVsNom=new Chart(document.getElementById('pVsNom'),{{
    type:'bar',data:{{labels:PDV_ORDER.map(id=>VD[id].name),datasets:[
      {{label:'Ventas',data:PDV_ORDER.map(id=>VD[id]?.total||0),backgroundColor:'#4f6ef7bb',borderColor:'#4f6ef7',borderWidth:2,borderRadius:4}},
      {{label:'Nómina',data:PDV_ORDER.map(id=>ND[id]?.total_devengo||0),backgroundColor:'#e05d7abb',borderColor:'#e05d7a',borderWidth:2,borderRadius:4}}
    ]}},
    options:{{plugins:{{legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},tooltip:{{callbacks:{{label:ctx=>` ${{fmtFull(ctx.raw)}}`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',callback:v=>fmt(v)}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});
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
      return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
        <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{id}} ${{VD[id].name}}</strong></td>
        <td>${{fmtFull(VD[id]?.total||0)}}</td><td>${{ND[id]?.n_empleados||0}}</td>
        <td>${{fmtFull(ND[id]?.total_devengo||0)}}</td>
        <td style="font-weight:600;color:var(--accent2)">${{fmtFull(ve)}}</td>
        <td><span class="pill ${{npCls}}">${{np.toFixed(2)}}%</span></td></tr>`;
    }}).join('')}}</tbody>`;
}}

// ══════════ INVENTARIO ══════════
let curIPdv='all', invAllItems=[];

function initIKpis(){{
  const ID=ALLMONTHS[curMes].inventario||{{}};
  const meta=ID._meta||{{}};
  const pdvsData=Object.keys(ID).filter(k=>k!=='_meta');
  const totalU=meta.total_unidades||0;
  const totalSKU=meta.total_skus||0;
  const topPdv=pdvsData.reduce((a,b)=>(ID[a]?.total_unidades||0)>(ID[b]?.total_unidades||0)?a:b,pdvsData[0]||'001');
  const prevMes=MESES[MESES.indexOf(curMes)-1];
  const prevID=prevMes?ALLMONTHS[prevMes]?.inventario:null;
  const prevU=prevID?(prevID._meta?.total_unidades||0):0;
  const varU=prevU>0?((totalU-prevU)/prevU*100):null;
  const varStr=varU!==null?(varU>=0?`▲ ${{varU.toFixed(1)}}%`:`▼ ${{Math.abs(varU).toFixed(1)}}%`):'—';
  const varCol=varU===null?'var(--text2)':varU>=0?'var(--green)':'var(--red)';
  document.getElementById('iKpiRow').innerHTML=`
    <div class="kpi c1"><div class="kpi-label">Total Unidades</div><div class="kpi-val">${{Math.round(totalU).toLocaleString('es-CO')}}</div><div class="kpi-sub">Inventario final del mes</div></div>
    <div class="kpi c2"><div class="kpi-label">SKUs Únicos</div><div class="kpi-val">${{totalSKU}}</div><div class="kpi-sub">Referencias distintas</div></div>
    <div class="kpi c3"><div class="kpi-label">Mayor Stock</div><div class="kpi-val">${{ID[topPdv]?.name||'—'}}</div><div class="kpi-sub">${{Math.round(ID[topPdv]?.total_unidades||0).toLocaleString('es-CO')}} uds</div></div>
    <div class="kpi c5"><div class="kpi-label">vs Mes Anterior</div><div class="kpi-val" style="color:${{varCol}}">${{varStr}}</div><div class="kpi-sub">${{prevMes||'Sin datos previos'}}</div></div>`;
}}

function buildINav(){{
  const ID=ALLMONTHS[curMes].inventario||{{}};
  const nav=document.getElementById('iNav');nav.innerHTML='';
  const a=document.createElement('button');a.className='pdv-btn active';a.dataset.id='all';a.textContent='🏪 Todos';
  a.onclick=()=>selectIPdv('all');nav.appendChild(a);
  const pdvs=(ID._meta?.pdvs_con_datos||[]).sort();
  pdvs.forEach(co=>{{
    const i=gd_pdv_idx(co);
    const b=document.createElement('button');b.className='pdv-btn';b.dataset.id=co;
    b.innerHTML=`<span style="color:${{COLORS[i]}};margin-right:3px">●</span>${{co}} ${{ID[co]?.name||co}}`;
    b.onclick=()=>selectIPdv(co);nav.appendChild(b);
  }});
}}

function gd_pdv_idx(co){{return PDV_ORDER.indexOf(co);}}

function selectIPdv(id){{
  document.querySelectorAll('#iNav .pdv-btn').forEach(b=>b.classList.toggle('active',b.dataset.id===id));
  curIPdv=id;
  document.getElementById('iAll').style.display=id==='all'?'':'none';
  document.getElementById('iPdv').style.display=id!=='all'?'':'none';
  document.getElementById('iBread').style.display=id!=='all'?'flex':'none';
  if(id==='all')renderIAll();else renderIPdv(id);
}}

function renderIAll(){{
  const ID=ALLMONTHS[curMes].inventario||{{}};
  const pdvs=(ID._meta?.pdvs_con_datos||[]).sort();
  const labels=pdvs.map(co=>ID[co]?.name||co);
  const vals=pdvs.map(co=>ID[co]?.total_unidades||0);
  const cols=pdvs.map(co=>COLORS[gd_pdv_idx(co)]);

  dc('iBarAll');
  charts.iBarAll=new Chart(document.getElementById('iBarAll'),{{
    type:'bar',data:{{labels,datasets:[{{label:'Unidades',data:vals,backgroundColor:cols.map(c=>c+'bb'),borderColor:cols,borderWidth:2,borderRadius:5}}]}},
    options:{{plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{Math.round(ctx.raw).toLocaleString('es-CO')}} uds`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.5)'}}}},y:{{ticks:{{color:'#8b90b0',callback:v=>Math.round(v/1000)+'K'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});

  dc('iDonut');
  charts.iDonut=new Chart(document.getElementById('iDonut'),{{
    type:'doughnut',data:{{labels,datasets:[{{data:vals,backgroundColor:cols,borderWidth:2,borderColor:'#1a1d27'}}]}},
    options:{{plugins:{{legend:{{position:'right',labels:{{color:'#8b90b0',font:{{size:11}},padding:9}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.label}}: ${{Math.round(ctx.raw).toLocaleString('es-CO')}} uds`}}}}}},cutout:'60%'}}
  }});

  // Evolución mes a mes
  dc('iLineEvo');
  const mesLabels=MESES.filter(m=>ALLMONTHS[m]?.inventario?._meta);
  const dsEvo=pdvs.map((co,i)=>{{
    return{{
      label:ID[co]?.name||co,
      data:mesLabels.map(m=>ALLMONTHS[m]?.inventario?.[co]?.total_unidades||0),
      borderColor:cols[i],backgroundColor:'transparent',borderWidth:2.5,
      pointRadius:5,pointHoverRadius:7,tension:.3
    }};
  }});
  charts.iLineEvo=new Chart(document.getElementById('iLineEvo'),{{
    type:'line',data:{{labels:mesLabels,datasets:dsEvo}},
    options:{{plugins:{{legend:{{position:'bottom',labels:{{color:'#8b90b0',font:{{size:11}},boxWidth:10,padding:10}}}},
      tooltip:{{callbacks:{{label:ctx=>` ${{ctx.dataset.label}}: ${{Math.round(ctx.raw).toLocaleString('es-CO')}} uds`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:'#8b90b0',callback:v=>Math.round(v/1000)+'K'}},grid:{{color:'rgba(46,50,72,.5)'}}}}}}}}
  }});

  // Top global
  dc('iTopGlobal');
  const top15=(ID._meta?.top_items_global||[]).slice(0,15);
  charts.iTopGlobal=new Chart(document.getElementById('iTopGlobal'),{{
    type:'bar',
    data:{{labels:top15.map(t=>t.name.length>30?t.name.slice(0,28)+'…':t.name),
      datasets:[{{label:'Unidades',data:top15.map(t=>t.unidades),
        backgroundColor:CAT_COLORS.map(c=>c+'bb'),borderColor:CAT_COLORS,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{Math.round(ctx.raw).toLocaleString('es-CO')}} uds`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>Math.round(v/1000)+'K'}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});

  const grand=ID._meta?.total_unidades||1;
  const sortedPdv=[...pdvs].sort((a,b)=>(ID[b]?.total_unidades||0)-(ID[a]?.total_unidades||0));
  document.getElementById('iOvTable').innerHTML=`
    <thead><tr><th>#</th><th>PDV</th><th>SKUs</th><th>Total Unidades</th><th>Participación</th></tr></thead>
    <tbody>${{sortedPdv.map((co,i)=>{{
      const d=ID[co];const col=COLORS[gd_pdv_idx(co)];
      const pct=(d.total_unidades/grand*100).toFixed(1);
      return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
        <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{co}} ${{d.name}}</strong></td>
        <td>${{d.total_skus}}</td>
        <td><strong>${{Math.round(d.total_unidades).toLocaleString('es-CO')}}</strong></td>
        <td><div style="display:flex;align-items:center;gap:5px">
          <div class="bar-t" style="width:80px"><div class="bar-f" style="width:${{pct}}%;background:${{col}}"></div></div>
          <span>${{pct}}%</span></div></td></tr>`;
    }}).join('')}}</tbody>`;
}}

function renderIPdv(co){{
  const ID=ALLMONTHS[curMes].inventario||{{}};
  const d=ID[co];if(!d)return;
  const col=COLORS[gd_pdv_idx(co)];
  document.getElementById('iBread').innerHTML=
    `<span class="bc-link" onclick="selectIPdv('all')">🏪 Todos</span>
     <span style="color:var(--border)">›</span><span class="bc-current">PDV ${{co}} – ${{d.name}}</span>`;

  // Bar top 15
  dc('iBarPdv');
  const top15=d.top_items.slice(0,15);
  charts.iBarPdv=new Chart(document.getElementById('iBarPdv'),{{
    type:'bar',
    data:{{labels:top15.map(t=>t.name.length>30?t.name.slice(0,28)+'…':t.name),
      datasets:[{{label:'Unidades',data:top15.map(t=>t.unidades),
        backgroundColor:col+'bb',borderColor:col,borderWidth:1.5,borderRadius:4}}]}},
    options:{{indexAxis:'y',plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:ctx=>` ${{Math.round(ctx.raw).toLocaleString('es-CO')}} uds`}}}}}},
      scales:{{x:{{ticks:{{color:'#8b90b0',callback:v=>Math.round(v/1000)>0?Math.round(v/1000)+'K':v}},grid:{{color:'rgba(46,50,72,.5)'}}}},
        y:{{ticks:{{color:'#8b90b0',font:{{size:10}}}},grid:{{color:'rgba(46,50,72,.3)'}}}}}}}}
  }});

  // Evolución del PDV a través de los meses
  dc('iLinePdv');
  const mesLabels=MESES.filter(m=>ALLMONTHS[m]?.inventario?.[co]);
  const uEvo=mesLabels.map(m=>ALLMONTHS[m].inventario[co]?.total_unidades||0);
  const skuEvo=mesLabels.map(m=>ALLMONTHS[m].inventario[co]?.total_skus||0);
  charts.iLinePdv=new Chart(document.getElementById('iLinePdv'),{{
    type:'line',
    data:{{labels:mesLabels,datasets:[
      {{label:'Unidades',data:uEvo,borderColor:col,backgroundColor:col+'22',fill:true,borderWidth:2.5,pointRadius:5,tension:.3,yAxisID:'y'}},
      {{label:'SKUs',data:skuEvo,borderColor:'#a78bfa',backgroundColor:'transparent',borderWidth:2,borderDash:[5,4],pointRadius:4,tension:.3,yAxisID:'y2'}}
    ]}},
    options:{{plugins:{{legend:{{position:'top',labels:{{color:'#8b90b0',font:{{size:11}}}}}},
      tooltip:{{callbacks:{{label:ctx=>ctx.datasetIndex===0?` ${{Math.round(ctx.raw).toLocaleString('es-CO')}} uds`:` ${{ctx.raw}} SKUs`}}}}}},
      scales:{{
        x:{{ticks:{{color:'#8b90b0'}},grid:{{color:'rgba(46,50,72,.3)'}}}},
        y:{{ticks:{{color:col,callback:v=>Math.round(v/1000)>0?Math.round(v/1000)+'K':v}},grid:{{color:'rgba(46,50,72,.4)'}},position:'left'}},
        y2:{{ticks:{{color:'#a78bfa'}},grid:{{display:false}},position:'right'}}
      }}}}
  }});

  // Tabla completa con búsqueda
  invAllItems=d.all_items;
  renderInvTable(invAllItems);
  document.getElementById('iSearch').value='';
}}

function renderInvTable(items){{
  const grand=items.reduce((s,i)=>s+i.unidades,0)||1;
  document.getElementById('iAllTable').innerHTML=`
    <thead><tr><th>#</th><th>Referencia</th><th>Descripción</th><th>U.M.</th><th>Existencia</th><th>% del PDV</th></tr></thead>
    <tbody>${{items.map((it,i)=>{{
      const pct=(it.unidades/grand*100).toFixed(2);
      const col=CAT_COLORS[i%10];
      return`<tr><td style="color:var(--text3)">${{i+1}}</td>
        <td style="font-family:'DM Mono',monospace;font-size:11px;color:var(--text2)">${{it.ref}}</td>
        <td><strong>${{it.name}}</strong></td>
        <td style="color:var(--text2);font-size:11px">${{it.um}}</td>
        <td style="font-variant-numeric:tabular-nums;font-weight:600">${{Math.round(it.unidades).toLocaleString('es-CO')}}</td>
        <td><div style="display:flex;align-items:center;gap:5px">
          <div class="bar-t" style="width:70px"><div class="bar-f" style="width:${{Math.min(parseFloat(pct)*5,100)}}%;background:${{col}}"></div></div>
          <span style="font-size:10px;color:var(--text2)">${{pct}}%</span></div></td></tr>`;
    }}).join('')}}</tbody>`;
}}

function filterInv(){{
  const q=document.getElementById('iSearch').value.toLowerCase().trim();
  if(!q){{renderInvTable(invAllItems);return;}}
  renderInvTable(invAllItems.filter(it=>it.name.toLowerCase().includes(q)||it.ref.includes(q)));
}}

// ══════════ ALERTAS ══════════
function initAlertas(){{
  const semHtml=PDV_ORDER.map((id,i)=>{{
    const np=(ND[id]?.total_devengo||0)/Math.max(VD[id]?.total||1,1)*100;
    const col=np<8?'var(--green)':np<12?'var(--yellow)':'var(--red)';
    const bg=np<8?'rgba(56,201,160,.1)':np<12?'rgba(247,208,79,.1)':'rgba(224,93,122,.1)';
    const icon=np<8?'✅':np<12?'⚠️':'🔴';
    return`<div style="background:${{bg}};border:1px solid ${{col}};border-radius:12px;padding:16px;text-align:center">
      <div style="font-size:22px;margin-bottom:6px">${{icon}}</div>
      <div style="font-size:11px;color:var(--text2);margin-bottom:4px">${{id}} ${{VD[id].name}}</div>
      <div style="font-size:24px;font-weight:800;color:${{col}}">${{np.toFixed(1)}}%</div>
      <div style="font-size:10px;color:var(--text2);margin-top:3px">nómina/ventas</div></div>`;
  }}).join('');
  document.getElementById('aSemaforo').innerHTML=semHtml;
  const groupAvgM=PDV_ORDER.reduce((s,id)=>s+(VD[id]?.avg_margin||0),0)/PDV_ORDER.length;
  const margenHtml=PDV_ORDER.map(id=>{{
    const m=VD[id]?.avg_margin||0;const diff=m-groupAvgM;
    const isRed=diff<-2,isYellow=diff>=-2&&diff<0;
    if(!isRed&&!isYellow)return'';
    const col=isRed?'var(--red)':'var(--yellow)';
    const bg=isRed?'rgba(224,93,122,.08)':'rgba(247,208,79,.08)';
    const border=isRed?'rgba(224,93,122,.4)':'rgba(247,208,79,.4)';
    const icon=isRed?'🔴':'⚠️';
    const lines99=(VD[id]?.categories||[]).filter(c=>c.has_anomaly)
      .map(c=>`<span style="background:rgba(168,85,247,.15);color:var(--purple);padding:2px 7px;border-radius:5px;font-size:10px;margin:2px">${{c.cat}}</span>`).join('');
    return`<div style="background:${{bg}};border:1px solid ${{border}};border-radius:10px;padding:14px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span style="font-size:16px">${{icon}}</span><strong style="color:${{col}}">${{id}} ${{VD[id].name}}</strong>
        <span style="color:var(--text2);font-size:12px">Margen: <strong style="color:${{col}}">${{m.toFixed(2)}}%</strong> (prom: ${{groupAvgM.toFixed(2)}}% | dif: ${{diff.toFixed(2)}}%)</span>
      </div>${{lines99?`<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:3px">${{lines99}}</div>`:''}}</div>`;
  }}).filter(Boolean).join('');
  document.getElementById('aMargen').innerHTML=margenHtml||`<div style="color:var(--green);padding:10px">✅ Todos los PDV tienen margen dentro del rango normal.</div>`;
  const cal=VD._meta?.cal||{{}};
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
      const diff=d.ventas-avgHabil;const pct=(diff/avgHabil*100).toFixed(1);
      const worst=PDV_ORDER.reduce((a,b)=>{{
        const va=(VD[a]?.daily||[]).find(x=>x.date===d.date)?.ventas||0;
        const vb=(VD[b]?.daily||[]).find(x=>x.date===d.date)?.ventas||0;
        return va<vb?a:b;
      }});
      const tipoBadge=d.tipo==='saturday'?'<span class="pill py" style="font-size:9px">Sáb</span>':'';
      return`<tr><td style="color:var(--red);font-weight:700">#${{i+1}}</td>
        <td><strong>${{d.date}}</strong></td><td>${{d.label}} ${{tipoBadge}}</td>
        <td style="color:var(--red)">${{fmtFull(d.ventas)}}</td>
        <td><span class="pill pr">${{pct}}%</span></td>
        <td><span style="color:${{COLORS[PDV_ORDER.indexOf(worst)]}}">${{worst}} ${{VD[worst].name}}</span></td></tr>`;
    }}).join('')}}</tbody>`;
  const veVals=PDV_ORDER.map(id=>(VD[id]?.total||0)/Math.max(ND[id]?.n_empleados||1,1));
  const veMedian=[...veVals].sort((a,b)=>a-b)[Math.floor(veVals.length/2)];
  const scored=PDV_ORDER.map((id,i)=>{{
    const m=VD[id]?.avg_margin||0;
    const np=(ND[id]?.total_devengo||0)/Math.max(VD[id]?.total||1,1)*100;
    const ve=veVals[i];
    const sm=m>=groupAvgM?1:m>=groupAvgM-2?0:-1;
    const sn=np<8?1:np<12?0:-1;
    const sv=ve>=veMedian?1:ve>=veMedian*0.85?0:-1;
    return{{id,score:sm+sn+sv,m,np,ve,sm,sn,sv}};
  }}).sort((a,b)=>b.score-a.score);
  function scorePill(s){{return s===1?'<span class="pill pg">+1</span>':s===0?'<span class="pill py"> 0</span>':'<span class="pill pr">−1</span>';}}
  function totalBadge(s){{const col=s>=2?'var(--green)':s>=0?'var(--yellow)':'var(--red)';const bg=s>=2?'rgba(56,201,160,.15)':s>=0?'rgba(247,208,79,.15)':'rgba(224,93,122,.15)';return`<span style="background:${{bg}};color:${{col}};padding:3px 10px;border-radius:8px;font-weight:800;font-size:13px">${{s>0?'+':''}}${{s}}</span>`;}}
  document.getElementById('aRanking').innerHTML=`
    <thead><tr><th>#</th><th>PDV</th><th>Score</th><th>Margen</th><th>% Nómina</th><th>Ventas/Emp</th></tr></thead>
    <tbody>${{scored.map((r,i)=>{{const col=COLORS[PDV_ORDER.indexOf(r.id)];
      return`<tr><td style="color:${{col}};font-weight:700">#${{i+1}}</td>
        <td><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${{col}};margin-right:6px"></span><strong>${{r.id}} ${{VD[r.id].name}}</strong></td>
        <td>${{totalBadge(r.score)}}</td><td>${{scorePill(r.sm)}} ${{r.m.toFixed(2)}}%</td>
        <td>${{scorePill(r.sn)}} ${{r.np.toFixed(2)}}%</td><td>${{scorePill(r.sv)}} ${{fmtFull(r.ve)}}</td></tr>`;
    }}).join('')}}</tbody>`;
}}

// ══════════ TAB + RENDER ══════════
function renderTab(t){{
  curVPdv='all';curNPdv='all';curCPdv='all';curIPdv='all';selCatIdx=null;
  document.getElementById('vAll').style.display='';document.getElementById('vPdv').style.display='none';document.getElementById('vBread').style.display='none';
  document.getElementById('nAll').style.display='';document.getElementById('nPdv').style.display='none';document.getElementById('nBread').style.display='none';
  document.getElementById('cAll').style.display='';document.getElementById('cPdv').style.display='none';document.getElementById('cBread').style.display='none';
  document.getElementById('iAll').style.display='';document.getElementById('iPdv').style.display='none';document.getElementById('iBread').style.display='none';
  if(t==='ventas'){{initVKpis();buildVNav();renderVAll();}}
  if(t==='nomina'){{initNKpis();buildNNav();renderNAll();}}
  if(t==='compras'){{initCKpis();buildCNav();renderCAll();}}
  if(t==='productividad')initProductividad();
  if(t==='inventario'){{initIKpis();buildINav();renderIAll();}}
  if(t==='alertas')initAlertas();
}}
function showTab(t){{
  curTab=t;
  document.querySelectorAll('.tab-btn').forEach((b,i)=>b.classList.toggle('active',['ventas','nomina','compras','productividad','inventario','alertas'][i]===t));
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
  renderTab(t);
}}

// ── BOOT
setMesData();
buildMesSel();
initVKpis();buildVNav();renderVAll();
initNKpis();buildNNav();
initCKpis();buildCNav();
initIKpis();buildINav();
</script>
</body>
</html>"""
    return html


if __name__ == '__main__':
    log.info('Cargando datos de todos los meses...')
    all_data = load_all_months()
    log.info('Construyendo HTML...')
    html = build_html(all_data)
    out = OUTPUT_DIR / 'Dashboard_2026.html'
    out.write_text(html, encoding='utf-8')
    log.info(f'✅ Dashboard multi-mes generado: {out}')
    for mes, d in all_data.items():
        v = sum(d['ventas'].get(co, {}).get('total', 0) for co in gd.PDV_NAMES)
        n = sum(d['nomina'].get(co, {}).get('total_devengo', 0) for co in gd.PDV_NAMES)
        log.info(f'   {mes}: Ventas=${v/1e9:.3f}B  Nómina=${n/1e6:.1f}M')
