from . import build_domain

PLATFORM = ("search_imagery", "fetch_scene", "prepare_map_roi", "parse_document", "ocr_recognize",
            "web_search", "generate_report", "look_at_location")


def build_platform_mcp():
    server = build_domain("Agent-RS Platform", PLATFORM)

    @server.prompt
    def inspect_index_report():
        return "核实当前影像及指数所需波段，计算用户指定的指数，使用同一影像的成功结果生成报告。"

    @server.prompt
    def mask_segment_report():
        return "核实影像质量标记，执行用户指定的分割，说明掩膜适用范围，引用实际结果生成报告。"

    @server.prompt
    def detect_report():
        return "对选定影像执行目标检测，核对有效范围与检测数量，再生成报告。成功检测到零个目标也是有效结果。"

    return server
