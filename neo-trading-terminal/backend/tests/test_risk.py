import pytest
from app.terminal.risk import RiskManager, RiskLimits, RiskViolationError

def test_max_order_value():
    rm = RiskManager(RiskLimits(max_order_value=1000.0))
    # Valid order
    rm.validate_order("TCS", "BUY", 10, 90.0, 95.0)  # Value 900
    
    # Exceeds max_order_value
    with pytest.raises(RiskViolationError) as excinfo:
        rm.validate_order("TCS", "BUY", 10, 110.0, 110.0)  # Value 1100
    assert excinfo.value.code == "MAX_ORDER_VALUE_EXCEEDED"

def test_price_deviation():
    rm = RiskManager(RiskLimits(max_price_deviation_pct=5.0))
    # Valid price (deviation is exactly 5%)
    rm.validate_order("RELIANCE", "BUY", 1, 105.0, 100.0)
    
    # Exceeds price deviation (6% deviation)
    with pytest.raises(RiskViolationError) as excinfo:
        rm.validate_order("RELIANCE", "BUY", 1, 106.0, 100.0)
    assert excinfo.value.code == "PRICE_COLLAR_EXCEEDED"
    
def test_max_daily_loss():
    rm = RiskManager(RiskLimits(max_daily_loss=500.0))
    # Accumulate some loss
    rm.record_trade_pnl(-200.0)
    rm.validate_order("INFY", "SELL", 10, 100.0, 100.0)  # Should pass
    
    # Accumulate more loss to breach limit
    rm.record_trade_pnl(-400.0)
    # Total loss is now -600.0
    with pytest.raises(RiskViolationError) as excinfo:
        rm.validate_order("INFY", "BUY", 10, 100.0, 100.0)
    assert excinfo.value.code == "MAX_DAILY_LOSS_EXCEEDED"

def test_kill_switch():
    rm = RiskManager()
    rm.validate_order("HDFC", "BUY", 1, 100.0, 100.0) # Should pass
    
    rm.trigger_kill_switch("Fat finger detected")
    
    with pytest.raises(RiskViolationError) as excinfo:
        rm.validate_order("HDFC", "BUY", 1, 100.0, 100.0)
    assert excinfo.value.code == "KILL_SWITCH_ACTIVE"
    assert "Fat finger detected" in str(excinfo.value)
    
    rm.reset_kill_switch()
    rm.validate_order("HDFC", "BUY", 1, 100.0, 100.0) # Should pass again

def test_max_quantity():
    rm = RiskManager(RiskLimits(max_quantity_per_order=100))
    rm.validate_order("ITC", "BUY", 100, 100.0, 100.0) # Should pass
    
    with pytest.raises(RiskViolationError) as excinfo:
        rm.validate_order("ITC", "BUY", 101, 100.0, 100.0)
    assert excinfo.value.code == "MAX_QUANTITY_EXCEEDED"
    
def test_invalid_quantity():
    rm = RiskManager()
    with pytest.raises(RiskViolationError) as excinfo:
        rm.validate_order("ITC", "BUY", 0, 100.0, 100.0)
    assert excinfo.value.code == "INVALID_QUANTITY"
