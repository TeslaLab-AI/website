"""
Model Router v1 for Engineer 2 (Agent 2).
Selects the appropriate LLM model and tier based on task type, complexity hint, and cost.
Supports configuration-driven routing, runtime overrides, hot reload, and LLMGateway delegation.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Sequence
from pydantic import BaseModel

try:
    import yaml
except ImportError:
    yaml = None

from app.agents.agent_2.router.models import (
    ModelRoute,
    ModelTier,
    RouterConfig,
    TierConfig,
    TaskRule,
)
from app.agents.agent_2.gateway import (
    LLMGateway,
    default_gateway,
    LLMMessage,
    LLMResponse,
)

logger = logging.getLogger("model_router")

DEFAULT_CONFIG_PATH = Path(__file__).parent / "router_config.json"


class ModelRouter:
    """
    Configuration-driven Model Router.
    Routes tasks to Fast, Strong, or Reasoning model tiers.
    """

    # Provider mapping based on known models
    MODEL_PROVIDER_MAP = {
        "claude-3-5-sonnet": "anthropic",
        "claude-3-5-sonnet-20241022": "anthropic",
        "claude-3-5-haiku": "anthropic",
        "claude-3-5-haiku-20241022": "anthropic",
        "gpt-4o": "openai",
        "gpt-4o-mini": "openai",
        "o3-mini": "openai",
        "deepseek-v3": "deepseek",
        "deepseek-chat": "deepseek",
        "deepseek-r1": "deepseek",
        "deepseek-reasoner": "deepseek",
        "gemini-1.5-pro": "gemini",
        "gemini-1.5-flash": "gemini",
    }

    def __init__(
        self,
        config_path: str | Path | None = None,
        config: RouterConfig | dict[str, Any] | None = None,
        gateway: LLMGateway | None = None,
        auto_hot_reload: bool = True,
    ) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.gateway = gateway or default_gateway
        self.auto_hot_reload = auto_hot_reload
        self._is_in_memory_config = config is not None
        if config is not None:
            if isinstance(config, RouterConfig):
                self.config = config
            else:
                self.config = RouterConfig(**config)
        else:
            self.reload_config()

    def _load_config_from_disk(self, path: Path) -> RouterConfig:
        """Load and parse JSON or YAML router configuration from disk."""
        if not path.exists():
            raise FileNotFoundError(f"Router configuration file not found at: {path}")

        raw_text = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("PyYAML is not installed to parse YAML config")
            data = yaml.safe_load(raw_text)
        else:
            data = json.loads(raw_text)

        return RouterConfig(**data)

    def reload_config(self, config_path: str | Path | None = None) -> RouterConfig:
        """Explicitly reload configuration from disk without restarting."""
        self._is_in_memory_config = False
        target_path = Path(config_path) if config_path else self.config_path
        new_config = self._load_config_from_disk(target_path)
        self.config = new_config
        self.config_path = target_path
        try:
            self._last_mtime = os.path.getmtime(target_path)
        except OSError:
            self._last_mtime = 0.0
        logger.info("ModelRouter configuration reloaded successfully from %s", target_path)
        return self.config

    def update_config(self, new_config: RouterConfig | dict[str, Any]) -> None:
        """Programmatically update router configuration."""
        if isinstance(new_config, RouterConfig):
            self.config = new_config
        else:
            self.config = RouterConfig(**new_config)
        self._is_in_memory_config = True

    def _check_hot_reload(self) -> None:
        """Inspect file modification time and reload if file changed on disk."""
        if self._is_in_memory_config or not self.auto_hot_reload or not self.config_path.exists():
            return
        try:
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime > self._last_mtime:
                logger.info("Detected change in %s. Performing hot reload.", self.config_path)
                self.reload_config()
        except OSError:
            pass

    def _resolve_provider(self, model: str, tier_cfg: TierConfig) -> str:
        """Resolve provider name for a given model."""
        if tier_cfg.provider:
            return tier_cfg.provider
        clean = model.strip().lower()
        if clean in self.MODEL_PROVIDER_MAP:
            return self.MODEL_PROVIDER_MAP[clean]
        try:
            return self.gateway.get_adapter_for_model(model).provider_name
        except Exception:
            return "unknown"

    def get_model_for_task(
        self,
        task_type: str,
        complexity_hint: str | None = None,
        override_tier: str | None = None,
    ) -> ModelRoute:
        """
        Select model, tier, provider, and fallback for a task.

        Args:
            task_type: Type of task (e.g. 'triage', 'classification', 'planning', 'diagnosis', 'complex_logic_bug')
            complexity_hint: Optional complexity indicator (e.g. 'low', 'medium', 'high', 'complex')
            override_tier: Optional runtime tier override ('fast', 'strong', 'reasoning')

        Returns:
            ModelRoute containing routing decision.
        """
        self._check_hot_reload()

        clean_task = task_type.strip().lower()
        clean_hint = complexity_hint.strip().lower() if complexity_hint else None
        clean_override = override_tier.strip().lower() if override_tier else None

        # 1. Handle runtime tier override
        if clean_override:
            if clean_override not in self.config.tiers:
                raise ValueError(
                    f"Unknown override_tier '{override_tier}'. "
                    f"Allowed tiers: {list(self.config.tiers.keys())}"
                )
            tier_name = clean_override
            tier_cfg = self.config.tiers[tier_name]
            model = tier_cfg.primary_model
            provider = self._resolve_provider(model, tier_cfg)
            return ModelRoute(
                task_type=task_type,
                tier=tier_name,
                model=model,
                provider=provider,
                fallback_model=tier_cfg.fallback_model,
                is_override=True,
                reason=f"Runtime override explicitly requested tier '{tier_name}'",
            )

        # 2. Look up configured task rule
        task_rule = self.config.task_rules.get(clean_task)
        if task_rule:
            tier_name = task_rule.tier.lower()
            reason = f"Configured task rule mapped '{task_type}' to tier '{tier_name}'"
        else:
            # Fallback for unknown/invalid task types
            tier_name = self.config.default_tier.lower()
            reason = f"Unknown task type '{task_type}' defaulted to '{tier_name}' tier"

        # 3. Check complexity escalation
        if clean_hint and clean_hint in self.config.complexity_escalations:
            escalated_tier = self.config.complexity_escalations[clean_hint].lower()
            if escalated_tier in self.config.tiers and escalated_tier != tier_name:
                reason += f" (escalated from '{tier_name}' to '{escalated_tier}' due to complexity_hint='{complexity_hint}')"
                tier_name = escalated_tier

        # 4. Resolve tier model and provider
        if tier_name not in self.config.tiers:
            tier_name = self.config.default_tier.lower()
        tier_cfg = self.config.tiers[tier_name]

        model = task_rule.override_model if (task_rule and task_rule.override_model) else tier_cfg.primary_model
        provider = self._resolve_provider(model, tier_cfg)

        return ModelRoute(
            task_type=task_type,
            tier=tier_name,
            model=model,
            provider=provider,
            fallback_model=tier_cfg.fallback_model,
            is_override=False,
            reason=reason,
        )

    def complete(
        self,
        task_type: str,
        messages: Sequence[dict[str, Any] | LLMMessage],
        complexity_hint: str | None = None,
        override_tier: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
        gateway: LLMGateway | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Route and execute completion through the Task 19 LLM Gateway.
        """
        route = self.get_model_for_task(
            task_type=task_type,
            complexity_hint=complexity_hint,
            override_tier=override_tier,
        )

        gw = gateway or self.gateway
        return gw.complete(
            messages=messages,
            model=route.model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
            fallback_model=route.fallback_model,
            **kwargs,
        )


# Global default ModelRouter instance
default_router = ModelRouter()


def get_model_for_task(
    task_type: str,
    complexity_hint: str | None = None,
    override_tier: str | None = None,
) -> ModelRoute:
    """Convenience functional access to the default ModelRouter."""
    return default_router.get_model_for_task(
        task_type=task_type,
        complexity_hint=complexity_hint,
        override_tier=override_tier,
    )
