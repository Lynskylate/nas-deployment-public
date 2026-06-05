from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import DebugEvent
from .utils import dataclass_to_dict


@dataclass
class DebugTracer:
    enabled: bool = False
    events: List[DebugEvent] = field(default_factory=list)

    def log(self, step: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        self.events.append(
            DebugEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                step=step,
                message=message,
                payload=payload or {},
            )
        )

    def dump(self, path: Optional[str]) -> None:
        if not self.enabled or not path:
            return
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        serializable = [dataclass_to_dict(event) for event in self.events]
        out.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
