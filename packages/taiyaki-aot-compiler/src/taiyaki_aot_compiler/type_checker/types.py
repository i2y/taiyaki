"""Type representations for the Tsuchi type system."""

from __future__ import annotations

from dataclasses import dataclass, field


class MonoType:
    """Base class for all monomorphic types."""

    def apply(self, subst: Substitution) -> MonoType:
        return self

    def free_type_vars(self) -> set[int]:
        return set()

    def __eq__(self, other):
        return type(self) is type(other)

    def __hash__(self):
        return hash(type(self))


class NumberType(MonoType):
    """JS number — always f64."""
    def __repr__(self):
        return "number"


class BooleanType(MonoType):
    def __repr__(self):
        return "boolean"


class StringType(MonoType):
    def __repr__(self):
        return "string"


class NullType(MonoType):
    def __repr__(self):
        return "null"


class VoidType(MonoType):
    def __repr__(self):
        return "void"


_next_typevar_id = 0


def _fresh_id() -> int:
    global _next_typevar_id
    _next_typevar_id += 1
    return _next_typevar_id


def reset_typevar_counter():
    global _next_typevar_id
    _next_typevar_id = 0


@dataclass
class TypeVar(MonoType):
    id: int = field(default_factory=_fresh_id)

    def apply(self, subst: Substitution) -> MonoType:
        if self.id in subst.mapping:
            return subst.mapping[self.id].apply(subst)
        return self

    def free_type_vars(self) -> set[int]:
        return {self.id}

    def __eq__(self, other):
        return isinstance(other, TypeVar) and self.id == other.id

    def __hash__(self):
        return hash(("TypeVar", self.id))

    def __repr__(self):
        return f"T{self.id}"


@dataclass
class FunctionType(MonoType):
    param_types: list[MonoType]
    return_type: MonoType

    def apply(self, subst: Substitution) -> MonoType:
        return FunctionType(
            [p.apply(subst) for p in self.param_types],
            self.return_type.apply(subst),
        )

    def free_type_vars(self) -> set[int]:
        result: set[int] = set()
        for p in self.param_types:
            result |= p.free_type_vars()
        result |= self.return_type.free_type_vars()
        return result

    def __eq__(self, other):
        return (
            isinstance(other, FunctionType)
            and self.param_types == other.param_types
            and self.return_type == other.return_type
        )

    def __hash__(self):
        return hash(("FunctionType", tuple(self.param_types), self.return_type))

    def __repr__(self):
        params = ", ".join(repr(p) for p in self.param_types)
        return f"({params}) => {self.return_type!r}"


@dataclass
class ArrayType(MonoType):
    element_type: MonoType

    def apply(self, subst: Substitution) -> MonoType:
        return ArrayType(self.element_type.apply(subst))

    def free_type_vars(self) -> set[int]:
        return self.element_type.free_type_vars()

    def __eq__(self, other):
        return isinstance(other, ArrayType) and self.element_type == other.element_type

    def __hash__(self):
        return hash(("ArrayType", self.element_type))

    def __repr__(self):
        return f"{self.element_type!r}[]"


@dataclass
class PromiseType(MonoType):
    """Promise<T> — resolved value type is inner_type."""
    inner_type: MonoType

    def apply(self, subst: Substitution) -> MonoType:
        return PromiseType(self.inner_type.apply(subst))

    def free_type_vars(self) -> set[int]:
        return self.inner_type.free_type_vars()

    def __eq__(self, other):
        return isinstance(other, PromiseType) and self.inner_type == other.inner_type

    def __hash__(self):
        return hash(("PromiseType", self.inner_type))

    def __repr__(self):
        return f"Promise<{self.inner_type!r}>"


@dataclass
class ObjectType(MonoType):
    """Object type / interface: { key: Type }."""
    fields: dict[str, MonoType] = field(default_factory=dict)

    def apply(self, subst: Substitution) -> MonoType:
        return ObjectType({k: v.apply(subst) for k, v in self.fields.items()})

    def free_type_vars(self) -> set[int]:
        result: set[int] = set()
        for v in self.fields.values():
            result |= v.free_type_vars()
        return result

    def __eq__(self, other):
        return isinstance(other, ObjectType) and self.fields == other.fields

    def __hash__(self):
        return hash(("ObjectType", tuple(sorted(self.fields.items()))))

    def __repr__(self):
        fields = ", ".join(f"{k}: {v!r}" for k, v in self.fields.items())
        return f"{{ {fields} }}"


@dataclass
class ClassType(MonoType):
    """Class type: tracks fields (from constructor) and methods."""
    name: str = ""
    fields: dict[str, MonoType] = field(default_factory=dict)
    methods: dict[str, FunctionType] = field(default_factory=dict)

    def apply(self, subst: Substitution) -> MonoType:
        # ClassType is a named type — don't recursively apply to avoid cycles
        return self

    def free_type_vars(self) -> set[int]:
        return set()

    def __eq__(self, other):
        return isinstance(other, ClassType) and self.name == other.name

    def __hash__(self):
        return hash(("ClassType", self.name))

    def __repr__(self):
        return f"class {self.name}"

    def instance_type(self) -> ObjectType:
        """Return the ObjectType of instances of this class (data fields only, no methods).

        For classes with inheritance, fields preserve insertion order
        (parent fields first) via the _ordered flag.
        """
        ot = ObjectType(fields=dict(self.fields))
        ot._ordered = True  # Use insertion order, not alphabetical
        return ot


@dataclass
class FFIStructType(MonoType):
    """FFI struct passed by value: { x: number, y: number } → LLVM {double, double}."""
    name: str = ""
    fields: dict[str, MonoType] = field(default_factory=dict)

    def apply(self, subst: Substitution) -> MonoType:
        return self

    def free_type_vars(self) -> set[int]:
        return set()

    def __eq__(self, other):
        return isinstance(other, FFIStructType) and self.name == other.name

    def __hash__(self):
        return hash(("FFIStructType", self.name))

    def __repr__(self):
        return f"ffi_struct {self.name}"


@dataclass
class OpaquePointerType(MonoType):
    """Opaque pointer to a C resource: i8* in LLVM."""
    name: str = ""

    def apply(self, subst: Substitution) -> MonoType:
        return self

    def free_type_vars(self) -> set[int]:
        return set()

    def __eq__(self, other):
        return isinstance(other, OpaquePointerType) and self.name == other.name

    def __hash__(self):
        return hash(("OpaquePointerType", self.name))

    def __repr__(self):
        return f"opaque {self.name}"


class Substitution:
    """A mapping from TypeVar ids to MonoTypes."""

    def __init__(self, mapping: dict[int, MonoType] | None = None):
        self.mapping: dict[int, MonoType] = mapping or {}

    def apply(self, ty: MonoType) -> MonoType:
        return ty.apply(self)

    def compose(self, other: Substitution) -> Substitution:
        """Compose two substitutions: self after other."""
        new_mapping = {k: self.apply(v) for k, v in other.mapping.items()}
        new_mapping.update(self.mapping)
        return Substitution(new_mapping)

    def __repr__(self):
        items = ", ".join(f"T{k} -> {v!r}" for k, v in self.mapping.items())
        return f"Subst({items})"


# Singleton instances
NUMBER = NumberType()
BOOLEAN = BooleanType()
STRING = StringType()
NULL = NullType()
VOID = VoidType()
