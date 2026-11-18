from . import build_domain

VISION = ("detect_objects", "segment_instances")


def build_vision_mcp():
    return build_domain("Agent-RS Vision", VISION)
