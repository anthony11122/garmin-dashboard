# Garmin Health Dashboard & Intervals.icu Bridge ⌚⚡

> **佳明健康与心率精度诊断控制台 × Intervals.icu 跨区自动中继桥梁**
>
> 专为佳明（Garmin）用户打造的开源健康数据可视化与诊断平台，原生支持**佳明中国区（connect.garmin.cn）**与**国际区（connect.garmin.com）**。通过服务端后台自动化，一举解决国内佳明无法直接接入 Intervals.icu 的痛点，并提供专业的心率假性尖刺、步频锁定（Cadence Lock）诊断与纯净 Bark 推送。

---

## ✨ 核心特性

- 🇨🇳 **佳明中国区/国际区双支持**：原生适配中国区（`connect.garmin.cn`）与国际区，本地生成 OAuth Token 免密静默持久化，无需手动导出数据。
- 🌐 **Intervals.icu 跨区自动桥梁**：
  - 自动从佳明国区抓取单次跑步/骑行运动的原始 **`.FIT` 轨迹文件** 并中继上传给 Intervals.icu。
  - 每日昨夜 HRV、睡眠、静息心率自动推送到 Intervals.icu 日历。
  - 自动拉取云端计算的 **有氧心率解耦率（Pa:Hr Decoupling）** 与 **Banister 体能/疲劳模型（CTL / ATL / TSB）** 回传本地展示。
- 💓 **全天心率质量与传感器精度诊断**：
  - **光电假性尖刺识别（Optical Spikes）**：利用动态变化率捕捉因手腕急甩产生的瞬时心率虚高。
  - **佩戴松动脱落捕捉（Dropouts）**：识别心率信号突然骤跌与断连。
  - **步频锁定专项诊断（Cadence Lock）**：自动比对运动中心率与步频（SPM）走势，诊断表带松动引起的假性高心率共振。
- 🌊 **HRV 自主神经与恢复评估**：基于 60 天动态正态分布带宽（$\pm 0.75 \text{ SD}$），量化交感/副交感神经平衡。
- 🍎 **Bark 纯净推送**：
  - **每日限次简报**：每天仅在晨间同步完睡眠/HRV 后推送 1 次健康简报，白天后续步数/活动更新完全静默，杜绝通知轰炸。
  - **纯文本纯净消息**：不带多余 URL 链接，清晰直观。
  - **异常增量预警**：仅在新捕捉到心率异常点时告警。
- 🚀 **Docker 一键容器化编排**：全栈打包，带自适应智能探测器，开箱即用。

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
| `garmin.auto_sync_interval_hours` | `2` | 后台定时同步周期（小时） |
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
