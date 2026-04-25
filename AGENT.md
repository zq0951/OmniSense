# 🤖 AI Agent 协作与自动化运维指引 (AI Context)

> [!IMPORTANT]
> **To any AI Agent reading this**: This document provides the essential technical context, architectural decisions, and deployment patterns for the OmniSense project. Use this to guide your reasoning and execution.

## 1. 项目核心架构
- **项目名**：OmniSense (OpenClaw SmartHome)
- **部署模式**：Docker Compose (多容器微服务)
- **关键服务**：
  - `audio_terminal`: 语音交互中枢 (Python/FastAPI)
  - `radar_station`: 空间感知与库存管理 (Python/FastAPI/ESPHome)
  - `whisper-stt`: 语音转文字服务 (Faster-Whisper)

## 2. 自动化部署路径 (Deployment Flow)
1.  **脚本驱动**：优先通过 `./manage.sh` 进行所有运维操作。
2.  **代码补全**：若克隆后缺少 `MOSS-TTS-Nano`，脚本会自动从 `OpenMOSS` 组织拉取。
3.  **配置注入**：
    - 读取 `.env.example` -> 生成 `.env`。
    - 必须由 Agent 辅助确认的变量：`HA_TOKEN`, `AGENT_API_URL`, `API_SERVER_KEY`。

## 3. 核心设计规范 (Expert Guardrails)
- **离线增强猴子补丁**：在 `audio_terminal/main.py` 中存在针对 MOSS-TTS 的离线路径修复逻辑。在重构或移动文件时，**绝对不能删除**这些补丁，否则会导致离线环境加载模型死锁。
- **配置一致性**：所有硬件引脚、HA 实体 ID、网络端口必须通过环境变量控制，禁止在逻辑代码中硬编码。
- **雷达实体 Pattern**：系统支持通过 `RADAR_X_PATTERN` 等变量动态匹配 Home Assistant 实体，以适配不同的雷达固件。
- **双工模式**：`AUDIO_DUPLEX_MODE` 决定了录音与播放是否冲突，`full` 模式需要回声消除硬件支持。

## 4. 调试指引
- **日志聚合**：使用 `./manage.sh logs` 查看所有容器的实时混合日志。
- **常见故障排查**：
  - 404/路径错误：检查 `config.py` 中的 `models--OpenMOSS-Team--...` 路径是否与宿主机文件系统对齐。
  - 语音不响应：检查 `AGENT_API_URL` 是否连通及 VAD 阈值是否过高。

---
_OmniSense AI Helper - v1.0_
