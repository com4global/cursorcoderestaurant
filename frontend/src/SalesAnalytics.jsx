import { useState, useEffect } from "react";
import { fetchAnalytics } from "./api.js";

const STATUS_COLORS = {
    completed: "#22c55e",
    rejected: "#ef4444",
    confirmed: "#eab308",
    accepted: "#3b82f6",
    preparing: "#8b5cf6",
    ready: "#06b6d4",
    pending: "#6b7280",
};

export default function SalesAnalytics({ token, restaurantId, restaurantName }) {
    const [period, setPeriod] = useState("month");
    const [customFrom, setCustomFrom] = useState("");
    const [customTo, setCustomTo] = useState("");
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        loadData();
    }, [period]);

    async function loadData() {
        setLoading(true);
        try {
            const d = await fetchAnalytics(
                token, restaurantId, period,
                period === "custom" ? customFrom : undefined,
                period === "custom" ? customTo : undefined,
            );
            setData(d);
        } catch {
            // silent
        }
        setLoading(false);
    }

    function fmt(cents) {
        return "$" + (cents / 100).toFixed(2);
    }

    function fmtShort(cents) {
        if (cents >= 100000) return "$" + (cents / 100000).toFixed(1) + "k";
        return "$" + (cents / 100).toFixed(0);
    }

    if (loading && !data) {
        return <div className="sales-loading">Loading analytics...</div>;
    }

    if (!data) {
        return <div className="sales-loading">Unable to load analytics.</div>;
    }

    const { summary, daily_revenue, top_items, orders_by_status } = data;
    const maxRevenue = Math.max(...daily_revenue.map(d => d.revenue), 1);
    const totalStatusOrders = Object.values(orders_by_status).reduce((a, b) => a + b, 0);

    // Chart dimensions
    const chartW = 100; // percentage width
    const barCount = daily_revenue.length;

    return (
        <div className="sales-analytics">
            {/* Period Selector */}
            <div className="sales-period-bar">
                {["week", "month", "year"].map(p => (
                    <button
                        key={p}
                        className={`sales-period-btn ${period === p ? "active" : ""}`}
                        onClick={() => setPeriod(p)}
                    >
                        {p === "week" ? "7 Days" : p === "month" ? "30 Days" : "1 Year"}
                    </button>
                ))}
                <button
                    className={`sales-period-btn ${period === "custom" ? "active" : ""}`}
                    onClick={() => setPeriod("custom")}
                >
                    Custom
                </button>
            </div>

            {/* Custom date range */}
            {period === "custom" && (
                <div className="sales-custom-range">
                    <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)} />
                    <span>to</span>
                    <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)} />
                    <button className="sales-apply-btn" onClick={loadData}>Apply</button>
                </div>
            )}

            {/* Date range display */}
            <div className="sales-date-range">
                📅 {data.date_from} → {data.date_to}
            </div>

            {/* Summary Cards */}
            <div className="sales-summary-grid">
                <div className="sales-card sales-card-revenue">
                    <div className="sales-card-icon">💰</div>
                    <div className="sales-card-value">{fmt(summary.total_revenue_cents)}</div>
                    <div className="sales-card-label">Total Revenue</div>
                </div>
                <div className="sales-card sales-card-orders">
                    <div className="sales-card-icon">📦</div>
                    <div className="sales-card-value">{summary.order_count}</div>
                    <div className="sales-card-label">Completed Orders</div>
                </div>
                <div className="sales-card sales-card-avg">
                    <div className="sales-card-icon">📊</div>
                    <div className="sales-card-value">{fmt(summary.avg_order_cents)}</div>
                    <div className="sales-card-label">Avg Order Value</div>
                </div>
            </div>

            {/* Revenue Chart */}
            <div className="sales-chart-section">
                <h4>Revenue Over Time</h4>
                <div className="sales-chart-container">
                    <div className="sales-chart-y-axis">
                        <span>{fmtShort(maxRevenue)}</span>
                        <span>{fmtShort(maxRevenue / 2)}</span>
                        <span>$0</span>
                    </div>
                    <div className="sales-chart-bars">
                        {daily_revenue.map((d, i) => {
                            const h = maxRevenue > 0 ? (d.revenue / maxRevenue) * 100 : 0;
                            const showLabel = barCount <= 14 || i % Math.ceil(barCount / 10) === 0;
                            return (
                                <div key={d.date} className="sales-bar-group" title={`${d.date}\n${fmt(d.revenue)} | ${d.orders} orders`}>
                                    <div className="sales-bar-fill" style={{ height: `${Math.max(h, 1)}%` }}>
                                        {h > 15 && barCount <= 14 && (
                                            <span className="sales-bar-value">{fmtShort(d.revenue)}</span>
                                        )}
                                    </div>
                                    {showLabel && (
                                        <span className="sales-bar-label">
                                            {barCount <= 14 ? d.date.slice(5) : d.date.slice(5, 7)}
                                        </span>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>

            {/* Two Column: Top Items + Status Breakdown */}
            <div className="sales-bottom-grid">
                {/* Top Items */}
                <div className="sales-chart-section">
                    <h4>🏆 Top Selling Items</h4>
                    {top_items.length === 0 && <p className="sales-empty">No sales data yet.</p>}
                    <div className="sales-top-items">
                        {top_items.map((item, i) => {
                            const barW = top_items[0] ? (item.quantity / top_items[0].quantity) * 100 : 0;
                            return (
                                <div key={item.menu_item_id} className="sales-top-item">
                                    <div className="sales-top-rank">#{i + 1}</div>
                                    <div className="sales-top-info">
                                        <div className="sales-top-name">{item.name}</div>
                                        <div className="sales-top-bar-bg">
                                            <div className="sales-top-bar-fill" style={{ width: `${barW}%` }} />
                                        </div>
                                    </div>
                                    <div className="sales-top-stats">
                                        <span className="sales-top-qty">{item.quantity} sold</span>
                                        <span className="sales-top-rev">{fmt(item.revenue)}</span>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Status Breakdown */}
                <div className="sales-chart-section">
                    <h4>📊 Order Status Breakdown</h4>
                    {totalStatusOrders === 0 && <p className="sales-empty">No orders in this period.</p>}
                    {totalStatusOrders > 0 && (
                        <>
                            {/* Horizontal stacked bar */}
                            <div className="sales-status-bar">
                                {Object.entries(orders_by_status).map(([status, count]) => (
                                    <div
                                        key={status}
                                        className="sales-status-segment"
                                        style={{
                                            width: `${(count / totalStatusOrders) * 100}%`,
                                            backgroundColor: STATUS_COLORS[status] || "#6b7280",
                                        }}
                                        title={`${status}: ${count}`}
                                    />
                                ))}
                            </div>
                            <div className="sales-status-legend">
                                {Object.entries(orders_by_status).map(([status, count]) => (
                                    <div key={status} className="sales-status-item">
                                        <span
                                            className="sales-status-dot"
                                            style={{ backgroundColor: STATUS_COLORS[status] || "#6b7280" }}
                                        />
                                        <span className="sales-status-label">{status}</span>
                                        <span className="sales-status-count">{count}</span>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
