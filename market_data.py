#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 全景分析 — 动态行情抓取 (market_data.py)

每次构建/推送前自动抓取最新行情，生成 market_data.json，
供 build_site.py 与 tools/wechat_push.py 动态注入，实现「动态抓取真正上线」：

  • 港股: 恒生指数 / 恒生科技指数 / 恒生中国企业指数
  • 美股: 标普 500 / 纳斯达克 / 道琼斯
  • 商品: 现货黄金 / WTI 原油 / 布伦特原油
  • 汇率: 美元兑离岸人民币 / 在岸人民币

抓取源（按优先级逐源回退）：
  1. Yahoo Finance chart API  (query1.finance.yahoo.com) — 指数/期货/汇率全覆盖
  2. Stooq CSV 行情            (stooq.com)               — 无需密钥，稳定

设计原则：
  • 单品失败不阻断 —— 失败项 last=null，页面与推送降级显示 "—"，并在 summary 中记录，
    保证每天 09:00 定时任务与推送永不因个别源故障而中断。
  • 纯标准库（urllib），GitHub Actions ubuntu-latest 开箱即用，无需 pip install。

用法:
  python3 market_data.py                      # 联网抓取 → market_data.json
  python3 market_data.py --demo               # 写入一组模拟行情（本地联调/演示）
  python3 market_data.py --offline            # 断网兜底：基于旧数据刷新时间戳
  python3 market_data.py --json out.json --timeout 10
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 行情清单: (key, 中文名, 单位, Yahoo 代码, Stooq 代码, 展示小数位)
# ---------------------------------------------------------------------------
SYMBOLS = [
    ('HSI',    '恒生指数',         '点',        '^HSI',   '^hsi',   2),
    ('HSTECH', '恒生科技指数',     '点',        '^HSTECH', None,    2),
    ('HSCE',   '恒生中国企业指数', '点',        '^HSCE',  '^hsc',   2),
    ('SPX',    '标普 500',         '点',        '^GSPC',  '^spx',   2),
    ('NDQ',    '纳斯达克',         '点',        '^IXIC',  '^ndq',   2),
    ('DJI',    '道琼斯',           '点',        '^DJI',   '^dji',   2),
    ('GOLD',   '现货黄金',         '美元/盎司', 'GC=F',   'xauusd', 2),
    ('WTI',    'WTI 原油',         '美元/桶',   'CL=F',   'cl.f',   2),
    ('BRENT',  '布伦特原油',       '美元/桶',   'BZ=F',   'br.f',   2),
    ('USDCNH', '美元/离岸人民币',  '',          'CNH=X',  'usdcnh', 4),
    ('USDCNY', '美元/在岸人民币',  '',          'CNY=X',  'usdcny', 4),
]

YAHOO_BASE = 'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d'
STOOQ_BASE = 'https://stooq.com/q/l/?s={sym}&f=sdc&h&e=csv'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')

# 演示数据: key -> (last, chg, pct, as_of) —— 与当前报告风格一致，便于本地联调
DEMO = {
    'HSI':    (25440.17, -212.65, -0.83, '2026-08-28'),
    'HSTECH': (4776.44,  -47.77,  -0.99, '2026-08-28'),
    'HSCE':   (9012.34,  -60.11,  -0.66, '2026-08-28'),
    'SPX':    (6120.45,   15.20,   0.25, '2026-08-28'),
    'NDQ':    (19980.12,  60.30,   0.30, '2026-08-28'),
    'DJI':    (41500.88, -120.44, -0.29, '2026-08-28'),
    'GOLD':   (4400.50,   25.10,   0.57, '2026-08-28'),
    'WTI':    (82.70,      0.90,   1.10, '2026-08-28'),
    'BRENT':  (89.05,      0.85,   0.96, '2026-08-28'),
    'USDCNH': (7.1820,    -0.0050, -0.07, '2026-08-28'),
    'USDCNY': (7.1750,    -0.0040, -0.06, '2026-08-28'),
}


def http_get(url, timeout=10):
    """GET 请求，带浏览器 UA，返回文本；失败抛异常由调用方兜底。"""
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': '*/*',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def fetch_yahoo(yahoo_sym, timeout=10):
    """Yahoo Finance chart API → (last, prev_close, as_of) 或 None。"""
    if not yahoo_sym:
        return None
    url = YAHOO_BASE.format(sym=urllib.parse.quote(yahoo_sym, safe=''))
    raw = http_get(url, timeout=timeout)
    data = json.loads(raw)
    result = (data.get('chart') or {}).get('result')
    if not result:
        return None
    meta = result[0].get('meta') or {}
    last = meta.get('regularMarketPrice')
    prev = meta.get('chartPreviousClose') or meta.get('previousClose')
    ts = meta.get('regularMarketTime')
    if ts is None:
        stamps = result[0].get('timestamp') or []
        ts = stamps[-1] if stamps else None
    as_of = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d') if ts else None
    if last is None:
        return None
    return (float(last), float(prev) if prev is not None else None, as_of)


def fetch_stooq(stooq_sym, timeout=10):
    """Stooq CSV 行情 → (last, prev_close, as_of) 或 None（stooq 只有收盘价，prev=None）。"""
    if not stooq_sym:
        return None
    url = STOOQ_BASE.format(sym=urllib.parse.quote(stooq_sym, safe=''))
    raw = http_get(url, timeout=timeout)
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if len(lines) < 2 or 'No data' in raw:
        return None
    # 首行可能是表头(Symbol,Date,Close)或直接数据；兼容两种
    row = None
    for ln in lines:
        if ln.lower().startswith('symbol'):
            continue
        row = ln.split(',')
        break
    if not row or len(row) < 3:
        return None
    try:
        last = float(row[2])
    except (ValueError, IndexError):
        return None
    as_of = row[1] if re.match(r'20\d{2}-\d{2}-\d{2}', row[1]) else None
    return (last, None, as_of)


def make_quote(key, name, unit, decimals, last, prev, as_of, source):
    """组装单条行情 dict；无 prev 时 chg/pct 为 None。"""
    chg = pct = None
    if last is not None and prev is not None and prev != 0:
        chg = round(last - prev, 4)
        pct = round((last - prev) / prev * 100, 2)
    return {
        'name': name,
        'unit': unit,
        'decimals': decimals,
        'last': last,
        'chg': chg,
        'pct': pct,
        'as_of': as_of,
        'source': source,
    }


def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 动态行情抓取')
    ap.add_argument('--json', default='market_data.json', help='输出 JSON 路径')
    ap.add_argument('--timeout', type=int, default=10, help='单次请求超时秒数')
    ap.add_argument('--demo', action='store_true', help='写入模拟行情（本地联调/演示）')
    ap.add_argument('--offline', action='store_true',
                    help='断网兜底：读取已有 JSON，仅刷新时间戳')
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    now_full = now.strftime('%Y-%m-%d %H:%M:%S UTC')
    fetch_date = now.strftime('%Y-%m-%d')

    if args.offline:
        # 基于旧数据刷新时间戳，页面仍可构建（行情显示旧值并标注 offline）
        try:
            with open(args.json, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {'quotes': {}}
        data.update({'generated_at': now_full, 'fetch_date': fetch_date, 'mode': 'offline'})
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'🌐 离线模式: 已基于旧数据刷新时间戳 → {args.json}')
        return

    quotes = {}
    failed = []

    if args.demo:
        for key, name, unit, _y, _s, dec in SYMBOLS:
            if key in DEMO:
                last, chg, _pct, as_of = DEMO[key]
                quotes[key] = make_quote(key, name, unit, dec, last, round(last - chg, 4), as_of, 'demo')
            else:
                quotes[key] = make_quote(key, name, unit, dec, None, None, None, None)
        mode = 'demo'
    else:
        mode = 'live'
        for key, name, unit, yahoo_sym, stooq_sym, dec in SYMBOLS:
            q = None
            src = None
            try:
                r = fetch_yahoo(yahoo_sym, args.timeout)
                if r:
                    last, prev, as_of = r
                    q = make_quote(key, name, unit, dec, last, prev, as_of, 'yahoo')
                    src = 'yahoo'
            except Exception as e:  # noqa: BLE001 - 单品失败不阻断
                print(f'  ⚠️ {name}: Yahoo 失败({e}); 尝试 Stooq…', file=sys.stderr)
            if q is None:
                try:
                    r = fetch_stooq(stooq_sym, args.timeout)
                    if r:
                        last, _prev, as_of = r
                        q = make_quote(key, name, unit, dec, last, None, as_of, 'stooq')
                        src = 'stooq'
                except Exception as e:  # noqa: BLE001
                    print(f'  ⚠️ {name}: Stooq 失败({e}); 降级为 "—"', file=sys.stderr)
            if q is None:
                q = make_quote(key, name, unit, dec, None, None, None, None)
                failed.append(name)
            else:
                print(f'  ✅ {name: <8} {src: <6} '
                      f'{q["last"]:,.{q["decimals"]}f}  {q["pct"]}%  ({q["as_of"]})')
            quotes[key] = q
            time.sleep(0.2)

    data = {
        'generated_at': now_full,
        'fetch_date': fetch_date,
        'mode': mode,
        'quotes': quotes,
        'summary': {
            'ok': len(SYMBOLS) - len(failed),
            'total': len(SYMBOLS),
            'failed': failed,
        },
        'notes': [
            '由 market_data.py 构建时自动抓取 (Yahoo Finance → Stooq 多源回退)',
            '单品抓取失败降级显示 "—"，不阻断构建与推送',
        ],
    }
    with open(args.json, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    failed_str = ", ".join(failed)
    print(f'📦 行情已写入 {args.json} '
          f'({data["summary"]["ok"]}/{data["summary"]["total"]} 成功'
          + (f', 失败: {failed_str}' if failed else '')
          + f' · 抓取日期 {fetch_date} · {now_full})')


if __name__ == '__main__':
    main()
