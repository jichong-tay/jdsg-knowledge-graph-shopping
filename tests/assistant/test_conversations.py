"""File-backed lifecycle checks through the saved-conversation public boundary."""

import pytest

from shopping.assistant import conversations as saved


def submit(settings, text="What did I buy?", *, conversation_id=None, command_id="submit-1"):
    return saved.accept_command(
        settings,
        {
            "id": command_id,
            "kind": "submit",
            "conversation_id": conversation_id or saved.new_draft(settings),
            "text": text,
        },
    )


def test_first_submission_is_atomic_and_duplicate_commands_return_saved_outcome(settings):
    draft = saved.new_draft(settings)
    assert saved.list_conversations(settings)["items"] == []
    accepted = submit(settings, "  What did I buy?\n", conversation_id=draft)
    assert submit(settings, "  What did I buy?\n", conversation_id=draft) == accepted
    assert saved.command_status(settings, "submit-1") == accepted
    conversation = saved.get_conversation(settings, draft)
    assert conversation["title"] == "What did I buy?"
    assert (conversation["endpoint"], conversation["model"]) == (
        "http://127.0.0.1:11434",
        "qwen3.5:9b",
    )
    attempt = saved.get_attempt(settings, draft, accepted["attempt_id"])
    assert attempt["question"] == "  What did I buy?\n"
    assert attempt["status"] == "running"
    with pytest.raises(ValueError, match="command_conflict"):
        submit(settings, "Changed question", conversation_id=draft)
    with pytest.raises(ValueError, match="busy"):
        submit(settings, "Another question", conversation_id=draft, command_id="submit-2")
    assert len(saved.history(settings, draft)["items"]) == 1
    assert saved.command_status(settings, "submit-2") is None


def test_checkpoints_are_versioned_and_stop_wins_over_late_completion(settings):
    accepted = submit(settings)
    cid, aid = accepted["conversation_id"], accepted["attempt_id"]
    first = saved.checkpoint(settings, cid, aid, expected_version=1, text="Partial answer")
    assert (first["version"], first["text"]) == (2, "Partial answer")
    with pytest.raises(ValueError, match="stale_version"):
        saved.checkpoint(settings, cid, aid, expected_version=1, text="Older output")
    stop = {"id": "stop-1", "kind": "stop", "conversation_id": cid, "attempt_id": aid}
    stopped = saved.accept_command(settings, stop)
    assert stopped["status"] == "stopping"
    assert saved.accept_command(settings, stop) == stopped
    with pytest.raises(ValueError, match="stopping"):
        saved.checkpoint(
            settings, cid, aid, expected_version=3, text="Late final", status="complete"
        )
    final = saved.checkpoint(
        settings,
        cid,
        aid,
        expected_version=3,
        text="Partial answer",
        status="stopped",
        code="cancelled",
    )
    assert final["version"] == 4
    assert saved.get_attempt(settings, cid, aid)["status"] == "stopped"


def test_committed_completion_stays_complete_and_wrong_attempt_cannot_stop_it(settings):
    accepted = submit(settings)
    cid, aid = accepted["conversation_id"], accepted["attempt_id"]
    complete = saved.checkpoint(
        settings, cid, aid, expected_version=1, text="Please clarify.", status="complete"
    )
    stopped = saved.accept_command(
        settings, {"id": "stop-1", "kind": "stop", "conversation_id": cid, "attempt_id": aid}
    )
    assert stopped["status"] == "already_finished"
    assert saved.get_attempt(settings, cid, aid) == complete
    other = saved.new_draft(settings)
    with pytest.raises(ValueError, match="gone"):
        saved.accept_command(
            settings,
            {"id": "wrong-stop", "kind": "stop", "conversation_id": other, "attempt_id": aid},
        )


def test_retry_keeps_original_message_and_only_latest_failure_is_retryable(settings):
    first = submit(settings)
    cid, aid = first["conversation_id"], first["attempt_id"]
    saved.checkpoint(
        settings,
        cid,
        aid,
        expected_version=1,
        text="Failed partial",
        status="failed",
        code="provider_eof",
    )
    command = {"id": "retry-1", "kind": "retry", "conversation_id": cid, "attempt_id": aid}
    retry = saved.accept_command(settings, command)
    assert saved.accept_command(settings, command) == retry
    assert retry["message_id"] == first["message_id"]
    assert retry["attempt_id"] != aid
    assert saved.get_attempt(settings, cid, retry["attempt_id"])["tools"] == []
    saved.checkpoint(
        settings, cid, retry["attempt_id"], expected_version=1, text="Failed again", status="failed"
    )
    with pytest.raises(ValueError, match="not_retryable"):
        saved.accept_command(settings, {**command, "id": "retry-old"})
    later = submit(settings, "Correction", conversation_id=cid, command_id="submit-later")
    saved.checkpoint(
        settings, cid, later["attempt_id"], expected_version=1, text="Done", status="complete"
    )
    with pytest.raises(ValueError, match="not_retryable"):
        saved.accept_command(
            settings, {**command, "id": "retry-later", "attempt_id": retry["attempt_id"]}
        )
    page = saved.history(settings, cid, limit=2)
    assert [a["question"] for a in page["items"]] == ["Correction", "What did I buy?"]
    older = saved.history(settings, cid, before=page["next_cursor"], limit=2)
    assert [a["text"] for a in older["items"]] == ["Failed partial"]
    assert older["next_cursor"] is None


def test_changed_identity_is_readable_but_cannot_accept_new_work(settings):
    from dataclasses import replace

    first = submit(settings)
    cid, aid = first["conversation_id"], first["attempt_id"]
    saved.checkpoint(settings, cid, aid, expected_version=1, text="", status="failed")
    changed = replace(settings, ollama_model="another:model")
    assert saved.get_conversation(changed, cid)["model"] == "qwen3.5:9b"
    with pytest.raises(ValueError, match="configuration_changed"):
        submit(changed, conversation_id=cid, command_id="new-submit")
    with pytest.raises(ValueError, match="configuration_changed"):
        saved.accept_command(
            changed, {"id": "retry", "kind": "retry", "conversation_id": cid, "attempt_id": aid}
        )


def test_only_complete_exchanges_and_complete_tool_groups_enter_bounded_context(settings):
    first = submit(settings, "First question")
    cid, aid = first["conversation_id"], first["attempt_id"]
    running = {
        "type": "tool",
        "call_id": "1:0",
        "name": "get_order",
        "arguments": {"order_id": 1},
        "status": "running",
    }
    saved.record_tool(settings, cid, aid, expected_version=1, event=running)
    with pytest.raises(ValueError, match="incomplete_response"):
        saved.checkpoint(
            settings, cid, aid, expected_version=2, text="Premature", status="complete"
        )
    result = {
        "status": "not_found",
        "data": {},
        "evidence": [],
        "next_cursor": None,
        "truncated": False,
    }
    saved.record_tool(
        settings,
        cid,
        aid,
        expected_version=2,
        event={
            "type": "tool",
            "call_id": "1:0",
            "name": "get_order",
            "status": "not_found",
            "result": result,
        },
    )
    saved.checkpoint(
        settings, cid, aid, expected_version=3, text="No order found.", status="complete"
    )
    failed = submit(settings, "Second question", conversation_id=cid, command_id="second")
    saved.checkpoint(
        settings,
        cid,
        failed["attempt_id"],
        expected_version=1,
        text="Do not send this failed text",
        status="failed",
    )
    current = submit(settings, "Third question", conversation_id=cid, command_id="third")
    context = saved.context_for_attempt(settings, cid, current["attempt_id"])
    assert context["question"] == "Third question"
    assert context["identity"] == ("http://127.0.0.1:11434", "qwen3.5:9b")
    assert context["completed_exchanges"] == [
        [
            {"role": "user", "content": "First question"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_order", "arguments": {"order_id": 1}}}],
            },
            {"role": "tool", "tool_name": "get_order", "content": saved_json(result)},
            {"role": "assistant", "content": "No order found."},
        ]
    ]
    assert (
        saved.context_for_attempt(settings, cid, current["attempt_id"], max_bytes=1)[
            "completed_exchanges"
        ]
        == []
    )


def saved_json(value):
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_deletion_fences_writes_and_only_finalizes_after_confirmed_cleanup(settings, fixture_dir):
    from shopping.ingestion.pipeline import import_eml
    from shopping.purchases.queries import count_current_orders

    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    archived = sorted(settings.raw_email_dir.rglob("*.eml"))
    raw = [path.read_bytes() for path in archived]
    first = submit(settings)
    cid, aid = first["conversation_id"], first["attempt_id"]
    delete = {"id": "delete-1", "kind": "delete", "conversation_id": cid, "confirmed": True}
    fenced = saved.accept_command(settings, delete)
    assert fenced["status"] == "deleting"
    assert saved.get_conversation(settings, cid)["deleting"] == 1
    with pytest.raises(ValueError, match="deleting"):
        saved.checkpoint(settings, cid, aid, expected_version=2, text="Late data")
    with pytest.raises(ValueError, match="cleanup_required"):
        saved.finalize_delete(
            settings, cid, expected_version=fenced["version"], cleanup_confirmed=False
        )
    assert saved.get_conversation(settings, cid)["deleting"] == 1
    assert (
        saved.finalize_delete(
            settings, cid, expected_version=fenced["version"], cleanup_confirmed=True
        )["status"]
        == "gone"
    )
    outcome = saved.command_status(settings, "submit-1")
    assert outcome is not None and outcome["status"] == "gone"
    assert saved.accept_command(settings, delete)["status"] == "gone"
    assert submit(settings, conversation_id=cid)["status"] == "gone"
    with pytest.raises(ValueError, match="gone"):
        submit(settings, conversation_id=cid, command_id="fresh-id-stale-draft")
    with pytest.raises(ValueError, match="gone"):
        saved.get_attempt(settings, cid, aid)
    assert saved.list_conversations(settings)["items"] == []
    assert count_current_orders(settings.database_path) == 1
    assert [path.read_bytes() for path in archived] == raw


def test_rename_deduplicates_without_reordering_and_restart_preserves_partial_text(settings):
    first = submit(settings)
    cid, aid = first["conversation_id"], first["attempt_id"]
    saved.checkpoint(settings, cid, aid, expected_version=1, text="Saved partial")
    before = saved.get_conversation(settings, cid)
    rename = {"id": "rename-1", "kind": "rename", "conversation_id": cid, "text": "New title"}
    result = saved.accept_command(settings, rename)
    assert saved.accept_command(settings, rename) == result
    assert saved.get_conversation(settings, cid)["activity_at"] == before["activity_at"]
    recovered = saved.interrupt_unfinished(settings)
    assert [a["id"] for a in recovered] == [aid]
    assert recovered[0]["status"] == "interrupted"
    assert recovered[0]["text"] == "Saved partial"
    assert saved.interrupt_unfinished(settings) == []
    retry = saved.accept_command(
        settings, {"id": "retry-1", "kind": "retry", "conversation_id": cid, "attempt_id": aid}
    )
    assert retry["attempt_id"] != aid
    # An old tab targeting the interrupted attempt cannot stop the new Retry.
    old_stop = saved.accept_command(
        settings, {"id": "old-stop", "kind": "stop", "conversation_id": cid, "attempt_id": aid}
    )
    assert old_stop["status"] == "already_finished"
    assert saved.get_attempt(settings, cid, retry["attempt_id"])["status"] == "running"


def test_saved_evidence_must_come_from_this_attempts_tool_records(settings, fixture_dir):
    from shopping.assistant.tools import dispatch_tool
    from shopping.ingestion.pipeline import import_eml

    import_eml(fixture_dir / "fairprice_order_minimal.eml", settings)
    first = submit(settings)
    cid, aid = first["conversation_id"], first["attempt_id"]
    result = dispatch_tool(settings, "get_order", {"order_id": 1})
    saved.record_tool(
        settings,
        cid,
        aid,
        expected_version=1,
        event={
            "type": "tool",
            "call_id": "1:0",
            "name": "get_order",
            "arguments": {"order_id": 1},
            "status": "running",
        },
    )
    saved.record_tool(
        settings,
        cid,
        aid,
        expected_version=2,
        event={
            "type": "tool",
            "call_id": "1:0",
            "name": "get_order",
            "result": result,
            "status": result["status"],
        },
    )
    evidence = result["evidence"]
    with pytest.raises(ValueError, match="invalid_evidence"):
        saved.checkpoint(
            settings,
            cid,
            aid,
            expected_version=3,
            text="Wrong",
            status="complete",
            evidence=[{**evidence[0], "url": "https://host.invalid"}],
        )
    finished = saved.checkpoint(
        settings,
        cid,
        aid,
        expected_version=3,
        text="Saved answer",
        status="complete",
        evidence=evidence,
    )
    assert finished["evidence"] == evidence


def test_concurrent_submissions_deduplicate_and_never_queue(settings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    cid = saved.new_draft(settings)
    barrier = Barrier(2)

    def send(_):
        barrier.wait()
        return submit(settings, conversation_id=cid)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert results[0] == results[1]
    assert len(saved.history(settings, cid)["items"]) == 1
    draft = saved.new_draft(settings)
    with pytest.raises(ValueError, match="busy"):
        submit(settings, conversation_id=draft, command_id="other")
    assert len(saved.list_conversations(settings)["items"]) == 1


def test_checkpoint_failure_rolls_back_text_and_versions(settings):
    import sqlite3
    from contextlib import closing

    from shopping.storage.connection import connect_database

    first = submit(settings)
    cid, aid = first["conversation_id"], first["attempt_id"]
    before = saved.get_attempt(settings, cid, aid)
    conversation = saved.get_conversation(settings, cid)
    # Inject a real storage failure after the attempt UPDATE, in the same transaction.
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "CREATE TRIGGER fail_checkpoint BEFORE UPDATE ON conversations "
            "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        saved.checkpoint(settings, cid, aid, expected_version=1, text="Unsaved")
    assert saved.get_attempt(settings, cid, aid) == before
    assert saved.get_conversation(settings, cid) == conversation


def test_acceptance_failure_rolls_back_draft_consumption_and_message(settings):
    import sqlite3
    from contextlib import closing

    from shopping.storage.connection import connect_database

    draft = saved.new_draft(settings)
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "CREATE TRIGGER fail_command BEFORE INSERT ON conversation_commands "
            "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        submit(settings, conversation_id=draft)
    assert saved.list_conversations(settings)["items"] == []
    assert saved.command_status(settings, "submit-1") is None
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute("DROP TRIGGER fail_command")
    assert submit(settings, conversation_id=draft)["status"] == "accepted"


def test_failed_delete_is_recoverable_after_restart(settings):
    import sqlite3
    from contextlib import closing

    from shopping.storage.connection import connect_database

    first = submit(settings)
    cid = first["conversation_id"]
    fence = saved.accept_command(
        settings, {"id": "delete", "kind": "delete", "conversation_id": cid, "confirmed": True}
    )
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute(
            "CREATE TRIGGER fail_delete BEFORE DELETE ON conversations "
            "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        saved.finalize_delete(
            settings, cid, expected_version=fence["version"], cleanup_confirmed=True
        )
    assert saved.get_conversation(settings, cid)["deleting"] == 1
    assert saved.command_status(settings, "submit-1") == first
    with closing(connect_database(settings.database_path)) as connection:
        connection.execute("DROP TRIGGER fail_delete")
    recovered = saved.interrupt_unfinished(settings)
    assert recovered[0]["status"] == "interrupted"
    version = saved.get_conversation(settings, cid)["version"]
    assert (
        saved.finalize_delete(settings, cid, expected_version=version, cleanup_confirmed=True)[
            "status"
        ]
        == "gone"
    )


@pytest.mark.parametrize("target", [True, -1, 2**80])
def test_invalid_attempt_targets_are_rejected_before_sql(settings, target):
    accepted = submit(settings)
    with pytest.raises(ValueError, match="invalid_id"):
        saved.get_attempt(settings, accepted["conversation_id"], target)


def test_tool_and_output_bounds_preserve_last_checkpoint(settings):
    accepted = submit(settings)
    cid, aid = accepted["conversation_id"], accepted["attempt_id"]
    for index in range(8):
        saved.record_tool(
            settings,
            cid,
            aid,
            expected_version=index + 1,
            event={
                "type": "tool",
                "call_id": f"1:{index}",
                "name": "get_order",
                "arguments": {"order_id": 1},
                "status": "running",
            },
        )
    before = saved.get_attempt(settings, cid, aid)
    with pytest.raises(ValueError, match="tool_limit"):
        saved.record_tool(
            settings,
            cid,
            aid,
            expected_version=9,
            event={
                "type": "tool",
                "call_id": "1:8",
                "name": "get_order",
                "arguments": {"order_id": 1},
                "status": "running",
            },
        )
    with pytest.raises(ValueError, match="tool_limit"):
        saved.record_tool(
            settings,
            cid,
            aid,
            expected_version=9,
            event={
                "type": "tool",
                "call_id": "1:0",
                "name": "get_order",
                "status": "ok",
                "result": {
                    "status": "ok",
                    "data": {"value": "x" * 4096},
                    "evidence": [],
                    "truncated": False,
                    "next_cursor": None,
                },
            },
        )
    with pytest.raises(ValueError, match="output_limit"):
        saved.checkpoint(settings, cid, aid, expected_version=9, text="x" * 65537)
    assert saved.get_attempt(settings, cid, aid) == before


def test_context_and_history_never_cross_conversations_and_list_pages_are_ordered(settings):
    first = submit(settings, "First question")
    saved.checkpoint(
        settings,
        first["conversation_id"],
        first["attempt_id"],
        expected_version=1,
        text="First answer",
        status="complete",
    )
    second = submit(settings, "Second question", command_id="second")
    context = saved.context_for_attempt(settings, second["conversation_id"], second["attempt_id"])
    assert context["completed_exchanges"] == []
    with pytest.raises(ValueError, match="attempt_gone"):
        saved.get_attempt(settings, second["conversation_id"], first["attempt_id"])
    page = saved.list_conversations(settings, limit=1)
    assert page["items"][0]["id"] == second["conversation_id"]
    older = saved.list_conversations(settings, limit=1, before=page["next_cursor"])
    assert older["items"][0]["id"] == first["conversation_id"]
    assert older["next_cursor"] is None
