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

