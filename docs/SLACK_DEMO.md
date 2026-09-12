# Slack Demo

The Slack workflow is the intended team-facing interface.

A typical demo has two parts:

1. **Normal evidence question**
   - A user asks about a metabolite-disease pair.
   - MetaboCausal returns a compact answer.
   - The answer points to a fuller evidence card or source-linked record.

2. **Challenge prompt**
   - A user supplies a malformed or unsupported request.
   - The system should reject the request instead of forcing it into an evidence answer.

This repository does not include Slack workspace configuration or bot credentials.

## Demo screenshots

The images below are demo captures from the MetaboCausal Slack workflow.

### Normal source-linked answer

![Slack demo showing a MetaboCausal HDL cholesterol and coronary artery disease question](assets/slack-success-live-1-question.png)

![Slack demo showing State A retrieved MR result](assets/slack-success-live-2-result.png)

![Slack demo showing generated evidence-card attachment](assets/slack-success-live-3-card.png)

![Slack demo showing figure generation buttons and forest plot preview](assets/slack-success-live-4-figure.png)

### Challenge prompt

![Slack demo showing an unreadable pair rejected](assets/slack-challenge-live-unreadable-pair.png)

Suggested caption:

> In this test, the system refused to force an unreadable pair into an evidence answer. This is one challenge test, not proof that hallucination is impossible.
