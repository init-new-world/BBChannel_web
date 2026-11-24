# BBchannel Web Wiki

本目录存放 BBchannel Web 的架构设计、设备连接、图像识别机制、脚本编辑器规范及开发测试文档。日常安装与启动请直接查看根目录 [README.md](../README.md)。

## 文档导航

| 文档 | 内容说明 |
| --- | --- |
| [项目结构与架构设计](architecture.md) | 仓库目录结构、后端分层、WebSocket 实时协议、任务持久化与单步调试 |
| [设备连接、画面与实时触控](device-and-screen.md) | ADB 自动发现与环境变量、MuMu 连接、画面旋转校准、实时触控状态机与提示音 |
| [自动化流程与图像识别机制](automation-and-recognition.md) | 全流程阶段续接、助战筛选、指令卡恢复、操作延时、绊满/掉落识别与活动自动化 |
| [脚本编辑器与资源规范](script-editor-and-resources.md) | 简易向导与专业模式、源码保真 JSON 编辑、特殊技能格式、素材与标签目录约定 |
| [开发、测试与联调指南](development-and-testing.md) | 单元测试、前端语法校验、Playwright 浏览器回归与手动联调清单 |
