from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, AssistantMessage, TextBlock
from agents.query import QueryAgent

@tool("parseCallstack", "Goes through a callstack to understand the error and common fixes. Is more efficient than trying to parse a callstack itself.", {"callstack": str})
async def parseCallstack(args):
    agent = QueryAgent()
    r = agent.parse_callstack(args['callstack'])
    return {
        "content": [{
            "type": "text",
            "text": f"Response: {r}"
        }]
    }

@tool("makeGitPR", "Recieves a detailed explanation of changes and converts it to a summary for a GitHub PR comment. Is more efficient than trying to make one yourself.", {"callstack": str})
async def gitPRText(args):
    agent = QueryAgent()
    pretext = """    
       You are a formatter for code review summaries.
        Take the raw analysis and format it as a GitHub PR comment with:
    
        Executive summary at the top
        Issues grouped by severity
        Clear markdown formatting
        Code blocks for examples
        Emoji for visual clarity (🔴critical, 🟡medium, etc.)
        Keep it professional but friendly.""",
    r = agent.query(pretext + args['callstack'])
    return {
        "content": [{
            "type": "text",
            "text": f"Response: {r}"
        }]
    }



__all__ = ['parseCallstack']
