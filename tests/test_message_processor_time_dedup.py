from datetime import datetime

from astrbot_plugin_angel_heart.core.message_processor import MessageProcessor


def test_user_message_does_not_append_duplicate_time_text_block():
    processor = MessageProcessor("fairy")
    msg = {
        "role": "user",
        "content": "fairy？有没有觉得提示词哪里不对？我继续修",
        "sender_name": "红豆泥",
        "sender_id": "289104862",
        "timestamp": 1784008800,
        "chat_id": "aiocqhttp:GroupMessage:10000",
    }

    processed = processor.process_message(msg)

    assert processed["role"] == "user"
    assert isinstance(processed["content"], list)
    assert len(processed["content"]) == 1
    assert processed["content"][0]["type"] == "text"
    text = processed["content"][0]["text"]
    assert "[群友: 红豆泥 (ID: 289104862, 群友)]" in text
    assert "fairy？有没有觉得提示词哪里不对？我继续修" in text
    # 断言"只出现一次"，而非硬编码钟点：钟点由运行环境时区决定（CI 为 UTC）
    expected_time = datetime.fromtimestamp(1784008800).astimezone().strftime("%Y-%m-%d %H:%M")
    assert text.count(expected_time) == 1
