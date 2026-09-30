"""Deployer contract. Deployers never decide *what* ships; they only move approved, guard-checked
changes into the client's stack. status 'draft_open' means a human still has to merge/publish."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Change:
    page_id: int
    url: str
    source_path: str | None
    old_html: str
    new_html: str
    proposal_id: int | None = None
    rationale: str = ""
    is_new: bool = False  # a page that doesn't exist on the live site yet


@dataclass
class DeployResult:
    status: str  # applied | draft_open | failed
    external_ref: str | None = None
    details: dict = field(default_factory=dict)


class Deployer(ABC):
    name = ""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def deploy(self, changes: list[Change], *, label: str, message: str, extras: dict[str, str] | None = None) -> DeployResult:
        """extras: extra files to include in a package (relative path -> text), e.g. the report and site-files/llms.txt."""
        ...


_REGISTRY: dict[str, type[Deployer]] = {}


def register(name: str):
    def deco(cls):
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def build_deployer(config: dict) -> Deployer:
    kind = config.get("type", "export")
    if kind not in _REGISTRY:
        raise ValueError(f"unknown deployer {kind!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[kind](config)
