# 设备连接、画面校准与实时触控

## ADB 自动发现与配置

`AdbBackend` 按以下顺序查找 ADB 可执行文件：
1. 环境变量 `BBCHANNEL_ADB_PATH`
2. 仓库内置 `bin/adb/`（含 `33.0.2`、`airtest_adb`、`leidian_adb`、`nox_adb`；在 Linux/WSL 等非 Windows 宿主上会优先使用原生 POSIX `adb`，再回退 `.exe`）
3. 上级目录 `../adb/` 或系统 `PATH`

连接发现流程：先执行 `adb devices -l` 获取已连接设备；启用自动发现时，探测常见模拟器端口并尝试 `adb connect`，随后刷新设备详情（型号、Android 版本、分辨率、网络与 Root 状态）。在 WSL 环境下，`auto` 主机会自动从 `/etc/resolv.conf` 读取 Windows 宿主机 IP，从而无需硬编码即可发现宿主机上的 MuMu 等模拟器（例如返回 `172.x.x.x:16384` 或 `172.x.x.x:7555`）。

### 环境变量覆盖

```bash
BBCHANNEL_ADB_PATH=
BBCHANNEL_ADB_AUTO_CONNECT=1
BBCHANNEL_ADB_SCAN_HOSTS=auto
BBCHANNEL_ADB_SCAN_PORTS=5555,16384,7555,62001
BBCHANNEL_ADB_CONNECT_TIMEOUT_MS=300
BBCHANNEL_ADB_DISCOVERY_TTL_SECONDS=10
BBCHANNEL_ADB_ENRICH_DETAILS=1
```

### 截屏与输入加速

- **快速截屏**：优先使用 DroidCast 720p 预缩放会话（`BBCHANNEL_ADB_DROIDCAST=1`）或原始 `exec-out screencap`（`BBCHANNEL_ADB_FAST_CAPTURE=1`），失败时自动回退标准 `screencap -p`。
- **快速输入**：默认保持每设备一条持久 `adb shell` 通道（`BBCHANNEL_ADB_FAST_INPUT=1`），通过 C++ Binder 的 `cmd input` 直接注入 `tap`、`swipe` 及 `motionevent`，省去每次操作拉起进程的开销。

## MuMu 原生 / Bridge 连接

在 Windows 本地可直接调用 MuMu 原生 DLL；在 WSL 环境中可通过宿主机运行的 `bin/mumu_ipc_bridge.py` 进行 TCP 桥接，支持低延迟截屏与 `touch_down` / `touch_up` 触控事件。

## 画面旋转校准

控制台屏幕工具栏复刻了原版连接校准流程，对应接口为 `GET /api/screen/rotation` 与 `POST /api/screen/rotation`：

- `FrameNormalizer.rotation` 支持 `null`（自动将竖屏旋转为横屏）及显式 `0° / 90° / 180° / 270°`。
- 工具栏按钮 **`-90°`**、`+90°`、`Auto` 会立即更新旋转角度、重置旧的坐标变换矩阵并刷新一帧，且在重连期间保持用户校准结果。
- 脚本 JSON 支持可选字段 `screenRotation`（`null` / `0` / `90` / `180` / `270`），全流程运行启动前会自动应用非空旋转配置。

## 实时画面与防抖触控

屏幕画布由 [screen-touch.js](../webapp/static/screen-touch.js) 驱动，基于 Pointer Events 四态互斥状态机实现防抖与实时交互：

- **点击（Tap）**：按下到松开位移 `< 10px` 且时长 `< 420ms` 时，以按下点坐标触发 `tap`，并过滤鼠标微动开关 `< 45ms` 的同点硬件抖动双击。
- **实时长按（Long Press）**：在防抖半径内持续按住满 `420ms` 立即向设备发送 `touch_down`（画面实时显示游戏反应），长按期间放宽微颤容错半径，松手瞬间发送 `touch_up`。
- **实时拖动（Drag）**：位移超过 `10px` 即锁定拖动并取消长按计时器，立即从起点发送 `touch_down` 并按节流间隔实时流式发送 `touch_move`，松手发送 `touch_up`；后端对并发 `touch_move` 做最新位置合并避免拖影延迟。
- **安全兜底**：切窗失焦、`pointercancel`、按 `Esc` 或 WebSocket 断线时自动补发 `touch_cancel` / `touch_up`；未勾选“触控”时点击/拖动仅回填左侧 `Tap` / `Swipe` 坐标而不操作设备。

## 完本提示音

任务面板内置完本音频提醒，偏好保存在 `localStorage`：
- 内置 Web Audio 合成音效（`chime`、`bell`、`beep`），区分正常完成与失败/取消；也可在当前会话选择本地音频文件。
- 严格仅在任务由活跃态转为终态时触发一次，不会重播历史已完成任务。
