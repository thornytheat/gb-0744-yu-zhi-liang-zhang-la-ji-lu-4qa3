from app.modules.m4_elongation.formula import evaluate


def compensate(aligned, targets, repeat_tensions=()):
    result = {}
    repeats = set(repeat_tensions)
    for (beam, strand), target in targets.items():
        for end in ("L", "R"):
            key = beam, strand, end
            history = [aligned.get((*key, level)) for level in (20, 40, 100)]
            lines = [row["line"] for row in history if row is not None]
            if (beam, strand, end) in repeats:
                # 该端存在第二次完整张拉：第一次照常计算，但整束必须待人工复测。
                detail = {"原因码": "REPEAT_TENSION"}
            elif len(lines) < 3:
                detail = {"原因码": "MISSING_LEVEL"}
            else:
                detail = evaluate(history, target["loss"][end])
            result[key] = {**detail, "源行": lines}
    return result
