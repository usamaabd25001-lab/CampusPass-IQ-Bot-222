from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NavigationAction(StrEnum):
    BACK = "back"
    HOME = "home"


@dataclass(slots=True, frozen=True)
class NavigationDecision:
    action: NavigationAction
    clear_fsm: bool
    cancel_uncommitted_workflow: bool
    preserve_committed_order: bool = True

    @classmethod
    def back(cls) -> "NavigationDecision":
        return cls(
            action=NavigationAction.BACK,
            clear_fsm=False,
            cancel_uncommitted_workflow=False,
        )

    @classmethod
    def home(cls) -> "NavigationDecision":
        return cls(
            action=NavigationAction.HOME,
            clear_fsm=True,
            cancel_uncommitted_workflow=True,
        )
