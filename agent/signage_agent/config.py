import os
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping


@dataclass(frozen=True)
class AgentConfig:
    server_url: str
    device_token: str
    state_dir: Path
    poll_interval: float

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"


def load_config(env: Mapping[str, str] = os.environ) -> AgentConfig:
    """Read settings from environment variables. On the device they come from /etc/signage-agent/agent.env."""
    return AgentConfig(
        server_url=env["SIGNAGE_SERVER_URL"],
        device_token=env["SIGNAGE_DEVICE_TOKEN"],
        state_dir=Path(env.get("SIGNAGE_STATE_DIR", "/var/lib/signage-agent")),
        poll_interval=float(env.get("SIGNAGE_POLL_INTERVAL", "15")),
    )
