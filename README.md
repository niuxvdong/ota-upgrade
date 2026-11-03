# OTA 终端模拟器

用 MQTT 模拟终端，覆盖 OTA 升级全流程的 17 个状态，无需真实硬件。

## 快速开始

**Web 版（推荐）**

双击 `启动Web版.bat`，浏览器自动打开 http://127.0.0.1:8080

**手动启动**

```bat
python web_server.py 127.0.0.1 8080
```

## 依赖

```
pip install paho-mqtt
```

bat 脚本会自动检测并安装。

## 文件说明

| 文件 | 说明 |
|---|---|
| `mock_device.py` | 核心模块：配置区、场景定义、protobuf 解析 |
| `web_core.py` | 终端管理器：MQTT 连接、场景执行、持久化 |
| `web_server.py` | Web 服务：UI 页面 + HTTP API |
| `启动Web版.bat` | 一键启动 Web 版 |

## 界面说明

```
┌─────────────────────────────────────────────────────────────────┐
│ [broker][端口][deviceId][deviceType][用户名][密码][协议]        │
│ [连接][断开][注册报文][保存配置]  ●未连接                       │
├──────────────┬────────────────────────────┬─────────────────────┤
│ 连接状态      │ 最近收到的命令  [✓只看升级] │ 实时日志            │
│              │                            │                     │
│ 自动场景      │ 手动回报状态（15 个按钮）   │                     │
│  升级方式     │                            │                     │
│  模块类型     │ 消息收发                   │                     │
│  [场景列表]   │  ┌──────────────────────┐  │                     │
│              │  │ 收发记录（绿收蓝发）   │  │                     │
│ 订阅 Topic    │  └──────────────────────┘  │                     │
│              │  [topic 下拉]  [发送]       │                     │
│              │  [报文输入框]               │                     │
└──────────────┴────────────────────────────┴─────────────────────┘
```

## 核心功能

### 升级方式（自动推导 commandType）

| 升级方式 | commandType 规则 |
|---|---|
| **自动升级** | 全部 `3001`（下载+升级合并） |
| **下载后手动升级**（默认） | 下载阶段 `3006`，升级阶段(11/12/13/22/23) `3007` |

场景步骤里 commandType 是**只读显示**，随升级方式和状态码自动变化。

### 模块类型

对应 `FirmwareModuleTypeEnum`，写入报文的 `data.moduleType`：

| 值 | 含义 |
|---|---|
| 1 | 主机 HOST |
| 2 | 天线 ANTENNA |
| 3 | 安全卡 SECURITY |
| **4** | **终端套件 SDK（默认）** |
| 5 | AP |
| 6 | CP |
| 7 | 安全芯片 SECURITY_CHIP |
| 101/104 | 单点模式 |

### 场景

9 个预置场景，可编辑步骤、也可新建自定义场景：

| 场景 | 流程 |
|---|---|
| `download-ok` | 10 → 14（正常下载） |
| `download-abort` | 10 → 18 → 26 → 14（中断续传） |
| `download-fail` | 10 → 18 → 29（不可续传） |
| `verify-fail` | 10 → 15（验签失败） |
| `full-success` | 10 → 14 → 11 → 12（全流程成功） |
| `upgrade-fail` | 10 → 14 → 11 → 13（升级失败） |
| `no-reply` | 不回响应，触发超时 |
| `delete-ok` | 14 → 24（删包成功） |
| `delete-fail` | 14 → 25（删包失败） |

**两种用法**：

- **点场景卡片** = 选中，平台下发命令后自动按步骤回报
- **点 ▶ 按钮** = 立即执行，不等平台命令

### 手动回报状态

点击状态按钮 **不会直接发送**，而是把报文**填充到下方发送框**，你检查/修改后再点【发送】。

好处：
- 能先看清 requestId、commandType、data 是否正确
- 可以在发送前临时改字段
- 不会误发

### 只看升级命令

最近命令区右上角开关（默认开启）：

- **开启**：只显示 `3001`/`3006`/`3007`，其他命令显示灰色过滤提示
- **关闭**：全部命令都显示

状态存在 localStorage。

## 重要规则

### 平台侧的处理逻辑

`OtaFirmwareUpdateHandler` 的核心规则：

```
if (progress != null) {
    只走进度分支，status 完全被忽略
    return;
}
```

因此：

| 状态 | 必须 | 原因 |
|---|---|---|
| `18`（下载中断） | **不能带 progress** | 带 progress 会走进度分支，18 置不上 |
| `29`（下载失败） | **不能带 progress** | 同上，否则走不到 setPushEndTime |
| `26`（续传中） | 平台自动推导 | 记录已是 18 且 offset > 上次 downloadSize |
| `10`（下载中） | 可带 progress | 从 20 自动提升为 10 |

### Topic

| Topic | 用途 |
|---|---|
| `access/device/{deviceId}/command` | 订阅：接收平台下发命令 |
| `access/device/executetask/result` | 发布：异步任务结果上报（OTA 状态） |
| `access/device/command/reply` | 发布：同步命令应答 |
| `device/register` | 发布：终端注册 |

**白名单限制**：接入系统校验 topic 中的 deviceId 必须等于 clientId。
如果加了 clientId 前缀，topic 里的 deviceId 就对不上，订阅会被拒绝（SUBACK=0x80）。

### 注册报文

连接时自动上报到 `device/register`。

默认值：
- `deviceType`: `999`
- `hostVersion`: `025_999_1_V1.0.1`
- `sdkVersion`: `025_999_1_V1.0.1`

可在【注册报文】弹窗里编辑，改后点【保存为模板】持久化。

## 配置持久化

所有配置存在同目录的 `mock-config.json`：

```json
{
  "otaType": 1,                    // 升级方式 0=自动 1=手动
  "moduleType": 4,                 // 模块类型
  "conn": {                        // 顶部连接配置
    "host": "172.1.2.14",
    "port": "1883",
    "deviceId": "DEVICE-001",
    "deviceType": "999",
    "username": "cscn-sat",
    "password": "...",
    "protocolVersion": 5
  },
  "sendBox": {                     // 发送区
    "topic": "access/device/executetask/result",
    "payload": "{...}"
  },
  "scenarios": {                   // 内置场景的步骤覆盖
    "download-ok": [...]
  },
  "customScenarios": {             // 自定义场景
    "my-scene": { "desc": "...", "steps": [...] }
  },
  "statuses": [...],               // 状态按钮
  "registerPayload": { ... }       // 注册报文模板
}
```

**保存时机**：

| 方式 | 触发 |
|---|---|
| 自动 | 输入框防抖 600ms / 失焦 / 关页面 sendBeacon |
| 手动 | 点【保存配置】按钮 |

**并发安全**：文件写入有专用锁 + 唯一临时文件名 + 重试 5 次，多请求同时保存不会冲突。

**恢复默认**：删除 `mock-config.json` 即可。

## 配置项（mock_device.py）

```python
MQTT_HOST = "172.1.2.14"        # broker IP
MQTT_PORT = 1883
MQTT_USERNAME = "cscn-sat"
MQTT_PASSWORD = "b3a515...;hmacsha256"
MQTT_PROTOCOL_VERSION = 5       # 5=MQTT5.0  4=3.1.1  3=3.1
CLIENT_ID_PREFIX = ""           # clientId 前缀，留空
DEVICE_ID = "DEVICE-001"
DEVICE_TYPE = "999"
```

也支持环境变量覆盖：`MQTT_HOST`、`MQTT_PORT`、`DEVICE_ID` 等。

## 排查问题

**连接超时**

先确认 TCP 能否连通：

```bat
telnet 172.1.2.14 1883
```

页面连接失败时，日志会显示具体停在哪一步（步骤1/3 TCP、步骤2/3 握手、步骤3/3 订阅）。

**订阅被拒绝**

日志显示 `[订阅失败] ... SUBACK=0x80`，说明 topic 不在白名单。
检查 clientId 是否与 topic 中的 deviceId 一致。

**状态置不上**

- 数字状态没问题，但平台记录没变 → 检查是否误带了 `progress`
- `26` 不出现 → 需要先发 `18`，再发带更大 `offset` 的 `10`

**页面显示旧版本**

标题栏有版本号 `v2.3-xxxxx`。如果不对：
1. `Ctrl + Shift + R` 强刷
2. 或关闭所有 python 进程后重新双击 bat

## 消息解析说明

平台下发的命令是 **protobuf 二进制**（`MqttRequestProtobuf`）：

| 字段 | 内容 |
|---|---|
| field 1 | requestId |
| field 2 | commandType |
| field 301/306 | DeviceOTANoticeRequest（version/description/md5/url/packageName/moduleType/fileLength）|
| field 307 | DeviceUpgradePackageRequest（packages 数组）|

页面会自动解析成 JSON 展示，原始 hex 也能看到。

如果平台配置 `device.deserialize.deviceMethod=0`（自适应），也可能下发 JSON，同样能解析。
