"""确定性的开发会话权限与审计脱敏，不信任客户端身份。"""

import json
import re


class PermissionDenied(Exception):
    """资源不存在或不在当前作用域内，统一拒绝以避免枚举。"""


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {
            str(k): "[已脱敏]"
            if re.search(r"secret|password|token|api.?key|authorization|reasoning|thinking", str(k), re.I)
            else redact(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(redact(json.loads(value), secrets), ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[已脱敏]")
        value = re.sub(r"(?is)<(think|reasoning)>.*?(</\1>|$)", "[已移除推理]", value)
        value = re.sub(r'(?i)(secret|password|api.?key|token)(["\s:=]+)[^\s,"}]+', r"\1\2[已脱敏]", value)
        value = re.sub(
            r'(?i)(?:sk-[\w-]+|Bearer\s+\S+|[a-z]+://[^\s"<>]+|[A-Z]:[\\/][^\s"<>]+)', "[已脱敏]", value
        )
        return value
    return value
