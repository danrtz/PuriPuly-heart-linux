from __future__ import annotations

_RECOGNITION_CAUSES = frozenset(
    {
        "buffer_exhausted",
        "cancelled",
        "closed",
        "provider_epoch_ended",
        "provider_final_timeout",
        "provider_result_too_large",
        "provider_retirement_drain_timeout",
        "provider_session_lifetime_exceeded",
        "provider_stable_prefix_inconsistent",
        "provider_turn_failed_before_terminal",
        "provider_turn_identity_mismatch",
        "provider_update_sequence_disorder",
        "provider_not_ready",
        "provider_event_stream_failed",
        "provider_begin_timeout",
        "provider_send_timeout",
        "provider_seal_timeout",
        "provider_abort_timeout",
        "provider_begin_failed",
        "provider_send_failed",
        "provider_seal_failed",
        "provider_abort_failed",
        "soniox_request_failed",
        "soniox_protocol_ambiguity",
        "soniox_write_failed",
        "soniox_receive_failed",
        "soniox_keepalive_failed",
        "soniox_connection_ended",
        "soniox_stream_finished",
        "soniox_idle_authoritative_text",
        "soniox_token_buffer_overflow",
        "stopped",
        "toggle_off",
    }
)


def recognition_cause(reason: str | None) -> str:
    if reason is None:
        return "none"
    category = reason.partition(":")[0]
    if category in _RECOGNITION_CAUSES:
        return category
    return "unclassified"
