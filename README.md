# 03 — 章鱼 AI 全景分析

自动生成的分析报告站点:<https://k-macao.github.io/03/>

## 结构

| 文件 | 说明 |
|---|---|
| `report.html` | 报告源文件(歸藏风格 · 靛蓝瓷配色 + Swiss / Editorial 排版),内含"手动推送"按钮及内嵌的微信版全文(`<script id="wechat-parts">`) |
| `tools/wechat_push.py` | 微信推送工具:把 `report.html` 转为微信兼容的内联样式 HTML,经 PushPlus 推送到微信 |
| `.github/workflows/m.yml` | CI:部署 Pages(g.github/workflow 由人工维护) |

## 微信推送(PushPlus)

- **页面按钮**:打开 Pages 站点点"手动推送",即把**完整报告**逐条推送到微信
  (内容已内嵌在页面里,超 2 万字自动按章节拆条,条间间隔 15s 符合接口频率限制)。
- **命令行**:`python3 tools/wechat_push.py --push`
- **验证转换效果**:`python3 tools/wechat_push.py --dry-run`
- 报告 `report.html` 更新后,跑一次 `python3 tools/wechat_push.py --embed`
  重新生成内嵌内容(幂等)。

Token 维护在 `report.html` 的 `PUSHPLUS_TOKEN` 常量中,网页按钮与本工具共用,更换只需改这一处。

**一对多群组推送**:群组编码维护在 `report.html` 的 `PUSHPLUS_TOPIC` 常量中(当前 `oai.1`,
群内成员都会收到推送);命令行可用 `--topic` 或环境变量 `PUSHPLUS_TOPIC` 覆盖。
把常量留空 `''` 即退回一对一推送(token 本人)。

## 可选:每次合并 main 自动推送微信

工作流文件需账号所有者手动维护(机器人 token 无 workflow 修改权限)。
在 `.github/workflows/m.yml` 的部署步骤之后追加:

```yaml
      - name: 📲 推送报告到微信 (PushPlus)
        if: ${{ github.event_name == 'push' }}
        run: python3 tools/wechat_push.py --push
```

如需随部署刷新 `wechat.json`(按钮的备用数据源),另加:

```yaml
      - name: 🧩 生成微信推送内容 (wechat.json)
        run: python3 tools/wechat_push.py --emit _site/wechat.json
```

> 群组编码无需改动工作流:Actions 推送会自动读取 `report.html` 的 `PUSHPLUS_TOPIC`(当前 `oai.1`)。
> 仅当想用 Secrets 覆盖时,才需所有者在工作流 env 手动加一行 `PUSHPLUS_TOPIC: ${{ secrets.PUSHPLUS_TOPIC }}`。
