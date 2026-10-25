"""AWS Lambda entry point. Event: {"bucket", "key"} of the match video (or {"video_url"}), optional
"window": [lo, hi] and "out_key". Writes the sheet JSON to s3://bucket/out_key (default <key>.sheet.json)."""
import json
import os

import boto3

from scout_match import run

s3 = boto3.client("s3")


def handler(event, context):
    bucket = event.get("bucket")
    video = event.get("video_url") or s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": event["key"]}, ExpiresIn=6 * 3600)
    res = run(video, window=event.get("window"), log=print)
    out_key = event.get("out_key") or f"{event.get('key', 'match')}.sheet.json"
    if bucket:
        s3.put_object(Bucket=bucket, Key=out_key, Body=json.dumps(res).encode(), ContentType="application/json")
    return {"out_key": out_key, "events": len(res["events"]), "cost_usd": res["cost_usd"], "seconds": res["seconds"]}
