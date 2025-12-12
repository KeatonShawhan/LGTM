from temporalio import activity
from agents.query import QueryAgent
@activity.defn(name="composeDir")
async def compose_directory(directory_path: str, queryAgent: QueryAgent):
    """
    compose_directory is the activity which is used to generate the formatted json-like description of the repo.
    this is used because the other option is to pass entire files into the agentic-claude which likely will
    result in token-limitations and excess costs 
    
    :param directory_path: the path of the root directory (normally repo root)
        :type directory_path: str
    :param queryAgent: query agent that will query Claude to parse function headers/code and generate descriptions
        :type queryAgent: QueryAgent
    """



    import os
    try:
        d = os.listdir(directory_path)
    except OSError as e:
        activity.heartbeat(f"Failed to list directory: {d}, \n \n {e}")
        raise e
    
    from utils.repoComposer import master_compose
    d = os.PathLike(directory_path)
    result = master_compose(d)
    # TODO: save results? or leave in memory?
    # TODO: figure out context-managing for handling token limits in claude calls
