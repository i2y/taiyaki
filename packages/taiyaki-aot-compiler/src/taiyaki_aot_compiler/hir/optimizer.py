"""HIR optimization passes.

Operates on HIR (SSA form) before LLVM codegen. Performs:
1. Constant folding — evaluate HIRBinaryOp/HIRUnaryOp/HIRCompare with constant operands
2. Constant propagation — track constant SSA vars, substitute at use sites
3. Branch simplification — HIRBranch with constant condition → HIRJump
4. Dead block elimination — remove unreachable blocks via BFS
5. Copy propagation — HIRAssign(X, Y) → replace all uses of X with Y
6. Dead instruction elimination — remove unused side-effect-free instructions
"""

from __future__ import annotations

import math
import operator
from collections import defaultdict

from taiyaki_aot_compiler.hir.nodes import (
    HIRModule, HIRFunction, BasicBlock,
    HIRConst, HIRParam, HIRBinaryOp, HIRUnaryOp, HIRCompare,
    HIRCall, HIRAssign, HIRReturn, HIRBranch, HIRJump, HIRPhi,
    HIRAllocObj, HIRFieldGet, HIRFieldSet,
    HIRAllocArray, HIRArrayGet, HIRArraySet, HIRArrayPush, HIRArrayLen,
    HIRFuncRef, HIRIndirectCall,
    HIRMakeClosure, HIRLoadCapture, HIRStoreCapture,
    HIRArrayForEach, HIRArrayMap, HIRArrayFilter, HIRArrayReduce, HIRArrayReduceRight,
    HIRArrayFind, HIRArrayFindIndex, HIRArraySome, HIRArrayEvery, HIRArraySort,
    HIRTryCatch, HIRInstruction,
    HIRFFIStructCreate, HIRFFIStructFieldGet,
    HIRLoadGlobal, HIRStoreGlobal,
)
from taiyaki_aot_compiler.type_checker.types import (
    NumberType, BooleanType, StringType, MonoType,
    NUMBER, BOOLEAN, STRING,
)


# Binary ops that can be constant-folded
_BINOP_EVAL = {
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "div": operator.truediv,
    "mod": operator.mod,
    "pow": operator.pow,
}

# Comparison ops
_CMPOP_EVAL = {
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
    "eq": operator.eq,
    "ne": operator.ne,
}


def _is_side_effect_free(instr: HIRInstruction) -> bool:
    """Check if an instruction has no side effects (safe to remove if unused)."""
    return isinstance(instr, (
        HIRConst, HIRBinaryOp, HIRUnaryOp, HIRCompare, HIRAssign, HIRPhi,
    ))


def _get_result(instr: HIRInstruction) -> str | None:
    """Get the result SSA variable of an instruction, if any."""
    if hasattr(instr, 'result'):
        return instr.result
    return None


def _get_used_vars(instr: HIRInstruction) -> set[str]:
    """Get all SSA variables used (read) by an instruction."""
    used = set()
    if isinstance(instr, HIRConst):
        pass  # no inputs
    elif isinstance(instr, HIRParam):
        pass  # no inputs
    elif isinstance(instr, HIRBinaryOp):
        used.update([instr.left, instr.right])
    elif isinstance(instr, HIRUnaryOp):
        used.add(instr.operand)
    elif isinstance(instr, HIRCompare):
        used.update([instr.left, instr.right])
    elif isinstance(instr, HIRCall):
        used.update(instr.args)
    elif isinstance(instr, HIRAssign):
        used.add(instr.value)
    elif isinstance(instr, HIRReturn):
        if instr.value:
            used.add(instr.value)
    elif isinstance(instr, HIRBranch):
        used.add(instr.condition)
    elif isinstance(instr, HIRPhi):
        for val, _blk in instr.incoming:
            used.add(val)
    elif isinstance(instr, HIRAllocObj):
        pass
    elif isinstance(instr, HIRFieldGet):
        used.add(instr.obj)
    elif isinstance(instr, HIRFieldSet):
        used.update([instr.obj, instr.value])
    elif isinstance(instr, HIRAllocArray):
        used.update(instr.elements)
    elif isinstance(instr, HIRArrayGet):
        used.update([instr.array, instr.index])
    elif isinstance(instr, HIRArraySet):
        used.update([instr.array, instr.index, instr.value])
    elif isinstance(instr, HIRArrayPush):
        used.update([instr.array, instr.value])
    elif isinstance(instr, HIRArrayLen):
        used.add(instr.array)
    elif isinstance(instr, HIRFuncRef):
        pass
    elif isinstance(instr, HIRIndirectCall):
        used.add(instr.callee)
        used.update(instr.args)
    elif isinstance(instr, HIRMakeClosure):
        used.update(instr.captures)
    elif isinstance(instr, HIRLoadCapture):
        used.add(instr.env)
    elif isinstance(instr, HIRStoreCapture):
        used.update([instr.env, instr.value])
    elif isinstance(instr, HIRArrayForEach):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRArrayMap):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRArrayFilter):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRArrayReduce):
        used.update([instr.array, instr.callback, instr.initial])
    elif isinstance(instr, HIRArrayReduceRight):
        used.update([instr.array, instr.callback, instr.initial])
    elif isinstance(instr, HIRArrayFind):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRArrayFindIndex):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRArraySome):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRArrayEvery):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRArraySort):
        used.update([instr.array, instr.callback])
    elif isinstance(instr, HIRTryCatch):
        pass  # TryCatch references blocks, not SSA vars directly
    elif isinstance(instr, HIRFFIStructCreate):
        used.update(instr.field_values)
    elif isinstance(instr, HIRFFIStructFieldGet):
        used.add(instr.struct_val)
    elif isinstance(instr, HIRLoadGlobal):
        pass  # no SSA inputs
    elif isinstance(instr, HIRStoreGlobal):
        used.add(instr.value)  # the value being stored is used
    return used


def _get_terminator_used_vars(term) -> set[str]:
    """Get variables used by a terminator."""
    if isinstance(term, HIRBranch):
        return {term.condition}
    elif isinstance(term, HIRReturn):
        return {term.value} if term.value else set()
    return set()


class HIROptimizer:
    """Optimize HIR functions with standard compiler optimizations."""

    def optimize_module(self, module: HIRModule) -> HIRModule:
        """Optimize all functions in a module."""
        optimized_funcs = [self.optimize_function(f) for f in module.functions]
        return HIRModule(
            functions=optimized_funcs,
            fallback_sources=module.fallback_sources,
            fallback_signatures=module.fallback_signatures,
            entry_statements=module.entry_statements,
            classes=module.classes,
            func_aliases=module.func_aliases,
            ffi_info=module.ffi_info,
            global_vars=module.global_vars,
            global_var_inits=module.global_var_inits,
        )

    def optimize_function(self, func: HIRFunction) -> HIRFunction:
        """Apply optimization passes to a single function."""
        blocks = list(func.blocks)

        # Iterative passes: copy prop + constant fold + propagate + branch simplify
        for _ in range(3):
            constants: dict[str, HIRConst] = {}
            old_blocks = blocks
            blocks = self._copy_propagation(blocks)
            blocks = self._constant_propagation(blocks, constants)
            blocks = self._constant_folding(blocks, constants)
            blocks = self._branch_simplification(blocks, constants)
            if blocks == old_blocks:
                break

        # Single-pass cleanups
        blocks = self._dead_block_elimination(blocks)
        blocks = self._dead_instruction_elimination(blocks)

        return HIRFunction(
            name=func.name,
            params=func.params,
            blocks=blocks,
            return_type=func.return_type,
            is_exported=func.is_exported,
            captures=func.captures,
            is_async=func.is_async,
        )

    def _constant_propagation(self, blocks: list[BasicBlock],
                               constants: dict[str, HIRConst]) -> list[BasicBlock]:
        """Track which SSA vars are constants. Build the constants map."""
        for bb in blocks:
            for instr in bb.instructions:
                if isinstance(instr, HIRConst):
                    constants[instr.result] = instr
        return blocks

    def _constant_folding(self, blocks: list[BasicBlock],
                           constants: dict[str, HIRConst]) -> list[BasicBlock]:
        """Fold binary/unary/compare ops where all operands are constants."""
        new_blocks = []
        changed = False
        for bb in blocks:
            new_instrs = []
            for instr in bb.instructions:
                folded = self._try_fold(instr, constants)
                if folded is not None:
                    new_instrs.append(folded)
                    constants[folded.result] = folded
                    changed = True
                else:
                    new_instrs.append(instr)
            new_blocks.append(BasicBlock(
                label=bb.label,
                instructions=new_instrs,
                terminator=bb.terminator,
            ))
        return new_blocks

    def _try_fold(self, instr: HIRInstruction,
                   constants: dict[str, HIRConst]) -> HIRConst | None:
        """Try to fold an instruction into a constant. Returns None if not foldable."""
        if isinstance(instr, HIRBinaryOp):
            left_c = constants.get(instr.left)
            right_c = constants.get(instr.right)
            if left_c is not None and right_c is not None:
                return self._fold_binary(instr, left_c, right_c)
        elif isinstance(instr, HIRUnaryOp):
            operand_c = constants.get(instr.operand)
            if operand_c is not None:
                return self._fold_unary(instr, operand_c)
        elif isinstance(instr, HIRCompare):
            left_c = constants.get(instr.left)
            right_c = constants.get(instr.right)
            if left_c is not None and right_c is not None:
                return self._fold_compare(instr, left_c, right_c)
        return None

    def _fold_binary(self, instr: HIRBinaryOp,
                      left: HIRConst, right: HIRConst) -> HIRConst | None:
        """Fold a binary op with constant operands."""
        lv, rv = left.value, right.value

        # String concatenation
        if instr.op == "add" and isinstance(lv, str) and isinstance(rv, str):
            return HIRConst(value=lv + rv, type=STRING, result=instr.result)

        # Numeric operations
        if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
            return self._fold_numeric_binary(instr.op, float(lv), float(rv), instr.result)

        # Boolean operands coerced to number
        if isinstance(lv, bool) and isinstance(rv, bool):
            ln = 1.0 if lv else 0.0
            rn = 1.0 if rv else 0.0
            return self._fold_numeric_binary(instr.op, ln, rn, instr.result)

        return None

    def _fold_numeric_binary(self, op: str, lv: float, rv: float,
                              result: str) -> HIRConst | None:
        """Fold a numeric binary op using JS semantics."""
        try:
            if op == "div" and rv == 0:
                return None
            if op == "mod" and rv == 0:
                return None
            if op == "mod":
                # JS modulo: sign follows dividend (C semantics), not Python's
                val = math.fmod(lv, rv)
            else:
                op_fn = _BINOP_EVAL.get(op)
                if op_fn is None:
                    return None
                val = op_fn(lv, rv)
            return HIRConst(value=val, type=NUMBER, result=result)
        except (ZeroDivisionError, ValueError, OverflowError):
            return None

    def _fold_unary(self, instr: HIRUnaryOp, operand: HIRConst) -> HIRConst | None:
        """Fold a unary op with a constant operand."""
        v = operand.value
        if instr.op == "neg" and isinstance(v, (int, float)):
            return HIRConst(value=-float(v), type=NUMBER, result=instr.result)
        if instr.op == "not" and isinstance(v, bool):
            return HIRConst(value=not v, type=BOOLEAN, result=instr.result)
        if instr.op == "not" and isinstance(v, (int, float)):
            return HIRConst(value=v == 0, type=BOOLEAN, result=instr.result)
        if instr.op == "pos" and isinstance(v, (int, float)):
            return HIRConst(value=float(v), type=NUMBER, result=instr.result)
        return None

    def _fold_compare(self, instr: HIRCompare,
                       left: HIRConst, right: HIRConst) -> HIRConst | None:
        """Fold a comparison with constant operands."""
        lv, rv = left.value, right.value

        # String comparison
        if isinstance(lv, str) and isinstance(rv, str):
            op_fn = _CMPOP_EVAL.get(instr.op)
            if op_fn is not None:
                return HIRConst(value=op_fn(lv, rv), type=BOOLEAN, result=instr.result)

        # Numeric comparison
        if isinstance(lv, (int, float, bool)) and isinstance(rv, (int, float, bool)):
            ln = float(1 if lv is True else (0 if lv is False else lv))
            rn = float(1 if rv is True else (0 if rv is False else rv))
            op_fn = _CMPOP_EVAL.get(instr.op)
            if op_fn is not None:
                return HIRConst(value=op_fn(ln, rn), type=BOOLEAN, result=instr.result)

        return None

    def _branch_simplification(self, blocks: list[BasicBlock],
                                constants: dict[str, HIRConst]) -> list[BasicBlock]:
        """Replace HIRBranch with constant condition by HIRJump.

        Also updates phi nodes in orphaned target blocks to remove references
        to the block whose branch was simplified.
        """
        # Collect which blocks are orphaned from which source
        orphaned_edges: list[tuple[str, str]] = []  # (source_label, orphaned_target)

        new_blocks = []
        for bb in blocks:
            term = bb.terminator
            if isinstance(term, HIRBranch):
                cond_c = constants.get(term.condition)
                if cond_c is not None and isinstance(cond_c.value, bool):
                    target = term.true_block if cond_c.value else term.false_block
                    orphaned = term.false_block if cond_c.value else term.true_block
                    orphaned_edges.append((bb.label, orphaned))
                    new_blocks.append(BasicBlock(
                        label=bb.label,
                        instructions=list(bb.instructions),
                        terminator=HIRJump(target_block=target),
                    ))
                    continue
            new_blocks.append(bb)

        # Update phi nodes in orphaned targets
        if orphaned_edges:
            orphaned_map: dict[str, set[str]] = {}
            for src, tgt in orphaned_edges:
                orphaned_map.setdefault(tgt, set()).add(src)

            result = []
            for bb in new_blocks:
                if bb.label in orphaned_map:
                    dead_preds = orphaned_map[bb.label]
                    new_instrs = []
                    for instr in bb.instructions:
                        if isinstance(instr, HIRPhi):
                            new_incoming = [(val, blk) for val, blk in instr.incoming
                                           if blk not in dead_preds]
                            if new_incoming:
                                new_instrs.append(HIRPhi(
                                    incoming=new_incoming,
                                    result=instr.result,
                                    type=instr.type,
                                ))
                        else:
                            new_instrs.append(instr)
                    result.append(BasicBlock(
                        label=bb.label,
                        instructions=new_instrs,
                        terminator=bb.terminator,
                    ))
                else:
                    result.append(bb)
            return result

        return new_blocks

    def _dead_block_elimination(self, blocks: list[BasicBlock]) -> list[BasicBlock]:
        """Remove unreachable blocks via BFS from entry."""
        if not blocks:
            return blocks

        # Build reachability set
        reachable = set()
        worklist = [blocks[0].label]
        block_map = {bb.label: bb for bb in blocks}

        while worklist:
            label = worklist.pop()
            if label in reachable:
                continue
            reachable.add(label)
            bb = block_map.get(label)
            if bb is None:
                continue
            # Follow successors from terminator
            term = bb.terminator
            if isinstance(term, HIRJump):
                worklist.append(term.target_block)
            elif isinstance(term, HIRBranch):
                worklist.append(term.true_block)
                worklist.append(term.false_block)
            # Follow successors from TryCatch instructions
            for instr in bb.instructions:
                if isinstance(instr, HIRTryCatch):
                    worklist.append(instr.try_block)
                    if instr.catch_block:
                        worklist.append(instr.catch_block)
                    if instr.finally_block:
                        worklist.append(instr.finally_block)
                    worklist.append(instr.merge_block)

        dead_labels = {bb.label for bb in blocks} - reachable
        if not dead_labels:
            return blocks

        # Filter blocks and update phi nodes to remove dead predecessors
        result = []
        for bb in blocks:
            if bb.label not in reachable:
                continue
            new_instrs = []
            for instr in bb.instructions:
                if isinstance(instr, HIRPhi):
                    new_incoming = [(val, blk) for val, blk in instr.incoming
                                   if blk not in dead_labels]
                    if new_incoming:
                        new_instrs.append(HIRPhi(
                            incoming=new_incoming,
                            result=instr.result,
                            type=instr.type,
                        ))
                    # If no incoming left, skip this phi entirely
                else:
                    new_instrs.append(instr)
            result.append(BasicBlock(
                label=bb.label,
                instructions=new_instrs,
                terminator=bb.terminator,
            ))
        return result

    def _copy_propagation(self, blocks: list[BasicBlock]) -> list[BasicBlock]:
        """Replace uses of X where HIRAssign(X, Y) with Y."""
        # Build copy map: target → source
        copies: dict[str, str] = {}
        for bb in blocks:
            for instr in bb.instructions:
                if isinstance(instr, HIRAssign):
                    copies[instr.target] = instr.value

        if not copies:
            return blocks

        # Resolve transitive copies: X→Y→Z → X→Z
        def resolve(var: str) -> str:
            visited = set()
            while var in copies and var not in visited:
                visited.add(var)
                var = copies[var]
            return var

        # Apply substitution to all instructions
        new_blocks = []
        for bb in blocks:
            new_instrs = []
            for instr in bb.instructions:
                new_instrs.append(self._substitute_vars(instr, resolve))
            new_term = self._substitute_terminator(bb.terminator, resolve) if bb.terminator else None
            new_blocks.append(BasicBlock(
                label=bb.label,
                instructions=new_instrs,
                terminator=new_term,
            ))
        return new_blocks

    def _substitute_vars(self, instr: HIRInstruction, resolve) -> HIRInstruction:
        """Substitute SSA variables in an instruction using resolve function."""
        if isinstance(instr, HIRBinaryOp):
            return HIRBinaryOp(
                op=instr.op, left=resolve(instr.left), right=resolve(instr.right),
                result=instr.result, type=instr.type,
            )
        elif isinstance(instr, HIRUnaryOp):
            return HIRUnaryOp(
                op=instr.op, operand=resolve(instr.operand),
                result=instr.result, type=instr.type,
            )
        elif isinstance(instr, HIRCompare):
            return HIRCompare(
                op=instr.op, left=resolve(instr.left), right=resolve(instr.right),
                result=instr.result, operand_type=instr.operand_type,
            )
        elif isinstance(instr, HIRCall):
            return HIRCall(
                func_name=instr.func_name,
                args=[resolve(a) for a in instr.args],
                result=instr.result, type=instr.type,
                is_js_fallback=instr.is_js_fallback,
            )
        elif isinstance(instr, HIRAssign):
            return HIRAssign(target=instr.target, value=resolve(instr.value))
        elif isinstance(instr, HIRPhi):
            return HIRPhi(
                incoming=[(resolve(val), blk) for val, blk in instr.incoming],
                result=instr.result, type=instr.type,
            )
        elif isinstance(instr, HIRIndirectCall):
            return HIRIndirectCall(
                callee=resolve(instr.callee),
                args=[resolve(a) for a in instr.args],
                result=instr.result, type=instr.type,
                func_type=instr.func_type,
            )
        elif isinstance(instr, HIRFieldGet):
            return HIRFieldGet(
                obj=resolve(instr.obj), field_name=instr.field_name,
                result=instr.result, type=instr.type,
            )
        elif isinstance(instr, HIRFieldSet):
            return HIRFieldSet(
                obj=resolve(instr.obj), field_name=instr.field_name,
                value=resolve(instr.value), type=instr.type,
            )
        elif isinstance(instr, HIRArrayGet):
            return HIRArrayGet(
                array=resolve(instr.array), index=resolve(instr.index),
                result=instr.result, type=instr.type,
            )
        elif isinstance(instr, HIRArraySet):
            return HIRArraySet(
                array=resolve(instr.array), index=resolve(instr.index),
                value=resolve(instr.value), type=instr.type,
            )
        elif isinstance(instr, HIRArrayPush):
            return HIRArrayPush(
                array=resolve(instr.array), value=resolve(instr.value),
                result=instr.result, type=instr.type,
            )
        elif isinstance(instr, HIRArrayLen):
            return HIRArrayLen(array=resolve(instr.array), result=instr.result)
        return instr  # HIRConst, HIRParam, etc. — no var substitution needed

    def _substitute_terminator(self, term, resolve):
        """Substitute variables in a terminator."""
        if isinstance(term, HIRBranch):
            return HIRBranch(
                condition=resolve(term.condition),
                true_block=term.true_block,
                false_block=term.false_block,
            )
        elif isinstance(term, HIRReturn):
            return HIRReturn(
                value=resolve(term.value) if term.value else None,
                type=term.type,
            )
        return term  # HIRJump has no variables

    def _dead_instruction_elimination(self, blocks: list[BasicBlock]) -> list[BasicBlock]:
        """Remove instructions whose results are never used."""
        # Collect all used variables
        used_vars: set[str] = set()
        for bb in blocks:
            for instr in bb.instructions:
                used_vars.update(_get_used_vars(instr))
            if bb.terminator:
                used_vars.update(_get_terminator_used_vars(bb.terminator))

        # Remove unused side-effect-free instructions
        new_blocks = []
        for bb in blocks:
            new_instrs = []
            for instr in bb.instructions:
                result = _get_result(instr)
                if result is not None and result not in used_vars and _is_side_effect_free(instr):
                    continue  # Dead instruction — skip
                new_instrs.append(instr)
            new_blocks.append(BasicBlock(
                label=bb.label,
                instructions=new_instrs,
                terminator=bb.terminator,
            ))
        return new_blocks
