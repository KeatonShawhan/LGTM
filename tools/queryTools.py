from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, AssistantMessage, TextBlock
from agents.query import QueryAgent

@tool("parseCallstack", "Goes through a callstack to understand the error and common fixes", {"callstack": str})
async def parseCallstack(args):
    agent = QueryAgent()
    r = agent.parse_callstack(args['callstack'])
    return {
        "content": [{
            "type": "text",
            "text": f"Response: {r}"
        }]
    }

__all__ = ['parseCallstack']
