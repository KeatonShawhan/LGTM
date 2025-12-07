from anthropic import Anthropic
#TODO: add config for query agent

class QueryAgent:
    """Agent for performing calculations and reading data"""
    
    def __init__(self):
        self.client = Anthropic()
    
    def query(self, task: str):
        if not self.client:
            raise RuntimeError("Agent not initialized. Use 'async with' context manager.")
        
        message = self.client.messages.create(
            model = "claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": task}
            ]
        )
        return message.content[0].text
    
    def parse_callstack(self, callstack: str):
        pretext = "Your task is to parse a callstack. Please respond with which exact file is throwing the error, and which line of code the error is being thrown on. Additionally, provide a brief explanation of the error in relation to the available line."
        pretext += "Please also provide your understanding of this error, including common causes and fixes.\n\n"
        return self.query(pretext + callstack)
        
__all__ = ['QueryAgent']

if __name__ == '__main__':
    #test queryAgent
    test_message = "please write hello world in python. Provide no other text, only the code required to execute the task. Do not format it in markdown or anything like that, respond with plaintext code."
    agent = QueryAgent()
    response = agent.query(test_message)
    print(f'test message: {test_message}')
    print(f'response: {response}')
