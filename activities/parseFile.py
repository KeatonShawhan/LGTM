from temporalio import activity
from os import PathLike
import libcst as cst
from libcst.metadata import PositionProvider

class FunctionExtractor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, function_name: str, class_name: str | None = None):
        self.function_name = function_name
        self.class_name = class_name
        self._class_stack = []
        self.positions = []

    def visit_ClassDef(self, node: cst.ClassDef):
        self._class_stack.append(node.name.value)

    def leave_ClassDef(self, node: cst.ClassDef):
        self._class_stack.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef):
        if node.name.value != self.function_name:
            return

        if self.class_name:
            if not self._class_stack or self._class_stack[-1] != self.class_name:
                return

        pos = self.get_metadata(PositionProvider, node)
        self.positions.append(pos)

@activity.defn(name="ExtractFunction")
async def extract_function(
    file_path: PathLike,
    function_name: str,
    class_name: str | None = None,
) -> list[str]:
    """
    Extract raw source code for matching functions.

    Args:
        source_code: Full file source
        function_name: Name of function or method
        class_name: Optional class scope

    Returns:
        List of raw source slices (verbatim)
    """
    import os
    import libcst as cst
    from libcst.metadata import PositionProvider


    assert os.path.isfile(file_path), f"extract function was not provided a valid filepath: {file_path}"
    with open(file_path, 'r') as f:
        try:
            source_code = "\n".join(f.readlines())
        except UnicodeDecodeError as e:
            print("GET YOUR DAMN EMOJI'S OUT OF MY FILES")
            raise ValueError(f"Failed to read file {file_path} due to encoding error: {e}") from e

    module = cst.parse_module(source_code)
    wrapper = cst.MetadataWrapper(module)

    extractor = FunctionExtractor(
        function_name=function_name,
        class_name=class_name,
    )

    wrapper.visit(extractor)

    lines = source_code.splitlines(keepends=True)

    extracted = []
    for pos in extractor.positions:
        start = pos.start.line - 1
        end = pos.end.line
        extracted.append("".join(lines[start:end]))

    return extracted

if __name__ == "__main__":
    import asyncio

    p = r'C:\Users\fireo\Documents\LGTM\utils\repoManager.py'
    funcs = asyncio.run(extract_function(p, "get_repo_path"))
    if funcs:
        print(funcs[0])
