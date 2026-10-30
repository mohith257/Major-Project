"""
edge_agent/actuator.py

The defense side of the agent loop, kept deliberately separate from
detection logic so BLOCK/ALERT decisions in agent.py stay testable without
needing real root/iptables access on a dev machine.

Graded response (escalate, expire, roll back) instead of one-shot permanent
blocks: with a ~14-18% false-positive rate on UNSW-NB15, a permanent DROP on
the first high-confidence verdict would cut off a large share of legitimate
hosts for good. Each BLOCK verdict on an IP raises its level:
    level 1 -> temporary block for base_ttl seconds
    level k -> temporary block for base_ttl * 2**(k-1) seconds
    level >= permanent_after -> permanent block
Temporary blocks lift themselves (expire()), and rollback() undoes a block
the analyst marks as a false positive. An IP flagged by ANOTHER device
(shared threat intel, see agent.py) starts one level higher.

All methods take `now` explicitly so the same code runs live (time.time())
and in the replay experiments (simulated clock).
"""
import ipaddress
import logging
import platform
import subprocess

logger = logging.getLogger("actuator")


class DefenseActuator:
    def __init__(self, incident_sink=None, simulate=True, base_ttl=60.0, permanent_after=4):
        # simulate=True: log the block, don't touch the real firewall.
        # Only flip to False on Linux boxes where you actually want an
        # iptables rule applied (e.g. the EC2 demo nodes).
        self.simulate = simulate or platform.system() != "Linux"
        self.incident_sink = incident_sink
        self.base_ttl = base_ttl
        self.permanent_after = permanent_after
        self.level = {}      # ip -> escalation level
        self.blocked = {}    # ip -> expiry time (float("inf") = permanent)

    @property
    def blocked_ips(self):
        return set(self.blocked)

    def is_blocked(self, ip, now):
        return self.blocked.get(ip, float("-inf")) > now

    def block(self, source_ip, now, head_start=0):
        """Escalate source_ip one level and (re)apply the matching block.
        Returns the expiry time, or None if refused."""
        # Live capture on `lo` flags 127.0.0.1 -- a real iptables DROP on it
        # would cut the box off from itself (incl. the agent's own sockets).
        try:
            loopback = ipaddress.ip_address(source_ip).is_loopback
        except ValueError:  # None, "", "-", or anything else that isn't an IP
            loopback = True
        if loopback:
            logger.warning("refusing to block %r (missing or loopback)", source_ip)
            return None
        lvl = max(self.level.get(source_ip, 0) + 1, 1 + head_start)
        self.level[source_ip] = lvl
        expiry = (float("inf") if lvl >= self.permanent_after
                  else now + self.base_ttl * 2 ** (lvl - 1))
        already = source_ip in self.blocked
        self.blocked[source_ip] = expiry
        if not already:
            self._firewall("-A", source_ip)
        logger.warning("BLOCK %s level=%d until=%s", source_ip, lvl,
                       "permanent" if expiry == float("inf") else round(expiry - now))
        return expiry

    def expire(self, now):
        """Lift every temporary block whose TTL has passed. Returns the IPs lifted."""
        lifted = [ip for ip, t in self.blocked.items() if t <= now]
        for ip in lifted:
            self._unblock(ip)
        return lifted

    def rollback(self, source_ip):
        """Analyst marked the block a false positive: lift it and reset the level."""
        self.level.pop(source_ip, None)
        if source_ip in self.blocked:
            self._unblock(source_ip)

    def _unblock(self, ip):
        del self.blocked[ip]
        self._firewall("-D", ip)

    def _firewall(self, op, ip):
        if self.simulate:
            logger.info("SIMULATED iptables %s INPUT -s %s -j DROP", op, ip)
            return
        # A real firewall call must never take down detection: the run loop
        # only catches KeyboardInterrupt, so a missing binary or a permissions
        # error here used to crash the agent (and lose its in-memory state on
        # the systemd restart). Log and carry on instead -- the verdict is
        # still recorded and reported; only the kernel rule didn't apply.
        try:
            subprocess.run(["iptables", op, "INPUT", "-s", ip, "-j", "DROP"],
                           check=True, capture_output=True, text=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            detail = getattr(e, "stderr", "") or ""
            logger.error("firewall %s %s failed (block recorded, rule NOT applied): %s %s",
                         op, ip, type(e).__name__, detail.strip())

    def log_incident(self, device_id, decision, explanation=None):
        entry = {
            "device_id": device_id,
            "action": decision.action.name,
            "reason": decision.reason,
            "confidence": decision.confidence,
            "source_ip": decision.source_ip,
        }
        if explanation:
            # attention-rollout output (model/explain.py, Objective 5) --
            # which input features drove this call, not just the score.
            entry["attention"] = explanation
        logger.info("INCIDENT: %s", entry)
        if self.incident_sink:
            self.incident_sink(entry)  # e.g. POST to the cloud /incidents table
