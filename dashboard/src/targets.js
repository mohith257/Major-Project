// Sandbox attack targets = the nodes' PUBLIC IPs. Not secret — they're on the
// open internet. If an instance ever gets a new public IP (only happens on
// stop/start), update it here and redeploy. Port is whatever the browser hits;
// the agent captures the inbound SYN regardless of whether anything listens.
//
// Port choice matters for the score: the model reads service from the port
// (live_capture.py PORT_SERVICE). 8080 maps to "http", so a single visit looks
// like benign web traffic and scores ~0.60 — below the 0.65 block threshold, so
// the node only ALERTs and nothing is shared as peer intel. An unmapped port
// reads as service "-", the same as the internet bots, and a single bare SYN
// scores high enough to BLOCK → the IP is firewalled and shared to all nodes.
// 4444 is not on the browser's restricted-port list, so window.open still fires.
export const ATTACK_PORT = 4444

export const NODE_TARGETS = [
  { id: 'device1', label: 'device-1', ip: '35.154.172.128' },
  { id: 'device2', label: 'device-2', ip: '3.109.0.101' },
  { id: 'device3', label: 'device-3', ip: '65.1.112.185' },
  { id: 'device4', label: 'device-4', ip: '13.235.241.61' },
]
