import time

from codexd.harness.message_buffer import MessageBuffer


def test_add_and_read():
    buf = MessageBuffer(max_per_channel=100)
    buf.add("#general", "spark-ori", "hello")
    buf.add("#general", "spark-culture", "hi there")
    msgs = buf.read("#general", limit=50)
    assert len(msgs) == 2
    assert msgs[0].nick == "spark-ori"
    assert msgs[0].text == "hello"
    assert msgs[1].nick == "spark-culture"


def test_read_returns_since_last_read():
    buf = MessageBuffer(max_per_channel=100)
    buf.add("#general", "a", "msg1")
    buf.add("#general", "b", "msg2")
    msgs1 = buf.read("#general", limit=50)
    assert len(msgs1) == 2
    buf.add("#general", "c", "msg3")
    msgs2 = buf.read("#general", limit=50)
    assert len(msgs2) == 1
    assert msgs2[0].text == "msg3"


def test_read_empty_channel():
    buf = MessageBuffer(max_per_channel=100)
    assert buf.read("#empty", limit=50) == []


def test_ring_buffer_eviction():
    buf = MessageBuffer(max_per_channel=5)
    for i in range(10):
        buf.add("#general", "bot", f"msg{i}")
    msgs = buf.read("#general", limit=100)
    assert len(msgs) == 5
    assert msgs[0].text == "msg5"
    assert msgs[-1].text == "msg9"


def test_limit_caps_results():
    buf = MessageBuffer(max_per_channel=100)
    for i in range(20):
        buf.add("#general", "bot", f"msg{i}")
    msgs = buf.read("#general", limit=5)
    assert len(msgs) == 5
    assert msgs[0].text == "msg15"


def test_multiple_channels_independent():
    buf = MessageBuffer(max_per_channel=100)
    buf.add("#general", "a", "gen1")
    buf.add("#dev", "b", "dev1")
    gen_msgs = buf.read("#general", limit=50)
    assert len(gen_msgs) == 1
    assert gen_msgs[0].text == "gen1"
    dev_msgs = buf.read("#dev", limit=50)
    assert len(dev_msgs) == 1
    assert dev_msgs[0].text == "dev1"


def test_messages_have_timestamps():
    buf = MessageBuffer(max_per_channel=100)
    before = time.time()
    buf.add("#general", "ori", "test")
    after = time.time()
    msgs = buf.read("#general", limit=1)
    assert before <= msgs[0].timestamp <= after


def test_known_nicks_collects_across_channels():
    buf = MessageBuffer(max_per_channel=100)
    buf.add("#a", "alice", "hi")
    buf.add("#a", "bob", "yo")
    buf.add("#b", "alice", "hey")
    buf.add("#b", "carol", "sup")
    assert buf.known_nicks() == {"alice", "bob", "carol"}


def test_known_nicks_empty_when_no_messages():
    buf = MessageBuffer(max_per_channel=100)
    assert buf.known_nicks() == set()


def test_read_thread_filters_by_thread_name():
    buf = MessageBuffer(max_per_channel=100)
    buf.add("#general", "alice", "[thread:t1] starting work")
    buf.add("#general", "bob", "[thread:t2] different thread")
    buf.add("#general", "alice", "[thread:t1] more on first")
    msgs = buf.read_thread("#general", "t1")
    assert [m.text for m in msgs] == ["[thread:t1] starting work", "[thread:t1] more on first"]


def test_read_thread_empty_for_unknown_channel():
    buf = MessageBuffer(max_per_channel=100)
    assert buf.read_thread("#missing", "t1") == []


def test_read_thread_respects_limit():
    buf = MessageBuffer(max_per_channel=100)
    for i in range(5):
        buf.add("#g", "alice", f"[thread:t1] msg {i}")
    msgs = buf.read_thread("#g", "t1", limit=2)
    assert len(msgs) == 2
    assert [m.text for m in msgs] == ["[thread:t1] msg 3", "[thread:t1] msg 4"]
