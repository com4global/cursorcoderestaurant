import { useState, useEffect, useRef, useCallback } from "react";
import {
    registerOwner,
    getMe,
    getMyRestaurants,
    createRestaurant,
    importMenuFromUrl,
    saveImportedMenu,
    fetchOrders,
    updateOrderStatus,
    updateNotifications,
} from "./api.js";

export default function OwnerPortal({ token, onBack, onTokenUpdate }) {
    const [user, setUser] = useState(null);
    const [myRestaurants, setMyRestaurants] = useState([]);
    const [loading, setLoading] = useState(true);

    // Registration
    const [regEmail, setRegEmail] = useState("");
    const [regPassword, setRegPassword] = useState("");
    const [regError, setRegError] = useState("");

    // Create Restaurant
    const [showCreate, setShowCreate] = useState(false);
    const [restName, setRestName] = useState("");
    const [restCity, setRestCity] = useState("");
    const [restAddress, setRestAddress] = useState("");
    const [restZipcode, setRestZipcode] = useState("");
    const [restPhone, setRestPhone] = useState("");
    const [restLat, setRestLat] = useState("");
    const [restLng, setRestLng] = useState("");
    const [restDesc, setRestDesc] = useState("");

    // Menu Import
    const [importUrl, setImportUrl] = useState("");
    const [importLoading, setImportLoading] = useState(false);
    const [importedMenu, setImportedMenu] = useState(null);
    const [importError, setImportError] = useState("");
    const [importRestId, setImportRestId] = useState(null);
    const [saveStatus, setSaveStatus] = useState("");

    // Orders Dashboard
    const [activeTab, setActiveTab] = useState({}); // { restaurantId: "orders" | "menu" | "settings" }
    const [orders, setOrders] = useState({}); // { restaurantId: [...orders] }
    const [ordersLoading, setOrdersLoading] = useState({});
    const [lastOrderCounts, setLastOrderCounts] = useState({});
    const audioRef = useRef(null);

    // Notification settings
    const [notifEmail, setNotifEmail] = useState({});
    const [notifPhone, setNotifPhone] = useState({});
    const [notifSaving, setNotifSaving] = useState({});

    useEffect(() => {
        if (token) loadProfile();
    }, [token]);

    // --- Orders polling ---
    const loadOrders = useCallback(async (restaurantId) => {
        if (!token) return;
        setOrdersLoading((p) => ({ ...p, [restaurantId]: true }));
        try {
            const data = await fetchOrders(token, restaurantId);
            const prevCount = lastOrderCounts[restaurantId] || 0;
            const confirmedOrders = data.filter((o) => o.status === "confirmed");
            // Play sound if new confirmed orders appeared
            if (confirmedOrders.length > prevCount && prevCount > 0) {
                playNotificationSound();
            }
            setLastOrderCounts((p) => ({ ...p, [restaurantId]: confirmedOrders.length }));
            setOrders((p) => ({ ...p, [restaurantId]: data }));
        } catch {
            // silent
        }
        setOrdersLoading((p) => ({ ...p, [restaurantId]: false }));
    }, [token, lastOrderCounts]);

    // Poll orders for restaurants with "orders" tab active
    useEffect(() => {
        const intervals = [];
        for (const rId of Object.keys(activeTab)) {
            if (activeTab[rId] === "orders") {
                loadOrders(parseInt(rId));
                const iv = setInterval(() => loadOrders(parseInt(rId)), 10000);
                intervals.push(iv);
            }
        }
        return () => intervals.forEach(clearInterval);
    }, [activeTab, token]);

    function playNotificationSound() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 800;
            gain.gain.value = 0.3;
            osc.start();
            osc.stop(ctx.currentTime + 0.3);
            setTimeout(() => {
                const osc2 = ctx.createOscillator();
                osc2.connect(gain);
                osc2.frequency.value = 1000;
                osc2.start();
                osc2.stop(ctx.currentTime + 0.3);
            }, 200);
        } catch {
            // AudioContext not available
        }
    }

    async function loadProfile() {
        setLoading(true);
        try {
            const me = await getMe(token);
            setUser(me);
            if (me.role === "owner" || me.role === "admin") {
                const rests = await getMyRestaurants(token);
                setMyRestaurants(rests);
                // Initialize notification fields
                const ne = {}, np = {};
                rests.forEach((r) => {
                    ne[r.id] = r.notification_email || "";
                    np[r.id] = r.notification_phone || "";
                });
                setNotifEmail(ne);
                setNotifPhone(np);
            }
        } catch {
            setUser(null);
        }
        setLoading(false);
    }

    async function handleRegisterOwner(e) {
        e.preventDefault();
        setRegError("");
        try {
            const data = await registerOwner({ email: regEmail, password: regPassword });
            if (onTokenUpdate) onTokenUpdate(data.access_token);
        } catch (err) {
            setRegError(err.message || "Registration failed");
        }
    }

    async function handleCreateRestaurant(e) {
        e.preventDefault();
        try {
            await createRestaurant(token, {
                name: restName,
                city: restCity,
                address: restAddress,
                zipcode: restZipcode,
                phone: restPhone,
                latitude: restLat ? parseFloat(restLat) : undefined,
                longitude: restLng ? parseFloat(restLng) : undefined,
                description: restDesc,
            });
            setRestName(""); setRestCity(""); setRestAddress(""); setRestZipcode("");
            setRestPhone(""); setRestLat(""); setRestLng(""); setRestDesc("");
            setShowCreate(false);
            loadProfile();
        } catch {
            alert("Failed to create restaurant");
        }
    }

    async function handleImportMenu() {
        if (!importUrl.trim()) return;
        setImportLoading(true);
        setImportError("");
        setImportedMenu(null);
        try {
            const data = await importMenuFromUrl(token, importUrl.trim());
            if (data.error) {
                setImportError(data.error);
            } else {
                // Convert price_cents to price (dollars) and strip empty categories
                if (data.categories) {
                    data.categories = data.categories
                        .filter(c => c.items && c.items.length > 0)
                        .map(c => ({
                            ...c,
                            items: c.items.map(item => ({
                                ...item,
                                // Always prefer price_cents (from AI), convert to dollars
                                price: item.price_cents ? (item.price_cents / 100) : (item.price || 0),
                            }))
                        }));
                }
                setImportedMenu(data);
            }
        } catch (err) {
            setImportError(err.message || "Import failed");
        }
        setImportLoading(false);
    }

    async function handleSaveMenu() {
        if (!importedMenu || !importRestId) return;
        setSaveStatus("saving");
        try {
            await saveImportedMenu(token, importRestId, importedMenu);
            setSaveStatus("saved");
            loadProfile();
        } catch {
            setSaveStatus("error");
        }
    }

    // --- Editable menu helpers ---
    function updateItem(catIndex, itemIndex, field, value) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            if (field === "price") {
                copy.categories[catIndex].items[itemIndex].price = parseFloat(value) || 0;
            } else {
                copy.categories[catIndex].items[itemIndex][field] = value;
            }
            return copy;
        });
    }

    function deleteItem(catIndex, itemIndex) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories[catIndex].items.splice(itemIndex, 1);
            return copy;
        });
    }

    function updateCategoryName(catIndex, newName) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories[catIndex].name = newName;
            return copy;
        });
    }

    function addItem(catIndex) {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories[catIndex].items.push({ name: "", description: "", price: 0 });
            return copy;
        });
    }

    function addCategory() {
        setImportedMenu((prev) => {
            const copy = JSON.parse(JSON.stringify(prev));
            copy.categories.push({ name: "New Category", items: [{ name: "", description: "", price: 0 }] });
            return copy;
        });
    }

    // --- Order status update ---
    async function handleStatusChange(restaurantId, orderId, newStatus) {
        try {
            await updateOrderStatus(token, orderId, newStatus);
            loadOrders(restaurantId);
        } catch {
            alert("Failed to update order status");
        }
    }

    // --- Save notification settings ---
    async function handleSaveNotifications(restaurantId) {
        setNotifSaving((p) => ({ ...p, [restaurantId]: true }));
        try {
            await updateNotifications(token, restaurantId, {
                notification_email: notifEmail[restaurantId] || "",
                notification_phone: notifPhone[restaurantId] || "",
            });
        } catch {
            alert("Failed to save notification settings");
        }
        setNotifSaving((p) => ({ ...p, [restaurantId]: false }));
    }

    // --- Status badge ---
    function StatusBadge({ status }) {
        const colors = {
            pending: { bg: "#fef3c7", color: "#92400e", label: "🛒 In Cart" },
            confirmed: { bg: "#fde68a", color: "#92400e", label: "🔔 New Order" },
            accepted: { bg: "#d1fae5", color: "#065f46", label: "✅ Accepted" },
            preparing: { bg: "#dbeafe", color: "#1e40af", label: "🍳 Preparing" },
            ready: { bg: "#a7f3d0", color: "#065f46", label: "📦 Ready" },
            rejected: { bg: "#fee2e2", color: "#991b1b", label: "❌ Rejected" },
            completed: { bg: "#e5e7eb", color: "#374151", label: "✓ Done" },
        };
        const s = colors[status] || { bg: "#e5e7eb", color: "#374151", label: status };
        return (
            <span style={{
                background: s.bg, color: s.color, padding: "3px 10px", borderRadius: 12,
                fontSize: "0.78rem", fontWeight: 700, whiteSpace: "nowrap",
            }}>{s.label}</span>
        );
    }

    // --- Tab helper ---
    function getTab(rId) { return activeTab[rId] || "menu"; }
    function setTab(rId, tab) {
        setActiveTab((p) => ({ ...p, [rId]: tab }));
        if (tab === "orders" && !orders[rId]) loadOrders(rId);
    }

    if (loading) {
        return (
            <div className="owner-portal">
                <div className="owner-loading">Loading...</div>
            </div>
        );
    }

    // Not logged in or not an owner — show register
    if (!user || (user.role !== "owner" && user.role !== "admin")) {
        return (
            <div className="owner-portal">
                <button className="owner-back-btn" onClick={onBack}>← Back to App</button>
                <div className="owner-card owner-register">
                    <h2>🍽️ Restaurant Owner Portal</h2>
                    <p>Register as a restaurant owner to manage your menus and receive orders.</p>
                    <form onSubmit={handleRegisterOwner}>
                        <label>Email<input type="email" value={regEmail} onChange={(e) => setRegEmail(e.target.value)} required /></label>
                        <label>Password<input type="password" value={regPassword} onChange={(e) => setRegPassword(e.target.value)} required minLength={6} /></label>
                        {regError && <p className="owner-error">{regError}</p>}
                        <button type="submit" className="owner-primary-btn">Continue as Owner</button>
                    </form>
                </div>
            </div>
        );
    }

    return (
        <div className="owner-portal">
            <div className="owner-header">
                <button className="owner-back-btn" onClick={onBack}>← Back to App</button>
                <h2>🍽️ Owner Dashboard</h2>
                <span className="owner-email">{user.email}</span>
            </div>

            {/* My Restaurants */}
            <div className="owner-card">
                <div className="owner-card-header">
                    <h3>My Restaurants ({myRestaurants.length})</h3>
                    <button className="owner-add-btn" onClick={() => setShowCreate(!showCreate)}>
                        {showCreate ? "✕ Cancel" : "+ Add Restaurant"}
                    </button>
                </div>

                {showCreate && (
                    <form className="owner-form" onSubmit={handleCreateRestaurant}>
                        <div className="owner-form-grid">
                            <label>Restaurant Name *<input value={restName} onChange={(e) => setRestName(e.target.value)} required placeholder="e.g. Joe's Pizza" /></label>
                            <label>City *<input value={restCity} onChange={(e) => setRestCity(e.target.value)} required placeholder="e.g. Lancaster" /></label>
                            <label>Address<input value={restAddress} onChange={(e) => setRestAddress(e.target.value)} placeholder="123 Main St" /></label>
                            <label>Zipcode<input value={restZipcode} onChange={(e) => setRestZipcode(e.target.value)} placeholder="29720" /></label>
                            <label>Phone<input value={restPhone} onChange={(e) => setRestPhone(e.target.value)} placeholder="803-555-1234" /></label>
                            <label>Description<input value={restDesc} onChange={(e) => setRestDesc(e.target.value)} placeholder="Best pizza in town" /></label>
                            <label>Latitude<input value={restLat} onChange={(e) => setRestLat(e.target.value)} placeholder="34.72" /></label>
                            <label>Longitude<input value={restLng} onChange={(e) => setRestLng(e.target.value)} placeholder="-80.77" /></label>
                        </div>
                        <button type="submit" className="owner-primary-btn">Create Restaurant</button>
                    </form>
                )}

                {myRestaurants.length === 0 && !showCreate && (
                    <p className="owner-empty">No restaurants yet. Click "+ Add Restaurant" to get started.</p>
                )}

                {/* Restaurant list with tabs */}
                <div className="owner-restaurants-list">
                    {myRestaurants.map((r) => {
                        const tab = getTab(r.id);
                        const rOrders = orders[r.id] || [];
                        const newOrderCount = rOrders.filter((o) => o.status === "confirmed").length;
                        return (
                            <div key={r.id} className="owner-restaurant-block">
                                {/* Restaurant header */}
                                <div className="owner-restaurant-item">
                                    <div className="owner-restaurant-info">
                                        <strong>{r.name}</strong>
                                        <span className="owner-restaurant-meta">{r.city} · #{r.slug}</span>
                                    </div>
                                    {newOrderCount > 0 && (
                                        <span className="owner-new-order-badge">{newOrderCount} new</span>
                                    )}
                                </div>

                                {/* Tab buttons */}
                                <div className="owner-tab-bar">
                                    <button className={`owner-tab-btn ${tab === "orders" ? "active" : ""}`} onClick={() => setTab(r.id, "orders")}>
                                        📋 Orders {newOrderCount > 0 && <span className="owner-tab-badge">{newOrderCount}</span>}
                                    </button>
                                    <button className={`owner-tab-btn ${tab === "menu" ? "active" : ""}`} onClick={() => setTab(r.id, "menu")}>
                                        🍽️ Menu
                                    </button>
                                    <button className={`owner-tab-btn ${tab === "settings" ? "active" : ""}`} onClick={() => setTab(r.id, "settings")}>
                                        ⚙️ Notifications
                                    </button>
                                </div>

                                {/* ORDERS TAB */}
                                {tab === "orders" && (
                                    <div className="owner-orders-panel">
                                        {ordersLoading[r.id] && rOrders.length === 0 && (
                                            <p className="owner-loading-text">Loading orders...</p>
                                        )}
                                        {!ordersLoading[r.id] && rOrders.length === 0 && (
                                            <p className="owner-empty">No orders yet. Orders will appear here when customers check out.</p>
                                        )}
                                        {rOrders.map((order) => (
                                            <div key={order.id} className={`owner-order-card ${order.status === "confirmed" ? "owner-order-new" : ""}`}>
                                                <div className="owner-order-header">
                                                    <span className="owner-order-id">Order #{order.id}</span>
                                                    <StatusBadge status={order.status} />
                                                </div>
                                                <div className="owner-order-meta">
                                                    <span>👤 {order.customer_email || "Guest"}</span>
                                                    <span>🕐 {new Date(order.created_at).toLocaleString()}</span>
                                                </div>
                                                <div className="owner-order-items">
                                                    {order.items.map((item, idx) => (
                                                        <div key={idx} className="owner-order-item-row">
                                                            <span>{item.name} × {item.quantity}</span>
                                                            <span>${(item.price_cents / 100).toFixed(2)}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                                <div className="owner-order-total">
                                                    Total: <strong>${(order.total_cents / 100).toFixed(2)}</strong>
                                                </div>
                                                {/* Action buttons based on status */}
                                                {order.status === "confirmed" && (
                                                    <div className="owner-order-actions">
                                                        <button className="owner-accept-btn" onClick={() => handleStatusChange(r.id, order.id, "accepted")}>
                                                            ✅ Accept
                                                        </button>
                                                        <button className="owner-reject-btn" onClick={() => handleStatusChange(r.id, order.id, "rejected")}>
                                                            ❌ Reject
                                                        </button>
                                                    </div>
                                                )}
                                                {order.status === "accepted" && (
                                                    <div className="owner-order-actions">
                                                        <button className="owner-preparing-btn" onClick={() => handleStatusChange(r.id, order.id, "preparing")}>
                                                            🍳 Start Preparing
                                                        </button>
                                                    </div>
                                                )}
                                                {order.status === "preparing" && (
                                                    <div className="owner-order-actions">
                                                        <button className="owner-ready-btn" onClick={() => handleStatusChange(r.id, order.id, "ready")}>
                                                            📦 Mark Ready
                                                        </button>
                                                    </div>
                                                )}
                                                {order.status === "ready" && (
                                                    <div className="owner-order-actions">
                                                        <button className="owner-complete-btn" onClick={() => handleStatusChange(r.id, order.id, "completed")}>
                                                            ✓ Complete
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* MENU TAB */}
                                {tab === "menu" && (
                                    <div className="owner-menu-panel">
                                        <button
                                            className="owner-import-trigger"
                                            onClick={() => {
                                                setImportRestId(r.id);
                                                setImportedMenu(null);
                                                setImportUrl("");
                                                setImportError("");
                                                setSaveStatus("");
                                            }}
                                        >
                                            🤖 Import Menu from Website
                                        </button>
                                    </div>
                                )}

                                {/* SETTINGS TAB */}
                                {tab === "settings" && (
                                    <div className="owner-settings-panel">
                                        <h4>📧 Notification Settings</h4>
                                        <p className="owner-settings-desc">Get notified when new orders come in. Leave blank to use your login email.</p>
                                        <div className="owner-settings-form">
                                            <label>
                                                Notification Email
                                                <input
                                                    type="email"
                                                    value={notifEmail[r.id] || ""}
                                                    onChange={(e) => setNotifEmail((p) => ({ ...p, [r.id]: e.target.value }))}
                                                    placeholder={user.email}
                                                />
                                            </label>
                                            <label>
                                                Phone (for SMS/WhatsApp)
                                                <input
                                                    type="tel"
                                                    value={notifPhone[r.id] || ""}
                                                    onChange={(e) => setNotifPhone((p) => ({ ...p, [r.id]: e.target.value }))}
                                                    placeholder="+1 803-555-1234"
                                                />
                                            </label>
                                            <button
                                                className="owner-primary-btn"
                                                onClick={() => handleSaveNotifications(r.id)}
                                                disabled={notifSaving[r.id]}
                                            >
                                                {notifSaving[r.id] ? "Saving..." : "💾 Save Notification Settings"}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* AI Menu Import Modal Overlay */}
            {importRestId && (
                <div className="owner-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) setImportRestId(null); }}>
                    <div className="owner-modal">
                        {/* Scrollable body */}
                        <div className="owner-modal-body">
                            <div className="owner-modal-header">
                                <h3>
                                    🤖 AI Menu Import
                                    <span className="owner-import-for">
                                        for {myRestaurants.find((r) => r.id === importRestId)?.name}
                                    </span>
                                </h3>
                                <button className="owner-modal-close" onClick={() => setImportRestId(null)}>✕</button>
                            </div>
                            <p className="owner-modal-desc">Paste the restaurant's website/menu URL and our AI will extract the full menu automatically.</p>

                            <div className="owner-import-row">
                                <input
                                    className="owner-import-input"
                                    value={importUrl}
                                    onChange={(e) => setImportUrl(e.target.value)}
                                    placeholder="https://restaurant-website.com/menu"
                                    autoFocus
                                />
                                <button
                                    className="owner-extract-btn"
                                    onClick={handleImportMenu}
                                    disabled={importLoading}
                                >
                                    {importLoading ? "⏳ Extracting..." : "🔮 Extract Menu"}
                                </button>
                            </div>

                            {importLoading && (
                                <div className="owner-import-loading">
                                    <div className="owner-progress-bar">
                                        <div className="owner-progress-fill"></div>
                                    </div>
                                    <p>Crawling menu pages with JS rendering... This may take 60-90 seconds for large sites.</p>
                                </div>
                            )}

                            {importError && <p className="owner-error">{importError}</p>}

                            {importedMenu && (
                                <div className="owner-extracted">
                                    <div className="owner-extracted-header">
                                        <h4>✅ Extracted: {importedMenu.restaurant_name || "Menu"}</h4>
                                        <span className="owner-extracted-stats">
                                            {importedMenu.pages_scraped > 1 && `${importedMenu.pages_scraped} pages · `}
                                            {importedMenu.categories?.length || 0} categories · {importedMenu.categories?.reduce((s, c) => s + (c.items?.length || 0), 0) || 0} items
                                        </span>
                                    </div>

                                    <div className="owner-edit-hint">✏️ Edit names, descriptions, and prices below. Use "+ Add Item" to add items manually.</div>

                                    <div className="owner-menu-preview">
                                        {importedMenu.categories?.map((cat, ci) => (
                                            <div key={ci} className="owner-menu-category">
                                                <div className="owner-cat-header">
                                                    <input
                                                        className="owner-cat-name-input"
                                                        value={cat.name}
                                                        onChange={(e) => updateCategoryName(ci, e.target.value)}
                                                    />
                                                    <span className="owner-item-count">{cat.items?.length || 0}</span>
                                                </div>
                                                {cat.items?.map((item, ii) => (
                                                    <div key={ii} className="owner-menu-item-row">
                                                        <div className="owner-item-fields">
                                                            <input className="owner-item-name" value={item.name} onChange={(e) => updateItem(ci, ii, "name", e.target.value)} placeholder="Item name" />
                                                            <input className="owner-item-desc" value={item.description || ""} onChange={(e) => updateItem(ci, ii, "description", e.target.value)} placeholder="Description" />
                                                        </div>
                                                        <div className="owner-item-price-group">
                                                            <span className="owner-dollar">$</span>
                                                            <input className="owner-item-price" type="number" step="0.01" value={item.price || 0} onChange={(e) => updateItem(ci, ii, "price", e.target.value)} />
                                                            <button className="owner-item-delete" onClick={() => deleteItem(ci, ii)}>✕</button>
                                                        </div>
                                                    </div>
                                                ))}
                                                <button className="owner-add-item-btn" onClick={() => addItem(ci)}>+ Add Item</button>
                                            </div>
                                        ))}
                                        <button className="owner-add-cat-btn" onClick={addCategory}>+ Add Category</button>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Sticky footer with save button — always visible */}
                        {importedMenu && (
                            <div className="owner-modal-footer">
                                <button className="owner-save-btn" onClick={handleSaveMenu} disabled={saveStatus === "saving"}>
                                    {saveStatus === "saving" ? "⏳ Saving..." : saveStatus === "saved" ? "✅ Saved Successfully!" : "💾 Save Menu to Restaurant"}
                                </button>
                                {saveStatus === "error" && <span style={{ color: "#fca5a5", fontSize: "0.85rem" }}>Failed to save. Try again.</span>}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
