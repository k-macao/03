#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_data.parse_yahoo_chart 单元测试（离线 · 使用真实 API 抓取报文）

背景（2026-09-16 修复）:
  Yahoo chart API range=5d 时 meta.chartPreviousClose 是「5 日窗口前收」
  （约 5 个交易日前收盘），不能当作「前一交易日收盘」计算当日涨跌。
  2026-09-16 实例: 恒指收 24,713.78，chartPreviousClose=25,274.96（9/9 收盘），
  误算 −561.18/−2.22%；真实当日 +46.54/+0.19%（前收 24,667.24，etnet/富途多源印证）。
"""
import unittest

from market_data import parse_yahoo_chart, make_quote

# ---- 真实报文（2026-09-16 11:10 UTC 抓自 query1.finance.yahoo.com, 仅保留解析所需字段）----

HSI_5D = {
    'chart': {'result': [{
        'meta': {
            'regularMarketTime': 1789546148,          # 2026-09-16 16:09 HKT（收盘后）
            'regularMarketPrice': 24713.78,
            'fulldayChange': 46.539,                  # Yahoo 官方当日涨跌额
            'regularMarketChangePercent': 0.189,
            'chartPreviousClose': 25274.96,           # ⚠️ 9/9 收盘（窗口前收），非昨收
        },
        'timestamp': [1789003800, 1789090200, 1789349400, 1789435800, 1789522200],
        'indicators': {'quote': [{'close': [24954.470703125, 24805.630859375,
                                            24917.599609375, 24667.240234375,
                                            24713.779296875]}]},
    }], 'error': None},
}

GSPC_5D = {
    'chart': {'result': [{
        'meta': {
            'regularMarketTime': 1789505608,          # 2026-09-15 收盘
            'regularMarketPrice': 7585.73,
            'fulldayChange': -34.25,
            'regularMarketChangePercent': -0.449,
            'chartPreviousClose': 7673.52,            # 9/8 收盘（窗口前收）
        },
        'timestamp': [1788960600, 1789047000, 1789133400, 1789392600, 1789479000],
        'indicators': {'quote': [{'close': [7636.35986328125, 7591.7001953125,
                                            7656.97998046875, 7619.97998046875,
                                            7585.72998046875]}]},
    }], 'error': None},
}


def _legacy(meta_overrides, closes):
    """构造无 fulldayChange 的旧式报文。"""
    result = {
        'meta': dict({'regularMarketPrice': closes[-1],
                      'regularMarketTime': 1789522200}, **meta_overrides),
        'timestamp': list(range(len(closes))),
        'indicators': {'quote': [{'close': list(closes)}]},
    }
    return {'chart': {'result': [result], 'error': None}}


class TestParseYahooChart(unittest.TestCase):

    def test_hsi_daily_change_not_5day(self):
        """恒指: prev 应为 9/15 收盘 24,667.24 → +46.54/+0.19%（而非 −561.18/−2.22%）。"""
        r = parse_yahoo_chart(HSI_5D)
        self.assertIsNotNone(r)
        last, prev, as_of = r
        self.assertAlmostEqual(last, 24713.78, places=2)
        self.assertAlmostEqual(prev, 24667.24, places=2)   # 非 25274.96（5 日窗口前收）
        self.assertEqual(as_of, '2026-09-16')
        q = make_quote('HSI', '恒生指数', '点', 2, last, prev, as_of, 'yahoo')
        self.assertAlmostEqual(q['chg'], 46.54, places=2)
        self.assertAlmostEqual(q['pct'], 0.19, places=2)   # Yahoo 官方 +0.189%
        self.assertLess(q['pct'], 0.2)                     # 不是 5 日累计 −2.22%

    def test_gspc_daily_change(self):
        """标普 500: 9/15 当日 −34.25/−0.45%（而非窗口前收算出的 −87.79/−1.14%）。"""
        r = parse_yahoo_chart(GSPC_5D)
        last, prev, as_of = r
        self.assertAlmostEqual(prev, 7619.98, places=2)
        self.assertEqual(as_of, '2026-09-15')
        q = make_quote('SPX', '标普 500', '点', 2, last, prev, as_of, 'yahoo')
        self.assertAlmostEqual(q['chg'], -34.25, places=2)
        self.assertAlmostEqual(q['pct'], -0.45, places=2)

    def test_fallback_closes_array(self):
        """无 fulldayChange 时回退日线 closes[-2]。"""
        payload = _legacy({'chartPreviousClose': 9999.0},
                          [25000.0, 24800.0, 24667.24, 24713.78])
        last, prev, _ = parse_yahoo_chart(payload)
        self.assertAlmostEqual(last, 24713.78, places=2)
        self.assertAlmostEqual(prev, 24667.24, places=2)   # 用 closes[-2], 非 9999

    def test_fallback_meta_prev_last_resort(self):
        """单根 K 线且无 fulldayChange → 兜底 meta.previousClose/chartPreviousClose。"""
        payload = _legacy({'chartPreviousClose': 25274.96}, [24713.78])
        _last, prev, _ = parse_yahoo_chart(payload)
        self.assertAlmostEqual(prev, 25274.96, places=2)

    def test_none_inputs(self):
        self.assertIsNone(parse_yahoo_chart(None))
        self.assertIsNone(parse_yahoo_chart({}))
        self.assertIsNone(parse_yahoo_chart({'chart': {'result': [], 'error': None}}))


if __name__ == '__main__':
    unittest.main()
