"""
edge_agent/triage.py

LLM incident triage (Claude on Amazon Bedrock), deliberately OFF the
detection path: the transformer + policy decide and act in ~2 ms; this runs
afterwards in a background thread and only writes an analyst-facing summary.
If Bedrock is slow, down, or not permitted, detection and blocking are
unaffected -- the queue just drops work.

Input to the LLM is metadata only: the verdict, confidence, source IP, the
attention-rollout feature importances and the device's last few decisions.
No raw packets or payloads (there are none on this path anyway).

Rate-limited (min_interval seconds between calls) because every call costs
money; incidents arriving faster than that are skipped, not queued forever.

Needs bedrock:InvokeModel on the chosen model/profile. The edge-node IAM
role does NOT have it by default (least privilege) -- grant it only if you
enable TRIAGE=1 on a node, scoped to this one model ARN.
"""
import json
import logging
import queue
import threading
import time

import boto3

logger = logging.getLogger("triage")

DEFAULT_MODEL = "global.anthropic.claude-haiku-5-5"

PROMPT = """You are a SOC analyst assistant. A network-intrusion agent on an edge device made this decision:

{incident}

Its last decisions on this device (oldest first):
{history}

The "attention" field gives the fraction of model attention on each input token (a heuristic, not a causal explanation).
Reply with ONLY a JSON object with keys:
  "summary": one sentence on what likely happened,
  "likely_category": e.g. scan, fuzzing, dos, brute_force, benign_false_positive, unknown,
  "recommended_action": one of keep_block, lift_block, escalate_to_human, monitor,
  "rationale": at most two sentences, citing the evidence above.
Be explicit about uncertainty; do not invent facts not in the input."""


def triage_once(client, model_id, incident, history):
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": PROMPT.format(
            incident=json.dumps(incident, default=str, indent=1),
            history=json.dumps(history, default=str))}]}],
        inferenceConfig={"maxTokens": 300, "temperature": 0.0},
    )
    text = resp["output"]["message"]["content"][0]["text"].strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1]) if start >= 0 else {"summary": text}


def start_triage_worker(sink, region="ap-south-1", model_id=DEFAULT_MODEL, min_interval=10.0):
    """Returns submit(incident, history). sink(dict) receives each triage
    result (e.g. CloudComms.report_incident)."""
    client = boto3.client("bedrock-runtime", region_name=region)
    work = queue.Queue(maxsize=1)
    last = [0.0]

    def worker():
        while True:
            incident, history = work.get()
            try:
                result = triage_once(client, model_id, incident, history)
                sink({**{k: incident.get(k) for k in ("device_id", "source_ip")},
                      "action": "TRIAGE", "triage": result, "of_action": incident.get("action")})
            except Exception as e:  # never let triage take the agent down
                logger.warning("triage failed: %s", e)

    threading.Thread(target=worker, daemon=True).start()

    def submit(incident, history):
        now = time.time()
        if now - last[0] < min_interval:
            return False
        try:
            work.put_nowait((incident, history))
            last[0] = now
            return True
        except queue.Full:
            return False

    return submit
