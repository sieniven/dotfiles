When this command is invoked, you MUST delegate the task to the `xlayer-devnet` agent using the Agent tool. Do NOT attempt to perform devnet operations yourself — always use the Agent tool with the xlayer-devnet agent.

Pass the user's arguments (if any) as the task prompt to the agent. If no arguments are given, instruct the agent to run the full E2E validation checklist.

For stress testing and load testing, the agent knows to use the adventure scripts at `/Users/nivensie/dev/xlayer/adventure/` — never use polycli directly.
