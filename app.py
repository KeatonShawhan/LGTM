import os
import asyncio
import json
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, AssistantMessage, TextBlock

@tool("add", "Add two numbers", {"a": float, "b": float})
async def add(args):
    return {
        "content": [{
            "type": "text",
            "text": f"Sum: {args['a'] + args['b']}"
        }]
    }

@tool("multiply", "Multiply two numbers", {"a": float, "b": float})
async def multiply(args):
    return {
        "content": [{
            "type": "text",
            "text": f"Product: {args['a'] * args['b']}"
        }]
    }

calculator = create_sdk_mcp_server(
    name="calculator",
    version="2.0.0",
    tools=[add, multiply]
)

# Configure options with MCP server
options = ClaudeAgentOptions(
    model="claude-haiku-4-5-20251001",
    mcp_servers={"calc": calculator},
    allowed_tools=["mcp__calc__add", "mcp__calc__multiply", "Read"]
)

async def main():
    # Create the SDK client
    async with ClaudeSDKClient(options=options) as client:
        with open("logs/log.txt", "a") as f:
            f.write("\n" * 5)
            f.write("=" * 60)
            f.write("\n" * 5)

        # Send a query
        # task = "Use the Read tool and read the number in ./data/sample.txt."
        task = "Go into ./data/sample.txt in my machine, not the agent sandbox, then read the number in the sample.txt file. Then tell me what that number is."
        print(f"Task: {task}\n")
        print("=" * 60)
        
        await client.query(task)
        
        # Receive and print responses
        async for message in client.receive_response():
            print(type(message), '\n')
            if isinstance(message, dict):
                print(json.dumps(message, indent=2))
            elif isinstance(message, str):
                try:
                    # Try to parse and pretty print if it's JSON string
                    parsed = json.loads(message)
                    print(json.dumps(parsed, indent=2))
                except:
                    # Not JSON, just print normally
                    print(message)
            else:
                # For other objects, convert to dict if possible
                try:
                    print(json.dumps(message.__dict__, indent=2, default=str))
                except:
                    print(message)
            if type(message) is ResultMessage:
                print(message.result, message.total_cost_usd)
            if type(message) is AssistantMessage:
                with open("logs/log.txt", "a") as f:
                    for block in message.content:
                        f.write("Content: " + str(block) + "\n")
                    if message.error != None:
                        f.write("Error: " + message.error + "\n")

        print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(main())