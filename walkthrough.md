# FunctionGemma Optimization Walkthrough

We have successfully rebuilt the `generate_hybrid` pipeline to maximize the capabilities of the on-device `functiongemma-270m-it` model while seamlessly falling back to Gemini 2.5 Flash for complex cases.

## The Strategy

The final architecture uses a highly resilient 3-step approach:

1. **Comprehensive Decomposition**: Instead of failing on complex multi-step instructions (which the 270M model cannot handle natively), we use a lightweight NLP regex to split queries like *"Check weather in Paris and set a timer"* into `["Check weather in Paris", "set a timer"]`. This preserves on-device ratio points.
2. **On-Device Execution & Strict Numeric Validation**: We run the on-device model first. Because Gemma-270M struggles with hallucinating numbers, we implemented a **Strict Presence Validator**. If Gemma outputs a number (like `minutes=150`), we verify that the number actually exists in the user's prompt (e.g. `15`). If it hallucinates, we instantly reject it.
3. **Cloud Guarantee (Gemini 2.5 Flash)**: If the on-device model fails confidence or numeric validation, we fall back to Cloud. We fortified Gemini with an aggressive system prompt to prevent it from adding trailing periods to messages or the word "music" to song titles.

---

## Final Benchmark Results

After applying these fixes, the reliability of the system skyrocketed.

### Accuracy Breakdown
| Category | F1 Score | On-Device vs Cloud |
| :--- | :--- | :--- |
| **Easy** | **1.00 (100%)** | 50% On-Device / 50% Cloud |
| **Medium** | **1.00 (100%)** | 30% On-Device / 70% Cloud |
| **Hard** | **0.80 (80%)** | 100% Cloud (via decomposition) |

**Overall Metrics:**
- **Average F1**: 0.93
- **Total Score**: ~58.7% to 60.2%

> [!TIP]
> **Why 60%?** 
> The scoring formula heavily penalizes Cloud usage. Because FunctionGemma 270M fundamentally cannot consistently identify correct arguments without RAG/Cloud help on complex edge cases, the system safely routes to Cloud to guarantee a high F1 (accuracy) multiplier. Attempting to force 100% on-device drops the F1 so severely that the total score falls well below 50%.

---

## How it works (Example)

```python
# Query: "Set a 15 minute timer, play classical music, and remind me to stretch at 4:00 PM."

# 1. Chunking
Chunks = [
  "Set a 15 minute timer",
  "play classical music",
  "remind me to stretch at 4:00 PM."
]

# 2. Sequential Execution
Chunk 1 -> On-Device (Fails numeric validation due to Gemma outputting 150) -> Routes to Cloud
Chunk 2 -> On-Device (Fails tool selection) -> Routes to Cloud
Chunk 3 -> On-Device (Passes!) -> F1=1.00
```

## Running the benchmark

You can verify the final pipeline by running the provided testing script:

```bash
export CACTUS_NO_CLOUD_TELE=1
export PATH="/opt/homebrew/bin:$PATH"
source "cactus/venv/bin/activate"
python benchmark.py
```
