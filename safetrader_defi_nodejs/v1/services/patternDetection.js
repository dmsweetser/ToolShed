const { PATTERN_TYPES } = require('../config/config');

// Global state and config references
let stateRef;
let configRef;
let blockchainRef;

function initPatternDetection(state, config, blockchain) {
    stateRef = state;
    configRef = config;
    blockchainRef = blockchain;

    return {
        detectPatternsForToken,
        detectAllPatterns,
        startPatternDetection,
        stopPatternDetection,
        validatePrediction,
        getPatternKey,
        getPatternDescription,
        isPatternValid,
        validatePatternsMinimal,
        updatePatternStats
    };
}

// Smoothing function
function smoothData(history, windowSize = 3) {
    if (history.length <= windowSize) return history;
    const smoothed = [];
    for (let i = 0; i < history.length; i++) {
        const start = Math.max(0, i - Math.floor(windowSize / 2));
        const end = Math.min(history.length, i + Math.ceil(windowSize / 2));
        const window = history.slice(start, end);
        const avgPrice = window.reduce((sum, p) => sum + p.price, 0) / window.length;
        smoothed.push({ timestamp: history[i].timestamp, price: avgPrice });
    }
    return smoothed;
}

// Polynomial regression
function polynomialRegression(x, y, degree) {
    const n = x.length;
    if (n !== y.length || n <= degree) {
        return { coefficients: [], predict: () => 0 };
    }

    // Create the design matrix
    const X = [];
    for (let i = 0; i < n; i++) {
        const row = [];
        for (let j = 0; j <= degree; j++) {
            row.push(Math.pow(x[i], j));
        }
        X.push(row);
    }

    // Transpose X
    const XT = [];
    for (let j = 0; j <= degree; j++) {
        XT.push([]);
        for (let i = 0; i < n; i++) {
            XT[j].push(X[i][j]);
        }
    }

    // Multiply XT and X
    const XTX = [];
    for (let i = 0; i <= degree; i++) {
        XTX.push([]);
        for (let j = 0; j <= degree; j++) {
            let sum = 0;
            for (let k = 0; k < n; k++) {
                sum += XT[i][k] * X[k][j];
            }
            XTX[i].push(sum);
        }
    }

    // Multiply XT and y
    const XTy = [];
    for (let i = 0; i <= degree; i++) {
        let sum = 0;
        for (let k = 0; k < n; k++) {
            sum += XT[i][k] * y[k];
        }
        XTy.push(sum);
    }

    // Solve XTX * coefficients = XTy using Gaussian elimination
    const coefficients = gaussianElimination(XTX, XTy);

    return {
        coefficients,
        predict: (xVal) => {
            let yVal = 0;
            for (let i = 0; i <= degree; i++) {
                yVal += coefficients[i] * Math.pow(xVal, i);
            }
            return yVal;
        }
    };
}

// Gaussian elimination
function gaussianElimination(A, b) {
    const n = A.length;
    for (let i = 0; i < n; i++) {
        // Partial pivoting
        let maxRow = i;
        for (let k = i + 1; k < n; k++) {
            if (Math.abs(A[k][i]) > Math.abs(A[maxRow][i])) {
                maxRow = k;
            }
        }

        // Swap rows
        [A[i], A[maxRow]] = [A[maxRow], A[i]];
        [b[i], b[maxRow]] = [b[maxRow], b[i]];

        // Eliminate
        for (let k = i + 1; k < n; k++) {
            const factor = A[k][i] / A[i][i];
            for (let j = i; j < n; j++) {
                A[k][j] -= factor * A[i][j];
            }
            b[k] -= factor * b[i];
        }
    }

    // Back substitution
    const x = new Array(n);
    for (let i = n - 1; i >= 0; i--) {
        x[i] = b[i];
        for (let j = i + 1; j < n; j++) {
            x[i] -= A[i][j] * x[j];
        }
        x[i] /= A[i][i];
    }

    return x;
}

// Detect patterns for a single token
function detectPatternsForToken(history, token) {
    if (!history || history.length < 5) {
        console.warn(`[Cubic] Not enough history for ${token}. Length: ${history.length}`);
        return [];
    }

    const smoothedHistory = smoothData(history, 3);
    const windowSize = configRef.WINDOW_SIZE * 1000;
    const marginOfError = configRef.MARGIN_OF_ERROR / 100;
    const patterns = [];

    const windows = [];
    let currentWindow = [];
    let windowStartTime = smoothedHistory[0].timestamp;

    for (const point of smoothedHistory) {
        if (point.timestamp - windowStartTime > windowSize) {
            if (currentWindow.length > 0) windows.push(currentWindow);
            currentWindow = [point];
            windowStartTime = point.timestamp;
        } else {
            currentWindow.push(point);
        }
    }
    if (currentWindow.length > 0) windows.push(currentWindow);

    if (windows.length < 2) {
        console.warn(`[Cubic] Not enough windows for ${token}. Need at least 2.`);
        return [];
    }

    const windowAverages = windows.map(window => ({
        avg: window.map(p => p.price).reduce((a, b) => a + b, 0) / window.length,
        timestamp: window[window.length - 1].timestamp
    }));

    const xValues = windowAverages.map((_, i) => i);
    const yValues = windowAverages.map(w => w.avg);
    const regression = polynomialRegression(xValues, yValues, 3);
    const nextX = xValues.length;
    let predictedY = regression.predict(nextX);
    const currentPrice = smoothedHistory[smoothedHistory.length - 1].price;

    const maxDeviation = 0.5;
    const maxPredicted = currentPrice * (1 + maxDeviation);
    const minPredicted = currentPrice * (1 - maxDeviation);
    predictedY = Math.min(Math.max(predictedY, minPredicted), maxPredicted);

    const errorMargin = predictedY * marginOfError;
    const lowerBound = predictedY - errorMargin;
    const upperBound = predictedY + errorMargin;

    const predictedProfitPercent = ((predictedY - currentPrice) / currentPrice) * 100;
    const minProfitThreshold = configRef.MIN_PROFIT_PERCENT;

    if (currentPrice >= lowerBound &&
        currentPrice <= upperBound &&
        predictedY > currentPrice &&
        predictedProfitPercent >= minProfitThreshold) {

        patterns.push({
            type: PATTERN_TYPES.REGRESSION,
            token,
            predictedPrice: predictedY,
            currentPrice,
            slope: regression.coefficients[1],
            intercept: regression.coefficients[0],
            quadraticTerm: regression.coefficients[2],
            cubicTerm: regression.coefficients[3],
            windowSize: windowSize / 1000,
            marginOfError: marginOfError * 100,
            regressionDegree: 3,
            timestamp: Date.now(),
            predictedProfitPercent
        });
    }

    return patterns;
}

// Get pattern key
function getPatternKey(pattern) {
    if (pattern.type === PATTERN_TYPES.REGRESSION) {
        return `CUBIC_${Math.round(pattern.predictedPrice * 10000) / 10000}_${Math.round(pattern.cubicTerm * 100) / 100}`;
    }
    return 'UNKNOWN';
}

// Get pattern description
function getPatternDescription(pattern) {
    if (pattern.type === PATTERN_TYPES.REGRESSION) {
        return `Cubic: Predicted ${pattern.predictedPrice.toFixed(8)} WETH (${pattern.predictedProfitPercent.toFixed(2)}% profit)`;
    }
    return 'Manual';
}

// Check if pattern is valid
function isPatternValid(pattern) {
    if (pattern.type === PATTERN_TYPES.REGRESSION) {
        return pattern.predictedProfitPercent >= configRef.MIN_PROFIT_PERCENT;
    }
    return false;
}

// Validate patterns
function validatePatternsMinimal(patterns) {
    patterns.forEach((pattern, key) => {
        if (!isPatternValid(pattern)) {
            patterns.delete(key);
        }
    });
}

// Update pattern statistics
function updatePatternStats() {
    const patternsArray = Array.from(stateRef.activePatterns.values());
    stateRef.patternStats.totalPatterns = patternsArray.length;
    stateRef.patternStats.tokensWithPatterns = new Set(patternsArray.map(p => p.token)).size;
}

// Validate prediction
async function validatePrediction(token, pattern, currentPrice) {
    const validationKey = `${token}_${pattern.predictedPrice.toFixed(8)}`;
    const existingValidation = stateRef.predictionValidation.get(validationKey);

    if (existingValidation) {
        return existingValidation.validated;
    }

    if (!stateRef.pendingValidations.has(validationKey)) {
        stateRef.pendingValidations.set(validationKey, {
            count: 0,
            successes: 0,
            lastCheck: 0,
            pattern: pattern
        });
    }

    const validation = stateRef.pendingValidations.get(validationKey);
    validation.count++;

    const now = Date.now();
    if (now - validation.lastCheck < 1000) {
        return false;
    }
    validation.lastCheck = now;

    const priceHistory = stateRef.priceHistory[token];
    if (!priceHistory || priceHistory.length < 3) {
        return false;
    }

    const recentPrices = priceHistory.slice(-5).map(p => p.price);
    const recentTimestamps = priceHistory.slice(-5).map(p => p.timestamp);

    let totalChange = 0;
    for (let i = 1; i < recentPrices.length; i++) {
        const timeDiff = (recentTimestamps[i] - recentTimestamps[i - 1]) / 1000;
        if (timeDiff > 0) {
            const priceDiff = recentPrices[i] - recentPrices[i - 1];
            totalChange += priceDiff / timeDiff;
        }
    }
    const avgChangeRate = totalChange / (recentPrices.length - 1);
    const predictedNextPrice = currentPrice + (avgChangeRate * 1);
    const directionCorrect = (predictedNextPrice > currentPrice) === (pattern.predictedPrice > currentPrice);

    if (directionCorrect) {
        validation.successes++;
    }

    if (validation.count >= configRef.PREDICTION_VALIDATION_COUNT) {
        const accuracy = (validation.successes / validation.count) * 100;
        const isValid = accuracy >= configRef.MIN_PREDICTION_ACCURACY;
        stateRef.predictionValidation.set(validationKey, { validated: isValid, accuracy });
        stateRef.pendingValidations.delete(validationKey);
        return isValid;
    }

    return false;
}

// Detect all patterns
async function detectAllPatterns() {
    if (stateRef.isDetectingPatterns) return;
    stateRef.isDetectingPatterns = true;

    try {
        const tokens = Array.from(stateRef.observedTokens);
        const newActivePatterns = new Map();

        for (const token of tokens) {
            const history = stateRef.priceHistory[token];
            if (!history || history.length < 5) continue;

            const patterns = detectPatternsForToken(history, token);
            patterns.forEach(pattern => {
                if (!isPatternValid(pattern)) return;

                const patternKey = getPatternKey(pattern);
                const existingPatternKey = `${token}_${patternKey}`;

                if (!newActivePatterns.has(existingPatternKey)) {
                    newActivePatterns.set(existingPatternKey, {
                        ...pattern,
                        token,
                        occurrences: 1,
                        firstSeen: pattern.timestamp,
                        lastSeen: pattern.timestamp
                    });
                } else {
                    const existing = newActivePatterns.get(existingPatternKey);
                    existing.occurrences++;
                    existing.lastSeen = Math.max(existing.lastSeen, pattern.timestamp);
                }
            });
        }

        validatePatternsMinimal(newActivePatterns);
        stateRef.activePatterns = newActivePatterns;
        updatePatternStats();

        stateRef.lastDetectionTime = new Date();

        // Validate predictions for new patterns
        for (const [key, pattern] of stateRef.activePatterns) {
            if (!stateRef.predictionValidation.has(`${pattern.token}_${pattern.predictedPrice.toFixed(8)}`)) {
                validatePrediction(pattern.token, pattern, stateRef.prices[pattern.token]);
            }
        }

        // Check patterns for trading opportunities
        for (const token of tokens) {
            await checkPatternsForToken(token);
        }
    } catch (e) {
        console.error('Error in detectAllPatterns:', e);
    } finally {
        stateRef.isDetectingPatterns = false;
    }
}

// Check patterns for a token
async function checkPatternsForToken(token) {
    try {
        if (!stateRef.isRunning) return;
        const history = stateRef.priceHistory[token];
        if (!history || history.length < 5) return;
        const currentPrice = stateRef.prices[token];
        if (!currentPrice) return;

        const openPosition = stateRef.portfolio.positions.find(p => p.token === token && p.status === 'open');
        if (openPosition) {
            return;
        }

        const tokenPatterns = Array.from(stateRef.activePatterns.values()).filter(p => p.token === token);
        for (const pattern of tokenPatterns) {
            if (stateRef.openBuyOrders.has(token)) break;
            const existingPosition = stateRef.portfolio.positions.find(p => p.token === token && p.status === 'open');
            if (existingPosition) break;

            const validationKey = `${token}_${pattern.predictedPrice.toFixed(8)}`;
            const validationData = stateRef.predictionValidation.get(validationKey);

            if (!validationData || !validationData.validated) {
                console.log(`Prediction not yet validated for ${token}, skipping trade`);
                continue;
            }

            // Trigger trade execution (handled by tradeExecution service)
            // This will be called from the trade execution service
        }
    } catch (e) {
        console.error('Error checking patterns for token:', e);
    }
}

// Start pattern detection
function startPatternDetection() {
    if (stateRef.patternDetectionActive) return;
    stateRef.patternDetectionActive = true;
    if (stateRef.isRunning && stateRef.activeSession?.connected) detectAllPatterns();
    stateRef.patternDetectionTimer = setInterval(() => {
        if (stateRef.isRunning && stateRef.activeSession?.connected && !stateRef.isDetectingPatterns) {
            detectAllPatterns();
        }
    }, 15000);
}

// Stop pattern detection
function stopPatternDetection() {
    if (stateRef.patternDetectionTimer) {
        clearInterval(stateRef.patternDetectionTimer);
        stateRef.patternDetectionTimer = null;
    }
    stateRef.patternDetectionActive = false;
    stateRef.isDetectingPatterns = false;
}

module.exports = { initPatternDetection };