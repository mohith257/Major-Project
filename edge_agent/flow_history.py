"""
edge_agent/flow_history.py

Per-source sliding window of scored flows -- the agent's short-term memory.
Shared by the bandit (edge_agent/bandit.py, as context features) and the
investigator (edge_agent/investigator.py, as tool results).
"""
import threading
from collections import Counter, defaultdict, deque


class FlowHistory:
    """Per-source sliding window of scored flows. Written by the agent
    thread, read by the investigator thread -- hence the lock."""

    def __init__(self, window_s=180.0, max_per_src=500):
        self.window_s = window_s
        self.flows = defaultdict(lambda: deque(maxlen=max_per_src))
        self.lock = threading.Lock()

    def add(self, rec, p_attack, action, now):
        ip = rec.get("src_ip")
        if not ip:
            return
        with self.lock:
            self.flows[ip].append({
                "t": now, "dst_ip": rec.get("dst_ip"), "dst_port": rec.get("dst_port"),
                "proto": rec.get("proto"), "service": rec.get("service"), "state": rec.get("state"),
                "duration": round(float(rec.get("duration", 0)), 3),
                "src_bytes": int(rec.get("src_bytes", 0)), "dst_bytes": int(rec.get("dst_bytes", 0)),
                "src_pkts": int(rec.get("src_pkts", 0)), "dst_pkts": int(rec.get("dst_pkts", 0)),
                "p_attack": round(p_attack, 3), "agent_action": action,
            })

    def window(self, ip, now):
        with self.lock:
            return [f for f in self.flows.get(ip, ()) if now - f["t"] <= self.window_s]

    def profile(self, ip, now):
        fl = self.window(ip, now)
        if not fl:
            return {"ip": ip, "flows": 0}
        span = max(now - fl[0]["t"], 1.0)
        ps = sorted(f["p_attack"] for f in fl)
        return {
            "ip": ip, "window_seconds": round(span, 1), "flows": len(fl),
            "flows_per_second": round(len(fl) / span, 2),
            "distinct_dst_ports": len({f["dst_port"] for f in fl}),
            "distinct_dst_hosts": len({f["dst_ip"] for f in fl}),
            "top_dst_ports": Counter(f["dst_port"] for f in fl).most_common(5),
            "states": dict(Counter(f["state"] for f in fl)),
            "services": dict(Counter(f["service"] for f in fl).most_common(5)),
            "protocols": dict(Counter(f["proto"] for f in fl)),
            "median_src_bytes": sorted(f["src_bytes"] for f in fl)[len(fl) // 2],
            "median_src_pkts": sorted(f["src_pkts"] for f in fl)[len(fl) // 2],
            "p_attack_median": ps[len(ps) // 2], "p_attack_max": ps[-1],
            "flows_scored_above_0.5": sum(p > 0.5 for p in ps),
            "agent_actions_so_far": dict(Counter(f["agent_action"] for f in fl)),
        }

    def recent(self, ip, n, now):
        fl = self.window(ip, now)[-max(1, min(n, 20)):]
        return [{**f, "t": round(f["t"] - now, 1)} for f in fl]  # t = seconds ago (negative)
