"""
edge_agent/live_capture.py

Bridges REAL traffic on this machine into the canonical flow schema
InferenceModel/SchemaEncoder already expect (data/scripts/partition_data.py:
CANONICAL_CONTINUOUS = [duration, src_bytes, dst_bytes, src_pkts, dst_pkts],
CANONICAL_CATEGORICAL = [proto, service, state]). This is the piece the rest
of the pipeline was missing end-to-end -- EdgeAgent, InferenceModel,
DefenseActuator and CloudComms already accept any object exposing those
fields (run_edge_node.py's traffic_stream() feeds them pandas Series rows
read from a dataset CSV); this module produces the same shape from packets
you actually send across the wire (nmap/hping3/hydra/whatever), so attacking
this machine for real moves the agent instead of nothing happening.

Requires scapy (deliberately NOT in the base requirements.txt -- it pulls in
raw-socket capture, which only a box doing live capture needs; Lambda and
the CSV-only path never import this module). Setup:
  - Linux/EC2: `pip install scapy`, run as root (or grant CAP_NET_RAW).
  - Windows: install Npcap (https://npcap.com, "WinPcap API-compatible
    mode" checked at install), `pip install scapy`, run the terminal as
    Administrator.

Flow definition: packets sharing a (ip_a, ip_b, port_a, port_b, proto)
5-tuple (direction-agnostic -- both legs of one connection hit the same
entry), flushed on TCP RST/FIN or after `flow_timeout` seconds of silence.
That's deliberately simpler than Argus/NFStream -- it's enough to drive the
same canonical schema those tools' CSV output drives, which is the only
property that matters here; reimplementing Argus is not a good use of a
one-day build.

IMPORTANT for a clean demo: whatever interface/filter you pass here will
also see this process's own HTTPS calls to the cloud API (CloudComms) if
you capture on the machine's real NIC without scoping the filter. Either
capture on loopback only (demo attacks against 127.0.0.1) or pass a
CAPTURE_FILTER that excludes your API's host/port. See run_edge_node.py's
env var docs.
"""
import queue
import threading
import time

from scapy.all import ICMP, IP, TCP, UDP, sniff

# Best-effort dst/src-port -> service name. Only needs to cover common demo
# traffic (ssh brute force, http scan, dns recon, rdp/smb) well enough for
# the frozen vocab to recognize it as something other than __unk__ --
# SchemaEncoder._encode_categorical already falls back to __unk__ for any
# value (port or otherwise) this dict doesn't know about, so this never
# needs to be exhaustive.
PORT_SERVICE = {
    20: "ftp-data", 21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp",
    53: "dns", 67: "dhcp", 68: "dhcp", 80: "http", 110: "pop3",
    123: "ntp", 135: "rpc", 139: "netbios-ssn", 143: "imap",
    161: "snmp", 389: "ldap", 443: "ssl", 445: "smb", 3306: "mysql",
    3389: "rdp", 5432: "postgres", 8080: "http",
}

TCP_FIN, TCP_SYN, TCP_RST, TCP_ACK = 0x01, 0x02, 0x04, 0x10


def _service_for(dport, sport):
    return PORT_SERVICE.get(dport) or PORT_SERVICE.get(sport) or "-"


def _proto_name(pkt):
    if pkt.haslayer(TCP):
        return "tcp"
    if pkt.haslayer(UDP):
        return "udp"
    if pkt.haslayer(ICMP):
        return "icmp"
    return "other"


class FlowRecord(dict):
    """dict subclass that also answers attribute access.
    SchemaEncoder.encode_row() does row[c] (dict-style -- works on a plain
    dict or a pandas Series); EdgeAgent.decide() does flow_record.src_ip
    (attribute-style -- only a pandas Series does that for free). A live
    capture record has to satisfy both call sites the same way the CSV-row
    pandas Series already does, without dragging pandas into every packet
    callback."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class _Flow:
    __slots__ = (
        "src_ip", "dst_ip", "sport", "dport", "proto", "start", "last",
        "src_pkts", "dst_pkts", "src_bytes", "dst_bytes",
        "saw_syn", "saw_synack", "saw_rst", "saw_fin",
    )

    def __init__(self, src_ip, dst_ip, sport, dport, proto, now):
        self.src_ip, self.dst_ip = src_ip, dst_ip
        self.sport, self.dport = sport, dport
        self.proto = proto
        self.start = self.last = now
        self.src_pkts = self.dst_pkts = 0
        self.src_bytes = self.dst_bytes = 0
        self.saw_syn = self.saw_synack = self.saw_rst = self.saw_fin = False

    def add(self, from_src: bool, size: int, flags, now: float):
        self.last = now
        if from_src:
            self.src_pkts += 1
            self.src_bytes += size
        else:
            self.dst_pkts += 1
            self.dst_bytes += size
        if flags is not None:
            if flags & TCP_SYN and not (flags & TCP_ACK):
                self.saw_syn = True
            if flags & TCP_SYN and flags & TCP_ACK:
                self.saw_synack = True
            if flags & TCP_RST:
                self.saw_rst = True
            if flags & TCP_FIN:
                self.saw_fin = True

    def _state(self) -> str:
        # Same 3-way bucket partition_data.py's bucket_state() collapses
        # Argus/Zeek states into -- see that module's STATE_BUCKET_MAP.
        if self.saw_rst:
            return "rejected_reset"
        if self.saw_fin or (self.saw_syn and self.saw_synack):
            return "established"
        return "incomplete_other"

    def to_record(self) -> FlowRecord:
        return FlowRecord({
            "duration": max(self.last - self.start, 0.0),
            "src_bytes": self.src_bytes, "dst_bytes": self.dst_bytes,
            "src_pkts": self.src_pkts, "dst_pkts": self.dst_pkts,
            "proto": self.proto,
            "service": _service_for(self.dport, self.sport),
            "state": self._state(),
            "src_ip": self.src_ip, "dst_ip": self.dst_ip,
        })


def sniff_flows(iface=None, flow_timeout: float = 2.0, bpf_filter: str = None):
    """Generator yielding one FlowRecord per closed flow, forever. scapy's
    sniff() runs in a background thread and calls on_packet() inline per
    packet (it doesn't yield); a second sweep thread flushes flows that
    have gone quiet for `flow_timeout` seconds. Both threads push finished
    flows onto a queue this generator blocks on -- so the caller just does
    `for flow in sniff_flows(...): ...` like any other iterator."""
    out_q: "queue.Queue[FlowRecord]" = queue.Queue()
    flows: dict = {}
    lock = threading.Lock()

    def on_packet(pkt):
        if not pkt.haslayer(IP):
            return
        ip = pkt[IP]
        proto = _proto_name(pkt)
        l4 = pkt[TCP] if pkt.haslayer(TCP) else (pkt[UDP] if pkt.haslayer(UDP) else None)
        pa, pb = (l4.sport, l4.dport) if l4 is not None else (0, 0)
        # Canonical, direction-agnostic key so both legs of one connection
        # land in the same flow entry regardless of which side's packet
        # scapy hands us first.
        if (ip.src, pa) <= (ip.dst, pb):
            key = (ip.src, ip.dst, pa, pb, proto)
        else:
            key = (ip.dst, ip.src, pb, pa, proto)
        now = time.time()
        flags = int(l4.flags) if pkt.haslayer(TCP) else None

        with lock:
            flow = flows.get(key)
            if flow is None:
                sport, dport = (pa, pb) if l4 is not None else (0, 0)
                flow = _Flow(ip.src, ip.dst, sport, dport, proto, now)
                flows[key] = flow
            flow.add(from_src=(ip.src == flow.src_ip), size=len(pkt), flags=flags, now=now)
            if flags is not None and (flags & TCP_RST or flags & TCP_FIN):
                out_q.put(flows.pop(key).to_record())

    def sweep():
        while True:
            time.sleep(max(flow_timeout / 2.0, 0.25))
            now = time.time()
            with lock:
                stale = [k for k, f in flows.items() if now - f.last > flow_timeout]
                for k in stale:
                    out_q.put(flows.pop(k).to_record())

    threading.Thread(target=sweep, daemon=True).start()
    threading.Thread(
        target=lambda: sniff(iface=iface, filter=bpf_filter, prn=on_packet, store=False),
        daemon=True,
    ).start()

    while True:
        yield out_q.get()
