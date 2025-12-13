import os
from agents.query import QueryAgent

def master_compose(starting_dir: os.PathLike, queryAgent: QueryAgent):

    seen = set()

    def recursive_compose(current_dir: os.PathLike):
        pass

def compose_file(file_path: os.PathLike, queryAgent: QueryAgent):
    """
    compose_file translates the raw text of the file into a formatted string which describes the 
    function of the file.
    
    :param file_path: file path for desired file to be composed
        :type file_path: os.PathLike
    :param queryAgent: query agent that will query Claude to parse function headers/code and generate descriptions
        :type queryAgent: QueryAgent
    """
    assert os.path.exists(file_path), f"File path does not exist and failed to compose: {file_path}"
    assert os.path.isfile(file_path), f"Provided directory and *NOT* filepath: {file_path}"

"""
json format

{

path: os.PathLike -> path to the given file
isfile: bool -> True if file, False if directory
subfiles: list[os.PathLike] -> empty if file, contains subfiles (including root directory) if directory
description: str: if file, describes the function/activity of the file (general overview of it's functions and what it performs)
                  if directory, summary will contain an overview of what the sub-listed files do. (TODO: figure this out)
}
functions: list[dict] -> (empty if directory) 
    { each function is described as
        arguments: list[str] -> in format "argument: type"
        return_type: str
        description: str -> through a call to claude, the function is described in 1-3 sentences (brevity strongly preferred)
        line_number: int -> starting line for the function
    }

imports: list[str] -> lists the general imports to the file, empty if directory TODO: list or str?
non_function_code: str -> contains all general code not included in functions TODO: how important is this? should we do more?

The general intent of this is to reduce the token input to the model, and to reduce the amount of comprehension
we rely on the model to do. Less is more? 
"""