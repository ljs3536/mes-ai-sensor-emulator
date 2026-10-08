"""PIEZO 진동 파형 에뮬레이터.

현재 기능:
- MES에 연결된 센서 목록을 읽어 설비·센서별로 파형 블록을 MQTT에 발행
- 결함 파형 미리보기와 예전 채널 설정 API를 제공
실제 수집 설정(주기, 샘플레이트, 샘플 수, 프리셋)의 기준은 MES MariaDB다.
"""

import logging
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .config import get_settings
from .db import Channel, ChannelStore
from .publisher import Publisher
from .wave import ALLOWED_N, PRESETS, synthesize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

store = ChannelStore()
publisher: Publisher | None = None


class Schema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ChannelIn(Schema):
    machine: str = Field(min_length=1, max_length=32)
    channel: str = Field(min_length=1, max_length=32)
    sample_rate: int
    n_samples: int
    interval_s: float
    preset: str
    severity: float
    rated_rpm: float = 1800
    enabled: bool = True


class PreviewIn(Schema):
    sample_rate: int
    n_samples: int
    rpm: float = 1800
    preset: str = "normal"
    severity: float = 0.3


@asynccontextmanager
async def lifespan(_: FastAPI):
    global publisher
    publisher = Publisher(store)
    publisher.start()
    yield
    publisher.stop()


app = FastAPI(title="MES Sensor Emulator", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "mqtt": bool(publisher and publisher.connected())}


@app.get("/api/presets")
def presets():
    return {"presets": [{"id": k, "label": v} for k, v in PRESETS.items()], "sampleCounts": list(ALLOWED_N)}


@app.get("/api/channels")
def channels():
    return [ch.as_dict() for ch in store.list_channels()]


@app.put("/api/channels")
def save_channel(body: ChannelIn):
    ch = Channel(
        machine=body.machine.strip(),
        channel=body.channel.strip(),
        sample_rate=body.sample_rate,
        n_samples=body.n_samples,
        interval_s=body.interval_s,
        preset=body.preset,
        severity=body.severity,
        rated_rpm=body.rated_rpm,
        enabled=body.enabled,
    )
    try:
        saved = store.upsert(ch)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return saved.as_dict()


@app.post("/api/preview")
def preview(body: PreviewIn):
    if body.preset not in PRESETS or body.n_samples not in ALLOWED_N:
        raise HTTPException(422, "프리셋 또는 샘플 개수가 올바르지 않습니다")
    if body.sample_rate < 256 or body.sample_rate > 25600:
        raise HTTPException(422, "샘플레이트가 범위를 벗어났습니다")
    samples = synthesize(
        body.sample_rate,
        body.n_samples,
        body.rpm,
        body.preset,
        body.severity,
        np.random.default_rng(1),
    )
    return {
        "sampleRate": body.sample_rate,
        "n": body.n_samples,
        "resolutionHz": round(body.sample_rate / body.n_samples, 4),
        "durationS": round(body.n_samples / body.sample_rate, 4),
        "samples": samples.tolist(),
    }
