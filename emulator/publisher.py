"""설정된 채널의 파형 블록을 MQTT로 발행한다. PLC 상태는 게이트웨이 state 토픽에서 읽는다."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import paho.mqtt.client as mqtt

from .config import get_settings
from .db import Channel, ChannelStore
from .wave import synthesize

log = logging.getLogger("emulator.publish")
KST = ZoneInfo("Asia/Seoul")


class Publisher:
    def __init__(self, store: ChannelStore):
        s = get_settings()
        self.store = store
        self.prefix = s.mqtt_topic_prefix
        self.rng = np.random.default_rng()
        self._rpm: dict[str, float] = {}
        self._running: dict[str, bool] = {}
        self._last: dict[tuple[str, str], float] = {}
        self._channels: list[Channel] = []
        self._channels_at = 0.0
        self._stop = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sensor-emulator")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = lambda *_: log.warning("MQTT 연결 끊김, 재연결 대기")
        self.client.reconnect_delay_set(1, 30)
        self.client.connect_async(s.mqtt_host, s.mqtt_port, keepalive=30)

    def start(self) -> None:
        self.client.loop_start()
        self._thread = threading.Thread(target=self._loop, name="waveform", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.client.loop_stop()
        self.client.disconnect()

    def connected(self) -> bool:
        return self.client.is_connected()

    def _on_connect(self, client, _u, _f, reason_code, _p):
        if reason_code.is_failure:
            log.error("MQTT 연결 거부: %s", reason_code)
            return
        client.subscribe(f"{self.prefix}/machines/+/state", qos=0)
        log.info("MQTT 연결, PLC state 구독")

    def _on_message(self, _c, _u, msg):
        parts = msg.topic.split("/")
        if parts[-1] != "state":
            return
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            return
        code = parts[-2]
        self._rpm[code] = float(payload.get("spindleRpm") or 0)
        self._running[code] = payload.get("state") == "RUNNING" and payload.get("plcOnline", True)

    def rpm_for(self, ch: Channel) -> float:
        # 스핀들이 돌고 있으면 PLC 회전수를 쓰고, 정지 중에는 정격 RPM으로 파형을 만든다.
        live = self._rpm.get(ch.machine, 0.0)
        if self._running.get(ch.machine) and live > 30:
            return live
        return ch.rated_rpm

    def _refresh_channels(self, now: float) -> None:
        if self._channels and now - self._channels_at < 30:
            return
        self._channels_at = now
        try:
            response = httpx.get(f"{get_settings().mes_url}/api/sensors", timeout=5)
            response.raise_for_status()
            rows = response.json()
        except httpx.HTTPError as e:
            log.warning("MES 센서 목록을 가져오지 못했습니다: %s", e)
            return
        rated = {"MACHINE_A": 3000.0, "MACHINE_B": 2400.0}
        self._channels = [
            Channel(
                machine=row["machineCode"],
                channel=row["code"],
                sample_rate=int(row["sampleRate"]),
                n_samples=int(row["nSamples"]),
                interval_s=float(row["intervalS"]),
                preset=row["preset"],
                severity=float(row["severity"]),
                rated_rpm=rated.get(row["machineCode"], 1800.0),
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]
        log.info("MES 센서 %d개 반영, 전송 주기 %s초", len(self._channels), 
                 ", ".join(f"{c.machine}/{c.channel}={int(c.interval_s)}" for c in self._channels))

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            self._refresh_channels(now)
            for ch in self._channels:
                if not ch.enabled:
                    continue
                key = (ch.machine, ch.channel)
                last = self._last.get(key)
                if last is not None and now - last < ch.interval_s:
                    continue
                self._last[key] = now
                self._publish(ch)
            self._stop.wait(0.2)

    def _publish(self, ch: Channel) -> None:
        if not self.client.is_connected():
            return
        rpm = self.rpm_for(ch)
        samples = synthesize(ch.sample_rate, ch.n_samples, rpm, ch.preset, ch.severity, self.rng)
        ts = datetime.now(KST).isoformat(timespec="milliseconds")
        body = {
            "ts": ts,
            "channel": ch.channel,
            "sampleRate": ch.sample_rate,
            "n": ch.n_samples,
            "rpm": round(rpm, 2),
            "unit": "g",
            "samples": base64.b64encode(samples.tobytes()).decode("ascii"),
        }
        self.client.publish(f"{self.prefix}/machines/{ch.machine}/waveform", json.dumps(body), qos=0)
        label = {
            "ts": ts,
            "fault": "none" if ch.preset == "normal" else ch.preset,
            "severity": ch.severity,
            "preset": ch.preset,
        }
        self.client.publish(f"{self.prefix}/sim/{ch.machine}/labels", json.dumps(label), qos=0)
