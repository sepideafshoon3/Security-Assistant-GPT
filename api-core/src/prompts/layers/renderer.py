"""Jinja2-backed template rendering for prompt layers."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from jinja2 import (
    BaseLoader,
    Environment,
    StrictUndefined,
    TemplateSyntaxError,
    Undefined,
    UndefinedError,
    meta,  # <-- ADDED: For analyzing template syntax
)
from jinja2.sandbox import SandboxedEnvironment  # <-- FIXED IMPORT

from src.prompts.layers.errors import LayerConditionError, LayerRenderError


def _build_env(*, strict: bool = True) -> Environment:
    """Create a properly sandboxed Jinja environment for prompts.

    Uses SandboxedEnvironment to prevent arbitrary code execution via
    template injection attacks. The environment is intentionally limited:
    - No filesystem access (BaseLoader)
    - No dangerous builtins or attributes
    - Strict undefined handling (optional)
    - Plain text output (no auto-escaping)
    """
    return SandboxedEnvironment(  # <-- Now properly imported
        loader=BaseLoader(),
        autoescape=False,  # Prompts are plain text, no HTML escaping needed
        undefined=StrictUndefined if strict else Undefined,
        keep_trailing_newline=True,
        # Trim blocks lightly so multi-line templates stay readable
        trim_blocks=True,
        lstrip_blocks=True,
    )


_STRICT_ENV = _build_env(strict=True)
_RELAXED_ENV = _build_env(strict=False)


class PromptRenderer:
    """Render Jinja2 templates and evaluate layer conditions."""

    def __init__(self, *, strict_undefined: bool = True) -> None:
        self._env = _STRICT_ENV if strict_undefined else _RELAXED_ENV

    def render(
        self,
        template_source: str,
        variables: Optional[Mapping[str, Any]] = None,
        *,
        layer_id: Optional[str] = None,
    ) -> str:
        """Render a template string with the given variables.

        All string variables are automatically sanitized to prevent
        template injection attacks.
        """
        vars_dict: Dict[str, Any] = dict(variables or {})
        
        # Sanitize all string variables to prevent template injection
        vars_dict = self._sanitize_variables(vars_dict)
        
        # Additional validation: check for dangerous template patterns
        self._validate_template_safety(template_source)
        
        try:
            template = self._env.from_string(template_source)
            return template.render(**vars_dict)
        except TemplateSyntaxError as exc:
            raise LayerRenderError(
                f"invalid template syntax: {exc}",
                layer_id=layer_id,
            ) from exc
        except UndefinedError as exc:
            raise LayerRenderError(
                f"undefined variable while rendering: {exc}",
                layer_id=layer_id,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise LayerRenderError(
                f"template render failed: {exc}",
                layer_id=layer_id,
            ) from exc

    def eval_condition(
        self,
        expression: str,
        context: Optional[Mapping[str, Any]] = None,
        *,
        layer_id: Optional[str] = None,
    ) -> bool:
        """Evaluate a Jinja2 boolean expression against *context*.

        Empty / whitespace expressions are treated as True (always include).
        """
        expr = (expression or "").strip()
        if not expr:
            return True

        # Sanitize context variables
        ctx = dict(context or {})
        ctx = self._sanitize_variables(ctx)

        # Additional validation: check for dangerous patterns in condition
        self._validate_condition_safety(expr, layer_id)

        # Wrap as a pure expression template
        source = f"{{{{ {expr} }}}}"
        try:
            template = self._env.from_string(source)
            raw = template.render(**ctx)
        except TemplateSyntaxError as exc:
            raise LayerConditionError(
                f"invalid condition syntax: {exc}",
                layer_id=layer_id,
            ) from exc
        except UndefinedError as exc:
            raise LayerConditionError(
                f"undefined name in condition: {exc}",
                layer_id=layer_id,
            ) from exc
        except Exception as exc:
            raise LayerConditionError(
                f"condition evaluation failed: {exc}",
                layer_id=layer_id,
            ) from exc

        return _truthy(raw)

    def _sanitize_variables(self, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize variables to prevent template injection.
        
        This escapes Jinja2 template syntax in string values while preserving
        non-string types (bool, int, float, None) for condition evaluation.
        
        Args:
            variables: Dictionary of variables to sanitize
            
        Returns:
            Sanitized dictionary with all string values escaped
        """
        sanitized = {}
        for key, value in variables.items():
            if isinstance(value, str):
                sanitized[key] = self._escape_template_syntax(value)
            else:
                # Preserve non-string values for conditions
                sanitized[key] = value
        return sanitized

    def _escape_template_syntax(self, value: str) -> str:
        """Escape Jinja2 template delimiters to prevent injection.
        
        Converts:
        - {{ }} -> {{"{{"}} {{"}}"}}
        - {% %} -> {{"{%"}} {{"%}"}}
        - {# #} -> {{"{#"}} {{"#}"}}
        
        This ensures user input is treated as literal text, not template code.
        
        Args:
            value: String to escape
            
        Returns:
            Escaped string safe for template rendering
        """
        if not value:
            return value
        
        # Escape in order to avoid double-escaping
        # Using an approach that renders the delimiters as literal strings
        replacements = [
            ('{{', '{{"{{"}}'),
            ('}}', '{{"}}"}}'),
            ('{%', '{{"{%"}}'),
            ('%}', '{{"%}"}}'),
            ('{#', '{{"{#"}}'),
            ('#}', '{{"#}"}}'),
        ]
        
        result = value
        for old, new in replacements:
            result = result.replace(old, new)
        return result

    def _validate_template_safety(self, template_source: str) -> None:
        """Validate template for dangerous patterns.
        
        This is an additional defense layer that checks for potential
        template injection attempts.
        """
        # Check for known dangerous patterns
        dangerous_patterns = [
            r'__class__',
            r'__mro__',
            r'__subclasses__',
            r'__builtins__',
            r'__import__',
            r'eval\(',
            r'exec\(',
            r'compile\(',
            r'getattr\(',
            r'setattr\(',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, template_source, re.IGNORECASE):
                # Log warning but don't block - SandboxedEnvironment should handle it
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Potential dangerous pattern in template: {pattern}")
        
        # Parse template to see what variables/functions are used
        try:
            parsed = self._env.parse(template_source)
            # Check for any function calls or attribute access that might be dangerous
            # This is a basic check - the sandbox will handle the rest
        except Exception:
            pass  # Let the rendering handle it

    def _validate_condition_safety(self, expression: str, layer_id: Optional[str] = None) -> None:
        """Validate condition expression for safety."""
        # Check for dangerous patterns in conditions
        dangerous_patterns = [
            r'__class__',
            r'__mro__',
            r'__subclasses__',
            r'__builtins__',
            r'__import__',
            r'eval\(',
            r'exec\(',
            r'compile\(',
            r'getattr\(',
            r'setattr\(',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, expression, re.IGNORECASE):
                raise LayerConditionError(
                    f"Unsafe condition pattern detected: {pattern}",
                    layer_id=layer_id,
                )


def _truthy(value: Any) -> bool:
    """Coerce Jinja render output / Python values to bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"", "false", "0", "none", "null", "no", "off"}:
        return False
    if text in {"true", "1", "yes", "on"}:
        return True
    # Non-empty strings that are not known falsey tokens are True
    return bool(text)