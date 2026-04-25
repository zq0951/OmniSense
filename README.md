# OpenClaw SmartHome (OmniSense) 项目文档

OpenClaw SmartHome（代号：OmniSense）是一个高性能、本地化的 AI 智能家居助理集成方案。它以本地部署的 LLM（如 Qwen2.5/Gemma3 系列）和 OpenClaw 平台为核心，通过优化后的异步语音链路实现极速响应。

## 🏗️ 核心架构与功能组件 (模块化重构)

本项目已完成从单体架构向模块化架构的迁移，核心分为以下职责块：

### 1. OmniSense 语音终端 (`audio_terminal/`)

项目的逻辑中枢与交互入口，具备以下自研特性：

- **异步 I/O 内核 (Async Core)**：全面迁移至 `httpx.AsyncClient`。流式接收 LLM 响应的同时，通过异步生成器实现真正的并发处理，大幅降低响应延迟。
- **自适应 VAD (Adaptive Voice Activity Detection)**：内置背景噪声平滑估计算法。系统能自动学习环境音底噪并动态调整录音触发阈值（RMS Multiplier），在嘈杂环境下依然保持灵敏。
- **VCD 语义意图匹配 (Vector Cosine Distance)**：引入 `sentence-transformers` 语义引擎。不仅支持硬核关键词匹配，还能识别语义相近的模糊指令（如“别说话了”与“安静点”均可触发停止）。
- **流水线并行 (Pipeline parallelism)**：将音频合成 (TTS) 与播放 (Playback) 解耦。在播报当前句子的同时后台并行预合成下一句，实现句子间的“零停顿”。
- **智能提示词策略**：`voice_system_hint` 仅在 Session 首轮对话中注入，在保持模型行为规范的同时节省 Token 并优化长对话连贯性。
- **TTS 健壮性优化**：具备符号口语化转换和强制 EOS (End of Sentence) 注入逻辑。解决 LLM 断句不当导致的 TTS 尾部噪音。

### 2. 空间感知与事件桥接 (`event_bridge/`)

- **感知闭环**：通过 MQTT 监听 Home Assistant 中的雷达、传感器状态。
- **主动式交互**：监听雷达计数实体，根据空间内的“进/出”及“逗留”事件，主动触发 OmniSense 的语音播报。

### 3. 空间雷达与库存管理系统 (`radar_station/`)

- **手动空间分组 (Manual Grouping)**：废弃自动聚类，引入显式 `groupId` 机制。用户可在 Web 面板手动合并物品。
- **坐标同步引擎**：修改组内任一物品的位置，后端自动同步更新。

---

> [!CAUTION]
> **⚠️ 安全性说明 (Security Warning)**
>
> 本项目在与 OpenClaw/Hermes 交互时默认开启了 **YOLO (You Only Live Once) 执行策略**。
>
> - **策略行为**：该模式下 Agent 拥有完全的系统执行权限，且在执行敏感或危险操作（如删除文件、修改系统配置）时 **不会弹出人工确认提示**。
> - **风险提示**：请确保项目部署在受信任的局域网环境，并对 Agent 可调用的工具集进行严格审计。开发者不对因 Agent 自主决策导致的任何数据损失或系统损坏负责。

---

---

## 🤖 AI 协作与自动部署 (AI-First Deployment)

> [!TIP]
> **💡 强烈推荐**：为了获得最佳的开箱即用体验，建议使用 **AI 编程助手**（如 Antigravity, Cursor, Windsurf, Claude Dev 等）配合本项目。
>
> 本项目已针对机器理解进行了深度优化，您可以直接将 [AGENT.md](AGENT.md) 丢给您的 AI 助手，它将引导您完成从环境自检、配置注入到一键启动的全过程。

---

## 🚀 启动与部署 (快速开始)

### 1. 硬件建议 (Hardware Recommendations)

为了获得最佳的语音交互体验，建议如下：

- **推荐方案**：使用 **全向会议麦克风** (如 Jabra Speak 系列、eMeet 等)。这类设备自带硬件级回声消除 (AEC) 和降噪 (ANS)，支持 **全双工模式**（即 OmniSense 说话时你也可以随时打断它）。
- **普通方案**：使用独立的麦克风和音箱。
  - **风险**：音箱的声音会被麦克风录入，导致回声干扰。
  - **对策**：在 `.env` 中设置 `AUDIO_DUPLEX_MODE=half`。此时系统进入 **半双工模式**，在 OmniSense 播报音频期间会暂时关闭麦克风识别，避免自触发。
  - **优化**：如果仍有误触发，请调高 `config.py` 中的 `VAD_MULTIPLIER` 或 `ENERGY_THRESHOLD`。

### 2. 环境准备

本项目支持多种启动模式，以适应是否有雷达硬件的场景。

### 1. 环境准备

```bash
cd /root/smarthome
# 脚本会自动检查并生成 .env 文件
./manage.sh help
```

请编辑 `.env` 文件，填入必要的 `HA_TOKEN` 和 `AGENT_API_URL`。

### 2. 启动服务

使用内置管理脚本一键启动：

```bash
./manage.sh start
```

### 3. 常用运维指令

使用内置管理脚本可以简化所有日常操作：

```bash
# 查看实时日志
./manage.sh logs

# 重启系统
./manage.sh restart

# 强制重新构建并启动
./manage.sh start --build

# 彻底清理环境
./manage.sh clean
```

## 📁 项目目录结构

```text
/root/smarthome
├── manage.sh                # 🚀 统一管理脚本 (推荐入口)
├── docker-compose.yml       # 容器排布方案 (支持 Profiles)
├── audio_terminal/          # 🎙️ 语音交互逻辑核心 (OmniSense Audio)
│   ├── main.py              # 程序主入口
│   ├── config.py            # 全局参数配置
│   ├── core/                # 核心引擎 (VAD/STT/TTS/Orchestrator)
│   ├── api/                 # REST 路由 (FastAPI)
│   └── models/              # [GitIgnore] 语义模型权重
├── radar_station/           # 📡 雷达感知与空间管理模块
│   ├── radar_server.py      # 服务端逻辑
│   ├── radar.yaml           # ⚡ ESPHome 硬件配置文件 (ESP32-C3 + LD2450)
│   ├── radar_view.html      # 空间可视化面板
│   ├── inventory.json       # [GitIgnore] 个人物品库存数据
│   ├── zones.json           # [GitIgnore] 房间坐标配置
│   ├── zones.json.example   # 空间配置模板
│   └── inventory.json.example # 库存数据模板
├── MOSS-TTS-Nano/           # 🔊 TTS 推理运行时 (核心依赖)
├── voice-stack/             # 🛠️ 语音基础服务 (Whisper/Kokoro 等)
├── .env.example             # 环境变量配置模板
└── requirements.txt         # 基础依赖列表
```

## 🛠️ 硬件方案 (Hardware Setup)

本项目推荐使用以下硬件方案以实现最佳空间感知：

1. **主控**：ESP32-C3 (如 Xiao ESP32-C3 或普通开发板)。
2. **雷达**：希尔联 LD2450 毫米波雷达模块。
3. **固件**：使用 `radar_station/radar.yaml` 通过 [ESPHome](https://esphome.io/) 刷写。
   - **接线**：RX 接 (GPIO 4)，TX 接 (GPIO 5)。
   - **配置**：在刷写前请确保已配置好 WiFi 信息。

## 📦 模型准备 (Model Setup)

本项目依赖多个预训练模型，建议在启动前手动准备以加快首次启动速度：

1. **MOSS TTS 权重**：
   - 下载 [OpenMOSS-Team/MOSS-TTS-Nano](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano) 的所有文件。
   - 放置路径：`MOSS-TTS-Nano/hf_cache/hub/models--OpenMOSS-Team--MOSS-TTS-Nano/snapshots/...` (详见 `.env.example`)。
2. **Whisper STT 权重**：
   - 默认会自动下载 `small` 模型。
   - 如需离线使用，请提前将模型放入 `voice-stack/whisper-models`。
3. **语义引擎权重**：
   - 系统首次运行会下载 `paraphrase-multilingual-MiniLM-L12-v2` 用于意图识别。
   - **离线存放路径**：`audio_terminal/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。

## 🛠️ 后续计划 (Roadmap)

### 🟢 核心功能增强 (P0)

- **[DONE] 模块化重构**：实现高内聚、低耦合的组件化代码结构。
- **[DONE] 动态阈值 (Adaptive VAD)**：基于背景环境音实时计算灵敏度。
- **[DONE] 语义意图匹配**：基于向量相似度的指令拦截系统。
- **[DONE] 异步响应流**：全面提升并发性能。

### 🟡 体验调优 (P1)

- **多模型负载均衡**：在 GPU 集群与 CPU 本地推理间实现自动调度。
- **唤醒词支持**：引入轻量级离线唤醒词引擎 (Wake Word)。

### 🔴 架构演进 (P2)

- **分布式播报**：支持多房间音响联动。
- **知识库集成**：引入 RAG 架构，使 OmniSense 具备完整的家庭文档记忆。

---

## 🤝 贡献与反馈 (Contributing)

我们非常欢迎社区的贡献！无论是修复 Bug、增加新功能还是优化文档，请随时提交 Pull Request。

- **提交规范**：请确保代码通过基础测试，并保持现有的异步/模块化风格。
- **交流方式**：建议通过 GitHub Issues 记录功能建议或错误反馈。

## 📜 许可证 (License)

本项目采用 **MIT License**。详情请参阅 [LICENSE](LICENSE) 文件。

_OmniSense - 让家不仅智能，更有温度。_
