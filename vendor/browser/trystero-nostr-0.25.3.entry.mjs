// Reviewed MIT-licensed derivative of @trystero-p2p/nostr 0.25.3.
// The local adapter adds bounded last-room socket disposal and relay
// generation-bound acceptance/delivery probes; upstream archives remain exact.
export {
  defaultRelayUrls,
  disposeRelaySockets,
  getRelayHealth,
  getRelaySockets,
  joinRoom,
  pauseRelayReconnection,
  qualifyRelays,
  resumeRelayReconnection,
  selfId
} from './nostr-patched.ts'
