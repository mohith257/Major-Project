// Fallback data shown when the dashboard can't reach the API (no backend
// deployed yet, wrong .env, network down). App.jsx renders a loud
// "DEMO DATA" banner whenever this is in use -- these numbers must never
// be mistaken for a live result. The accuracy trajectory here is loosely
// modeled on the real, validated Fuzzers hold-out result (model/
// validate_holdout.py: 0.213 -> 0.365, see memory.md §4) rather than an
// arbitrary climb to make the shape of a genuine FL run recognizable.
export const MOCK_ROUNDS = [
  { round: 1, completed_at: 1_735_000_000, participants: ['device1', 'device2', 'device3', 'device4'], avg_val_accuracy: 0.58 },
  { round: 2, completed_at: 1_735_000_060, participants: ['device1', 'device2', 'device3'], avg_val_accuracy: 0.64 },
  { round: 3, completed_at: 1_735_000_120, participants: ['device1', 'device2', 'device3', 'device4'], avg_val_accuracy: 0.70 },
  { round: 4, completed_at: 1_735_000_180, participants: ['device1', 'device3', 'device4'], avg_val_accuracy: 0.21 },
  { round: 5, completed_at: 1_735_000_240, participants: ['device1', 'device2', 'device3', 'device4'], avg_val_accuracy: 0.37 },
]

export const MOCK_INCIDENTS = [
  {
    device_id: 'device2', timestamp: 1_735_000_250_000, action: 'BLOCK',
    reason: 'high-confidence malicious flow', confidence: 0.94, source_ip: '10.44.201.7',
    attention: { continuous_features: 0.43, proto: 0.17, service: 0.18, state: 0.22 },
  },
  {
    device_id: 'device3', timestamp: 1_735_000_245_000, action: 'ALERT',
    reason: 'malicious but below block threshold', confidence: 0.71, source_ip: '192.168.30.14',
    attention: { continuous_features: 0.31, proto: 0.09, service: 0.47, state: 0.13 },
  },
  {
    device_id: 'device4', timestamp: 1_735_000_200_000, action: 'RETRAIN',
    reason: 'model wrong on known local labeled data', confidence: null, source_ip: null,
  },
  {
    device_id: 'device1', timestamp: 1_735_000_100_000, action: 'BLOCK',
    reason: 'high-confidence malicious flow', confidence: 0.88, source_ip: '10.12.9.201',
    attention: { continuous_features: 0.52, proto: 0.14, service: 0.12, state: 0.22 },
  },
]
