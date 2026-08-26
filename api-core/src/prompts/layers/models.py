"""Pydantic models for single-layer and multi-layer prompt composition."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class PromptRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class PromptMode(str, Enum):
    """Composition mode for the prompt engine."""

    SINGLE = "single"
    MULTI = "multi"


class PromptLayerConfig(BaseModel):
    """One stackable prompt layer.

    Layers are sorted by ``order`` ascending, then ``priority`` descending
    (higher priority wins ties). Disabled layers and layers whose
    ``condition`` evaluates to false are skipped.
    """

    id: str = Field(..., min_length=1, description="Stable layer identifier")
    role: PromptRole = PromptRole.SYSTEM
    # Content sources (exactly one required after validation)
    content: Optional[str] = Field(
        default=None,
        description="Literal or Jinja2 template body",
    )
    template: Optional[str] = Field(
        default=None,
        description="Alias for content (Jinja2 template body)",
    )
    content_ref: Optional[str] = Field(
        default=None,
        description="Registry key resolving to a known prompt string",
    )
    enabled: bool = True
    order: int = 0
    priority: int = 0
    condition: Optional[str] = Field(
        default=None,
        description=(
            "Optional Jinja2 boolean expression evaluated against context "
            "(e.g. 'security_mode and has_dark_recon')"
        ),
    )
    variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Layer-local variables merged under global variables",
    )
    required_variables: List[str] = Field(
        default_factory=list,
        description="Variable names that must be present when rendering",
    )

    @field_validator("id")
    @classmethod
    def _id_must_be_nonblank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("id must be a non-empty string")
        return cleaned

    @field_validator("condition")
    @classmethod
    def _condition_strip(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _require_content_source(self) -> "PromptLayerConfig":
        has_content = self.content is not None
        has_template = self.template is not None
        has_ref = bool(self.content_ref and self.content_ref.strip())

        if not (has_content or has_template or has_ref):
            raise ValueError(
                "each layer needs exactly one of: content, template, content_ref"
            )
        if has_content and has_template:
            raise ValueError("provide either content or template, not both")
        if has_ref and (has_content or has_template):
            raise ValueError(
                "content_ref cannot be combined with content or template"
            )
        return self

    def resolved_template(self) -> Optional[str]:
        """Return the template body if this layer uses inline content."""
        if self.template is not None:
            return self.template
        if self.content is not None:
            return self.content
        return None


class PromptStackConfig(BaseModel):
    """Named stack of layers for multi-layer (or single merged) composition."""

    name: str = Field(..., min_length=1)
    mode: PromptMode = PromptMode.MULTI
    layers: List[PromptLayerConfig] = Field(default_factory=list)
    merge_same_role: bool = Field(
        default=False,
        description=(
            "When true, concatenate consecutive same-role layers into one "
            "message (useful for single-system-prompt backends)."
        ),
    )
    separator: str = Field(
        default="\n\n",
        description="Separator used when merging same-role layers",
    )

    @field_validator("name")
    @classmethod
    def _name_nonblank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("stack name must be a non-empty string")
        return cleaned

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "PromptStackConfig":
        seen: set[str] = set()
        dupes: list[str] = []
        for layer in self.layers:
            if layer.id in seen:
                dupes.append(layer.id)
            seen.add(layer.id)
        if dupes:
            raise ValueError(
                f"duplicate layer ids in stack '{self.name}': {sorted(set(dupes))}"
            )
        return self


class AppliedLayerInfo(BaseModel):
    id: str
    role: PromptRole
    order: int
    priority: int
    char_count: int = 0


class SkippedLayerInfo(BaseModel):
    id: str
    reason: str


class ComposedPrompt(BaseModel):
    """Result of single- or multi-layer composition."""

    mode: PromptMode
    system: str = ""
    user: str = ""
    messages: List[Dict[str, str]] = Field(default_factory=list)
    applied_layers: List[AppliedLayerInfo] = Field(default_factory=list)
    skipped_layers: List[SkippedLayerInfo] = Field(default_factory=list)
    stack_name: Optional[str] = None

    def as_chat_messages(
        self,
        *,
        include_empty: bool = False,
    ) -> List[Dict[str, str]]:
        """Return OpenAI-style chat messages.

        Prefer ``messages`` when multi-layer produced discrete role turns;
        otherwise fall back to classic system + user pair.
        """
        if self.messages:
            if include_empty:
                return list(self.messages)
            return [m for m in self.messages if (m.get("content") or "").strip()]

        out: List[Dict[str, str]] = []
        if self.system or include_empty:
            out.append({"role": "system", "content": self.system})
        if self.user or include_empty:
            out.append({"role": "user", "content": self.user})
        return out


class SingleLayerRequest(BaseModel):
    """Convenience input for classic one system + one user composition."""

    system: str = ""
    user: str = ""
    variables: Dict[str, Any] = Field(default_factory=dict)
    system_is_template: bool = True
    user_is_template: bool = True
