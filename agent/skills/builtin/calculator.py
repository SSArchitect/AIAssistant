import ast
import operator
from typing import Any

from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult

# Safe operators for math evaluation
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> Any:
    """Safely evaluate a math expression AST node."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _SAFE_OPS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        return _SAFE_OPS[op_type](_safe_eval(node.operand))
    else:
        raise ValueError(f"Unsupported expression type: {type(node).__name__}")


class CalculatorSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="calculator",
            description="安全计算数学表达式。支持 +、-、*、/、//、%、**。",
            parameters=[
                SkillParameter(
                    name="expression",
                    type="string",
                    description="要计算的数学表达式，例如 42 * 17 + 3。",
                    required=True,
                ),
            ],
            tags=["utility", "math"],
        )

    async def execute(self, **kwargs) -> SkillResult:
        expression = kwargs.get("expression", "")
        if not expression:
            return SkillResult(success=False, error="No expression provided")

        try:
            tree = ast.parse(expression, mode="eval")
            result = _safe_eval(tree)
            return SkillResult(
                success=True,
                data={"expression": expression, "result": result},
                display_text=f"{expression} = {result}",
            )
        except ZeroDivisionError:
            return SkillResult(success=False, error="Division by zero")
        except Exception as e:
            return SkillResult(success=False, error=f"Failed to evaluate: {e}")
