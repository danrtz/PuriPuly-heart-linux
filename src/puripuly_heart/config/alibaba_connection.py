from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

AlibabaRegion = Literal["beijing", "singapore"]
AlibabaEndpointMode = Literal["legacy_shared", "workspace_dedicated"]

_SHARED_HOSTS = {
    "beijing": "dashscope.aliyuncs.com",
    "singapore": "dashscope-intl.aliyuncs.com",
}
_WORKSPACE_SUFFIXES = {
    "beijing": ".cn-beijing.maas.aliyuncs.com",
    "singapore": ".ap-southeast-1.maas.aliyuncs.com",
}
_CREDENTIAL_REFS = {
    "beijing": "qwen:beijing",
    "singapore": "qwen:singapore",
}
_WORKSPACE_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)


def alibaba_credential_sources(
    region: AlibabaRegion,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    if region not in _CREDENTIAL_REFS:
        raise ValueError("Invalid Alibaba region")
    return (
        f"alibaba_api_key_{region}",
        ("alibaba_api_key",),
        (f"ALIBABA_API_KEY_{region.upper()}", "ALIBABA_API_KEY", "DASHSCOPE_API_KEY"),
    )


def normalize_api_host(value: str, region: AlibabaRegion) -> str:
    if not isinstance(value, str) or region not in _WORKSPACE_SUFFIXES:
        raise ValueError("Invalid Alibaba API Host for selected region")
    candidate = value.strip()
    if not candidate:
        return ""
    if "://" in candidate:
        try:
            parsed = urlsplit(candidate)
            if (
                parsed.scheme != "https"
                or parsed.path not in ("", "/", "/api/v1", "/compatible-mode/v1")
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
            candidate = parsed.netloc
        except ValueError:
            raise ValueError("Invalid Alibaba API Host for selected region") from None
    host = candidate.lower()
    suffix = _WORKSPACE_SUFFIXES[region]
    if not host.endswith(suffix) or not _WORKSPACE_ID.fullmatch(host[: -len(suffix)]):
        raise ValueError("Invalid Alibaba API Host for selected region")
    return host


def workspace_api_host_region(value: str) -> tuple[AlibabaRegion, str] | None:
    for region in _WORKSPACE_SUFFIXES:
        try:
            host = normalize_api_host(value, region)
        except ValueError:
            continue
        if host:
            return region, host
    return None


def validated_native_url(value: str, region: AlibabaRegion) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.path != "/api/v1" or parsed.query or parsed.fragment:
            raise ValueError
        if parsed.netloc == _SHARED_HOSTS[region]:
            return f"https://{_SHARED_HOSTS[region]}/api/v1"
        host = normalize_api_host(parsed.netloc, region)
        return f"https://{host}/api/v1"
    except ValueError, KeyError:
        raise ValueError("Invalid Alibaba native endpoint") from None


def validated_websocket_url(value: str, region: AlibabaRegion) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "wss"
            or parsed.path != "/api-ws/v1/inference"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        if parsed.netloc == _SHARED_HOSTS[region]:
            return f"wss://{_SHARED_HOSTS[region]}/api-ws/v1/inference"
        host = normalize_api_host(parsed.netloc, region)
        return f"wss://{host}/api-ws/v1/inference"
    except ValueError, KeyError:
        raise ValueError("Invalid Alibaba WebSocket endpoint") from None


@dataclass(frozen=True, slots=True)
class AlibabaRegionalSettings:
    endpoint_mode: AlibabaEndpointMode = "legacy_shared"
    api_host: str = ""
    revision: int = 0

    def __post_init__(self) -> None:
        if self.endpoint_mode not in ("legacy_shared", "workspace_dedicated"):
            raise ValueError("Invalid Alibaba endpoint mode")
        if not isinstance(self.api_host, str):
            raise ValueError("Invalid Alibaba API Host")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 0
        ):
            raise ValueError("Invalid Alibaba connection revision")


@dataclass(frozen=True, slots=True)
class AlibabaConnection:
    region: AlibabaRegion
    endpoint_mode: AlibabaEndpointMode
    host: str
    credential_reference: str
    revision: int

    @property
    def compatible_url(self) -> str:
        return f"https://{self.host}/compatible-mode/v1"

    @property
    def native_url(self) -> str:
        return f"https://{self.host}/api/v1"

    @property
    def websocket_url(self) -> str:
        return f"wss://{self.host}/api-ws/v1/inference"


def resolve_alibaba_connection(
    region: AlibabaRegion,
    settings: AlibabaRegionalSettings,
) -> AlibabaConnection:
    if region not in _SHARED_HOSTS:
        raise ValueError("Invalid Alibaba region")
    if settings.endpoint_mode == "legacy_shared":
        host = _SHARED_HOSTS[region]
    else:
        host = normalize_api_host(settings.api_host, region)
        if not host:
            raise ValueError("Alibaba workspace API Host is required")
    return AlibabaConnection(
        region, settings.endpoint_mode, host, _CREDENTIAL_REFS[region], settings.revision
    )
