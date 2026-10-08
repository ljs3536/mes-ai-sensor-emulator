# MES Sensor Emulator

설비에 붙은 진동 센서를 흉내 냅니다. PLC(`machine-emulator`)와 분리되어 있고, 파형 설정은 SQLite에 저장됩니다.

- 발행: `mes/machines/{code}/waveform` (base64 float32 블록), `mes/sim/{code}/labels`
- PLC 회전수는 `mes/machines/{code}/state`의 `spindleRpm`을 따릅니다. 상태가 없으면 채널의 정격 RPM을 씁니다.
- `PUT /api/channels`로 샘플레이트, 샘플 개수, 주기, 프리셋(정상/불균형/정렬불량/베어링/풀림)을 바꾸면 다음 블록부터 반영됩니다.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn emulator.main:app --port 8002 --reload
```
