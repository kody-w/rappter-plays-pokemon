import {schnorr} from '@noble/secp256k1'
import {
  createRelayManager,
  createTopicStrategy,
  fromJson,
  genId,
  getRelays,
  hashWith,
  libName,
  makeSocket,
  pauseRelayReconnection,
  resumeRelayReconnection,
  selfId,
  strToNum,
  toHex,
  toJson,
  type JoinRoom,
  type JoinRoomConfig,
  type SocketClient
} from '@trystero-p2p/core'

const relayManager = createRelayManager<SocketClient>(client => client.socket)
const defaultRedundancy = 5
const tag = 'x'
const eventMsgType = 'EVENT'
const {secretKey, publicKey} = schnorr.keygen()
const pubkey = toHex(publicKey)
const subIdToTopic: Record<string, string> = {}
const msgHandlers: Record<
  string,
  ((topic: string, data: string) => void) | undefined
> = {}
const kindCache: Record<string, number> = {}
const maxTopicsPerSubscription = 250
const localDisposalGraceMs = 150
const maxPublishedEventsPerRelay = 256
const publishedEventTtlMs = 60_000
const qualificationProbeTimeoutMs = 10_000
const qualificationProbeMarker = 'rpp-relay-qualification-v1'

type PublishedEventState = {
  accepted: boolean
  delivered: boolean
  expiresAt: number
}

type QualificationProbe = {
  url: string
  socket: WebSocket
  generation: number
  subId: string
  topic: string
  kind: number
  content: string
  eventId: string
  accepted: boolean
  delivered: boolean
  subscribed: boolean
  settled: boolean
  timer: ReturnType<typeof setTimeout> | null
  promise: Promise<boolean>
  resolve: (qualified: boolean) => void
}

type RelayQualification = {
  accepted: boolean
  delivered: boolean
  qualified: boolean
  qualifying: boolean
  socket: WebSocket | null
  generation: number
  attempted: boolean
  probe: QualificationProbe | null
  publishedIds: Map<string, PublishedEventState>
}

const relayQualification: Record<string, RelayQualification> = {}
const relayClients: Record<string, SocketClient | undefined> = {}
const relayKeys = new WeakMap<SocketClient, string>()
const qualificationRelayUrls = new Set<string>()
let qualificationEnabled = false
let socketQualificationGeneration = 0

const relayKeyFor = (client: SocketClient): string =>
  relayKeys.get(client) ?? client.url

const emptyQualification = (
  socket: WebSocket | null,
  generation = 0,
  attempted = false
): RelayQualification => ({
  accepted: false,
  delivered: false,
  qualified: false,
  qualifying: false,
  socket,
  generation,
  attempted,
  probe: null,
  publishedIds: new Map()
})

const activeQualificationFor = (
  client: SocketClient
): RelayQualification | null => {
  const health = relayQualification[relayKeyFor(client)]

  return (
    health &&
    health.socket === client.socket &&
    client.socket.readyState === 1
  )
    ? health
    : null
}

const prunePublishedEvents = (
  health: RelayQualification,
  timestamp = Date.now()
): void => {
  health.publishedIds.forEach((state, id) => {
    if (state.expiresAt <= timestamp) {
      health.publishedIds.delete(id)
    }
  })
}

const rememberPublishedEvent = (
  client: SocketClient,
  id: string
): void => {
  const health = activeQualificationFor(client)

  if (!health || health.qualified) {
    return
  }

  const timestamp = Date.now()
  prunePublishedEvents(health, timestamp)
  health.publishedIds.delete(id)
  health.publishedIds.set(id, {
    accepted: false,
    delivered: false,
    expiresAt: timestamp + publishedEventTtlMs
  })

  while (health.publishedIds.size > maxPublishedEventsPerRelay) {
    const oldest = health.publishedIds.keys().next().value

    if (typeof oldest !== 'string') {
      break
    }

    health.publishedIds.delete(oldest)
  }
}

const recordPublishedEventResult = (
  client: SocketClient,
  id: string,
  result: 'accepted' | 'delivered' | 'rejected'
): void => {
  const health = activeQualificationFor(client)

  if (!health) {
    return
  }

  prunePublishedEvents(health)
  const published = health.publishedIds.get(id)

  if (!published) {
    return
  }

  if (result === 'rejected') {
    health.publishedIds.delete(id)
    return
  }

  published[result] = true

  if (published.accepted && published.delivered) {
    health.publishedIds.delete(id)
  }
}

const randomHex = (size: number): string => {
  const value = new Uint8Array(size)
  globalThis.crypto.getRandomValues(value)
  return toHex(value)
}

const probeIsCurrent = (probe: QualificationProbe): boolean => {
  const health = relayQualification[probe.url]

  return Boolean(
    !probe.settled &&
    health?.probe === probe &&
    health.socket === probe.socket &&
    health.generation === probe.generation &&
    relayClients[probe.url]?.socket === probe.socket &&
    probe.socket.readyState === 1
  )
}

const settleQualificationProbe = (
  probe: QualificationProbe,
  qualified: boolean
): void => {
  if (probe.settled) {
    return
  }

  const current = probeIsCurrent(probe)
  probe.settled = true

  if (probe.timer !== null) {
    clearTimeout(probe.timer)
    probe.timer = null
  }

  if (probe.subscribed && probe.socket.readyState === 1) {
    try {
      probe.socket.send(toJson(['CLOSE', probe.subId]))
    } catch {
      // A failed relay socket cannot retain a live subscription.
    }
  }

  const health = relayQualification[probe.url]

  if (health?.probe === probe) {
    health.probe = null
    health.qualifying = false
    health.accepted = probe.accepted
    health.delivered = probe.delivered
    health.qualified = Boolean(
      current &&
      qualified &&
      probe.accepted &&
      probe.delivered
    )
    if (health.qualified) {
      health.publishedIds.clear()
    }
  }

  probe.resolve(Boolean(current && qualified))
}

const invalidateSocketQualification = (
  url: string,
  socket: WebSocket,
  generation: number
): void => {
  const health = relayQualification[url]

  if (
    !health ||
    health.socket !== socket ||
    health.generation !== generation
  ) {
    return
  }

  if (health.probe) {
    settleQualificationProbe(health.probe, false)
  }

  relayQualification[url] = emptyQualification(
    socket,
    generation,
    true
  )
}

const startQualificationProbe = (
  client: SocketClient
): Promise<boolean> => {
  const socket = client.socket
  const url = relayKeyFor(client)
  const health = activeQualificationFor(client)

  if (
    !qualificationEnabled ||
    !qualificationRelayUrls.has(url) ||
    !health
  ) {
    return Promise.resolve(false)
  }

  if (health.probe) {
    return health.probe.promise
  }

  if (health.attempted) {
    return Promise.resolve(health.qualified)
  }

  health.attempted = true
  health.qualifying = true

  let resolveProbe: (qualified: boolean) => void = () => {}
  const promise = new Promise<boolean>(resolve => {
    resolveProbe = resolve
  })
  const topic = `${qualificationProbeMarker}:${randomHex(32)}`
  const probe: QualificationProbe = {
    url,
    socket,
    generation: health.generation,
    subId: `${qualificationProbeMarker}:${randomHex(16)}`,
    topic,
    kind: strToNum(topic, 10_000) + 20_000,
    content: `${qualificationProbeMarker}:${randomHex(32)}`,
    eventId: '',
    accepted: false,
    delivered: false,
    subscribed: false,
    settled: false,
    timer: null,
    promise,
    resolve: resolveProbe
  }
  health.probe = probe

  void (async () => {
    try {
      const event = await createEventForKind(
        probe.topic,
        probe.content,
        probe.kind
      )
      const parsed = fromJson<[string, {id?: unknown}]>(event)
      const eventId = parsed[1]?.id

      if (typeof eventId !== 'string' || !probeIsCurrent(probe)) {
        settleQualificationProbe(probe, false)
        return
      }

      probe.eventId = eventId
      probe.timer = setTimeout(
        () => settleQualificationProbe(probe, false),
        qualificationProbeTimeoutMs
      )
      socket.send(
        toJson([
          'REQ',
          probe.subId,
          {
            kinds: [probe.kind],
            authors: [pubkey],
            since: now(),
            ['#' + tag]: [probe.topic]
          }
        ])
      )
      probe.subscribed = true
      socket.send(event)
    } catch {
      settleQualificationProbe(probe, false)
    }
  })()

  return promise
}

const recordQualificationAcceptance = (
  client: SocketClient,
  eventId: string,
  accepted: boolean
): void => {
  const probe = activeQualificationFor(client)?.probe

  if (!probe || !probeIsCurrent(probe) || eventId !== probe.eventId) {
    return
  }

  if (!accepted) {
    settleQualificationProbe(probe, false)
    return
  }

  probe.accepted = true
  const health = relayQualification[probe.url]

  if (health?.probe === probe) {
    health.accepted = true
  }

  if (probe.delivered) {
    settleQualificationProbe(probe, true)
  }
}

type DeliveredEvent = {
  id?: unknown
  content?: unknown
  kind?: unknown
  pubkey?: unknown
  tags?: unknown
}

const recordQualificationDelivery = (
  client: SocketClient,
  subId: string,
  event: DeliveredEvent
): void => {
  const probe = activeQualificationFor(client)?.probe

  if (
    !probe ||
    !probeIsCurrent(probe) ||
    subId !== probe.subId ||
    event.id !== probe.eventId ||
    event.content !== probe.content ||
    event.kind !== probe.kind ||
    event.pubkey !== pubkey ||
    !Array.isArray(event.tags) ||
    event.tags.length !== 1 ||
    !Array.isArray(event.tags[0]) ||
    event.tags[0].length !== 2 ||
    event.tags[0][0] !== tag ||
    event.tags[0][1] !== probe.topic
  ) {
    return
  }

  probe.delivered = true
  const health = relayQualification[probe.url]

  if (health?.probe === probe) {
    health.delivered = true
  }

  if (probe.accepted) {
    settleQualificationProbe(probe, true)
  }
}

const resetQualification = (urls: string[]): void => {
  urls.forEach(url => {
    const health = relayQualification[url]

    if (health?.probe) {
      settleQualificationProbe(health.probe, false)
    }

    relayQualification[url] = emptyQualification(null)
  })
}

type ObservedSocket = WebSocket & {
  __rppQualificationObserved?: boolean
  __rppQualificationGeneration?: number
}

const observeRelaySocket = (client: SocketClient): void => {
  const socket = client.socket as ObservedSocket
  const url = relayKeyFor(client)

  if (socket.__rppQualificationObserved) {
    return
  }

  socket.__rppQualificationObserved = true
  const generation = ++socketQualificationGeneration
  socket.__rppQualificationGeneration = generation
  const previous = relayQualification[url]

  if (previous?.probe) {
    settleQualificationProbe(previous.probe, false)
  }

  relayQualification[url] = emptyQualification(socket, generation)
  const onClose = socket.onclose
  const onError = socket.onerror
  const onMessage = socket.onmessage
  const onOpen = socket.onopen

  socket.onopen = event => {
    onOpen?.call(socket, event)

    if (client.socket === socket) {
      void startQualificationProbe(client)
    }
  }

  socket.onclose = event => {
    invalidateSocketQualification(url, socket, generation)
    onClose?.call(socket, event)
  }
  socket.onerror = event => {
    invalidateSocketQualification(url, socket, generation)
    onError?.call(socket, event)
  }
  socket.onmessage = event => {
    if (client.socket === socket) {
      onMessage?.call(socket, event)
    }
  }
}

export type NostrRoomConfig = JoinRoomConfig

const now = (): number => Math.floor(Date.now() / 1000)

const topicToKind = (topic: string): number =>
  (kindCache[topic] ??= strToNum(topic, 10_000) + 20_000)

const createEventForKind = async (
  topic: string,
  content: string,
  kind: number
): Promise<string> => {
  const payload = {
    kind,
    tags: [[tag, topic]],
    created_at: now(),
    content,
    pubkey
  }

  const id = await hashWith(
    'SHA-256',
    toJson([
      0,
      payload.pubkey,
      payload.created_at,
      payload.kind,
      payload.tags,
      payload.content
    ])
  )

  return toJson([
    eventMsgType,
    {
      ...payload,
      id: toHex(id),
      sig: toHex(await schnorr.signAsync(id, secretKey))
    }
  ])
}

export const createEvent = async (
  topic: string,
  content: string
): Promise<string> => createEventForKind(topic, content, topicToKind(topic))

export const subscribe = (subId: string, topic: string): string => {
  subIdToTopic[subId] = topic

  return toJson([
    'REQ',
    subId,
    {
      kinds: [topicToKind(topic)],
      since: now(),
      ['#' + tag]: [topic]
    }
  ])
}

type TopicHandler = (topic: string, data: string) => void

type TopicRegistration = {
  generation: number
  handler: TopicHandler
}

type BatchState = {
  subIds: string[]
  topics: Map<string, TopicRegistration>
  updateTimer: ReturnType<typeof setTimeout> | null
}

const batchers: Record<string, BatchState> = {}

const batchAdd = (
  client: SocketClient,
  topic: string,
  generation: number,
  handler: TopicHandler
): void => {
  const batcher = (batchers[client.url] ??= {
    subIds: [],
    topics: new Map(),
    updateTimer: null
  })

  batcher.topics.set(topic, {generation, handler})
  scheduleBatchFlush(client, batcher)
}

const batchRemove = (
  client: SocketClient,
  topic: string,
  generation: number,
  handler: TopicHandler
): void => {
  const batcher = batchers[client.url]

  if (!batcher) {
    return
  }

  const registration = batcher.topics.get(topic)

  if (
    !registration ||
    registration.generation !== generation ||
    registration.handler !== handler
  ) {
    return
  }

  batcher.topics.delete(topic)

  if (batcher.topics.size === 0) {
    if (batcher.updateTimer !== null) {
      clearTimeout(batcher.updateTimer)
      batcher.updateTimer = null
    }

    batcher.subIds.forEach(subId => client.send(toJson(['CLOSE', subId])))
    delete batchers[client.url]
  } else {
    scheduleBatchFlush(client, batcher)
  }
}

const scheduleBatchFlush = (
  client: SocketClient,
  batcher: BatchState
): void => {
  if (batcher.updateTimer !== null) {
    return
  }

  batcher.updateTimer = setTimeout(() => {
    batcher.updateTimer = null
    flushBatch(client)
  }, 0)
}

const flushBatch = (client: SocketClient): void => {
  const batcher = batchers[client.url]

  if (!batcher || batcher.topics.size === 0) {
    return
  }

  const topics = [...batcher.topics.keys()]
  const chunks: string[][] = []
  const since = now()

  for (let i = 0; i < topics.length; i += maxTopicsPerSubscription) {
    chunks.push(topics.slice(i, i + maxTopicsPerSubscription))
  }

  while (batcher.subIds.length > chunks.length) {
    const subId = batcher.subIds.pop()

    if (subId) {
      client.send(toJson(['CLOSE', subId]))
    }
  }

  chunks.forEach((chunk, i) => {
    const subId = (batcher.subIds[i] ??= genId(64))

    client.send(
      toJson([
        'REQ',
        subId,
        {
          kinds: [...new Set(chunk.map(topicToKind))],
          since,
          ['#' + tag]: chunk
        }
      ])
    )
  })
}

const resubscribeOnReconnect = (client: SocketClient): void => {
  const batcher = batchers[client.url]

  if (batcher && batcher.topics.size > 0) {
    flushBatch(client)
  }
}

type RelayLease = {
  client: SocketClient
  generation: number
  cancelled: boolean
  ready: Promise<RelayLease>
  cancel: () => void
}

let subscriptionGeneration = 0
let activeSubscriptionGeneration = 0
const leasesByGeneration = new Map<number, Set<RelayLease>>()

const createRelayLease = (
  client: SocketClient,
  generation: number
): RelayLease => {
  let resolveReady: (lease: RelayLease) => void = () => {}
  let settled = false
  const lease = {
    client,
    generation,
    cancelled: false,
    ready: null as unknown as Promise<RelayLease>,
    cancel: () => {}
  }
  const settle = (): void => {
    if (!settled) {
      settled = true
      resolveReady(lease)
    }
  }

  lease.ready = new Promise(resolve => {
    resolveReady = resolve
  })
  lease.cancel = () => {
    lease.cancelled = true
    settle()
  }
  const leases = leasesByGeneration.get(generation) ?? new Set<RelayLease>()
  leases.add(lease)
  leasesByGeneration.set(generation, leases)
  void client.ready.then(settle)
  return lease
}

const cancelSubscriptionGeneration = (generation: number): void => {
  leasesByGeneration.get(generation)?.forEach(lease => lease.cancel())
  leasesByGeneration.delete(generation)
}

const upstreamJoinRoom: JoinRoom<NostrRoomConfig> = createTopicStrategy<
  RelayLease,
  NostrRoomConfig
>({
  init: config =>
    getRelays(config, defaultRelayUrls, defaultRedundancy, true).map(url => {
      const client = relayManager.register(url, () =>
        makeSocket(
          url,
          data => {
            const [msgType, subId, payload, relayMsg] =
              fromJson<
                [
                  string,
                  string,
                  (DeliveredEvent & {content: string}) | boolean,
                  string
                ]
              >(data)

            if (msgType !== eventMsgType) {
              if (msgType === 'OK') {
                recordQualificationAcceptance(
                  client,
                  subId,
                  payload === true
                )
                recordPublishedEventResult(
                  client,
                  subId,
                  payload === true ? 'accepted' : 'rejected'
                )
              }
              const prefix = `${libName}: relay failure from ${client.url} - `

              if (config.relayConfig?.warnOnRelayFailure !== false) {
                if (msgType === 'NOTICE') {
                  console.warn(prefix + subId)
                } else if (msgType === 'OK' && !payload) {
                  console.warn(prefix + relayMsg)
                }
              }

              return
            }

            if (
              payload &&
              typeof payload === 'object' &&
              'content' in payload
            ) {
              recordQualificationDelivery(client, subId, payload)
              if (
                typeof payload.id === 'string' &&
                activeQualificationFor(client)
              ) {
                recordPublishedEventResult(
                  client,
                  payload.id,
                  'delivered'
                )
              }
              const {content} = payload
              const handler = msgHandlers[subId]

              if (handler) {
                handler(subIdToTopic[subId] ?? '', content)
                return
              }

              const batcher = batchers[client.url]

              if (batcher?.subIds.includes(subId) && payload.tags) {
                const topicTag = payload.tags.find(t => t[0] === tag)

                if (topicTag?.[1]) {
                  batcher.topics
                    .get(topicTag[1])
                    ?.handler(topicTag[1], content)
                }
              }
            }
          },
          () => {
            observeRelaySocket(client)
            resubscribeOnReconnect(client)
            void startQualificationProbe(client)
          }
        )
      )

      relayClients[url] = client
      relayKeys.set(client, url)
      observeRelaySocket(client)
      return createRelayLease(client, activeSubscriptionGeneration).ready
    }),

  subscribeTopic: (lease, topic, onMessage) => {
    const {client, generation} = lease
    const handler: TopicHandler = (topic, data) => {
      if (
        !lease.cancelled &&
        generation === activeSubscriptionGeneration
      ) {
        void onMessage(topic, data)
      }
    }

    if (
      lease.cancelled ||
      generation !== activeSubscriptionGeneration
    ) {
      return () => {}
    }

    batchAdd(client, topic, generation, handler)

    return () => {
      batchRemove(client, topic, generation, handler)
    }
  },

  publishTopic: async (lease, topic, msg) => {
    if (
      lease.cancelled ||
      lease.generation !== activeSubscriptionGeneration
    ) {
      return
    }

    const event = await createEvent(
      topic,
      typeof msg === 'string' ? msg : toJson(msg)
    )
    if (
      lease.cancelled ||
      lease.generation !== activeSubscriptionGeneration
    ) {
      return
    }

    const parsed = fromJson<[string, {id?: unknown}]>(event)
    const id = parsed[1]?.id

    if (typeof id === 'string') {
      rememberPublishedEvent(lease.client, id)
    }

    lease.client.send(event)
  }
})

export const getRelaySockets = relayManager.getSockets

export const getRelayHealth = (): Record<
  string,
  {
    accepted: boolean
    delivered: boolean
    qualified: boolean
    qualifying: boolean
    pendingPublicationCount: number
  }
> => {
  const sockets = getRelaySockets()

  return Object.fromEntries(
    Object.entries(relayQualification).map(([url, health]) => {
      const active =
        sockets[url] === health.socket &&
        health.socket?.readyState === 1

      if (active) {
        prunePublishedEvents(health)
      }

      return [
      url,
      {
        accepted: Boolean(active && health.accepted),
        delivered: Boolean(active && health.delivered),
        qualified: Boolean(active && health.qualified),
        qualifying: Boolean(active && health.qualifying),
        pendingPublicationCount: active ? health.publishedIds.size : 0
      }
      ]
    })
  )
}

export const qualifyRelays = async (): Promise<
  Record<string, boolean>
> => {
  if (activeRoomCount === 0) {
    return {}
  }

  qualificationEnabled = true
  const probes: Promise<boolean>[] = []

  qualificationRelayUrls.forEach(url => {
    const client = relayClients[url]

    if (client?.socket.readyState === 1) {
      probes.push(startQualificationProbe(client))
    }
  })

  await Promise.allSettled(probes)
  const health = getRelayHealth()

  return Object.fromEntries(
    [...qualificationRelayUrls].map(url => [
      url,
      health[url]?.qualified === true
    ])
  )
}

export const disposeRelaySockets = (): void => {
  qualificationEnabled = false
  pauseRelayReconnection()
  Object.values(getRelaySockets()).forEach(socket => {
    try {
      const managed = socket as WebSocket & {__rppSuspend?: () => void}

      if (managed.__rppSuspend) {
        managed.__rppSuspend()
      } else {
        managed.close()
      }
    } catch {
      // A closed socket is already inert.
    }
  })
  resetQualification(Object.keys(getRelaySockets()))
  qualificationRelayUrls.clear()
}

const decoratedRooms = new WeakSet<object>()
let activeRoomCount = 0

export const joinRoom: JoinRoom<NostrRoomConfig> = (
  config,
  roomId,
  callbacks
) => {
  const urls = getRelays(config, defaultRelayUrls, defaultRedundancy, true)

  if (activeRoomCount === 0) {
    qualificationEnabled = false
    qualificationRelayUrls.clear()
    urls.forEach(url => qualificationRelayUrls.add(url))
    activeSubscriptionGeneration = ++subscriptionGeneration
    resetQualification(urls)
    resumeRelayReconnection()
    Object.values(getRelaySockets()).forEach(socket => {
      const managed = socket as WebSocket & {__rppResume?: () => void}
      managed.__rppResume?.()
    })
  } else {
    urls.forEach(url => qualificationRelayUrls.add(url))
  }

  const room = upstreamJoinRoom(config, roomId, callbacks)

  if (!decoratedRooms.has(room)) {
    decoratedRooms.add(room)
    activeRoomCount += 1
    const leaveUpstream = room.leave.bind(room)
    const roomSubscriptionGeneration = activeSubscriptionGeneration
    let leavePromise: Promise<void> | null = null

    room.leave = () =>
      (leavePromise ??= (async () => {
        let failure: unknown = null

        if (activeRoomCount === 1) {
          cancelSubscriptionGeneration(roomSubscriptionGeneration)
          disposeRelaySockets()
        }

        try {
          await leaveUpstream()
        } catch (error) {
          failure = error
        } finally {
          await new Promise(resolve => setTimeout(resolve, localDisposalGraceMs))
          activeRoomCount = Math.max(0, activeRoomCount - 1)

          if (activeRoomCount === 0) {
            cancelSubscriptionGeneration(roomSubscriptionGeneration)
            disposeRelaySockets()
          }
        }

        if (failure) {
          throw failure
        }
      })())
  }

  return room
}

export {pauseRelayReconnection, resumeRelayReconnection, selfId}

export const defaultRelayUrls = [
  'basspistol.org',
  'bucket.coracle.social',
  'chorus.almostmachines.dev',
  'chorus.pjv.me',
  'communities.nos.social',
  'ftp.halifax.rwth-aachen.de/nostr',
  'hol.is',
  'hornetstorage.net/relay',
  'koru.bitcointxoko.org',
  'nos.lol',
  'nostr-01.uid.ovh',
  'nostr-01.yakihonne.com',
  'nostr-relay.corb.net',
  'nostr.data.haus',
  'nostr.islandarea.net',
  'nostr.sathoarder.com',
  'nostr.self-determined.de',
  'nostr.tegila.com.br',
  'nostr.vulpem.com',
  'purplerelay.com',
  'relay-can.zombi.cloudrodion.com',
  'relay-rpi.edufeed.org',
  'relay.agorist.space',
  'relay.angor.io',
  'relay.artio.inf.unibe.ch',
  'relay.binaryrobot.com',
  'relay.damus.io',
  'relay.froth.zone',
  'relay.libernet.app',
  'relay.mostr.pub',
  'relay.mostro.network',
  'relay.nostr.place',
  'relay.nostrdice.com',
  'relay.notoshi.win',
  'relay.sigit.io',
  'relay02.lnfi.network',
  'relay2.angor.io',
  'schnorr.me',
  'slick.mjex.me',
  'social.amanah.eblessing.co',
  'staging.yabu.me',
  'strfry.openhoofd.nl',
  'strfry.shock.network',
  'testnet-relay.samt.st',
  'top.testrelay.top',
  'x.kojira.io',
  'yabu.me/v2'
].map(url => 'wss://' + url)

export type * from '@trystero-p2p/core'
