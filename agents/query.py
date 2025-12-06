from anthropic import Anthropic
#TODO: add config for query agent

class QueryAent:
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

__all__ = ['QueryAgent']

if __name__ == '__main__':
    #test queryAgent
    test_message = "please write hello world in python. Provide no other text, only the code required to execute the task. Do not format it in markdown or anything like that, respond with plaintext code."
    agent = QueryAent()
    response = agent.query(test_message)
    print(f'test message: {test_message}')
    print(f'response: {response}')
