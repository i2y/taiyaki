"""HIR (High-level Intermediate Representation) node definitions in SSA form."""

from __future__ import annotations

from dataclasses import dataclass, field

from taiyaki_aot_compiler.type_checker.types import ClassType, MonoType, NumberType, PromiseType


@dataclass
class HIRConst:
    value: float | bool | str | None
    type: MonoType
    result: str  # SSA variable name


@dataclass
class HIRParam:
    name: str
    type: MonoType
    result: str  # SSA variable name


@dataclass
class HIRBinaryOp:
    op: str  # "add", "sub", "mul", "div", "mod", "pow"
    left: str  # SSA var
    right: str  # SSA var
    result: str
    type: MonoType


@dataclass
class HIRUnaryOp:
    op: str  # "neg", "pos", "not"
    operand: str  # SSA var
    result: str
    type: MonoType


@dataclass
class HIRCompare:
    op: str  # "lt", "le", "gt", "ge", "eq", "ne"
    left: str
    right: str
    result: str
    operand_type: MonoType | None = None


@dataclass
class HIRCall:
    func_name: str
    args: list[str]  # SSA vars
    result: str
    type: MonoType
    is_js_fallback: bool = False


@dataclass
class HIRFFIStructCreate:
    """Create an FFI struct by value from field values."""
    field_values: list[str]  # SSA vars for each field (in order)
    result: str
    type: MonoType  # FFIStructType


@dataclass
class HIRFFIStructFieldGet:
    """Extract a field from an FFI struct by value (extractvalue)."""
    struct_val: str  # SSA var holding the struct value
    field_index: int
    result: str
    type: MonoType  # field type


@dataclass
class HIRAssign:
    target: str  # SSA var
    value: str  # SSA var


@dataclass
class HIRReturn:
    value: str | None  # SSA var or None
    type: MonoType


@dataclass
class HIRBranch:
    condition: str  # SSA var (bool)
    true_block: str  # label
    false_block: str  # label


@dataclass
class HIRJump:
    target_block: str  # label


@dataclass
class HIRPhi:
    incoming: list[tuple[str, str]]  # [(value SSA var, block label), ...]
    result: str
    type: MonoType


@dataclass
class HIRAllocObj:
    """Allocate an object (stack-allocated struct)."""
    fields: list[tuple[str, MonoType]]  # field name → type
    result: str  # SSA var (pointer to struct)
    type: MonoType  # ObjectType


@dataclass
class HIRFieldGet:
    """Read a field from an object."""
    obj: str  # SSA var (object pointer)
    field_name: str
    result: str
    type: MonoType  # field type


@dataclass
class HIRFieldSet:
    """Write a field to an object."""
    obj: str  # SSA var (object pointer)
    field_name: str
    value: str  # SSA var
    type: MonoType  # field type


@dataclass
class HIRAllocArray:
    """Allocate a heap array via C runtime."""
    elements: list[str]  # SSA vars for initial elements
    result: str  # SSA var (pointer to TsuchiArray)
    type: MonoType  # ArrayType


@dataclass
class HIRArrayGet:
    """Read an element from an array: arr[index]."""
    array: str  # SSA var (array pointer)
    index: str  # SSA var (f64 index)
    result: str
    type: MonoType  # element type


@dataclass
class HIRArraySet:
    """Write an element to an array: arr[index] = value."""
    array: str  # SSA var (array pointer)
    index: str  # SSA var (f64 index)
    value: str  # SSA var
    type: MonoType  # element type


@dataclass
class HIRArrayPush:
    """Push an element to an array: arr.push(value)."""
    array: str  # SSA var (array pointer)
    value: str  # SSA var
    result: str  # SSA var (new length as f64)
    type: MonoType  # element type


@dataclass
class HIRArrayLen:
    """Get array length: arr.length."""
    array: str  # SSA var (array pointer)
    result: str  # SSA var (length as f64)


@dataclass
class HIRFuncRef:
    """Get a pointer to a named function."""
    func_name: str  # Name of the target function
    result: str     # SSA variable holding the function pointer
    type: MonoType  # FunctionType


@dataclass
class HIRIndirectCall:
    """Call through a function pointer (SSA variable)."""
    callee: str       # SSA var holding the function pointer
    args: list[str]   # SSA vars for arguments
    result: str       # SSA var for return value
    type: MonoType    # Return type
    func_type: MonoType  # Full FunctionType (needed for LLVM call signature)


@dataclass
class HIRMakeClosure:
    """Create a closure: {fn_ptr, env_ptr} with captured values."""
    func_name: str              # lifted function name (has env as first param)
    captures: list[str]         # SSA vars for captured values
    capture_types: list[MonoType]  # types of captured values
    result: str                 # SSA var for closure pair
    type: MonoType              # FunctionType


@dataclass
class HIRLoadCapture:
    """Load a captured variable from the env pointer."""
    env: str                    # SSA var for env pointer (placeholder, codegen uses func.args[0])
    index: int                  # field index in env struct
    capture_types: list[MonoType]  # all capture types (for env struct layout)
    result: str                 # SSA var for loaded value
    type: MonoType              # type of captured variable


@dataclass
class HIRStoreCapture:
    """Store a value back into the env pointer (mutable capture)."""
    env: str                    # SSA var for env pointer (placeholder, codegen uses func.args[0])
    index: int                  # field index in env struct
    capture_types: list[MonoType]  # all capture types (for env struct layout)
    value: str                  # SSA var to store
    type: MonoType              # type of captured variable


@dataclass
class HIRLoadGlobal:
    """Load a module-level global variable."""
    name: str                   # global variable name
    result: str                 # SSA var for loaded value
    type: MonoType              # type of the global


@dataclass
class HIRStoreGlobal:
    """Store to a module-level global variable."""
    name: str                   # global variable name
    value: str                  # SSA var to store
    type: MonoType              # type of the global


@dataclass
class HIRArrayForEach:
    """arr.forEach(callback) — loop calling callback(elem, index) for each element."""
    array: str       # SSA var (array pointer)
    callback: str    # SSA var (closure pair {fn_ptr, env_ptr})
    cb_type: MonoType  # FunctionType of the callback


@dataclass
class HIRArrayMap:
    """arr.map(callback) — loop calling callback(elem, index), collect results in new array."""
    array: str       # SSA var (array pointer)
    callback: str    # SSA var (closure pair {fn_ptr, env_ptr})
    cb_type: MonoType  # FunctionType of the callback
    result: str      # SSA var (new array pointer)
    type: MonoType   # ArrayType of the result


@dataclass
class HIRArrayFilter:
    """arr.filter(callback) — loop calling callback(elem, index), collect truthy results."""
    array: str       # SSA var (array pointer)
    callback: str    # SSA var (closure pair {fn_ptr, env_ptr})
    cb_type: MonoType  # FunctionType of the callback
    result: str      # SSA var (new array pointer)
    type: MonoType   # ArrayType of the result (same element type)


@dataclass
class HIRArrayReduce:
    """arr.reduce(callback, initial) — fold over array."""
    array: str       # SSA var (array pointer)
    callback: str    # SSA var (closure pair {fn_ptr, env_ptr})
    cb_type: MonoType  # FunctionType of the callback
    initial: str     # SSA var (initial accumulator value)
    result: str      # SSA var (final accumulator value)
    type: MonoType   # type of result


@dataclass
class HIRArrayReduceRight:
    """arr.reduceRight(callback, initial) — fold over array from right to left."""
    array: str
    callback: str
    cb_type: MonoType
    initial: str
    result: str
    type: MonoType


@dataclass
class HIRArrayFind:
    """arr.find(callback) — loop calling callback(elem, index), return first truthy."""
    array: str       # SSA var (array pointer)
    callback: str    # SSA var (closure pair)
    cb_type: MonoType
    result: str      # SSA var (found element as f64, or NaN if not found)
    type: MonoType   # element type


@dataclass
class HIRArraySome:
    """arr.some(callback) — loop, return true if any callback returns truthy."""
    array: str
    callback: str
    cb_type: MonoType
    result: str      # SSA var (i1 boolean)
    type: MonoType


@dataclass
class HIRArrayEvery:
    """arr.every(callback) — loop, return true if all callbacks return truthy."""
    array: str
    callback: str
    cb_type: MonoType
    result: str      # SSA var (i1 boolean)
    type: MonoType


@dataclass
class HIRArrayFindIndex:
    """arr.findIndex(callback) — loop calling callback(elem, index), return first truthy index or -1."""
    array: str       # SSA var (array pointer)
    callback: str    # SSA var (closure pair)
    cb_type: MonoType
    result: str      # SSA var (f64 index, or -1 if not found)
    type: MonoType   # NUMBER


@dataclass
class HIRArraySort:
    """arr.sort(compareFn) — in-place sort with comparator callback."""
    array: str
    callback: str
    cb_type: MonoType
    result: str      # SSA var (same array pointer)
    type: MonoType


@dataclass
class HIRAwait:
    """Await a Promise. Becomes a state machine suspend point."""
    promise: str  # SSA var holding TsuchiPromise*
    result: str   # SSA var receiving resolved value
    result_type: MonoType = field(default_factory=lambda: NumberType())


@dataclass
class HIRTryCatch:
    """Try/catch/finally control flow.

    The LLVM generator handles setjmp/longjmp directly since jmp_buf
    must be allocated on the stack of the calling function.
    """
    try_block: str       # label of the try body block
    catch_block: str | None  # label of the catch body block (None if no catch)
    catch_param: str | None  # SSA var for error message (None if no catch param)
    finally_block: str | None  # label of the finally body block (None if no finally)
    merge_block: str     # label of the merge block after try/catch/finally


HIRInstruction = (
    HIRConst
    | HIRParam
    | HIRBinaryOp
    | HIRUnaryOp
    | HIRCompare
    | HIRCall
    | HIRAssign
    | HIRReturn
    | HIRBranch
    | HIRJump
    | HIRPhi
    | HIRAllocObj
    | HIRFieldGet
    | HIRFieldSet
    | HIRAllocArray
    | HIRArrayGet
    | HIRArraySet
    | HIRArrayPush
    | HIRArrayLen
    | HIRFuncRef
    | HIRIndirectCall
    | HIRMakeClosure
    | HIRLoadCapture
    | HIRArrayForEach
    | HIRArrayMap
    | HIRArrayFilter
    | HIRArrayReduce
    | HIRArrayFind
    | HIRArraySome
    | HIRArrayEvery
    | HIRArraySort
    | HIRAwait
    | HIRTryCatch
    | HIRFFIStructCreate
    | HIRFFIStructFieldGet
)


@dataclass
class BasicBlock:
    label: str
    instructions: list[HIRInstruction] = field(default_factory=list)
    terminator: HIRReturn | HIRBranch | HIRJump | None = None


@dataclass
class HIRFunction:
    name: str
    params: list[HIRParam]
    blocks: list[BasicBlock]
    return_type: MonoType
    is_exported: bool = True
    captures: list[tuple[str, MonoType]] = field(default_factory=list)
    is_async: bool = False


@dataclass
class FallbackFuncInfo:
    """Info about a non-compilable function for QuickJS fallback."""
    name: str
    param_count: int
    return_type_hint: str  # "number", "boolean", "string", "void"


@dataclass
class HIRModule:
    functions: list[HIRFunction]
    fallback_sources: dict[str, str] = field(default_factory=dict)
    fallback_signatures: dict[str, FallbackFuncInfo] = field(default_factory=dict)
    entry_statements: list[str] = field(default_factory=list)  # JS source for entry stmts
    classes: dict[str, ClassType] = field(default_factory=dict)  # Resolved class types
    func_aliases: dict[str, str] = field(default_factory=dict)  # alias → canonical name
    ffi_info: object = None  # FFIInfo from ffi_loader (optional)
    global_vars: dict[str, MonoType] = field(default_factory=dict)  # top-level var/let
    global_var_inits: dict[str, float] = field(default_factory=dict)  # constant initial values
