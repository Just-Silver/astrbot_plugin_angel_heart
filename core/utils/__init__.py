"""
AngelHeart 插件 - 核心工具模块
提供各种通用工具和辅助功能
"""

# 从各个子模块导入函数
from .content_utils import (
    convert_content_to_string,
    strip_markdown,
    strip_period_before_newline,
)
from .context_utils import (
    format_decision_xml,
    format_final_prompt,
    json_serialize_context,
    partition_dialogue,
    partition_dialogue_raw,
)
from .json_parser import JsonParser
from .message_hits import (
    build_message_metadata,
    extract_plain_body_from_components,
    metadata_has_hit,
    metadata_hit_phrases,
    parse_pipe_phrases,
    parse_space_phrases,
)
from .message_utils import format_message_for_llm, prune_old_messages
from .time_utils import format_relative_time, get_beijing_time_str, get_latest_message_time
from .xml_formatter import format_message_to_text

# 导出所有函数和类
__all__ = [
    # 时间相关
    "get_latest_message_time",
    "format_relative_time",
    "get_beijing_time_str",
    # 内容处理相关
    "convert_content_to_string",
    "strip_markdown",
    "strip_period_before_newline",
    # 正文命中相关
    "build_message_metadata",
    "extract_plain_body_from_components",
    "metadata_has_hit",
    "metadata_hit_phrases",
    "parse_pipe_phrases",
    "parse_space_phrases",
    # 消息处理相关
    "prune_old_messages",
    "format_message_for_llm",
    # 上下文处理相关
    "json_serialize_context",
    "partition_dialogue",
    "format_decision_xml",
    # XML 格式化相关
    "format_message_to_text",
    "partition_dialogue_raw",
    "format_final_prompt",
    # JSON解析相关
    "JsonParser",
]
