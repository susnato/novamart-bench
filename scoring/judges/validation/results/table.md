| Judge | Prompt | Cohen's kappa | Raw agreement | Cost per verified submission | Model status | Model string |
|---|---|---|---|---|---|---|
| Always "not correct" (floor) | none | 0.000 | 65.4% | $0 | | |
| Gemini 3 Flash Preview (judge v1, the paper's judge) | v1 release prompt | 0.601 | 81.5% | $26.77 | preview | `gemini-3-flash-preview` |
| Gemini 3 Flash Preview | V4 | 0.561 | 78.8% | $26.54 | preview | `gemini-3-flash-preview` |
| Gemini 3.8 Flash | v1 release prompt | 0.461 | 77.3% | $16.14 | GA | `gemini-3.8-flash` |
| Claude Sonnet 5.5 | V4 | 0.509 | 78.5% | $40.20 | GA | `bedrock/global.anthropic.claude-sonnet-5-5` |
| Claude Haiku 5.5 | v1 release prompt | 0.433 | 76.5% | $2.01 | GA | `bedrock/global.anthropic.claude-haiku-5-5` |
| Claude Haiku 5.5 | V5 (hand-written) | 0.614 | 81.5% | $2.64 | GA | `bedrock/global.anthropic.claude-haiku-5-5` |
| **Claude Haiku 5.5, selected (judge v2)** | **V5H6 (reflective rewrite of V5)** | **0.663** | **83.8%** | **$2.72** | **GA** | `bedrock/global.anthropic.claude-haiku-5-5` |
| GPT-6 Luna | V5 | 0.532 | 76.9% | $1.77 | GA | `bedrock/global.openai.gpt-6-luna` |
| GPT-6 Luna | V5RL3 (reflective rewrite of V5) | 0.522 | 77.7% | $2.07 | GA | `bedrock/global.openai.gpt-6-luna` |
| GPT-6.1 Sol | V3 | 0.413 | 75.4% | $8.96 | GA | `bedrock/global.openai.gpt-6.1-sol` |
