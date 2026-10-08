import sqlite3
import threading
from dataclasses import dataclass

from .config import get_settings
from .wave import ALLOWED_N, PRESETS

DEFAULTS = (
    ("MACHINE_A", "VIBRATION", 2560, 1024, 1.0, "normal", 0.2, 3000.0, 1),
    ("MACHINE_B", "VIBRATION", 2560, 1024, 1.0, "bearing_outer", 0.7, 2400.0, 1),
)


@dataclass(frozen=True)
class Channel:
    machine: str
    channel: str
    sample_rate: int
    n_samples: int
    interval_s: float
    preset: str
    severity: float
    rated_rpm: float
    enabled: bool

    def as_dict(self) -> dict:
        return {
            "machine": self.machine,
            "channel": self.channel,
            "sampleRate": self.sample_rate,
            "nSamples": self.n_samples,
            "intervalS": self.interval_s,
            "preset": self.preset,
            "severity": self.severity,
            "ratedRpm": self.rated_rpm,
            "enabled": self.enabled,
        }


class ChannelStore:
    def __init__(self, path: str | None = None):
        self.path = path or get_settings().database_path
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    machine TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    sample_rate INTEGER NOT NULL,
                    n_samples INTEGER NOT NULL,
                    interval_s REAL NOT NULL,
                    preset TEXT NOT NULL,
                    severity REAL NOT NULL,
                    rated_rpm REAL NOT NULL,
                    enabled INTEGER NOT NULL,
                    PRIMARY KEY (machine, channel)
                )
                """
            )
            count = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            if count == 0:
                conn.executemany(
                    """
                    INSERT INTO channels
                    (machine, channel, sample_rate, n_samples, interval_s, preset, severity, rated_rpm, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    DEFAULTS,
                )

    def list_channels(self) -> list[Channel]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM channels ORDER BY machine, channel").fetchall()
        return [self._row(r) for r in rows]

    def get(self, machine: str, channel: str) -> Channel | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM channels WHERE machine = ? AND channel = ?",
                (machine, channel),
            ).fetchone()
        return self._row(row) if row else None

    def upsert(self, ch: Channel) -> Channel:
        self._validate(ch)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO channels
                (machine, channel, sample_rate, n_samples, interval_s, preset, severity, rated_rpm, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine, channel) DO UPDATE SET
                    sample_rate = excluded.sample_rate,
                    n_samples = excluded.n_samples,
                    interval_s = excluded.interval_s,
                    preset = excluded.preset,
                    severity = excluded.severity,
                    rated_rpm = excluded.rated_rpm,
                    enabled = excluded.enabled
                """,
                (
                    ch.machine,
                    ch.channel,
                    ch.sample_rate,
                    ch.n_samples,
                    ch.interval_s,
                    ch.preset,
                    ch.severity,
                    ch.rated_rpm,
                    int(ch.enabled),
                ),
            )
        return ch

    @staticmethod
    def _validate(ch: Channel) -> None:
        if ch.sample_rate < 256 or ch.sample_rate > 25600:
            raise ValueError("샘플레이트는 256~25600 Hz")
        if ch.n_samples not in ALLOWED_N:
            raise ValueError(f"샘플 개수는 {ALLOWED_N} 중 하나")
        if not 0.2 <= ch.interval_s <= 30:
            raise ValueError("수집 주기는 0.2~30초")
        if ch.preset not in PRESETS:
            raise ValueError("알 수 없는 파형 프리셋")
        if not 0 <= ch.severity <= 1:
            raise ValueError("세기는 0~1")

    @staticmethod
    def _row(row: sqlite3.Row) -> Channel:
        return Channel(
            machine=row["machine"],
            channel=row["channel"],
            sample_rate=row["sample_rate"],
            n_samples=row["n_samples"],
            interval_s=row["interval_s"],
            preset=row["preset"],
            severity=row["severity"],
            rated_rpm=row["rated_rpm"],
            enabled=bool(row["enabled"]),
        )
