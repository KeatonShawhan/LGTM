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

class FileStructureVisitor(cst.CSTVisitor):
    def __init__(self):
        self.classes: list[str] = []
        self.functions: list[str] = []
        self.imports: list[str] = []

    # ---- Classes ----
    def visit_ClassDef(self, node: cst.ClassDef):
        self.classes.append(node.name.value)

    # ---- Functions (top-level only) ----
    def visit_FunctionDef(self, node: cst.FunctionDef):
        self.functions.append(node.name.value)

    # ---- Imports ----
    def visit_Import(self, node: cst.Import):
        for alias in node.names:
            if alias.asname:
                self.imports.append(
                    f"import {alias.name.value} as {alias.asname.name.value}"
                )
            else:
                self.imports.append(f"import {alias.name.value}")

    def visit_ImportFrom(self, node: cst.ImportFrom):
        module = (
            "." * len(node.relative)
            + node.module.value
            if node.module
            else "." * len(node.relative)
        )

        for alias in node.names:
            if isinstance(alias, cst.ImportStar):
                self.imports.append(f"from {module} import *")
            elif alias.asname:
                self.imports.append(
                    f"from {module} import {alias.name.value} as {alias.asname.name.value}"
                )
            else:
                self.imports.append(f"from {module} import {alias.name.value}")



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

@activity.defn(name="GetFileStructure")
async def get_file_structure(file_path: str | PathLike) -> dict:
    """
    Parse a Python file and return its structural outline.

    Returns:
        {
            "file": filename,
            "classes": [...],
            "functions": [...],
            "imports": [...]
        }
    """
    import os
    assert os.path.isfile(file_path), f"extract function was not provided a valid filepath: {file_path}"

    with open(file_path, 'r') as f:
        try:
            source = "\n".join(f.readlines())
        except UnicodeDecodeError as e:
            print("GET YOUR DAMN EMOJI'S OUT OF MY FILES")
            raise ValueError(f"Failed to read file {file_path} due to encoding error: {e}") from e

    module = cst.parse_module(source)

    visitor = FileStructureVisitor()
    module.visit(visitor)

    return {
        "file": file_path,
        "classes": visitor.classes,
        "functions": visitor.functions,
        "imports": visitor.imports,
    }


if __name__ == "__main__":
    import asyncio

    p = r'C:\Users\fireo\Documents\LGTM\utils\repoManager.py'
    funcs = asyncio.run(extract_function(p, "get_repo_path"))
    if funcs:
        print(funcs[0])
    structure = asyncio.run(get_file_structure(p))
    print(structure)
