# 开发、测试与联调指南

## 自动化测试

运行后端与静态前端全部单元测试（缺少可选依赖时相关用例会自动跳过）：

```bash
python -m pytest -q
```

校验核心前端 ES 模块语法：

```bash
node --check webapp/static/app.js
node --check webapp/static/i18n.js
node --check webapp/static/screen-touch.js
node --check webapp/static/preset-wizard.js
node --check webapp/static/preset-team.js
node --check webapp/static/preset-assist.js
node --check webapp/static/preset-equips.js
node --check webapp/static/preset-settlement.js
node --check webapp/static/preset-drops.js
```

## 浏览器回归测试（可选）

浏览器回归测试基于隔离的临时数据目录与模拟设备运行。安装 Playwright 并指定本机 Chromium / Chrome 路径后执行：

```bash
python -m pip install playwright
BBCHANNEL_TEST_CHROMIUM=/path/to/chromium python -m pytest -q tests/test_*_browser.py
```

## 手动实机 Smoke 联调清单

在安装 `requirements.txt` 并执行 `python -m webapp` 后，按以下顺序快速核验：

1. 打开 `http://127.0.0.1:8000`，确认界面加载正常且 `/api/health` 返回 `{"ok": true}`。
2. 确认设备能力列表正确加载 ADB / MuMu 状态，并连接一台在线模拟器或真机。
3. 执行截屏与实时预览（Live），测试点击、长按与拖动触控、模板匹配，检查底部事件日志流。
4. 通过「简易向导」或「专业模式」新建/编辑脚本，确认校验结果与编译后执行计划无报错。
5. 先在目标助战界面单次试跑 1 把并观察日志与画面，确认选助战、技能轴和结算全部正常后，再开启多把或清体运行。
