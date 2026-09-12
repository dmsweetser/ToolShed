// ======================
// UTILITY HELPERS
// ======================

// Format helpers
function formatNumber(num, decimals = 8) {
  if (num === null || num === undefined) return '0';
  return num.toFixed(decimals);
}

function formatETH(value, decimals = 8) {
  if (value === null || value === undefined) return '0.00000000 WETH';
  return formatNumber(value, decimals) + ' WETH';
}

function formatPercent(value, decimals = 2) {
  if (value === null || value === undefined) return '0.00%';
  return value.toFixed(decimals) + '%';
}

// Normalize Ethereum address
function norm(a) {
  return a ? String(a).toLowerCase() : '';
}

// Shorten address for display
function short(a) {
  if (!a) return '';
  return a.substring(0, 6) + '...' + a.substring(a.length - 4);
}

// Sleep function
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Check if token is stablecoin
function isStable(s, address) {
  address = norm(address);
  return s.chain.stables.some(x => norm(x) === address);
}

// Check if token is quote token (WETH for Arbitrum)
function isQuoteToken(s, address) {
  return s.chain.quoteMode === "native" && norm(address) === norm(s.chain.wrappedNative);
}

// Pool price calculation from sqrtPriceX96
function poolPrice(sqrtPriceX96, decimals0, decimals1) {
  const sqrt = Number(sqrtPriceX96);
  if (!Number.isFinite(sqrt) || sqrt <= 0) return null;
  const normalized = sqrt / Math.pow(2, 96);
  const rawPrice = normalized * normalized;
  const decimalAdjustment = Math.pow(10, decimals0 - decimals1);
  const price = rawPrice * decimalAdjustment;
  return Number.isFinite(price) && price > 0 ? price : null;
}

// Calculate time difference in human-readable format
function formatTimeAgo(timestamp) {
  const now = Date.now();
  const diff = now - timestamp;
  
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  
  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return `${seconds}s ago`;
}

// Generate a random ID
function generateId(prefix = 'id') {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

// Safe JSON stringify
function safeStringify(obj) {
  try {
    return JSON.stringify(obj);
  } catch (e) {
    console.error('Error stringifying object:', e);
    return '{}';
  }
}

// Safe JSON parse
function safeParse(json) {
  try {
    return JSON.parse(json);
  } catch (e) {
    console.error('Error parsing JSON:', e);
    return null;
  }
}

// Deep clone object
function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

// Check if object is empty
function isEmpty(obj) {
  return obj == null || Object.keys(obj).length === 0;
}

// Get current timestamp
function getTimestamp() {
  return Date.now();
}

// Get ISO string
function getISOString() {
  return new Date().toISOString();
}

// Calculate percentage change
function calculatePercentChange(oldValue, newValue) {
  if (oldValue === 0) return 0;
  return ((newValue - oldValue) / oldValue) * 100;
}

// Calculate average
function calculateAverage(arr) {
  if (!arr || arr.length === 0) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

// Calculate standard deviation
function calculateStdDev(arr) {
  if (!arr || arr.length < 2) return 0;
  
  const mean = calculateAverage(arr);
  const squaredDiffs = arr.map(x => Math.pow(x - mean, 2));
  const variance = calculateAverage(squaredDiffs);
  return Math.sqrt(variance);
}

// Check if value is within range
function isInRange(value, min, max) {
  return value >= min && value <= max;
}

// Clamp value between min and max
function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

// Linear interpolation
function lerp(start, end, t) {
  return start + (end - start) * t;
}

// Generate a random number in range
function randomInRange(min, max) {
  return Math.random() * (max - min) + min;
}

// Shuffle array (Fisher-Yates algorithm)
function shuffleArray(arr) {
  const array = [...arr];
  for (let i = array.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [array[i], array[j]] = [array[j], array[i]];
  }
  return array;
}

// Get random item from array
function getRandomItem(arr) {
  if (!arr || arr.length === 0) return null;
  return arr[Math.floor(Math.random() * arr.length)];
}

// Check if all elements in array satisfy predicate
function all(arr, predicate) {
  return arr.every(predicate);
}

// Check if any element in array satisfies predicate
function any(arr, predicate) {
  return arr.some(predicate);
}

// Filter array by predicate
function filter(arr, predicate) {
  return arr.filter(predicate);
}

// Find first element in array that satisfies predicate
function find(arr, predicate) {
  return arr.find(predicate);
}

// Map array elements
function map(arr, mapper) {
  return arr.map(mapper);
}

// Reduce array
function reduce(arr, reducer, initialValue) {
  return arr.reduce(reducer, initialValue);
}

// Group array by key
function groupBy(arr, key) {
  return arr.reduce((acc, item) => {
    const groupKey = item[key];
    if (!acc[groupKey]) {
      acc[groupKey] = [];
    }
    acc[groupKey].push(item);
    return acc;
  }, {});
}

// Sort array by key
function sortBy(arr, key, descending = false) {
  return [...arr].sort((a, b) => {
    const aVal = a[key];
    const bVal = b[key];
    if (descending) {
      return bVal > aVal ? 1 : bVal < aVal ? -1 : 0;
    }
    return aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
  });
}

// Debounce function
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Throttle function
function throttle(func, limit) {
  let inThrottle;
  return function(...args) {
    if (!inThrottle) {
      func.apply(this, args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}

// Memoize function
function memoize(func) {
  const cache = new Map();
  return function(...args) {
    const key = JSON.stringify(args);
    if (cache.has(key)) {
      return cache.get(key);
    }
    const result = func.apply(this, args);
    cache.set(key, result);
    return result;
  };
}

// Retry function with exponential backoff
async function retry(func, maxRetries = 3, initialDelay = 1000) {
  let retries = 0;
  let delay = initialDelay;
  
  while (retries < maxRetries) {
    try {
      return await func();
    } catch (error) {
      retries++;
      if (retries >= maxRetries) {
        throw error;
      }
      await sleep(delay);
      delay *= 2; // Exponential backoff
    }
  }
}

// Batch process array in chunks
async function batchProcess(array, processor, chunkSize = 10) {
  const results = [];
  
  for (let i = 0; i < array.length; i += chunkSize) {
    const chunk = array.slice(i, i + chunkSize);
    const chunkResults = await Promise.all(chunk.map(processor));
    results.push(...chunkResults);
  }
  
  return results;
}

// Timeout promise
function timeout(ms) {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error(`Timeout after ${ms}ms`)), ms);
  });
}

// Promise with timeout
async function withTimeout(promise, ms) {
  return Promise.race([promise, timeout(ms)]);
}

// Safe promise all (doesn't fail on first rejection)
async function promiseAllSettled(promises) {
  const results = await Promise.all(
    promises.map(p => p.then(value => ({ status: 'fulfilled', value }))
      .catch(reason => ({ status: 'rejected', reason })))
  );
  
  const fulfilled = results.filter(r => r.status === 'fulfilled').map(r => r.value);
  const rejected = results.filter(r => r.status === 'rejected').map(r => r.reason);
  
  return { fulfilled, rejected };
}

module.exports = {
  formatNumber,
  formatETH,
  formatPercent,
  norm,
  short,
  sleep,
  isStable,
  isQuoteToken,
  poolPrice,
  formatTimeAgo,
  generateId,
  safeStringify,
  safeParse,
  deepClone,
  isEmpty,
  getTimestamp,
  getISOString,
  calculatePercentChange,
  calculateAverage,
  calculateStdDev,
  isInRange,
  clamp,
  lerp,
  randomInRange,
  shuffleArray,
  getRandomItem,
  all,
  any,
  filter,
  find,
  map,
  reduce,
  groupBy,
  sortBy,
  debounce,
  throttle,
  memoize,
  retry,
  batchProcess,
  timeout,
  withTimeout,
  promiseAllSettled
};