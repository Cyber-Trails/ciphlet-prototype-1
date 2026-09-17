"""Shared conversation/session structure used by both text and voice (§4.2).

Ciphlet is one assistant, not separate voice and chat assistants — whichever
modality the user is using, it reads and writes the same Session/Message
stream through the same Orchestrator.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ciphlet.brain.base import BrainMode


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    no_memory: bool = False
    # AUTO (default) = free-provider chain; LOCAL_ONLY = Qwen only, no
    # network AI calls (see brain/base.py BrainMode, brain/router.py).
    brain_mode: BrainMode = BrainMode.AUTO
    # True when this id was resumed from a prior run (cross-restart
    # continuity, §5.2) rather than freshly minted — purely informational,
    # for accurate "(resuming...)" vs "(new session)" CLI messaging.
    resumed: bool = False
