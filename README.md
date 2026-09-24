# Garmin Health Dashboard & Intervals.icu Bridge ⌚⚡

> **佳明健康与心率精度诊断控制台 × Intervals.icu 跨区自动中继桥梁**
>
> 专为佳明（Garmin）用户打造的开源健康数据可视化与诊断平台，原生支持**佳明中国区（connect.garmin.cn）**与**国际区（connect.garmin.com）**。通过服务端后台自动化，一举解决国内佳明无法直接接入 Intervals.icu 的痛点，并提供专业的心率假性尖刺、步频锁定（Cadence Lock）诊断与纯净 Bark 推送。

---

## ✨ 核心特性

- 🇨🇳 **佳明中国区/国际区双支持**：原生适配中国区（`connect.garmin.cn`）与国际区，本地生成 OAuth Token 免密静默持久化，无需手动导出数据。
- ⚡ **Vue 3 纯前端响应式单页架构（SPA）**：
  - **零白屏、零跳转**：全链路采用异步 AJAX 内部驱动，URL 保持极致纯净（不堆叠任何冗余参数）。
  - **沉浸式单日步进控制**：提供「前一天 / 今天 / 后一天」极速单手点按切换，支持原生系统日历快速直选及「还原」即时回跳今日。
  - **自然跨层级无缝下钻**：支持从周度 7 天矩阵、月度生理热力日历一键直接穿透查看单日 24 小时高精度心率曲线。
- 🌊 **HRV 自主神经全域深度融合**：
  - **今日全景**：展示入睡至苏醒昨夜连续 5 分钟高精度 HRV 曲线，搭配个人生理黄金平衡带标尺（$\\pm 0.75 \\text{ SD}$）与峰谷微型图钉。
  - **周度洞察**：步数万步达标柱状图与「静息心率 (RHR) × 夜间 HRV」双轴趋势图像素级垂直对齐。
  - **月度全貌**：全月 31 天多维度生理状态热力图与跨季度健康基线滚动评估，支持全量历史跨年跨月回溯。
- 🌐 **Intervals.icu 跨区自动桥梁**：
  - 自动从佳明国区抓取单次跑步/骑行运动的原始 **`.FIT` 轨迹文件** 并中继上传给 Intervals.icu。
  - 每日昨夜 HRV、睡眠、静息心率自动推送到 Intervals.icu 日历。
  - 自动拉取云端计算的 **有氧心率解耦率（Pa:Hr Decoupling）** 与 **Banister 体能/疲劳模型（CTL / ATL / TSB）** 回传本地展示。
- 💓 **全天心率质量与传感器精度诊断**：
  - **光电假性尖刺识别（Optical Spikes）**：利用动态变化率捕捉因手腕急甩产生的瞬时心率虚高。
  - **佩戴松动脱落捕捉（Dropouts）**：识别心率信号突然骤跌与断连。
  - **步频锁定专项诊断（Cadence Lock）**：自动比对运动中心率与步频（SPM）走势，诊断表带松动引起的假性高心率共振。
- 🍎 **Bark 纯净推送**：
  - **每日限次简报**：每天仅在晨间同步完睡眠/HRV 后推送 1 次健康简报，白天后续步数/活动更新完全静默，杜绝通知轰炸。
  - **纯文本纯净消息**：不带多余 URL 链接，清晰直观。
  - **异常增量预警**：仅在新捕捉到心率异常点时告警。
- 🛠️ **全功能设置控制面板**：Web 界面内建 Garmin 账号、Intervals.icu 凭据与 Bark 服务的明文显隐编辑与即时连通性校验。
- 🚀 **Docker 一键容器化编排**：全栈打包，带 40s 毫秒级自适应智能探测器，开箱即用。

---

## 🛠️ 快速开始

### 方式一：Docker Compose（推荐）

1. **克隆仓库**
   ```bash
   git clone https://github.com/anthony11122/garmin-dashboard.git
   cd garmin-dashboard
   ```

2. **准备配置文件**
   ```bash
   cp config.example.yaml config.yaml
   ```
   修改 `config.yaml` 填入你的佳明账号与相关凭据（或稍后直接在 Web 界面设置中填写）：
   ```yaml
   garmin:
     email: "your_garmin_email@example.com"
     password: "your_garmin_password"
     is_cn: true  # 佳明国区设为 true，国际区设为 false
   ```

3. **启动服务**
   ```bash
   docker compose up -d --build
   ```

4. **访问控制台**
   在浏览器打开：`http://localhost:8099`（或服务器内网 IP）。

---

### 方式二：本地 Python 运行

```bash
git clone https://github.com/anthony11122/garmin-dashboard.git
cd garmin-dashboard

# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 准备配置文件
cp config.example.yaml config.yaml

# 启动服务
uvicorn app:app --host 0.0.0.0 --port 8099 --app-dir src
```

---

## ⚙️ 配置说明

完整配置模板见 `config.example.yaml`：

| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `garmin.is_cn` | `true` | `true` 为中国区 (`connect.garmin.cn`)，`false` 为国际区 |
| `garmin.realtime_probe` | 自动开启 | 默认毫秒级时间戳轻量探针（40秒），手表在手机 App 同步后自动秒级跟进抓取 |
| `intervals_icu.api_key` | `""` | Intervals.icu 开发者 API Key（从官网设置中复制） |
| `intervals_icu.athlete_id` | `"0"` | Intervals.icu 运动员 ID（填 `0` 即可自动解析） |
| `bark.enabled` | `true` | 是否启用 Bark 推送通知 |
| `bark.server` | `https://api.day.app` | Bark 服务器地址（自建可填 `http://ip:port`） |
| `bark.notify_on_sync` | `true` | 晨间首次同步后推送每日健康简报（1次/天） |
| `anomaly_detection.spike_threshold_bpm` | `35` | 光电心率假性突发尖刺阈值 (bpm) |
| `anomaly_detection.dropout_threshold_bpm`| `42` | 心率信号骤跌脱落阈值 (bpm) |

---

## 🔒 隐私与安全性

- **本地持久化**：所有账号密码仅在容器本地初次连接时使用，随后换取 OAuth Token 缓存在 `data/tokens/`，绝不上传第三方。
- **无外网泄露**：除向佳明官方与用户配置的 Intervals.icu / Bark 发送请求外，服务 100% 运行于本地局域网环境中。
- **SQLite 数据持久化**：每日生理数据保存在本地 SQLite 数据库中，挂载于 `data/` 目录。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
