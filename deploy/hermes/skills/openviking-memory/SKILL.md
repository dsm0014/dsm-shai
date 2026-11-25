---
name: openviking-memory
description: "Use the OpenViking memory tools correctly: which four or five tools exist, when to save a memory, how to search with the mode=context rule, and how to check a save."
version: 1.0.0
metadata:
  hermes:
    tags: [memory, openviking, remember, search, recall]
    category: custom
---

# OpenViking memory

OpenViking is the only memory for this agent. Built-in memory is off. The tools are the ones in your tool list: `find`, `read`, `list`, `remember`, and `search` when it is listed. Do not call any other name. If a tool you want is not in your list, say so and do the job another way.

## When to save

Save with `remember` once, at the end of a task, and only for a durable fact or a decision the owner will need later. Examples: a repository decision, a changed setting, an owner preference. Do not save chatter, guesses, or anything you did not verify. A task with nothing durable saves nothing.

Check the `remember` schema before you call it. Pass the fields it requires. The form that has worked is a `messages` list with the fact in it.

After a save, confirm it with `find` using a short marker phrase from the save. If the marker is not found, say the save failed. Do not claim it worked.

## When to search

- `find` answers "what do I know about X" in plain language. Use it first.
- `read` opens one URI you already have.
- `list` shows what is under a URI.
- `search` is for a precise query. It has a conditional parameter, `detail`. **If you set `detail`, also set `mode` to `context`. If you do not set `detail`, do not send `mode`.** Sending `mode` alone, or `detail` without `mode=context`, is the error that made earlier calls fail. Check the schema for the exact field names.

## Errors

- `not a known tool name`: you used a name that is not in your list. Use the tool in your list.
- `401` or connection reset: the OpenViking link is down. Say so. Do not retry in a loop, and do not invent an answer from memory.
- Empty results: say nothing was found. Do not fill the gap from your own knowledge and present it as a memory.
