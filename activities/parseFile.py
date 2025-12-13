from temporalio import activity
from os import PathLike

@activity.defn(name="get_code_snippet")
def get_code_snippet(file: PathLike, symbol=None, line=None):
    """
    Docstring for get_code_snippet
    
    :param file: PathLike -> full path to the desired file to get the code snippet from
    :param symbol: str: Name of function or class that needs to be read
    :param line: int: Line number for function/class header
    """
    import os
    try:
        assert os.path.isfile(file)
    except Exception as e:
        message = f"get_code_snippet was either provided a directory or a non-valid filepath {file}"
        activity.heartbeat(message)
        print(message)
        raise e
    
    assert symbol or line, "get_code_snippet must be provided either a symbol or line"
    
    with open(file, 'r') as f:
        lines = f.readlines()
    
    import re

    if symbol:
        cline = 0
        while not re.search('( )*def( )+', lines[cline]) and not re.search(symbol, lines[cline]):
            cline += 1
        line = cline

    nested_funcs = 0
    search_nested = r'( )*def( )+'
    search_return = r'^\s*return\b(?=(?:[^"\'#]|"(?:\\.|[^"])*"|\'(?:\\.|[^\'])*\')*$)'
    assert re.search(search_nested, lines[line]), f"provided line number {line} does not contain a function defition: \n {lines[line]}"
    for l in range(line, len(lines)):
        nested_funcs += 1 if re.search(search_nested, lines[l]) else 0
        nested_funcs -= 1 if re.search(search_return, lines[l]) else 0
        if nested_funcs == 0:
            end_line = l
            break
    return "\n".join(lines[line:end_line+1])