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


def test_get_or_create_with_unknown_id_creates_new_with_that_id():
    manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=20)
    conv = manager.get_or_create("custom-id-123")
    assert conv.conversation_id == "custom-id-123"
    assert conv.messages == []


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
