from rupsaa.conversation.manager import (
    Conversation,
    ConversationManager,
    InMemoryConversationStore,
)


def test_get_or_create_new_conversation_has_id():
    manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=20)
    conv = manager.get_or_create(None)
    assert conv.conversation_id
    assert conv.messages == []


def test_get_or_create_returns_existing_conversation():
    manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=20)
    conv = manager.get_or_create(None)
    manager.append_turn(conv, "hi", "hello!")

    fetched = manager.get_or_create(conv.conversation_id)
    assert fetched.conversation_id == conv.conversation_id
    assert len(fetched.messages) == 2


def test_unknown_or_client_chosen_id_gets_a_fresh_server_id():
    """A client-chosen id is never adopted (two users sending "1" must not share a history)."""
    manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=20)
    conv = manager.get_or_create("custom-id-123")
    assert conv.conversation_id != "custom-id-123" and conv.messages == []
    other = manager.get_or_create("custom-id-123")
    assert other.conversation_id != conv.conversation_id  # no shared history through a guessable id
    unknown_uuid = "0195a040-b91c-4c1e-9f0a-aff213f509fd"
    assert manager.get_or_create(unknown_uuid).conversation_id != unknown_uuid


def test_store_is_bounded_by_count_and_idle_time():
    now = [0.0]
    store = InMemoryConversationStore(max_conversations=3, idle_seconds=60, clock=lambda: now[0])
    manager = ConversationManager(store=store, max_history_messages=20)
    ids = [manager.get_or_create(None).conversation_id for _ in range(5)]
    assert len(store) == 3 and store.get(ids[0]) is None and store.get(ids[-1]) is not None
    now[0] = 61.0
    assert store.get(ids[-1]) is None and len(store) == 0


def test_append_turn_adds_user_and_assistant_messages():
    manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=20)
    conv = manager.get_or_create(None)
    manager.append_turn(conv, "hi", "hello!")
    assert len(conv.messages) == 2
    assert conv.messages[0].role == "user"
    assert conv.messages[0].content == "hi"
    assert conv.messages[1].role == "assistant"
    assert conv.messages[1].content == "hello!"


def test_history_is_truncated_to_max_messages():
    manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=4)
    conv = manager.get_or_create(None)
    for i in range(5):
        manager.append_turn(conv, f"user{i}", f"assistant{i}")
    assert len(conv.messages) == 4
    # oldest turns should have been dropped, newest retained
    assert conv.messages[-1].content == "assistant4"


def test_reset_removes_conversation_from_store():
    store = InMemoryConversationStore()
    manager = ConversationManager(store=store, max_history_messages=20)
    conv = manager.get_or_create(None)
    manager.append_turn(conv, "hi", "hello!")

    manager.reset(conv.conversation_id)
    assert store.get(conv.conversation_id) is None


def test_approx_token_count_is_nonnegative():
    conv = Conversation(conversation_id="x")
    assert conv.approx_token_count() == 0
