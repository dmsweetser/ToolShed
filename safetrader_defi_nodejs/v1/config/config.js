// Configuration constants
const CHAINS = {
  arbitrum: {
    name: "Arbitrum One",
    chainId: 42161,
    rpcs: [
      process.env.RPC_URL_1 || "wss://arbitrum-one-rpc.publicnode.com",
      process.env.RPC_URL_2 || "wss://arb1.arbitrum.io/ws",
      process.env.RPC_URL_3 || "wss://arbitrum-mainnet.public.blastapi.io"
    ],
    factory: process.env.FACTORY_ADDRESS || "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    wrappedNative: process.env.WETH_ADDRESS || "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    quoteMode: "native",
    quoteLabel: "WETH",
    stables: [
      "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", // USDC
      "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"  // USDT
    ]
  }
};

// Token addresses
const NETWORK_TOKENS = {
  arbitrum: {
    WETH: process.env.WETH_ADDRESS || '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
    WBTC: '0x2f2a2543B76A416654947aaB75B4e35b52a17231',
    UNI: '0xfa7F8980b0f1E64A2062791cc3b0871572f1F7f0',
    LINK: '0xf97f4df75117a78c1A5a0DBb814Af92458539FB4',
    ARB: '0x912CE59144196C11c48067255325c5414506085A',
    GMX: '0xfc5A1A6EB076a2C7aD06eD22C5C769A78b3Fa3A1',
    USDC: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    USDT: '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9',
    LEVY: '0x709232b2084659408421a351439f8462d450416f',
    APEX: '0x5063C83912b5A8d352226578e47F845B1a8d5a2F'
  }
};

// ABIs
const ERC20_ABI = [
  "function symbol() view returns (string)",
  "function decimals() view returns (uint8)",
  "function name() view returns (string)",
  "function balanceOf(address) view returns (uint256)",
  "function transfer(address,uint256) returns (bool)",
  "function approve(address,uint256) returns (bool)"
];

const POOL_ABI = [
  "function token0() view returns (address)",
  "function token1() view returns (address)",
  "function fee() view returns (uint24)",
  "function factory() view returns (address)",
  "function liquidity() view returns (uint128)",
  "function slot0() view returns (uint160, int24, uint16, uint16, uint16, uint16, uint16, uint16, bool)"
];

const SWAP_INTERFACE = new (require('ethers')).Interface([
  "event Swap(address indexed sender,address indexed recipient,int256 amount0,int256 amount1,uint160 sqrtPriceX96,uint128 liquidity,int24 tick)"
]);

const SWAP_TOPIC = SWAP_INTERFACE.getEvent("Swap").topicHash;

// Known tokens
const KNOWN_TOKENS = {
  'WETH': { address: null, decimals: 18, symbol: 'WETH', name: 'Wrapped ETH' },
  'ETH': { address: null, decimals: 18, symbol: 'ETH', name: 'Ethereum' },
  'WBTC': { address: null, decimals: 8, symbol: 'WBTC', name: 'Wrapped BTC' },
  'UNI': { address: null, decimals: 18, symbol: 'UNI', name: 'Uniswap' },
  'LINK': { address: null, decimals: 18, symbol: 'LINK', name: 'Chainlink' },
  'ARB': { address: null, decimals: 18, symbol: 'ARB', name: 'Arbitrum' },
  'GMX': { address: null, decimals: 18, symbol: 'GMX', name: 'GMX' },
  'USDC': { address: null, decimals: 6, symbol: 'USDC', name: 'USD Coin' },
  'USDT': { address: null, decimals: 6, symbol: 'USDT', name: 'Tether' },
  'LEVY': { address: null, decimals: 18, symbol: 'LEVY', name: 'Levy' },
  'APEX': { address: null, decimals: 18, symbol: 'APEX', name: 'Apex' }
};

// Pool fees
const POOL_FEES = { LOW: 500, MEDIUM: 3000, HIGH: 10000 };

// Pattern types
const PATTERN_TYPES = {
  REGRESSION: 'regression'
};

// Timeouts
const SWAP_DETECTION_TIMEOUT = 5 * 60 * 1000; // 5 minutes
const BLOCK_PROCESSING_TIMEOUT = 2 * 60 * 1000; // 2 minutes
const MAX_SWAPS_STORAGE = 1000;

// Application version
const APP_VERSION = '11.1.0 (Fixed Connectivity + Enhanced Validation + Full Sell + Persistence + Lock Recovery)';

// Initialize known tokens with addresses
function initializeKnownTokens() {
  const network = NETWORK_TOKENS.arbitrum;
  for (const [symbol, token] of Object.entries(KNOWN_TOKENS)) {
    if (network[symbol]) {
      KNOWN_TOKENS[symbol].address = network[symbol];
    }
  }
}

// Get chain configuration
function getChainConfig(network) {
  return CHAINS[network || 'arbitrum'];
}

module.exports = {
  CHAINS,
  NETWORK_TOKENS,
  ERC20_ABI,
  POOL_ABI,
  SWAP_INTERFACE,
  SWAP_TOPIC,
  KNOWN_TOKENS,
  POOL_FEES,
  PATTERN_TYPES,
  SWAP_DETECTION_TIMEOUT,
  BLOCK_PROCESSING_TIMEOUT,
  MAX_SWAPS_STORAGE,
  APP_VERSION,
  initializeKnownTokens,
  getChainConfig
};