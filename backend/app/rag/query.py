"""确定性查询规范化与受控中英文术语扩展。"""

import re

TERMS = {
    "残差网络": ("ResNet", "residual network"),
    "resnet": ("残差网络", "residual network"),
    "目标检测": ("object detection",),
    "object detection": ("目标检测",),
    "平均精度": ("average precision", "AP"),
    "average precision": ("平均精度", "AP"),
    "卷积神经网络": ("CNN", "convolutional neural network"),
    "视觉变换器": ("ViT", "Vision Transformer"),
}


def normalize_query(query: str) -> list[str]:
    original = query.strip()
    normalized = re.sub(r"\s+", " ", original.translate(str.maketrans("，。！？；：（）", ",.!?;:()")))
    values = [original]
    if normalized != original:
        values.append(normalized)
    lower = normalized.lower()
    additions = []
    for term, expansions in TERMS.items():
        if term in lower if term.isascii() else term in normalized:
            additions.extend(expansions)
    if additions:
        values.append(normalized + " " + " ".join(dict.fromkeys(additions)))
    return list(dict.fromkeys(value[:4000] for value in values if value))[:6]

