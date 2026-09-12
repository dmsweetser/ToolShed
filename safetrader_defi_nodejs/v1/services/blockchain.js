const { ethers } = require('ethers');
const {
  CHAINS,
  NETWORK_TOKENS,
  ERC20_ABI,
  POOL_ABI,
  SWAP_INTERFACE,
  SWAP_TOPIC,
  POOL_FEES,
  initializeKnownTokens,
  getChainConfig
} = require('../config/config');

// Initialize known tokens
initializeKnownTokens();

// Global state references
let stateRef;
let configRef;

// Session management
const sessions = new Map();

function initBlockchain(state, config) {
  stateRef = state;
  configRef = config;
  
  return {
    connect,
    disconnect,
    getProvider,
    getSigner,
    getCurrentGasPrice,
    getTokenInfo,
    getPoolInfo,
    processBlock,
    processSwapLog,
    startGasMonitoring,
    startPriceMonitoring,
    updatePricesForSession,
    queueBlock,
    processPending
  };
}

// Create a new session
function createSession(key) {
  const chain = getChainConfig(key);
  return {
    id: ++stateRef.sessionSerial,
    chainKey: key,
    chain: chain,
    provider: null,
    ws: null,
    active: true,
    connected: false,
    blockCount: 0,
    rpcHead: 0,
    lastProcessedBlock: null,
    pendingBlock: null,
    processingBlocks: false,
    reconnectTimer: null,
    reconnectAttempts: 0,
    pools: new Map(),
    tokens: new Map(),
    pairPrices: new Map(),
    metadataInFlight: new Map(),
    swaps: [],
    gasPrice: null,
    gasPriceHistory: [],
    currentRpcIndex: 0,
    blockPollingInterval: null,
    priceUpdateInterval: null,
    heartbeatInterval: null
  };
}

// Connect to blockchain
async function connect() {
  if (!stateRef.isRunning) return;
  
  stateRef.manuallyStopped = false;
  stateRef.sessionSerial++;
  const old = stateRef.activeSession;
  stateRef.activeSession = null;
  
  if (old) await destroySession(old);
  
  const s = createSession(stateRef.currentNetwork);
  stateRef.activeSession = s;
  
  try {
    await connectWithRetry(s);
    if (!s.connected) {
      stateRef.isRunning = false;
      stateRef.manuallyStopped = true;
    }
  } catch (e) {
    s.connected = false;
    stateRef.isRunning = false;
    stateRef.manuallyStopped = true;
    console.error('Session start error:', e);
  }
}

// Disconnect from blockchain
function disconnect() {
  stateRef.manuallyStopped = true;
  stateRef.sessionSerial++;
  const old = stateRef.activeSession;
  stateRef.activeSession = null;
  
  if (old) destroySession(old);
}

// Destroy a session
async function destroySession(s) {
  if (!s) return;
  s.active = false;
  
  if (s.reconnectTimer) {
    clearTimeout(s.reconnectTimer);
    s.reconnectTimer = null;
  }
  
  if (s.priceUpdateInterval) {
    clearInterval(s.priceUpdateInterval);
    s.priceUpdateInterval = null;
  }
  
  if (s.blockPollingInterval) {
    clearInterval(s.blockPollingInterval);
    s.blockPollingInterval = null;
  }
  
  if (s.heartbeatInterval) {
    clearInterval(s.heartbeatInterval);
    s.heartbeatInterval = null;
  }
  
  try { s.provider?.removeAllListeners(); } catch { }
  try { s.ws?.close(); } catch { }
  try { s.provider?.destroy(); } catch { }
  
  s.provider = null;
  s.ws = null;
  s.connected = false;
}

// Connect with retry logic
async function connectWithRetry(s) {
  if (!current(s)) return;
  
  try {
    const chain = getChainConfig(stateRef.currentNetwork);
    const wsRpc = chain.rpcs[s.currentRpcIndex || 0];
    
    console.log(`[WebSocket] Connecting to ${wsRpc}...`);
    
    const provider = new ethers.WebSocketProvider(wsRpc, chain.chainId);
    
    if (!current(s)) {
      try { provider.destroy(); } catch { }
      return;
    }
    
    s.provider = provider;
    s.ws = provider.websocket;
    
    if (s.ws) {
      s.ws.addEventListener("open", () => {
        if (!current(s)) return;
        console.log(`[WebSocket] Connected to ${s.chain.name}`);
        s.connected = true;
        s.reconnectAttempts = 0;
        initializeSessionHandlers(s);
      });
      
      s.ws.addEventListener("close", (e) => {
        if (!current(s)) return;
        console.warn(`[WebSocket] Disconnected: ${e.code} ${e.reason}`);
        s.connected = false;
        // Reconnect immediately if this was an unexpected close
        if (e.code !== 1000) {
          scheduleReconnect(s);
        } else {
          scheduleReconnect(s);
        }
      });
      
      s.ws.addEventListener("error", (e) => {
        if (!current(s)) return;
        console.error(`[WebSocket] Error:`, e);
        s.connected = false;
        scheduleReconnect(s);
      });
    }
    
    const head = await provider.getBlockNumber();
    if (!current(s)) return;
    
    s.rpcHead = head;
    s.blockCount = head;
    
    if (s.chain.quoteMode === "native") {
      await loadToken(s, s.chain.wrappedNative);
    }
    
    startGasMonitoring(s);
    startPriceMonitoring(s);
    
  } catch (e) {
    if (!current(s)) return;
    console.error('[Connection] Failed:', e);
    s.connected = false;
    scheduleReconnect(s);
  }
}

// Check if session is current
function current(s) {
  return !!s && stateRef.activeSession === s && s.id === stateRef.sessionSerial && s.active && !stateRef.manuallyStopped;
}

// Schedule reconnection
function scheduleReconnect(s) {
  if (!current(s) || s.reconnectTimer) return;
  
  s.reconnectAttempts++;
  const maxAttempts = stateRef.maxReconnectAttempts || 10;
  const delay = Math.min(5000 * s.reconnectAttempts, 30000);
  
  if (s.reconnectAttempts > maxAttempts) {
    console.error(`Max reconnection attempts (${maxAttempts}) reached.`);
    stateRef.isRunning = false;
    stateRef.manuallyStopped = true;
    return;
  }
  
  console.log(`[Reconnect] Attempt ${s.reconnectAttempts}/${maxAttempts} in ${delay / 1000}s...`);
  
  s.reconnectTimer = setTimeout(() => {
    s.reconnectTimer = null;
    if (current(s)) {
      // Try next RPC if available
      s.currentRpcIndex = (s.currentRpcIndex + 1) % s.chain.rpcs.length;
      connectWithRetry(s);
    }
  }, delay);
}

// Initialize session handlers
function initializeSessionHandlers(s) {
  if (!current(s)) return;
  
  if (s.provider && s.provider.on) {
    s.provider.on("block", n => {
      if (current(s)) {
        console.log(`[Block] Received block ${n}`);
        queueBlock(s, Number(n));
      }
    });
  }
  
  if (!s.priceUpdateInterval) {
    s.priceUpdateInterval = setInterval(() => {
      if (current(s)) {
        console.log(`[Price Update] Fetching prices...`);
        updatePricesForSession(s);
      }
    }, 10000);
  }
  
  // Heartbeat: Check WebSocket every 10 seconds
  if (!s.heartbeatInterval) {
    s.heartbeatInterval = setInterval(async () => {
      if (!current(s) || !s.connected) return;
      try {
        const blockNumber = await s.provider.getBlockNumber();
        stateRef.lastBlockProcessed = Date.now();
      } catch (e) {
        console.warn('[Heartbeat] WebSocket failed. Reconnecting...');
        s.connected = false;
        scheduleReconnect(s);
      }
    }, 10000);
  }
}

// Start gas monitoring
async function startGasMonitoring(s) {
  if (!s || !s.provider) return;
  await updateGasPriceForSession(s);
  setInterval(async () => {
    if (current(s)) await updateGasPriceForSession(s);
  }, 120000);
}

// Update gas price for session
async function updateGasPriceForSession(s) {
  if (!s || !s.provider) return;
  
  try {
    const feeData = await s.provider.getFeeData();
    s.gasPrice = feeData.gasPrice ? parseInt(feeData.gasPrice) / 1e9 : null;
    stateRef.currentGasPrice = s.gasPrice || stateRef.currentGasPrice;
    
    if (s.gasPrice) {
      s.gasPriceHistory.push({ timestamp: Date.now(), gasPrice: s.gasPrice });
      if (s.gasPriceHistory.length > 100) s.gasPriceHistory.shift();
    }
  } catch (error) {
    console.warn('Failed to update gas price, using cached value:', error);
    stateRef.currentGasPrice = stateRef.currentGasPrice || configRef.MAX_GAS_PRICE;
  }
}

// Get current gas price
function getCurrentGasPrice() {
  return stateRef.currentGasPrice || configRef.MAX_GAS_PRICE;
}

// Start price monitoring
async function startPriceMonitoring(s) {
  if (!current(s) || !s.connected) return;
  await updatePricesForSession(s);
  
  if (s.priceUpdateInterval) {
    clearInterval(s.priceUpdateInterval);
  }
  
  s.priceUpdateInterval = setInterval(async () => {
    if (current(s) && s.connected) {
      await updatePricesForSession(s);
    }
  }, 10000);
}

// Update prices for session
async function updatePricesForSession(s) {
  if (!current(s) || !s.connected) {
    console.warn('Skipping price update: Session not active or connected.');
    return;
  }
  
  try {
    await updateGasPriceForSession(s);
    const tokensToUpdate = Array.from(stateRef.observedTokens);
    
    for (const token of tokensToUpdate) {
      try {
        const tokenMeta = findTokenMeta(s, token);
        if (tokenMeta) {
          const price = quotePrice(s, tokenMeta.address);
          if (price !== null) {
            stateRef.prices[token] = price;
            addPoint(tokenMeta, price);
          }
        }
      } catch (e) {
        console.warn(`Error updating price for ${token}:`, e);
      }
    }
    
    stateRef.lastPriceUpdate = new Date();
  } catch (error) {
    console.error('Error updating prices for session:', error);
  }
}

// Find token metadata
function findTokenMeta(s, symbol) {
  for (const [address, token] of s.tokens) {
    if (token.symbol === symbol) return token;
  }
  return null;
}

// Queue block for processing
async function queueBlock(s, n) {
  if (!current(s)) return;
  if (s.lastProcessedBlock !== null && n <= s.lastProcessedBlock) return;
  s.pendingBlock = Math.max(s.pendingBlock ?? 0, n);
  processPending(s);
}

// Process pending blocks
async function processPending(s) {
  if (s.processingBlocks || !current(s)) return;
  s.processingBlocks = true;
  
  try {
    while (s.pendingBlock !== null && current(s)) {
      const target = s.pendingBlock;
      s.pendingBlock = null;
      
      let head;
      try {
        head = await s.provider.getBlockNumber();
      } catch {
        s.pendingBlock = target;
        await new Promise(resolve => setTimeout(resolve, 1000));
        continue;
      }
      
      if (!current(s)) break;
      s.rpcHead = head;
      s.blockCount = Math.max(s.blockCount, head);
      
      if (target > head) {
        s.pendingBlock = target;
        await new Promise(resolve => setTimeout(resolve, 1000));
        continue;
      }
      
      if (s.lastProcessedBlock !== null && target <= s.lastProcessedBlock) continue;
      await processBlock(s, target);
      
      if (!current(s)) break;
      s.lastProcessedBlock = target;
    }
  } finally {
    s.processingBlocks = false;
  }
}

// Process a block
async function processBlock(s, n) {
  if (!current(s)) return;
  
  try {
    const head = await s.provider.getBlockNumber();
    s.rpcHead = head;
    
    if (n > head) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      return;
    }
    
    let logs = [];
    try {
      const blockRange = { fromBlock: n, toBlock: n, topics: [SWAP_TOPIC] };
      logs = await s.provider.getLogs(blockRange);
    } catch (e) {
      if (e.message && e.message.includes("invalid block range params")) {
        console.info(`Skipping block ${n} due to invalid block range params`);
        return;
      }
      console.warn('Error getting logs:', e);
      return;
    }
    
    if (!logs || !current(s) || !logs.length) {
      stateRef.lastBlockProcessed = Date.now();
      return;
    }
    
    const logBatches = [];
    for (let i = 0; i < logs.length; i += 5) {
      logBatches.push(logs.slice(i, i + 5));
    }
    
    await Promise.all(logBatches.map(async (batch) => {
      await Promise.all(batch.map(async (logEntry) => {
        try {
          await processSwapLog(s, logEntry);
        } catch (e) {
          console.warn('Error processing swap log:', e);
        }
      }));
    }));
    
    stateRef.lastBlockProcessed = Date.now();
  } catch (error) {
    console.error('Error processing block:', error);
  }
}

// Process swap log
async function processSwapLog(s, logEntry) {
  if (!current(s)) return;
  
  try {
    const pool = await loadPool(s, logEntry.address);
    if (!current(s) || !pool?.initialized) return;
    
    let parsed;
    try {
      parsed = SWAP_INTERFACE.parseLog({ topics: logEntry.topics, data: logEntry.data });
    } catch (e) {
      console.warn('Failed to parse log entry:', e);
      return;
    }
    
    if (!parsed) return;
    
    const amount0 = parsed.args.amount0;
    const amount1 = parsed.args.amount1;
    const sqrt = parsed.args.sqrtPriceX96;
    const pair = poolPrice(sqrt, pool.token0Meta.decimals, pool.token1Meta.decimals);
    
    if (pair == null) return;
    
    setPair(s, pool.token0, pool.token1, pair);
    const ts = Date.now();
    const t0 = pool.token0Meta;
    const t1 = pool.token1Meta;
    
    const swapRecord = {
      timestamp: ts,
      tokenIn: t0.symbol || short(t0.address),
      tokenOut: t1.symbol || short(t1.address),
      amountIn: Math.abs(Number(ethers.formatUnits(amount0, t0.decimals))),
      amountOut: Math.abs(Number(ethers.formatUnits(amount1, t1.decimals))),
      pool: short(logEntry.address)
    };
    
    stateRef.lastSwaps.unshift(swapRecord);
    if (stateRef.lastSwaps.length > 1000) {
      stateRef.lastSwaps.pop();
    }
    
    stateRef.lastSwapDetected = ts;
    
    s.swaps.push(ts);
    while (s.swaps.length && s.swaps[0] < ts - 15 * 60 * 1000) s.swaps.shift();
    
    t0.swaps.push(ts);
    t1.swaps.push(ts);
    t0.lastSeen = ts;
    t1.lastSeen = ts;
    
    while (t0.swaps.length && t0.swaps[0] < ts - 15 * 60 * 1000) t0.swaps.shift();
    while (t1.swaps.length && t1.swaps[0] < ts - 15 * 60 * 1000) t1.swaps.shift();
    
    let n0 = 0, n1 = 0;
    try {
      n0 = Math.abs(Number(ethers.formatUnits(amount0, t0.decimals)));
      n1 = Math.abs(Number(ethers.formatUnits(amount1, t1.decimals)));
    } catch (e) { }
    
    const p0 = quotePrice(s, t0.address);
    const p1 = quotePrice(s, t1.address);
    
    if (p0 != null) {
      t0.priceQuote = p0;
      addPoint(t0, p0, ts);
    }
    
    if (p1 != null) {
      t1.priceQuote = p1;
      addPoint(t1, p1, ts);
    }
    
    let volume = null;
    if (p0 != null && p1 != null) {
      volume = (n0 * p0 + n1 * p1) / 2;
    } else if (p0 != null) {
      volume = n0 * p0;
    } else if (p1 != null) {
      volume = n1 * p1;
    }
    
    if (volume != null && Number.isFinite(volume)) {
      t0.volumeQuote += volume;
      t1.volumeQuote += volume;
    }
    
    if (t0.symbol) {
      stateRef.prices[t0.symbol] = p0;
      stateRef.observedTokens.add(t0.symbol);
    }
    
    if (t1.symbol) {
      stateRef.prices[t1.symbol] = p1;
      stateRef.observedTokens.add(t1.symbol);
    }
    
    stateRef.lastPriceUpdate = new Date();
    
    if (t0.symbol && p0 !== null) {
      updatePriceHistory(t0.symbol, p0, ts);
    }
    
    if (t1.symbol && p1 !== null) {
      updatePriceHistory(t1.symbol, p1, ts);
    }
    
  } catch (error) {
    console.error('Error processing swap log:', error);
  }
}

// Get provider
function getProvider() {
  return stateRef.activeSession?.provider || null;
}

// Get signer (for live trading)
function getSigner() {
  if (!process.env.PRIVATE_KEY) return null;
  
  const provider = getProvider();
  if (!provider) return null;
  
  return new ethers.Wallet(process.env.PRIVATE_KEY, provider);
}

// Load token
async function loadToken(s, address) {
  if (!current(s)) return null;
  address = norm(address);
  
  if (s.tokens.has(address)) return s.tokens.get(address);
  
  const key = `token:${address}`;
  if (s.metadataInFlight.has(key)) return s.metadataInFlight.get(key);
  
  const promise = (async () => {
    const t = {
      address,
      symbol: short(address),
      name: short(address),
      decimals: 18,
      swaps: [],
      volumeQuote: 0,
      priceQuote: null,
      history: [],
      lastSeen: 0,
      liquidity: 0,
      feeTier: POOL_FEES.MEDIUM
    };
    
    s.tokens.set(address, t);
    
    try {
      const c = new ethers.Contract(address, ERC20_ABI, s.provider);
      const [symbol, decimals, name] = await Promise.all([
        c.symbol(),
        c.decimals(),
        c.name()
      ]);
      
      if (!current(s)) return null;
      
      t.symbol = String(symbol);
      t.decimals = Number(decimals);
      t.name = String(name);
      stateRef.observedTokens.add(t.symbol);
      
      if (!stateRef.priceHistory[t.symbol]) {
        stateRef.priceHistory[t.symbol] = [];
      }
      
      for (const [pa, pool] of s.pools) {
        if (pool.token0 === address || pool.token1 === address) {
          t.liquidity += 1;
          t.feeTier = pool.fee;
        }
      }
    } catch (e) {
      // Try to find in known tokens
      for (const [symbol, token] of Object.entries(KNOWN_TOKENS)) {
        if (norm(token.address) === norm(address)) {
          t.symbol = symbol;
          t.name = token.name || symbol;
          t.decimals = token.decimals || 18;
          stateRef.observedTokens.add(symbol);
          break;
        }
      }
    } finally {
      s.metadataInFlight.delete(key);
    }
    
    return current(s) ? t : null;
  })();
  
  s.metadataInFlight.set(key, promise);
  return promise;
}

// Load pool
async function loadPool(s, address) {
  if (!current(s)) return null;
  address = norm(address);
  
  if (s.pools.has(address)) return s.pools.get(address);
  
  const key = `pool:${address}`;
  if (s.metadataInFlight.has(key)) return s.metadataInFlight.get(key);
  
  const promise = (async () => {
    const pool = {
      address,
      token0: null,
      token1: null,
      fee: null,
      token0Meta: null,
      token1Meta: null,
      initialized: false,
      liquidity: 0
    };
    
    s.pools.set(address, pool);
    
    try {
      const c = new ethers.Contract(address, POOL_ABI, s.provider);
      const [t0, t1, fee, factory, liquidity] = await Promise.all([
        c.token0(),
        c.token1(),
        c.fee(),
        c.factory(),
        c.liquidity()
      ]);
      
      if (!current(s)) return null;
      if (norm(factory) !== norm(s.chain.factory)) {
        s.pools.delete(address);
        return null;
      }
      
      pool.token0 = norm(t0);
      pool.token1 = norm(t1);
      pool.fee = Number(fee);
      pool.liquidity = parseInt(liquidity);
      
      [pool.token0Meta, pool.token1Meta] = await Promise.all([
        loadToken(s, pool.token0),
        loadToken(s, pool.token1)
      ]);
      
      if (!current(s) || !pool.token0Meta || !pool.token1Meta) return null;
      
      pool.token0Meta.liquidity += pool.liquidity;
      pool.token0Meta.feeTier = pool.fee;
      pool.token1Meta.liquidity += pool.liquidity;
      pool.token1Meta.feeTier = pool.fee;
      
      pool.initialized = true;
      return pool;
    } catch (e) {
      s.pools.delete(address);
      return null;
    } finally {
      s.metadataInFlight.delete(key);
    }
  })();
  
  s.metadataInFlight.set(key, promise);
  return promise;
}

// Get token info
async function getTokenInfo(tokenSymbol) {
  const s = stateRef.activeSession;
  if (!s) return null;
  
  for (const [address, token] of s.tokens) {
    if (token.symbol === tokenSymbol) {
      return {
        address,
        symbol: token.symbol,
        name: token.name,
        decimals: token.decimals
      };
    }
  }
  
  return null;
}

// Get pool info
async function getPoolInfo(token0, token1) {
  const s = stateRef.activeSession;
  if (!s) return null;
  
  for (const [address, pool] of s.pools) {
    if (!pool.initialized) continue;
    
    const t0 = pool.token0Meta?.symbol;
    const t1 = pool.token1Meta?.symbol;
    
    if ((t0 === token0 && t1 === token1) || (t0 === token1 && t1 === token0)) {
      return {
        address,
        token0: t0,
        token1: t1,
        fee: pool.fee,
        liquidity: pool.liquidity
      };
    }
  }
  
  return null;
}

// Set pair price
function setPair(s, a, b, p) {
  if (!Number.isFinite(p) || p <= 0) return;
  a = norm(a);
  b = norm(b);
  
  if (!s.pairPrices.has(a)) s.pairPrices.set(a, new Map());
  if (!s.pairPrices.has(b)) s.pairPrices.set(b, new Map());
  
  const ts = Date.now();
  s.pairPrices.get(a).set(b, { price: p, updatedAt: ts });
  s.pairPrices.get(b).set(a, { price: 1 / p, updatedAt: ts });
}

// Normalize address
function norm(a) { return a ? String(a).toLowerCase() : ''; }

// Shorten address
function short(a) { if (!a) return ''; return a.substring(0, 6) + '...' + a.substring(a.length - 4); }

// Pool price calculation
function poolPrice(sqrtPriceX96, decimals0, decimals1) {
  const sqrt = Number(sqrtPriceX96);
  if (!Number.isFinite(sqrt) || sqrt <= 0) return null;
  const normalized = sqrt / Math.pow(2, 96);
  const rawPrice = normalized * normalized;
  const decimalAdjustment = Math.pow(10, decimals0 - decimals1);
  const price = rawPrice * decimalAdjustment;
  return Number.isFinite(price) && price > 0 ? price : null;
}

// Add price point to token history
function addPoint(t, p, timestamp = null) {
  if (!Number.isFinite(p) || p <= 0) return;
  const ts = timestamp || Date.now();
  t.history.push({ t: ts, price: p });
  const cut = ts - configRef.PRICE_HISTORY_DURATION * 60 * 60 * 1000;
  
  while (t.history.length && t.history[0].t < cut) t.history.shift();
  if (t.history.length > configRef.MAX_PRICE_HISTORY) {
    t.history.splice(0, t.history.length - configRef.MAX_PRICE_HISTORY);
  }
  
  if (t.symbol) updatePriceHistory(t.symbol, p, ts);
}

// Update price history
function updatePriceHistory(token, price, timestamp = null) {
  if (price === null || !Number.isFinite(price)) return;
  if (!stateRef.priceHistory[token]) stateRef.priceHistory[token] = [];
  
  const ts = timestamp || Date.now();
  stateRef.priceHistory[token].push({ price, timestamp: ts });
  
  const maxHistory = configRef.MAX_PRICE_HISTORY;
  if (stateRef.priceHistory[token].length > maxHistory) {
    stateRef.priceHistory[token].shift();
  }
  
  const durationMs = configRef.PRICE_HISTORY_DURATION * 60 * 60 * 1000;
  const cutoff = ts - durationMs;
  
  while (stateRef.priceHistory[token].length && stateRef.priceHistory[token][0].timestamp < cutoff) {
    stateRef.priceHistory[token].shift();
  }
}

// Quote price calculation
function quotePrice(s, address) {
  address = norm(address);
  if (s.chain.quoteMode === "usd" && isStable(s, address)) return 1;
  if (s.chain.quoteMode === "native" && isQuoteToken(s, address)) return 1;
  
  const queue = [{ token: address, value: 1, depth: 0 }];
  const seen = new Set([address]);
  
  while (queue.length) {
    const x = queue.shift();
    if (x.depth >= 4) continue;
    
    const neighbors = s.pairPrices.get(x.token);
    if (!neighbors) continue;
    
    for (const [neighbor, edge] of neighbors) {
      if (!edge || !Number.isFinite(edge.price) || edge.price <= 0) continue;
      const value = x.value * edge.price;
      
      if (s.chain.quoteMode === "usd" && isStable(s, neighbor)) return value;
      if (s.chain.quoteMode === "native" && isQuoteToken(s, neighbor)) return value;
      if (!seen.has(neighbor)) {
        seen.add(neighbor);
        queue.push({ token: neighbor, value, depth: x.depth + 1 });
      }
    }
  }
  return null;
}

// Check if token is stable
function isStable(s, address) {
  address = norm(address);
  return s.chain.stables.some(x => norm(x) === address);
}

// Check if token is quote token
function isQuoteToken(s, address) {
  return s.chain.quoteMode === "native" && norm(address) === norm(s.chain.wrappedNative);
}