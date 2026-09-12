# Product Design

MetaboCausal is built around a product constraint: the evidence must remain inspectable.

The prototype is not designed to make a free-form claim such as "this molecule causes this disease." It is designed to help a team see the evidence boundary:

- what was found
- what was not found
- what source produced the result
- what should be checked next

## User flow

1. A user asks a metabolite-disease question in Slack.
2. The system resolves names and candidate identifiers.
3. The system checks evidence sources.
4. The result is classified into an evidence state.
5. The user gets a compact Slack answer.
6. The user can open a fuller evidence card for review.

## Why Slack

Drug discovery and research decisions are often made in team discussion. Slack lets the evidence appear where a team is already asking questions.

The important part is not Slack itself. The important part is that a short conversational answer remains attached to a reviewable evidence record.

## Model boundary

The language model explains retrieved material. It should not invent numbers, sources or causal support.

The product boundary is:

> Retrieval first. Explanation second.

If the retrieved evidence is missing or weak, the answer should say so.

## Demo boundary

The demos in this public repository are static. They show the intended product behavior and information design. They do not run the private APIs, private search workflow or Slack bot.

