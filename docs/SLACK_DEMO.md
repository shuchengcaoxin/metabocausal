# Slack Demo

The Slack workflow is the intended team-facing interface.

A typical demo has two parts:

1. **Normal evidence question**
   - A user asks about a metabolite-disease pair.
   - MetaboCausal returns a compact answer.
   - The answer points to a fuller evidence card or source-linked record.

2. **Challenge prompt**
   - A user supplies a deliberately unsupported premise.
   - The system should reject unsupported evidence instead of inventing support.

The public repository does not include the private Slack workspace or bot credentials. Add only sanitized screenshots here.

## Public-safe screenshots

These images are sanitized static demos, not private live workspace captures.

### Normal source-linked answer

![Sanitized Slack demo showing a source-linked MetaboCausal answer](assets/slack-success-demo.png)

### Challenge prompt

![Sanitized Slack demo showing an unsupported claim rejected](assets/slack-challenge-demo.png)

Suggested public caption:

> In this test, the system rejected an unsupported claim instead of inventing evidence. This is one challenge test, not proof that hallucination is impossible.
