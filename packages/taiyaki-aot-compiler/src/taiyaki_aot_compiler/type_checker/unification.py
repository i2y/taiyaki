"""Type unification for HM type inference."""

from __future__ import annotations

from .types import (
    MonoType,
    TypeVar,
    FunctionType,
    ArrayType,
    ObjectType,
    ClassType,
    NumberType,
    BooleanType,
    StringType,
    NullType,
    VoidType,
    Substitution,
)


class UnificationError(Exception):
    def __init__(self, t1: MonoType, t2: MonoType, message: str = ""):
        self.t1 = t1
        self.t2 = t2
        if message:
            super().__init__(message)
        else:
            super().__init__(f"Cannot unify {t1!r} with {t2!r}")


def occurs_check(var_id: int, ty: MonoType) -> bool:
    """Check if type variable occurs in type (prevents infinite types)."""
    if isinstance(ty, TypeVar):
        return ty.id == var_id
    if isinstance(ty, FunctionType):
        return any(occurs_check(var_id, p) for p in ty.param_types) or occurs_check(
            var_id, ty.return_type
        )
    if isinstance(ty, ArrayType):
        return occurs_check(var_id, ty.element_type)
    if isinstance(ty, ObjectType):
        return any(occurs_check(var_id, ft) for ft in ty.fields.values())
    return False


def unify(t1: MonoType, t2: MonoType) -> Substitution:
    """Unify two types, returning a substitution that makes them equal."""
    if isinstance(t1, TypeVar) and isinstance(t2, TypeVar) and t1.id == t2.id:
        return Substitution()

    if isinstance(t1, TypeVar):
        if occurs_check(t1.id, t2):
            raise UnificationError(t1, t2, f"Occurs check failed: {t1!r} in {t2!r}")
        return Substitution({t1.id: t2})

    if isinstance(t2, TypeVar):
        if occurs_check(t2.id, t1):
            raise UnificationError(t1, t2, f"Occurs check failed: {t2!r} in {t1!r}")
        return Substitution({t2.id: t1})

    # Same concrete types
    if type(t1) is type(t2) and isinstance(
        t1, (NumberType, BooleanType, StringType, NullType, VoidType)
    ):
        return Substitution()

    # Function types
    if isinstance(t1, FunctionType) and isinstance(t2, FunctionType):
        if len(t1.param_types) != len(t2.param_types):
            raise UnificationError(
                t1, t2,
                f"Function arity mismatch: {len(t1.param_types)} vs {len(t2.param_types)}",
            )
        subst = Substitution()
        for p1, p2 in zip(t1.param_types, t2.param_types):
            s = unify(subst.apply(p1), subst.apply(p2))
            subst = s.compose(subst)
        s = unify(subst.apply(t1.return_type), subst.apply(t2.return_type))
        subst = s.compose(subst)
        return subst

    # Array types
    if isinstance(t1, ArrayType) and isinstance(t2, ArrayType):
        return unify(t1.element_type, t2.element_type)

    # Object types
    if isinstance(t1, ObjectType) and isinstance(t2, ObjectType):
        subst = Substitution()
        for fname in t1.fields:
            if fname in t2.fields:
                s = unify(subst.apply(t1.fields[fname]), subst.apply(t2.fields[fname]))
                subst = s.compose(subst)
        return subst

    # Class types (same class name = same type)
    if isinstance(t1, ClassType) and isinstance(t2, ClassType):
        if t1.name == t2.name:
            return Substitution()
        raise UnificationError(t1, t2)

    raise UnificationError(t1, t2)
