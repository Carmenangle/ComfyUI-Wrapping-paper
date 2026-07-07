"""跨模块契约测试：EmbedConfig 默认值 + parser/convert 共享穿透集的有意差异。

这些是「架构不变量」——PrimitiveNode 差异是有意的（见 workflow-convert 记忆），
测试把它钉死，防后续误合并。
"""
from app.services.rag_store import EmbedConfig
from app.services import workflow_parser, workflow_convert


def test_embed_config_默认模型():
    assert EmbedConfig().embed_model == "text-embedding-3-small"
    c = EmbedConfig("u", "k", "m")
    assert (c.base_url, c.api_key, c.embed_model) == ("u", "k", "m")


def test_穿透集共享核心():
    assert workflow_parser.SKIP_TYPES == workflow_parser.PASSTHROUGH_TYPES
    assert workflow_parser.PASSTHROUGH_TYPES == {"Note", "MarkdownNote", "Reroute"}


def test_convert_额外并入PrimitiveNode是有意差异():
    # convert 运行期须穿透 PrimitiveNode（值已并入下游），parser 不 skip 它以暴露 value。
    # _NON_EXEC 是 convert 内的局部量，此处校验其组成规则的两个前提常量。
    assert "PrimitiveNode" not in workflow_parser.SKIP_TYPES
    assert "PrimitiveNode" not in workflow_parser.PASSTHROUGH_TYPES
    # convert 从 parser 导入的正是共享穿透集（同一来源，非各写一份）
    assert workflow_convert.PASSTHROUGH_TYPES is workflow_parser.PASSTHROUGH_TYPES
