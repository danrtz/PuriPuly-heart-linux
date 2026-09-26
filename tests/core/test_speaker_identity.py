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


def test_palette_capacity_grays_sixteenth_distinct_key_without_aliasing():
    allocator = PeerSpeakerIdentityAllocator()
    palette = [
        allocator.observe(_transcript(f"speaker-{index}", "session", index + 1), child_sequence=0)
        for index in range(16)
    ]
    assert [item.palette_index for item in palette[:15]] == list(range(15))
    assert palette[15].palette_index is None
    assert (
        allocator.observe(_transcript("speaker-0", "session", 17), child_sequence=0).palette_index
        == 0
    )
