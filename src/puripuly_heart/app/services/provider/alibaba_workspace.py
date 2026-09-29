from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, replace
from typing import Literal
from uuid import uuid4

from puripuly_heart.app.ports.provider_verifier import ProviderVerifierPort
from puripuly_heart.app.ports.settings_view import (
    AlibabaCapabilityEvidence,
    AlibabaConnectionDraftSnapshot,
)
from puripuly_heart.app.services.canonical_settings_persistence import SettingsOwner
from puripuly_heart.app.services.provider.provider_settings import ProviderSettingsOwner
from puripuly_heart.config.alibaba_connection import (
    AlibabaEndpointMode,
    AlibabaRegion,
    AlibabaRegionalSettings,
    alibaba_credential_sources,
    normalize_api_host,
    resolve_alibaba_connection,
)
from puripuly_heart.config.runtime_resolution import QWEN_AUDIO_STT_MODEL
from puripuly_heart.config.settings_vnext.schema import AppSettingsVNext

_REGIONS = frozenset(("beijing", "singapore"))


def _fingerprint(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _failure_kind(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    codes = [getattr(exc, "error_code", "")]
    if response is not None:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                codes.append(payload.get("code", ""))
                error = payload.get("error", {})
                if isinstance(error, dict):
                    codes.append(error.get("code", ""))
        except ValueError, AttributeError, TypeError:
            pass
    normalized = {code.lower() for code in codes if isinstance(code, str)}
    if status in (401, 403) or normalized.intersection(
        {"unauthorized", "accessdenied", "invalidapikey"}
    ):
        return "authentication_or_access"
    if status == 404 or normalized.intersection(
        {"model_not_found", "modelnotfound", "modelnotavailable"}
    ):
        return "model_unavailable"
    if status == 429 or normalized.intersection({"ratelimit", "throttling"}):
        return "rate_limited"
    if isinstance(exc, (OSError, TimeoutError, ConnectionError)) or isinstance(
        exc.__cause__, OSError
    ):
        return "network"
    return "ambiguous"


@dataclass(slots=True)
class AlibabaWorkspaceOwner:
    settings: SettingsOwner
    provider_settings: ProviderSettingsOwner
    verifier: ProviderVerifierPort
    _draft: AlibabaConnectionDraftSnapshot | None = field(default=None, init=False)
    _base: AppSettingsVNext | None = field(default=None, init=False)
    _credential_fingerprint: str | None = field(default=None, init=False)
    _regions: dict[str, tuple[AlibabaEndpointMode, str]] = field(default_factory=dict, init=False)
    _edited_regions: set[str] = field(default_factory=set, init=False)
    _active_evidence: dict[
        tuple[str, str], tuple[object, str | None, AlibabaCapabilityEvidence]
    ] = field(default_factory=dict, init=False)

    def _current(self) -> AppSettingsVNext:
        current = self.settings.canonical
        if not isinstance(current, AppSettingsVNext):
            raise RuntimeError("Canonical settings unavailable")
        return current

    async def _key(self, region: AlibabaRegion) -> tuple[str | None, bool]:
        current = self._current()
        store = self.provider_settings.secret_store_factory(current)
        regional_key, legacy_keys, env_vars = alibaba_credential_sources(region)
        for name in (regional_key, *legacy_keys):
            secret = await store.snapshot_secret(name)
            if secret.value:
                return secret.value, True
        for name in env_vars:
            value = os.getenv(name)
            if value:
                return value, False
        return None, False

    async def begin(self) -> AlibabaConnectionDraftSnapshot:
        current = self._current()
        self._base = current
        self._edited_regions.clear()
        region = current.intent.translation.qwen.region
        regional = getattr(current.intent.translation.qwen, region)
        self._regions = {
            name: (
                getattr(current.intent.translation.qwen, name).endpoint_mode,
                getattr(current.intent.translation.qwen, name).api_host,
            )
            for name in _REGIONS
        }
        key, _ = await self._key(region)
        self._credential_fingerprint = _fingerprint(key)
        self._draft = self._snapshot(
            token=uuid4().hex,
            scope="draft",
            region=region,
            mode=regional.endpoint_mode,
            host=regional.api_host,
            key_present=bool(key),
            current=current,
        )
        return self._draft

    async def active(self) -> AlibabaConnectionDraftSnapshot:
        current = self._current()
        region = current.intent.translation.qwen.region
        regional = getattr(current.intent.translation.qwen, region)
        key, _ = await self._key(region)
        snapshot = self._snapshot(
            token="",
            scope="active",
            region=region,
            mode=regional.endpoint_mode,
            host=regional.api_host,
            key_present=bool(key),
            current=current,
        )
        evidence = {}
        for name in ("asr", "translation"):
            previous = self._active_evidence.get((region, name))
            if previous is None:
                continue
            connection, fingerprint, result = previous
            if (
                connection == snapshot.connection
                and fingerprint == _fingerprint(key)
                and result.model == getattr(snapshot, name).model
            ):
                evidence[name] = result
            else:
                evidence[name] = replace(getattr(snapshot, name), state="invalidated")
        return replace(snapshot, **evidence)

    def _snapshot(
        self,
        *,
        token: str,
        scope: Literal["draft", "active"],
        region: AlibabaRegion,
        mode: AlibabaEndpointMode,
        host: str,
        key_present: bool,
        current: AppSettingsVNext,
    ) -> AlibabaConnectionDraftSnapshot:
        regional = getattr(current.intent.translation.qwen, region)
        connection = None
        try:
            connection = resolve_alibaba_connection(
                region, AlibabaRegionalSettings(mode, host, regional.revision)
            )
        except ValueError:
            pass
        incomplete = connection is None or not key_present
        asr = AlibabaCapabilityEvidence(
            "asr", QWEN_AUDIO_STT_MODEL, "incomplete" if incomplete else "unverified"
        )
        translation = AlibabaCapabilityEvidence(
            "translation",
            current.intent.translation.qwen.llm_model,
            "incomplete" if incomplete else "unverified",
        )
        affected = []
        if current.intent.stt.provider == "qwen_audio":
            affected.append("self_qwen_audio")
        if current.intent.peer_stt.provider == "qwen_audio":
            affected.append("peer_qwen_audio")
        if current.intent.translation.model == "qwen38_flash":
            affected.append("qwen_translation")
        return AlibabaConnectionDraftSnapshot(
            token,
            scope,
            current.intent.translation.qwen.region,
            region,
            mode,
            host,
            key_present,
            connection,
            asr,
            translation,
            tuple(affected),
        )

    async def read(self) -> AlibabaConnectionDraftSnapshot:
        draft = self._require_draft()
        current = self._current()
        key, _ = await self._key(draft.region)
        base = self._base
        qwen = current.intent.translation.qwen
        if (
            base is None
            or base.intent.translation.qwen.region != qwen.region
            or getattr(base.intent.translation.qwen, draft.region) != getattr(qwen, draft.region)
            or _fingerprint(key) != self._credential_fingerprint
        ):
            return replace(
                draft,
                key_present=bool(key),
                asr=replace(draft.asr, state="invalidated"),
                translation=replace(draft.translation, state="invalidated"),
            )
        if base.intent.translation.qwen.llm_model != qwen.llm_model:
            return replace(draft, translation=replace(draft.translation, state="invalidated"))
        return draft

    def _require_draft(self) -> AlibabaConnectionDraftSnapshot:
        if self._draft is None:
            raise RuntimeError("No Alibaba connection draft")
        return self._draft

    async def edit(
        self,
        *,
        token: str,
        region: AlibabaRegion | None = None,
        endpoint_mode: AlibabaEndpointMode | None = None,
        api_host: str | None = None,
    ) -> AlibabaConnectionDraftSnapshot:
        old = self._require_draft()
        if token != old.token:
            raise ValueError("Alibaba draft changed")
        current = self._current()
        if region is not None and region not in _REGIONS:
            raise ValueError("Invalid Alibaba region")
        if endpoint_mode is not None and endpoint_mode not in (
            "legacy_shared",
            "workspace_dedicated",
        ):
            raise ValueError("Invalid Alibaba endpoint mode")
        target = region or old.region
        self._regions[old.region] = (old.endpoint_mode, old.api_host)
        mode, host = self._regions[target]
        if endpoint_mode is not None:
            mode = endpoint_mode
        if api_host is not None:
            host = api_host
        if not isinstance(host, str):
            raise ValueError("Invalid Alibaba API Host")
        try:
            host = normalize_api_host(host, target)
        except ValueError:
            if mode == "legacy_shared":
                host = ""
        if (mode, host) != self._regions[target]:
            self._edited_regions.add(target)
        self._regions[target] = (mode, host)
        key, _ = await self._key(target)
        self._credential_fingerprint = _fingerprint(key)
        self._draft = self._snapshot(
            token=uuid4().hex,
            scope="draft",
            region=target,
            mode=mode,
            host=host,
            key_present=bool(key),
            current=current,
        )
        return self._draft

    async def verify(
        self,
        *,
        token: str,
        capability: Literal["asr", "translation", "both"],
        api_key: str | None = None,
    ) -> AlibabaConnectionDraftSnapshot:
        draft = await self.read()
        if token != draft.token or draft.asr.state == "invalidated":
            raise ValueError("Alibaba draft changed")
        if capability not in ("asr", "translation", "both"):
            raise ValueError("Invalid Alibaba verification capability")
        if draft.connection is None:
            return draft
        effective_key, persisted = await self._key(draft.region)
        key = api_key if api_key is not None else effective_key
        if not key:
            return draft
        selected = ("asr", "translation") if capability == "both" else (capability,)
        if any(getattr(draft, name).state == "invalidated" for name in selected):
            raise ValueError("Alibaba draft changed")
        key_revision = _fingerprint(key)
        checking = {
            name: replace(
                getattr(draft, name),
                state="checking",
                credential_revision=key_revision,
                credential_saved=persisted and key_revision == self._credential_fingerprint,
            )
            for name in selected
        }
        self._draft = replace(draft, **checking)
        for name in selected:
            try:
                if name == "asr":
                    success = await self.verifier.verify_qwen_audio_api_key(
                        key, endpoint=draft.connection.websocket_url, model=draft.asr.model
                    )
                else:
                    success = await self.verifier.probe_qwen_llm_api_key(
                        key,
                        base_url=draft.connection.native_url,
                        model=draft.translation.model,
                    )
                state = "verified" if success else "failed"
                failure = None if success else "ambiguous"
            except Exception as exc:
                state = "failed"
                failure = _failure_kind(exc)
            latest = await self.read()
            if latest.token != token or getattr(latest, name).state == "invalidated":
                return replace(
                    latest, **{name: replace(getattr(latest, name), state="invalidated")}
                )
            self._draft = replace(
                latest, **{name: replace(getattr(latest, name), state=state, failure_kind=failure)}
            )
        return self._require_draft()

    async def apply(self, *, token: str, apply_settings) -> object:
        draft = await self.read()
        if token != draft.token or draft.asr.state == "invalidated":
            raise ValueError("Alibaba draft changed")
        if draft.connection is None:
            raise ValueError("Alibaba workspace API Host is required")
        current = self._current()
        qwen = current.intent.translation.qwen
        changes = {}
        base = self._base
        if base is None:
            raise ValueError("Alibaba draft changed")
        for region in self._edited_regions:
            regional = getattr(qwen, region)
            if getattr(base.intent.translation.qwen, region) != regional:
                raise ValueError("Alibaba draft changed")
            mode, host = self._regions[region]
            if (regional.endpoint_mode, regional.api_host) != (mode, host):
                changes[region] = replace(
                    regional, endpoint_mode=mode, api_host=host, revision=regional.revision + 1
                )
        updated = replace(
            current,
            intent=replace(
                current.intent,
                translation=replace(
                    current.intent.translation,
                    qwen=replace(qwen, region=draft.region, **changes),
                ),
            ),
        )
        result = await apply_settings(updated)
        if result:
            active = self._current()
            active_region = active.intent.translation.qwen.region
            active_connection = resolve_alibaba_connection(
                active_region, getattr(active.intent.translation.qwen, active_region)
            )
            for name in ("asr", "translation"):
                evidence = getattr(draft, name)
                if evidence.state == "verified" and evidence.credential_saved:
                    self._active_evidence[(active_region, name)] = (
                        active_connection,
                        evidence.credential_revision,
                        evidence,
                    )
            self._draft = None
            self._base = None
            self._regions.clear()
            self._edited_regions.clear()
        return result

    def cancel(self, *, token: str) -> None:
        if token != self._require_draft().token:
            raise ValueError("Alibaba draft changed")
        self._draft = None
        self._regions.clear()
        self._edited_regions.clear()
        self._base = None
