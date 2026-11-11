"""The financial report as an A4 PDF (ReportLab): branded header, summary, chart, income statement, sites,
months, sales by package, payback and every expense. build(report, tr) takes app._finance_report()'s dict."""
import io
import re
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

INK = colors.HexColor('#111827')
MUTED = colors.HexColor('#6B7280')
LINE = colors.HexColor('#E5E7EB')
SOFT = colors.HexColor('#F5F6F8')
GOOD = colors.HexColor('#15803D')
BAD = colors.HexColor('#B91C1C')
W, H = A4
M = 16 * mm                 # side margins
HEADER = 38 * mm            # the first page's band


def _money(v, sign=False):
    v = Decimal(str(v or 0))
    s = '{:,.0f}'.format(abs(v))
    return ('-' if v < 0 else ('+' if sign and v > 0 else '')) + s


def _styles(brand):
    base = dict(fontName='Helvetica', fontSize=9, leading=12, textColor=INK)
    st = lambda name, **kw: ParagraphStyle(name, **{**base, **kw})
    return {
        'p': st('p'), 'small': st('small', fontSize=7.5, leading=10, textColor=MUTED),
        'h': st('h', fontName='Helvetica-Bold', fontSize=11.5, leading=14, textColor=brand, spaceBefore=4, spaceAfter=0),
        'label': st('label', fontName='Helvetica-Bold', fontSize=7, leading=9, textColor=MUTED),
        'kpi': st('kpi', fontName='Helvetica-Bold', fontSize=15, leading=18),
        'cell': st('cell', fontSize=8.5, leading=10.5), 'cellr': st('cellr', fontSize=8.5, leading=10.5, alignment=TA_RIGHT),
        'cellb': st('cellb', fontName='Helvetica-Bold', fontSize=8.5, leading=10.5),
        'cellbr': st('cellbr', fontName='Helvetica-Bold', fontSize=8.5, leading=10.5, alignment=TA_RIGHT),
        'th': st('th', fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=MUTED),
        'thr': st('thr', fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=MUTED, alignment=TA_RIGHT),
    }


def _heading(text, S, brand):
    t = Table([[Paragraph(escape(text), S['h'])]], colWidths=[W - 2 * M])
    t.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), 0.8, brand), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 3), ('TOPPADDING', (0, 0), (-1, -1), 8)]))
    return t


def _grid(rows, widths, S, total=False, align_right_from=1, zebra=True):
    """A table with a header row; numbers right-aligned; an optional bold total row at the end."""
    data = []
    for i, row in enumerate(rows):
        cells = []
        for j, v in enumerate(row):
            if isinstance(v, Paragraph):
                cells.append(v)
                continue
            head, last = i == 0, total and i == len(rows) - 1
            right = j >= align_right_from
            style = S['thr' if right else 'th'] if head else (S['cellbr' if right else 'cellb'] if last else S['cellr' if right else 'cell'])
            cells.append(Paragraph(v if isinstance(v, str) and v.startswith('<') else escape(str(v)), style))
        data.append(cells)
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [('LINEBELOW', (0, 0), (-1, 0), 0.8, INK), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
             ('TOPPADDING', (0, 0), (-1, -1), 3.2), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.2),
             ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4)]
    if zebra:
        for i in range(1, len(data) - (1 if total else 0)):
            if i % 2 == 0:
                style.append(('BACKGROUND', (0, i), (-1, i), SOFT))
    if total:
        style += [('LINEABOVE', (0, -1), (-1, -1), 0.8, INK), ('LINEBELOW', (0, -1), (-1, -1), 0.8, INK)]
    t.setStyle(TableStyle(style))
    return t


def _colored(v, sign=False):
    v = Decimal(str(v or 0))
    color = '#15803D' if v > 0 else ('#B91C1C' if v < 0 else '#111827')
    return f'<font color="{color}">{_money(v, sign)}</font>'


def _kpis(rep, tr, S, brand):
    t, cmp_ = rep['totals'], rep['compare']
    cur = rep['currency']

    def change(key, good_up=True):
        c = cmp_.get(key)
        if c is None:
            return Paragraph(escape(tr('No earlier figures to compare')), S['small'])
        up = c > 0
        color = '#15803D' if (up == good_up and c) else ('#B91C1C' if c else '#6B7280')
        arrow = '+' if up else ''
        return Paragraph(f'<font color="{color}"><b>{arrow}{c}%</b></font> ' + escape(tr('vs the period before')), S['small'])

    net = t['net']
    boxes = [
        (tr('MONEY IN'), _money(t['sales']), GOOD, change('sales')),
        (tr('MONEY OUT'), _money(t['out']), BAD, change('out', good_up=False)),
        (tr('NET PROFIT') if net >= 0 else tr('NET LOSS'), _money(net), GOOD if net >= 0 else BAD, change('net')),
        (tr('PROFIT MARGIN'), f"{t['margin']}%" if t['margin'] is not None else '-', brand,
         Paragraph(escape(tr('of money in kept as profit')), S['small'])),
    ]
    cells = []
    for label, value, color, sub in boxes:
        unit = '' if label == tr('PROFIT MARGIN') else f'<font size="8" color="#6B7280"> {cur}</font>'
        cells.append([Paragraph(escape(label), S['label']), Spacer(1, 2),
                      Paragraph(f'<font color="{color.hexval().replace("0x", "#")}">{escape(value)}</font>{unit}', S['kpi']),
                      Spacer(1, 2), sub])
    gap = 3 * mm
    w = (W - 2 * M - 3 * gap) / 4
    row, widths = [], []
    for i, c in enumerate(cells):
        row.append(c); widths.append(w)
        if i < 3:
            row.append(''); widths.append(gap)
    tbl = Table([row], colWidths=widths)
    style = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
             ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 6)]
    for i, (_, _, color, _) in enumerate(boxes):
        style += [('BACKGROUND', (i * 2, 0), (i * 2, 0), SOFT), ('LINEBEFORE', (i * 2, 0), (i * 2, 0), 2.5, color)]
    tbl.setStyle(TableStyle(style))
    return tbl


def _chart(rep, tr):
    rows = rep['shown'][-18:]                     # at most a year and a half, so the bars stay readable
    width, height = W - 2 * M, 58 * mm
    d = Drawing(width, height)
    c = VerticalBarChart()
    c.x, c.y, c.width, c.height = 38, 30, width - 48, height - 50
    c.data = [[float(r['sales']) for r in rows], [float(r['out']) for r in rows]]
    c.categoryAxis.categoryNames = [r['month'][5:] + '/' + r['month'][2:4] for r in rows]
    c.categoryAxis.labels.fontName, c.categoryAxis.labels.fontSize = 'Helvetica', 7
    c.categoryAxis.labels.fillColor = MUTED
    c.categoryAxis.strokeColor = LINE
    top = max([1.0] + c.data[0] + c.data[1])
    c.valueAxis.valueMin, c.valueAxis.valueMax = 0, top * 1.12
    c.valueAxis.labels.fontName, c.valueAxis.labels.fontSize, c.valueAxis.labels.fillColor = 'Helvetica', 7, MUTED
    c.valueAxis.labelTextFormat = lambda v: ('{:,.0f}k'.format(v / 1000) if top >= 10000 else '{:,.0f}'.format(v))
    c.valueAxis.strokeColor = colors.white
    c.valueAxis.visibleGrid, c.valueAxis.gridStrokeColor, c.valueAxis.gridStrokeWidth = True, LINE, 0.5
    c.bars[0].fillColor, c.bars[1].fillColor = GOOD, BAD
    c.bars[0].strokeColor = c.bars[1].strokeColor = None
    c.barSpacing, c.groupSpacing = 1, 6 if len(rows) > 6 else 14
    d.add(c)
    for i, (label, color) in enumerate(((tr('Money in'), GOOD), (tr('Money out'), BAD))):
        x = width - 150 + i * 75
        d.add(Rect(x, height - 10, 8, 8, fillColor=color, strokeColor=None))
        d.add(String(x + 12, height - 9, label, fontName='Helvetica', fontSize=7.5, fillColor=INK))
    d.add(String(0, height - 9, tr('Money in and out by month ({currency})', currency=rep['currency']),
                 fontName='Helvetica-Bold', fontSize=8.5, fillColor=INK))
    return d


def _statement(rep, tr, S, brand, width):
    t = rep['totals']
    cur = rep['currency']
    R = lambda text, amount, kind='row': (text, amount, kind)
    lines = [R(tr('INCOME'), None, 'section'),
             R(tr('Mobile-money sales'), t['online']), R(tr('Cash vouchers'), t['cash']),
             R(tr('Total income'), t['sales'], 'total'),
             R(tr('EXPENSES'), None, 'section')]
    for name, amount in rep['by_cat']:
        lines.append(R(name, amount))
    if t['fees']:
        lines.append(R(tr('SafeNet payment fees'), t['fees']))
    if t['sms']:
        lines.append(R(tr('SMS to customers'), t['sms']))
    if t['plan']:
        lines.append(R(tr('SafeNet plan'), t['plan']))
    if not rep['by_cat'] and not t['safenet']:
        lines.append(R(tr('No expenses recorded'), Decimal(0)))
    lines.append(R(tr('Total expenses'), t['out'], 'total'))
    lines.append(R(tr('NET PROFIT') if t['net'] >= 0 else tr('NET LOSS'), t['net'], 'net'))
    data, style = [], [('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                       ('TOPPADDING', (0, 0), (-1, -1), 2.6), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.6),
                       ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]
    data.append([Paragraph(escape(tr('Income statement')), S['cellb']), Paragraph(escape(cur), S['thr'])])
    style.append(('LINEBELOW', (0, 0), (-1, 0), 0.8, INK))
    for text, amount, kind in lines:
        i = len(data)
        if kind == 'section':
            data.append([Paragraph(f'<font color="{brand.hexval().replace("0x", "#")}"><b>{escape(text)}</b></font>', S['cell']), ''])
            style.append(('TOPPADDING', (0, i), (-1, i), 7))
        elif kind == 'total':
            data.append([Paragraph(escape(text), S['cellb']), Paragraph(_money(amount), S['cellbr'])])
            style.append(('LINEABOVE', (0, i), (-1, i), 0.6, INK))
        elif kind == 'net':
            color = GOOD if amount >= 0 else BAD
            big = ParagraphStyle('net', parent=S['cellb'], fontSize=10.5, leading=13, textColor=colors.white)
            data.append([Paragraph(escape(text), big), Paragraph(_money(amount), ParagraphStyle('netr', parent=big, alignment=TA_RIGHT))])
            style += [('BACKGROUND', (0, i), (-1, i), color), ('TOPPADDING', (0, i), (-1, i), 6), ('BOTTOMPADDING', (0, i), (-1, i), 6)]
        else:
            data.append([Paragraph('&nbsp;&nbsp;&nbsp;' + escape(text), S['cell']), Paragraph(_money(amount), S['cellr'])])
    tbl = Table(data, colWidths=[width - 30 * mm, 30 * mm])
    style.append(('SPAN', (0, 0), (0, 0)))
    tbl.setStyle(TableStyle(style))
    return tbl


def _side(rep, tr, S, brand, width):
    """Payback (all time) and the period before, beside the income statement."""
    pb, prev, cur = rep['payback'], rep['prev'], rep['currency']
    out = []
    box = lambda flow: Table([[flow]], colWidths=[width], style=TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), SOFT), ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    inner = [Paragraph(escape(tr('INVESTMENT AND PAYBACK')), S['label']), Spacer(1, 3)]
    if pb['out'] or pb['in']:
        pct = max(0, min(100, pb['percent']))
        bar_w = width - 16
        bar = Drawing(bar_w, 9)
        bar.add(Rect(0, 0, bar_w, 7, fillColor=LINE, strokeColor=None, rx=3, ry=3))
        if pct:
            bar.add(Rect(0, 0, bar_w * pct / 100, 7, fillColor=GOOD if pct >= 100 else brand, strokeColor=None, rx=3, ry=3))
        inner += [Paragraph(f'<font size="15"><b>{pct}%</b></font> ' + escape(tr('paid back (all time)')), S['p']), Spacer(1, 4), bar, Spacer(1, 5)]
        kv = [(tr('Invested (your expenses)'), pb['invested']), (tr('All money out'), pb['out']), (tr('All money in'), pb['in']),
              (tr('Profit so far') if pb['net'] >= 0 else tr('Still to earn back'), abs(pb['net']))]
        t = Table([[Paragraph(escape(k), S['cell']), Paragraph(_money(v), S['cellr'])] for k, v in kv],
                  colWidths=[width - 16 - 22 * mm, 22 * mm])
        t.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                               ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
                               ('LINEABOVE', (0, -1), (-1, -1), 0.5, MUTED)]))
        inner.append(t)
        if pb['net'] >= 0 and pb.get('month'):
            inner += [Spacer(1, 4), Paragraph(escape(tr('Paid back in {month}.', month=pb['month'])), S['small'])]
        elif pb.get('months_left'):
            inner += [Spacer(1, 4), Paragraph(escape(tr('At the last three months\' pace, about {n} more months.', n=pb['months_left'])), S['small'])]
    else:
        inner.append(Paragraph(escape(tr('No money in or out yet.')), S['small']))
    out.append(box(inner))
    if not rep['has_prev']:
        return out
    out.append(Spacer(1, 4 * mm))
    n = len(rep['rows'])
    inner = [Paragraph(escape(tr('THE {n} MONTHS BEFORE', n=n) if n > 1 else tr('THE MONTH BEFORE')), S['label']), Spacer(1, 3)]
    t = Table([[Paragraph(escape(k), S['cell']), Paragraph(_money(v), S['cellr'])] for k, v in
               ((tr('Money in'), prev['sales']), (tr('Money out'), prev['out']), (tr('Net'), prev['net']))],
              colWidths=[width - 16 - 22 * mm, 22 * mm])
    t.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                           ('TOPPADDING', (0, 0), (-1, -1), 1.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5)]))
    inner.append(t)
    out.append(box(inner))
    return out


class _Numbered(rl_canvas.Canvas):
    """Draws 'Page x of y' once the page count is known."""
    def __init__(self, *a, **kw):
        self._footer = kw.pop('footer')
        super().__init__(*a, **kw)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for state in self._pages:
            self.__dict__.update(state)
            self._footer(self, len(self._pages))
            super().showPage()
        super().save()


def build(rep, tr, logo=None, color='#051D60'):
    brand = colors.HexColor(color if re.fullmatch(r'#[0-9a-fA-F]{6}', color or '') else '#051D60')
    S = _styles(brand)
    buf = io.BytesIO()
    title = tr('Financial report')
    image = None
    if logo:
        try:
            image = ImageReader(io.BytesIO(logo))
        except Exception:
            image = None
    subtitle = ' · '.join(x for x in (rep['site_name'], rep['title']) if x)

    def first(c, doc):
        c.saveState()
        c.setFillColor(brand)
        c.rect(0, H - HEADER, W, HEADER, stroke=0, fill=1)
        x = M
        if image:
            size = 20 * mm
            c.setFillColor(colors.white)
            c.roundRect(M, H - HEADER + (HEADER - size) / 2, size, size, 3 * mm, stroke=0, fill=1)
            try:
                c.drawImage(image, M + 2 * mm, H - HEADER + (HEADER - size) / 2 + 2 * mm, size - 4 * mm, size - 4 * mm,
                            preserveAspectRatio=True, anchor='c', mask='auto')
            except Exception:
                pass
            x = M + size + 5 * mm
        c.setFillColor(colors.white)
        c.setFont('Helvetica', 8.5)
        c.drawString(x, H - 14 * mm, title.upper())
        c.setFont('Helvetica-Bold', 19)
        c.drawString(x, H - 22.5 * mm, rep['business'][:42])
        c.setFont('Helvetica', 10)
        c.drawString(x, H - 29 * mm, subtitle[:80])
        c.setFont('Helvetica', 7.5)
        c.drawRightString(W - M, H - 14 * mm, tr('Prepared {date}', date=rep['generated']))
        if rep.get('by'):
            c.drawRightString(W - M, H - 18 * mm, tr('by {name}', name=rep['by']))
        c.drawRightString(W - M, H - 22 * mm, tr('Amounts in {currency}', currency=rep['currency']))
        c.restoreState()

    def later(c, doc):
        c.saveState()
        c.setFillColor(brand)
        c.rect(0, H - 5, W, 5, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(M, H - 12 * mm, f"{rep['business']} — {title}")
        c.setFont('Helvetica', 8)
        c.drawRightString(W - M, H - 12 * mm, subtitle)
        c.setStrokeColor(LINE)
        c.line(M, H - 14 * mm, W - M, H - 14 * mm)
        c.restoreState()

    def footer(c, pages):
        c.saveState()
        c.setStrokeColor(LINE)
        c.line(M, 13 * mm, W - M, 13 * mm)
        c.setFont('Helvetica', 7.5)
        c.setFillColor(MUTED)
        c.drawString(M, 9 * mm, tr('{business} · financial report · made with SafeNet', business=rep['business']))
        c.drawRightString(W - M, 9 * mm, tr('Page {page} of {pages}', page=c.getPageNumber(), pages=pages))
        c.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4, title=f"{title} — {rep['business']} — {rep['title']}", author=rep['business'],
                          creator='SafeNet', leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=18 * mm)
    fw = W - 2 * M
    doc.addPageTemplates([
        PageTemplate('first', [Frame(M, 18 * mm, fw, H - HEADER - 24 * mm, id='f1', leftPadding=0, rightPadding=0,
                                     topPadding=0, bottomPadding=0)], onPage=first, autoNextPageTemplate='later'),
        PageTemplate('later', [Frame(M, 18 * mm, fw, H - 36 * mm, id='f2', leftPadding=0, rightPadding=0,
                                     topPadding=0, bottomPadding=0)], onPage=later)])
    story = [_kpis(rep, tr, S, brand), Spacer(1, 6 * mm)]
    if len(rep['shown']) > 1:
        story += [_chart(rep, tr), Spacer(1, 4 * mm)]
    left, gap = fw * 0.58, 6 * mm
    right = fw - left - gap
    two = Table([[_statement(rep, tr, S, brand, left), '', _side(rep, tr, S, brand, right)]], colWidths=[left, gap, right])
    two.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                             ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0)]))
    story += [two]
    cur = rep['currency']

    if rep['sites']:
        rows = [[tr('Site'), tr('Money in'), tr('Money out'), tr('Net'), tr('Margin')]]
        for s in rep['sites']:
            rows.append([s['name'], _money(s['sales']), _money(s['out']), _colored(s['net']),
                         f"{s['margin']}%" if s['margin'] is not None else '-'])
        t = rep['totals']
        rows.append([tr('Total'), _money(t['sales']), _money(t['out']), _colored(t['net']), f"{t['margin']}%" if t['margin'] is not None else '-'])
        story += [CondPageBreak(40 * mm), _heading(tr('Sites compared'), S, brand), Spacer(1, 2 * mm),
                  _grid(rows, [fw * 0.36] + [fw * 0.16] * 4, S, total=True)]

    if len(rep['shown']) > 1:
        rows = [[tr('Month'), tr('Mobile money'), tr('Cash'), tr('Money in'), tr('Expenses'), tr('SafeNet'), tr('Net'), tr('Running total')]]
        for r in rep['shown']:
            rows.append([r['label'], _money(r['online']), _money(r['cash']), _money(r['sales']), _money(r['spent']),
                         _money(r['safenet']), _colored(r['net']), _colored(r['running'])])
        t = rep['totals']
        rows.append([tr('Total'), _money(t['online']), _money(t['cash']), _money(t['sales']), _money(t['spent']),
                     _money(t['safenet']), _colored(t['net']), ''])
        story += [CondPageBreak(45 * mm), _heading(tr('Month by month ({currency})', currency=cur), S, brand), Spacer(1, 2 * mm),
                  _grid(rows, [fw * 0.19] + [fw * 0.1157] * 7, S, total=True)]

    if rep['packages']:
        total = sum((p[2] for p in rep['packages']), Decimal(0)) or Decimal(1)
        rows = [[tr('What was sold'), tr('Sold'), tr('Amount ({currency})', currency=cur), tr('Share')]]
        for name, count, amount in rep['packages']:
            rows.append([name, f'{count:,}', _money(amount), f'{amount * 100 / total:.0f}%'])
        rows.append([tr('Total'), f"{sum(p[1] for p in rep['packages']):,}", _money(sum(p[2] for p in rep['packages'])), '100%'])
        story += [CondPageBreak(40 * mm), _heading(tr('Sales by package'), S, brand), Spacer(1, 2 * mm),
                  _grid(rows, [fw * 0.52, fw * 0.14, fw * 0.2, fw * 0.14], S, total=True)]

    all_sites = rep['all_sites']
    rows = [[tr('Date'), tr('What'), tr('Category')] + ([tr('Site')] if all_sites else []) + [tr('Amount ({currency})', currency=cur)]]
    for e in rep['items']:
        what = escape(e.description) + (f'<br/><font size="7" color="#6B7280">{escape(tr("to {name}", name=e.paid_to))}</font>' if e.paid_to else '')
        rows.append([e.spent_on.strftime('%d %b %Y'), Paragraph(what, S['cell']), rep['categories'].get(e.category, e.category)]
                    + ([e.site.name if e.site else tr('Whole business')] if all_sites else []) + [_money(e.amount)])
    if rep['items']:
        rows.append([tr('Total'), '', ''] + ([''] if all_sites else []) + [_money(sum((Decimal(str(e.amount)) for e in rep['items']), Decimal(0)))])
        widths = [fw * 0.14, fw * 0.36, fw * 0.2, fw * 0.15, fw * 0.15] if all_sites else [fw * 0.15, fw * 0.45, fw * 0.23, fw * 0.17]
        story += [CondPageBreak(40 * mm), _heading(tr('Expense details'), S, brand), Spacer(1, 2 * mm),
                  _grid(rows, widths, S, total=True, align_right_from=len(widths) - 1)]

    story += [Spacer(1, 4 * mm), KeepTogether([
        Paragraph(escape(tr('How these figures are counted')), S['label']), Spacer(1, 2),
        Paragraph(escape(tr('Money in is what customers paid: mobile-money payments when they were paid, and cash vouchers when they were first used. '
                            'Money out is the expenses recorded in SafeNet plus what SafeNet charged (payment fees, SMS and the SafeNet plan). '
                            'Payback counts everything from the first month.')), S['small'])])]
    doc.build(story, canvasmaker=lambda *a, **kw: _Numbered(*a, footer=footer, **kw))
    return buf.getvalue()
