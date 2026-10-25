# Updating the site's Lambda to the evolved system

Paste this file to the AI that deployed the site.

## What this folder is

| File | What it is |
|---|---|
| `system.py` | The evolved volleyball system, unchanged from evolution: `analyse(match) -> events`. Its stages are: dead-time filter (Flash), then the Argon clip scout, then merge, then the rule check and re-watch, then the number check and re-read, then a serve-time shift. |
| `tools.py` | The production toolbox. It cuts the video into 30 s clips (8 s overlap) with ffmpeg, uploads them to the Gemini Files API, and reads the team sheet from the video. It also provides `watch`, `watch_range` and `ask`, and meters cost. |
| `scout_match.py` | `run(video, window=None) -> {"events", "team_sheet", "colours", "cost_usd", "calls", "seconds"}`, plus a command-line interface. |
| `lambda_handler.py` | The event is `{"bucket", "key"}` or `{"video_url"}`, with optional `"window": [lo, hi]` and `"out_key"`. It writes the sheet JSON to S3. |
| `Dockerfile`, `requirements.txt` | A Lambda container image (Python 3.12 + static ffmpeg + google-genai + boto3). |

Each event in the output looks like this:

```json
{"t": 1103.4, "type": "serve|receive|set|dig|attack|kill|block", "side": "left|right",
 "team": "<shirt colour read from the video, or white/blue>", "number": "7" | null}
```

`t` is in seconds from the start of the video.

## Steps

1. **Swap the pipeline.** In the existing Lambda, replace the old pipeline call with
   `from scout_match import run; res = run(video_path_or_presigned_url)`. Or deploy this folder
   as-is, as a container Lambda:
   ```
   docker build -t scout .
   docker tag scout <acct>.dkr.ecr.<region>.amazonaws.com/scout:latest
   docker push <acct>.dkr.ecr.<region>.amazonaws.com/scout:latest
   aws lambda update-function-code --function-name <fn> --image-uri <acct>.dkr.ecr.<region>.amazonaws.com/scout:latest
   ```
2. **Set the configuration:**
   - environment variable `GEMINI_API_KEY`, ideally from Secrets Manager;
   - timeout 900 s;
   - memory 10240 MB (this also gives 6 vCPU for ffmpeg);
   - ephemeral storage 10240 MB;
   - an IAM role with `s3:GetObject` on the input and `s3:PutObject` on the output.
3. **Invoke asynchronously** (`InvocationType=Event`). The site then polls for `<key>.sheet.json`.
4. **Map the output to the site's existing event format:**
   - the fields are `t`, `type`, `side`, `team` and `number`;
   - the team names left and right by the shirt colours it reads;
   - the camera must be fixed side-on, with each team on one side for the whole video.

## Limits to know

- **Speed.** Most of the time goes on cutting clips: about 20 CPU-seconds per 30 s clip of 1080p
  input, roughly 9–10 minutes for a full 60-minute match on 6 vCPU. The Gemini calls add
  about 3–5 minutes.
  - **A full match is close to Lambda's 15-minute limit.** Either pass `"window"` to process a
    set at a time, or run the same image on Fargate or AWS Batch, which has no time limit.
  - **For speed,** use Step Functions: one invocation per clip for cutting, uploading and
    scouting, then a final step for the stages after merge.
- **Cost.** Gemini costs about $15 per full match; AWS adds cents.
- **Tested.** On 2 minutes of the match (1100–1220 s) the human scout logged 24 touches. The
  system found 22 of them with the right action and team, invented 0, and got 14 numbers right.
  That cost $1.18. On a window that short the team sheet is weak (few clips to read from); on a
  full match it reads 12 clips spread over the match.
- **Held-out accuracy** (part of the match never used in development):
  - overall 0.84;
  - touches found within 1 s: 0.905;
  - right action and team: 0.884;
  - right shirt number: 0.695.
