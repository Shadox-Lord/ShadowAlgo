-- Shadow Portfolio Hub - Serverless Schema Migration
-- Target: Supabase PostgreSQL
-- Architecture: 100% Serverless Signal Generation (Human-in-the-Loop)
-- Risk Model: Method A - Fixed Initial Balance (0.30% risk per trade)

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Auto-update timestamp function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

-- ===== SYSTEM STATE TABLE =====
-- Single-row table storing target initial balance for risk calculations
CREATE TABLE system_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    target_initial_balance DECIMAL(12, 2) NOT NULL DEFAULT 5000.00,
    is_trading_halted BOOLEAN NOT NULL DEFAULT FALSE,
    halted_at TIMESTAMZT,
    halted_reason VARCHAR(255),
    updated_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

-- Initialize with default row
INSERT INTO system_state (id, target_initial_balance) VALUES (1, 5000.00);

CREATE TRIGGER trg_system_state_updated_at
    BEFORE UPDATE ON system_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE system_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_can_read_system_state"
    ON system_state FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service_role_all_system_state"
    ON system_state FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ===== AUDIT LOGS TABLE =====
-- Stores Kronos forecasting data and Qwen SMC reasoning
CREATE TABLE audit_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    kronos_direction VARCHAR(10),
    kronos_confidence DECIMAL(5, 2),
    kronos_predicted_move_pct DECIMAL(8, 4),
    qwen_structure_valid BOOLEAN,
    qwen_direction VARCHAR(10),
    qwen_confidence DECIMAL(5, 2),
    qwen_reasoning JSONB,
    signal_approved BOOLEAN DEFAULT FALSE,
    rejection_reason VARCHAR(255),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_asset ON audit_logs(asset);
CREATE INDEX idx_audit_logs_timeframe ON audit_logs(timeframe);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_logs_approved ON audit_logs(signal_approved);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_can_read_audit_logs"
    ON audit_logs FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service_role_all_audit_logs"
    ON audit_logs FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ===== TRADE EXECUTIONS TABLE =====
-- Stores generated signals with status SIGNAL_SENT
CREATE TABLE trade_executions (
    execution_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('long', 'short')),
    entry_price DECIMAL(12, 5) NOT NULL,
    stop_loss DECIMAL(12, 5) NOT NULL,
    take_profit DECIMAL(12, 5) NOT NULL,
    lot_size DECIMAL(12, 2) NOT NULL,
    risk_amount DECIMAL(12, 2) NOT NULL,
    sl_distance_pips DECIMAL(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SIGNAL_SENT' CHECK (status IN ('SIGNAL_SENT', 'MANUAL_FILLED', 'MANUAL_CANCELLED', 'EXPIRED')),
    kronos_confidence DECIMAL(5, 2),
    qwen_confidence DECIMAL(5, 2),
    qwen_reasoning JSONB,
    telegram_message_id BIGINT,
    manual_entry_price DECIMAL(12, 5),
    manual_exit_price DECIMAL(12, 5),
    manual_pnl DECIMAL(12, 2),
    manual_pnl_pct DECIMAL(8, 4),
    filled_at TIMESTAMZT,
    closed_at TIMESTAMZT,
    user_notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMZT NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_executions_asset ON trade_executions(asset);
CREATE INDEX idx_trade_executions_status ON trade_executions(status);
CREATE INDEX idx_trade_executions_created ON trade_executions(created_at DESC);
CREATE INDEX idx_trade_executions_direction ON trade_executions(direction);

CREATE TRIGGER trg_trade_executions_updated_at
    BEFORE UPDATE ON trade_executions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE trade_executions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_can_read_trade_executions"
    ON trade_executions FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service_role_all_trade_executions"
    ON trade_executions FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ===== PERFORMANCE METRICS TABLE =====
-- For tracking manual fill results and PnL updates
CREATE TABLE performance_metrics (
    metric_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

CREATE POLICY "anon_can_read_perf_metrics"
    ON performance_metrics FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service_role_all_perf_metrics"
    ON performance_metrics FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ===== MODULE PAUSE STATES TABLE =====
-- Tracks temporarily disabled asset classes
CREATE TABLE module_pause_states (
    module_name VARCHAR(50) PRIMARY KEY,
    is_paused BOOLEAN NOT NULL DEFAULT FALSE,
    paused_by VARCHAR(100),
    paused_at TIMESTAMZT,
    pause_reason VARCHAR(255),
    updated_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

-- Initialize with default modules
INSERT INTO module_pause_states (module_name, is_paused) VALUES
    ('NQ', FALSE),
    ('XAUUSD', FALSE),
    ('EURUSD', FALSE),
    ('GBPUSD', FALSE),
    ('USDJPY', FALSE),
    ('AUDUSD', FALSE)
ON CONFLICT (module_name) DO NOTHING;

CREATE TRIGGER trg_module_pause_states_updated_at
    BEFORE UPDATE ON module_pause_states
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE module_pause_states ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_module_states"
    ON module_pause_states FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ===== SYSTEM LOGS TABLE =====
-- General logging for debugging and monitoring
CREATE TABLE system_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level VARCHAR(10) NOT NULL CHECK (level IN ('info', 'warn', 'error', 'debug', 'critical')),
    module VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMZT NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_system_logs_level ON system_logs(level);
CREATE INDEX idx_system_logs_module ON system_logs(module);
CREATE INDEX idx_system_logs_created ON system_logs(created_at DESC);

ALTER TABLE system_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all_system_logs"
    ON system_logs FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ===== HELPER FUNCTIONS =====

-- Function to get current target balance
CREATE OR REPLACE FUNCTION get_target_balance()
RETURNS DECIMAL(12, 2) AS $$
BEGIN
    RETURN (SELECT target_initial_balance FROM system_state WHERE id = 1);
END;
$$ LANGUAGE 'plpgsql' STABLE;

-- Function to check if trading is halted
CREATE OR REPLACE FUNCTION is_trading_halted()
RETURNS BOOLEAN AS $$
BEGIN
    RETURN (SELECT is_trading_halted FROM system_state WHERE id = 1);
END;
$$ LANGUAGE 'plpgsql' STABLE;

-- Function to insert audit log with Kronos + Qwen data
CREATE OR REPLACE FUNCTION insert_audit_log(
    p_asset VARCHAR(20),
    p_timeframe VARCHAR(10),
    p_kronos_direction VARCHAR(10),
    p_kronos_confidence DECIMAL(5, 2),
    p_kronos_predicted_move_pct DECIMAL(8, 4),
    p_qwen_structure_valid BOOLEAN,
    p_qwen_direction VARCHAR(10),
    p_qwen_confidence DECIMAL(5, 2),
    p_qwen_reasoning JSONB,
    p_signal_approved BOOLEAN,
    p_rejection_reason VARCHAR(255)
)
RETURNS UUID AS $$
DECLARE
    v_log_id UUID;
BEGIN
    INSERT INTO audit_logs (
        asset, timeframe, kronos_direction, kronos_confidence, 
        kronos_predicted_move_pct, qwen_structure_valid, qwen_direction,
        qwen_confidence, qwen_reasoning, signal_approved, rejection_reason
    ) VALUES (
        p_asset, p_timeframe, p_kronos_direction, p_kronos_confidence,
        p_kronos_predicted_move_pct, p_qwen_structure_valid, p_qwen_direction,
        p_qwen_confidence, p_qwen_reasoning, p_signal_approved, p_rejection_reason
    ) RETURNING log_id INTO v_log_id;
    
    RETURN v_log_id;
END;
$$ LANGUAGE 'plpgsql';

COMMENT ON FUNCTION insert_audit_log IS 'Helper function to insert audit logs with Kronos and Qwen data';
