// Reviewed MIT-licensed derivative of @trystero-p2p/nostr 0.25.3.
// The local adapter adds bounded last-room socket disposal and relay
// acceptance/delivery qualification; upstream package archives remain exact.
export {
  defaultRelayUrls,
  disposeRelaySockets,
  getRelayHealth,
  getRelaySockets,
  joinRoom,
  pauseRelayReconnection,
  resumeRelayReconnection,
  selfId
} from './nostr-patched.ts'
