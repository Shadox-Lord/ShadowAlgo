-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Auto-update timestamp function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
$$;
$$ language 'plpgsql';

-- ===== TRADES TABLE =====
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('long', 'short')),
    entry_price DECIMAL(12, 5) NOT NULL,
    exit_price DECIMAL(12, 5),
    quantity DECIMAL(12, 5) NOT NULL,
    entry_time TIMESTAMZT NOT NULL DEFAULT NOW(),
    exit_time TIMESTAMZT,
    pnl DECIMAL(12, 5),
    pnl_pct DECIMAL(8, 4),
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    strategy VARCHAR(50),
    signal_id UUID,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMZT NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trades_asset ON trades(asset);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_entry_time ON trades(entry_time DESC);
CREATE INDEX idx_trades_strategy ON trades(strategy);

CREATE TRIGGER trg_trades_updated_at
    BEFORE UPDATE ON trades
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_can_read_trades"
    ON trades FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service_role_all_trades"
    ON trades FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ====== SIGNALS TABLE =====
CREATE TABLE signals (
    signal_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('long', 'short')),
    confidence DECIMAL(5, 2) NOT NULL CHECK (confidence >= 0 AND confidence <= 100),
    timeframe VARCHAR(10) NOT NULL,
    strategy VARCHAR(50),
    kronos_approved BOOLEAN DEFAULT FALSE,
    qwen_approved BOOLEAN DEFAULT FALSE,
    triggered BOOLEAN DEFAULT FALSE,
    executed_trade_id UUID REFERENCES trades(trade_id),
    price_at_signal DECIMAL(12, 5),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signals_asset ON signals(asset);
CREATE INDEX idx_signals_triggered ON signals(triggered);
CREATE INDEX idx_signals_created ON signals(created_at DESC);
CREATE INDEX idx_signals_confidence ON signals(confidence DESC);

ALTER TABLE signals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_can_read_signals"
    ON signals FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service_role_all_signals"
    ON signals FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ====== PERFORMANCE METRICS TABLE =====
CREATE TABLE performance_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    asset VARCHAR(20) NOT NULL,
    metric_name VARCHAR(50) NOT NULL,
    metric_value DECIMAL(15, 6) NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_perf_date ON performance_metrics(date DESC);
CREATE INDEX idx_perf_asset ON performance_metrics(asset);
CREATE INDEX idx_perf_name ON performance_metrics(metric_name);

ALTER TABLE performance_metrics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_can_read_perf"
    ON performance_metrics FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service_role_all_perf"
    ON performance_metrics FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ====== SYSTEM LOGS TABLE =====
CREATE TABLE system_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level VARCHAR(10) NOT NULL CHECK (level IN ('info', 'warn', 'error', 'debug')),
    module VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_logs_level ON system_logs(level);
CREATE INDEX idx_logs_module ON system_logs(module);
CREATE INDEX idx_logs_created ON system_logs(created_at DESC);

ALTER TABLE system_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_logs"
    ON system_logs FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ====== MODULE STATES TABLE =====
CREATE TABLE module_states (
    module_name VARCHAR(50) PRIMARY KEY,
    state VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'paused')),
    paused_by VARCHAR(100),
    paused_at TIMESTAMZT,
    updated_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

INSERT INTO, module_states (module_name, state) VALUES
    ('kronos_engine', 'active'),
    ('qwen_engine', 'active'),
    ('telegram_controller', 'active'),
    ('signal_generator', 'active'),
    ('trade_executor', 'active');

CREATE TRIGGER trg_module_states_updated_at
    BEFORE UPDATE ON module_states
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE module_states ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_modules"
    ON module_states FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ====== TELEGRAM COMMANDS TABLE =====
CREATE TABLE telegram_commands (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    command VARCHAR(50) NOT NULL,
    from_user VARCHAR(100),
    chat_id VARCHAR(50),
    response TEXT,
    created_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tg_commands_created ON telegram_commands(created_at DESC);

ALTER TABLE telegram_commands ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_tg_commands"
    ON telegram_commands FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);