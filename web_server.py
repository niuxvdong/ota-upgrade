#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTA 终端模拟器 —— Web 工作台（主程序）

启动：python web_server.py [host] [port]
默认：http://127.0.0.1:8080

依赖：pip install paho-mqtt
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import mock_device as m
from web_core import MANAGER, MULTI, DEFAULT_STATUS_BUTTONS

BUILD_STAMP = time.strftime("%Y%m%d%H%M%S")
VERSION = "v2.3-" + BUILD_STAMP[-5:]

WEB_HOST = "127.0.0.1"
WEB_PORT = 8080

# ============================================================================
# 页面
# ============================================================================
PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>OTA 终端模拟器 __VER__</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #eef2f7; color: #1a202c; font-size: 14px;
    display: flex; flex-direction: column; overflow: hidden;
  }

  /* ---------- 顶部栏 ---------- */
  .topbar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 8px 14px; background: #fff; border-bottom: 1px solid #e2e8f0; flex: 0 0 auto;
  }
  .brand { font-weight: 800; font-size: 14.5px; color: #1a202c; margin-right: 8px;
           display: flex; align-items: center; gap: 6px;
           background: linear-gradient(135deg,#2b6cb0,#4299e1);
           -webkit-background-clip: text; -webkit-text-fill-color: transparent;
           background-clip: text; }
  .brand small { font-weight: 600; color: #4299e1; font-size: 10.5px;
                 font-family: Consolas, monospace;
                 -webkit-text-fill-color: #4299e1; }
  .fld { display: inline-flex; flex-direction: column; gap: 1px; }
  .fld > i { font-style: normal; font-size: 9px; color: #a0aec0; padding-left: 2px;
             line-height: 1.1; }
  .conn-form { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .conn-form input, .conn-form select {
    padding: 5px 8px; border: 1px solid #cbd5e0; border-radius: 5px;
    font-size: 13px; outline: none; background: #fff;
  }
  input:focus, select:focus, textarea:focus { border-color: #3182ce; }
  .host { width: 118px; } .port { width: 66px; } .dev { width: 108px; }
  .user { width: 96px; } .dtype { width: 76px; }
  .pass { min-width: 210px; }
  button {
    padding: 6px 13px; border: none; border-radius: 5px; font-size: 13px;
    cursor: pointer; font-family: inherit; white-space: nowrap;
  }
  .btn-primary { background: #3182ce; color: #fff; }
  .btn-primary:hover { background: #2b6cb0; }
  .btn-primary:disabled { background: #a0aec0; cursor: not-allowed; }
  .btn-danger { background: #e53e3e; color: #fff; }
  .btn-danger:hover { background: #c53030; }
  .btn-danger:disabled { background: #fbb; cursor: not-allowed; }
  .btn-ghost { background: #edf2f7; color: #2d3748; }
  .btn-ghost:hover { background: #e2e8f0; }
  .badge {
    padding: 5px 14px; border-radius: 14px; font-size: 12px; font-weight: 700;
    background: #fc8181; color: #fff; display: inline-flex;
    align-items: center; justify-content: center; line-height: 1;
    letter-spacing: .3px; box-shadow: 0 1px 3px rgba(0,0,0,.15);
  }
  .badge.on { background: #48bb78; color: #fff; }

  /* ---------- 三栏 ---------- */
  .layout {
    flex: 1; min-height: 0; display: grid;
    grid-template-columns: 330px 1fr 400px; gap: 10px; padding: 10px;
  }
  @media (max-width: 1500px) { .layout { grid-template-columns: 300px 1fr 340px; } }
  @media (max-width: 1200px) { .layout { grid-template-columns: 270px 1fr 300px; } }
  .col { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
  .card {
    background: #fff; border: 1px solid #cbd5e0; border-radius: 8px;
    display: flex; flex-direction: column; min-height: 0; overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }
  .pane-title {
    padding: 9px 12px; border-bottom: 2px solid #e2e8f0;
    font-size: 12.5px; font-weight: 700; color: #2b6cb0; letter-spacing: .4px;
    display: flex; align-items: center; justify-content: space-between;
    gap: 8px; flex: 0 0 auto; background: #f7fafc;
  }
  .pane-body { padding: 9px 11px; overflow-y: auto; min-height: 0; }
  .hint { font-size: 11.5px; color: #4a5568; margin-top: 6px; line-height: 1.6; }

  /* ---------- 连接状态 ---------- */
  .st-row { display: flex; align-items: center; gap: 8px; font-size: 12.5px;
            padding: 2px 0; }
  .st-row b { color: #718096; font-weight: 500; min-width: 62px; }
  .mono { font-family: Consolas, monospace; word-break: break-all; font-size: 11.5px;
          color: #2d3748; }

  /* ---------- 场景 ---------- */
  .scene {
    display: flex; flex-direction: column; align-items: flex-start;
    justify-content: center; gap: 1px;
    width: 100%; text-align: left; padding: 4px 8px; border-radius: 5px;
    border: 1px solid #cbd5e0; background: #ffffff; cursor: pointer;
    font-size: 12px; color: #1a202c; transition: all .15s; line-height: 1.25;
    font-family: inherit;
    /* ★ 紧凑：标题 + 最多 2 行描述 */
    min-height: 46px; height: 46px;
    overflow: hidden;
  }
  .scene:hover { background: #ebf8ff; border-color: #63b3ed; }
  .scene.active {
    background: linear-gradient(135deg, #2b6cb0, #3182ce);
    border-color: #2b6cb0; color: #fff;
    box-shadow: 0 2px 6px rgba(49,130,206,.35);
  }
  .scene.active .d { color: #e6f0ff; }
  .scene code {
    font-family: Consolas, monospace; font-weight: 700; font-size: 12px;
    display: block; width: 100%;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .scene .d {
    font-size: 10.5px; color: #4a5568; font-weight: 500;
    width: 100%; line-height: 1.3;
    /* ★ 允许换行，最多 2 行，超出省略 */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  .scene.active .d { color: #dbeafe; }
  /* 仅监听：未选中时白底虚线 */
  .scene.none {
    background: #f7fafc; border-style: dashed; border-color: #a0aec0;
  }
  .scene.none .n {
    font-weight: 700; color: #2d3748; display: block; width: 100%;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .scene.none .d { color: #4a5568; }
  .scene.none:hover { background: #ebf8ff; border-color: #63b3ed; }

  /* ★ 仅监听被选中：必须重新声明渐变（覆盖上面的白底） */
  .scene.none.active {
    background: linear-gradient(135deg, #2b6cb0, #3182ce);
    border-style: solid; border-color: #2b6cb0;
    box-shadow: 0 2px 6px rgba(49,130,206,.35);
  }
  .scene.none.active .n,
  .scene.none.active .d { color: #fff; }

  /* 未连接禁用外观：只降低透明度，不灰度（保留蓝色可辨识） */
  .scene.disabled, .st.disabled {
    opacity: .62; cursor: not-allowed !important;
    box-shadow: none;
  }
  .scene.disabled:hover, .st.disabled:hover {
    transform: none; box-shadow: none;
  }
  /* 禁用的普通场景：灰色提示不可点 */
  .scene.disabled:not(.active):not(.none) {
    background: #edf2f7; border-color: #cbd5e0; color: #718096;
  }
  .scene.disabled:not(.active):not(.none) .d { color: #a0aec0; }
  /* 禁用的「仅监听」未选中：白底虚线，文字仍可读 */
  .scene.disabled.none:not(.active) {
    background: #f7fafc; border-color: #cbd5e0;
  }
  /* ★ 禁用的选中项：保留蓝色渐变（略淡），一眼看出选中 */
  .scene.disabled.active {
    background: linear-gradient(135deg, #5a89b8, #6fa3cc) !important;
    border-color: #5a89b8 !important;
    color: #fff !important;
  }
  .scene.disabled.active .d,
  .scene.disabled.active .n,
  .scene.disabled.active code { color: #fff !important; }

  /* ---------- 状态按钮 ---------- */
  .statuses { display: grid; grid-template-columns: repeat(8, 1fr); gap: 3px; }
  .st {
    padding: 4px 1px; border-radius: 4px; text-align: center; cursor: pointer;
    font-size: 9.5px; border: 1px solid transparent; font-family: inherit;
    line-height: 1.15; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
  }
  .st b { display: block; font-size: 11.5px; margin-bottom: 1px; }
  .st-push { background: #bee3f8; color: #1a4e8a; border-color: #90cdf4; }
  .st-up { background: #c6f6d5; color: #1c5c3a; border-color: #9ae6b4; }
  .st-oth { background: #e2e8f0; color: #2d3748; border-color: #cbd5e0; }
  .st-fail { background: #fed7d7; color: #9b2c2c; border-color: #feb2b2; }
  .st:hover { filter: brightness(.92); transform: translateY(-1px);
              box-shadow: 0 2px 5px rgba(0,0,0,.12); }

  /* ---------- 最近命令 ---------- */
  .last-cmd {
    padding: 8px 11px; font-family: Consolas, monospace; font-size: 11.5px;
    color: #1a202c; line-height: 1.55; min-height: 44px; font-weight: 500;
  }
  .last-cmd b { color: #2b6cb0; font-weight: 700; }

  /* ---------- 消息 ---------- */
  .msgs {
    flex: 1; overflow-y: auto; padding: 9px; background: #f7f9fc; min-height: 0;
    /* 允许正常选中与复制 */
    user-select: text; -webkit-user-select: text;
    cursor: text;
    /* 拖选文字时不让浏览器平滑滚动干扰 */
    scroll-behavior: auto;
  }
  .msgs .msg, .msgs .msg * {
    user-select: text; -webkit-user-select: text;
  }
  .msg {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 6px;
    margin-bottom: 6px; overflow: hidden; font-size: 12px;
  }
  .msg.in { border-left: 4px solid #38a169; background: #f0fff4; }
  .msg.out { border-left: 4px solid #3182ce; background: #ebf8ff; }
  .msg-h {
    padding: 4px 9px; display: flex; gap: 7px; align-items: center;
    font-size: 10.5px; color: #718096; border-bottom: 1px solid #edf2f7;
    flex-wrap: wrap; line-height: 1.4;
  }
  .msg-h .t { font-family: Consolas, monospace; color: #2d3748; flex: 1;
              word-break: break-all; min-width: 0; }
  .msg-b {
    padding: 8px 11px; font-family: Consolas, monospace; font-size: 11.5px;
    white-space: pre-wrap; word-break: break-all; max-height: 200px;
    overflow-y: auto; line-height: 1.5;
  }
  .msg-h .btn-use {
    padding: 1px 7px; font-size: 10.5px; background: #edf2f7;
    border: none; border-radius: 3px; cursor: pointer; color: #4a5568;
  }
  .msg-h .btn-use:hover { background: #e2e8f0; }

  /* ---------- 日志 ---------- */
  .col-right .card { flex: 1; }
  #log {
    flex: 1; overflow-y: auto; background: #1a202c; color: #cbd5e0;
    padding: 9px 11px; font-family: Consolas, monospace; font-size: 11.5px;
    line-height: 1.6; white-space: pre-wrap; word-break: break-all; min-height: 0;
  }

  /* ---------- 发送框 ---------- */
  .send-box { padding: 9px 11px; border-top: 1px solid #edf2f7; flex: 0 0 auto; }
  .send-row { display: flex; gap: 6px; align-items: center; }
  .send-box textarea {
    width: 100%; padding: 8px 10px; border: 1px solid #cbd5e0; border-radius: 4px;
    font-size: 12px; font-family: Consolas, monospace; resize: vertical;
    min-height: 100px; outline: none; margin-top: 5px;
    overflow-y: auto; line-height: 1.55; box-sizing: border-box;
  }

  /* ---------- 弹窗 ---------- */
  .modal {
    position: fixed; inset: 0; background: rgba(0,0,0,.45); display: none;
    align-items: center; justify-content: center; z-index: 100; padding: 20px;
  }
  .modal.show { display: flex; }
  .modal-box {
    background: #fff; border-radius: 10px; width: min(1400px, 96vw);
    max-height: 94vh; display: flex; flex-direction: column;
  }
  #scModal .modal-box { width: min(1180px, 94vw); max-height: 92vh; }
  .modal-h {
    padding: 12px 16px; border-bottom: 1px solid #edf2f7;
    display: flex; justify-content: space-between; align-items: center;
    flex: 0 0 auto;
  }
  .modal-h h2 { margin: 0; font-size: 15px; font-weight: 600; }
  .modal-b { padding: 14px 16px; overflow-y: auto; flex: 1; }
  .modal-b textarea {
    width: 100%; padding: 10px; border: 1px solid #cbd5e0;
    border-radius: 6px; font-family: Consolas, monospace; font-size: 11.5px;
    resize: vertical; outline: none; box-sizing: border-box;
  }
  .modal-b textarea.sc-data { min-height: 0; resize: none; }
  .modal-b textarea.reg-ta { min-height: 380px; }
  .modal-f {
    padding: 11px 16px; border-top: 1px solid #edf2f7;
    display: flex; gap: 8px; justify-content: flex-end; flex: 0 0 auto;
  }
  label { font-size: 12px; color: #718096; }

  .empty { text-align: center; color: #a0aec0; font-size: 12px; padding: 20px 10px;
           line-height: 1.7; }

  /* ---------- toast ---------- */
  .toast {
    position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
    background: #2d3748; color: #fff; padding: 10px 20px; border-radius: 6px;
    font-size: 13px; opacity: 0; pointer-events: none; transition: opacity .25s;
    z-index: 200; max-width: 80vw; line-height: 1.5;
  }
  .toast.show { opacity: 1; }
  .toast.ok { background: #276749; }
  .toast.err { background: #9b2c2c; }
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">OTA 终端模拟器 <small>__VER__</small></div>
  <div class="conn-form">
    <span class="fld"><i>broker</i>
      <input class="host" id="host" placeholder="172.1.2.14" title="MQTT 服务端地址"
             oninput="autoWidth(this)"></span>
    <span class="fld"><i>端口</i>
      <input class="port" id="port" placeholder="2883" title="MQTT 端口"></span>
    <span class="fld"><i>deviceId</i>
      <input class="dev" id="deviceId" placeholder="DEVICE-0001" title="模拟终端ID"
             oninput="onDeviceIdChange()"></span>
    <span class="fld"><i>deviceType</i>
      <input class="dtype" id="deviceType" placeholder="999" title="设备类型"
             oninput="onDeviceTypeChange()"></span>
    <span class="fld"><i>用户名</i>
      <input class="user" id="username" placeholder="cscn-sat" title="MQTT 用户名"
             oninput="autoWidth(this)"></span>
    <span class="fld"><i>密码</i>
      <input class="pass" id="password" type="text" placeholder="密码" title="MQTT 密码"
             oninput="autoWidth(this)"></span>
    <span class="fld"><i>协议</i>
      <select id="protocolVersion" style="width:96px;" title="MQTT 协议版本">
        <option value="5">MQTT 5.0</option>
        <option value="4">MQTT 3.1.1</option>
        <option value="3">MQTT 3.1</option>
      </select></span>
    <button class="btn-primary" id="btnConnect" onclick="connect()">连接</button>
    <button class="btn-danger" id="btnDisconnect" onclick="disconnect()" disabled>断开</button>
    <button class="btn-ghost" onclick="openRegister()">注册报文</button>
    <button class="btn-ghost" id="btnSaveCfg" onclick="saveAllConfig()"
            title="把顶部连接配置和下方发送区保存到 mock-config.json，重启后自动恢复">
      保存配置
    </button>
    <span class="badge" id="badge">未连接</span>
  </div>
</div>

<div class="layout">
  <!-- ==================== 左栏 ==================== -->
  <div class="col">
    <div class="card">
      <div class="pane-title">
        <span>连接状态</span>
        <label style="display:flex;align-items:center;gap:4px;font-size:10.5px;
               color:#4a5568;margin:0;cursor:pointer;font-weight:400;"
               title="开启后可配置多个 deviceId，所有操作同时作用于所有终端">
          <input type="checkbox" id="multiMode" onchange="onMultiModeChange()"
                 style="margin:0;cursor:pointer;">
          多终端
        </label>
      </div>
      <div class="pane-body">
        <div class="st-row"><b>状态</b><span class="badge" id="stBadge">未连接</span></div>
        <div class="st-row"><b>clientId</b><span class="mono" id="clientId">-</span></div>
        <div id="multiBox" style="display:none;margin-top:8px;padding-top:8px;
             border-top:1px dashed #cbd5e0;">
          <label style="font-size:11px;color:#4a5568;">deviceId 列表（每行一个或逗号分隔）</label>
          <textarea id="multiIds" rows="3" spellcheck="false"
                    placeholder="DEVICE-0001&#10;DEVICE-0002&#10;DEVICE-0003"
                    style="width:100%;margin-top:4px;padding:5px 7px;border:1px solid #cbd5e0;
                    border-radius:4px;font-size:11px;font-family:Consolas,monospace;
                    resize:vertical;outline:none;box-sizing:border-box;"></textarea>
          <div style="display:flex;gap:5px;margin-top:6px;">
            <button class="btn-primary" onclick="connectAll()"
                    style="flex:1;padding:5px 8px;font-size:11.5px;">一键连接</button>
            <button class="btn-danger" onclick="disconnectAll()"
                    style="flex:1;padding:5px 8px;font-size:11.5px;">一键断开</button>
          </div>
          <div class="hint" id="multiHint" style="margin-top:6px;"></div>
        </div>
      </div>
    </div>

    <div class="card" style="flex:1;min-height:0;">
      <div class="pane-title">
        <span>自动场景</span>
        <button class="btn-ghost" onclick="openCreateScenario()"
                style="padding:2px 9px;font-size:10.5px;" title="创建一个新的自定义场景">
          + 新建
        </button>
      </div>
      <div style="padding:8px 11px 0;flex:0 0 auto;">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;
             padding:6px 8px;background:#f7fafc;border:1px solid #e2e8f0;border-radius:5px;">
          <span style="font-size:11px;color:#718096;white-space:nowrap;">升级方式</span>
          <select id="otaType" onchange="onOtaTypeChange()"
                  style="flex:1;padding:3px 7px;border:1px solid #cbd5e0;border-radius:4px;
                  font-size:11.5px;outline:none;background:#fff;">
            <option value="1">下载后手动升级（3006 / 3007）</option>
            <option value="0">自动升级（3001）</option>
          </select>
        </div>
        <div class="hint" id="cmdTypeHint" style="margin:-2px 0 6px 2px;"></div>
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;
             padding:6px 8px;background:#f7fafc;border:1px solid #e2e8f0;border-radius:5px;">
          <span style="font-size:11px;color:#718096;white-space:nowrap;">模块类型</span>
          <select id="moduleType" onchange="onModuleTypeChange()"
                  style="flex:1;padding:3px 7px;border:1px solid #cbd5e0;border-radius:4px;
                  font-size:11.5px;outline:none;background:#fff;">
            <option value="4">4 - 终端套件（SDK）</option>
            <option value="1">1 - 主机（HOST）</option>
            <option value="2">2 - 天线（ANTENNA）</option>
            <option value="3">3 - 安全卡（SECURITY）</option>
            <option value="5">5 - AP</option>
            <option value="6">6 - CP</option>
            <option value="7">7 - 安全芯片（SECURITY_CHIP）</option>
            <option value="101">101 - 主机（单点）</option>
            <option value="104">104 - 终端套件（单点）</option>
          </select>
        </div>
      </div>
      <div class="pane-body" id="scenarios" style="padding-top:0;"></div>
      <div class="hint" style="padding:0 11px 9px;flex:0 0 auto;">
        选中后收到命令自动按步骤回报；【仅监听】只记录不回复。
      </div>
    </div>

    <div class="card" style="flex:0 0 auto;max-height:230px;">
      <div class="pane-title">订阅 Topic</div>
      <div class="pane-body">
        <div id="subs" style="margin-bottom:6px;"></div>
        <div style="display:flex;gap:5px;">
          <select id="newSub" onchange="toggleCustomTopic()"
                  style="flex:1;font-size:10.5px;padding:4px 6px;border:1px solid #cbd5e0;
                  border-radius:4px;outline:none;">
            <option value="">-- 选择 topic --</option>
          </select>
          <input id="newSubCustom" placeholder="自定义 topic" style="flex:1;display:none;
                 font-size:10.5px;padding:4px 6px;border:1px solid #cbd5e0;border-radius:4px;
                 outline:none;">
          <button class="btn-ghost" onclick="addSub()"
                  style="padding:4px 10px;font-size:11px;"
                  title="点此订阅上面选中的 topic —— 只有订阅后，平台下发的消息才会被收到">+</button>
        </div>
        <div class="hint">
          点【+】订阅下拉框里选中的 topic。<br>
          只有订阅的 topic，平台下发的消息才会被收到。
        </div>
      </div>
    </div>
  </div>

  <!-- ==================== 中栏 ==================== -->
  <div class="col">
    <div class="card" style="flex:0 0 auto;">
      <div class="pane-title">
        <span>最近收到的命令</span>
        <span style="display:flex;align-items:center;gap:8px;">
          <label style="display:flex;align-items:center;gap:4px;font-size:10.5px;
                 color:#718096;margin:0;cursor:pointer;font-weight:400;"
                 title="开启后只显示 OTA 升级相关命令（3001/3006/3007）">
            <input type="checkbox" id="onlyOtaCmd" checked
                   onchange="onOnlyOtaCmdChange()" style="margin:0;cursor:pointer;">
            只看升级命令
          </label>
          <button class="btn-ghost" onclick="fillRequestId()"
                  style="padding:2px 9px;font-size:10.5px;"
                  title="把最近收到的 requestId / commandType 填入下方待发送 JSON">
            填入待发送
          </button>
        </span>
      </div>
      <div id="lastCmd" class="last-cmd">尚未收到命令，等待平台下发...</div>
    </div>

    <div class="card" style="flex:0 0 auto;">
      <div class="pane-title">
        <span>手动回报状态</span>
        <span style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:10.5px;color:#a0aec0;font-weight:400;" id="stHint">
            需先收到命令
          </span>
          <button class="btn-ghost" onclick="openStatusEditor()"
                  style="padding:2px 9px;font-size:10.5px;">编辑</button>
        </span>
      </div>
      <div class="pane-body" style="padding:8px 9px;">
        <div class="statuses" id="statuses"></div>
      </div>
    </div>

    <div class="card" style="flex:1;min-height:0;">
      <div class="pane-title">
        <span style="font-size:11px;font-weight:600;color:#718096;white-space:nowrap;"
              title="这里显示你收到的所有 MQTT 消息（绿色=收到）和你手动发出的消息（蓝色=发出）。">
          消息收发
          <span style="font-weight:400;color:#a0aec0;font-size:10px;">(收发记录)</span>
        </span>
        <span style="display:flex;gap:6px;align-items:center;">
          <input class="filter" id="msgFilter" placeholder="按 topic 过滤（回车）"
                 onkeydown="if(event.key==='Enter'){reloadMsgs();}"
                 style="padding:3px 7px;border:1px solid #cbd5e0;border-radius:4px;
                 font-size:11px;outline:none;width:190px;">
          <button class="btn-ghost" onclick="clearMsgs()"
                  style="padding:2px 9px;font-size:10.5px;">清空</button>
        </span>
      </div>
      <div class="msgs" id="msgs">
        <div class="empty">
          还没有消息<br>
          <span style="font-size:10.5px;color:#cbd5e0;">
            连接后：平台下发的命令会显示在这里（绿色）<br>
            你手动发送或自动场景回报的内容也会显示（蓝色）
          </span>
        </div>
      </div>
      <div class="send-box">
        <div class="send-row">
          <select class="tp" id="sendTopic" onchange="onSendTopicChange()"
                  style="flex:1;padding:5px 8px;border:1px solid #cbd5e0;border-radius:4px;
                  font-size:11.5px;font-family:Consolas,monospace;outline:none;background:#fff;">
            <option value="access/device/executetask/result">access/device/executetask/result（执行结果）</option>
            <option value="access/device/command/reply">access/device/command/reply（命令应答）</option>
            <option value="device/register">device/register（注册）</option>
            <option value="access/device/data/report">access/device/data/report（数据上报）</option>
            <option value="__custom__">自定义...</option>
          </select>
          <button class="btn-primary" onclick="doPublish()"
                  style="padding:5px 14px;font-size:11.5px;">发送</button>
        </div>
        <textarea id="sendPayload" oninput="autoGrowTextarea(this);saveSendBox();"
                  placeholder='{"deviceId":"...","requestId":"...","commandType":"3006","code":200,"data":{"status":14}}'></textarea>
        <div class="hint">
          这里是<b>手动发送</b>入口：可向任意 topic 发消息（默认发应答 topic）。<br>
          点上方消息卡片右侧「引用」可自动填入 requestId，方便构造合法应答。
        </div>
      </div>
    </div>
  </div>

  <!-- ==================== 右栏 ==================== -->
  <div class="col col-right">
    <div class="card">
      <div class="pane-title">
        <span>实时日志</span>
        <button class="btn-ghost" onclick="document.getElementById('log').innerHTML=''"
                style="padding:2px 9px;font-size:10.5px;">清空</button>
      </div>
      <div id="log"></div>
    </div>
  </div>
</div>

<!-- ==================== 注册报文弹窗 ==================== -->
<div id="regModal" class="modal">
  <div class="modal-box" style="width:min(900px,94vw);">
    <div class="modal-h">
      <h2>注册报文（连接时自动上报）</h2>
      <button class="btn-ghost" onclick="closeRegister()">关闭</button>
    </div>
    <div class="modal-b">
      <textarea id="regPayload" class="reg-ta" spellcheck="false"
        oninput="regPayloadDirty = true; autoGrowTextarea(this)"
        style="overflow-y:auto;line-height:1.55;box-sizing:border-box;"></textarea>
      <div id="regReadonlyTip" style="display:none;margin-top:10px;padding:8px 12px;
           background:#fef3e0;border:1px solid #f59e0b;border-radius:5px;
           font-size:12px;color:#a8670a;">
        已连接，报文只读。如需编辑请先【断开】连接。
      </div>
      <div class="hint" style="margin-top:8px;">发送到 topic: <b>device/register</b>；
        timestamp 为 0 时自动填当前时间；deviceId / deviceType 可在左侧修改后自动同步到此报文；
        也可以直接在此编辑任意字段（断开连接时可编辑）。</div>
    </div>
    <div class="modal-f">
      <button class="btn-ghost" id="regBtnFormat" onclick="formatRegJson()">格式化</button>
      <button class="btn-ghost" id="regBtnReset" onclick="resetRegJson()">恢复默认</button>
      <button class="btn-ghost" id="regBtnSave" onclick="saveRegisterTemplate()">保存为模板</button>
      <button class="btn-primary" id="regBtnSend" onclick="sendRegister()">发送并保存</button>
    </div>
  </div>
</div>

<!-- ==================== 状态按钮编辑弹窗 ==================== -->
<div id="stModal" class="modal">
  <div class="modal-box" style="width:min(760px,94vw);">
    <div class="modal-h">
      <h2>编辑状态按钮</h2>
      <button class="btn-ghost" onclick="closeStatusEditor()">关闭</button>
    </div>
    <div class="modal-b">
      <div style="font-size:11px;color:#718096;margin-bottom:10px;line-height:1.7;">
        code = 写入 data.status 的值（0 表示不回响应，用于触发超时）；<br>
        名称 = 按钮上显示的文字；颜色 = 分类；「自动」勾选表示该状态由平台自动写入。
      </div>
      <div id="stList"></div>
      <button class="btn-ghost" style="margin-top:8px;width:100%;"
              onclick="addStatusBtn()">+ 添加一个按钮</button>
    </div>
    <div class="modal-f">
      <button class="btn-ghost" onclick="resetStatusButtons()">恢复默认</button>
      <button class="btn-primary" onclick="saveStatusButtons()">保存</button>
    </div>
  </div>
</div>

<!-- ==================== 新建场景弹窗 ==================== -->
<div id="csModal" class="modal">
  <div class="modal-box" style="width:min(560px,94vw);">
    <div class="modal-h">
      <h2>新建自定义场景</h2>
      <button class="btn-ghost" onclick="closeCreateScenario()">关闭</button>
    </div>
    <div class="modal-b">
      <label style="font-size:12px;">场景名称（英文/数字/下划线）</label>
      <input type="text" id="csName" placeholder="my-custom-scene"
             style="width:100%;padding:7px 10px;margin-bottom:10px;border:1px solid #cbd5e0;
             border-radius:5px;font-size:13px;outline:none;">
      <label style="font-size:12px;">场景描述</label>
      <input type="text" id="csDesc" placeholder="例如：自定义成功流程 10 → 14 → 11 → 12"
             style="width:100%;padding:7px 10px;margin-bottom:10px;border:1px solid #cbd5e0;
             border-radius:5px;font-size:13px;outline:none;">
      <label style="font-size:12px;">从哪个场景复制步骤（可选）</label>
      <select id="csCopyFrom"
              style="width:100%;padding:7px 10px;border:1px solid #cbd5e0;
              border-radius:5px;font-size:13px;outline:none;background:#fff;">
        <option value="">空场景（1 个默认步骤）</option>
      </select>
      <div class="hint" style="margin-top:10px;">
        创建后会自动打开步骤编辑器，可以增删步骤、调整状态码。
        保存后会持久化到 mock-config.json，重启不丢失。
      </div>
    </div>
    <div class="modal-f">
      <button class="btn-ghost" onclick="closeCreateScenario()">取消</button>
      <button class="btn-primary" onclick="doCreateScenario()">创建</button>
    </div>
  </div>
</div>

<!-- ==================== 场景步骤编辑弹窗 ==================== -->
<div id="scModal" class="modal">
  <div class="modal-box">
    <div class="modal-h">
      <h2>场景步骤 <span id="scName"
          style="color:#3182ce;font-family:Consolas,monospace;"></span></h2>
      <button class="btn-ghost" onclick="closeScenarioEditor()">关闭</button>
    </div>
    <div class="modal-b">
      <div style="font-size:12px;color:#718096;margin-bottom:10px;line-height:1.7;">
        每步字段说明：<b>延迟(秒)</b> = 收到命令后等多久发这一步；
        <b>状态码</b> = 写入 data.status（留空表示不发 status）；
        <b>commandType</b> = 由升级方式自动推导（只读）；
        <b>附加数据</b> = JSON 对象，会合并进 data；
        <b>说明</b> = 仅用于日志展示。
        <br><span style="color:#c05621;">注意：带 progress 字段的步骤会走进度分支，
        18/29 这类状态必须不带 progress，否则置不上。</span>
      </div>
      <div id="scSteps"></div>
      <button class="btn-ghost" style="margin-top:10px;width:100%;"
              onclick="addScenarioStep()">+ 添加一步</button>
    </div>
    <div class="modal-f">
      <button class="btn-ghost" onclick="resetScenarioSteps()">恢复默认</button>
      <button class="btn-primary" onclick="saveScenarioSteps()">保存</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ==================== 全局状态 ====================
let STATUSES = [];
let logCursor = 0;
let msgCursor = 0;
let activeScenario = null;
let isConnected = false;
let DEFAULT_DEVICE_ID = "";
let regPayloadDirty = false;
let configLoaded = false;
let scEditingName = null;
let scStepsData = [];
let stEditingData = [];
let lastCmdCache = null;
var lastCmdByDevice = {};

// ==================== 工具 ====================
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
var escHtml = esc;
function escAttr(s) {
  return esc(s).replace(/"/g, "&quot;");
}
function v(id) {
  var el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

let toastTimer = null;
function toast(msg, ok) {
  var t = document.getElementById("toast");
  t.textContent = msg || "";
  t.className = "toast show " + (ok ? "ok" : "err");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.className = "toast"; }, ok ? 2600 : 8000);
}

// 输入框宽度随内容自动扩展
function autoWidth(el, minPx) {
  if (!el) return;
  var min = minPx || parseInt(el.getAttribute("data-min") || "150", 10);
  var span = document.getElementById("__measure__");
  if (!span) {
    span = document.createElement("span");
    span.id = "__measure__";
    span.style.cssText = "position:absolute;visibility:hidden;white-space:pre;" +
      "font-size:12px;font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;padding:0 18px;";
    document.body.appendChild(span);
  }
  span.textContent = el.value || el.placeholder || "";
  var w = Math.max(min, Math.ceil(span.offsetWidth) + 4);
  el.style.width = w + "px";
}

function initAutoWidth() {
  var minMap = { host: 118, port: 66, deviceId: 108, deviceType: 76,
                 username: 96, password: 210 };
  Object.keys(minMap).forEach(function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.setAttribute("data-min", String(minMap[id]));
      autoWidth(el, minMap[id]);
    }
  });
}

// textarea 按内容自动撑高
function autoGrowTextarea(el) {
  if (!el) return;
  var MAX_ROWS = 40;
  var MIN_H = 46;
  el.style.height = "0px";
  el.style.overflowY = "hidden";
  var cs = getComputedStyle(el);
  var lineH = parseFloat(cs.lineHeight) || 16;
  var padT = parseFloat(cs.paddingTop) || 0;
  var padB = parseFloat(cs.paddingBottom) || 0;
  var bT = parseFloat(cs.borderTopWidth) || 0;
  var bB = parseFloat(cs.borderBottomWidth) || 0;
  var contentH = el.scrollHeight;
  var maxH = Math.round(lineH * MAX_ROWS + padT + padB);
  var h = Math.max(MIN_H, Math.min(contentH + bT + bB, maxH));
  el.style.height = h + "px";
  el.style.overflowY = (contentH + bT + bB) > maxH ? "auto" : "hidden";
}

// ==================== 状态码描述 ====================
var STATUS_DESC_MAP = {
  "-10": "升级包已覆盖失效", "0": "不回响应（触发超时）", "5": "待终端稳定入网",
  "10": "升级包下载中", "11": "终端升级中", "12": "终端升级成功",
  "13": "终端升级失败", "14": "下载完成等待升级", "15": "升级包验签失败",
  "18": "下载中断，等待续传", "20": "平台推送命令下发成功",
  "21": "套件推送命令接收失败", "22": "平台升级命令下发成功",
  "23": "套件升级命令接收失败", "24": "远程删除本地固件包成功",
  "25": "远程删除本地固件包失败", "26": "续传中", "29": "下载失败（不可续传）"
};
function getStatusDesc(code) {
  if (code === null || code === undefined || code === "") return "";
  return STATUS_DESC_MAP[String(code)] || "";
}

// ==================== 升级方式 → commandType ====================
var UPGRADE_STAGE_STATUS = [11, 12, 13, 22, 23];

function getOtaType() {
  var el = document.getElementById("otaType");
  return el ? parseInt(el.value || "1", 10) : 1;
}

function resolveCmdType(statusCode) {
  if (getOtaType() === 0) return "3001";
  var code = (statusCode === null || statusCode === undefined || statusCode === "")
    ? null : parseInt(statusCode, 10);
  if (code !== null && !isNaN(code) && UPGRADE_STAGE_STATUS.indexOf(code) >= 0) {
    return "3007";
  }
  return "3006";
}

function onOtaTypeChange() {
  var val = getOtaType();
  fetch("/api/ota-type", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ otaType: val })
  }).then(function (r) { return r.json(); }).then(function (d) {
    updateCmdTypeHint();
    toast(d.msg, d.ok);
    var scm = document.getElementById("scModal");
    if (scm && scm.classList.contains("show")) refreshAllStepPreviews();
    loadScenarios();
  }).catch(function () {});
}

function updateCmdTypeHint() {
  var el = document.getElementById("cmdTypeHint");
  if (!el) return;
  if (getOtaType() === 0) {
    el.innerHTML = '当前：<b>自动升级</b> → 所有回复都用 <b>3001</b>';
  } else {
    el.innerHTML = '当前：<b>下载后手动升级</b> → 下载阶段 <b>3006</b>，' +
      '升级阶段(11/12/13/22/23) <b>3007</b>';
  }
}

function getModuleType() {
  var el = document.getElementById("moduleType");
  return el ? parseInt(el.value || "4", 10) : 4;
}

function onModuleTypeChange() {
  var val = getModuleType();
  fetch("/api/module-type", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ moduleType: val })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    var scm = document.getElementById("scModal");
    if (scm && scm.classList.contains("show")) refreshAllStepPreviews();
  }).catch(function () {});
}

// ==================== 配置加载 ====================
function loadConfig() {
  return fetch("/api/config").then(function (r) { return r.json(); }).then(function (c) {
    document.getElementById("host").value = c.host || "172.1.2.14";
    document.getElementById("port").value = c.port || 2883;
    document.getElementById("deviceId").value = c.deviceId || "DEVICE-0001";
    document.getElementById("username").value = c.username || "";
    document.getElementById("password").value = c.password || "";
    var dtEl = document.getElementById("deviceType");
    if (dtEl) dtEl.value = (c.deviceType != null) ? String(c.deviceType) : "999";
    var pv = document.getElementById("protocolVersion");
    if (pv) pv.value = String(c.protocolVersion || 5);
    DEFAULT_DEVICE_ID = c.deviceId || "DEVICE-0001";
  }).catch(function () {});
}

function loadSavedConfig() {
  return fetch("/api/saved-config").then(function (r) { return r.json(); }).then(function (d) {
    var c = d.conn || {};
    if (c.host) document.getElementById("host").value = c.host;
    if (c.port) document.getElementById("port").value = c.port;
    if (c.deviceId) document.getElementById("deviceId").value = c.deviceId;
    if (c.deviceType) document.getElementById("deviceType").value = c.deviceType;
    if (c.username) document.getElementById("username").value = c.username;
    if (c.password) document.getElementById("password").value = c.password;
    if (c.protocolVersion) {
      var pv = document.getElementById("protocolVersion");
      if (pv) pv.value = String(c.protocolVersion);
    }
    if (d.otaType !== undefined && d.otaType !== null) {
      var otEl = document.getElementById("otaType");
      if (otEl) otEl.value = String(d.otaType);
    }
    if (d.moduleType !== undefined && d.moduleType !== null) {
      var mtEl = document.getElementById("moduleType");
      if (mtEl) mtEl.value = String(d.moduleType);
    }
    var onlyOta = localStorage.getItem("onlyOtaCmd");
    var cb = document.getElementById("onlyOtaCmd");
    if (cb && onlyOta !== null) cb.checked = (onlyOta === "1");

    var sb = d.sendBox || {};
    if (sb.topic) setSendTopic(sb.topic);
    if (sb.payload) document.getElementById("sendPayload").value = sb.payload;

    afterConfigLoaded();
    setTimeout(function () { autoGrowTextarea(document.getElementById("sendPayload")); }, 0);
    configLoaded = true;
  }).catch(function () {
    configLoaded = true;
    afterConfigLoaded();
  });
}

function afterConfigLoaded() {
  updateCmdTypeHint();
  refreshRegisterPreview();
  buildTopicOptions();
  initAutoWidth();
}

// ==================== 连接 ====================
function connect() {
  // 多终端模式：分流到一键连接
  if (typeof multiEnabled !== "undefined" && multiEnabled) {
    connectAll();
    return;
  }
  var body = {
    host: v("host"), port: parseInt(v("port") || "2883", 10),
    deviceId: v("deviceId"), username: v("username"), password: v("password"),
    protocolVersion: parseInt(document.getElementById("protocolVersion").value || "5", 10)
  };
  if (!body.host) { toast("请填写 broker 地址", false); return; }
  if (!body.deviceId) { toast("请填写 deviceId", false); return; }
  var btn = document.getElementById("btnConnect");
  btn.disabled = true; btn.textContent = "连接中...";
  fetch("/api/connect", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    pollStatus();
  }).catch(function (e) {
    toast("连接失败：" + e, false);
  }).finally(function () {
    btn.disabled = false; btn.textContent = "连接";
  });
}

function disconnect() {
  if (typeof multiEnabled !== "undefined" && multiEnabled) {
    disconnectAll();
    return;
  }
  fetch("/api/disconnect", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (d) { toast(d.msg, d.ok); pollStatus(); });
}

// ==================== 状态轮询 ====================
// ==================== 多终端 ====================
var multiEnabled = false;

function getMultiIds() {
  var ta = document.getElementById("multiIds");
  if (!ta) return [];
  var NL = String.fromCharCode(10);    // 

  var CR = String.fromCharCode(13);    // 

  var raw = (ta.value || "")
    .split(NL).join(",")
    .split(CR).join(",")
    .split(";").join(",")
    .split("，").join(",")        // 中文逗号
    .split("；").join(",");       // 中文分号
  return raw.split(",")
    .map(function (x) { return x.trim(); })
    .filter(function (x) { return x && x.length > 0; });
}

function onMultiModeChange() {
  var cb = document.getElementById("multiMode");
  multiEnabled = cb.checked;
  var box = document.getElementById("multiBox");
  if (box) box.style.display = multiEnabled ? "block" : "none";
  if (multiEnabled && !document.getElementById("multiIds").value.trim()) {
    // 默认填入当前 deviceId
    var cur = v("deviceId") || "DEVICE-0001";
    document.getElementById("multiIds").value = cur;
  }
  fetch("/api/multi/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: multiEnabled, deviceIds: getMultiIds() })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    updateMultiHint();
    pollStatus();
  });
}

function connectAll() {
  if (!multiEnabled) { connect(); return; }
  var ids = getMultiIds();
  if (!ids.length) { toast("请至少填写一个 deviceId", false); return; }
  // 先保存配置
  fetch("/api/multi/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: true, deviceIds: ids })
  }).then(function () {
    var body = {
      host: v("host"), port: parseInt(v("port") || "2883", 10),
      username: v("username"), password: v("password"),
      protocolVersion: parseInt(document.getElementById("protocolVersion").value || "5", 10)
    };
    var btn = document.getElementById("btnConnect");
    if (btn) { btn.disabled = true; btn.textContent = "连接中..."; }
    return fetch("/api/connect-all", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    pollStatus();
  }).catch(function (e) {
    toast("连接失败：" + e, false);
  }).finally(function () {
    var btn = document.getElementById("btnConnect");
    if (btn) { btn.disabled = false; btn.textContent = "连接"; }
  });
}

function disconnectAll() {
  if (!multiEnabled) { disconnect(); return; }
  fetch("/api/disconnect-all", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (d) { toast(d.msg, d.ok); pollStatus(); });
}

function updateMultiHint() {
  var el = document.getElementById("multiHint");
  if (!el) return;
  var n = getMultiIds().length;
  el.innerHTML = multiEnabled
    ? '当前配置 <b>' + n + '</b> 个终端，所有操作（场景/回报/发送）会同时作用于全部'
    : '';
}

function pollStatus() {
  fetch("/api/state").then(function (r) { return r.json(); }).then(function (s) {
    isConnected = !!s.connected;
    var badge = document.getElementById("badge");
    var stBadge = document.getElementById("stBadge");
    // 多终端：显示 x/y 已连接
    var txt;
    if (s.multiMode) {
      var cc = s.connectedCount || 0, tt = s.total || 0;
      txt = cc + "/" + tt + " 已连接";
      isConnected = cc > 0;
    } else {
      txt = isConnected ? "已连接" : "未连接";
    }
    badge.textContent = txt;
    badge.className = "badge" + (isConnected ? " on" : "");
    stBadge.textContent = txt;
    stBadge.className = "badge" + (isConnected ? " on" : "");

    // clientId 展示
    var cidEl = document.getElementById("clientId");
    if (s.multiMode && s.terminals && s.terminals.length) {
      var lines = s.terminals.map(function (t) {
        return (t.deviceId || "?") + "  " +
          (t.connected ? '<span style="color:#276749;">●</span>' : '<span style="color:#c53030;">○</span>');
      });
      cidEl.innerHTML = lines.join("<br>");
      cidEl.style.lineHeight = "1.6";
    } else {
      cidEl.textContent = (s.config && s.config.clientId) || "-";
    }

    // 同步多终端 UI 状态
    if (s.multiMode !== undefined && window.__lastMulti !== s.multiMode) {
      window.__lastMulti = s.multiMode;
      multiEnabled = !!s.multiMode;
      var mc = document.getElementById("multiMode");
      if (mc) mc.checked = multiEnabled;
      var mb = document.getElementById("multiBox");
      if (mb) mb.style.display = multiEnabled ? "block" : "none";
      if (s.deviceIds && s.deviceIds.length) {
        var mt = document.getElementById("multiIds");
        if (mt) mt.value = s.deviceIds.join(String.fromCharCode(10));
      }
      updateMultiHint();
    }
    // 按钮状态：单终端模式全连上才禁用；多终端模式只有全部连上才禁用
    var btnC = document.getElementById("btnConnect");
    var btnD = document.getElementById("btnDisconnect");
    if (s.multiMode) {
      var allOn = !!s.allConnected;
      var anyOn = (s.connectedCount || 0) > 0;
      if (btnC) btnC.disabled = allOn;         // 全部连上才不能点连接
      if (btnD) btnD.disabled = !anyOn;        // 任一个连上就能断开
    } else {
      if (btnC) btnC.disabled = isConnected;
      if (btnD) btnD.disabled = !isConnected;
    }

    var hint = document.getElementById("stHint");
    if (hint) hint.textContent = s.lastCommand ? "点击填充到发送框" : "需先收到命令";

    lastCmdCache = s.lastCommand || null;
    lastCmdByDevice = s.lastCommandsByDevice || {};
    renderLastCommand();

    if (s.autoScenario !== activeScenario) {
      activeScenario = s.autoScenario;
      loadScenarios();
    }
    // 连接状态变化时重新渲染（切换禁用样式）
    if (window.__lastConnected !== undefined &&
        window.__lastConnected !== isConnected) {
      loadScenarios();
      renderStatusButtons();
      if (!isConnected && window.__wasEverConnected) {
        toast("连接已断开", false);
      }
      setTimeout(fetchLogs, 300);
    }
    if (isConnected) window.__wasEverConnected = true;
    window.__lastConnected = isConnected;
  }).catch(function () {});
}

// ==================== 最近命令 ====================
var OTA_COMMAND_TYPES = ["3001", "3006", "3007"];

function onOnlyOtaCmdChange() {
  var cb = document.getElementById("onlyOtaCmd");
  localStorage.setItem("onlyOtaCmd", cb.checked ? "1" : "0");
  renderLastCommand();
}

function renderLastCommand() {
  var box = document.getElementById("lastCmd");
  if (!box) return;
  var cb = document.getElementById("onlyOtaCmd");
  var onlyOta = cb ? cb.checked : true;

  // ★ 多终端：逐个终端展示各自的最近命令
  if (typeof multiEnabled !== "undefined" && multiEnabled) {
    var ids = Object.keys(lastCmdByDevice || {});
    if (!ids.length) {
      box.textContent = "尚未收到命令，等待平台下发...";
      return;
    }
    var html = "";
    ids.sort().forEach(function (did) {
      var c = lastCmdByDevice[did];
      if (!c) return;
      if (onlyOta && OTA_COMMAND_TYPES.indexOf(String(c.commandType)) < 0) return;
      html +=
        '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;' +
          'padding:3px 0;border-bottom:1px dashed #edf2f7;">' +
          '<span style="background:#2b6cb0;color:#fff;padding:1px 7px;border-radius:3px;' +
            'font-size:10.5px;font-weight:600;">' + esc(did) + '</span>' +
          '<span style="background:#3182ce;color:#fff;padding:1px 7px;border-radius:3px;' +
            'font-weight:700;font-size:11px;">' + esc(c.commandType) + '</span>' +
          '<span style="color:#2d3748;font-size:11px;">' + esc(c.cmdName || "") + '</span>' +
          '<span style="color:#a0aec0;font-size:10px;margin-left:auto;">' +
            esc(c.ts || "") + '</span>' +
          '<button class="btn-ghost btn-fill-req" data-did="' + escAttr(did) + '" ' +
            'style="padding:0 6px;font-size:10px;">填入</button>' +
        '</div>' +
        '<div style="padding:1px 0 4px 4px;color:#4a5568;font-size:10.5px;' +
          'font-family:Consolas,monospace;word-break:break-all;">' +
          esc(c.requestId) + '</div>';
    });
    if (!html) {
      box.innerHTML = '<span style="color:#a0aec0;">当前无 OTA 升级命令（已按开关过滤）</span>';
      return;
    }
    box.innerHTML = html;
    // 绑定「填入」按钮
    var btns = box.querySelectorAll(".btn-fill-req");
    for (var bi = 0; bi < btns.length; bi++) {
      (function (btn) {
        btn.onclick = function () {
          fillRequestIdFor(btn.getAttribute("data-did"));
        };
      })(btns[bi]);
    }
    return;
  }

  var lc = lastCmdCache;
  if (!lc) {
    box.textContent = "尚未收到命令，等待平台下发...";
    return;
  }
  if (onlyOta && OTA_COMMAND_TYPES.indexOf(String(lc.commandType)) < 0) {
    box.innerHTML = '<span style="color:#a0aec0;">最近命令 commandType=' +
      esc(lc.commandType) + '（' + esc(lc.cmdName || "") +
      '）不属于 OTA 升级命令（3001/3006/3007），已按开关过滤。<br>' +
      '取消勾选「只看升级命令」可查看。</span>';
    return;
  }
  box.innerHTML =
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
      '<span style="background:#3182ce;color:#fff;padding:2px 9px;border-radius:4px;' +
        'font-weight:700;font-size:12.5px;">' + esc(lc.commandType) + '</span>' +
      '<span style="color:#2d3748;font-weight:600;">' + esc(lc.cmdName || "") + '</span>' +
      '<span style="color:#a0aec0;font-size:11px;margin-left:auto;">' +
        esc(lc.ts || "") + '</span>' +
    '</div>' +
    '<div style="margin-top:4px;color:#4a5568;font-size:11.5px;">' +
      '<b>requestId</b>: ' + esc(lc.requestId) + '</div>';
}

// ★ 按指定终端填充 requestId（多终端用）
function fillRequestIdFor(deviceId) {
  var c = (lastCmdByDevice || {})[deviceId];
  if (!c || !c.requestId) {
    toast("终端 " + deviceId + " 还没有收到命令", false);
    return;
  }
  fillRequestIdInto(deviceId, c.requestId);
  var ta = document.getElementById("sendPayload");
  ta.scrollIntoView({ behavior: "smooth", block: "center" });
  ta.focus();
}

// ★ 只替换 requestId，不改动报文其它内容
function fillRequestIdInto(deviceId, requestId) {
  var ta = document.getElementById("sendPayload");
  var cur = (ta.value || "").trim();
  var obj = null;
  if (cur) {
    try { obj = JSON.parse(cur); } catch (e) { obj = null; }
  }
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    // 已有合法 JSON：只改 requestId（和设备 id，若指定）
    obj.requestId = requestId;
    if (deviceId) obj.deviceId = deviceId;
    ta.value = JSON.stringify(obj, null, 2);
  } else {
    // 当前不是合法 JSON 对象 → 生成最小骨架
    obj = { deviceId: deviceId || v("deviceId") || "DEVICE-0001",
            requestId: requestId };
    ta.value = JSON.stringify(obj, null, 2);
  }
  autoGrowTextarea(ta);
  saveSendBox();
  toast("已填入 requestId" + (deviceId ? "（" + deviceId + "）" : ""), true);
}

function fillRequestId() {
  if (!lastCmdCache || !lastCmdCache.requestId) {
    toast("还没有收到命令，无法填充", false);
    return;
  }
  fillRequestIdInto(null, lastCmdCache.requestId);
}

// ==================== 场景列表 ====================
function loadScenarios() {
  fetch("/api/scenarios").then(function (r) { return r.json(); }).then(function (list) {
    var box = document.getElementById("scenarios");
    box.innerHTML = "";

    var none = document.createElement("button");
    none.className = "scene none" + (activeScenario === null ? " active" : "") +
      (isConnected ? "" : " disabled");
    none.style.cssText = "width:100%;margin-bottom:6px;";
    none.innerHTML = '<span class="n">仅监听</span>' +
      '<div class="d">不自动回报，手动点状态按钮</div>';
    none.onclick = function () { setScenario(null); };
    box.appendChild(none);

    (list || []).forEach(function (s) {
      var wrap = document.createElement("div");
      wrap.style.cssText = "display:flex;gap:4px;align-items:stretch;margin-bottom:4px;";
      var b = document.createElement("button");
      b.className = "scene" + (activeScenario === s.name ? " active" : "") +
        (isConnected ? "" : " disabled");
      b.style.flex = "1";
      b.innerHTML = "<code>" + esc(s.name) + "</code>" +
        (s.customized ? ' <span style="color:#f6ad55;font-size:10px;">·已改</span>' : "") +
        (s.isCustom ? ' <span style="color:#68d391;font-size:10px;">·自定义</span>' : "") +
        '<div class="d">' + esc(s.desc) + "</div>";
      b.onclick = function () { setScenario(s.name); };

      var ed = document.createElement("button");
      ed.className = "btn-ghost";
      ed.title = "编辑步骤";
      ed.style.cssText = "padding:0 7px;font-size:11px;background:#edf2f7;flex:0 0 auto;";
      ed.textContent = "编辑";
      ed.onclick = function (e) { e.stopPropagation(); openScenarioEditor(s.name); };

      var run = document.createElement("button");
      run.className = "btn-primary";
      run.title = "立即执行这个场景（不等平台下发命令，直接按步骤发送）";
      run.style.cssText = "padding:0 7px;font-size:10.5px;flex:0 0 auto;";
      run.textContent = "▶";
      run.onclick = function (e) { e.stopPropagation(); runScenarioNow(s.name); };

      wrap.appendChild(b);
      wrap.appendChild(ed);
      wrap.appendChild(run);

      if (s.isCustom) {
        var del = document.createElement("button");
        del.className = "btn-danger";
        del.title = "删除这个自定义场景";
        del.style.cssText = "padding:0 7px;font-size:11px;flex:0 0 auto;";
        del.textContent = "删";
        del.onclick = function (e) { e.stopPropagation(); deleteCustomScenario(s.name); };
        wrap.appendChild(del);
      }
      box.appendChild(wrap);
    });
  }).catch(function () {});
}

function setScenario(name) {
  if (!isConnected) {
    toast("未连接，无法切换场景。请先点击【连接】", false);
    return;
  }
  fetch("/api/scenario", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario: name })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) {
      activeScenario = name;
      loadScenarios();
      setTimeout(fetchLogs, 300);
    }
  });
}

function runScenarioNow(name) {
  if (!isConnected) {
    toast("未连接，无法执行场景。请先点击【连接】", false);
    return;
  }
  fetch("/api/run-scenario", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario: name })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) setTimeout(fetchMsgs, 800);
  });
}

// ==================== 状态按钮 ====================
function loadStatusButtons() {
  fetch("/api/status-buttons").then(function (r) { return r.json(); }).then(function (d) {
    STATUSES = d.statuses || [];
    renderStatusButtons();
  }).catch(function () {});
}

function renderStatusButtons() {
  var box = document.getElementById("statuses");
  if (!box) return;
  box.innerHTML = "";
  STATUSES.forEach(function (s) {
    var b = document.createElement("button");
    b.className = "st " + (s.cls || "st-oth") + (isConnected ? "" : " disabled");
    var shortName = s.name.length > 6 ? s.name.substring(0, 6) : s.name;
    b.innerHTML = "<b>" + (s.code === 0 ? "--" : s.code) + "</b>" + esc(shortName);
    b.title = "状态码 " + s.code + "：" + s.name +
      (s.auto ? "（平台自动写入）" : "（点击填充到发送框）");
    b.onclick = function () { sendStatus(s.code); };
    box.appendChild(b);
  });
}

// 点击状态按钮 → 填充到发送框（不直接发送）
function sendStatus(code) {
  if (!isConnected) {
    toast("未连接，无法回报状态。请先点击【连接】", false);
    return;
  }
  fetch("/api/status-payload?status=" + code)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var ta = document.getElementById("sendPayload");
      ta.value = JSON.stringify(d.payload, null, 2);
      autoGrowTextarea(ta);
      setSendTopic("access/device/executetask/result");
      saveSendBox();
      toast("已填充状态 " + code + " 的报文，请检查后点【发送】", true);
      ta.scrollIntoView({ behavior: "smooth", block: "center" });
      ta.focus();
      setTimeout(fetchLogs, 300);
    }).catch(function () { toast("填充失败", false); });
}

function openStatusEditor() {
  fetch("/api/status-buttons").then(function (r) { return r.json(); }).then(function (d) {
    stEditingData = (d.statuses || []).map(function (x) {
      return { code: x.code, name: x.name, cls: x.cls || "st-oth", auto: !!x.auto };
    });
    renderStatusEditor();
    document.getElementById("stModal").classList.add("show");
  }).catch(function (e) { toast("加载状态按钮失败：" + e, false); });
}

function closeStatusEditor() {
  document.getElementById("stModal").classList.remove("show");
}

function renderStatusEditor() {
  var box = document.getElementById("stList");
  box.innerHTML = "";
  stEditingData.forEach(function (s, i) {
    var row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;align-items:center;margin-bottom:7px;" +
      "padding:7px 9px;background:#fafbfc;border:1px solid #e2e8f0;border-radius:6px;";
    row.innerHTML =
      '<input type="number" class="st-code" value="' + s.code + '" ' +
        'style="width:64px;padding:4px 6px;border:1px solid #cbd5e0;border-radius:4px;' +
        'font-size:11.5px;outline:none;">' +
      '<input type="text" class="st-name" value="' + escAttr(s.name) + '" ' +
        'style="flex:1;padding:4px 6px;border:1px solid #cbd5e0;border-radius:4px;' +
        'font-size:11.5px;outline:none;">' +
      '<select class="st-cls" style="padding:4px 6px;border:1px solid #cbd5e0;' +
        'border-radius:4px;font-size:11px;outline:none;">' +
        '<option value="st-push"' + (s.cls === "st-push" ? " selected" : "") + '>推送</option>' +
        '<option value="st-up"' + (s.cls === "st-up" ? " selected" : "") + '>升级</option>' +
        '<option value="st-oth"' + (s.cls === "st-oth" ? " selected" : "") + '>其他</option>' +
        '<option value="st-fail"' + (s.cls === "st-fail" ? " selected" : "") + '>失败</option>' +
      '</select>' +
      '<label style="font-size:10.5px;color:#718096;display:flex;align-items:center;gap:3px;">' +
        '<input type="checkbox" class="st-auto"' + (s.auto ? " checked" : "") +
        ' style="margin:0;">自动</label>' +
      '<button class="btn-ghost" style="padding:2px 7px;font-size:10.5px;">↑</button>' +
      '<button class="btn-ghost" style="padding:2px 7px;font-size:10.5px;">↓</button>' +
      '<button class="btn-danger" style="padding:2px 7px;font-size:10.5px;">删</button>';
    var btns = row.querySelectorAll("button");
    btns[0].onclick = function () { moveStatusBtn(i, -1); };
    btns[1].onclick = function () { moveStatusBtn(i, 1); };
    btns[2].onclick = function () { delStatusBtn(i); };
    box.appendChild(row);
  });
}

function collectStatusButtons() {
  var rows = document.getElementById("stList").children;
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var code = parseInt(r.querySelector(".st-code").value || "0", 10);
    var name = r.querySelector(".st-name").value.trim();
    if (!name) { toast("第" + (i + 1) + "个按钮名称不能为空", false); return null; }
    out.push({
      code: isNaN(code) ? 0 : code,
      name: name,
      cls: r.querySelector(".st-cls").value,
      auto: r.querySelector(".st-auto").checked
    });
  }
  return out;
}

function addStatusBtn() {
  var cur = collectStatusButtons();
  if (!cur) return;
  stEditingData = cur;
  stEditingData.push({ code: 14, name: "新按钮", cls: "st-oth", auto: false });
  renderStatusEditor();
}

function delStatusBtn(i) {
  var cur = collectStatusButtons();
  if (!cur) return;
  stEditingData = cur;
  stEditingData.splice(i, 1);
  renderStatusEditor();
}

function moveStatusBtn(i, dir) {
  var cur = collectStatusButtons();
  if (!cur) return;
  var j = i + dir;
  if (j < 0 || j >= cur.length) return;
  var tmp = cur[i]; cur[i] = cur[j]; cur[j] = tmp;
  stEditingData = cur;
  renderStatusEditor();
}

function saveStatusButtons() {
  var btns = collectStatusButtons();
  if (!btns) return;
  fetch("/api/status-buttons", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ statuses: btns })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) {
      closeStatusEditor();
      loadStatusButtons();
    }
  });
}

function resetStatusButtons() {
  fetch("/api/status-buttons-reset", { method: "POST" })
    .then(function (r) { return r.json(); }).then(function (d) {
      toast(d.msg, d.ok);
      closeStatusEditor();
      loadStatusButtons();
    });
}

// ==================== 场景步骤编辑 ====================
function openScenarioEditor(name) {
  scEditingName = name;
  document.getElementById("scName").textContent = name;
  fetch("/api/scenario-steps?name=" + encodeURIComponent(name))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d.ok) { toast(d.msg || "加载场景步骤失败", false); return; }
      scStepsData = (d.steps || []).map(function (st) {
        return { delay: st.delay, status: st.status,
                 data: st.data || {}, desc: st.desc || "" };
      });
      renderScenarioSteps();
      document.getElementById("scModal").classList.add("show");
    })
    .catch(function (e) { toast("加载场景步骤失败：" + e, false); });
}

function closeScenarioEditor() {
  document.getElementById("scModal").classList.remove("show");
}

function renderScenarioSteps() {
  var box = document.getElementById("scSteps");
  if (!box) return;
  box.innerHTML = "";
  if (!scStepsData.length) {
    box.innerHTML = '<div class="empty">还没有步骤</div>';
    return;
  }

  scStepsData.forEach(function (st, i) {
    var card = document.createElement("div");
    card.style.cssText = "border:1px solid #e2e8f0;border-radius:7px;padding:10px 11px;" +
      "margin-bottom:9px;background:#fafbfc;";

    var left = document.createElement("div");
    left.style.cssText = "flex:1;min-width:0;";
    left.innerHTML =
      '<div style="display:flex;align-items:center;gap:7px;margin-bottom:7px;">' +
        '<span style="background:#3182ce;color:#fff;width:19px;height:19px;border-radius:50%;' +
          'display:flex;align-items:center;justify-content:center;font-size:10.5px;' +
          'font-weight:600;flex:0 0 auto;">' + (i + 1) + '</span>' +
        '<input type="text" class="sc-desc" value="' + escAttr(st.desc) + '" ' +
          'placeholder="步骤说明" style="flex:1;padding:4px 7px;border:1px solid #cbd5e0;' +
          'border-radius:4px;font-size:11.5px;outline:none;min-width:0;">' +
        '<button class="btn-ghost" style="padding:2px 7px;font-size:10.5px;" ' +
          'onclick="moveScenarioStep(' + i + ',-1)">↑</button>' +
        '<button class="btn-ghost" style="padding:2px 7px;font-size:10.5px;" ' +
          'onclick="moveScenarioStep(' + i + ',1)">↓</button>' +
        '<button class="btn-danger" style="padding:2px 7px;font-size:10.5px;" ' +
          'onclick="delScenarioStep(' + i + ')">删</button>' +
      '</div>' +
      '<div style="display:flex;gap:7px;margin-bottom:7px;">' +
        '<label style="flex:0 0 96px;font-size:10.5px;color:#718096;">延迟(秒)' +
          '<input type="number" step="0.1" class="sc-delay" value="' + (st.delay || 0) + '" ' +
            'style="width:100%;margin-top:2px;padding:4px 7px;border:1px solid #cbd5e0;' +
            'border-radius:4px;font-size:11.5px;outline:none;"></label>' +
        '<label style="flex:0 0 96px;font-size:10.5px;color:#718096;">状态码' +
          '<input type="text" class="sc-status" value="' +
            (st.status === null || st.status === undefined ? "" : st.status) + '" ' +
            'style="width:100%;margin-top:2px;padding:4px 7px;border:1px solid #cbd5e0;' +
            'border-radius:4px;font-size:11.5px;outline:none;"></label>' +
        '<div style="flex:0 0 100px;font-size:10.5px;color:#718096;">commandType' +
          '<div class="sc-cmdtype-view" style="margin-top:2px;padding:4px 7px;' +
            'background:#edf2f7;border:1px solid #cbd5e0;border-radius:4px;' +
            'font-size:11.5px;font-family:Consolas,monospace;color:#2b6cb0;font-weight:600;">' +
            resolveCmdType(st.status) + '</div></div>' +
        '<div style="flex:1;font-size:10.5px;color:#718096;line-height:1.5;">' +
          '<div style="margin-top:2px;">状态含义：' +
            '<span class="sc-status-desc" style="color:#2b6cb0;font-weight:600;">' +
            (getStatusDesc(st.status) || "—") + '</span></div>' +
          '<div style="color:#a0aec0;">留空状态码 = 不发 status</div>' +
        '</div>' +
      '</div>' +
      '<label style="font-size:10.5px;color:#718096;display:block;">附加数据 data (JSON)' +
        '<textarea class="sc-data" spellcheck="false" oninput="autoGrowTextarea(this)" ' +
          'style="width:100%;margin-top:2px;padding:6px 8px;border:1px solid #cbd5e0;' +
          'border-radius:4px;font-family:Consolas,monospace;font-size:10.5px;' +
          'resize:none;outline:none;overflow-y:hidden;line-height:1.5;box-sizing:border-box;">' +
          escHtml(JSON.stringify(st.data || {}, null, 2)) + '</textarea></label>';

    var right = document.createElement("div");
    right.style.cssText = "flex:0 0 330px;margin-left:12px;";
    right.innerHTML =
      '<div style="font-size:10px;color:#a0aec0;margin-bottom:3px;">' +
        '实际发送的完整报文（预览，只读）</div>' +
      '<pre class="sc-preview" style="margin:0;padding:8px 10px;background:#1a202c;' +
        'color:#a0d8ef;border-radius:4px;font-family:Consolas,monospace;font-size:11px;' +
        'line-height:1.55;white-space:pre-wrap;word-break:break-all;max-height:260px;' +
        'overflow-y:auto;">' + escHtml(buildStepPreview(st)) + '</pre>';

    var wrap = document.createElement("div");
    wrap.style.cssText = "display:flex;align-items:flex-start;";
    wrap.appendChild(left);
    wrap.appendChild(right);
    card.appendChild(wrap);
    box.appendChild(card);

    var statusInput = left.querySelector(".sc-status");
    var dataInput = left.querySelector(".sc-data");
    var preview = right.querySelector(".sc-preview");
    var descSpan = left.querySelector(".sc-status-desc");

    var refresh = function () {
      var st2 = readStepFromCard(card);
      if (st2) {
        preview.textContent = buildStepPreview(st2);
        if (descSpan) descSpan.textContent = getStatusDesc(st2.status) || "—";
        var cmdView = card.querySelector(".sc-cmdtype-view");
        if (cmdView) cmdView.textContent = resolveCmdType(st2.status);
      }
      if (dataInput) autoGrowTextarea(dataInput);
    };
    if (statusInput) statusInput.addEventListener("input", refresh);
    if (dataInput) dataInput.addEventListener("input", refresh);
    if (dataInput) setTimeout(function () { autoGrowTextarea(dataInput); }, 0);
  });
}

function readStepFromCard(card) {
  var q = function (sel) { return card.querySelector(sel); };
  var delayEl = q(".sc-delay");
  if (!delayEl) return null;
  var data = {};
  var dataEl = q(".sc-data");
  try {
    var raw = (dataEl ? dataEl.value : "").trim();
    data = raw ? JSON.parse(raw) : {};
  } catch (e) {
    return null;
  }
  var sv = (q(".sc-status") ? q(".sc-status").value : "").trim();
  return {
    delay: parseFloat(delayEl.value || "0") || 0,
    status: sv === "" ? null : parseInt(sv, 10),
    data: data,
    desc: (q(".sc-desc") ? q(".sc-desc").value : "")
  };
}

function buildStepPreview(st) {
  var devId = (v("deviceId") || "DEVICE-0001");
  var data = {};
  if (st.status !== null && st.status !== undefined && !isNaN(st.status)) {
    data.status = st.status;
  }
  if (st.data && typeof st.data === "object") {
    var keys = Object.keys(st.data);
    for (var i = 0; i < keys.length; i++) data[keys[i]] = st.data[keys[i]];
  }
  data.moduleType = getModuleType();
  var payload = {
    deviceId: devId,
    requestId: (lastCmdCache && lastCmdCache.requestId) || "<最近收到的 requestId>",
    commandType: resolveCmdType(st.status),
    code: 200, msg: "success",
    timestamp: Date.now(),
    data: data
  };
  return JSON.stringify(payload, null, 2);
}

function refreshAllStepPreviews() {
  var cards = document.getElementById("scSteps").children;
  for (var i = 0; i < cards.length; i++) {
    var card = cards[i];
    var st = readStepFromCard(card);
    if (!st) continue;
    var preview = card.querySelector(".sc-preview");
    if (preview) preview.textContent = buildStepPreview(st);
    var cmdView = card.querySelector(".sc-cmdtype-view");
    if (cmdView) cmdView.textContent = resolveCmdType(st.status);
  }
}

function collectScenarioSteps() {
  var cards = document.getElementById("scSteps").children;
  var out = [];
  for (var i = 0; i < cards.length; i++) {
    var c = cards[i];
    var delayEl = c.querySelector(".sc-delay");
    if (!delayEl) continue;
    var statusEl = c.querySelector(".sc-status");
    var dataEl = c.querySelector(".sc-data");
    var descEl = c.querySelector(".sc-desc");
    var data = {};
    try {
      var raw = (dataEl ? dataEl.value : "").trim();
      data = raw ? JSON.parse(raw) : {};
    } catch (e) {
      toast("第" + (i + 1) + "步 data 不是合法 JSON：" + e.message, false);
      return null;
    }
    var sv = (statusEl ? statusEl.value : "").trim();
    out.push({
      delay: parseFloat(delayEl.value || "0") || 0,
      status: sv === "" ? null : parseInt(sv, 10),
      data: data,
      desc: (descEl ? descEl.value : "") || ("步骤" + (i + 1))
    });
  }
  return out;
}

function addScenarioStep() {
  var cur = collectScenarioSteps();
  if (!cur) return;
  scStepsData = cur;
  scStepsData.push({ delay: 10, status: 11, data: {}, desc: "新步骤" });
  renderScenarioSteps();
}

function delScenarioStep(i) {
  var cur = collectScenarioSteps();
  if (!cur) return;
  cur.splice(i, 1);
  scStepsData = cur;
  renderScenarioSteps();
}

function moveScenarioStep(i, dir) {
  var cur = collectScenarioSteps();
  if (!cur) return;
  var j = i + dir;
  if (j < 0 || j >= cur.length) return;
  var tmp = cur[i]; cur[i] = cur[j]; cur[j] = tmp;
  scStepsData = cur;
  renderScenarioSteps();
}

function saveScenarioSteps() {
  var steps = collectScenarioSteps();
  if (!steps) return;
  fetch("/api/scenario-steps", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: scEditingName, steps: steps })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) {
      closeScenarioEditor();
      loadScenarios();
    }
  });
}

function resetScenarioSteps() {
  fetch("/api/scenario-reset", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: scEditingName })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) openScenarioEditor(scEditingName);
  });
}

// ==================== 自定义场景 ====================
function openCreateScenario() {
  document.getElementById("csName").value = "";
  document.getElementById("csDesc").value = "";
  var sel = document.getElementById("csCopyFrom");
  sel.innerHTML = '<option value="">空场景（1 个默认步骤）</option>';
  fetch("/api/scenarios").then(function (r) { return r.json(); }).then(function (list) {
    (list || []).forEach(function (x) {
      var op = document.createElement("option");
      op.value = x.name;
      op.textContent = x.name + "  —  " + x.desc;
      sel.appendChild(op);
    });
  }).catch(function () {});
  document.getElementById("csModal").classList.add("show");
}

function closeCreateScenario() {
  document.getElementById("csModal").classList.remove("show");
}

function doCreateScenario() {
  var name = v("csName");
  var desc = v("csDesc");
  var copyFrom = document.getElementById("csCopyFrom").value;
  if (!name) { toast("请填写场景名称", false); return; }

  var createIt = function (steps) {
    fetch("/api/custom-scenario", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, desc: desc || "自定义场景", steps: steps })
    }).then(function (r) { return r.json(); }).then(function (d) {
      toast(d.msg, d.ok);
      if (!d.ok) return;
      closeCreateScenario();
      loadScenarios();
      setTimeout(function () { openScenarioEditor(name); }, 300);
    });
  };

  if (copyFrom) {
    fetch("/api/scenario-steps?name=" + encodeURIComponent(copyFrom))
      .then(function (r) { return r.json(); })
      .then(function (d) { createIt(d.steps || []); })
      .catch(function () { createIt(null); });
  } else {
    createIt([{ delay: 1, status: 14, data: {}, desc: "步骤1" }]);
  }
}

function deleteCustomScenario(name) {
  if (!confirm("确定删除自定义场景【" + name + "】？")) return;
  fetch("/api/custom-scenario-delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) {
      if (activeScenario === name) setScenario(null);
      loadScenarios();
    }
  });
}

// ==================== 注册报文 ====================
function refreshRegisterPreview() {
  var dev = v("deviceId") || "DEVICE-0001";
  var dt = v("deviceType") || "999";
  fetch("/api/register-payload?deviceId=" + encodeURIComponent(dev) +
        "&deviceType=" + encodeURIComponent(dt))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var ta = document.getElementById("regPayload");
      if (ta && !regPayloadDirty) {
        try {
          ta.value = JSON.stringify(JSON.parse(d.payload || "{}"), null, 2);
        } catch (e) { ta.value = d.payload || ""; }
      }
    }).catch(function () {});
}

function syncRegisterField(field, value) {
  var ta = document.getElementById("regPayload");
  if (!ta || !ta.value.trim()) { refreshRegisterPreview(); return; }
  try {
    var o = JSON.parse(ta.value);
    if (o.data && typeof o.data === "object") o.data[field] = value;
    ta.value = JSON.stringify(o, null, 2);
  } catch (e) { refreshRegisterPreview(); }
}

function onDeviceIdChange() {
  buildTopicOptions();
  var dev = v("deviceId");
  var sendTa = document.getElementById("sendPayload");
  if (sendTa && sendTa.value.trim()) {
    try {
      var o = JSON.parse(sendTa.value);
      if (o && typeof o === "object" && "deviceId" in o) {
        o.deviceId = dev;
        sendTa.value = JSON.stringify(o, null, 2);
      }
    } catch (e) {}
  }
  var regTa = document.getElementById("regPayload");
  if (regTa && regTa.value.trim()) {
    try {
      var o2 = JSON.parse(regTa.value);
      o2.deviceId = dev;
      if (o2.data && typeof o2.data === "object") o2.data.deviceId = dev;
      regTa.value = JSON.stringify(o2, null, 2);
      return;
    } catch (e) {}
  }
  refreshRegisterPreview();
}

function onDeviceTypeChange() {
  var val = v("deviceType");
  syncRegisterField("deviceType", val);
  var ta = document.getElementById("regPayload");
  if (ta && ta.value.trim()) {
    try {
      var o = JSON.parse(ta.value);
      if (o.data && typeof o.data === "object") o.data.deviceType = val;
      ta.value = JSON.stringify(o, null, 2);
      clearTimeout(window.__regTplTimer);
      window.__regTplTimer = setTimeout(function () {
        try {
          fetch("/api/register-template", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ template: JSON.parse(ta.value) })
          });
        } catch (e) {}
      }, 600);
    } catch (e) {}
  } else {
    refreshRegisterPreview();
  }
}

function openRegister() {
  var modal = document.getElementById("regModal");
  modal.classList.add("show");
  var ta = document.getElementById("regPayload");
  var ro = document.getElementById("regReadonlyTip");
  if (isConnected) {
    if (ro) ro.style.display = "block";
    ta.readOnly = true;
    if (document.getElementById("regBtnSend")) {
      document.getElementById("regBtnSend").disabled = false;
    }
  } else {
    if (ro) ro.style.display = "none";
    ta.readOnly = false;
  }
  var dev = v("deviceId") || "DEVICE-0001";
  var dt = v("deviceType") || "999";
  fetch("/api/register-template").then(function (r) { return r.json(); })
    .then(function (d) {
      var base = d.template || {};
      base.deviceId = dev;
      if (base.data && typeof base.data === "object") {
        base.data.deviceId = dev;
        base.data.deviceType = dt;
      }
      ta.value = JSON.stringify(base, null, 2);
      regPayloadDirty = false;
      setTimeout(function () { autoGrowTextarea(ta); }, 0);
    }).catch(function () {});
}

function closeRegister() {
  document.getElementById("regModal").classList.remove("show");
}

function formatRegJson() {
  var ta = document.getElementById("regPayload");
  try {
    ta.value = JSON.stringify(JSON.parse(ta.value), null, 2);
    autoGrowTextarea(ta);
    toast("已格式化", true);
  } catch (e) { toast("JSON 格式错误：" + e.message, false); }
}

function resetRegJson() {
  var dev = v("deviceId") || "DEVICE-0001";
  var dt = v("deviceType") || "999";
  fetch("/api/register-payload?default=1&deviceId=" + encodeURIComponent(dev) +
        "&deviceType=" + encodeURIComponent(dt))
    .then(function (r) { return r.json(); }).then(function (d) {
      var ta = document.getElementById("regPayload");
      try {
        ta.value = JSON.stringify(JSON.parse(d.payload || "{}"), null, 2);
      } catch (e) { ta.value = d.payload || ""; }
      regPayloadDirty = false;
      autoGrowTextarea(ta);
      toast("已恢复默认", true);
    });
}

function saveRegisterTemplate() {
  var ta = document.getElementById("regPayload");
  var obj;
  try { obj = JSON.parse(ta.value); }
  catch (e) { toast("JSON 格式错误：" + e.message, false); return; }
  fetch("/api/register-template", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template: obj })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    regPayloadDirty = false;
  });
}

function sendRegister() {
  var ta = document.getElementById("regPayload");
  var obj;
  try { obj = JSON.parse(ta.value); }
  catch (e) { toast("JSON 格式错误：" + e.message, false); return; }
  fetch("/api/register", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ payload: obj })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) closeRegister();
  });
}

// ==================== 订阅 ====================
function buildTopicOptions() {
  var dev = v("deviceId") || "DEVICE-0001";
  var sel = document.getElementById("newSub");
  if (!sel) return;
  var cur = sel.value;
  var base = [
    "access/device/" + dev + "/command",
    "access/device/command",
    "device/" + dev + "/command",
    "access/device/broadcast"
  ];
  sel.innerHTML = '<option value="">-- 选择 topic --</option>';
  base.forEach(function (t) {
    var op = document.createElement("option");
    op.value = t; op.textContent = t;
    sel.appendChild(op);
  });
  var op2 = document.createElement("option");
  op2.value = "__custom__"; op2.textContent = "自定义...";
  sel.appendChild(op2);
  if (cur) sel.value = cur;
}

function toggleCustomTopic() {
  var sel = document.getElementById("newSub");
  var inp = document.getElementById("newSubCustom");
  inp.style.display = (sel.value === "__custom__") ? "block" : "none";
  if (sel.value === "__custom__") inp.focus();
}

function addSub() {
  var sel = document.getElementById("newSub");
  var topic = sel.value;
  if (topic === "__custom__") topic = v("newSubCustom");
  if (!topic) { toast("请先选择或输入 topic", false); return; }
  fetch("/api/subscribe", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic: topic })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    setTimeout(pollSubs, 600);
  });
}

function delSub(topic) {
  fetch("/api/unsubscribe", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic: topic })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    setTimeout(pollSubs, 400);
  });
}

function pollSubs() {
  fetch("/api/state").then(function (r) { return r.json(); }).then(function (s) {
    var box = document.getElementById("subs");
    if (!box) return;
    box.innerHTML = "";
    (s.subscriptions || []).forEach(function (t) {
      var row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:5px;margin-bottom:4px;" +
        "font-size:10.5px;font-family:Consolas,monospace;background:#ebf8ff;" +
        "border:1px solid #bee3f8;border-radius:4px;padding:3px 6px;color:#2b6cb0;";
      var sp = document.createElement("span");
      sp.style.cssText = "flex:1;word-break:break-all;";
      sp.textContent = t;
      var btn = document.createElement("button");
      btn.className = "btn-ghost";
      btn.style.cssText = "padding:0 5px;font-size:10px;";
      btn.textContent = "×";
      btn.onclick = function () { delSub(t); };
      row.appendChild(sp);
      row.appendChild(btn);
      box.appendChild(row);
    });
  }).catch(function () {});
}

// ==================== 消息 ====================
function highlightJson(obj) {
  var s = JSON.stringify(obj, null, 2);
  if (!s) return "";
  return esc(s);
}

function buildMsgEl(msg) {
  var el = document.createElement("div");
  el.className = "msg " + (msg.direction === "in" ? "in" : "out");
  var label = msg.direction === "in" ? "收到" : "发送";
  var head = document.createElement("div");
  head.className = "msg-h";
  var body = msg.json ? highlightJson(msg.json) : esc(msg.payload || msg.hex || "");
  head.innerHTML =
    '<span style="font-weight:600;color:' +
      (msg.direction === "in" ? "#276749" : "#2b6cb0") + ';">' + label + '</span>' +
    '<span class="t">' + esc(msg.topic) + '</span>' +
    '<span>QoS' + (msg.qos || 0) + '</span>' +
    '<span>' + esc(msg.ts) + '</span>';
  if (msg.direction === "in") {
    var use = document.createElement("button");
    use.className = "btn-use";
    use.textContent = "引用";
    use.onclick = function () { quoteFromEl(msg); };
    head.appendChild(use);
  }
  var b = document.createElement("div");
  b.className = "msg-b";
  b.textContent = body;
  el.appendChild(head);
  el.appendChild(b);
  return el;
}

function quoteFromEl(msg) {
  var rid = null;
  var ctype = null;
  if (msg.json) {
    rid = msg.json.requestId || (msg.json.data && msg.json.data.requestId);
    ctype = msg.json.commandType;
  }
  if (!rid) { toast("该消息没有 requestId", false); return; }
  var payload = {
    deviceId: v("deviceId") || "DEVICE-0001",
    requestId: rid,
    commandType: String(ctype || resolveCmdType(14)),
    code: 200, msg: "success",
    timestamp: Date.now(),
    data: { status: 14, moduleType: getModuleType() }
  };
  var ta = document.getElementById("sendPayload");
  ta.value = JSON.stringify(payload, null, 2);
  autoGrowTextarea(ta);
  setSendTopic("access/device/executetask/result");
  saveSendBox();
  toast("已引用 requestId=" + rid, true);
}

// 记住用户是否手动向上滚动过（滚上去就不自动拉底，方便查看历史）
var msgUserScrolledUp = false;

function fetchMsgs() {
  var filter = (document.getElementById("msgFilter") || {}).value || "";
  fetch("/api/messages?since=0&filter=" + encodeURIComponent(filter))
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var box = document.getElementById("msgs");
      var list = d.messages || [];
      var nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;

      // ★ 增量更新：只追加新消息，不清空 DOM
      //   （清空重建会导致：选中文字丢失、滚动条跳动）
      var rendered = window.__msgRendered || 0;
      var filterChanged = (window.__msgFilter !== filter);

      if (list.length < rendered || filterChanged) {
        // 消息变少了（清空）或过滤条件变了 → 全量重建
        box.innerHTML = "";
        rendered = 0;
        window.__msgFilter = filter;
      }

      if (!list.length) {
        if (!box.querySelector(".empty")) {
          box.innerHTML = '<div class="empty">还没有消息<br>' +
            '<span style="font-size:10.5px;color:#718096;">' +
            '连接后：平台下发的命令会显示在这里（绿色）<br>' +
            '你手动发送或自动场景回报的内容也会显示（蓝色）</span></div>';
        }
        window.__msgRendered = 0;
        return;
      }

      // 移除空状态提示
      var emptyEl = box.querySelector(".empty");
      if (emptyEl) emptyEl.remove();

      // 只追加新的
      for (var i = rendered; i < list.length; i++) {
        box.appendChild(buildMsgEl(list[i]));
      }
      var appended = list.length - rendered;
      window.__msgRendered = list.length;
      window.__msgCount = list.length;

      // 新消息到达时：如果用户没往上翻，自动滚到底
      if (appended > 0 && !msgUserScrolledUp) {
        box.scrollTop = box.scrollHeight;
      } else if (appended > 0 && nearBottom) {
        box.scrollTop = box.scrollHeight;
      }
    }).catch(function () {});
}

// 监听用户滚动：手动上翻则暂停自动跟随，回到底部则恢复
function bindMsgScroll() {
  var box = document.getElementById("msgs");
  if (!box || box.__bound) return;
  box.__bound = true;
  box.addEventListener("scroll", function () {
    var nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    msgUserScrolledUp = !nearBottom;
  });
}

function reloadMsgs() { fetchMsgs(); }

function clearMsgs() {
  fetch("/api/messages/clear", { method: "POST" })
    .then(function (r) { return r.json(); })
    .then(function (d) { toast(d.msg, d.ok); fetchMsgs(); });
}

// ==================== 发送 ====================
function getSendTopic() {
  var sel = document.getElementById("sendTopic");
  if (!sel) return "";
  if (sel.value === "__custom__") {
    var inp = document.getElementById("sendTopicCustom");
    return inp ? inp.value.trim() : "";
  }
  return sel.value;
}

function setSendTopic(topic) {
  var sel = document.getElementById("sendTopic");
  if (!sel || !topic) return;
  var exists = false;
  for (var i = 0; i < sel.options.length; i++) {
    if (sel.options[i].value === topic) { exists = true; break; }
  }
  var old = document.getElementById("sendTopicCustom");
  if (exists) {
    sel.value = topic;
    if (old) old.style.display = "none";
  } else {
    sel.value = "__custom__";
    onSendTopicChange();
    var inp = document.getElementById("sendTopicCustom");
    if (inp) inp.value = topic;
    localStorage.setItem("lastCustomSendTopic", topic);
  }
}

function onSendTopicChange() {
  var sel = document.getElementById("sendTopic");
  var old = document.getElementById("sendTopicCustom");
  if (sel.value === "__custom__") {
    if (!old) {
      var inp = document.createElement("input");
      inp.type = "text";
      inp.id = "sendTopicCustom";
      inp.placeholder = "输入自定义 topic";
      inp.style.cssText = "flex:1;padding:5px 8px;border:1px solid #cbd5e0;" +
        "border-radius:4px;font-size:11px;font-family:Consolas,monospace;outline:none;";
      inp.value = localStorage.getItem("lastCustomSendTopic") || "";
      sel.parentNode.insertBefore(inp, sel.nextSibling);
      inp.focus();
    } else {
      old.style.display = "block";
    }
  } else if (old) {
    old.style.display = "none";
  }
  saveSendBox();
}

function initSendPayload() {
  var ta = document.getElementById("sendPayload");
  if (!ta || ta.value.trim()) return;
  var tpl = {
    deviceId: v("deviceId") || "DEVICE-0001",
    requestId: "<填最近收到的 requestId>",
    commandType: resolveCmdType(14),
    code: 200, msg: "success",
    timestamp: 0,
    data: { status: 14, moduleType: getModuleType() }
  };
  ta.value = JSON.stringify(tpl, null, 2);
  setTimeout(function () { autoGrowTextarea(ta); }, 0);
}

function doPublish() {
  var topic = getSendTopic();
  if (!topic) { toast("请先选择或输入要发送的 topic", false); return; }
  var payload = document.getElementById("sendPayload").value || "";
  if (!payload.trim()) { toast("报文不能为空", false); return; }
  try { JSON.parse(payload); }
  catch (e) { toast("报文不是合法 JSON：" + e.message, false); return; }
  fetch("/api/publish", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic: topic, payload: payload, qos: 1 })
  }).then(function (r) { return r.json(); }).then(function (d) {
    toast(d.msg, d.ok);
    if (d.ok) setTimeout(fetchMsgs, 400);
  });
}

let sendSaveTimer = null;
function saveSendBox() {
  clearTimeout(sendSaveTimer);
  sendSaveTimer = setTimeout(function () {
    fetch("/api/save-sendbox", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: getSendTopic(),
        payload: document.getElementById("sendPayload").value || ""
      })
    }).catch(function () {});
  }, 800);
}

// ==================== 配置保存 ====================
let connSaveTimer = null;
function scheduleSaveConn() {
  clearTimeout(connSaveTimer);
  connSaveTimer = setTimeout(saveConnConfig, 600);
}

function saveConnConfig() {
  var cfg = {
    host: v("host"), port: v("port"), deviceId: v("deviceId"),
    deviceType: v("deviceType"), username: v("username"),
    password: v("password"),
    protocolVersion: parseInt(document.getElementById("protocolVersion").value || "5", 10)
  };
  fetch("/api/save-conn", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg)
  }).catch(function () {});
}

function saveAllConfig() {
  var btn = document.getElementById("btnSaveCfg");
  var cfg = {
    host: v("host"), port: v("port"), deviceId: v("deviceId"),
    deviceType: v("deviceType"), username: v("username"),
    password: v("password"),
    protocolVersion: parseInt(document.getElementById("protocolVersion").value || "5", 10)
  };
  var sb = { topic: getSendTopic(), payload: document.getElementById("sendPayload").value || "" };
  var regTpl = null;
  var regTa = document.getElementById("regPayload");
  if (regTa && regTa.value.trim()) {
    try { regTpl = JSON.parse(regTa.value); } catch (e) { regTpl = null; }
  }
  if (btn) { btn.disabled = true; btn.textContent = "保存中..."; }

  var tasks = [
    fetch("/api/save-conn", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg)
    }),
    fetch("/api/save-sendbox", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sb)
    }).catch(function () { return null; }),
    fetch("/api/ota-type", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ otaType: getOtaType() })
    }).catch(function () { return null; }),
    fetch("/api/module-type", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ moduleType: getModuleType() })
    }).catch(function () { return null; })
  ];
  if (regTpl) {
    tasks.push(fetch("/api/register-template", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: regTpl })
    }).catch(function () { return null; }));
  }
  Promise.all(tasks).then(function () {
    toast("配置已保存（连接 / 发送区 / 升级方式 / 模块类型" +
      (regTpl ? " / 注册报文" : "") + "），重启后自动恢复", true);
  }).catch(function (e) {
    toast("保存失败：" + e, false);
  }).finally(function () {
    if (btn) { btn.disabled = false; btn.textContent = "保存配置"; }
  });
}

function flushSaveOnExit() {
  if (!configLoaded) return;
  try {
    var cfg = {
      host: v("host"), port: v("port"), deviceId: v("deviceId"),
      deviceType: v("deviceType"), username: v("username"), password: v("password"),
      protocolVersion: parseInt(document.getElementById("protocolVersion").value || "5", 10)
    };
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/save-conn",
        new Blob([JSON.stringify(cfg)], { type: "application/json" }));
    }
    var sb = { topic: getSendTopic(), payload: document.getElementById("sendPayload").value || "" };
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/save-sendbox",
        new Blob([JSON.stringify(sb)], { type: "application/json" }));
    }
  } catch (e) {}
}

function bindConnAutoSave() {
  ["host", "port", "deviceId", "deviceType", "username", "password"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", scheduleSaveConn);
      el.addEventListener("blur", saveConnConfig);
    }
  });
  var pv = document.getElementById("protocolVersion");
  if (pv) pv.addEventListener("change", saveConnConfig);
  var ta = document.getElementById("sendPayload");
  if (ta) ta.addEventListener("input", saveSendBox);
  var st = document.getElementById("sendTopic");
  if (st) st.addEventListener("change", saveSendBox);
}

// ==================== 日志 ====================
function fetchLogs() {
  fetch("/api/logs?since=" + logCursor)
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var box = document.getElementById("log");
      if (d.logs && d.logs.length) {
        var atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
        box.textContent += d.logs.join("\n") + "\n";
        var lines = box.textContent.split("\n");
        if (lines.length > 900) {
          box.textContent = lines.slice(-900).join("\n");
        }
        if (atBottom) box.scrollTop = box.scrollHeight;
      }
      logCursor = d.cursor != null ? d.cursor : logCursor;
    }).catch(function () {});
}

// ==================== 初始化 ====================
window.onload = function () {
  loadConfig()
    .then(function () { return loadSavedConfig(); })
    .then(function () {
      bindConnAutoSave();
      initSendPayload();
      window.addEventListener("beforeunload", flushSaveOnExit);
      window.addEventListener("pagehide", flushSaveOnExit);
    })
    .catch(function () {
      bindConnAutoSave();
      initSendPayload();
    });

  loadStatusButtons();
  loadScenarios();
  pollStatus();
  pollSubs();
  bindMsgScroll();
  fetchMsgs();
  fetchLogs();
  setInterval(pollStatus, 1500);
  setInterval(pollSubs, 3000);
  setInterval(fetchLogs, 900);
  setInterval(fetchMsgs, 1500);
};
</script>
</body>
</html>
"""


# ============================================================================
# HTTP 处理
# ============================================================================
class Handler(BaseHTTPRequestHandler):

    server_version = "OtaMock/2.3"

    def log_message(self, fmt, *args):
        pass   # 静默，避免刷屏

    # ---------------- 响应工具 ----------------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------------- GET ----------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path in ("/", "/index.html"):
                html = PAGE.replace("__VER__", VERSION).replace("__BUILD_STAMP__", BUILD_STAMP)
                self._send(200, html, "text/html; charset=utf-8")
                return

            if path == "/api/config":
                self._json({
                    "host": m.MQTT_HOST,
                    "port": m.MQTT_PORT,
                    "deviceId": m.DEVICE_ID,
                    "username": m.MQTT_USERNAME,
                    "password": m.MQTT_PASSWORD,
                    "protocolVersion": m.MQTT_PROTOCOL_VERSION,
                    "clientIdPrefix": getattr(m, "CLIENT_ID_PREFIX", ""),
                    "deviceType": (m.REGISTER_PAYLOAD.get("data") or {}).get("deviceType", "999"),
                })
                return

            if path == "/api/state":
                st = MULTI.status_all()
                # 保留 lastCommand 等兼容字段
                self._json(st)
                return

            if path == "/api/multi/state":
                self._json(MULTI.status_all())
                return

            if path == "/api/multi/config":
                self._json({
                    "multiMode": MULTI.multi_mode,
                    "deviceIds": MULTI.device_ids,
                })
                return

            if path == "/api/logs":
                since = int(qs.get("since", ["0"])[0])
                if MULTI.multi_mode and MULTI.managers:
                    logs, cursor = MULTI.get_logs(since)
                else:
                    logs, cursor = MANAGER.get_logs(since)
                self._json({"logs": logs, "cursor": cursor})
                return

            if path == "/api/messages":
                since = int(qs.get("since", ["0"])[0])
                filt = qs.get("filter", [""])[0]
                msgs, cursor = MANAGER.get_messages(since, filt or None)
                self._json({"messages": msgs, "cursor": cursor})
                return

            if path == "/api/scenarios":
                with MANAGER.lock:
                    ov = set(MANAGER.scenario_overrides.keys())
                    cs = dict(MANAGER.custom_scenarios)
                result = [{"name": k, "desc": v["desc"], "customized": k in ov,
                           "isCustom": False} for k, v in m.SCENARIOS.items()]
                for k, vv in cs.items():
                    result.append({"name": k, "desc": vv.get("desc") or "自定义场景",
                                   "customized": True, "isCustom": True})
                self._json(result)
                return

            if path == "/api/scenario-steps":
                name = qs.get("name", [""])[0]
                steps = MANAGER.get_scenario_steps(name)
                if steps is None:
                    self._json({"ok": False, "msg": "场景不存在：%s" % name, "steps": []})
                else:
                    self._json({"ok": True, "steps": steps})
                return

            if path == "/api/status-buttons":
                self._json({"statuses": MANAGER.get_status_buttons()})
                return

            if path == "/api/register-template":
                self._json({"template": MANAGER.get_register_template()})
                return

            if path == "/api/register-payload":
                dev = qs.get("deviceId", [""])[0]
                dt = qs.get("deviceType", [""])[0]
                if qs.get("default", ["0"])[0] in ("1", "true", "yes"):
                    import copy as _copy
                    p = _copy.deepcopy(m.REGISTER_PAYLOAD)
                else:
                    p = MANAGER.get_register_template()
                if dev:
                    p["deviceId"] = dev
                    if isinstance(p.get("data"), dict):
                        p["data"]["deviceId"] = dev
                if dt and isinstance(p.get("data"), dict):
                    p["data"]["deviceType"] = dt
                self._json({"payload": json.dumps(p, ensure_ascii=False)})
                return

            if path == "/api/saved-config":
                with MANAGER.lock:
                    self._json({
                        "conn": MANAGER.saved_conn or {},
                        "sendBox": MANAGER.saved_send or {},
                        "otaType": MANAGER.ota_type,
                        "moduleType": MANAGER.module_type,
                    })
                return

            if path == "/api/ota-type":
                with MANAGER.lock:
                    self._json({"otaType": MANAGER.ota_type})
                return

            if path == "/api/module-type":
                with MANAGER.lock:
                    self._json({"moduleType": MANAGER.module_type})
                return

            if path == "/api/status-payload":
                try:
                    code = int(qs.get("status", ["0"])[0])
                except Exception:
                    code = 0
                self._json({"payload": MANAGER.build_status_payload(code)})
                return

            if path == "/api/custom-scenarios":
                self._json({"custom": MANAGER.list_custom_scenarios()})
                return

            if path == "/api/diagnose":
                host = qs.get("host", [m.MQTT_HOST])[0]
                port = int(qs.get("port", [str(m.MQTT_PORT)])[0])
                ok, detail = MANAGER.diagnose(host, port)
                self._json({"ok": ok, "detail": detail})
                return

            self._json({"ok": False, "msg": "未知接口：%s" % path}, 404)

        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "msg": "服务端异常：%s" % e}, 500)

    # ---------------- POST ----------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()

        try:
            ok, msg = False, "未知接口"

            if path == "/api/connect":
                ok, msg = MANAGER.connect(
                    body.get("host"), int(body.get("port") or 2883),
                    body.get("deviceId"), body.get("username", ""),
                    body.get("password", ""),
                    protocol_version=int(body.get("protocolVersion") or 5))
            elif path == "/api/disconnect":
                if MULTI.multi_mode:
                    ok, msg = MULTI.disconnect_all()
                else:
                    ok, msg = MANAGER.disconnect()
            elif path == "/api/scenario":
                if MULTI.multi_mode:
                    ok, msg = MULTI.set_auto_scenario_all(body.get("scenario"))
                else:
                    ok, msg = MANAGER.set_auto_scenario(body.get("scenario"))
            elif path == "/api/run-scenario":
                if MULTI.multi_mode:
                    ok, msg = MULTI.run_scenario_all(body.get("scenario"))
                else:
                    ok, msg = MANAGER.run_scenario_now(body.get("scenario"))
            elif path == "/api/status":
                if MULTI.multi_mode:
                    ok, msg = MULTI.send_status_all(body.get("status"))
                else:
                    ok, msg = MANAGER.send_status(body.get("status"))
            elif path == "/api/register":
                payload = body.get("payload")
                # ★ 先保存为模板（这样断开重连也用这份）
                if payload:
                    try:
                        MANAGER.save_register_template(payload)
                        MULTI.sync_register_template(MANAGER.register_template)
                    except Exception:
                        pass
                ok, msg = MANAGER.send_register(payload)
            elif path == "/api/register-template":
                ok, msg = MANAGER.save_register_template(body.get("template"))
                if ok:
                    MULTI.sync_register_template(MANAGER.register_template)
            elif path == "/api/register-template-reset":
                ok, msg = MANAGER.reset_register_template()
                if ok:
                    MULTI.sync_register_template(None)
            elif path == "/api/status-buttons":
                ok, msg = MANAGER.save_status_buttons(body.get("statuses"))
            elif path == "/api/status-buttons-reset":
                ok, msg = MANAGER.reset_status_buttons()
            elif path == "/api/scenario-steps":
                ok, msg = MANAGER.save_scenario_steps(body.get("name"), body.get("steps"))
            elif path == "/api/scenario-reset":
                ok, msg = MANAGER.reset_scenario_steps(body.get("name"))
            elif path == "/api/custom-scenario":
                ok, msg = MANAGER.create_custom_scenario(
                    body.get("name"), body.get("desc", ""), body.get("steps"))
            elif path == "/api/custom-scenario-delete":
                ok, msg = MANAGER.delete_custom_scenario(body.get("name"))
            elif path == "/api/multi/config":
                ok, msg = MULTI.set_multi_mode(
                    body.get("enabled"), body.get("deviceIds"))
            elif path == "/api/connect-all":
                MULTI.sync_all_settings()
                devs = MULTI.device_ids if MULTI.multi_mode else [v("deviceId") or m.DEVICE_ID]
                ok, msg = MULTI.connect_all(
                    body.get("host"), int(body.get("port") or 2883),
                    body.get("username", ""), body.get("password", ""),
                    protocol_version=int(body.get("protocolVersion") or 5))
            elif path == "/api/disconnect-all":
                ok, msg = MULTI.disconnect_all()
            elif path == "/api/ota-type":
                ok, msg = MANAGER.save_ota_type(body.get("otaType"))
            elif path == "/api/module-type":
                ok, msg = MANAGER.save_module_type(body.get("moduleType"))
            elif path == "/api/subscribe":
                ok, msg = MANAGER.subscribe(body.get("topic"))
            elif path == "/api/unsubscribe":
                ok, msg = MANAGER.unsubscribe(body.get("topic"))
            elif path == "/api/publish":
                if MULTI.multi_mode:
                    ok, msg = MULTI.publish_all(body.get("topic"), body.get("payload") or "",
                                                int(body.get("qos") or 0))
                else:
                    ok, msg = MANAGER.publish(body.get("topic"), body.get("payload") or "",
                                              int(body.get("qos") or 0))
            elif path == "/api/messages/clear":
                ok, msg = MANAGER.clear_messages()
            elif path == "/api/save-conn":
                ok, msg = MANAGER.save_conn_config(body)
            elif path == "/api/save-sendbox":
                ok, msg = MANAGER.save_send_box(body)

            self._json({"ok": ok, "msg": msg})

        except Exception as e:
            traceback.print_exc()
            self._json({"ok": False, "msg": "服务端异常：%s" % e}, 500)


# ============================================================================
# 入口
# ============================================================================
def main():
    host = WEB_HOST
    port = WEB_PORT
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            port = int(sys.argv[2])
        except Exception:
            pass

    print("=" * 68)
    print("  OTA 终端模拟器 Web 工作台  %s" % VERSION)
    print("=" * 68)
    print("  访问地址: http://%s:%d" % (host, port))
    print("  配置文件: %s" % MANAGER.CONFIG_FILE)
    print("=" * 68)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
