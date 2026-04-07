"""Tests for HIR optimization passes."""

import pytest
from tsuchi.hir.nodes import (
    HIRModule, HIRFunction, BasicBlock, FallbackFuncInfo,
    HIRConst, HIRParam, HIRBinaryOp, HIRUnaryOp, HIRCompare,
    HIRAssign, HIRReturn, HIRBranch, HIRJump, HIRPhi,
)
from tsuchi.hir.optimizer import HIROptimizer
from tsuchi.type_checker.types import NUMBER, BOOLEAN, STRING, VOID


def _make_func(name: str, blocks: list[BasicBlock],
               params=None, return_type=NUMBER) -> HIRFunction:
    return HIRFunction(
        name=name,
        params=params or [],
        blocks=blocks,
        return_type=return_type,
    )


def _make_module(funcs: list[HIRFunction]) -> HIRModule:
    return HIRModule(functions=funcs)


class TestConstantFolding:
    def test_add_numbers(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=3.0, type=NUMBER, result="t0"),
                HIRConst(value=4.0, type=NUMBER, result="t1"),
                HIRBinaryOp(op="add", left="t0", right="t1", result="t2", type=NUMBER),
            ],
            terminator=HIRReturn(value="t2", type=NUMBER),
        )]
        func = _make_func("add_const", blocks)
        opt = HIROptimizer()
        result = opt.optimize_function(func)
        # t2 should be folded to a constant 7.0
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t2" and c.value == 7.0 for c in consts)

    def test_mul_numbers(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=5.0, type=NUMBER, result="t0"),
                HIRConst(value=6.0, type=NUMBER, result="t1"),
                HIRBinaryOp(op="mul", left="t0", right="t1", result="t2", type=NUMBER),
            ],
            terminator=HIRReturn(value="t2", type=NUMBER),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("mul_const", blocks))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t2" and c.value == 30.0 for c in consts)

    def test_string_concat(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value="hello", type=STRING, result="t0"),
                HIRConst(value=" world", type=STRING, result="t1"),
                HIRBinaryOp(op="add", left="t0", right="t1", result="t2", type=STRING),
            ],
            terminator=HIRReturn(value="t2", type=STRING),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("str_concat", blocks, return_type=STRING))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t2" and c.value == "hello world" for c in consts)

    def test_chained_fold(self):
        """Test that chained constant expressions are folded across iterations."""
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=2.0, type=NUMBER, result="t0"),
                HIRConst(value=3.0, type=NUMBER, result="t1"),
                HIRBinaryOp(op="add", left="t0", right="t1", result="t2", type=NUMBER),
                HIRConst(value=4.0, type=NUMBER, result="t3"),
                HIRBinaryOp(op="mul", left="t2", right="t3", result="t4", type=NUMBER),
            ],
            terminator=HIRReturn(value="t4", type=NUMBER),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("chained", blocks))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t4" and c.value == 20.0 for c in consts)

    def test_div_by_zero_not_folded(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=1.0, type=NUMBER, result="t0"),
                HIRConst(value=0.0, type=NUMBER, result="t1"),
                HIRBinaryOp(op="div", left="t0", right="t1", result="t2", type=NUMBER),
            ],
            terminator=HIRReturn(value="t2", type=NUMBER),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("divzero", blocks))
        # Should NOT be folded (division by zero)
        binops = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRBinaryOp)]
        assert len(binops) == 1


class TestUnaryFolding:
    def test_negate(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=5.0, type=NUMBER, result="t0"),
                HIRUnaryOp(op="neg", operand="t0", result="t1", type=NUMBER),
            ],
            terminator=HIRReturn(value="t1", type=NUMBER),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("neg", blocks))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t1" and c.value == -5.0 for c in consts)

    def test_not_bool(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=True, type=BOOLEAN, result="t0"),
                HIRUnaryOp(op="not", operand="t0", result="t1", type=BOOLEAN),
            ],
            terminator=HIRReturn(value="t1", type=BOOLEAN),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("not_bool", blocks, return_type=BOOLEAN))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t1" and c.value is False for c in consts)


class TestCompareFolding:
    def test_lt_true(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=1.0, type=NUMBER, result="t0"),
                HIRConst(value=2.0, type=NUMBER, result="t1"),
                HIRCompare(op="lt", left="t0", right="t1", result="t2"),
            ],
            terminator=HIRReturn(value="t2", type=BOOLEAN),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("lt_true", blocks, return_type=BOOLEAN))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t2" and c.value is True for c in consts)

    def test_eq_strings(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value="abc", type=STRING, result="t0"),
                HIRConst(value="abc", type=STRING, result="t1"),
                HIRCompare(op="eq", left="t0", right="t1", result="t2"),
            ],
            terminator=HIRReturn(value="t2", type=BOOLEAN),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("eq_str", blocks, return_type=BOOLEAN))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t2" and c.value is True for c in consts)


class TestBranchSimplification:
    def test_const_true_branch(self):
        blocks = [
            BasicBlock(
                label="entry",
                instructions=[
                    HIRConst(value=True, type=BOOLEAN, result="cond"),
                ],
                terminator=HIRBranch(condition="cond", true_block="then", false_block="else"),
            ),
            BasicBlock(
                label="then",
                instructions=[HIRConst(value=1.0, type=NUMBER, result="r1")],
                terminator=HIRReturn(value="r1", type=NUMBER),
            ),
            BasicBlock(
                label="else",
                instructions=[HIRConst(value=2.0, type=NUMBER, result="r2")],
                terminator=HIRReturn(value="r2", type=NUMBER),
            ),
        ]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("branch_const", blocks))
        # Entry block should have HIRJump to "then", not HIRBranch
        entry = result.blocks[0]
        assert isinstance(entry.terminator, HIRJump)
        assert entry.terminator.target_block == "then"

    def test_const_false_branch(self):
        blocks = [
            BasicBlock(
                label="entry",
                instructions=[
                    HIRConst(value=False, type=BOOLEAN, result="cond"),
                ],
                terminator=HIRBranch(condition="cond", true_block="then", false_block="else"),
            ),
            BasicBlock(
                label="then",
                instructions=[HIRConst(value=1.0, type=NUMBER, result="r1")],
                terminator=HIRReturn(value="r1", type=NUMBER),
            ),
            BasicBlock(
                label="else",
                instructions=[HIRConst(value=2.0, type=NUMBER, result="r2")],
                terminator=HIRReturn(value="r2", type=NUMBER),
            ),
        ]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("branch_false", blocks))
        entry = result.blocks[0]
        assert isinstance(entry.terminator, HIRJump)
        assert entry.terminator.target_block == "else"


class TestDeadBlockElimination:
    def test_unreachable_block_removed(self):
        blocks = [
            BasicBlock(
                label="entry",
                instructions=[HIRConst(value=1.0, type=NUMBER, result="r")],
                terminator=HIRReturn(value="r", type=NUMBER),
            ),
            BasicBlock(
                label="dead",
                instructions=[HIRConst(value=2.0, type=NUMBER, result="r2")],
                terminator=HIRReturn(value="r2", type=NUMBER),
            ),
        ]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("dead_block", blocks))
        assert len(result.blocks) == 1
        assert result.blocks[0].label == "entry"

    def test_reachable_block_kept(self):
        blocks = [
            BasicBlock(
                label="entry",
                instructions=[],
                terminator=HIRJump(target_block="next"),
            ),
            BasicBlock(
                label="next",
                instructions=[HIRConst(value=1.0, type=NUMBER, result="r")],
                terminator=HIRReturn(value="r", type=NUMBER),
            ),
        ]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("reachable", blocks))
        assert len(result.blocks) == 2


class TestCopyPropagation:
    def test_assign_propagated(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=5.0, type=NUMBER, result="t0"),
                HIRAssign(target="t1", value="t0"),
                HIRBinaryOp(op="add", left="t1", right="t1", result="t2", type=NUMBER),
            ],
            terminator=HIRReturn(value="t2", type=NUMBER),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("copy_prop", blocks))
        # After copy propagation, t1 uses should be replaced with t0
        # Then constant folding should fold 5.0 + 5.0 = 10.0
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t2" and c.value == 10.0 for c in consts)


class TestDeadInstructionElimination:
    def test_unused_const_removed(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=42.0, type=NUMBER, result="unused"),
                HIRConst(value=1.0, type=NUMBER, result="used"),
            ],
            terminator=HIRReturn(value="used", type=NUMBER),
        )]
        opt = HIROptimizer()
        result = opt.optimize_function(_make_func("die", blocks))
        consts = [i for bb in result.blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert len(consts) == 1
        assert consts[0].result == "used"


class TestModuleOptimization:
    def test_module_level(self):
        blocks = [BasicBlock(
            label="entry",
            instructions=[
                HIRConst(value=10.0, type=NUMBER, result="t0"),
                HIRConst(value=20.0, type=NUMBER, result="t1"),
                HIRBinaryOp(op="add", left="t0", right="t1", result="t2", type=NUMBER),
            ],
            terminator=HIRReturn(value="t2", type=NUMBER),
        )]
        module = _make_module([_make_func("f", blocks)])
        opt = HIROptimizer()
        result = opt.optimize_module(module)
        assert len(result.functions) == 1
        consts = [i for bb in result.functions[0].blocks for i in bb.instructions if isinstance(i, HIRConst)]
        assert any(c.result == "t2" and c.value == 30.0 for c in consts)
