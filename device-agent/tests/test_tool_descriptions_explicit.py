import ast
from pathlib import Path

FILES = [
    Path(__file__).parents[1] / 'mcptoai_agent' / 'tools' / 'host_tools.py',
    Path(__file__).parents[1] / 'mcptoai_agent' / 'google_drive_integration.py',
]

def test_all_fastmcp_tools_have_explicit_descriptions():
    missing=[]
    for path in FILES:
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.attr=='tool':
                    if not any(k.arg=='description' and isinstance(k.value,ast.Constant) and bool(k.value.value) for k in dec.keywords):
                        missing.append(f'{path.name}:{node.name}')
    assert not missing, f'MCP tools missing explicit descriptions: {missing}'
