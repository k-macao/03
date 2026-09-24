#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字符配图：把 matplotlib 的 Axes 译成等宽字符，挂在微信推送里表达当次数据分析。

对照 Matplotlib 3.11（https://github.com/matplotlib/matplotlib ，plot types
https://matplotlib.org/stable/plot_types/index.html ）和 Quick start 里的
Figure 解剖：每张图有标题、轴刻度、柱端数值（bar_label）。不靠颜色区分序列
——微信里颜色会丢，字符本身要能读。

  Axes.barh / ordered bar     类别比较，按数值从大到小
  diverging bar               有正负的比较，零线居中（画廊常见配图）
  bar stacked                 构成：一条柱按占比堆叠，配图例
  axvline 阈值                决策线写在图注里（配对 |z|=1，做多 ±10 / +25）

柱身只用半角字符（# + - = .），避免方块字在中文字体里变成双宽、把比例画歪。
缺数据只留「不编柱」，不补 0、不回填历史点位。纯标准库。
"""
import html
import unicodedata

import quant_pair

BAR_W = 16
HALF = 8
LABEL_W = 12  # 显示列，汉字算 2

QUOTE_ORDER = (
    ('HSI', '恒指'), ('HSTECH', '恒科'), ('HSCE', '国企'),
    ('SPX', '标普'), ('NDQ', '纳指'), ('DJI', '道指'),
    ('GOLD', '黄金'), ('WTI', 'WTI'), ('BRENT', '布油'),
    ('USDCNH', '离岸'), ('USDCNY', '在岸'),
)

COMMUNITY_PARTS = (
    ('bull', '偏多', '#'),
    ('bear', '偏空', '='),
    ('neutral', '中性', '+'),
    ('mixed', '分歧', '.'),
)

DIR_FILL = {1: '#', -1: '=', 0: '.'}
DIR_WORD = {1: '利好', -1: '利空', 0: '中性'}


def _width(text):
    w = 0
    for ch in str(text):
        w += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return w


def _clip(text, width):
    out = []
    w = 0
    for ch in str(text or ''):
        cw = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if w + cw > width:
            break
        out.append(ch)
        w += cw
    return ''.join(out), w


def _pad(text, width):
    s, w = _clip(text, width)
    return s + ' ' * (width - w)


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _fmt(v, digits=2):
    return f'{v:+.{digits}f}'


def pos_bar(value, scale, width=BAR_W, fill='#'):
    """0 到 scale 的横向柱。刻度固定，不按当日最大值拉伸。"""
    if scale <= 0:
        return ' ' * width
    frac = max(0.0, min(float(scale), float(value))) / float(scale)
    n = int(round(frac * width))
    return fill * n + ' ' * (width - n)


def diverging_bar(value, limit, half=HALF):
    """零线居中。正值在 | 右侧用 +，负值在左侧用 -。"""
    limit = abs(float(limit)) or 1.0
    v = max(-limit, min(limit, float(value)))
    n = int(round(abs(v) / limit * half))
    if v > 0:
        left, right = ' ' * half, '+' * n + ' ' * (half - n)
    elif v < 0:
        left, right = ' ' * (half - n) + '-' * n, ' ' * half
    else:
        left, right = ' ' * half, ' ' * half
    return left + '|' + right


def stacked_bar(parts, width=24):
    """parts: [(glyph, count), ...]。最大余数法，保证格子数等于 width。"""
    total = sum(max(0, int(c)) for _, c in parts)
    if total <= 0 or width <= 0:
        return '', 0
    raw = [max(0, int(c)) / total * width for _, c in parts]
    cells = [int(x) for x in raw]
    remain = width - sum(cells)
    order = sorted(range(len(parts)), key=lambda i: (raw[i] - cells[i], -i), reverse=True)
    for i in order:
        if remain <= 0:
            break
        if parts[i][1] <= 0:
            continue
        cells[i] += 1
        remain -= 1
    # 余数若还在（全是 0 已在上面返回），按顺序补到有计数的格子上
    i = 0
    guard = 0
    while remain > 0 and guard < width * 2:
        if parts[i % len(parts)][1] > 0:
            cells[i % len(parts)] += 1
            remain -= 1
        i += 1
        guard += 1
    return ''.join(g * n for (g, _), n in zip(parts, cells)), total


def _rows_html(title, rows, note):
    """微信用表格装字符柱：标签、柱、数值分列，不靠中文等宽。"""
    body = [
        '<table class="char-fig" style="width:100%;border-collapse:collapse;margin:8px 0 0;'
        'background:#f4f7f4;border:1px solid #007a35;border-left:3px solid #000;">',
        '<caption style="text-align:left;font-weight:700;font-size:12px;color:#007a35;'
        'padding:8px 10px 2px;">◆ 字符配图 · ' + html.escape(title) + '</caption>',
    ]
    if not rows:
        body.append(
            '<tr><td style="padding:4px 10px 8px;font-size:11px;color:#141414;">'
            '（当次没有可画的数，本图不编柱，不回填历史点位）</td></tr>')
    else:
        for label, bar, value in rows:
            body.append(
                '<tr>'
                f'<td style="padding:1px 8px;font-size:11px;color:#141414;white-space:nowrap;">'
                f'{html.escape(str(label))}</td>'
                '<td style="padding:1px 0;font-family:Consolas,Menlo,\'Courier New\',monospace;'
                'font-size:12px;letter-spacing:0;white-space:pre;color:#000;">'
                f'{html.escape(bar)}</td>'
                '<td style="padding:1px 8px;font-size:11px;text-align:right;white-space:nowrap;'
                f'color:#141414;">{html.escape(str(value))}</td>'
                '</tr>')
    if note:
        body.append(
            '<tr><td colspan="3" style="padding:2px 10px 8px;font-size:10px;color:#7d838b;">'
            + html.escape(note) + '</td></tr>')
    body.append('</table>')
    return ''.join(body)


def _plain(title, rows, note):
    lines = ['◆ ' + title]
    if not rows:
        lines.append('（当次没有可画的数，本图不编柱，不回填历史点位）')
    for label, bar, value in rows:
        lines.append(f'{_pad(label, LABEL_W)} {bar}  {value}')
    if note:
        lines.append(note)
    return '\n'.join(lines)


def _quote_pcts(quotes):
    raw = quotes or {}
    if isinstance(raw, dict) and isinstance(raw.get('quotes'), dict):
        raw = raw['quotes']
    out = []
    if not isinstance(raw, dict):
        return out
    for key, short in QUOTE_ORDER:
        q = raw.get(key) or {}
        pct = _num(q.get('pct') if isinstance(q, dict) else None)
        if pct is None:
            continue
        out.append((short, pct))
    return out


def quotes_chart(quotes):
    """涨跌幅发散柱。只画有当次 pct 的标的。"""
    pts = _quote_pcts(quotes)
    title = '涨跌幅 diverging barh（零线居中）'
    if not pts:
        return _rows_html(title, [], 'matplotlib Axes.barh 的发散版。没有涨跌幅就不画柱。'), _plain(title, [], '')
    limit = max(1.0, max(abs(v) for _, v in pts))
    rows = [(name, diverging_bar(v, limit), f'{_fmt(v)}%') for name, v in pts]
    note = (f'满刻度 ±{limit:.2f}%。+ 在零线右侧，- 在左侧。'
            '缺涨跌幅的标的不补 0。对照 matplotlib 发散柱，数值标在柱端。')
    return _rows_html(title, rows, note), _plain(title, rows, note)


def forces_chart(scan):
    """力量分有序柱 + 做多合成分发散柱。刻度固定 0–100 / ±100。"""
    forces = (scan or {}).get('forces') or []
    title = '推动力量 ordered barh + 做多合成分'
    rows = []
    ranked = sorted(forces, key=lambda f: -(_num(f.get('score')) or 0))
    for f in ranked:
        score = _num(f.get('score'))
        if score is None:
            continue
        direction = f.get('direction') or 0
        fill = DIR_FILL.get(direction, '.')
        name = str(f.get('name') or '').split('（')[0].split('(')[0]
        rows.append((name, pos_bar(score, 100, fill=fill),
                     f'{score:.0f} {DIR_WORD.get(direction, "中性")}'))
    verdict = (scan or {}).get('verdict') or {}
    long_score = _num(verdict.get('long_score'))
    if long_score is not None and (rows or verdict):
        rows.append(('做多合成分', diverging_bar(long_score, 100, half=10),
                     f'{_fmt(long_score, 1)} {verdict.get("stance") or ""}'.strip()))
    note = ('力量分柱长按 0–100 固定刻度（#利好 =利空 .中性），不按当日最大值拉伸。'
            '做多合成分零线居中，阈值 −10 防御 / +10 轻仓试多 / +25 可做多。'
            '对照 matplotlib ordered bar 与发散柱。')
    if not rows:
        return _rows_html(title, [], note), _plain(title, [], note)
    return _rows_html(title, rows, note), _plain(title, rows, note)


def community_chart(counts):
    """社区研判构成：一条堆叠柱。家数来自当次汇总，不另算。"""
    counts = counts or {}
    parts = [(glyph, int(counts.get(key) or 0)) for key, _name, glyph in COMMUNITY_PARTS]
    title = '社区研判 stacked bar（构成）'
    total = sum(c for _, c in parts)
    if total <= 0:
        return _rows_html(title, [], '没有社区研判计数，不编构成。'), _plain(title, [], '')
    bar, _ = stacked_bar(parts, width=24)
    legend = '  '.join(f'{glyph}{name}{counts.get(key) or 0}'
                       for key, name, glyph in COMMUNITY_PARTS)
    rows = [('构成', bar, f'共 {total} 家'), ('图例', legend, '')]
    note = '一条柱即 100%（matplotlib bar stacked）。格子按家数占比分配，柱端是家数不是涨跌幅。'
    return _rows_html(title, rows, note), _plain(title, rows, note)


def pairs_chart(quotes):
    """每条配对策略的 z。只画两腿涨跌幅都在的组合。"""
    title = '配对 z diverging bar（|z|=1 为进场）'
    raw = quotes or {}
    if isinstance(raw, dict) and isinstance(raw.get('quotes'), dict):
        raw = raw['quotes']
    rows = []
    zs = []
    pending = []
    for s in quant_pair.STRATEGIES:
        rec = quant_pair.recommend('', raw, hint=s['id'])
        if rec.get('z') is None:
            continue
        pending.append(rec)
        zs.append(abs(rec['z']))
    if not pending:
        note = '两腿涨跌幅不齐时不计算 z，本图不编柱。'
        return _rows_html(title, [], note), _plain(title, [], note)
    limit = max(1.8, max(zs))
    for rec in sorted(pending, key=lambda r: -abs(r['z'])):
        rows.append((rec['strategy_name'].replace('配对', ''),
                     diverging_bar(rec['z'], limit),
                     f'z={_fmt(rec["z"])} {rec.get("stance") or ""}'.strip()))
    note = (f'满刻度 ±{limit:.2f}。|z|<1 观望，|z|≥1 进场，|z|≥1.8 标准仓。'
            'z 与正文里的 AI 量化同一公式，不另写口径。')
    return _rows_html(title, rows, note), _plain(title, rows, note)


def sentiment_chart(sd):
    """舆情温度柱、多空构成、标的净情感发散柱。不读取来源字段。"""
    title = '舆情因子 bar / stacked / diverging'
    sd = sd or {}
    m = sd.get('market') or {}
    rows = []
    temp = _num(m.get('sent_temp'))
    if temp is not None:
        rows.append(('舆情温度', pos_bar(temp, 100), f'{temp:.1f} / 100'))
    pos, neg = _num(m.get('pos_share')), _num(m.get('neg_share'))
    if pos is not None and neg is not None:
        rest = max(0.0, 100.0 - pos - neg)
        # 用百分数取整后再分配，避免把未标注的残差画成另一套口径
        parts = [('#', int(round(pos))), ('=', int(round(neg))), ('.', int(round(rest)))]
        bar, total = stacked_bar(parts, width=20)
        if total:
            rows.append(('多空构成', bar, f'正{pos:.0f} 负{neg:.0f}'))
    targets = ((sd.get('matches') or {}).get('targets') or [])[:6]
    signed = []
    for t in targets:
        v = _num(t.get('net_senti'))
        if v is None:
            continue
        signed.append((str(t.get('name') or '标的'), v))
    if signed:
        limit = max(0.5, max(abs(v) for _, v in signed))
        for name, v in signed:
            rows.append((name, diverging_bar(v, limit), _fmt(v)))
    series = [row for row in (sd.get('series') or []) if _num(row.get('value')) is not None]
    if len(series) >= 2:
        vals = [_num(row.get('value')) for row in series[-12:]]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        spark = ''.join('*' if (v - lo) / span >= 0.5 else '.' for v in vals)
        last = series[-1]
        rows.append(('情绪序列', spark, str(last.get('date') or '')[:10]))
    note = ('温度柱刻度 0–100，50 为中性。净情感零线居中。'
            '序列只画数值，不写来源。对照 matplotlib bar、stacked bar、plot。')
    return _rows_html(title, rows, note), _plain(title, rows, note)


def macro_counts_chart(macro):
    """各小节入库条数。文件不可用时不画，避免把「清空的旧快照」画成实测 0。"""
    title = '宏观快讯条数 barh'
    macro = macro or {}
    if not (macro.get('categories') or {}):
        return '', ''
    avail = macro.get('unavailable')
    if isinstance(avail, dict) and not avail.get('ok', True):
        return '', ''
    rows = []
    for key, blk in (macro.get('categories') or {}).items():
        label = str((blk or {}).get('label') or key).split('—')[0].split('（')[0].strip()
        n = len((blk or {}).get('items') or [])
        rows.append((label, n))
    if not rows:
        return '', ''
    scale = max(1, max(n for _, n in rows))
    drawn = [(name, pos_bar(n, scale), f'{n} 条') for name, n in rows]
    note = f'柱长按本图最多 {scale} 条缩放。0 条是窗口内没有，不是历史条数。'
    return _rows_html(title, drawn, note), _plain(title, drawn, note)


def _self_test():
    checks = []

    def ok(name, cond):
        checks.append((name, bool(cond)))
        print(('  ✅ ' if cond else '  ❌ ') + name)

    bar = diverging_bar(1.2, 1.6)
    mid = bar.index('|')
    ok('正值的 + 在零线右侧', '+' in bar[mid + 1:] and '-' not in bar[mid + 1:])
    neg = diverging_bar(-0.4, 1.6)
    mid = neg.index('|')
    ok('负值的 - 在零线左侧', '-' in neg[:mid] and '+' not in neg[:mid])
    zero = diverging_bar(0, 1.6)
    ok('零值不画柱', set(zero) <= set('| '))
    ok('正柱长度随数值增加', pos_bar(80, 100).count('#') > pos_bar(20, 100).count('#'))
    bar, total = stacked_bar([('#', 6), ('=', 3), ('+', 3), ('.', 2)], 24)
    ok('堆叠柱格子数等于宽度', len(bar) == 24 and total == 14)
    ok('堆叠柱保留四个序列', set('#=+.') <= set(bar) and ' ' not in bar)
    html_q, plain_q = quotes_chart({})
    ok('无行情不编柱', '不编柱' in html_q and '%' not in plain_q.split('不编柱')[-1])
    html_q, plain_q = quotes_chart({'HSI': {'pct': 1.2}, 'WTI': {'pct': -0.4}})
    ok('有行情才写出涨跌幅', '+1.20%' in plain_q and '-0.40%' in plain_q)
    ok('字符柱进了微信表格', '<table' in html_q and 'diverging barh' in html_q)
    html_c, plain_c = community_chart({'bull': 6, 'bear': 3, 'neutral': 3, 'mixed': 2})
    ok('社区构成写出家数', '共 14 家' in plain_c and '偏多6' in plain_c.replace(' ', ''))
    html_p, plain_p = pairs_chart({})
    ok('配对缺腿不编 z', '不编柱' in html_p and 'z=' not in plain_p)
    html_s, plain_s = sentiment_chart({})
    ok('舆情空图不写来源名', '不编柱' in html_s and '米筐' not in html_s and 'RQ_' not in html_s)
    failed = [n for n, c in checks if not c]
    if failed:
        raise SystemExit('自检失败: ' + '、'.join(failed))
    print(f'\n✅ char_charts 自检通过（{len(checks)} 项）')


if __name__ == '__main__':
    import sys
    if '--self-test' in sys.argv:
        _self_test()
    else:
        demo, _ = quotes_chart({'HSI': {'pct': 1.2}, 'HSTECH': {'pct': -0.8}, 'WTI': {'pct': 2.1}})
        print(demo)
