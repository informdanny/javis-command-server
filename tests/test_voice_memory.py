from app.voice_memory import (
    build_memory_aware_instructions,
    create_voice_memory,
    remember_realtime_event,
    reset_if_stale,
)


def test_memory_extracts_preferred_name_from_call_me():
    memory = create_voice_memory(max_events=12)
    remember_realtime_event(
        memory,
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Please call me Dan"},
    )
    assert memory.preferred_name == "Dan"


def test_memory_includes_recent_user_and_assistant_context():
    memory = create_voice_memory(max_events=12)
    remember_realtime_event(
        memory,
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Call me Dan"},
    )
    remember_realtime_event(
        memory,
        {"type": "response.output_audio_transcript.done", "transcript": "Okay Dan, got it."},
    )

    merged = build_memory_aware_instructions("Base prompt.", memory)
    assert "User preferred name: Dan." in merged
    assert "User: Call me Dan" in merged
    assert "Assistant: Okay Dan, got it." in merged


def test_memory_resets_after_ttl():
    memory = create_voice_memory(max_events=12)
    remember_realtime_event(
        memory,
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Call me Dan"},
    )
    memory.updated_at_monotonic -= 9999
    reset_if_stale(memory, ttl_seconds=60)
    assert memory.preferred_name is None
    assert len(memory.recent_events) == 0
