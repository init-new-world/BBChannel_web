# 项目结构与架构设计

BBchannel Web 是 BBchannel 自动化能力栈的本地 Web 控制台，后端基于 FastAPI + Uvicorn + OpenCV/NumPy，前端采用原生模块化 ES Modules（零构建依赖）。

## 目录结构

```text
web/
├── webapp/
│   ├── __main__.py          # CLI 入口（python -m webapp，默认监听 127.0.0.1:8000）
│   ├── app.py               # FastAPI 应用工厂与 REST API 路由
│   ├── api/
│   │   ├── jobs.py          # 任务队列、状态查询、SSE 事件流与清理接口
│   │   └── ws.py            # WebSocket：/api/ws/events 与 /api/ws/screen
│   ├── core/
│   │   ├── errors.py        # 统一错误码与 AppError 响应结构
│   │   └── models.py        # 设备、操作结果等核心数据模型
│   ├── devices/
│   │   ├── base.py          # DeviceBackend 协议定义
│   │   ├── adb.py           # ADB 发现、持久 Shell、DroidCast 加速与触控原语
│   │   ├── mumu.py          # MuMu 原生 DLL / Windows Bridge IPC 后端
│   │   ├── replay.py        # 离线回放测试后端
│   │   └── coordinates.py   # 画面归一化（1280×720）与旋转/坐标双向映射
│   ├── runtime/
│   │   ├── database.py      # SQLite 持久化（WAL 模式，runtime/bbchannel.db）
│   │   ├── jobs.py          # 单设备互斥调度、取消/暂停检查点与事件发布
│   │   └── models.py        # Job / JobEvent 状态模型
│   ├── services/            # 无状态/轻状态业务与图像识别服务
│   │   ├── devices.py       # 设备会话管理、帧广播、操作延时与调试钩子
│   │   ├── recognition.py   # OpenCV 模板匹配（多尺度、ROI、遮罩、灰度/裁剪）
│   │   ├── resources.py     # assets/ 与 data/ 路径解析与分前缀模板索引
│   │   ├── script_data.py   # 脚本/策略校验、执行计划编译、预检报告与替补推算
│   │   ├── assist.py        # 助战头像、礼装、满破、技能等级与冠位三槽识别
│   │   ├── cards.py         # 指令卡识别、助战角标、克制/抵抗与封印检测
│   │   ├── team.py          # 编队校验与礼装背面等待
│   │   ├── drop_recognition.py / drop_templates.py
│   │   ├── equip_templates.py / assist_tags.py / command_tags.py
│   │   ├── lottery.py / chocolate.py / digdig.py / expball.py
│   │   └── materials.py / notebook.py / master_portraits.py / event_log.py
│   ├── automation/          # 状态机与具体任务编排（run / stage / entry / assist / battle / completion / recovery 等）
│   └── static/              # 前端控制台（index.html、styles.css、app.js、preset-wizard.js、screen-touch.js 等）
├── assets/                  # 模板与图像资源（从者头像、技能图标、礼装、UI 模板等）
├── data/                    # 脚本（settings/）、策略（strategy/）、从者/礼装/技能目录数据
├── bin/                     # 内置 ADB 工具与 Windows MuMu Bridge 脚本
├── runtime/                 # 运行期数据：bbchannel.db、debug/ 单步截图、replays/
├── tests/                   # pytest 单元测试与可选 Playwright 浏览器回归测试
└── wiki/                    # 技术设计文档
```

## 实时通信协议（WebSocket）

前端依赖 `wsproto` 与后端建立两条实时 WebSocket 通道：

1. **`WS /api/ws/events`**
   - 推送连接状态快照、实时系统事件日志、任务状态流转以及当前订阅任务的细粒度步骤事件（支持 `EventSource` 自动回退）。
   - 前端重连或收到初始快照时同步设备连接状态与任务列表。
2. **`WS /api/ws/screen`**
   - 推送二进制画面帧（支持 JPEG / PNG），用于在控制台实时预览设备屏幕。
   - **任务运行期间的被动推流（`follow_jobs=true`）**：优先复用任务执行过程中的截图零开销广播；当任务处于等待/动画间隔时，采用非阻塞 `preview_snapshot()` 补帧，不会阻塞任务主线程。
   - **实时触控上行消息**：支持 `tap`、`swipe`、`touch_down`、`touch_move`（服务端最新帧合并防堆积）、`touch_up`、`touch_cancel`，以及 `refresh` / `set_interval`。连接异常断开时服务端自动补发抬起/取消，防止模拟器“卡键”。

## 任务持久化与单步调试

- **数据库**：任务历史与事件记录保存在 `runtime/bbchannel.db`（SQLite WAL 模式），可通过环境变量 `BBCHANNEL_RUNTIME_DB` 指定自定义路径。
- **单步调试（Step Debug）**：
  - 在任务请求体中传入 `"debug_step": true`，或在控制台勾选 **Step debug**，或设置环境变量 `BBCHANNEL_DEBUG_STEP=1`。
  - 每次点击或滑动前任务会自动暂停，并将 `latest.json`、`steps.jsonl` 及带标注的 PNG 截图输出到 `runtime/debug/<job_id>/`。
  - 传入 `"debug_step": "log"` 时仅落盘调试包而不暂停。
- **界面国际化**：顶栏语言选择器支持简体中文与英文，偏好保存在浏览器 `localStorage`，默认跟随浏览器语言。脚本 JSON、设备 ID 与后端原始消息保持原样不翻译。

## 本地安全边界

默认服务仅绑定回环地址 `127.0.0.1`。设备控制与自动化接口面向本地信任环境设计，未内置公网鉴权，请勿直接暴露至不可信公网。资源目录（`assets/`、`data/`）亦视为受信任的本地输入。
