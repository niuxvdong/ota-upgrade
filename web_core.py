#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTA 终端模拟器 Web 工作台

启动：python web_server.py [host] [port]
默认：http://127.0.0.1:8080

功能：
  - 三栏布局：左栏配置/场景/订阅，中栏命令/状态/消息，右栏日志
  - 升级方式（自动3001 / 手动3006·3007）自动推导 commandType
  - 模块类型选择（写入 data.moduleType）
  - 场景可编辑（步骤延迟/状态码/数据），支持自定义场景
  - 手动回报填充到发送框（不直接发）
  - 全部配置持久化到 mock-config.json
"""

import copy
import json
import os
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import paho.mqtt.client as mqtt

import mock_device as m

WEB_HOST = "127.0.0.1"
WEB_PORT = 8080

# 状态码附带的数据
STATUS_EXTRA = {
    10: {"progress": 45, "offset": 4718592, "speed": 1024},
    18: {},
    26: {"progress": 60, "offset": 6291456},
    15: {"faultCode": 0},
    14: {"fileSize": 10485760, "version": "1.0.1"},
    29: {"faultCode": 0},
    11: {},
    12: {"version": "1.0.1"},
    13: {"faultCode": 5},
    24: {"moduleType": 1},
    25: {"moduleType": 1},
}

# 默认状态按钮
DEFAULT_STATUS_BUTTONS = [
    # ---- 推送/下载阶段 ----
    {"code": 5,   "name": "待稳定入网",     "cls": "st-oth",  "auto": True},
    {"code": 20,  "name": "推送下发成功",   "cls": "st-push", "auto": True},
    {"code": 21,  "name": "推送接收失败",   "cls": "st-fail", "auto": True},
    {"code": 10,  "name": "升级包下载中",   "cls": "st-push", "auto": False},
    {"code": 18,  "name": "下载中断",       "cls": "st-push", "auto": False},
    {"code": 26,  "name": "续传中",         "cls": "st-push", "auto": True},
    {"code": 15,  "name": "验签失败",       "cls": "st-fail", "auto": False},
    {"code": 14,  "name": "下载完成待升级", "cls": "st-push", "auto": False},
    {"code": 29,  "name": "下载失败",       "cls": "st-fail", "auto": False},
    {"code": -10, "name": "升级包已失效",   "cls": "st-fail", "auto": True},
    # ---- 升级阶段 ----
    {"code": 22,  "name": "升级下发成功",   "cls": "st-up",   "auto": True},
    {"code": 23,  "name": "升级接收失败",   "cls": "st-fail", "auto": True},
    {"code": 11,  "name": "终端升级中",     "cls": "st-up",   "auto": False},
    {"code": 12,  "name": "升级成功",       "cls": "st-up",   "auto": False},
    {"code": 13,  "name": "升级失败",       "cls": "st-fail", "auto": False},
    # ---- 删包 ----
    {"code": 24,  "name": "删除包成功",     "cls": "st-oth",  "auto": False},
    {"code": 25,  "name": "删除包失败",     "cls": "st-oth",  "auto": False},
    # ---- 特殊 ----
    {"code": 0,   "name": "不回(触发超时)", "cls": "st-fail", "auto": False},
]


def mqtt_protocol():
    """按配置返回 paho 协议常量"""
    v = getattr(m, "MQTT_PROTOCOL_VERSION", 4)
    if v == 5:
        return mqtt.MQTTv5
    if v == 3:
        return mqtt.MQTTv31
    return mqtt.MQTTv311


# ============================================================================
# 终端管理器
# ============================================================================
class DeviceManager:

    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "mock-config.json")

    def __init__(self, device_id=None):
        self.device_id = device_id or m.DEVICE_ID
        # ★ RLock：status()/connect() 等在持锁时会调用同样加锁的方法
        self.lock = threading.RLock()
        self._file_lock = threading.Lock()
        self.client = None
        self.connected = False
        self.logs = []
        self.max_logs = 400
        self.messages = []
        self.max_messages = 600
        self.msg_seq = 0
        self.subscriptions = []
        self.pending_sub = {}
        self.config = {}
        self.auto_scenario = None
        self.last_command = None
        self.register_payload = None
        self.register_template = None
        self.saved_conn = None
        self.saved_send = None
        self.scenario_overrides = {}
        self.custom_scenarios = {}
        self.status_buttons = None
        # 升级方式：0=自动升级(3001) 1=下载后手动升级(3006/3007)
        self.ota_type = 1
        # 模块类型（FirmwareModuleTypeEnum）默认 4=终端套件
        self.module_type = 4
        # 只看升级命令（内存态，前端存 localStorage）
        self.only_ota_cmd = True
        self._heartbeat_thread = None
        self._heartbeat_stop = False

    # ---------------- 日志 ----------------
    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        with self.lock:
            self.logs.append("[%s] %s" % (ts, msg))
            if len(self.logs) > self.max_logs:
                self.logs = self.logs[-self.max_logs:]

    def get_logs(self, since=0):
        with self.lock:
            return self.logs[since:], len(self.logs)

    # ---------------- 消息 ----------------
    def _add_message(self, direction, topic, payload, qos=0, parsed=None, hexdump=None):
        with self.lock:
            self.msg_seq += 1
            if parsed is None:
                try:
                    parsed = json.loads(payload)
                except Exception:
                    parsed = None
            if hexdump is None and parsed is None:
                try:
                    hexdump = payload.encode("utf-8", errors="replace")[:96].hex(" ")
                except Exception:
                    hexdump = None
            self.messages.append({
                "seq": self.msg_seq, "direction": direction, "topic": topic,
                "payload": payload[:4000], "json": parsed, "hex": hexdump,
                "ts": time.strftime("%H:%M:%S"), "qos": qos,
            })
            if len(self.messages) > self.max_messages:
                self.messages = self.messages[-self.max_messages:]

    def get_messages(self, since=0, topic_filter=None):
        with self.lock:
            out = [x for x in self.messages
                   if x["seq"] > since and (not topic_filter or topic_filter in x["topic"])]
            return out, self.msg_seq

    def clear_messages(self):
        with self.lock:
            self.messages = []
            self.msg_seq = 0
        return True, "已清空消息"

    # ---------------- 配置持久化 ----------------
    def _load_config_file(self):
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            self.log("[WARN] 配置文件读取失败：%s" % e)
        return {}

    def _write_file_unlocked(self, data):
        """实际写文件（调用方必须持有 _file_lock）"""
        tmp = "%s.%s.tmp" % (self.CONFIG_FILE, uuid.uuid4().hex[:8])
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            last_err = None
            for attempt in range(5):
                try:
                    os.replace(tmp, self.CONFIG_FILE)
                    return True
                except OSError as e:
                    last_err = e
                    time.sleep(0.05 * (attempt + 1))
            self.log("[WARN] 配置文件替换失败（重试5次）：%s" % last_err)
            return False
        except Exception as e:
            self.log("[WARN] 配置文件保存失败：%s" % e)
            return False
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _save_config_file(self, data):
        with self._file_lock:
            return self._write_file_unlocked(data)

    def _persist(self, key, value):
        """把某个 key 合并写入配置文件（整个读-改-写在锁内）"""
        with self._file_lock:
            data = self._load_config_file()
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
            return self._write_file_unlocked(data)

    def load_persisted(self):
        """启动时加载全部持久化内容"""
        data = self._load_config_file()
        if not data:
            return

        # 1) 场景覆盖
        sc = data.get("scenarios") or {}
        if isinstance(sc, dict) and sc:
            with self.lock:
                self.scenario_overrides = sc
            self.log("[配置] 已加载自定义场景步骤 %d 个" % len(sc))

        # 2) 状态按钮
        st = data.get("statuses")
        if isinstance(st, list) and st:
            with self.lock:
                self.status_buttons = st
            self.log("[配置] 已加载自定义状态按钮 %d 个" % len(st))

        # 3) 连接配置
        conn = data.get("conn")
        if isinstance(conn, dict) and conn:
            with self.lock:
                self.saved_conn = conn
            self.log("[配置] 已加载连接配置：%s:%s"
                     % (conn.get("host", ""), conn.get("port", "")))

        # 4) 发送区
        send = data.get("sendBox")
        if isinstance(send, dict) and send:
            with self.lock:
                self.saved_send = send
            self.log("[配置] 已加载发送区配置")

        # 5) 自定义场景
        cs = data.get("customScenarios")
        if isinstance(cs, dict) and cs:
            with self.lock:
                self.custom_scenarios = cs
            self.log("[配置] 已加载自定义场景 %d 个：%s"
                     % (len(cs), ", ".join(cs.keys())))

        # 6) 注册报文模板
        rp = data.get("registerPayload")
        if isinstance(rp, dict) and rp:
            with self.lock:
                self.register_template = rp
                self.register_payload = json.dumps(rp, ensure_ascii=False, indent=2)
            self.log("[配置] 已加载自定义注册报文模板")

        # 7) 升级方式
        ot = data.get("otaType")
        if ot is not None:
            try:
                with self.lock:
                    self.ota_type = int(ot)
                self.log("[配置] 已加载升级方式=%s"
                         % ("自动升级" if int(ot) == 0 else "下载后手动升级"))
            except Exception:
                pass

        # 8) 模块类型
        mt = data.get("moduleType")
        if mt is not None:
            try:
                with self.lock:
                    self.module_type = int(mt)
                self.log("[配置] 已加载模块类型=%s" % mt)
            except Exception:
                pass

    # ---------------- 升级方式 / commandType ----------------
    def save_ota_type(self, ota_type):
        try:
            v = int(ota_type)
        except Exception:
            return False, "升级方式取值错误"
        if v not in (0, 1):
            return False, "升级方式只能是 0（自动）或 1（手动）"
        with self.lock:
            self.ota_type = v
        self._persist("otaType", v)
        name = "自动升级" if v == 0 else "下载后手动升级"
        self.log("[配置] 升级方式已设为 %s" % name)
        return True, "升级方式已保存：%s" % name

    def save_module_type(self, module_type):
        try:
            v = int(module_type)
        except Exception:
            return False, "模块类型取值错误"
        if v not in (1, 2, 3, 4, 5, 6, 7, 101, 102, 103, 104, 105, 106, 107):
            return False, "模块类型取值非法"
        with self.lock:
            self.module_type = v
        self._persist("moduleType", v)
        self.log("[配置] 模块类型已设为 %s" % v)
        return True, "模块类型已保存：%s" % v

    def resolve_command_type(self, status_code):
        """根据升级方式 + 状态码推导 commandType"""
        with self.lock:
            ot = self.ota_type
        return m.resolve_command_type(ot, status_code)

    # ---------------- 连接 ----------------
    def _probe_tcp(self, host, port, timeout=8):
        """TCP 连通性探测，返回 None 表示通"""
        import socket
        L = chr(10)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return None
        except socket.timeout:
            return ("步骤1/3 TCP 连接超时（%s:%d，等待 %d 秒）" % (host, port, timeout)) + L + L + (
                    "该端口从本机不可达，请先确认：" + L +
                    "  1. ping %s 是否通" % host + L +
                    "  2. telnet %s %d 是否通" % (host, port) + L +
                    "  3. 是否需要 VPN / 防火墙放行")
        except ConnectionRefusedError:
            return ("步骤1/3 TCP 连接被拒绝（%s:%d）" % (host, port)) + L + (
                    "端口未监听，请确认 broker 是否启动")
        except OSError as e:
            return ("步骤1/3 TCP 连接失败（%s:%d）：%s" % (host, port, e)) + L + (
                    "请检查网络连通性、防火墙、VPN")
        except Exception as e:
            return "步骤1/3 TCP 探测异常：%s" % e
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def connect(self, host, port, device_id, username="", password="",
                register_payload=None, subscribe_topics=None, protocol_version=None):
        # ★ 实时校验真实连接状态（不能用缓存标志，否则心跳未更新时会误判）
        with self.lock:
            old_client = self.client
            old_flag = self.connected
        really_alive = False
        if old_client is not None:
            try:
                really_alive = bool(old_client.is_connected())
            except Exception:
                really_alive = False

        if really_alive:
            return False, "已连接，请先断开"

        # 标志位说已连接但实际已断 → 清理残留连接
        if old_flag or old_client is not None:
            self.log("[连接] 检测到残留连接（实际已断开），自动清理")
            try:
                if old_client is not None:
                    try:
                        old_client.loop_stop()
                    except Exception:
                        pass
                    try:
                        old_client.disconnect()
                    except Exception:
                        pass
            except Exception:
                pass
            with self.lock:
                self.client = None
                self.connected = False

        prefix = getattr(m, "CLIENT_ID_PREFIX", "")
        client_id = prefix + device_id

        # 步骤1：TCP 探测
        self.log("[连接] 步骤1/3 探测 TCP %s:%d ..." % (host, port))
        tcp_err = self._probe_tcp(host, port, timeout=8)
        if tcp_err:
            return False, tcp_err
        self.log("[连接] 步骤1/3 TCP 可达")

        # 步骤2：MQTT 握手
        self.log("[连接] 步骤2/3 MQTT 握手 ...")
        ver = protocol_version if protocol_version is not None else getattr(m, "MQTT_PROTOCOL_VERSION", 4)
        proto = mqtt.MQTTv5 if ver == 5 else (mqtt.MQTTv31 if ver == 3 else mqtt.MQTTv311)
        self.log("[连接] 协议版本=MQTT %s  clientId=%s  (前缀=%s)"
                 % (ver, client_id, repr(prefix)))

        try:
            client = mqtt.Client(client_id=client_id, protocol=proto,
                                 callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except TypeError:
            client = mqtt.Client(client_id=client_id, protocol=proto)
        except Exception:
            client = mqtt.Client(client_id=client_id)

        if username:
            client.username_pw_set(username, password)

        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.on_subscribe = self._on_subscribe

        try:
            # keepalive 15 秒：网络断开后最多 ~15s 感知（默认 60s 太久）
            client.connect(host, port, keepalive=15)
        except Exception as e:
            return False, ("MQTT 握手失败：%s" % e) + chr(10) + (
                           "排查方向：" + chr(10) +
                           "  1. broker 是否要求 TLS" + chr(10) +
                           "  2. broker 是否要求用户名密码" + chr(10) +
                           "  3. 该端口是否真的是 MQTT 服务")

        client.loop_start()
        for _ in range(200):
            if self.connected:
                break
            time.sleep(0.1)
        if not self.connected:
            try:
                client.loop_stop()
            except Exception:
                pass
            L = chr(10)
            return False, ("步骤2/3 MQTT 握手超时（%s:%d）" % (host, port)) + L + L + (
                           "TCP 能连上但 broker 没回 CONNACK，常见原因：" + L +
                           "  1. broker 要求 TLS 加密" + L +
                           "  2. broker 要求用户名密码" + L +
                           "  3. 中间有代理只做 TCP 转发" + L +
                           "  4. clientId 规则不符")

        self.log("[连接] 步骤2/3 MQTT 握手成功")

        with self.lock:
            self.client = client
            self.config = {"host": host, "port": port, "deviceId": device_id,
                           "clientId": client_id, "username": username}
            if subscribe_topics is None:
                subscribe_topics = [m.TOPIC_COMMAND_TEMPLATE % device_id]
            self.subscriptions = []

        for t in subscribe_topics:
            self.subscribe(t)

        self.send_register(register_payload)
        return True, "已连接 %s:%d（%s）" % (host, port, device_id)

    def _heartbeat_loop(self):
        """主动心跳：每 5 秒检查连接，断连则更新状态并记日志"""
        import socket
        last_alive = True
        while not self._heartbeat_stop:
            time.sleep(5)
            if self._heartbeat_stop:
                break
            with self.lock:
                client = self.client
                host = self.config.get("host")
                port = self.config.get("port")
                was_connected = self.connected
            if client is None:
                # 没有 client 说明未连接，继续循环等待重连
                if was_connected:
                    with self.lock:
                        self.connected = False
                    self.log("[心跳] 连接不存在，已置为未连接")
                continue

            alive = False
            # 1) paho 自身状态
            try:
                alive = bool(client.is_connected())
            except Exception:
                alive = False

            # 2) paho 说连着，但可能已死（网络断了没人通知）→ TCP 探一下
            if alive and host and port:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    sock.connect((host, int(port)))
                    sock.close()
                except Exception:
                    alive = False

            if alive != was_connected:
                with self.lock:
                    self.connected = alive
                if alive:
                    self.log("[心跳] 连接已恢复")
                else:
                    self.log("[心跳] 检测到连接已断开（TCP 不可达或 MQTT 已断）")
            elif not alive and last_alive:
                self.log("[心跳] 连接异常，正在重试检测...")
            last_alive = alive

    def _start_heartbeat(self):
        """启动心跳线程"""
        self._heartbeat_stop = False
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _on_connect(self, client, userdata, flags, *args):
        rc = args[0] if args else None
        code = getattr(rc, "value", rc)
        if code == 0:
            self.connected = True
            self.log("[已连接] MQTT broker")
            self._start_heartbeat()
        else:
            self.log("[ERROR] 连接被拒 rc=%s" % code)

    def _on_disconnect(self, client, userdata, *args):
        with self.lock:
            self.connected = False
        rc = args[-1] if args else 0
        code = getattr(rc, "value", rc)
        reasons = {
            0: "正常断开",
            1: "协议错误",
            2: "clientId 被占用",
            3: "broker 不可用",
            4: "用户名密码错误",
            5: "未授权",
        }
        reason = reasons.get(code, "rc=%s" % code)
        self.log("[断开] 连接已断开：%s" % reason)

    def _on_subscribe(self, client, userdata, mid, *args):
        with self.lock:
            topic = self.pending_sub.pop(mid, None)
        if not topic:
            return
        granted = args[0] if args else None
        codes = list(granted) if isinstance(granted, (tuple, list)) else (
            [granted] if granted is not None else [])
        failed = False
        for c in codes:
            v = getattr(c, "value", c)
            if v == 0x80 or (isinstance(v, int) and v >= 128):
                failed = True
        if failed:
            self.log("[订阅失败] %s 被服务端拒绝（SUBACK=0x80）" % topic)
            self.log("[订阅失败] 常见原因：topic 不在白名单，或 clientId 与 topic 中 deviceId 不一致")
            with self.lock:
                if topic in self.subscriptions:
                    self.subscriptions.remove(topic)
        else:
            with self.lock:
                if topic not in self.subscriptions:
                    self.subscriptions.append(topic)
            self.log("[订阅成功] %s" % topic)

    def _on_message(self, client, userdata, msg):
        raw = msg.payload
        qos = getattr(msg, "qos", 0)

        parsed = None
        try:
            rid, ctype, info = m.parse_command(raw)
            if rid and rid != "UNKNOWN":
                parsed = {"requestId": rid, "commandType": ctype,
                          "param": (info or {}).get("param")}
        except Exception:
            parsed = None

        if parsed:
            self._add_message("in", msg.topic,
                              json.dumps(parsed, ensure_ascii=False, indent=2),
                              qos, parsed=parsed)
            self.log("[收到] topic=%s  %d 字节  commandType=%s"
                     % (msg.topic, len(raw), parsed.get("commandType")))
            if parsed.get("param"):
                for k, v in parsed["param"].items():
                    self.log("[收到]   %s = %s" % (k, v))
        else:
            try:
                text = raw.decode("utf-8")
                self._add_message("in", msg.topic, text, qos)
            except Exception:
                self._add_message("in", msg.topic, repr(raw), qos,
                                  hexdump=raw[:96].hex(" "))
            self.log("[收到] topic=%s  %d 字节（未能解析结构）" % (msg.topic, len(raw)))

        # 记录最近命令
        try:
            rid, ctype, _ = m.parse_command(raw)
            with self.lock:
                self.last_command = {
                    "requestId": rid, "commandType": ctype,
                    "cmdName": m.CMD_NAMES.get(ctype, ""),
                    "topic": msg.topic, "bytes": len(raw),
                    "hex": raw[:64].hex(" "),
                    "ts": time.strftime("%H:%M:%S"),
                }
        except Exception:
            pass

        # 自动场景
        scenario = self.auto_scenario
        if scenario:
            threading.Thread(target=self._run_scenario, args=(scenario,),
                             daemon=True).start()

    # ---------------- 订阅 ----------------
    def subscribe(self, topic):
        if not topic:
            return False, "topic 不能为空"
        with self.lock:
            client = self.client
        if not client:
            return False, "未连接"
        try:
            result, mid = client.subscribe(topic, qos=1)
            if result != 0:
                return False, "订阅请求发送失败：%s" % result
            with self.lock:
                self.pending_sub[mid] = topic
            self.log("[订阅] 已发起 %s（packetId=%s）" % (topic, mid))
            return True, "已发起订阅 %s" % topic
        except Exception as e:
            return False, "订阅异常：%s" % e

    def unsubscribe(self, topic):
        with self.lock:
            client = self.client
            if topic in self.subscriptions:
                self.subscriptions.remove(topic)
        if client:
            try:
                client.unsubscribe(topic)
                self.log("[取消订阅] %s" % topic)
            except Exception:
                pass
        return True, "已取消订阅 %s" % topic

    # ---------------- 发布 ----------------
    def publish(self, topic, payload, qos=0):
        with self.lock:
            client = self.client
        if not client or not self.connected:
            return False, "未连接"
        if not topic:
            return False, "topic 不能为空"
        try:
            client.publish(topic, payload, qos=qos)
        except Exception as e:
            return False, "发送失败：%s" % e
        self._add_message("out", topic, payload, qos)
        self.log("[发送] topic=%s  %d 字节" % (topic, len(payload.encode("utf-8"))))
        return True, "已发送到 %s" % topic

    # ---------------- 注册 ----------------
    def send_register(self, payload_json=None, use_template=True):
        """发送注册报文。

        优先级：
          1. 显式传入的 payload_json（前端点「发送并保存」时传）
          2. 已保存的自定义模板 register_template（★ 关键：连接时应该用这个）
          3. 内置默认 REGISTER_PAYLOAD
        """
        if payload_json:
            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
            except Exception as e:
                return False, "注册报文 JSON 错误：%s" % e
            payload = copy.deepcopy(payload)
        else:
            # ★ 优先用自定义模板，其次才用内置默认
            with self.lock:
                tpl = self.register_template
            if use_template and isinstance(tpl, dict) and tpl:
                payload = copy.deepcopy(tpl)
                self.log("[注册] 使用自定义注册报文模板")
            else:
                payload = copy.deepcopy(m.REGISTER_PAYLOAD)
                self.log("[注册] 使用内置默认注册报文")
            # 覆盖 deviceId / deviceType 为当前终端
            dev = self.config.get("deviceId") or self.device_id or m.DEVICE_ID
            payload["deviceId"] = dev
            if isinstance(payload.get("data"), dict):
                payload["data"]["deviceId"] = dev
        if not payload.get("timestamp"):
            payload["timestamp"] = int(time.time() * 1000)
        if isinstance(payload.get("data"), dict) and not payload["data"].get("timestamp"):
            payload["data"]["timestamp"] = int(time.time() * 1000)
        body = json.dumps(payload, ensure_ascii=False)
        with self.lock:
            self.register_payload = body
        ok, msg = self.publish(m.REGISTER_TOPIC, body, qos=1)
        if ok:
            self.log("[注册] 已上报 deviceId=%s" % payload.get("deviceId"))
            return True, "注册报文已上报"
        return False, msg

    def save_register_template(self, payload):
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception as e:
                return False, "注册报文 JSON 格式错误：%s" % e
        if not isinstance(payload, dict):
            return False, "注册报文必须是 JSON 对象"
        with self.lock:
            self.register_template = payload
            self.register_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        self._persist("registerPayload", payload)
        self.log("[注册] 已保存注册报文模板（已持久化）")
        return True, "注册报文模板已保存并持久化"

    def reset_register_template(self):
        with self.lock:
            self.register_template = None
            self.register_payload = None
        self._persist("registerPayload", None)
        self.log("[注册] 已恢复默认注册报文模板")
        return True, "已恢复默认注册报文模板"

    def get_register_template(self):
        with self.lock:
            if self.register_template:
                return copy.deepcopy(self.register_template)
        d = copy.deepcopy(m.REGISTER_PAYLOAD)
        d["deviceId"] = m.DEVICE_ID
        if isinstance(d.get("data"), dict):
            d["data"]["deviceId"] = m.DEVICE_ID
            d["data"]["deviceType"] = m.DEVICE_TYPE
        return d

    # ---------------- 状态按钮 ----------------
    def get_status_buttons(self):
        with self.lock:
            if self.status_buttons:
                return [dict(x) for x in self.status_buttons]
        return [dict(x) for x in DEFAULT_STATUS_BUTTONS]

    def save_status_buttons(self, buttons):
        if not isinstance(buttons, list) or not buttons:
            return False, "按钮列表不能为空"
        clean = []
        for i, b in enumerate(buttons, 1):
            try:
                code = int(b.get("code", 0))
            except Exception:
                return False, "第%d个按钮的 code 不是整数" % i
            name = (b.get("name") or "").strip()
            if not name:
                return False, "第%d个按钮的名称不能为空" % i
            cls = b.get("cls") or "st-oth"
            if cls not in ("st-push", "st-up", "st-oth", "st-fail"):
                cls = "st-oth"
            clean.append({"code": code, "name": name, "cls": cls,
                          "auto": bool(b.get("auto"))})
        with self.lock:
            self.status_buttons = clean
        self._persist("statuses", clean)
        self.log("[状态] 已更新状态按钮 %d 个" % len(clean))
        return True, "已保存 %d 个按钮（已持久化）" % len(clean)

    def reset_status_buttons(self):
        with self.lock:
            self.status_buttons = None
        self._persist("statuses", None)
        self.log("[状态] 已恢复默认状态按钮")
        return True, "已恢复默认状态按钮"

    # ---------------- 场景 ----------------
    def _normalize_steps(self, steps):
        if not isinstance(steps, list) or not steps:
            return None
        clean = []
        for i, st in enumerate(steps, 1):
            try:
                delay = float(st.get("delay", 10) or 0)
            except Exception:
                return None
            status = st.get("status")
            if status in ("", None):
                status = None
            else:
                try:
                    status = int(status)
                except Exception:
                    return None
            data = st.get("data") or {}
            if not isinstance(data, dict):
                return None
            clean.append({"delay": delay, "status": status, "data": data,
                          "desc": st.get("desc") or ("步骤%d" % i)})
        return clean

    def get_scenario_steps(self, name):
        """优先级：运行时覆盖 > 自定义场景 > 内置场景"""
        with self.lock:
            override = self.scenario_overrides.get(name)
            custom = self.custom_scenarios.get(name)
        if override is not None:
            return [dict(x) for x in override]
        if custom is not None:
            return [dict(x) for x in (custom.get("steps") or [])]
        sc = m.SCENARIOS.get(name)
        if not sc:
            return None
        return [{"delay": d, "status": st, "data": dict(ex or {}), "desc": desc}
                for (d, st, ex, desc) in sc["steps"]]

    def save_scenario_steps(self, name, steps):
        if not name:
            return False, "场景名不能为空"
        clean = self._normalize_steps(steps)
        if clean is None:
            return False, "步骤格式错误"
        with self.lock:
            is_custom = name in self.custom_scenarios
            if is_custom:
                self.custom_scenarios[name]["steps"] = clean
                cs_snapshot = dict(self.custom_scenarios)
            else:
                self.scenario_overrides[name] = clean
                ov_snapshot = dict(self.scenario_overrides)
        if is_custom:
            self._persist("customScenarios", cs_snapshot)
        else:
            self._persist("scenarios", ov_snapshot)
        self.log("[场景] 已更新 %s 的步骤（%d 步）" % (name, len(clean)))
        return True, "已保存 %d 步（已持久化）" % len(clean)

    def reset_scenario_steps(self, name):
        with self.lock:
            self.scenario_overrides.pop(name, None)
            snapshot = dict(self.scenario_overrides)
        self._persist("scenarios", snapshot if snapshot else None)
        return True, "已恢复默认步骤"

    def list_custom_scenarios(self):
        with self.lock:
            return dict(self.custom_scenarios)

    def create_custom_scenario(self, name, desc="", steps=None):
        name = (name or "").strip()
        if not name:
            return False, "场景名不能为空"
        if not all(c.isascii() and (c.isalnum() or c in "_-") for c in name):
            return False, "场景名只能包含英文字母、数字、下划线、横线"
        if name in m.SCENARIOS:
            return False, "场景名与内置场景冲突，请换一个"
        with self.lock:
            if name in self.custom_scenarios:
                return False, "场景已存在"
        clean = self._normalize_steps(steps or [{"delay": 1, "status": 14,
                                                 "data": {}, "desc": "步骤1"}])
        if clean is None:
            return False, "步骤格式错误"
        with self.lock:
            self.custom_scenarios[name] = {"desc": desc or "自定义场景", "steps": clean}
            snapshot = dict(self.custom_scenarios)
        self._persist("customScenarios", snapshot)
        self.log("[场景] 已创建自定义场景 %s（%d 步）" % (name, len(clean)))
        return True, "已创建场景 %s" % name

    def delete_custom_scenario(self, name):
        with self.lock:
            if name not in self.custom_scenarios:
                return False, "不是自定义场景，无法删除"
            self.custom_scenarios.pop(name, None)
            snapshot = dict(self.custom_scenarios) if self.custom_scenarios else None
            self.scenario_overrides.pop(name, None)
            ov = dict(self.scenario_overrides) if self.scenario_overrides else None
        self._persist("customScenarios", snapshot)
        self._persist("scenarios", ov)
        self.log("[场景] 已删除自定义场景 %s" % name)
        return True, "已删除场景 %s" % name

    def set_auto_scenario(self, scenario):
        # ★ 未连接不允许切换场景
        with self.lock:
            connected = self.connected
        if not connected:
            self.log("[场景] 切换被拒绝：未连接 MQTT")
            return False, "未连接，无法切换场景。请先点击【连接】"

        with self.lock:
            self.auto_scenario = scenario or None
            custom = self.custom_scenarios.get(scenario) if scenario else None
        if not scenario:
            self.log("[场景] 已切换为【仅监听】—— 收到命令只记录，不自动回复")
            return True, "已切换为仅监听（不自动回复）"
        if custom:
            desc = custom.get("desc") or "自定义场景"
        else:
            desc = m.SCENARIOS.get(scenario, {}).get("desc", scenario)
        self.log("[场景] 已选中【%s】—— %s" % (scenario, desc))
        self.log("[场景] 收到平台命令后将按步骤自动回报")
        return True, "自动场景：%s（收到命令后自动执行）" % desc

    def run_scenario_now(self, scenario):
        """立即执行场景（不等平台下发命令）"""
        if not self.connected:
            return False, "未连接，无法执行"
        steps = self.get_scenario_steps(scenario)
        if not steps:
            return False, "场景不存在或没有步骤"
        lc = self.last_command
        if not lc:
            lc = {"requestId": "MANUAL-%d" % int(time.time() * 1000),
                  "commandType": "3006"}
            self.log("[场景] 未收到过命令，使用占位 requestId 直接下发")
        threading.Thread(target=self._run_scenario, args=(scenario, lc),
                         daemon=True).start()
        return True, "已开始执行场景 %s（%d 步）" % (scenario, len(steps))

    def _run_scenario(self, scenario, override_cmd=None):
        steps = self.get_scenario_steps(scenario)
        if not steps:
            self.log("[场景] %s 不存在或没有步骤" % scenario)
            return
        lc = override_cmd or self.last_command
        if not lc:
            self.log("[场景] 还没有收到过命令，无法执行 %s" % scenario)
            return
        self.log("=" * 60)
        self.log("[场景] ▶ 开始执行【%s】，共 %d 步" % (scenario, len(steps)))
        self.log("[场景] 升级方式：%s" % ("自动升级(3001)" if self.ota_type == 0
                                          else "下载后手动升级(3006/3007)"))
        self.log("[场景] 模块类型：%s" % self.module_type)
        self.log("=" * 60)
        for idx, st in enumerate(steps, 1):
            delay = st.get("delay", 1)
            status = st.get("status")
            extra = st.get("data") or {}
            desc = st.get("desc", "")
            self.log("[场景] ── 第 %d/%d 步：%s ──" % (idx, len(steps), desc))
            if delay:
                self.log("[场景]    等待 %s 秒..." % delay)
                time.sleep(float(delay))
            data = {}
            if status is not None:
                data["status"] = status
            if extra:
                data.update(extra)
            with self.lock:
                mod = self.module_type
            data["moduleType"] = mod
            cmd_type = self.resolve_command_type(status)
            payload = {"deviceId": self.config.get("deviceId", ""),
                       "requestId": lc["requestId"], "commandType": cmd_type,
                       "code": 200, "msg": "success",
                       "timestamp": int(time.time() * 1000), "data": data}
            body = json.dumps(payload, ensure_ascii=False)
            topic = m.TOPIC_TASK_RESULT
            cmd_name = m.STATUS_DESC.get(status, "不回响应")
            self.log("[场景]    状态码=%s(%s)  commandType=%s" % (status, cmd_name, cmd_type))
            self.log("[场景]    topic=%s" % topic)
            self.log("[场景]    报文: %s" % body)
            ok, msg = self.publish(topic, body, qos=1)
            if ok:
                self.log("[场景]    ✓ 第 %d 步下发成功" % idx)
            else:
                self.log("[场景]    ✗ 第 %d 步下发失败：%s" % (idx, msg))
        self.log("=" * 60)
        self.log("[场景] ■ 场景【%s】执行完成" % scenario)
        self.log("=" * 60)

    # ---------------- 手动回报 ----------------
    def build_status_payload(self, status_code):
        """构造某个状态的应答报文（供填充到发送框）"""
        name = m.STATUS_DESC.get(status_code, "")
        self.log("[回报] 正在生成 status=%s（%s）的应答报文..." % (status_code, name))
        lc = self.last_command or {}
        cmd_type = self.resolve_command_type(status_code)
        with self.lock:
            mod = self.module_type
        data = {}
        if status_code:
            data["status"] = status_code
            data.update(STATUS_EXTRA.get(status_code, {}))
        data["moduleType"] = mod
        return {
            "deviceId": self.config.get("deviceId") or m.DEVICE_ID,
            "requestId": lc.get("requestId") or "<填最近收到的 requestId>",
            "commandType": cmd_type,
            "code": 200, "msg": "success",
            "timestamp": int(time.time() * 1000),
            "data": data,
        }

    def send_status(self, status_code):
        if not self.connected:
            return False, "未连接"
        lc = self.last_command
        if not lc:
            return False, "还没收到过任何命令，无法回响应"
        payload = self.build_status_payload(status_code)
        topic = m.TOPIC_TASK_RESULT
        ok, msg = self.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)
        if ok:
            self.log("[回报] 已发送 topic=%s status=%s"
                     % (topic, status_code if status_code else "不回"))
            return True, "已上报 status=%s" % (status_code if status_code else "不回")
        return False, msg

    # ---------------- 连接配置持久化 ----------------
    def save_conn_config(self, cfg):
        if not isinstance(cfg, dict):
            return False, "配置格式错误"
        keep = {}
        for k in ("host", "port", "deviceId", "deviceType",
                  "username", "password", "protocolVersion"):
            if k in cfg and cfg[k] is not None:
                keep[k] = cfg[k]
        if not keep:
            return False, "没有可保存的字段"
        with self.lock:
            self.saved_conn = keep
        self._persist("conn", keep)
        return True, "连接配置已保存"

    def save_send_box(self, box):
        if not isinstance(box, dict):
            return False, "格式错误"
        keep = {}
        if box.get("topic"):
            keep["topic"] = str(box["topic"])
        if box.get("payload") is not None:
            keep["payload"] = str(box["payload"])
        if not keep:
            return False, "没有可保存的内容"
        with self.lock:
            self.saved_send = keep
        self._persist("sendBox", keep)
        return True, "发送区已保存"

    # ---------------- 连接状态 ----------------
    def disconnect(self):
        """断开连接（幂等：已断开也返回成功）"""
        with self.lock:
            client = self.client
            was_connected = self.connected
            self.client = None
            self.connected = False
        # 清理订阅与待确认
        with self.lock:
            self.subscriptions = []
            self.pending_sub = {}
        if client is not None:
            try:
                client.loop_stop()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass
        if was_connected or client is not None:
            self.log("[断开] 已断开连接")
        else:
            self.log("[断开] 当前本就未连接（幂等返回）")
        # 心跳线程不停止，继续以 5s 间隔检测（重连后可复用）
        return True, "已断开"

    def status(self):
        with self.lock:
            client = self.client
            flag = self.connected
        # 以 paho 的 is_connected() 为准
        if client is not None:
            try:
                alive = client.is_connected()
            except Exception:
                alive = False
            if alive != flag:
                with self.lock:
                    self.connected = alive
                flag = alive
        with self.lock:
            return {
                "connected": flag,
                "config": self.config,
                "subscriptions": self.subscriptions,
                "autoScenario": self.auto_scenario,
                "lastCommand": self.last_command,
                "registerPayload": self.register_payload,
                "messageCount": len(self.messages),
                "otaType": self.ota_type,
                "moduleType": self.module_type,
                "onlyOtaCmd": self.only_ota_cmd,
            }

    def diagnose(self, host, port):
        import socket
        L = chr(10)
        lines = ["目标: %s:%d" % (host, port)]
        try:
            ip = socket.gethostbyname(host)
            lines.append("[1/2] 解析成功: %s -> %s" % (host, ip))
        except Exception as e:
            lines.append("[1/2] 域名解析失败: %s" % e)
            return False, L.join(lines)
        ok_count = 0
        for _ in range(3):
            if self._probe_tcp(host, port, timeout=5) is None:
                ok_count += 1
        if ok_count == 0:
            lines.append("[2/2] TCP 不可达（3 次全失败）")
            lines.append("  -> 端口不通，请检查网络/VPN/防火墙")
            return False, L.join(lines)
        lines.append("[2/2] TCP 可达（3 次中成功 %d 次）" % ok_count)
        return True, L.join(lines)


# ============================================================================
# 主管理器实例（单终端默认使用）
# ============================================================================
MANAGER = DeviceManager()
MANAGER.load_persisted()


# ============================================================================
# 多终端管理器
# ============================================================================
class MultiDeviceManager:
    """管理多个终端连接。

    - enabled=False 或 deviceIds 只有 1 个 → 单终端（复用原 MANAGER）
    - 多终端 → 每个 deviceId 一个 DeviceManager 实例
    - 所有操作（连接/断开/场景/回报/发送）广播到所有终端
    """

    def __init__(self):
        # ★ 用 RLock：_get_or_create / sync_* 会在持锁时再次进入（记录日志等）
        self.lock = threading.RLock()
        self.multi_mode = False          # 是否启用多终端
        self.device_ids = [m.DEVICE_ID]  # 终端列表
        # ★ 顶部输入框的 deviceId（由前端同步，不依赖连接后的 config）
        self.top_device_id = m.DEVICE_ID
        self.managers = {}               # deviceId -> DeviceManager
        self._agg_log = []               # 聚合日志（带 deviceId 前缀）
        self.max_agg_logs = 600

    # ---------- 初始化 ----------
    def _get_or_create(self, device_id):
        # 快路径：已存在直接返回
        with self.lock:
            mgr = self.managers.get(device_id)
        if mgr is not None:
            return mgr

        # 慢路径：在锁外创建（避免 super.__init__ / 字段赋值期间的重入）
        mgr = DeviceManager(device_id)
        # 复用主配置的单例字段
        mgr.ota_type = MANAGER.ota_type
        mgr.module_type = MANAGER.module_type
        mgr.scenario_overrides = MANAGER.scenario_overrides
        mgr.custom_scenarios = MANAGER.custom_scenarios
        mgr.status_buttons = MANAGER.status_buttons
        mgr.register_template = MANAGER.register_template
        mgr.auto_scenario = MANAGER.auto_scenario
        # 日志转发到聚合日志（带 deviceId 前缀）
        mgr.log_sink = lambda msg, _d=device_id: self._agg(_d, msg)

        # 双检锁写入
        with self.lock:
            existing = self.managers.get(device_id)
            if existing is not None:
                return existing
            self.managers[device_id] = mgr
            return mgr

    def _agg(self, device_id, msg):
        ts = time.strftime("%H:%M:%S")
        line = "[%s] [%s] %s" % (ts, device_id, msg)
        with self.lock:
            self._agg_log.append(line)
            if len(self._agg_log) > self.max_agg_logs:
                self._agg_log = self._agg_log[-self.max_agg_logs:]

    # ---------- 终端列表管理 ----------
    def set_multi_mode(self, enabled, device_ids=None, top_device_id=None):
        """启用/禁用多终端，并可设置 deviceId 列表与顶部 deviceId"""
        with self.lock:
            self.multi_mode = bool(enabled)
            if top_device_id is not None:
                # ★ 空字符串表示"顶部未填 deviceId"，置空而不是兜底成 0001
                self.top_device_id = str(top_device_id).strip()
            if device_ids:
                clean = [str(x).strip() for x in device_ids if str(x).strip()]
                # 去重保序
                seen = set()
                self.device_ids = []
                for d in clean:
                    if d not in seen:
                        seen.add(d)
                        self.device_ids.append(d)
            if not self.device_ids:
                self.device_ids = [m.DEVICE_ID]
        self._persist_multi()
        n = len(self.device_ids) if self.multi_mode else 1
        return True, ("已启用多终端，共 %d 个" % n if self.multi_mode
                      else "已切换为单终端")

    def _persist_multi(self):
        try:
            MANAGER._persist("multiMode", {
                "enabled": self.multi_mode,
                "deviceIds": self.device_ids,
                "topDeviceId": self.top_device_id,
            })
        except Exception:
            pass

    def load_multi_config(self):
        try:
            data = MANAGER._load_config_file()
            mc = data.get("multiMode") or {}
            if mc:
                self.multi_mode = bool(mc.get("enabled"))
                ids = mc.get("deviceIds") or []
                if ids:
                    self.device_ids = [str(x) for x in ids]
                tdid = mc.get("topDeviceId")
                if tdid:
                    self.top_device_id = str(tdid)
                MANAGER.log("[配置] 已加载多终端设置：%s，%d 个终端"
                            % ("多终端" if self.multi_mode else "单终端",
                               len(self.device_ids)))
        except Exception:
            pass

    # ---------- 目标终端 ----------
    def targets(self):
        """当前需要操作的 manager 列表

        ★ 多终端模式下，顶部的单一 deviceId 也会生效：
          把「顶部 deviceId」与「多选列表」合并去重。
        """
        with self.lock:
            multi = self.multi_mode
            ids = list(self.device_ids)
            # ★ 用前端同步的 top_device_id，为空表示顶部未填
            top_dev = (self.top_device_id or "").strip()

        if not multi:
            # 单终端：只用顶部 deviceId（为空才兜底）
            did = top_dev or m.DEVICE_ID
            if did == m.DEVICE_ID:
                return [(did, MANAGER)]
            return [(did, self._get_or_create(did))]

        # 多终端：顶部 deviceId + 多选列表，去重保序
        merged = []
        seen = set()
        for d in ([top_dev] if top_dev else []) + ids:
            d = (d or "").strip()
            if d and d not in seen:
                seen.add(d)
                merged.append(d)
        if not merged:
            merged = [m.DEVICE_ID]

        out = []
        for did in merged:
            if did == m.DEVICE_ID:
                out.append((did, MANAGER))
            else:
                out.append((did, self._get_or_create(did)))
        return out

    def primary(self):
        """主 manager（用于读取共享配置）"""
        return MANAGER

    def sync_register_template(self, tpl):
        """把注册模板同步到所有已存在的终端实例"""
        with self.lock:
            instances = list(self.managers.values())
        for mgr in instances:
            try:
                mgr.register_template = tpl
            except Exception:
                pass

    def sync_all_settings(self):
        """把主实例的共享配置同步到所有终端"""
        with self.lock:
            instances = list(self.managers.values())
        for mgr in instances:
            try:
                mgr.ota_type = MANAGER.ota_type
                mgr.module_type = MANAGER.module_type
                mgr.scenario_overrides = MANAGER.scenario_overrides
                mgr.custom_scenarios = MANAGER.custom_scenarios
                mgr.status_buttons = MANAGER.status_buttons
                mgr.register_template = MANAGER.register_template
                mgr.auto_scenario = MANAGER.auto_scenario
            except Exception:
                pass

    # ---------- 广播操作 ----------
    def _broadcast(self, fn, *args, **kwargs):
        """对所有目标执行 fn(deviceId, mgr, *args)，返回 [(deviceId, ok, msg)]"""
        results = []
        for did, mgr in self.targets():
            try:
                r = fn(did, mgr, *args, **kwargs)
                ok, msg = r if isinstance(r, tuple) else (bool(r), "")
            except Exception as e:
                ok, msg = False, "异常：%s" % e
            results.append((did, ok, msg))
        return results

    def connect_all(self, host, port, username="", password="",
                    protocol_version=5):
        """一键连接所有终端。已连接的会跳过（幂等），不算失败。"""
        results = self._broadcast(
            lambda did, mgr: mgr.connect(host, port, did, username, password,
                                         protocol_version=protocol_version))
        ok_count = 0
        skip_count = 0
        fail_list = []
        for did, ok, msg in results:
            if ok:
                ok_count += 1
            elif "已连接" in (msg or ""):
                skip_count += 1     # 已连接视为正常，不算失败
            else:
                fail_list.append("%s:%s" % (did, (msg or "")[:30]))

        total = len(results)
        if not fail_list:
            if skip_count:
                return True, "连接完成：%d 个新连接，%d 个原本已连接" % (
                    ok_count, skip_count)
            return True, "连接成功：%d/%d 个终端" % (ok_count, total)
        return (ok_count > 0,
                "连接 %d/%d 成功，%d 个失败：%s" % (
                    ok_count, total, len(fail_list), "；".join(fail_list)))

    def disconnect_all(self):
        results = self._broadcast(lambda did, mgr: mgr.disconnect())
        ok_count = sum(1 for _, ok, _ in results if ok)
        return True, "已断开 %d/%d 个终端" % (ok_count, len(results))

    def set_auto_scenario_all(self, scenario):
        # 同步到主 MANAGER 供新终端继承
        MANAGER.auto_scenario = scenario
        results = self._broadcast(lambda did, mgr: mgr.set_auto_scenario(scenario))
        fail = [msg for _, ok, msg in results if not ok]
        if fail and len(fail) == len(results):
            return False, fail[0]
        return True, "已在 %d 个终端应用场景" % len(results)

    def run_scenario_all(self, scenario):
        results = self._broadcast(lambda did, mgr: mgr.run_scenario_now(scenario))
        ok_count = sum(1 for _, ok, _ in results if ok)
        return ok_count > 0, "已在 %d/%d 个终端开始执行" % (ok_count, len(results))

    def send_status_all(self, status_code):
        results = self._broadcast(lambda did, mgr: mgr.send_status(status_code))
        ok_count = sum(1 for _, ok, _ in results if ok)
        return ok_count > 0, "已向 %d/%d 个终端发送 status=%s" % (
            ok_count, len(results), status_code)

    def publish_all(self, topic, payload, qos=0):
        results = self._broadcast(lambda did, mgr: mgr.publish(topic, payload, qos))
        ok_count = sum(1 for _, ok, _ in results if ok)
        return ok_count > 0, "已发送到 %d/%d 个终端" % (ok_count, len(results))

    # ---------- 状态聚合 ----------
    def status_all(self):
        out = []
        for did, mgr in self.targets():
            try:
                st = mgr.status()
            except Exception as e:
                st = {"connected": False, "error": str(e)}
            st["deviceId"] = did
            out.append(st)
        primary = out[0] if out else {}
        return {
            "multiMode": self.multi_mode,
            "deviceIds": list(self.device_ids),
            "terminals": out,
            "connected": any(x.get("connected") for x in out),
            "allConnected": all(x.get("connected") for x in out) and len(out) > 0,
            "connectedCount": sum(1 for x in out if x.get("connected")),
            "total": len(out),
            # 兼容单终端字段
            "config": primary.get("config"),
            "subscriptions": primary.get("subscriptions", []),
            "autoScenario": primary.get("autoScenario"),
            "lastCommand": primary.get("lastCommand"),
            # ★ 多终端：按 deviceId 索引的最近命令（各自的 requestId 独立）
            "lastCommandsByDevice": {
                x.get("deviceId"): x.get("lastCommand")
                for x in out if x.get("lastCommand")
            },
            "otaType": MANAGER.ota_type,
            "moduleType": MANAGER.module_type,
        }

    def get_logs(self, since=0):
        return self._agg_log[since:], len(self._agg_log)


MULTI = MultiDeviceManager()
MULTI.load_multi_config()


if __name__ == "__main__":
    # 页面和 HTTP 路由在 web_ui.py 中定义，此处仅为模块占位
    print("请运行 web_server 的完整版（含 web_ui）")
