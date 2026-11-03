#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTA 终端模拟器 —— 核心模块

包含：配置区、场景定义、protobuf 解析（Web 版与 CLI 版共用常量）

链路：
  平台 --Dubbo--> 接入系统 --MQTT--> 本模拟器
  本模拟器 --MQTT--> 接入系统 --Kafka--> 平台

依赖：
  pip install paho-mqtt
"""


# ==============================================================================
#
#                            ★★★  配 置 区  ★★★
#
#   只需修改下面这几项即可，无需改动其它代码。
#   优先级：命令行参数 > 环境变量 > 这里的默认值
#
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. MQTT 连接
# ------------------------------------------------------------------------------
MQTT_HOST = "172.1.2.14"     # ← broker IP
MQTT_PORT = 2883             # ← broker 端口

MQTT_USERNAME = "cscn-sat"   # ← 用户名
MQTT_PASSWORD = "b3a515284503d2e689a20f74e8f47fe8;hmacsha256"   # ← 密码
MQTT_AUTH_METHOD = "hmacsha256"   # 认证方式（仅供日志展示）

# MQTT 协议版本：5 = MQTT 5.0，4 = MQTT 3.1.1，3 = MQTT 3.1
MQTT_PROTOCOL_VERSION = 5

# clientId 前缀（留空 = 不加前缀）
CLIENT_ID_PREFIX = ""

# 是否使用 TLS
MQTT_USE_TLS = False

# ------------------------------------------------------------------------------
# 2. 模拟终端身份
# ------------------------------------------------------------------------------
DEVICE_ID = "DEVICE-0001"    # ← 要模拟的终端 deviceId
DEVICE_TYPE = "999"          # ← 设备类型

# ------------------------------------------------------------------------------
# 3. Topic（接入系统约定）
# ------------------------------------------------------------------------------
TOPIC_REGISTER = "device/register"                      # 终端注册
TOPIC_REGISTER_REPLY = "device/register/reply"          # 注册应答
TOPIC_COMMAND_REPLY = "access/device/command/reply"     # 命令同步应答
TOPIC_TASK_RESULT = "access/device/executetask/result"  # 异步任务结果
TOPIC_COMMAND_TEMPLATE = "access/device/%s/command"     # 命令下发

# ------------------------------------------------------------------------------
# 4. 注册报文（点击"连接"时自动上报）
# ------------------------------------------------------------------------------
REGISTER_TOPIC = "device/register"

REGISTER_PAYLOAD = {
    "deviceId": "DEVICE-0001",
    "commandType": "1000",
    "code": 200,
    "msg": "register",
    "timestamp": 0,          # 0 表示运行时自动填充
    "data": {
        "deviceId": "DEVICE-0001",
        "deviceType": "999",
        "terminalType": 1,
        "IMEI": "11111111",
        "IMSI": "22222222",
        "hostVersion": "025_999_1_V1.0.1",
        "APVersion": "",
        "CPVersion": "",
        "sdkVersion": "025_999_1_V1.0.1",
        "osVersion": "Ubuntu 20.04.6 LTS (Focal Fossa)",
        "orbitType": 1,
        "releaseTime": "2025-07-31",
        "dnnInfo": "",
        "userDnn": "1111111",
        "oamAddr": "",
        "proxyServer": "dm123456",
        "useProxy": True,
        "securityVersion": "",
        "hostId": "hostid",
        "cpid": "cpid",
        "apid": "apid",
        "securityId": "seid",
        "antennaId": "anid",
        "antennaVersion": "",
        "timestamp": 0,        # 0 = 运行时自动填充
    },
}

# ------------------------------------------------------------------------------
# 5. 默认场景
# ------------------------------------------------------------------------------
DEFAULT_SCENARIO = "interactive"

# ------------------------------------------------------------------------------
# 6. 命令类型
# ------------------------------------------------------------------------------
CMD_OTA_UPGRADE = "3001"            # 设备OTA升级（下载 + 升级合并）
CMD_OTA_DOWNLOAD = "3006"           # 固件升级包下载（仅下载）
CMD_OTA_PACKAGE_UPGRADE = "3007"    # 固件升级包刷新（仅升级）

CMD_NAMES = {
    "3001": "OTA升级(下载+升级)",
    "3006": "升级包下载",
    "3007": "升级包刷新",
}

# ==============================================================================
#                          配 置 区 结 束（以下无需修改）
# ==============================================================================

import argparse
import copy
import json
import os
import sys
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[ERROR] 缺少依赖，请先执行：pip install paho-mqtt")
    sys.exit(1)

# 环境变量覆盖
MQTT_HOST = os.getenv("MQTT_HOST", MQTT_HOST)
MQTT_PORT = int(os.getenv("MQTT_PORT", MQTT_PORT))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", MQTT_USERNAME)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", MQTT_PASSWORD)
MQTT_AUTH_METHOD = os.getenv("MQTT_AUTH_METHOD", MQTT_AUTH_METHOD)
DEVICE_ID = os.getenv("DEVICE_ID", DEVICE_ID)
DEVICE_TYPE = os.getenv("DEVICE_TYPE", DEVICE_TYPE)

REGISTER_PAYLOAD["deviceId"] = DEVICE_ID
if isinstance(REGISTER_PAYLOAD.get("data"), dict):
    REGISTER_PAYLOAD["data"]["deviceId"] = DEVICE_ID
    REGISTER_PAYLOAD["data"]["deviceType"] = DEVICE_TYPE


def topic_command(device_id):
    """命令下发 topic：access/device/{deviceId}/command"""
    return TOPIC_COMMAND_TEMPLATE % device_id


# ============================================================================
# 状态码 → 中文描述
# ============================================================================
STATUS_DESC = {
    -10: "升级包已覆盖失效",
    0:   "不回响应（触发超时）",
    5:   "待终端稳定入网",
    10:  "升级包下载中",
    11:  "终端升级中",
    12:  "终端升级成功",
    13:  "终端升级失败",
    14:  "下载完成等待升级",
    15:  "升级包验签失败",
    18:  "下载中断，等待续传",
    20:  "平台推送命令下发成功",
    21:  "套件推送命令接收失败",
    22:  "平台升级命令下发成功",
    23:  "套件升级命令接收失败",
    24:  "远程删除本地固件包成功",
    25:  "远程删除本地固件包失败",
    26:  "续传中",
    29:  "下载失败（不可续传）",
}

# 升级阶段状态（手动升级时用 3007）
UPGRADE_STAGE_STATUS = {11, 12, 13, 22, 23}


# ============================================================================
# 场景定义：list of (delay_seconds, status, extra_data, desc)
# status=None 表示不回响应（用于触发超时）
# ============================================================================
SCENARIOS = {

    # ---------- 推送阶段 ----------
    "download-ok": {
        "desc": "正常下载：10 → 14",
        "steps": [
            (1, 10, {"progress": 45, "offset": 4718592, "speed": 1024}, "下载中（20→10，写入进度）"),
            (10, 14, {"fileSize": 10485760, "version": "1.0.1"}, "下载完成"),
        ],
    },
    "download-abort": {
        # 18 必须不带 progress（带 progress 会被进度分支拦截）
        # 26 由平台自动判定（记录已是18 + offset 增长）
        "desc": "下载中断后续传：10 → 18 → 26 → 14",
        "steps": [
            (1, 10, {"progress": 30, "offset": 3145728}, "下载中（20→10，写入进度）"),
            (10, 18, {}, "下载中断（不带 progress 才能置 18）"),
            (10, 10, {"progress": 45, "offset": 4718592}, "重新上报进度，平台自动转 26 续传中"),
            (10, 10, {"progress": 80, "offset": 8388608}, "继续下载"),
            (10, 14, {"fileSize": 10485760}, "下载完成"),
        ],
    },
    "download-fail": {
        # 29 必须不带 progress，否则走不到 setPushEndTime
        "desc": "下载中断且无法续传：10 → 18 → 29",
        "steps": [
            (1, 10, {"progress": 30, "offset": 3145728}, "下载中"),
            (10, 18, {}, "下载中断"),
            (10, 29, {"faultCode": 0}, "下载失败（终止，不带 progress）"),
        ],
    },
    "verify-fail": {
        "desc": "验签失败：10 → 15",
        "steps": [
            (1, 10, {"progress": 100, "offset": 10485760}, "下载完成"),
            (10, 15, {"faultCode": 0}, "验签失败"),
        ],
    },

    # ---------- 升级阶段 ----------
    "full-success": {
        "desc": "自动升级全流程：10 → 14 → 11 → 12",
        "steps": [
            (1, 10, {"progress": 50, "offset": 5242880}, "下载中"),
            (10, 14, {"fileSize": 10485760}, "下载完成等待升级"),
            (10, 11, {}, "终端升级中"),
            (10, 12, {"version": "1.0.1"}, "升级成功"),
        ],
    },
    "upgrade-fail": {
        "desc": "升级失败：10 → 14 → 11 → 13",
        "steps": [
            (1, 10, {"progress": 100, "offset": 10485760}, "下载中"),
            (10, 14, {"fileSize": 10485760}, "下载完成"),
            (10, 11, {}, "终端升级中"),
            (10, 13, {"faultCode": 5}, "升级失败（软件升级被终止）"),
        ],
    },

    # ---------- 下载完成后可触发的场景（手动升级第二阶段）----------
    # 这些场景假设终端已经完成下载（记录处于 14 下载完成等待升级），
    # 平台下发 3007 升级命令后触发。也可直接用 ▶ 立即执行。
    "upgrade-only-success": {
        "desc": "仅升级成功（下载已完成）：11 → 12",
        "steps": [
            (1, 11, {}, "终端升级中（14→11）"),
            (10, 12, {"version": "1.0.1"}, "升级成功（11→12）"),
        ],
    },
    "upgrade-only-fail": {
        "desc": "仅升级失败（下载已完成）：11 → 13",
        "steps": [
            (1, 11, {}, "终端升级中（14→11）"),
            (10, 13, {"faultCode": 5}, "升级失败（11→13）"),
        ],
    },
    "upgrade-timeout": {
        "desc": "升级命令不响应（下载已完成）：触发升级超时 → 23",
        "steps": [
            (0, None, None, "收到 3007 不回响应，等待超时任务置 23"),
        ],
    },
    "download-done-hold": {
        "desc": "仅下载完成并停留（等待手动升级）：10 → 14",
        "steps": [
            (1, 10, {"progress": 100, "offset": 10485760, "speed": 2048}, "下载中（进度拉满）"),
            (5, 14, {"fileSize": 10485760, "version": "1.0.1"}, "下载完成，停在 14 等待升级"),
        ],
    },
    "download-done-verify-fail": {
        "desc": "下载完成但验签失败：10 → 15",
        "steps": [
            (1, 10, {"progress": 100, "offset": 10485760}, "下载中"),
            (5, 15, {"faultCode": 0}, "验签失败（不会进入升级阶段）"),
        ],
    },
    "download-done-delete": {
        "desc": "下载完成后删除本地包成功：14 → 24",
        "steps": [
            (1, 24, {"moduleType": 1}, "远程删除本地固件包成功（14→24，直接发 24）"),
        ],
    },
    "download-done-delete-fail": {
        "desc": "下载完成后删除包失败：14 → 25",
        "steps": [
            (1, 25, {"moduleType": 1}, "远程删除本地固件包失败（14→25，直接发 25）"),
        ],
    },

    # ---------- 超时 ----------
    "no-reply": {
        "desc": "故意不回响应，触发 5 分钟超时：20 → 21",
        "steps": [
            (0, None, None, "收到命令不回响应，等待超时任务置 21"),
        ],
    },

    # ---------- 删除包 ----------
    "delete-ok": {
        "desc": "删除本地包成功：14 → 24",
        "steps": [
            (1, 24, {"moduleType": 1}, "远程删除本地固件包成功"),
        ],
    },
    "delete-fail": {
        "desc": "删除本地包失败：14 → 25",
        "steps": [
            (1, 25, {"moduleType": 1}, "远程删除本地固件包失败"),
        ],
    },
}


# ============================================================================
# protobuf 解析
# ============================================================================
def _read_varint(buf, i):
    """读取 protobuf varint，返回 (值, 新下标)"""
    shift = 0
    val = 0
    while True:
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, i


def decode_protobuf_header(buf):
    """解出 requestId(字段1) / commandType(字段2)"""
    i = 0
    rid = None
    ctype = None
    while i < len(buf):
        try:
            key, i = _read_varint(buf, i)
        except Exception:
            break
        fn, wt = key >> 3, key & 0x7
        if wt == 2:
            ln, i = _read_varint(buf, i)
            val = buf[i:i + ln]
            i += ln
            if fn == 1:
                rid = val.decode("utf-8", "ignore")
            elif fn == 2:
                ctype = val.decode("utf-8", "ignore")
            elif fn >= 100:
                break
        elif wt == 0:
            _, i = _read_varint(buf, i)
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            break
        if rid and ctype:
            break
    return rid, ctype


def decode_ota_param(buf, field_no):
    """解析 param_3001 / 3006 / 3007"""
    # 3001 / 3006: DeviceOTANoticeRequest
    if field_no in (301, 306):
        names = {1: "version", 2: "description", 3: "md5", 4: "url",
                 5: "packageName", 6: "moduleType", 7: "fileLength"}
        out = {}
        i = 0
        while i < len(buf):
            try:
                key, i = _read_varint(buf, i)
                fn, wt = key >> 3, key & 0x7
                if wt == 2:
                    ln, i = _read_varint(buf, i)
                    val = buf[i:i + ln]
                    i += ln
                    out[names.get(fn, "f%d" % fn)] = val.decode("utf-8", "ignore")
                elif wt == 0:
                    v, i = _read_varint(buf, i)
                    out[names.get(fn, "f%d" % fn)] = v
                elif wt == 5:
                    i += 4
                elif wt == 1:
                    i += 8
                else:
                    break
            except Exception:
                break
        return out

    # 307: DeviceUpgradePackageRequest { repeated packages = 1 }
    if field_no == 307:
        out = {"packages": []}
        i = 0
        while i < len(buf):
            try:
                key, i = _read_varint(buf, i)
                fn, wt = key >> 3, key & 0x7
                if wt == 2:
                    ln, i = _read_varint(buf, i)
                    sub = buf[i:i + ln]
                    i += ln
                    if fn == 1:
                        item = {}
                        j = 0
                        while j < len(sub):
                            k2, j = _read_varint(sub, j)
                            f2, w2 = k2 >> 3, k2 & 0x7
                            if w2 == 2:
                                l2, j = _read_varint(sub, j)
                                v2 = sub[j:j + l2]
                                j += l2
                                item[{1: "version", 2: "packageName"}.get(
                                    f2, "f%d" % f2)] = v2.decode("utf-8", "ignore")
                            elif w2 == 0:
                                v2, j = _read_varint(sub, j)
                                item[{3: "moduleType"}.get(f2, "f%d" % f2)] = v2
                            else:
                                break
                        out["packages"].append(item)
                elif wt == 0:
                    _, i = _read_varint(buf, i)
                else:
                    break
            except Exception:
                break
        return out

    return {"_rawHex": buf[:64].hex(" ")}


def decode_protobuf_full(buf):
    """完整解码 MqttRequestProtobuf，尽量把 param 也解出来"""
    result = {"requestId": None, "commandType": None, "param": None, "extra": {}}
    i = 0
    param_field = None
    param_bytes = None
    while i < len(buf):
        try:
            key, i = _read_varint(buf, i)
        except Exception:
            break
        fn, wt = key >> 3, key & 0x7
        if wt == 2:
            ln, i = _read_varint(buf, i)
            val = buf[i:i + ln]
            i += ln
            if fn == 1:
                result["requestId"] = val.decode("utf-8", "ignore")
            elif fn == 2:
                result["commandType"] = val.decode("utf-8", "ignore")
            elif fn >= 100:
                param_field = fn
                param_bytes = val
        elif wt == 0:
            v, i = _read_varint(buf, i)
            if fn < 100:
                result["extra"]["f%d" % fn] = v
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            break

    if param_bytes is not None:
        result["param"] = decode_ota_param(param_bytes, param_field)
    return result


def parse_command(raw):
    """解析下发的命令，返回 (requestId, commandType, info)"""
    # 1) protobuf 完整解码
    try:
        full = decode_protobuf_full(raw)
        if full.get("requestId"):
            return full["requestId"], full.get("commandType") or "UNKNOWN", full
    except Exception:
        pass

    # 1b) 只解头部
    try:
        rid, ctype = decode_protobuf_header(raw)
        if rid:
            return rid, ctype or "UNKNOWN", {}
    except Exception:
        pass

    # 2) JSON 兜底
    try:
        obj = json.loads(raw.decode("utf-8"))
        rid = obj.get("requestId") or obj.get("request_id")
        if rid:
            return str(rid), str(obj.get("commandType") or obj.get("command_type")), obj
    except Exception:
        pass

    return "UNKNOWN", "UNKNOWN", {}


def resolve_command_type(ota_type, status_code):
    """根据升级方式 + 状态码推导 commandType

    自动升级(0) → 3001
    手动升级(1) → 升级阶段状态用 3007，其余 3006
    """
    if ota_type == 0:
        return "3001"
    try:
        code = int(status_code) if status_code not in (None, "") else None
    except Exception:
        code = None
    if code is not None and code in UPGRADE_STAGE_STATUS:
        return "3007"
    return "3006"


# ============================================================================
# CLI 模拟终端
# ============================================================================
class MockDevice:

    def __init__(self, device_id, host=MQTT_HOST, port=MQTT_PORT,
                 username=MQTT_USERNAME, password=MQTT_PASSWORD):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client = None
        self.connected = False
        self.run_scenario = None
        self.log_sink = print
        self.last_request = None
        self.allow_interactive = True

    def _log(self, *args, **kwargs):
        if callable(self.log_sink):
            try:
                self.log_sink(" ".join(str(a) for a in args))
                return
            except Exception:
                pass
        print(*args, **kwargs)

    def _connect_client(self):
        proto = mqtt.MQTTv5 if MQTT_PROTOCOL_VERSION == 5 else (
            mqtt.MQTTv31 if MQTT_PROTOCOL_VERSION == 3 else mqtt.MQTTv311)
        try:
            return mqtt.Client(client_id=CLIENT_ID_PREFIX + self.device_id,
                               protocol=proto,
                               callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except TypeError:
            return mqtt.Client(client_id=CLIENT_ID_PREFIX + self.device_id, protocol=proto)

    def connect(self):
        client_id = CLIENT_ID_PREFIX + self.device_id
        self.client = self._connect_client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        if MQTT_USE_TLS:
            self.client.tls_set()
        if self.username:
            self.client.username_pw_set(self.username, self.password)

        self._log("[连接] tcp://%s:%d  clientId=%s" % (self.host, self.port, client_id))
        try:
            self.client.connect(self.host, self.port, keepalive=60)
        except Exception as e:
            raise ConnectionError("连接 MQTT 失败：%s" % e)

        self.client.loop_start()
        for _ in range(200):
            if self.connected:
                break
            time.sleep(0.1)
        if not self.connected:
            raise ConnectionError("MQTT 连接超时（%s:%d）" % (self.host, self.port))

    def _on_connect(self, client, userdata, flags, *args):
        rc = args[0] if args else None
        rc = getattr(rc, "value", rc)
        if rc == 0:
            self.connected = True
            self._log("[已连接] MQTT broker")
            topic = topic_command(self.device_id)
            client.subscribe(topic, qos=1)
            self._log("[已订阅] %s" % topic)
            self._register()
        else:
            self._log("[ERROR] MQTT 连接失败 rc=%s" % rc)

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False
        rc = args[-1] if args else 0
        rc = getattr(rc, "value", rc)
        if rc:
            self._log("[断开] 连接已断开 rc=%s" % rc)

    def _on_message(self, client, userdata, msg):
        raw = msg.payload
        rid, ctype, info = parse_command(raw)
        self.last_request = (rid, ctype)
        self._log("")
        self._log("=" * 74)
        self._log("[收到命令] topic=%s" % msg.topic)
        self._log("           commandType=%s (%s)" % (ctype, CMD_NAMES.get(ctype, "")))
        self._log("           requestId=%s" % rid)
        self._log("           报文字节数=%d" % len(raw))
        param = (info or {}).get("param")
        if param:
            for k, v in param.items():
                self._log("           %s = %s" % (k, v))
        self._log("=" * 74)

        if self.run_scenario:
            self._play(self.run_scenario, rid, ctype)
        elif self.allow_interactive:
            self._interactive(rid, ctype)
        else:
            self._log("[提示] 未设置自动场景")

    def _register(self, payload_json=None):
        if payload_json:
            try:
                payload = json.loads(payload_json)
            except Exception as e:
                self._log("[ERROR] 注册报文 JSON 格式错误：%s" % e)
                return False
        else:
            payload = copy.deepcopy(REGISTER_PAYLOAD)
            payload["deviceId"] = self.device_id
            if isinstance(payload.get("data"), dict):
                payload["data"]["deviceId"] = self.device_id

        if not payload.get("timestamp"):
            payload["timestamp"] = int(time.time() * 1000)
        if isinstance(payload.get("data"), dict) and not payload["data"].get("timestamp"):
            payload["data"]["timestamp"] = int(time.time() * 1000)

        body = json.dumps(payload, ensure_ascii=False)
        self.client.publish(REGISTER_TOPIC, body, qos=1)
        self._log("[注册] 已上报 deviceId=%s，%d 字节"
                  % (payload.get("deviceId", self.device_id), len(body.encode("utf-8"))))
        return True

    def send_response(self, request_id, command_type, status, extra=None, code=200, msg="success"):
        data = {}
        if status is not None:
            data["status"] = status
        if extra:
            data.update(extra)
        data["moduleType"] = 4
        payload = {
            "deviceId": self.device_id,
            "requestId": request_id,
            "commandType": command_type,
            "code": code,
            "msg": msg,
            "timestamp": int(time.time() * 1000),
            "data": data,
        }
        body = json.dumps(payload, ensure_ascii=False)
        self.client.publish(TOPIC_TASK_RESULT, body, qos=1)
        if status is None:
            self._log("  [不回响应] requestId=%s" % request_id)
        else:
            self._log("  [已上报] status=%s data=%s"
                      % (status, json.dumps(data, ensure_ascii=False)))
        return payload

    def _play(self, scenario_name, request_id, command_type):
        scenario = SCENARIOS.get(scenario_name)
        if not scenario:
            self._log("[ERROR] 未知场景：%s" % scenario_name)
            return
        self._log("[场景] %s —— %s" % (scenario_name, scenario["desc"]))
        for delay, status, extra, desc in scenario["steps"]:
            if delay:
                time.sleep(delay)
            self._log("  -> %s" % desc)
            self.send_response(request_id, resolve_command_type(1, status), status, extra)
        self._log("[场景完成] %s" % scenario_name)

    def _interactive(self, request_id, command_type):
        self._log("选择要回报的状态：")
        options = [
            (10, '升级包下载中（带进度）', {"progress": 45, "offset": 4718592}),
            (18, '下载中断（不带progress）', {}),
            (10, '续传中（带更大offset自动转26）', {"progress": 60, "offset": 6291456}),
            (15, '升级包验签失败', {"faultCode": 0}),
            (14, '下载完成等待升级', {"fileSize": 10485760}),
            (29, '下载失败（终止）', {"faultCode": 0}),
            (11, '终端升级中', {}),
            (12, '终端升级成功', {"version": "1.0.1"}),
            (13, '终端升级失败', {"faultCode": 5}),
            (24, '删除本地包成功', {"moduleType": 1}),
            (25, '删除本地包失败', {"moduleType": 1}),
            (0, '不回响应（触发超时 21/23）', None),
        ]
        for i, (st, name, _) in enumerate(options, 1):
            self._log("  %2d) %-6s %s" % (i, st if st else "--", name))
        try:
            choice = input("\n请输入编号（回车跳过）：").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not choice:
            self._log("  已跳过")
            return
        try:
            idx = int(choice) - 1
            status, name, extra = options[idx]
        except (ValueError, IndexError):
            self._log("  输入无效")
            return
        self.send_response(request_id, command_type,
                           None if status == 0 else status, extra)

    def disconnect(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self._log("[已断开]")


# ============================================================================
# CLI 入口
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="OTA 终端模拟器 —— 用 MQTT 模拟终端覆盖 17 个升级状态")
    parser.add_argument("--device", default=DEVICE_ID, help="模拟终端 deviceId")
    parser.add_argument("--host", default=MQTT_HOST, help="MQTT broker 地址")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT broker 端口")
    parser.add_argument("--username", default=MQTT_USERNAME, help="MQTT 用户名")
    parser.add_argument("--password", default=MQTT_PASSWORD, help="MQTT 密码")
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO, help="场景名，见 --list")
    parser.add_argument("--list", action="store_true", help="列出所有场景")
    args = parser.parse_args()

    if args.list:
        print("可用场景：\n")
        for name, sc in SCENARIOS.items():
            print("  %-16s %s" % (name, sc["desc"]))
        print("\n  %-16s %s" % ("interactive", "交互式手动选择状态"))
        return

    dev = MockDevice(args.device, args.host, args.port, args.username, args.password)
    dev.run_scenario = None if args.scenario == "interactive" else args.scenario

    if dev.run_scenario and dev.run_scenario not in SCENARIOS:
        print("[ERROR] 未知场景：%s（用 --list 查看）" % dev.run_scenario)
        sys.exit(1)

    try:
        dev.connect()
        print("\n[就绪] 等待平台下发命令... (Ctrl+C 退出)\n")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    finally:
        dev.disconnect()


if __name__ == "__main__":
    main()
