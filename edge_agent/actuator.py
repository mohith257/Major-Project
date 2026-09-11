"""
edge_agent/actuator.py

The defense side of the agent loop, kept deliberately separate from
detection logic so BLOCK/ALERT decisions in agent.py stay testable without
needing real root/iptables access on a dev machine.
"""
import logging
import platform
import subprocess

logger = logging.getLogger("actuator")


class DefenseActuator:
    def __init__(self, incident_sink=None, simulate=True):
        # simulate=True: log the block, don't touch the real firewall.
        # Only flip to False on Linux boxes where you actually want an
        # iptables rule applied (e.g. the EC2 demo nodes).
        self.simulate = simulate or platform.system() != "Linux"
        self.incident_sink = incident_sink
        self.blocked_ips = set()

    def block(self, source_ip: str):
        if source_ip in self.blocked_ips:
            return
        self.blocked_ips.add(source_ip)
        if self.simulate:
            logger.warning("SIMULATED BLOCK: %s", source_ip)
        else:
            subprocess.run(
                ["iptables", "-A", "INPUT", "-s", source_ip, "-j", "DROP"],
                check=True,
            )
            logger.warning("BLOCKED (iptables): %s", source_ip)

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
