import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # App Settings
    APP_VERSION = os.getenv("APP_VERSION", "2.0.0-PREPROD")
    NETWORK = os.getenv("NETWORK", "arbitrum")
    PRIMARY_PRICE_SOURCE = os.getenv("PRIMARY_PRICE_SOURCE", "arbitrum")
    IS_TEST_MODE = os.getenv("IS_TEST_MODE", "true").lower() in ("true", "1", "yes")

    # Trading Patterns & Limits
    BUY_PATTERNS = os.getenv("BUY_PATTERNS", "<_-0.1_5-300")
    SELL_PATTERNS = os.getenv("SELL_PATTERNS", ">_+0.1_5-300")
    TOTAL_TRADE_CAPITAL = float(os.getenv("TOTAL_TRADE_CAPITAL", "200"))
    MIN_TRADE_AMOUNT = float(os.getenv("MIN_TRADE_AMOUNT", "0.5"))
    TRADE_STEP = float(os.getenv("TRADE_STEP", "3.0"))
    PROFIT_ADDRESS = os.getenv("PROFIT_ADDRESS", "")
    MAX_TRADES = int(os.getenv("MAX_TRADES", "5"))
    STOP_LOSS = float(os.getenv("STOP_LOSS", "2"))
    TAKE_PROFIT = float(os.getenv("TAKE_PROFIT", "5"))
    TRAILING_STOP = float(os.getenv("TRAILING_STOP", "1"))
    TOKENS = [t.strip() for t in os.getenv("TOKENS", "").split(",") if t.strip()]
    TRADE_COOLDOWN = int(os.getenv("TRADE_COOLDOWN", "60"))

    # Price & Gas Settings
    PRICE_INTERVAL = int(os.getenv("PRICE_INTERVAL", "5000"))
    MAX_PRICE_AGE = int(os.getenv("MAX_PRICE_AGE", "30"))
    SLIPPAGE = float(os.getenv("SLIPPAGE", "0.5"))
    MAX_GAS_PRICE = float(os.getenv("MAX_GAS_PRICE", "200"))
    GAS_LIMIT = int(os.getenv("GAS_LIMIT", "500000"))
    MAX_PRICE_IMPACT = float(os.getenv("MAX_PRICE_IMPACT", "1"))

    # Debug & Backup
    DEBUG_MODE = os.getenv("DEBUG_MODE", "none")
    AUTO_BACKUP = os.getenv("AUTO_BACKUP", "true").lower() in ("true", "1", "yes")
    BACKUP_INTERVAL = int(os.getenv("BACKUP_INTERVAL", "30"))
    ENCRYPTION_ENABLED = os.getenv("ENCRYPTION_ENABLED", "false").lower() in ("true", "1", "yes")

    # Free Public RPC Endpoints (No API Key Required)
    # Using PublicNode (https://publicnode.com/) - Free tier with rate limits
    RPC_ARBITRUM_WS = os.getenv("RPC_ARBITRUM_WS", "wss://arbitrum-one-rpc.publicnode.com")
    RPC_ARBITRUM_HTTP = os.getenv("RPC_ARBITRUM_HTTP", "https://arbitrum-one-rpc.publicnode.com")
    
    RPC_ETHEREUM_WS = os.getenv("RPC_ETHEREUM_WS", "wss://ethereum-rpc.publicnode.com")
    RPC_ETHEREUM_HTTP = os.getenv("RPC_ETHEREUM_HTTP", "https://ethereum-rpc.publicnode.com")
    
    RPC_BASE_WS = os.getenv("RPC_BASE_WS", "wss://base-rpc.publicnode.com")
    RPC_BASE_HTTP = os.getenv("RPC_BASE_HTTP", "https://base-rpc.publicnode.com")
    
    RPC_OPTIMISM_WS = os.getenv("RPC_OPTIMISM_WS", "wss://optimism-rpc.publicnode.com")
    RPC_OPTIMISM_HTTP = os.getenv("RPC_OPTIMISM_HTTP", "https://optimism-rpc.publicnode.com")
    
    RPC_POLYGON_WS = os.getenv("RPC_POLYGON_WS", "wss://polygon-bor-rpc.publicnode.com")
    RPC_POLYGON_HTTP = os.getenv("RPC_POLYGON_HTTP", "https://polygon-bor-rpc.publicnode.com")

    # API Keys (Optional - for services like CoinGecko)
    COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
    PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")

    @classmethod
    def as_dict(cls) -> dict:
        return {
            "app_version": cls.APP_VERSION,
            "network": cls.NETWORK,
            "primary_price_source": cls.PRIMARY_PRICE_SOURCE,
            "is_test_mode": cls.IS_TEST_MODE,
            "buy_patterns": cls.BUY_PATTERNS,
            "sell_patterns": cls.SELL_PATTERNS,
            "total_trade_capital": cls.TOTAL_TRADE_CAPITAL,
            "min_trade_amount": cls.MIN_TRADE_AMOUNT,
            "trade_step": cls.TRADE_STEP,
            "profit_address": cls.PROFIT_ADDRESS,
            "max_trades": cls.MAX_TRADES,
            "stop_loss": cls.STOP_LOSS,
            "take_profit": cls.TAKE_PROFIT,
            "trailing_stop": cls.TRAILING_STOP,
            "tokens": cls.TOKENS,
            "trade_cooldown": cls.TRADE_COOLDOWN,
            "price_interval": cls.PRICE_INTERVAL,
            "max_price_age": cls.MAX_PRICE_AGE,
            "slippage": cls.SLIPPAGE,
            "max_gas_price": cls.MAX_GAS_PRICE,
            "gas_limit": cls.GAS_LIMIT,
            "max_price_impact": cls.MAX_PRICE_IMPACT,
            "debug_mode": cls.DEBUG_MODE,
            "auto_backup": cls.AUTO_BACKUP,
            "backup_interval": cls.BACKUP_INTERVAL,
            "encryption_enabled": cls.ENCRYPTION_ENABLED,
            "rpc_endpoints": {
                "arbitrum": {"ws": cls.RPC_ARBITRUM_WS, "http": cls.RPC_ARBITRUM_HTTP},
                "ethereum": {"ws": cls.RPC_ETHEREUM_WS, "http": cls.RPC_ETHEREUM_HTTP},
                "base": {"ws": cls.RPC_BASE_WS, "http": cls.RPC_BASE_HTTP},
                "optimism": {"ws": cls.RPC_OPTIMISM_WS, "http": cls.RPC_OPTIMISM_HTTP},
                "polygon": {"ws": cls.RPC_POLYGON_WS, "http": cls.RPC_POLYGON_HTTP},
            },
            "coingecko_api_key": cls.COINGECKO_API_KEY,
            "private_key": cls.PRIVATE_KEY,
        }