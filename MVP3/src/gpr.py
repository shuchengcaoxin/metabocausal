"""A small non-evaluating GPR parser. Preserve Boolean structure; do not flatten AND."""

import re

TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z0-9_.:-]+)")
MAX_TOKENS = 10000
MAX_DEPTH = 100


def parse_gpr(text):
    if not isinstance(text, str):
        raise ValueError("GPR must be a string; missing is represented by an empty string")
    if not text.strip():
        return None
    tokens = []
    offset = 0
    while offset < len(text.rstrip()):
        match = TOKEN.match(text, offset)
        if not match:
            raise ValueError(f"Unsupported GPR syntax at character {offset}")
        tokens.append(match[1])
        offset = match.end()
        if len(tokens) > MAX_TOKENS:
            raise ValueError("GPR token limit exceeded")
    position = 0

    def expression(operator, inner, depth):
        nonlocal position
        children = [inner(depth)]
        while position < len(tokens) and tokens[position].lower() == operator:
            position += 1
            children.append(inner(depth))
        return children[0] if len(children) == 1 else {"op": operator, "children": children}

    def disjunction(depth):
        return expression("or", conjunction, depth)

    def conjunction(depth):
        return expression("and", atom, depth)

    def atom(depth):
        nonlocal position
        if depth > MAX_DEPTH or position >= len(tokens):
            raise ValueError("GPR nesting limit or missing operand")
        token = tokens[position]
        position += 1
        if token == "(":
            node = disjunction(depth + 1)
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("Unclosed GPR parenthesis")
            position += 1
            return node
        if token in ("(", ")") or token.lower() in ("and", "or", "not"):
            raise ValueError("Expected a gene identifier in GPR")
        return {"op": "gene", "gene_id": token}

    tree = disjunction(0)
    if position != len(tokens):
        raise ValueError("Unconsumed GPR tokens")
    return tree


def gene_members(tree, in_complex=False):
    """gene -> whether any occurrence is under an AND; not a standalone activity claim."""
    if tree is None:
        return {}
    if tree["op"] == "gene":
        return {tree["gene_id"]: in_complex}
    result = {}
    for child in tree["children"]:
        for gene, complex_member in gene_members(child, in_complex or tree["op"] == "and").items():
            result[gene] = result.get(gene, False) or complex_member
    return result
