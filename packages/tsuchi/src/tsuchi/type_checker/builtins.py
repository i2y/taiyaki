"""Built-in operator type rules for TypeScript/JavaScript semantics."""

from __future__ import annotations

from .types import MonoType, NumberType, BooleanType, StringType, VoidType, NullType, NUMBER, BOOLEAN, STRING


def binary_op_type(op: str, left: MonoType, right: MonoType) -> MonoType | None:
    """Return the result type for a binary operation, or None if invalid."""
    if isinstance(left, NumberType) and isinstance(right, NumberType):
        if op in ("+", "-", "*", "/", "%", "**"):
            return NUMBER
        # Bitwise operators: number & number → number
        if op in ("&", "|", "^", "<<", ">>", ">>>"):
            return NUMBER
        return None

    # boolean arithmetic: true + true → 2, true + 1 → 2 (JS coerces booleans to numbers)
    if isinstance(left, BooleanType) and isinstance(right, BooleanType):
        if op in ("+", "-", "*", "/", "%", "**"):
            return NUMBER
        if op in ("&", "|", "^", "<<", ">>", ">>>"):
            return NUMBER
    if op in ("+", "-", "*", "/", "%", "**"):
        if isinstance(left, BooleanType) and isinstance(right, NumberType):
            return NUMBER
        if isinstance(left, NumberType) and isinstance(right, BooleanType):
            return NUMBER

    if isinstance(left, StringType) and isinstance(right, StringType):
        if op == "+":
            return STRING
        return None

    # string + number or number + string → string (JS coercion)
    if op == "+":
        if isinstance(left, StringType) and isinstance(right, (NumberType, BooleanType)):
            return STRING
        if isinstance(right, StringType) and isinstance(left, (NumberType, BooleanType)):
            return STRING

    # instanceof always returns boolean
    if op == "instanceof":
        return BOOLEAN

    # in operator always returns boolean
    if op == "in":
        return BOOLEAN

    return None


def compare_op_type(op: str, left: MonoType, right: MonoType) -> MonoType | None:
    """Return the result type for a comparison, or None if invalid."""
    if op in ("===", "!==", "<", ">", "<=", ">="):
        # number vs number, string vs string, boolean vs boolean
        if type(left) is type(right) and isinstance(left, (NumberType, StringType, BooleanType)):
            return BOOLEAN
        # Allow comparison with undefined/null (=== undefined, !== null)
        if isinstance(left, (VoidType, NullType)) or isinstance(right, (VoidType, NullType)):
            return BOOLEAN
    return None


def unary_op_type(op: str, operand: MonoType) -> MonoType | None:
    """Return the result type for a unary operation."""
    if op in ("-", "+", "~") and isinstance(operand, NumberType):
        return NUMBER
    if op == "!" and isinstance(operand, BooleanType):
        return BOOLEAN
    # !number is also valid in JS → boolean
    if op == "!":
        return BOOLEAN
    # typeof always returns a string
    if op == "typeof":
        return STRING
    # void always returns undefined (number 0 in our system)
    if op == "void":
        return NUMBER
    return None
