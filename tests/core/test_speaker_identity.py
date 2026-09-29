from dataclasses import replace
from uuid import uuid4

from puripuly_heart.core.speaker_identity import PeerSpeakerIdentityAllocator
from puripuly_heart.domain.models import FinalLanguageRun, FinalSpeakerRun, Transcript


def _transcript(speaker, scope, order, *, language="en", state=None):
    text = "words"
    return Transcript(
        utterance_id=uuid4(),
        text=text,
        is_final=True,
        channel="peer",
        final_language_runs=(FinalLanguageRun(text, language),),
        final_speaker_runs=(
            FinalSpeakerRun(
                text,
                speaker,
                scope,
                source="soniox",
                attribution_state=state or ("identified" if speaker else "missing"),
            ),
        ),
        publication_generation=1,
        source_order=order,
        source_text_range=(0, len(text)),
        source_text_revision="revision",
    )


def test_identity_reuses_scope_key_across_unknown_language_and_returning_speaker():
    allocator = PeerSpeakerIdentityAllocator()
    readings = [
        _transcript("A", "session", 1),
        _transcript("B", "session", 2),
        _transcript("A", "session", 3, language="es"),
        _transcript(None, "session", 4),
        _transcript("A", "session", 5),
        _transcript("B", "session", 6),
    ]
    assignments = [allocator.observe(turn, child_sequence=0) for turn in readings]
    assert [assignment.palette_index for assignment in assignments] == [0, 1, 0, None, 0, 1]
    assert assignments[0].source_text_range == (0, 5)
    assert assignments[0].source_text_revision == "revision"
    assert assignments[3].attribution.state == "missing"


def test_new_connection_drops_mapping_without_contamination_from_late_old_completion():
    allocator = PeerSpeakerIdentityAllocator()
    old = _transcript("A", "old", 1)
    new = _transcript("A", "new", 3)
    late = _transcript("B", "old", 2)
    first = allocator.observe(old, child_sequence=0)
    second = allocator.observe(new, child_sequence=0)
    third = allocator.observe(late, child_sequence=0)
    next_speaker = allocator.observe(_transcript("B", "new", 4), child_sequence=0)
    assert first.palette_index == second.palette_index == 0
    assert first.attribution.key != second.attribution.key
    assert third.palette_index is None
    assert next_speaker.palette_index == 1


def test_same_scope_peers_a_to_f_get_four_colors_then_overflow_without_reuse():
    allocator = PeerSpeakerIdentityAllocator()
    speakers = ["A", "B", "C", "D", "E", "F"]
    first_pass = [
        allocator.observe(_transcript(speaker, "session", order), child_sequence=0)
        for order, speaker in enumerate(speakers, start=1)
    ]
    assert [item.palette_index for item in first_pass] == [0, 1, 2, 3, None, None]
    assert [item.palette_overflow for item in first_pass] == [False] * 4 + [True, True]

    returning = [
        allocator.observe(_transcript(speaker, "session", order), child_sequence=0)
        for order, speaker in enumerate(["F", "E", "D", "C", "B", "A"], start=7)
    ]
    assert [item.palette_index for item in returning] == [None, None, 3, 2, 1, 0]
    assert [item.palette_overflow for item in returning] == [True, True] + [False] * 4


def test_unattributed_and_stale_results_are_not_palette_overflow():
    allocator = PeerSpeakerIdentityAllocator()
    for order, speaker in enumerate(["A", "B", "C", "D"], start=1):
        allocator.observe(_transcript(speaker, "session", order), child_sequence=0)
    missing = allocator.observe(_transcript(None, "session", 5), child_sequence=0)
    stale = allocator.observe(_transcript("E", "session", 4), child_sequence=0)
    assert missing.palette_index is None and not missing.palette_overflow
    assert stale.palette_index is None and not stale.palette_overflow


def test_non_diarized_turn_preserves_prior_palette_without_consuming_slot() -> None:
    allocator = PeerSpeakerIdentityAllocator()
    first = allocator.observe(_transcript("A", "session", 1), child_sequence=0)
    second = allocator.observe(_transcript("B", "session", 2), child_sequence=0)
    off = allocator.observe(
        replace(_transcript("ignored", "session", 3), final_speaker_runs=()),
        child_sequence=0,
    )
    resumed = allocator.observe(_transcript("B", "session", 4), child_sequence=0)
    missing = allocator.observe(_transcript(None, "session", 5), child_sequence=0)
    following = allocator.observe(_transcript("C", "session", 6), child_sequence=0)
    assert [item.palette_index for item in (first, second, off, resumed, missing, following)] == [
        0,
        1,
        None,
        1,
        None,
        2,
    ]
