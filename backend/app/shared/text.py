"""Pure text utility shared by reference catalog adapters."""

import re

def token_similarity(left: str, right: str) -> float:
    tokenize = lambda value: set(re.findall(r"[\w+#.]+", str(value).casefold()))
    a, b = tokenize(left), tokenize(right)
    return len(a & b) / max(1, len(a | b))


