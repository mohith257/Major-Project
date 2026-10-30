"""
edge_agent/investigator.py

The reasoning half of the agent. The transformer + cost policy settle the
clear cases in ~2 ms (confident benign -> NOOP, confident attack -> BLOCK).
Everything in between -- the band where the cost policy would only ALERT,
which is exactly where Fuzzers-style traffic lands -- is handed to a Claude
investigator that gathers evidence with tools before it acts:

  get_source_profile  rate, port/host fan-out, connection states, score
                      history of one source over the last few minutes
  get_recent_flows    the source's last N flows as the sensor saw them
  get_threat_intel    peer-device blocks + this device's own block history
  decide              terminal: block / alert / allow / escalate, with an
                      attack-type guess and a rationale

A single flow score can't tell a port scan from one odd connection; the
per-source history can, and that's evidence the classifier never sees.

Runs in a background thread so a slow or failed LLM call never stalls
detection: verdicts are queued and the agent applies them on its own thread
(EdgeAgent.run_step drains them), so the actuator is only ever touched from
one thread. If Claude is down, the flow simply stays an ALERT.

Input to the LLM is flow metadata only (sizes, counts, ports, states, model
scores) -- no payloads; live_capture.py never reads them.

Needs bedrock:InvokeModel for the chosen model in the chosen region.
"""
import json
import logging
import queue
import threading
import time

import anthropic
from anthropic import AnthropicBedrockMantle

from edge_agent.flow_history import FlowHistory  # noqa: F401  (re-exported)

logger = logging.getLogger("investigator")

DEFAULT_MODEL = "anthropic.claude-haiku-5-5"

SYSTEM = """You are the investigation module of an autonomous network intrusion detection agent on an edge device.
A transformer classifier scored a flow as uncertain (neither clearly benign nor clearly an attack). Your job is to decide what the device does about the SOURCE of that flow.

Use the tools to gather evidence before deciding: the source's recent behaviour (rate, how many ports/hosts it touched, connection states, how the classifier scored its other flows) and threat intel from peer devices. One or two evidence calls are usually enough; then call decide exactly once.

Guidance:
- Many distinct destination ports or hosts in a short window, mostly rejected/incomplete connections -> scanning/reconnaissance.
- High rate of short flows to one service with repeated similar sizes -> brute force or fuzzing.
- A few normal-looking established connections with moderate scores -> likely benign; allow or alert.
- Block only when the behavioural evidence supports it; a block cuts the host off. Escalate when evidence conflicts.
- The classifier's attention values are a heuristic, not a causal explanation.
Do not invent facts that are not in the tool results."""

TOOLS = [
    {
        "name": "get_source_profile",
        "description": "Aggregate behaviour of one source IP over the recent window: flow count and rate, distinct destination ports/hosts, connection-state mix, services, byte/packet stats, and the classifier's score distribution across its flows.",
        "input_schema": {"type": "object", "properties": {"ip": {"type": "string"}},
                         "required": ["ip"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_recent_flows",
        "description": "The most recent flows (up to n, max 20) from one source IP, oldest first, with ports, protocol, state, sizes and the classifier's P(attack) for each.",
        "input_schema": {"type": "object", "properties": {"ip": {"type": "string"}, "n": {"type": "integer"}},
                         "required": ["ip", "n"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_threat_intel",
        "description": "Whether peer devices in the federation have blocked this IP, and this device's own block history for it.",
        "input_schema": {"type": "object", "properties": {"ip": {"type": "string"}},
                         "required": ["ip"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "decide",
        "description": "Final verdict for this source. Call exactly once, after gathering evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["block", "alert", "allow", "escalate"]},
                "attack_type": {"type": "string", "enum": [
                    "scanning", "brute_force", "fuzzing", "dos", "exploit", "benign", "unknown"]},
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["action", "attack_type", "confidence", "rationale"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


class Investigator:
    """submit() is called from the agent thread; verdicts() drains finished
    investigations back on that same thread."""

    def __init__(self, history, intel_fn, region="ap-south-1", model_id=DEFAULT_MODEL,
                 cooldown_s=30.0, max_turns=6, settle_s=3.0):
        self.settle_s = settle_s
        self.client = AnthropicBedrockMantle(aws_region=region)
        self.model_id = model_id
        self.history = history
        self.intel_fn = intel_fn  # ip -> dict, supplied by the agent
        self.cooldown_s = cooldown_s
        self.max_turns = max_turns
        self.last_case = {}  # ip -> time of last submission
        self.work = queue.Queue(maxsize=4)
        self.done = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, ip, flow, p_attack, attention, now):
        """False if this source was investigated recently or the queue is full."""
        if not ip or now - self.last_case.get(ip, float("-inf")) < self.cooldown_s:
            return False
        try:
            self.work.put_nowait((ip, dict(flow), p_attack, attention, now))
        except queue.Full:
            return False
        self.last_case[ip] = now
        return True

    def verdicts(self):
        out = []
        while not self.done.empty():
            out.append(self.done.get_nowait())
        return out

    def _worker(self):
        while True:
            ip, flow, p_attack, attention, t0 = self.work.get()
            # let the source's behaviour accumulate first: on its first
            # uncertain flow a scan is still one flow, not yet a fan-out
            time.sleep(max(0.0, t0 + self.settle_s - time.time()))
            try:
                verdict = self._investigate(ip, flow, p_attack, attention)
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                logger.warning("investigation of %s failed: %s", ip, e)
                continue
            if verdict:
                verdict["latency_s"] = round(time.time() - t0, 2)
                self.done.put(verdict)

    def _run_tool(self, name, args):
        now = time.time()
        if name == "get_source_profile":
            return self.history.profile(args["ip"], now)
        if name == "get_recent_flows":
            return self.history.recent(args["ip"], args["n"], now)
        if name == "get_threat_intel":
            return self.intel_fn(args["ip"])
        return {"error": f"unknown tool {name}"}

    def _investigate(self, ip, flow, p_attack, attention):
        case = {"source_ip": ip, "classifier_p_attack": round(p_attack, 3),
                "flow": {k: flow.get(k) for k in ("dst_ip", "dst_port", "proto", "service", "state",
                                                  "duration", "src_bytes", "dst_bytes", "src_pkts", "dst_pkts")},
                "attention": attention}
        messages = [{"role": "user", "content": "Uncertain flow to investigate:\n"
                     + json.dumps(case, default=str, indent=1)}]
        trace = []
        for _ in range(self.max_turns):
            resp = self.client.messages.create(
                model=self.model_id, max_tokens=2000, system=SYSTEM, tools=TOOLS,
                output_config={"effort": "low"}, messages=messages,
            )
            if resp.stop_reason == "refusal":
                logger.warning("investigation of %s refused", ip)
                return None
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for c in calls:
                if c.name == "decide":
                    logger.info("INVESTIGATION %s: %s", ip, " -> ".join(trace + ["decide"]))
                    return {"ip": ip, "trace": trace, **c.input}
                trace.append(c.name)
                results.append({"type": "tool_result", "tool_use_id": c.id,
                                "content": json.dumps(self._run_tool(c.name, c.input), default=str)})
            messages.append({"role": "user", "content": results})
        logger.warning("investigation of %s ended without a decision (trace=%s)", ip, trace)
        return None
